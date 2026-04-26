"""Unit tests for LiveReasoningPublisher.

Run: pytest backend/voice_agent/test_live_reasoning.py -v
"""

import asyncio
import json
import logging
import unittest
from unittest.mock import AsyncMock, MagicMock

from backend.voice_agent.live_reasoning import (
    DATA_TOPIC,
    MAX_MESSAGE_BYTES,
    MAX_PROGRESS_QUEUE,
    LiveReasoningPublisher,
)


def _make_room_mock() -> MagicMock:
    """Build a Room mock with an awaitable publish_data on local_participant."""
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock(return_value=None)
    return room


def _captured_payloads(room: MagicMock) -> list[dict]:
    """Decode every JSON payload that publish_data received."""
    return [
        json.loads(call.args[0].decode("utf-8"))
        for call in room.local_participant.publish_data.call_args_list
    ]


class TestPublishSession(unittest.IsolatedAsyncioTestCase):
    async def test_session_event_shape(self):
        room = _make_room_mock()
        pub = LiveReasoningPublisher(room)
        await pub.publish_session(
            call_id="abc-123",
            arm="sally_warm",
            personality="sally_warm",
            forced=False,
        )
        payloads = _captured_payloads(room)
        assert len(payloads) == 1
        assert payloads[0] == {
            "type": "session",
            "call_id": "abc-123",
            "arm": "sally_warm",
            "personality": "sally_warm",
            "forced": False,
        }

    async def test_session_uses_reliable_and_topic(self):
        room = _make_room_mock()
        pub = LiveReasoningPublisher(room)
        await pub.publish_session(
            call_id="x", arm="sally_direct", personality="sally_direct", forced=True
        )
        kwargs = room.local_participant.publish_data.call_args.kwargs
        assert kwargs["reliable"] is True
        assert kwargs["topic"] == DATA_TOPIC


class TestPublishTurn(unittest.IsolatedAsyncioTestCase):
    async def test_normal_turn_sends_one_publish(self):
        room = _make_room_mock()
        pub = LiveReasoningPublisher(room)
        turn = {
            "turn_index": 1,
            "phase": "CONNECTION",
            "user_text": "hello",
            "sally_text": "hi there",
            "thought_log": {"trace": "small"},
        }
        await pub.publish_turn(turn)
        assert room.local_participant.publish_data.call_count == 1
        payload = _captured_payloads(room)[0]
        assert payload["type"] == "turn"
        assert payload["turn_index"] == 1
        assert payload["thought_log"] == {"trace": "small"}

    async def test_oversize_thought_log_is_stripped(self):
        room = _make_room_mock()
        pub = LiveReasoningPublisher(room)
        # Build a thought_log large enough to push the JSON over MAX_MESSAGE_BYTES
        big_blob = "x" * (MAX_MESSAGE_BYTES + 1000)
        turn = {
            "turn_index": 7,
            "phase": "CONSEQUENCE",
            "user_text": "ok",
            "sally_text": "alright",
            "thought_log": {"huge_field": big_blob},
        }
        with self.assertLogs("sally.live_reasoning", level="WARNING") as cm:
            await pub.publish_turn(turn)

        payload = _captured_payloads(room)[0]
        assert payload["thought_log"] == {"_truncated": True}
        assert any("stripping thought_log" in line for line in cm.output)
        # Verify the stripped payload is actually under the cap
        encoded = json.dumps(payload).encode("utf-8")
        assert len(encoded) < MAX_MESSAGE_BYTES

    async def test_turn_uses_reliable_kind(self):
        room = _make_room_mock()
        pub = LiveReasoningPublisher(room)
        await pub.publish_turn({"turn_index": 1, "phase": "CONNECTION"})
        kwargs = room.local_participant.publish_data.call_args.kwargs
        assert kwargs["reliable"] is True

    async def test_publish_failure_is_swallowed(self):
        """The runner must never see a publish exception."""
        room = _make_room_mock()
        room.local_participant.publish_data = AsyncMock(side_effect=RuntimeError("boom"))
        pub = LiveReasoningPublisher(room)
        # Must not raise
        await pub.publish_turn({"turn_index": 1, "phase": "CONNECTION"})

    async def test_local_participant_none_does_not_crash(self):
        room = MagicMock()
        room.local_participant = None
        pub = LiveReasoningPublisher(room)
        # Must not raise
        await pub.publish_turn({"turn_index": 1, "phase": "CONNECTION"})
        await pub.publish_session(call_id="c", arm="a", personality="a", forced=False)


class TestPublishProgress(unittest.IsolatedAsyncioTestCase):
    async def test_progress_event_shape(self):
        room = _make_room_mock()
        pub = LiveReasoningPublisher(room)
        await pub.publish_progress("engine", "Sally is thinking…")
        payload = _captured_payloads(room)[0]
        assert payload == {
            "type": "progress",
            "stage": "engine",
            "detail": "Sally is thinking…",
        }

    async def test_progress_without_detail(self):
        room = _make_room_mock()
        pub = LiveReasoningPublisher(room)
        await pub.publish_progress("asr")
        payload = _captured_payloads(room)[0]
        assert payload == {"type": "progress", "stage": "asr"}
        assert "detail" not in payload

    async def test_progress_uses_lossy_kind(self):
        room = _make_room_mock()
        pub = LiveReasoningPublisher(room)
        await pub.publish_progress("tts")
        kwargs = room.local_participant.publish_data.call_args.kwargs
        assert kwargs["reliable"] is False

    async def test_progress_drops_when_queue_full(self):
        """When MAX_PROGRESS_QUEUE events are already in flight, new
        progress events should be dropped silently."""
        room = _make_room_mock()
        pub = LiveReasoningPublisher(room)

        # Force the queue depth to the limit. The publisher tracks depth
        # internally; we simulate by setting the counter directly.
        pub._progress_queue_depth = MAX_PROGRESS_QUEUE

        await pub.publish_progress("engine")

        # No publish_data call should have been made for the dropped event.
        assert room.local_participant.publish_data.call_count == 0

    async def test_progress_queue_depth_recovers_after_send(self):
        room = _make_room_mock()
        pub = LiveReasoningPublisher(room)
        await pub.publish_progress("engine")
        # After publish completes, depth should be back to 0
        assert pub._progress_queue_depth == 0


class TestModuleConstants(unittest.TestCase):
    def test_max_message_bytes_sane(self):
        # Should be well below LiveKit's per-message ceiling (~1MB)
        assert 10_000 < MAX_MESSAGE_BYTES < 200_000

    def test_data_topic_is_namespaced(self):
        assert DATA_TOPIC.startswith("sally.")


if __name__ == "__main__":
    unittest.main()

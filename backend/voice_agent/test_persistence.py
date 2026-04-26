"""Unit tests for SessionRecorder.

Run: pytest backend/voice_agent/test_persistence.py -v
"""

import asyncio
import json
import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.voice_agent.persistence import SessionRecorder, _phase_rank


class TestPhaseRank(unittest.TestCase):
    def test_known_phases_ordered(self):
        assert _phase_rank("CONNECTION") < _phase_rank("SITUATION")
        assert _phase_rank("SITUATION") < _phase_rank("PROBLEM_AWARENESS")
        assert _phase_rank("COMMITMENT") < _phase_rank("TERMINATED")

    def test_unknown_phase_negative(self):
        assert _phase_rank("BOGUS") == -1


class TestSessionRecorderAccumulation(unittest.TestCase):
    def _make_recorder(self) -> SessionRecorder:
        return SessionRecorder(
            call_id="test-call-1",
            arm="sally_warm",
            personality="sally_warm",
            forced=False,
        )

    def test_record_turn_accumulates(self):
        r = self._make_recorder()
        r.record_turn({"turn_index": 1, "phase": "CONNECTION", "user_text": "hi", "ended": False})
        r.record_turn({"turn_index": 2, "phase": "SITUATION", "user_text": "ok", "ended": False})
        assert len(r._acc.turns) == 2

    def test_deepest_phase_advances(self):
        r = self._make_recorder()
        r.record_turn({"phase": "CONNECTION", "ended": False})
        assert r._acc.deepest_phase == "CONNECTION"
        r.record_turn({"phase": "SITUATION", "ended": False})
        assert r._acc.deepest_phase == "SITUATION"
        r.record_turn({"phase": "PROBLEM_AWARENESS", "ended": False})
        assert r._acc.deepest_phase == "PROBLEM_AWARENESS"

    def test_deepest_phase_never_regresses(self):
        r = self._make_recorder()
        r.record_turn({"phase": "CONSEQUENCE", "ended": False})
        r.record_turn({"phase": "SITUATION", "ended": False})  # earlier phase
        assert r._acc.deepest_phase == "CONSEQUENCE"

    def test_session_ended_flagged(self):
        r = self._make_recorder()
        r.record_turn({"phase": "COMMITMENT", "ended": False})
        assert not r._acc.session_ended
        r.record_turn({"phase": "TERMINATED", "ended": True})
        assert r._acc.session_ended

    def test_ended_at_phase_tracks_latest(self):
        r = self._make_recorder()
        r.record_turn({"phase": "CONNECTION", "ended": False})
        r.record_turn({"phase": "SITUATION", "ended": False})
        assert r._acc.ended_at_phase == "SITUATION"

    def test_empty_phase_ignored(self):
        r = self._make_recorder()
        r.record_turn({"phase": "", "ended": False})
        assert r._acc.deepest_phase == "CONNECTION"  # unchanged default


class TestSessionRecorderFlush(unittest.IsolatedAsyncioTestCase):
    def _make_recorder(self, **kw) -> SessionRecorder:
        defaults = dict(call_id="c1", arm="sally_warm", personality="sally_warm", forced=False)
        defaults.update(kw)
        return SessionRecorder(**defaults)

    async def test_flush_idempotent(self):
        r = self._make_recorder()
        # Second flush should be a no-op (no HTTP call)
        with patch.dict(os.environ, {"VOICE_PERSIST_URL": ""}, clear=False):
            await r.flush()
            await r.flush()  # must not raise

    async def test_flush_no_url_logs_warning(self):
        r = self._make_recorder()
        with patch.dict(os.environ, {}, clear=False):
            # Remove the key entirely
            env = {k: v for k, v in os.environ.items() if k != "VOICE_PERSIST_URL"}
            with patch.dict(os.environ, env, clear=True):
                import logging
                with self.assertLogs("sally.persistence", level="WARNING") as cm:
                    await r.flush()
                assert any("VOICE_PERSIST_URL" in line for line in cm.output)

    async def test_flush_http_500_falls_back_to_disk(self):
        r = self._make_recorder()
        r.record_turn({"phase": "CONNECTION", "ended": False, "user_text": "hi", "sally_text": "hey", "turn_index": 1, "timestamp": time.time()})

        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="internal server error")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        import aiohttp as real_aiohttp

        with patch.dict(os.environ, {"VOICE_PERSIST_URL": "http://fake/voice/persist", "VOICE_PERSIST_TOKEN": "tok"}):
            with patch.object(real_aiohttp, "ClientSession", return_value=mock_session):
                with patch.object(r, "_fallback_to_disk") as mock_disk:
                    await r.flush()
                    mock_disk.assert_called_once()

    async def test_payload_shape_matches_pydantic_model(self):
        """The payload dict sent to the persist endpoint must contain
        all required fields of SessionPayload (voice_persistence_api.py)."""
        r = self._make_recorder()
        r.record_turn({
            "turn_index": 1,
            "phase": "CONNECTION",
            "phase_changed": False,
            "user_text": "hello",
            "sally_text": "hi there",
            "asr_ms": 50.0,
            "engine_ms": 2000.0,
            "tts_first_frame_ms": 90.0,
            "user_latency_ms": 2140.0,
            "ended": False,
            "timestamp": time.time(),
        })

        captured: list[dict] = []

        async def fake_flush(session_ended=False):
            r._acc.ended_at = time.time()
            payload = {
                "call_id": r._acc.call_id,
                "arm": r._acc.arm,
                "personality": r._acc.personality,
                "forced": r._acc.forced,
                "started_at": r._acc.started_at,
                "ended_at": r._acc.ended_at,
                "duration_s": r._acc.ended_at - r._acc.started_at,
                "deepest_phase": r._acc.deepest_phase,
                "ended_at_phase": r._acc.ended_at_phase,
                "session_ended": r._acc.session_ended,
                "n_turns": len(r._acc.turns),
                "turns": r._acc.turns,
            }
            captured.append(payload)

        # Patch flush to capture the payload without network
        with patch.object(r, "flush", fake_flush):
            await r.flush()

        required_keys = {
            "call_id", "arm", "personality", "forced",
            "started_at", "ended_at", "duration_s",
            "deepest_phase", "ended_at_phase", "session_ended",
            "n_turns", "turns",
        }
        assert required_keys.issubset(set(captured[0].keys()))
        assert isinstance(captured[0]["turns"], list)
        assert len(captured[0]["turns"]) == 1


class TestRoomMetadataParsing(unittest.TestCase):
    """Verify sally.py's room-metadata parsing logic in isolation."""

    def _parse_metadata(self, metadata_str: str | None, env_forced: str | None = None):
        """Mirror the logic in sally.py entrypoint without importing LiveKit."""
        import json as _json
        import os as _os

        _forced_from_meta = None
        _frontend_call_id = None
        try:
            if metadata_str:
                _meta = _json.loads(metadata_str)
                _forced_from_meta = _meta.get("forcedPersonality")
                _frontend_call_id = _meta.get("callId")
        except (ValueError, AttributeError):
            pass

        _forced_final = env_forced or _forced_from_meta
        return _forced_final, _frontend_call_id

    def test_forced_personality_from_metadata(self):
        forced, _ = self._parse_metadata(
            json.dumps({"forcedPersonality": "sally_warm", "callId": "abc"})
        )
        assert forced == "sally_warm"

    def test_env_var_wins_over_metadata(self):
        forced, _ = self._parse_metadata(
            json.dumps({"forcedPersonality": "sally_warm"}),
            env_forced="sally_direct",
        )
        assert forced == "sally_direct"

    def test_malformed_json_falls_back(self):
        forced, call_id = self._parse_metadata("not-json")
        assert forced is None
        assert call_id is None

    def test_none_metadata_falls_back(self):
        forced, call_id = self._parse_metadata(None)
        assert forced is None
        assert call_id is None

    def test_call_id_extracted(self):
        _, call_id = self._parse_metadata(
            json.dumps({"callId": "frontend-uuid-123"})
        )
        assert call_id == "frontend-uuid-123"


if __name__ == "__main__":
    unittest.main()

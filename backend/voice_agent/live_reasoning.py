"""Live reasoning publisher.

Fire-and-forget broadcast of turn metadata + reasoning blobs to the
participant browser via the LiveKit data channel.

Runs alongside SessionRecorder (Phase 1). DB persistence remains the
source of truth; this channel is for the live UI only and must never
block the voice runner.

Spec: VOICE_TAB_PHASE_2.md §6.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from livekit import rtc

log = logging.getLogger("sally.live_reasoning")

# LiveKit's per-message ceiling is generous (~1 MB), but real-world reliable
# delivery degrades well before that. 60 KB keeps each message under a single
# WebRTC SCTP datagram on most paths and gives plenty of headroom for the
# thought_log blob in normal turns. Long sessions blow this for any one turn
# only when the engine's reasoning chain is unusually verbose; in that case
# we strip thought_log and rely on the post-hoc viewer for full detail.
MAX_MESSAGE_BYTES = 60_000

# Cap on concurrent in-flight progress events. Progress is best-effort —
# turn events are reliable, so dropping a "thinking…" hint is harmless.
MAX_PROGRESS_QUEUE = 5

# Topic so the frontend hook can filter — the data channel is shared with
# any future LiveKit feature that publishes data on the same room.
DATA_TOPIC = "sally.reasoning"


class LiveReasoningPublisher:
    """Owns a reference to the LiveKit Room. Caller invokes `publish_turn`
    for each completed turn (after metrics are emitted), and optionally
    `publish_progress` for in-flight stage hints.
    """

    def __init__(self, room: rtc.Room) -> None:
        self._room = room
        self._progress_queue_depth = 0

    async def publish_session(
        self,
        *,
        call_id: str,
        arm: str,
        personality: str,
        forced: bool,
    ) -> None:
        """Called once at the start of a call, after greeting fires."""
        await self._send(
            {
                "type": "session",
                "call_id": call_id,
                "arm": arm,
                "personality": personality,
                "forced": forced,
            },
            reliable=True,
        )

    async def publish_turn(self, turn_dict: dict[str, Any]) -> None:
        """Publish a completed turn. Strips thought_log if oversized."""
        payload = {"type": "turn", **turn_dict}
        encoded = json.dumps(payload).encode("utf-8")

        if len(encoded) > MAX_MESSAGE_BYTES:
            log.warning(
                "Turn %s payload %d bytes exceeds %d; stripping thought_log",
                turn_dict.get("turn_index"),
                len(encoded),
                MAX_MESSAGE_BYTES,
            )
            stripped = {**payload, "thought_log": {"_truncated": True}}
            await self._send(stripped, reliable=True)
        else:
            await self._send(payload, reliable=True)

    async def publish_progress(self, stage: str, detail: Optional[str] = None) -> None:
        """Best-effort stage hint. Drops if more than MAX_PROGRESS_QUEUE
        events are already in flight — the live UI can survive missing
        progress hints; what it can't survive is a queued progress event
        delaying a turn delivery."""
        if self._progress_queue_depth >= MAX_PROGRESS_QUEUE:
            return
        self._progress_queue_depth += 1
        try:
            payload: dict[str, Any] = {"type": "progress", "stage": stage}
            if detail:
                payload["detail"] = detail
            await self._send(payload, reliable=False)
        finally:
            self._progress_queue_depth -= 1

    async def _send(self, payload: dict[str, Any], *, reliable: bool) -> None:
        """Encode + publish_data. Swallows all exceptions — the runner must
        never observe a publish failure. The DB write is the safety net."""
        try:
            local = getattr(self._room, "local_participant", None)
            if local is None:
                # Room not yet connected, or shutting down. Skip silently.
                return
            data = json.dumps(payload).encode("utf-8")
            await local.publish_data(data, reliable=reliable, topic=DATA_TOPIC)
        except Exception as e:  # noqa: BLE001
            log.debug("publish failed (non-fatal): %s", e)

import { useEffect, useRef, useState } from "react";
import { Room, RoomEvent } from "livekit-client";

// Mirrors the backend payload from backend/voice_agent/live_reasoning.py.
// The `turn` shape matches TurnMetrics fields plus a `type` discriminator.

export interface LiveSessionEvent {
  type: "session";
  call_id: string;
  arm: string;
  personality: string;
  forced: boolean;
}

export interface LiveTurnEvent {
  type: "turn";
  turn_index: number;
  phase: string;
  phase_changed: boolean;
  user_text: string;
  sally_text: string;
  asr_ms: number | null;
  engine_dispatch_ms: number | null;
  engine_ms: number | null;
  tts_first_frame_ms: number | null;
  user_latency_ms: number | null;
  utterance_duration_ms: number | null;
  l1_model: string | null;
  user_emotion: string | null;
  tts_tier: string | null;
  audio_tags_used: string[] | null;
  expression_decorated: boolean;
  tag_director_used: boolean;
  tag_director_latency_ms: number | null;
  tag_director_fallback: string | null;
  thought_log: Record<string, unknown> | null;
  timestamp: number;
  ended: boolean;
}

export interface LiveProgressEvent {
  type: "progress";
  stage: "asr" | "engine" | "tts";
  detail?: string;
}

export interface LiveReasoningState {
  session: LiveSessionEvent | null;
  turns: LiveTurnEvent[];
  currentProgress: LiveProgressEvent | null;
}

const DATA_TOPIC = "sally.reasoning";

/**
 * Subscribes to the LiveKit data channel for the given Room and surfaces
 * session, turn, and progress events as React state.
 *
 * The Room is passed as a prop (not via useRoomContext) because Phase 1
 * placed the ReasoningPanel as a sibling of <LiveKitRoom>, not inside it.
 * VoicePage uses a small bridge component inside <LiveKitRoom> to lift the
 * Room instance to its own state, then forwards it to this hook.
 *
 * Pass `null` for `room` when no call is active — the hook becomes a no-op.
 */
export function useLiveReasoning(room: Room | null): LiveReasoningState {
  const [session, setSession] = useState<LiveSessionEvent | null>(null);
  const [turns, setTurns] = useState<LiveTurnEvent[]>([]);
  const [progress, setProgress] = useState<LiveProgressEvent | null>(null);

  // Use a ref so the data handler closure always reads the latest list,
  // not a stale snapshot from when the effect was first set up.
  const turnsRef = useRef<LiveTurnEvent[]>([]);

  useEffect(() => {
    if (!room) {
      // Reset state when the room goes away (call ended / never started).
      setSession(null);
      setTurns([]);
      setProgress(null);
      turnsRef.current = [];
      return;
    }

    const handler = (
      payload: Uint8Array,
      _participant?: unknown,
      _kind?: unknown,
      topic?: string
    ) => {
      if (topic !== DATA_TOPIC) return;
      let evt: any;
      try {
        evt = JSON.parse(new TextDecoder().decode(payload));
      } catch {
        return;
      }

      if (!evt || typeof evt !== "object") return;

      if (evt.type === "session") {
        setSession(evt as LiveSessionEvent);
      } else if (evt.type === "turn") {
        const incoming = evt as LiveTurnEvent;
        // Idempotent on turn_index — if the same index arrives twice
        // (rare, but possible if the publisher retries), replace rather
        // than duplicate.
        const idx = turnsRef.current.findIndex(
          (t) => t.turn_index === incoming.turn_index
        );
        if (idx >= 0) {
          const next = turnsRef.current.slice();
          next[idx] = incoming;
          turnsRef.current = next;
        } else {
          // Insert in sorted order so out-of-order delivery still renders
          // correctly. In practice turns arrive in order, but the panel
          // shouldn't trust that.
          const next = [...turnsRef.current, incoming].sort(
            (a, b) => a.turn_index - b.turn_index
          );
          turnsRef.current = next;
        }
        setTurns(turnsRef.current);
        // Clear any pending progress hint — the turn it referred to is done.
        setProgress(null);
      } else if (evt.type === "progress") {
        setProgress(evt as LiveProgressEvent);
      }
    };

    room.on(RoomEvent.DataReceived, handler);
    return () => {
      room.off(RoomEvent.DataReceived, handler);
    };
  }, [room]);

  return { session, turns, currentProgress: progress };
}

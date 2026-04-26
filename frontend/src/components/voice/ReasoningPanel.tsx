import { useEffect, useState } from "react";
import type { Room } from "livekit-client";
import { getVoiceSession, type VoiceSessionDetail, type VoiceTurn } from "../../lib/voiceApi";
import {
  useLiveReasoning,
  type LiveTurnEvent,
  type LiveProgressEvent,
} from "../../lib/useLiveReasoning";

// Either source of turns can be rendered by TurnRow. The shape of
// LiveTurnEvent is a superset of VoiceTurn for the fields we display.
type AnyTurn = VoiceTurn | LiveTurnEvent;

interface Props {
  callId: string | null;
  live: boolean;
  room?: Room | null;  // required when live=true
}

export function ReasoningPanel({ callId, live, room }: Props) {
  if (live) {
    return <LiveView room={room ?? null} />;
  }
  return <PostHocView callId={callId} />;
}

// ---------------------------------------------------------------------------
// Live mode — subscribes to the LiveKit data channel via useLiveReasoning
// ---------------------------------------------------------------------------

function LiveView({ room }: { room: Room | null }) {
  const { session, turns, currentProgress } = useLiveReasoning(room);

  return (
    <div className="p-4 space-y-3 text-sm">
      <div>
        <h2 className="font-semibold">Live reasoning</h2>
        {session ? (
          <p className="text-xs text-zinc-500 mt-0.5">
            Arm: {session.arm}
            {session.forced ? " (forced)" : ""}
          </p>
        ) : (
          <p className="text-xs text-zinc-600 mt-0.5">Connecting…</p>
        )}
      </div>

      {turns.length === 0 && !currentProgress && (
        <p className="text-xs text-zinc-500">Waiting for the first turn…</p>
      )}

      {turns.map((turn) => (
        <TurnRow key={turn.turn_index} turn={turn} />
      ))}

      {currentProgress && <ProgressIndicator progress={currentProgress} />}
    </div>
  );
}

function ProgressIndicator({ progress }: { progress: LiveProgressEvent }) {
  const label = progress.detail ?? `Stage: ${progress.stage}`;
  return (
    <div className="text-xs text-zinc-400 italic animate-pulse pl-3">
      {label}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Post-hoc mode — Phase 1 unchanged, fetches from /voice/sessions/{id}
// ---------------------------------------------------------------------------

function PostHocView({ callId }: { callId: string | null }) {
  const [data, setData] = useState<VoiceSessionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!callId) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    getVoiceSession(callId)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [callId]);

  if (!callId) {
    return (
      <div className="p-4 text-zinc-500">
        <p className="text-sm font-medium">Reasoning panel</p>
        <p className="mt-2 text-xs">Start a call to see Sally's reasoning here.</p>
      </div>
    );
  }

  if (loading) {
    return <div className="p-4 text-zinc-500 text-sm">Loading…</div>;
  }

  if (error) {
    return (
      <div className="p-4 text-red-400 text-xs">
        Failed to load session: {error}
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="p-4 space-y-3 text-sm">
      <div>
        <h2 className="font-semibold">
          Session {data.call_id.slice(0, 8)}…
        </h2>
        <p className="text-xs text-zinc-500 mt-0.5">
          Arm: {data.arm}
          {data.forced ? " (forced)" : ""} &middot; {data.n_turns} turns
        </p>
      </div>
      {data.turns.map((turn) => (
        <TurnRow key={turn.turn_index} turn={turn} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared turn renderer — one component for both live and post-hoc views
// ---------------------------------------------------------------------------

function TurnRow({ turn }: { turn: AnyTurn }) {
  return (
    <div className="border-l-2 border-zinc-700 pl-3 py-1">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] text-zinc-500">
          Turn {turn.turn_index} &mdash; {turn.phase}
          {turn.phase_changed ? (
            <span className="ml-1 text-green-500">(phase change)</span>
          ) : null}
        </p>
        {turn.user_latency_ms != null && (
          <p className="text-[10px] text-zinc-600 shrink-0">
            {Math.round(turn.user_latency_ms)}ms
            {turn.tts_tier ? ` · ${turn.tts_tier}` : ""}
          </p>
        )}
      </div>
      <p className="text-xs mt-1">
        <span className="text-zinc-400">User: </span>
        {turn.user_text}
      </p>
      <p className="text-xs mt-0.5">
        <span className="text-zinc-400">Sally: </span>
        {turn.sally_text}
      </p>
      {turn.audio_tags_used && turn.audio_tags_used.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {turn.audio_tags_used.map((tag: string) => (
            <span
              key={tag}
              className="text-[10px] bg-orange-900/40 text-orange-400 px-1.5 py-0.5 rounded"
            >
              {tag}
            </span>
          ))}
        </div>
      )}
      {turn.thought_log && (
        <details className="mt-1">
          <summary className="text-[11px] cursor-pointer text-zinc-500 hover:text-zinc-300">
            Reasoning
          </summary>
          <pre className="mt-1 p-2 bg-zinc-900 rounded text-[10px] overflow-x-auto max-h-48 whitespace-pre-wrap">
            {JSON.stringify(turn.thought_log, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

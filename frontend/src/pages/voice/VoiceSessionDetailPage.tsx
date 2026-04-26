import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getVoiceSession, type VoiceSessionDetail, type VoiceTurn } from "../../lib/voiceApi";

function fmt(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

function ms(v: number | null) {
  if (v == null) return "—";
  return `${Math.round(v)}ms`;
}

function LatencyRow({ label, value }: { label: string; value: number | null }) {
  return (
    <span className="inline-flex items-center gap-1 bg-zinc-800 px-2 py-0.5 rounded text-[10px] text-zinc-400">
      {label}: {ms(value)}
    </span>
  );
}

function TurnCard({ turn }: { turn: VoiceTurn }) {
  return (
    <div className="border border-zinc-800 rounded-lg p-4 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-zinc-500">
          Turn {turn.turn_index} &mdash; {turn.phase}
        </span>
        {turn.phase_changed && (
          <span className="text-[10px] bg-blue-900/50 text-blue-400 px-1.5 py-0.5 rounded">
            phase change
          </span>
        )}
        {turn.tts_tier && turn.tts_tier !== "fast" && (
          <span className="text-[10px] bg-purple-900/50 text-purple-400 px-1.5 py-0.5 rounded">
            {turn.tts_tier}
          </span>
        )}
      </div>

      <div className="space-y-1 text-sm">
        <p>
          <span className="text-zinc-500 text-xs">User: </span>
          {turn.user_text}
        </p>
        <p>
          <span className="text-zinc-500 text-xs">Sally: </span>
          {turn.sally_text}
        </p>
      </div>

      {turn.audio_tags_used && turn.audio_tags_used.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {turn.audio_tags_used.map((tag) => (
            <span
              key={tag}
              className="text-[10px] bg-orange-900/40 text-orange-400 px-2 py-0.5 rounded"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        <LatencyRow label="user" value={turn.user_latency_ms} />
        <LatencyRow label="asr" value={turn.asr_ms} />
        <LatencyRow label="engine" value={turn.engine_ms} />
        <LatencyRow label="tts" value={turn.tts_first_frame_ms} />
        {turn.tag_director_used && (
          <LatencyRow label="director" value={turn.tag_director_latency_ms} />
        )}
      </div>

      {turn.thought_log && (
        <details>
          <summary className="text-[11px] text-zinc-500 cursor-pointer hover:text-zinc-300">
            Reasoning
          </summary>
          <pre className="mt-1 p-2 bg-zinc-950 rounded text-[10px] overflow-x-auto max-h-64 whitespace-pre-wrap">
            {JSON.stringify(turn.thought_log, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

export function VoiceSessionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [session, setSession] = useState<VoiceSessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    getVoiceSession(id)
      .then(setSession)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="p-6 text-zinc-500 text-sm">Loading…</div>;
  if (error) return <div className="p-6 text-red-400 text-sm">{error}</div>;
  if (!session) return null;

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link
          to="/voice/sessions"
          className="text-zinc-500 hover:text-zinc-300 text-sm"
        >
          &larr; Sessions
        </Link>
      </div>

      {/* Session metadata */}
      <div className="bg-zinc-900 rounded-lg p-4 space-y-1 text-sm">
        <div className="flex items-center gap-2">
          <span className="font-medium">
            {session.arm}
            {session.forced && (
              <span className="ml-1 text-xs text-amber-500">(forced)</span>
            )}
          </span>
        </div>
        <p className="text-zinc-500 text-xs">
          Call ID: {session.call_id}
        </p>
        <p className="text-zinc-500 text-xs">
          Started: {fmt(session.started_at)}
          {session.ended_at &&
            ` · Ended: ${fmt(session.ended_at)}`}
        </p>
        <div className="flex gap-3 text-xs text-zinc-400 pt-1">
          <span>{session.n_turns} turns</span>
          {session.deepest_phase && (
            <span>Deepest phase: {session.deepest_phase}</span>
          )}
          {session.duration_s != null && (
            <span>
              Duration: {Math.floor(session.duration_s / 60)}m{" "}
              {Math.round(session.duration_s % 60)}s
            </span>
          )}
        </div>
      </div>

      {/* Download raw JSON */}
      <div className="flex justify-end">
        <button
          onClick={() => {
            const blob = new Blob([JSON.stringify(session, null, 2)], {
              type: "application/json",
            });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `session-${session.call_id.slice(0, 8)}.json`;
            a.click();
            URL.revokeObjectURL(url);
          }}
          className="text-xs text-zinc-500 hover:text-zinc-300 underline"
        >
          Download JSON
        </button>
      </div>

      {/* Turns */}
      {session.turns.length === 0 ? (
        <p className="text-zinc-500 text-sm">No turns recorded yet.</p>
      ) : (
        <div className="space-y-3">
          {session.turns.map((t) => (
            <TurnCard key={t.turn_index} turn={t} />
          ))}
        </div>
      )}
    </div>
  );
}

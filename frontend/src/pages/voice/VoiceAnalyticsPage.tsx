import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getVoiceAnalytics, type VoiceAnalytics, type ArmAnalytics } from "../../lib/voiceApi";

const PHASE_ORDER = [
  "CONNECTION",
  "SITUATION",
  "PROBLEM_AWARENESS",
  "SOLUTION_AWARENESS",
  "CONSEQUENCE",
  "OWNERSHIP",
  "COMMITMENT",
  "TERMINATED",
];

function ms(v: number | null) {
  if (v == null) return "—";
  return `${Math.round(v)}ms`;
}

function pct(n: number) {
  return `${(n * 100).toFixed(1)}%`;
}

function ArmCard({ arm, data }: { arm: string; data: ArmAnalytics }) {
  const phases = PHASE_ORDER.filter((p) => data.deepest_phase_distribution[p]);

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{arm}</h2>
        <span className="text-sm text-zinc-400">
          {data.total_sessions} sessions
        </span>
      </div>

      {/* Latency table */}
      <div>
        <p className="text-xs text-zinc-500 mb-1.5">Latency</p>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-zinc-600 text-left">
              <th className="pr-3 pb-1">Metric</th>
              <th className="pr-3 pb-1">p50</th>
              <th className="pb-1">p95</th>
            </tr>
          </thead>
          <tbody className="text-zinc-400">
            <tr>
              <td className="pr-3">User latency</td>
              <td className="pr-3">{ms(data.latency.user_latency_p50_ms)}</td>
              <td>{ms(data.latency.user_latency_p95_ms)}</td>
            </tr>
            <tr>
              <td className="pr-3">Engine</td>
              <td className="pr-3">{ms(data.latency.engine_p50_ms)}</td>
              <td>{ms(data.latency.engine_p95_ms)}</td>
            </tr>
            <tr>
              <td className="pr-3">TTS first-frame</td>
              <td className="pr-3">{ms(data.latency.tts_first_frame_p50_ms)}</td>
              <td>{ms(data.latency.tts_first_frame_p95_ms)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Phase distribution */}
      {phases.length > 0 && (
        <div>
          <p className="text-xs text-zinc-500 mb-1.5">Deepest phase reached</p>
          <div className="space-y-1">
            {phases.map((p) => {
              const count = data.deepest_phase_distribution[p] ?? 0;
              const pctVal = data.total_sessions
                ? count / data.total_sessions
                : 0;
              return (
                <div key={p} className="flex items-center gap-2">
                  <span className="text-xs text-zinc-400 w-28 shrink-0">{p}</span>
                  <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-600 rounded-full"
                      style={{ width: `${pctVal * 100}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-zinc-500 w-8 text-right">
                    {count}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* TTS tier breakdown (emotive only) */}
      {Object.keys(data.tts_tier_counts).length > 1 && (
        <div>
          <p className="text-xs text-zinc-500 mb-1">TTS tier</p>
          <div className="flex gap-3 text-xs text-zinc-400">
            {Object.entries(data.tts_tier_counts).map(([tier, count]) => (
              <span key={tier}>
                {tier}: {count}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Top audio tags */}
      {data.top_audio_tags.length > 0 && (
        <div>
          <p className="text-xs text-zinc-500 mb-1.5">Top audio tags</p>
          <div className="flex flex-wrap gap-1.5">
            {data.top_audio_tags.slice(0, 8).map(({ tag, count }) => (
              <span
                key={tag}
                className="text-[10px] bg-orange-900/40 text-orange-400 px-2 py-0.5 rounded"
              >
                {tag} ×{count}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tag director (emotive only) */}
      {(data.tag_director.used_count > 0 || data.tag_director.fallback_count > 0) && (
        <div>
          <p className="text-xs text-zinc-500 mb-1">Tag director</p>
          <div className="text-xs text-zinc-400 space-y-0.5">
            <p>
              Used: {data.tag_director.used_count} turns &middot; Fallback:{" "}
              {data.tag_director.fallback_count} (
              {pct(data.tag_director.fallback_rate)})
            </p>
            <p>Latency p50: {ms(data.tag_director.latency_p50_ms)}</p>
          </div>
        </div>
      )}

      <p className="text-xs text-zinc-600">
        Avg turns: {data.avg_turns.toFixed(1)}
      </p>
    </div>
  );
}

export function VoiceAnalyticsPage() {
  const [analytics, setAnalytics] = useState<VoiceAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getVoiceAnalytics()
      .then(setAnalytics)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold">Voice Analytics</h1>
        <Link
          to="/voice/sessions"
          className="text-sm text-blue-400 hover:text-blue-300"
        >
          Sessions
        </Link>
      </div>

      {loading && <p className="text-zinc-500 text-sm">Loading…</p>}
      {error && <p className="text-red-400 text-sm">{error}</p>}

      {analytics && (
        <>
          <p className="text-xs text-zinc-600 mb-4">
            {analytics.total_sessions} total sessions
          </p>
          {Object.keys(analytics.arms).length === 0 ? (
            <p className="text-zinc-500 text-sm">No sessions recorded yet.</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {Object.entries(analytics.arms).map(([arm, data]) => (
                <ArmCard key={arm} arm={arm} data={data} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

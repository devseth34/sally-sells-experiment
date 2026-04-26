import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { listVoiceSessions, type VoiceSessionListItem } from "../../lib/voiceApi";

const ARMS = [
  { value: "", label: "All arms" },
  { value: "sally_warm", label: "sally_warm" },
  { value: "sally_confident", label: "sally_confident" },
  { value: "sally_direct", label: "sally_direct" },
  { value: "sally_emotive", label: "sally_emotive" },
];

function fmt(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

function dur(s: number | null) {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

export function VoiceSessionsPage() {
  const [params, setParams] = useSearchParams();
  const arm = params.get("arm") || "";
  const [sessions, setSessions] = useState<VoiceSessionListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    listVoiceSessions(arm || undefined)
      .then(setSessions)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [arm]);

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold">Voice Sessions</h1>
        <Link
          to="/voice/analytics"
          className="text-sm text-blue-400 hover:text-blue-300"
        >
          Analytics
        </Link>
      </div>

      <div className="mb-4">
        <select
          className="bg-zinc-800 text-white text-sm px-3 py-1.5 rounded-md border border-zinc-700"
          value={arm}
          onChange={(e) => {
            if (e.target.value) setParams({ arm: e.target.value });
            else setParams({});
          }}
        >
          {ARMS.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </select>
      </div>

      {loading && <p className="text-zinc-500 text-sm">Loading…</p>}
      {error && <p className="text-red-400 text-sm">{error}</p>}

      {!loading && !error && sessions.length === 0 && (
        <p className="text-zinc-500 text-sm">No sessions yet.</p>
      )}

      {!loading && sessions.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left border-b border-zinc-800 text-xs text-zinc-500">
              <th className="pb-2 pr-4">Started</th>
              <th className="pb-2 pr-4">Arm</th>
              <th className="pb-2 pr-4">Duration</th>
              <th className="pb-2 pr-4">Turns</th>
              <th className="pb-2 pr-4">Deepest Phase</th>
              <th className="pb-2"></th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr
                key={s.call_id}
                className="border-b border-zinc-900 hover:bg-zinc-900/40"
              >
                <td className="py-2 pr-4 text-zinc-400 text-xs">
                  {fmt(s.started_at)}
                </td>
                <td className="py-2 pr-4">
                  <span className="text-xs bg-zinc-800 px-2 py-0.5 rounded">
                    {s.arm}
                  </span>
                  {s.forced && (
                    <span className="ml-1 text-[10px] text-amber-500">forced</span>
                  )}
                </td>
                <td className="py-2 pr-4 text-zinc-400">{dur(s.duration_s)}</td>
                <td className="py-2 pr-4 text-zinc-400">{s.n_turns}</td>
                <td className="py-2 pr-4 text-zinc-400">
                  {s.deepest_phase ?? "—"}
                </td>
                <td className="py-2">
                  <Link
                    to={`/voice/sessions/${s.call_id}`}
                    className="text-blue-400 hover:text-blue-300 text-xs"
                  >
                    View
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

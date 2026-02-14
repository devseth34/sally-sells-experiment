import { useState, useEffect } from "react";
import { Header } from "../components/layout/Header.tsx";
import { Card, CardHeader, CardContent } from "../components/ui/index";
import { Badge } from "../components/ui/index";
import { getMetrics } from "../lib/api";
import { getPhaseLabel, getPhaseColor } from "../constants";
import type { MetricsResponse } from "../lib/api";

export function DashboardPage() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchMetrics = async () => {
    try {
      const data = await getMetrics();
      setMetrics(data);
      setError(null);
    } catch {
      setError("Cannot connect to backend. Is the server running?");
    }
  };

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="h-screen flex flex-col bg-zinc-950 text-white">
      <Header />
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-5xl mx-auto">
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-lg font-semibold">Dashboard</h1>
            <span className="text-[10px] text-zinc-600">Auto-refreshes every 10s</span>
          </div>

          {error && (
            <div className="mb-6 p-3 rounded-lg bg-red-900/20 border border-red-900/40 text-sm text-red-400">
              {error}
            </div>
          )}

          {!metrics && !error && (
            <div className="text-sm text-zinc-500">Loading metrics...</div>
          )}

          {metrics && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
                <MetricCard label="Total Sessions" value={metrics.total_sessions} />
                <MetricCard label="Active Now" value={metrics.active_sessions} highlight />
                <MetricCard label="Avg. Pre-Conviction" value={metrics.average_pre_conviction ? `${metrics.average_pre_conviction}/10` : "—"} />
                <MetricCard label="Avg. CDS" value={metrics.average_cds != null ? `${metrics.average_cds > 0 ? "+" : ""}${metrics.average_cds}` : "—"} highlight={metrics.average_cds != null && metrics.average_cds > 0} />
                <MetricCard label="Conversion Rate" value={`${metrics.conversion_rate}%`} />
              </div>

              <Card className="mb-6">
                <CardHeader>
                  <h2 className="text-sm font-medium text-zinc-300">Phase Distribution</h2>
                </CardHeader>
                <CardContent>
                  {Object.keys(metrics.phase_distribution).length === 0 ? (
                    <p className="text-sm text-zinc-600">No active sessions yet</p>
                  ) : (
                    <div className="space-y-3">
                      {Object.entries(metrics.phase_distribution).map(([phase, count]) => (
                        <div key={phase} className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full" style={{ background: getPhaseColor(phase) }} />
                            <span className="text-sm text-zinc-300">{getPhaseLabel(phase)}</span>
                          </div>
                          <span className="text-sm font-mono text-zinc-500">{count}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <h2 className="text-sm font-medium text-zinc-300">Drop-off Points</h2>
                </CardHeader>
                <CardContent>
                  {metrics.failure_modes.length === 0 ? (
                    <p className="text-sm text-zinc-600">No abandoned sessions yet</p>
                  ) : (
                    <div className="space-y-3">
                      {metrics.failure_modes.map(({ phase, count }) => {
                        const maxCount = Math.max(...metrics.failure_modes.map((f) => f.count));
                        return (
                          <div key={phase} className="space-y-1">
                            <div className="flex items-center justify-between">
                              <Badge>{getPhaseLabel(phase)}</Badge>
                              <span className="text-xs text-zinc-500">{count} session{count !== 1 ? "s" : ""}</span>
                            </div>
                            <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                              <div className="h-full rounded-full transition-all" style={{ width: `${(count / maxCount) * 100}%`, background: getPhaseColor(phase) }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>

              <div className="mt-6 grid grid-cols-3 gap-4">
                <Card><CardContent><div className="text-center"><p className="text-2xl font-semibold text-emerald-400">{metrics.completed_sessions}</p><p className="text-xs text-zinc-500 mt-1">Completed</p></div></CardContent></Card>
                <Card><CardContent><div className="text-center"><p className="text-2xl font-semibold text-amber-400">{metrics.active_sessions}</p><p className="text-xs text-zinc-500 mt-1">Active</p></div></CardContent></Card>
                <Card><CardContent><div className="text-center"><p className="text-2xl font-semibold text-red-400">{metrics.abandoned_sessions}</p><p className="text-xs text-zinc-500 mt-1">Abandoned</p></div></CardContent></Card>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value, highlight }: { label: string; value: string | number; highlight?: boolean }) {
  return (
    <Card>
      <CardContent>
        <p className="text-xs text-zinc-500 mb-1">{label}</p>
        <p className={`text-xl font-semibold ${highlight ? "text-emerald-400" : "text-white"}`}>{value}</p>
      </CardContent>
    </Card>
  );
}
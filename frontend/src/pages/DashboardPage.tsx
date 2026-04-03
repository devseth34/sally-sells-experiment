import { useState, useEffect } from "react";
import { Header } from "../components/layout/Header.tsx";
import { Card, CardHeader, CardContent } from "../components/ui/index";
import { Badge } from "../components/ui/index";
import { getMetrics, getTrends } from "../lib/api";
import { getPhaseLabel, getPhaseColor } from "../constants";
import type { MetricsResponse, TrendsResponse } from "../lib/api";
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from "recharts";

const ARM_DISPLAY: Record<string, string> = {
  sally_nepq: "Sally",
  hank_hypes: "Hank",
  ivy_informs: "Ivy",
  sally_hank_close: "Sally>Hank Close",
  sally_ivy_bridge: "Sally>Ivy Bridge",
  sally_empathy_plus: "Sally Empathy+",
  sally_direct: "Sally Direct",
  hank_structured: "Hank Structured",
};

const tooltipStyle = {
  contentStyle: { background: '#18181b', border: '1px solid #3f3f46', borderRadius: '8px' },
  labelStyle: { color: '#a1a1aa' },
};

function formatChartDate(dateStr: unknown): string {
  const s = String(dateStr ?? "");
  const d = new Date(s + "T00:00:00");
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function DashboardPage() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [trends, setTrends] = useState<TrendsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      const [metricsData, trendsData] = await Promise.all([
        getMetrics(),
        getTrends(),
      ]);
      setMetrics(metricsData);
      setTrends(trendsData);
      setError(null);
    } catch {
      setError("Cannot connect to backend. Is the server running?");
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  // Compute arm/channel totals from trends data
  const armTotals = { sally: 0, hank: 0, ivy: 0, web: 0, sms: 0 };
  if (trends) {
    for (const day of trends.sessions_by_day) {
      armTotals.sally += day.sally;
      armTotals.hank += day.hank;
      armTotals.ivy += day.ivy;
      armTotals.web += day.web;
      armTotals.sms += day.sms;
    }
  }

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
              {/* Top metric cards */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-4">
                <MetricCard label="Total Sessions" value={metrics.total_sessions} />
                <MetricCard label="Active Now" value={metrics.active_sessions} highlight />
                <MetricCard label="Avg. Pre-Conviction" value={metrics.average_pre_conviction ? `${metrics.average_pre_conviction}/10` : "—"} />
                <MetricCard label="Avg. CDS" value={metrics.average_cds != null ? `${metrics.average_cds > 0 ? "+" : ""}${metrics.average_cds}` : "—"} highlight={metrics.average_cds != null && metrics.average_cds > 0} />
                <MetricCard label="Conversion Rate" value={`${metrics.conversion_rate}%`} />
              </div>

              {/* Arm & channel breakdown */}
              {trends && (
                <div className="flex items-center gap-4 mb-8 text-xs text-zinc-500 flex-wrap">
                  <span className="text-blue-400">Sally: {armTotals.sally}</span>
                  <span className="text-rose-400">Hank: {armTotals.hank}</span>
                  <span className="text-zinc-400">Ivy: {armTotals.ivy}</span>
                  <span className="text-zinc-600">|</span>
                  <span>Web: {armTotals.web}</span>
                  <span>SMS: {armTotals.sms}</span>
                  <span className="text-zinc-700 text-[10px]">(last 30 days)</span>
                </div>
              )}

              {/* Chart 1: Sessions Over Time */}
              {trends && trends.sessions_by_day.length > 0 && (
                <Card className="mb-6">
                  <CardHeader><h2 className="text-sm font-medium text-zinc-300">Sessions Over Time</h2></CardHeader>
                  <CardContent>
                    <ResponsiveContainer width="100%" height={250}>
                      <LineChart data={trends.sessions_by_day}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                        <XAxis dataKey="date" tickFormatter={formatChartDate} tick={{ fill: '#71717a', fontSize: 11 }} />
                        <YAxis tick={{ fill: '#71717a', fontSize: 11 }} />
                        <Tooltip {...tooltipStyle} labelFormatter={formatChartDate} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Line type="monotone" dataKey="total" stroke="#ffffff" strokeWidth={2} name="Total" dot={false} />
                        <Line type="monotone" dataKey="sally" stroke="#3b82f6" name="Sally" dot={false} />
                        <Line type="monotone" dataKey="hank" stroke="#ef4444" name="Hank" dot={false} />
                        <Line type="monotone" dataKey="ivy" stroke="#6b7280" name="Ivy" dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              )}

              {/* Chart 2: CDS Trend */}
              {trends && trends.cds_by_day.length > 0 && (
                <Card className="mb-6">
                  <CardHeader><h2 className="text-sm font-medium text-zinc-300">CDS Trend</h2></CardHeader>
                  <CardContent>
                    <ResponsiveContainer width="100%" height={250}>
                      <LineChart data={trends.cds_by_day}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                        <XAxis dataKey="date" tickFormatter={formatChartDate} tick={{ fill: '#71717a', fontSize: 11 }} />
                        <YAxis tick={{ fill: '#71717a', fontSize: 11 }} />
                        <Tooltip {...tooltipStyle} labelFormatter={formatChartDate} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <ReferenceLine y={0} stroke="#3f3f46" strokeDasharray="4 4" />
                        <Line type="monotone" dataKey="mean_cds" stroke="#ffffff" strokeWidth={2} name="Mean CDS" dot={false} />
                        <Line type="monotone" dataKey="sally_cds" stroke="#3b82f6" name="Sally" dot={false} />
                        <Line type="monotone" dataKey="hank_cds" stroke="#ef4444" name="Hank" dot={false} />
                        <Line type="monotone" dataKey="ivy_cds" stroke="#6b7280" name="Ivy" dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              )}

              {/* Chart 3: Avg Conversation Length by Arm */}
              {trends && trends.avg_length_by_arm.length > 0 && (
                <Card className="mb-6">
                  <CardHeader><h2 className="text-sm font-medium text-zinc-300">Avg. Conversation Length by Arm</h2></CardHeader>
                  <CardContent>
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={trends.avg_length_by_arm.map(r => ({ ...r, display_arm: ARM_DISPLAY[r.arm] || r.arm }))}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                        <XAxis dataKey="display_arm" tick={{ fill: '#71717a', fontSize: 11 }} />
                        <YAxis tick={{ fill: '#71717a', fontSize: 11 }} />
                        <Tooltip {...tooltipStyle} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Bar dataKey="avg_messages" fill="#3b82f6" name="Avg Messages" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="avg_turns" fill="#f59e0b" name="Avg Turns" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              )}

              {/* Chart 4: Session Funnel */}
              {trends && (
                <Card className="mb-6">
                  <CardHeader><h2 className="text-sm font-medium text-zinc-300">Session Funnel</h2></CardHeader>
                  <CardContent>
                    <FunnelChart funnel={trends.funnel} />
                  </CardContent>
                </Card>
              )}

              {/* Phase Distribution */}
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

              {/* Drop-off Points */}
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

function FunnelChart({ funnel }: { funnel: TrendsResponse["funnel"] }) {
  const stages = [
    { label: "Total Sessions", count: funnel.total_sessions, color: "bg-zinc-500" },
    { label: "Reached Active", count: funnel.reached_active, color: "bg-blue-500" },
    { label: "Completed", count: funnel.reached_completed, color: "bg-emerald-500" },
    { label: "Has CDS Score", count: funnel.has_cds, color: "bg-amber-500" },
  ];
  const max = funnel.total_sessions || 1;

  return (
    <div className="space-y-3">
      {stages.map((stage) => {
        const pct = Math.round((stage.count / max) * 100);
        return (
          <div key={stage.label}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-zinc-400">{stage.label}</span>
              <span className="text-xs text-zinc-500 font-mono">{stage.count} ({pct}%)</span>
            </div>
            <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
              <div className={`h-full rounded-full ${stage.color} transition-all`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

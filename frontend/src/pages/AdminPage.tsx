import { useState, useEffect } from "react";
import { Header } from "../components/layout/Header";
import { Card, CardHeader, CardContent, Badge } from "../components/ui";
import { getAdminAnalytics } from "../lib/api";
import type { AdminAnalyticsResponse, AdminSession } from "../lib/api";
import { formatDate, formatDuration } from "../lib/utils";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

const ARM_COLORS: Record<string, string> = {
  sally_nepq: "#3b82f6",
  hank_hypes: "#ef4444",
  ivy_informs: "#71717a",
};

const ARM_LABELS: Record<string, string> = {
  sally_nepq: "Sally",
  hank_hypes: "Hank",
  ivy_informs: "Ivy",
};

const STATUS_COLORS: Record<string, string> = {
  GO: "bg-emerald-900/50 text-emerald-400 border-emerald-700",
  ITERATE: "bg-amber-900/50 text-amber-400 border-amber-700",
  KILL: "bg-red-900/50 text-red-400 border-red-700",
  insufficient_data: "bg-zinc-800 text-zinc-400 border-zinc-700",
};

function MetricCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <Card>
      <CardContent>
        <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">
          {label}
        </p>
        <p className="text-2xl font-bold text-white">{value}</p>
        {sub && <p className="text-xs text-zinc-400 mt-1">{sub}</p>}
      </CardContent>
    </Card>
  );
}

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div className="w-full bg-zinc-800 rounded-full h-3 overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{
          width: `${Math.min(pct, 100)}%`,
          background:
            pct >= 100
              ? "#10b981"
              : pct >= 50
                ? "#3b82f6"
                : "#f59e0b",
        }}
      />
    </div>
  );
}

function ArmBadge({ arm }: { arm: string }) {
  const color = ARM_COLORS[arm] || "#71717a";
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider"
      style={{ backgroundColor: `${color}20`, color }}
    >
      {ARM_LABELS[arm] || arm}
    </span>
  );
}

function CdsValue({ cds }: { cds: number | null }) {
  if (cds === null) return <span className="text-zinc-600">—</span>;
  const color = cds > 0 ? "text-emerald-400" : cds < 0 ? "text-red-400" : "text-zinc-300";
  return <span className={color}>{cds > 0 ? `+${cds}` : cds}</span>;
}

export function AdminPage() {
  const [data, setData] = useState<AdminAnalyticsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      const d = await getAdminAnalytics();
      setData(d);
      setError(null);
    } catch {
      setError("Cannot connect to backend. Is the server running?");
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, []);

  if (error) {
    return (
      <div className="h-screen flex flex-col bg-zinc-950 text-white">
        <Header />
        <div className="flex-1 flex items-center justify-center">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="h-screen flex flex-col bg-zinc-950 text-white">
        <Header />
        <div className="flex-1 flex items-center justify-center">
          <p className="text-zinc-500 text-sm">Loading analytics...</p>
        </div>
      </div>
    );
  }

  // Prepare chart data
  const cdsChartData = Object.entries(data.arms).map(([arm, stats]) => ({
    name: ARM_LABELS[arm] || arm,
    arm,
    cds: stats.mean_cds ?? 0,
  }));

  const funnelData = Object.entries(data.arms).map(([arm, stats]) => ({
    name: ARM_LABELS[arm] || arm,
    arm,
    active: stats.active,
    completed: stats.completed,
    abandoned: stats.abandoned,
    switched: stats.switched,
  }));

  const phaseData = Object.entries(data.sally_phase_distribution).map(
    ([phase, count]) => ({
      name: phase.replace("_", " "),
      count,
    })
  );

  return (
    <div className="h-screen flex flex-col bg-zinc-950 text-white">
      <Header />
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        <h1 className="text-lg font-semibold">Experiment Dashboard</h1>

        {/* Section A: Overview Cards */}
        <div className="grid grid-cols-4 gap-4">
          <MetricCard
            label="Total Experiment Sessions"
            value={data.total_experiment_sessions}
          />
          <MetricCard
            label="Valid CDS Scores"
            value={`${data.total_with_cds} / ${data.target_sessions}`}
          />
          <Card>
            <CardContent>
              <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">
                Progress to 60 Sessions
              </p>
              <ProgressBar pct={data.progress_pct} />
              <p className="text-xs text-zinc-400 mt-1.5">
                {data.progress_pct}%
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent>
              <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">
                Experiment Status
              </p>
              <span
                className={`inline-block px-3 py-1.5 rounded-md text-sm font-bold border ${STATUS_COLORS[data.experiment_status] || STATUS_COLORS.insufficient_data}`}
              >
                {data.experiment_status === "insufficient_data"
                  ? "Collecting Data"
                  : data.experiment_status}
              </span>
            </CardContent>
          </Card>
        </div>

        {/* Section B: CDS Scorecard */}
        <div className="grid grid-cols-2 gap-4">
          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold text-zinc-200">
                Mean CDS by Arm
              </h2>
            </CardHeader>
            <CardContent>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={cdsChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                    <XAxis dataKey="name" tick={{ fill: "#a1a1aa", fontSize: 12 }} />
                    <YAxis tick={{ fill: "#a1a1aa", fontSize: 12 }} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#18181b",
                        border: "1px solid #3f3f46",
                        borderRadius: "6px",
                        color: "#fff",
                      }}
                    />
                    <Bar dataKey="cds" radius={[4, 4, 0, 0]}>
                      {cdsChartData.map((entry) => (
                        <Cell
                          key={entry.arm}
                          fill={ARM_COLORS[entry.arm] || "#71717a"}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold text-zinc-200">
                Sally's Lift vs Controls
              </h2>
            </CardHeader>
            <CardContent>
              <div className="space-y-4 pt-2">
                {Object.entries(data.sally_lift).length === 0 ? (
                  <p className="text-zinc-500 text-sm">
                    Not enough data yet
                  </p>
                ) : (
                  Object.entries(data.sally_lift).map(([arm, lift]) => (
                    <div key={arm} className="flex items-center justify-between">
                      <span className="text-sm text-zinc-300">
                        vs {ARM_LABELS[arm] || arm}
                      </span>
                      <span
                        className={`text-lg font-bold ${lift >= 0.3 ? "text-emerald-400" : lift >= 0 ? "text-amber-400" : "text-red-400"}`}
                      >
                        {lift > 0 ? "+" : ""}
                        {lift}
                      </span>
                    </div>
                  ))
                )}
                <div className="border-t border-zinc-800 pt-3 mt-3">
                  {Object.entries(data.arms).map(([arm, stats]) => (
                    <div
                      key={arm}
                      className="flex items-center justify-between py-1"
                    >
                      <ArmBadge arm={arm} />
                      <span className="text-sm text-zinc-400">
                        CDS: {stats.mean_cds ?? "—"} &middot; n=
                        {stats.has_cds}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Section C: Session Funnel */}
        <Card>
          <CardHeader>
            <h2 className="text-sm font-semibold text-zinc-200">
              Session Funnel by Arm
            </h2>
          </CardHeader>
          <CardContent>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={funnelData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis type="number" tick={{ fill: "#a1a1aa", fontSize: 12 }} />
                  <YAxis
                    dataKey="name"
                    type="category"
                    tick={{ fill: "#a1a1aa", fontSize: 12 }}
                    width={60}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#18181b",
                      border: "1px solid #3f3f46",
                      borderRadius: "6px",
                      color: "#fff",
                    }}
                  />
                  <Bar dataKey="active" stackId="a" fill="#3b82f6" name="Active" />
                  <Bar dataKey="completed" stackId="a" fill="#10b981" name="Completed" />
                  <Bar dataKey="abandoned" stackId="a" fill="#ef4444" name="Abandoned" />
                  <Bar dataKey="switched" stackId="a" fill="#a855f7" name="Switched" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* Section D: Channel + Follow-ups */}
        <div className="grid grid-cols-5 gap-4">
          <MetricCard
            label="Web Sessions"
            value={data.channels["web"] ?? 0}
          />
          <MetricCard
            label="SMS Sessions"
            value={data.channels["sms"] ?? 0}
          />
          <MetricCard
            label="Sessions w/ Follow-ups"
            value={data.followups.sessions_with_followups}
          />
          <MetricCard
            label="Avg Follow-ups / Session"
            value={data.followups.avg_followups_per_session}
          />
          <MetricCard
            label="Total Follow-ups Sent"
            value={data.followups.total_sent ?? 0}
          />
        </div>

        {/* Section E: Sally Phase Distribution */}
        {phaseData.length > 0 && (
          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold text-zinc-200">
                Sally — Phase at Session End
              </h2>
            </CardHeader>
            <CardContent>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={phaseData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                    <XAxis
                      dataKey="name"
                      tick={{ fill: "#a1a1aa", fontSize: 10 }}
                      angle={-20}
                      textAnchor="end"
                      height={50}
                    />
                    <YAxis
                      tick={{ fill: "#a1a1aa", fontSize: 12 }}
                      allowDecimals={false}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#18181b",
                        border: "1px solid #3f3f46",
                        borderRadius: "6px",
                        color: "#fff",
                      }}
                    />
                    <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Section F: Recent Sessions Table */}
        <Card>
          <CardHeader>
            <h2 className="text-sm font-semibold text-zinc-200">
              Recent Sessions
            </h2>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-zinc-800 text-zinc-500 uppercase tracking-wider">
                    <th className="text-left py-2 px-2">ID</th>
                    <th className="text-left py-2 px-2">Arm</th>
                    <th className="text-left py-2 px-2">Channel</th>
                    <th className="text-left py-2 px-2">Status</th>
                    <th className="text-right py-2 px-2">Pre</th>
                    <th className="text-right py-2 px-2">Post</th>
                    <th className="text-right py-2 px-2">CDS</th>
                    <th className="text-right py-2 px-2">Msgs</th>
                    <th className="text-left py-2 px-2">Phase</th>
                    <th className="text-left py-2 px-2">Duration</th>
                    <th className="text-left py-2 px-2">Started</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_sessions.map((s: AdminSession) => (
                    <tr
                      key={s.id}
                      className="border-b border-zinc-800/50 hover:bg-zinc-900/80 transition-colors"
                    >
                      <td className="py-2 px-2 font-mono text-zinc-400">
                        {s.id}
                      </td>
                      <td className="py-2 px-2">
                        <ArmBadge arm={s.arm} />
                      </td>
                      <td className="py-2 px-2 text-zinc-400">
                        {s.channel || "web"}
                      </td>
                      <td className="py-2 px-2">
                        <Badge
                          variant={
                            s.status === "completed"
                              ? "success"
                              : s.status === "active"
                                ? "default"
                                : s.status === "abandoned"
                                  ? "danger"
                                  : "warning"
                          }
                        >
                          {s.status}
                        </Badge>
                      </td>
                      <td className="py-2 px-2 text-right text-zinc-400">
                        {s.pre_conviction ?? "—"}
                      </td>
                      <td className="py-2 px-2 text-right text-zinc-400">
                        {s.post_conviction ?? "—"}
                      </td>
                      <td className="py-2 px-2 text-right font-medium">
                        <CdsValue cds={s.cds_score} />
                      </td>
                      <td className="py-2 px-2 text-right text-zinc-400">
                        {s.message_count}
                      </td>
                      <td className="py-2 px-2 text-zinc-400 text-[10px]">
                        {s.current_phase}
                      </td>
                      <td className="py-2 px-2 text-zinc-400">
                        {formatDuration(s.start_time, s.end_time)}
                      </td>
                      <td className="py-2 px-2 text-zinc-500">
                        {formatDate(s.start_time)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

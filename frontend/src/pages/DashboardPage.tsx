import { Header } from "../components/layout/Header";
import { Card, CardHeader, CardContent } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { Users, TrendingUp, Activity, Target, AlertTriangle } from "lucide-react";
import type { Metrics, NEPQPhase } from "../types";

const MOCK_METRICS: Metrics = {
  totalSessions: 142,
  activeSessions: 3,
  completedSessions: 127,
  averageConvictionDelta: 2.4,
  conversionRate: 12.5,
  failureModes: [
    { phase: "CONSEQUENCE" as NEPQPhase, reason: "Failed to quantify stakes", count: 45, percentage: 35 },
    { phase: "PROBLEM_AWARENESS" as NEPQPhase, reason: "Prospect not in-market", count: 30, percentage: 24 },
    { phase: "COMMITMENT" as NEPQPhase, reason: "Price objection", count: 25, percentage: 20 },
  ],
};

function MetricCard({ title, value, subtitle, icon: Icon }: { 
  title: string; 
  value: string | number; 
  subtitle?: string;
  icon: typeof Users;
}) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs text-zinc-500 uppercase tracking-wider">{title}</p>
            <p className="text-2xl font-semibold text-white mt-1">{value}</p>
            {subtitle && <p className="text-xs text-zinc-400 mt-1">{subtitle}</p>}
          </div>
          <div className="p-2 rounded-lg bg-zinc-800">
            <Icon className="w-4 h-4 text-zinc-400" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function DashboardPage() {
  return (
    <div className="h-screen flex flex-col bg-zinc-950">
      <Header />
      
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-6xl mx-auto space-y-6">
          <div>
            <h1 className="text-xl font-semibold text-white">Dashboard</h1>
            <p className="text-sm text-zinc-400 mt-1">Real-time session telemetry and analytics</p>
          </div>

          {/* Metrics Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard 
              title="Total Sessions" 
              value={MOCK_METRICS.totalSessions} 
              subtitle="+12 this week"
              icon={Users} 
            />
            <MetricCard 
              title="Active Now" 
              value={MOCK_METRICS.activeSessions} 
              icon={Activity} 
            />
            <MetricCard 
              title="Avg. Conviction Δ" 
              value={`+${MOCK_METRICS.averageConvictionDelta}`} 
              subtitle="Points gained"
              icon={TrendingUp} 
            />
            <MetricCard 
              title="Conversion Rate" 
              value={`${MOCK_METRICS.conversionRate}%`} 
              subtitle="To workshop booking"
              icon={Target} 
            />
          </div>

          {/* Failure Modes */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <h2 className="font-medium text-white">Failure Modes</h2>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {MOCK_METRICS.failureModes.map((mode, i) => (
                <div key={i} className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/50">
                  <div className="flex items-center gap-3">
                    <Badge phase={mode.phase} size="sm" />
                    <span className="text-sm text-zinc-300">{mode.reason}</span>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-sm text-zinc-400">{mode.count} sessions</span>
                    <div className="w-24 h-2 bg-zinc-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-amber-500/70 rounded-full" 
                        style={{ width: `${mode.percentage}%` }}
                      />
                    </div>
                    <span className="text-xs text-zinc-500 w-8">{mode.percentage}%</span>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
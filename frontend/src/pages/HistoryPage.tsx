import { Header } from "../components/layout/Header";
import { Card, CardHeader, CardContent } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import type { Session } from "../types";
import { format } from "date-fns";
import { Eye, Clock, MessageSquare } from "lucide-react";

const MOCK_SESSIONS: Session[] = [
  {
    id: "SES-001",
    startTime: new Date(Date.now() - 3600000),
    endTime: new Date(),
    status: "completed",
    currentPhase: "COMMITMENT",
    messages: Array(12).fill(null),
    convictionDelta: 3.2,
  },
  {
    id: "SES-002",
    startTime: new Date(Date.now() - 86400000),
    status: "abandoned",
    currentPhase: "CONSEQUENCE",
    messages: Array(8).fill(null),
    convictionDelta: 1.1,
  },
  {
    id: "SES-003",
    startTime: new Date(Date.now() - 172800000),
    endTime: new Date(Date.now() - 172000000),
    status: "completed",
    currentPhase: "COMMITMENT",
    messages: Array(15).fill(null),
    convictionDelta: 4.5,
  },
];

const STATUS_STYLES = {
  active: "bg-emerald-500/10 text-emerald-400 border-emerald-500/50",
  completed: "bg-sky-500/10 text-sky-400 border-sky-500/50",
  abandoned: "bg-zinc-500/10 text-zinc-400 border-zinc-500/50",
};

export function HistoryPage() {
  return (
    <div className="h-screen flex flex-col bg-zinc-950">
      <Header />
      
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-6xl mx-auto space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-semibold text-white">Session History</h1>
              <p className="text-sm text-zinc-400 mt-1">Audit logs of past conversations</p>
            </div>
            <Button variant="secondary" size="sm">
              Export CSV
            </Button>
          </div>

          <Card>
            <CardHeader>
              <div className="grid grid-cols-6 gap-4 text-xs text-zinc-500 uppercase tracking-wider">
                <span>Session ID</span>
                <span>Status</span>
                <span>Final Phase</span>
                <span>Duration</span>
                <span>Messages</span>
                <span className="text-right">Actions</span>
              </div>
            </CardHeader>
            <CardContent className="divide-y divide-zinc-800">
              {MOCK_SESSIONS.map((session) => (
                <div key={session.id} className="grid grid-cols-6 gap-4 py-3 items-center">
                  <div>
                    <span className="text-sm font-mono text-white">{session.id}</span>
                    <p className="text-xs text-zinc-500 mt-0.5">
                      {format(session.startTime, "MMM d, HH:mm")}
                    </p>
                  </div>
                  <div>
                    <span className={`inline-flex px-2 py-0.5 text-xs rounded border ${STATUS_STYLES[session.status]}`}>
                      {session.status}
                    </span>
                  </div>
                  <div>
                    <Badge phase={session.currentPhase} size="sm" />
                  </div>
                  <div className="flex items-center gap-1.5 text-sm text-zinc-400">
                    <Clock className="w-3.5 h-3.5" />
                    {session.endTime 
                      ? `${Math.round((session.endTime.getTime() - session.startTime.getTime()) / 60000)}m`
                      : "—"
                    }
                  </div>
                  <div className="flex items-center gap-1.5 text-sm text-zinc-400">
                    <MessageSquare className="w-3.5 h-3.5" />
                    {session.messages.length}
                  </div>
                  <div className="text-right">
                    <Button variant="ghost" size="sm">
                      <Eye className="w-3.5 h-3.5 mr-1" />
                      View
                    </Button>
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
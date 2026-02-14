import { useState, useEffect } from "react";
import { Header } from "../components/layout/Header.tsx";
import { Card, CardHeader, CardContent } from "../components/ui/index";
import { Badge } from "../components/ui/index";
import { Button } from "../components/ui/index";
import { listSessions, getSession, getExportCsvUrl } from "../lib/api";
import { getPhaseLabel, getPhaseColor } from "../constants";
import { formatDate, formatDuration, formatTimestamp } from "../lib/utils";
import type { SessionListItem, SessionDetail } from "../lib/api";

export function HistoryPage() {
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [selectedSession, setSelectedSession] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { fetchSessions(); }, []);

  const fetchSessions = async () => {
    try {
      const data = await listSessions();
      setSessions(data);
      setError(null);
    } catch {
      setError("Cannot connect to backend. Is the server running?");
    } finally {
      setLoading(false);
    }
  };

  const handleViewSession = async (sessionId: string) => {
    try {
      const detail = await getSession(sessionId);
      setSelectedSession(detail);
    } catch {
      alert("Failed to load session transcript");
    }
  };

  if (selectedSession) {
    return (
      <div className="h-screen flex flex-col bg-zinc-950 text-white">
        <Header />
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-center justify-between mb-6">
              <Button variant="ghost" size="sm" onClick={() => setSelectedSession(null)}>← Back to History</Button>
              <div className="flex items-center gap-2">
                <Badge variant={selectedSession.status === "completed" ? "success" : selectedSession.status === "active" ? "warning" : "danger"}>{selectedSession.status}</Badge>
                <span className="text-xs text-zinc-500">Session {selectedSession.id}</span>
              </div>
            </div>

            <Card className="mb-6">
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                  <div><p className="text-zinc-500 text-xs">Pre-Conviction</p><p className="text-white font-medium">{selectedSession.pre_conviction ?? "—"}/10</p></div>
                  <div><p className="text-zinc-500 text-xs">Final Phase</p><p className="font-medium" style={{ color: getPhaseColor(selectedSession.current_phase) }}>{getPhaseLabel(selectedSession.current_phase)}</p></div>
                  <div><p className="text-zinc-500 text-xs">Duration</p><p className="text-white font-medium font-mono">{formatDuration(selectedSession.start_time, selectedSession.end_time)}</p></div>
                  <div><p className="text-zinc-500 text-xs">Messages</p><p className="text-white font-medium">{selectedSession.messages.length}</p></div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><h2 className="text-sm font-medium text-zinc-300">Full Transcript</h2></CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {selectedSession.messages.map((msg) => {
                    const phaseColor = getPhaseColor(msg.phase);
                    return (
                      <div key={msg.id} className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
                        <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${msg.role === "user" ? "bg-zinc-700 text-zinc-300" : "bg-zinc-800 text-zinc-400"}`}>
                          {msg.role === "user" ? "U" : "S"}
                        </div>
                        <div className={`flex-1 ${msg.role === "user" ? "text-right" : ""}`}>
                          <div className="flex items-center gap-2 mb-1 flex-wrap">
                            {msg.role === "user" && <span className="flex-1" />}
                            <span className="text-[10px] text-zinc-600">{formatTimestamp(msg.timestamp)}</span>
                            <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider" style={{ background: `${phaseColor}15`, color: phaseColor }}>{getPhaseLabel(msg.phase)}</span>
                          </div>
                          <p className={`text-sm leading-relaxed ${msg.role === "user" ? "text-zinc-300" : "text-zinc-400"}`}>{msg.content}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-zinc-950 text-white">
      <Header />
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-5xl mx-auto">
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-lg font-semibold">Session History</h1>
            <div className="flex items-center gap-2">
              <a
                href={getExportCsvUrl()}
                download
                className="inline-flex items-center h-8 px-3 rounded-md text-xs font-medium bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
              >
                Download CSV
              </a>
              <Button variant="secondary" size="sm" onClick={fetchSessions}>Refresh</Button>
            </div>
          </div>

          {error && <div className="mb-6 p-3 rounded-lg bg-red-900/20 border border-red-900/40 text-sm text-red-400">{error}</div>}
          {loading && <div className="text-sm text-zinc-500">Loading sessions...</div>}

          {!loading && sessions.length === 0 && (
            <Card><CardContent><p className="text-sm text-zinc-500 text-center py-8">No sessions yet. Start a conversation to see history here.</p></CardContent></Card>
          )}

          {sessions.length > 0 && (
            <Card>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800">
                      <th className="text-left p-3 text-xs text-zinc-500 font-medium">Session</th>
                      <th className="text-left p-3 text-xs text-zinc-500 font-medium">Status</th>
                      <th className="text-left p-3 text-xs text-zinc-500 font-medium">Phase</th>
                      <th className="text-left p-3 text-xs text-zinc-500 font-medium">Pre-Score</th>
                      <th className="text-left p-3 text-xs text-zinc-500 font-medium">CDS</th>
                      <th className="text-left p-3 text-xs text-zinc-500 font-medium">Messages</th>
                      <th className="text-left p-3 text-xs text-zinc-500 font-medium">Duration</th>
                      <th className="text-left p-3 text-xs text-zinc-500 font-medium">Started</th>
                      <th className="text-right p-3 text-xs text-zinc-500 font-medium">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessions.map((session) => (
                      <tr key={session.id} className="border-b border-zinc-800/50 hover:bg-zinc-900/50 transition-colors">
                        <td className="p-3 font-mono text-zinc-400">{session.id}</td>
                        <td className="p-3"><Badge variant={session.status === "completed" ? "success" : session.status === "active" ? "warning" : "danger"}>{session.status}</Badge></td>
                        <td className="p-3"><span className="text-xs font-medium" style={{ color: getPhaseColor(session.current_phase) }}>{getPhaseLabel(session.current_phase)}</span></td>
                        <td className="p-3 text-zinc-400">{session.pre_conviction ?? "—"}</td>
                        <td className="p-3">
                          {session.cds_score != null ? (
                            <span className={`font-mono text-xs ${session.cds_score > 0 ? "text-emerald-400" : session.cds_score < 0 ? "text-red-400" : "text-zinc-500"}`}>
                              {session.cds_score > 0 ? "+" : ""}{session.cds_score}
                            </span>
                          ) : (
                            <span className="text-zinc-600">—</span>
                          )}
                        </td>
                        <td className="p-3 text-zinc-400">{session.message_count}</td>
                        <td className="p-3 font-mono text-zinc-400">{formatDuration(session.start_time, session.end_time)}</td>
                        <td className="p-3 text-zinc-500">{formatDate(session.start_time)}</td>
                        <td className="p-3 text-right"><Button variant="ghost" size="sm" onClick={() => handleViewSession(session.id)}>View</Button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
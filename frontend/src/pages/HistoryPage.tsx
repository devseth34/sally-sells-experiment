import { useState, useEffect, useRef, useCallback } from "react";
import { Header } from "../components/layout/Header.tsx";
import { Card, CardHeader, CardContent } from "../components/ui/index";
import { Badge } from "../components/ui/index";
import { Button } from "../components/ui/index";
import { listSessions, getSession, getExportCsvUrl } from "../lib/api";
import { getPhaseLabel, getPhaseColor } from "../constants";
import { formatDate, formatDuration, formatTimestamp } from "../lib/utils";
import type { SessionListItem, SessionDetail, SessionFilters } from "../lib/api";

const ARM_LABELS: Record<string, string> = {
  sally_nepq: "Sally",
  hank_hypes: "Hank",
  ivy_informs: "Ivy",
  sally_hank_close: "Sally>Hank Close",
  sally_ivy_bridge: "Sally>Ivy Bridge",
  sally_empathy_plus: "Sally Empathy+",
  sally_direct: "Sally Direct",
  hank_structured: "Hank Structured",
};

const ARM_COLORS: Record<string, string> = {
  sally_nepq: "bg-blue-500/20 text-blue-400",
  hank_hypes: "bg-rose-500/20 text-rose-400",
  ivy_informs: "bg-zinc-500/20 text-zinc-400",
  sally_hank_close: "bg-purple-500/20 text-purple-400",
  sally_ivy_bridge: "bg-cyan-500/20 text-cyan-400",
  sally_empathy_plus: "bg-pink-500/20 text-pink-400",
  sally_direct: "bg-amber-500/20 text-amber-400",
  hank_structured: "bg-orange-500/20 text-orange-400",
};

const STATUS_COLORS: Record<string, "success" | "warning" | "danger"> = {
  completed: "success",
  active: "warning",
  abandoned: "danger",
  switched: "danger",
};

const selectClass = "h-8 px-2 rounded-md text-xs bg-zinc-800 border border-zinc-700 text-zinc-300";
const searchClass = "h-8 px-3 rounded-md text-xs bg-zinc-800 border border-zinc-700 text-zinc-300 placeholder-zinc-600 w-48";
const dateClass = "h-8 px-2 rounded-md text-xs bg-zinc-800 border border-zinc-700 text-zinc-300";

export function HistoryPage() {
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [selectedSession, setSelectedSession] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [channelFilter, setChannelFilter] = useState("");
  const [armFilter, setArmFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [searchText, setSearchText] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const buildFilters = useCallback((): SessionFilters => {
    const filters: SessionFilters = {};
    if (channelFilter) filters.channel = channelFilter;
    if (armFilter) filters.arm = armFilter;
    if (statusFilter) filters.status = statusFilter;
    if (searchText.trim()) filters.search = searchText.trim();
    if (startDate) filters.startDate = new Date(startDate).getTime() / 1000;
    if (endDate) filters.endDate = new Date(endDate + "T23:59:59").getTime() / 1000;
    return filters;
  }, [channelFilter, armFilter, statusFilter, searchText, startDate, endDate]);

  const fetchSessions = useCallback(async () => {
    try {
      const data = await listSessions(buildFilters());
      setSessions(data);
      setError(null);
    } catch {
      setError("Cannot connect to backend. Is the server running?");
    } finally {
      setLoading(false);
    }
  }, [buildFilters]);

  useEffect(() => { fetchSessions(); }, [fetchSessions]);

  // Debounced search
  const handleSearchChange = (value: string) => {
    setSearchText(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      // fetchSessions will be triggered by useEffect dependency on buildFilters
    }, 300);
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
                <Badge variant={STATUS_COLORS[selectedSession.status] || "danger"}>{selectedSession.status}</Badge>
                {(selectedSession as any).assigned_arm && (
                  <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${ARM_COLORS[(selectedSession as any).assigned_arm] || "bg-zinc-700 text-zinc-400"}`}>
                    {ARM_LABELS[(selectedSession as any).assigned_arm] || (selectedSession as any).assigned_arm}
                  </span>
                )}
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
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center justify-between mb-4">
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

          {/* Filter bar */}
          <div className="flex items-center gap-3 mb-4 flex-wrap">
            <select className={selectClass} value={channelFilter} onChange={(e) => setChannelFilter(e.target.value)}>
              <option value="">All Channels</option>
              <option value="web">Web</option>
              <option value="sms">SMS</option>
            </select>
            <select className={selectClass} value={armFilter} onChange={(e) => setArmFilter(e.target.value)}>
              <option value="">All Bots</option>
              <option value="sally_nepq">Sally</option>
              <option value="hank_hypes">Hank</option>
              <option value="ivy_informs">Ivy</option>
              <option value="sally_hank_close">Sally&gt;Hank Close</option>
              <option value="sally_ivy_bridge">Sally&gt;Ivy Bridge</option>
              <option value="sally_empathy_plus">Sally Empathy+</option>
              <option value="sally_direct">Sally Direct</option>
              <option value="hank_structured">Hank Structured</option>
            </select>
            <select className={selectClass} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All Statuses</option>
              <option value="active">Active</option>
              <option value="completed">Completed</option>
              <option value="abandoned">Abandoned</option>
              <option value="switched">Switched</option>
            </select>
            <input
              className={searchClass}
              placeholder="Search ID or phone..."
              value={searchText}
              onChange={(e) => handleSearchChange(e.target.value)}
            />
            <input type="date" className={dateClass} value={startDate} onChange={(e) => setStartDate(e.target.value)} title="From date" />
            <input type="date" className={dateClass} value={endDate} onChange={(e) => setEndDate(e.target.value)} title="To date" />
          </div>

          {error && <div className="mb-6 p-3 rounded-lg bg-red-900/20 border border-red-900/40 text-sm text-red-400">{error}</div>}
          {loading && <div className="text-sm text-zinc-500">Loading sessions...</div>}

          {!loading && sessions.length === 0 && (
            <Card><CardContent><p className="text-sm text-zinc-500 text-center py-8">No sessions found matching filters.</p></CardContent></Card>
          )}

          {sessions.length > 0 && (
            <>
              <p className="text-xs text-zinc-500 mb-2">Showing {sessions.length} session{sessions.length !== 1 ? "s" : ""}</p>
              <Card>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-zinc-800">
                        <th className="text-left p-3 text-xs text-zinc-500 font-medium">Session</th>
                        <th className="text-left p-3 text-xs text-zinc-500 font-medium">Channel</th>
                        <th className="text-left p-3 text-xs text-zinc-500 font-medium">Bot</th>
                        <th className="text-left p-3 text-xs text-zinc-500 font-medium">Status</th>
                        <th className="text-left p-3 text-xs text-zinc-500 font-medium">Phase</th>
                        <th className="text-left p-3 text-xs text-zinc-500 font-medium">Pre</th>
                        <th className="text-left p-3 text-xs text-zinc-500 font-medium">CDS</th>
                        <th className="text-left p-3 text-xs text-zinc-500 font-medium">Msgs</th>
                        <th className="text-left p-3 text-xs text-zinc-500 font-medium">F/U</th>
                        <th className="text-left p-3 text-xs text-zinc-500 font-medium">Duration</th>
                        <th className="text-left p-3 text-xs text-zinc-500 font-medium">Started</th>
                        <th className="text-right p-3 text-xs text-zinc-500 font-medium">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sessions.map((session, idx) => (
                        <tr key={session.id} className={`border-b border-zinc-800/50 hover:bg-zinc-900/50 transition-colors ${idx % 2 === 1 ? "bg-zinc-900/20" : ""}`}>
                          <td className="p-3 font-mono text-zinc-400 text-xs">{session.id}</td>
                          <td className="p-3">
                            <div>
                              <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ${session.channel === "sms" ? "bg-blue-500/20 text-blue-400" : "bg-zinc-700/50 text-zinc-400"}`}>
                                {session.channel === "sms" ? "SMS" : "Web"}
                              </span>
                              {session.channel === "sms" && session.phone_number && (
                                <p className="text-[10px] text-zinc-600 mt-0.5">{session.phone_number}</p>
                              )}
                            </div>
                          </td>
                          <td className="p-3">
                            {session.assigned_arm ? (
                              <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ${ARM_COLORS[session.assigned_arm] || "bg-zinc-700 text-zinc-400"}`}>
                                {ARM_LABELS[session.assigned_arm] || session.assigned_arm}
                              </span>
                            ) : (
                              <span className="text-zinc-600">—</span>
                            )}
                          </td>
                          <td className="p-3"><Badge variant={STATUS_COLORS[session.status] || "danger"}>{session.status}</Badge></td>
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
                          <td className="p-3 text-zinc-400">{session.followup_count ? session.followup_count : "—"}</td>
                          <td className="p-3 font-mono text-zinc-400 text-xs">{formatDuration(session.start_time, session.end_time)}</td>
                          <td className="p-3 text-zinc-500 text-xs">{formatDate(session.start_time)}</td>
                          <td className="p-3 text-right"><Button variant="ghost" size="sm" onClick={() => handleViewSession(session.id)}>View</Button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

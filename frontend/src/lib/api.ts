const API_BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000") + "/api";
export interface MessageResponse {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  phase: string;
}

export interface CreateSessionResponse {
  session_id: string;
  current_phase: string;
  pre_conviction: number;
  greeting: MessageResponse;
}

export interface SendMessageResponse {
  user_message: MessageResponse;
  assistant_message: MessageResponse;
  current_phase: string;
  previous_phase: string;
  phase_changed: boolean;
  session_ended: boolean;
}

export interface SessionDetail {
  id: string;
  status: string;
  current_phase: string;
  pre_conviction: number | null;
  post_conviction: number | null;
  start_time: number;
  end_time: number | null;
  messages: MessageResponse[];
}

export interface SessionListItem {
  id: string;
  status: string;
  current_phase: string;
  pre_conviction: number | null;
  message_count: number;
  start_time: number;
  end_time: number | null;
}

export interface MetricsResponse {
  total_sessions: number;
  active_sessions: number;
  completed_sessions: number;
  abandoned_sessions: number;
  average_pre_conviction: number | null;
  conversion_rate: number;
  phase_distribution: Record<string, number>;
  failure_modes: Array<{ phase: string; count: number }>;
}

export async function createSession(preConviction: number): Promise<CreateSessionResponse> {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pre_conviction: preConviction }),
  });
  if (!res.ok) throw new Error(`Failed to create session: ${res.statusText}`);
  return res.json();
}

export async function sendMessage(sessionId: string, content: string): Promise<SendMessageResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`Failed to send message: ${res.statusText}`);
  return res.json();
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`);
  if (!res.ok) throw new Error(`Failed to get session: ${res.statusText}`);
  return res.json();
}

export async function listSessions(): Promise<SessionListItem[]> {
  const res = await fetch(`${API_BASE}/sessions`);
  if (!res.ok) throw new Error(`Failed to list sessions: ${res.statusText}`);
  return res.json();
}

export async function getMetrics(): Promise<MetricsResponse> {
  const res = await fetch(`${API_BASE}/metrics`);
  if (!res.ok) throw new Error(`Failed to get metrics: ${res.statusText}`);
  return res.json();
}

export async function endSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/end`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to end session: ${res.statusText}`);
}
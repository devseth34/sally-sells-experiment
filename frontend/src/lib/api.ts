const API_BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000") + "/api";

// Persistent visitor identity — survives page refresh and browser close
export function getOrCreateVisitorId(): string {
  const key = "sally_visitor_id";
  let id = localStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(key, id);
  }
  return id;
}

// --- Authentication ---

export interface AuthResponse {
  token: string;
  user_id: string;
  email: string;
  display_name?: string;
}

export interface IdentifyResponse {
  identified: boolean;
  user_id?: string;
  display_name?: string;
  has_memory: boolean;
}

// Token management
export function getAuthToken(): string | null {
  return localStorage.getItem("sally_auth_token");
}

export function setAuthToken(token: string): void {
  localStorage.setItem("sally_auth_token", token);
}

export function clearAuth(): void {
  localStorage.removeItem("sally_auth_token");
  localStorage.removeItem("sally_user_email");
  localStorage.removeItem("sally_user_name");
}

export function isAuthenticated(): boolean {
  return !!getAuthToken();
}

export function getSavedUserInfo(): { email: string; name: string } | null {
  const email = localStorage.getItem("sally_user_email");
  if (!email) return null;
  return { email, name: localStorage.getItem("sally_user_name") || "" };
}

// Auth headers helper — includes Bearer token if available
function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export async function register(
  email: string,
  password: string,
  displayName?: string,
  phone?: string,
): Promise<AuthResponse> {
  const visitorId = getOrCreateVisitorId();
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      password,
      display_name: displayName,
      phone,
      visitor_id: visitorId,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Registration failed");
  }
  const data: AuthResponse = await res.json();
  setAuthToken(data.token);
  localStorage.setItem("sally_user_email", data.email);
  if (data.display_name) localStorage.setItem("sally_user_name", data.display_name);
  return data;
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const visitorId = getOrCreateVisitorId();
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, visitor_id: visitorId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Login failed");
  }
  const data: AuthResponse = await res.json();
  setAuthToken(data.token);
  localStorage.setItem("sally_user_email", data.email);
  if (data.display_name) localStorage.setItem("sally_user_name", data.display_name);
  return data;
}

export async function identifyByNamePhone(
  fullName: string,
  phone: string,
): Promise<IdentifyResponse> {
  const visitorId = getOrCreateVisitorId();
  const res = await fetch(`${API_BASE}/auth/identify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ full_name: fullName, phone, visitor_id: visitorId }),
  });
  if (!res.ok) throw new Error("Identification failed");
  return res.json();
}

// --- Session & Message Types ---

export type BotArm = "sally_nepq" | "hank_hypes" | "ivy_informs" | "sally_hank_close" | "sally_ivy_bridge" | "sally_empathy_plus" | "sally_direct" | "hank_structured";

export const SALLY_ENGINE_ARMS = new Set<string>([
  "sally_nepq", "sally_hank_close", "sally_ivy_bridge",
  "sally_empathy_plus", "sally_direct", "hank_structured",
]);

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
  assigned_arm: string;
  bot_display_name: string;
  greeting: MessageResponse;
  visitor_id?: string;
}

export interface ResumeSessionResponse {
  session_id: string;
  current_phase: string;
  assigned_arm: string;
  bot_display_name: string;
  messages: MessageResponse[];
  visitor_id: string;
  can_resume: boolean;
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
  post_conviction: number | null;
  cds_score: number | null;
  message_count: number;
  start_time: number;
  end_time: number | null;
  assigned_arm?: string;
  channel?: string;
  phone_number?: string;
  turn_number?: number;
  followup_count?: number;
  experiment_mode?: string;
}

export interface MetricsResponse {
  total_sessions: number;
  active_sessions: number;
  completed_sessions: number;
  abandoned_sessions: number;
  average_pre_conviction: number | null;
  average_cds: number | null;
  conversion_rate: number;
  phase_distribution: Record<string, number>;
  failure_modes: Array<{ phase: string; count: number }>;
}

// --- Session Management (with auth headers) ---

export async function createSession(
  preConviction: number,
  selectedBot?: BotArm,
  experimentMode: boolean = false,
  participantName?: string,
  participantEmail?: string,
  platform?: string,
  platformParticipantId?: string,
): Promise<CreateSessionResponse> {
  const visitorId = getOrCreateVisitorId();
  const body: Record<string, unknown> = {
    pre_conviction: preConviction,
    visitor_id: visitorId,
    experiment_mode: experimentMode,
  };
  if (selectedBot) {
    body.selected_bot = selectedBot;
  }
  if (participantName) {
    body.participant_name = participantName;
  }
  if (participantEmail) {
    body.participant_email = participantEmail;
  }
  if (platform) {
    body.platform = platform;
  }
  if (platformParticipantId) {
    body.platform_participant_id = platformParticipantId;
  }
  const res = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed to create session: ${res.statusText}`);
  return res.json();
}

export async function checkActiveSession(): Promise<ResumeSessionResponse | null> {
  const visitorId = getOrCreateVisitorId();
  try {
    const headers: Record<string, string> = {};
    const token = getAuthToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const res = await fetch(`${API_BASE}/visitors/${visitorId}/active-session`, { headers });
    if (res.status === 404) return null;
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function sendMessage(sessionId: string, content: string): Promise<SendMessageResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ content }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to send message: ${res.statusText}`);
  }
  return res.json();
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`);
  if (!res.ok) throw new Error(`Failed to get session: ${res.statusText}`);
  return res.json();
}

export interface SessionFilters {
  channel?: string;
  arm?: string;
  status?: string;
  search?: string;
  startDate?: number;
  endDate?: number;
}

export async function listSessions(filters?: SessionFilters): Promise<SessionListItem[]> {
  const params = new URLSearchParams();
  if (filters?.channel) params.set("channel", filters.channel);
  if (filters?.arm) params.set("arm", filters.arm);
  if (filters?.status) params.set("status", filters.status);
  if (filters?.search) params.set("search", filters.search);
  if (filters?.startDate) params.set("start_date", filters.startDate.toString());
  if (filters?.endDate) params.set("end_date", filters.endDate.toString());

  const qs = params.toString();
  const url = qs ? `${API_BASE}/sessions?${qs}` : `${API_BASE}/sessions`;
  const res = await fetch(url);
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

/**
 * Fire-and-forget session end via sendBeacon — survives tab close/navigation.
 * Use this in beforeunload/pagehide handlers where fetch() may be cancelled.
 */
export function endSessionBeacon(sessionId: string): void {
  const url = `${API_BASE}/sessions/${sessionId}/end`;
  navigator.sendBeacon(url);
}

export interface AppConfig {
  stripe_payment_link: string;
  stripe_publishable_key: string;
  tidycal_path: string;
}

export async function getConfig(): Promise<AppConfig> {
  const res = await fetch(`${API_BASE}/config`);
  if (!res.ok) throw new Error(`Failed to get config: ${res.statusText}`);
  return res.json();
}

export interface CheckoutResponse {
  checkout_url: string;
  session_id: string;
}

export async function createCheckoutSession(sessionId?: string): Promise<CheckoutResponse> {
  const url = sessionId
    ? `${API_BASE}/checkout?session_id=${sessionId}`
    : `${API_BASE}/checkout`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to create checkout: ${res.statusText}`);
  return res.json();
}

export interface PaymentVerification {
  payment_status: string;
  status: string;
  customer_email: string | null;
  amount_total: number;
  currency: string;
  metadata: Record<string, string>;
}

export async function verifyPayment(checkoutSessionId: string): Promise<PaymentVerification> {
  const res = await fetch(`${API_BASE}/checkout/verify/${checkoutSessionId}`);
  if (!res.ok) throw new Error(`Failed to verify payment: ${res.statusText}`);
  return res.json();
}

export interface PostConvictionResponse {
  session_id: string;
  pre_conviction: number | null;
  post_conviction: number;
  cds_score: number;
}

export async function submitPostConviction(sessionId: string, postConviction: number): Promise<PostConvictionResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/post-conviction`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ post_conviction: postConviction }),
  });
  if (!res.ok) throw new Error(`Failed to submit post-conviction: ${res.statusText}`);
  return res.json();
}

export interface CsvExportParams {
  platform?: string;
  arm?: string;
  status?: string;
  cds_only?: boolean;
  start_date?: string;  // YYYY-MM-DD
  end_date?: string;    // YYYY-MM-DD
  experiment_only?: boolean;
}

export function getExportCsvUrl(params?: CsvExportParams): string {
  const url = new URL(`${API_BASE}/export/csv`, window.location.origin);
  if (params) {
    if (params.platform) url.searchParams.set("platform", params.platform);
    if (params.arm) url.searchParams.set("arm", params.arm);
    if (params.status) url.searchParams.set("status", params.status);
    if (params.cds_only) url.searchParams.set("cds_only", "true");
    if (params.start_date) url.searchParams.set("start_date", params.start_date);
    if (params.end_date) url.searchParams.set("end_date", params.end_date);
    if (params.experiment_only !== undefined) url.searchParams.set("experiment_only", String(params.experiment_only));
  }
  return url.toString();
}

export function getExportPdfUrl(params?: CsvExportParams & { include_insights?: boolean }): string {
  const url = new URL(`${API_BASE}/export/pdf`, window.location.origin);
  if (params) {
    if (params.platform) url.searchParams.set("platform", params.platform);
    if (params.arm) url.searchParams.set("arm", params.arm);
    if (params.status) url.searchParams.set("status", params.status);
    if (params.cds_only) url.searchParams.set("cds_only", "true");
    if (params.start_date) url.searchParams.set("start_date", params.start_date);
    if (params.end_date) url.searchParams.set("end_date", params.end_date);
    if (params.experiment_only !== undefined) url.searchParams.set("experiment_only", String(params.experiment_only));
    if (params.include_insights !== undefined) url.searchParams.set("include_insights", String(params.include_insights));
  }
  return url.toString();
}

/**
 * Delete all stored memory for the current visitor and reset localStorage identity.
 * "Forget Me" — full privacy wipe.
 */
export async function clearVisitorMemory(): Promise<void> {
  const visitorId = getOrCreateVisitorId();
  const res = await fetch(`${API_BASE}/visitors/${visitorId}/memory`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Failed to clear memory: ${res.statusText}`);
  // Remove localStorage visitor identity so next session creates a fresh one
  localStorage.removeItem("sally_visitor_id");
}

// --- Bot Switching ---

export interface SwitchBotResponse {
  previous_session_id: string;
  new_session_id: string;
  new_arm: string;
  bot_display_name: string;
  current_phase: string;
  greeting: MessageResponse;
}

export async function switchBot(sessionId: string, newBot: BotArm): Promise<SwitchBotResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/switch`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ new_bot: newBot }),
  });
  if (!res.ok) throw new Error(`Failed to switch bot: ${res.statusText}`);
  return res.json();
}

// --- Analytics Trends ---

export interface TrendsResponse {
  sessions_by_day: Array<{
    date: string;
    total: number;
    sally: number;
    hank: number;
    ivy: number;
    web: number;
    sms: number;
  }>;
  cds_by_day: Array<{
    date: string;
    mean_cds: number | null;
    sally_cds: number | null;
    hank_cds: number | null;
    ivy_cds: number | null;
    count: number;
  }>;
  avg_length_by_arm: Array<{
    arm: string;
    avg_messages: number;
    avg_turns: number;
    avg_duration_minutes: number;
  }>;
  funnel: {
    total_sessions: number;
    reached_active: number;
    reached_completed: number;
    has_cds: number;
  };
}

export async function getTrends(): Promise<TrendsResponse> {
  const res = await fetch(`${API_BASE}/analytics/trends`);
  if (!res.ok) throw new Error(`Failed to get trends: ${res.statusText}`);
  return res.json();
}

// --- Experiment Monitoring ---

export interface CdsSummaryResponse {
  arms: Record<string, {
    total_sessions: number;
    completed_cds: number;
    mean_cds: number | null;
    min_cds: number | null;
    max_cds: number | null;
  }>;
  sally_lift_vs_controls: Record<string, number>;
  experiment_session_counts: Record<string, number>;
  target: {
    min_sessions_per_arm: number;
    total_target: number;
    sally_cds_target: number;
    lift_target: number;
  };
}

export async function getCdsSummary(): Promise<CdsSummaryResponse> {
  const res = await fetch(`${API_BASE}/monitoring/cds-summary`);
  if (!res.ok) throw new Error(`Failed to get CDS summary: ${res.statusText}`);
  return res.json();
}

// --- Admin Analytics ---

export interface ArmStats {
  total: number;
  completed: number;
  abandoned: number;
  switched: number;
  active: number;
  has_cds: number;
  mean_cds: number | null;
  mean_pre: number | null;
  mean_post: number | null;
  avg_messages: number | null;
  avg_turns: number | null;
  completion_rate: number;
}

export interface AdminSession {
  id: string;
  arm: string;
  channel: string;
  status: string;
  pre_conviction: number | null;
  post_conviction: number | null;
  cds_score: number | null;
  message_count: number;
  turn_number: number;
  current_phase: string;
  start_time: number;
  end_time: number | null;
  followup_count: number;
  participant_name?: string;
  participant_email?: string;
  platform?: string;
  platform_participant_id?: string;
}

export interface AdminAnalyticsResponse {
  experiment_status: string;
  total_experiment_sessions: number;
  total_with_cds: number;
  target_sessions: number;
  progress_pct: number;
  arms: Record<string, ArmStats>;
  sally_lift: Record<string, number>;
  channels: Record<string, number>;
  platforms: Record<string, { total: number; has_cds: number; mean_cds: number | null }>;
  followups: {
    sessions_with_followups: number;
    avg_followups_per_session: number;
    total_sent: number;
  };
  sally_phase_distribution: Record<string, number>;
  recent_sessions: AdminSession[];
}

export async function getAdminAnalytics(): Promise<AdminAnalyticsResponse> {
  const res = await fetch(`${API_BASE}/admin/analytics`);
  if (!res.ok) throw new Error(`Failed to get admin analytics: ${res.statusText}`);
  return res.json();
}

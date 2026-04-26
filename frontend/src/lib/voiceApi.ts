const VOICE_API_BASE =
  (import.meta.env.VITE_VOICE_API_URL || "http://localhost:8001") + "/voice";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TokenResponse {
  token: string;
  url: string;
  roomName: string;
  callId: string;
}

export interface VoiceSessionListItem {
  call_id: string;
  arm: string;
  personality: string;
  forced: boolean;
  started_at: number;
  ended_at: number | null;
  duration_s: number | null;
  deepest_phase: string | null;
  ended_at_phase: string | null;
  session_ended: boolean;
  n_turns: number;
}

export interface VoiceTurn {
  turn_index: number;
  phase: string;
  phase_changed: boolean;
  user_text: string;
  sally_text: string;
  asr_ms: number | null;
  engine_dispatch_ms: number | null;
  engine_ms: number | null;
  tts_first_frame_ms: number | null;
  user_latency_ms: number | null;
  utterance_duration_ms: number | null;
  l1_model: string | null;
  user_emotion: string | null;
  tts_tier: string | null;
  audio_tags_used: string[] | null;
  expression_decorated: boolean;
  tag_director_used: boolean;
  tag_director_latency_ms: number | null;
  tag_director_fallback: string | null;
  thought_log: Record<string, unknown> | null;
  timestamp: number;
  ended: boolean;
}

export interface VoiceSessionDetail extends VoiceSessionListItem {
  turns: VoiceTurn[];
}

export interface LatencyStats {
  user_latency_p50_ms: number | null;
  user_latency_p95_ms: number | null;
  engine_p50_ms: number | null;
  engine_p95_ms: number | null;
  tts_first_frame_p50_ms: number | null;
  tts_first_frame_p95_ms: number | null;
}

export interface ArmAnalytics {
  total_sessions: number;
  avg_turns: number;
  deepest_phase_distribution: Record<string, number>;
  latency: LatencyStats;
  tts_tier_counts: Record<string, number>;
  top_audio_tags: Array<{ tag: string; count: number }>;
  tag_director: {
    used_count: number;
    fallback_count: number;
    fallback_rate: number;
    latency_p50_ms: number | null;
  };
}

export interface VoiceAnalytics {
  arms: Record<string, ArmAnalytics>;
  total_sessions: number;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

export async function mintLiveKitToken(
  forcedPersonality?: string | null
): Promise<TokenResponse> {
  const res = await fetch(`${VOICE_API_BASE}/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ forcedPersonality: forcedPersonality ?? null }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Token mint failed: ${res.status}`);
  }
  return res.json();
}

export async function listVoiceSessions(
  arm?: string
): Promise<VoiceSessionListItem[]> {
  const params = arm ? `?arm=${encodeURIComponent(arm)}` : "";
  const res = await fetch(`${VOICE_API_BASE}/sessions${params}`);
  if (!res.ok) throw new Error(`Failed to list sessions: ${res.statusText}`);
  return res.json();
}

export async function getVoiceSession(
  callId: string
): Promise<VoiceSessionDetail> {
  const res = await fetch(`${VOICE_API_BASE}/sessions/${encodeURIComponent(callId)}`);
  if (!res.ok) throw new Error(`Failed to get session: ${res.statusText}`);
  return res.json();
}

export async function getVoiceAnalytics(
  arm?: string
): Promise<VoiceAnalytics> {
  const params = arm ? `?arm=${encodeURIComponent(arm)}` : "";
  const res = await fetch(`${VOICE_API_BASE}/analytics${params}`);
  if (!res.ok) throw new Error(`Failed to get analytics: ${res.statusText}`);
  return res.json();
}

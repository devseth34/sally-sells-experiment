export type NEPQPhase = 
  | "CONNECTION"
  | "SITUATION" 
  | "PROBLEM_AWARENESS"
  | "SOLUTION_AWARENESS"
  | "CONSEQUENCE"
  | "OWNERSHIP"
  | "COMMITMENT"
  | "TERMINATED";

export type SessionStatus = "active" | "completed" | "abandoned";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  phase: NEPQPhase;
}

export interface Session {
  id: string;
  startTime: Date;
  endTime?: Date;
  status: SessionStatus;
  currentPhase: NEPQPhase;
  messages: Message[];
  convictionDelta?: number;
}

export interface PhaseConfig {
  label: string;
  description: string;
  color: string;
  bgColor: string;
  borderColor: string;
}

export interface Metrics {
  totalSessions: number;
  activeSessions: number;
  completedSessions: number;
  averageConvictionDelta: number;
  conversionRate: number;
  failureModes: FailureMode[];
}

export interface FailureMode {
  phase: NEPQPhase;
  reason: string;
  count: number;
  percentage: number;
}
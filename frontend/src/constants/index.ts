export const NEPQ_PHASES = [
  { key: "CONNECTION", label: "Connection", shortLabel: "1", color: "#3b82f6" },
  { key: "SITUATION", label: "Situation", shortLabel: "2", color: "#8b5cf6" },
  { key: "PROBLEM_AWARENESS", label: "Problem", shortLabel: "3", color: "#f59e0b" },
  { key: "SOLUTION_AWARENESS", label: "Solution", shortLabel: "4", color: "#10b981" },
  { key: "CONSEQUENCE", label: "Consequence", shortLabel: "5", color: "#ef4444" },
  { key: "OWNERSHIP", label: "Ownership", shortLabel: "6", color: "#ec4899" },
  { key: "COMMITMENT", label: "Commitment", shortLabel: "7", color: "#06b6d4" },
] as const;

export const PHASE_MAP = Object.fromEntries(
  NEPQ_PHASES.map((p) => [p.key, p])
);

export function getPhaseIndex(phaseKey: string): number {
  return NEPQ_PHASES.findIndex((p) => p.key === phaseKey);
}

export function getPhaseLabel(phaseKey: string): string {
  return PHASE_MAP[phaseKey]?.label ?? phaseKey;
}

export function getPhaseColor(phaseKey: string): string {
  return PHASE_MAP[phaseKey]?.color ?? "#71717a";
}
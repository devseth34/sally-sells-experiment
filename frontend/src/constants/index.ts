import type { NEPQPhase, PhaseConfig } from "../types";

export const PHASES: Record<NEPQPhase, PhaseConfig> = {
  CONNECTION: {
    label: "Connection",
    description: "Build rapport, establish context",
    color: "text-sky-400",
    bgColor: "bg-sky-500/10",
    borderColor: "border-sky-500/50",
  },
  SITUATION: {
    label: "Situation",
    description: "Understand current state",
    color: "text-blue-400",
    bgColor: "bg-blue-500/10",
    borderColor: "border-blue-500/50",
  },
  PROBLEM_AWARENESS: {
    label: "Problem",
    description: "Surface dissatisfaction",
    color: "text-amber-400",
    bgColor: "bg-amber-500/10",
    borderColor: "border-amber-500/50",
  },
  SOLUTION_AWARENESS: {
    label: "Solution",
    description: "Explore desired future",
    color: "text-emerald-400",
    bgColor: "bg-emerald-500/10",
    borderColor: "border-emerald-500/50",
  },
  CONSEQUENCE: {
    label: "Consequence",
    description: "Quantify cost of inaction",
    color: "text-red-400",
    bgColor: "bg-red-500/10",
    borderColor: "border-red-500/50",
  },
  OWNERSHIP: {
    label: "Ownership",
    description: "Prospect owns decision",
    color: "text-violet-400",
    bgColor: "bg-violet-500/10",
    borderColor: "border-violet-500/50",
  },
  COMMITMENT: {
    label: "Commitment",
    description: "Close to next step",
    color: "text-fuchsia-400",
    bgColor: "bg-fuchsia-500/10",
    borderColor: "border-fuchsia-500/50",
  },
  TERMINATED: {
    label: "Ended",
    description: "Session complete",
    color: "text-zinc-400",
    bgColor: "bg-zinc-500/10",
    borderColor: "border-zinc-500/50",
  },
};

export const PHASE_ORDER: NEPQPhase[] = [
  "CONNECTION",
  "SITUATION",
  "PROBLEM_AWARENESS",
  "SOLUTION_AWARENESS",
  "CONSEQUENCE",
  "OWNERSHIP",
  "COMMITMENT",
];
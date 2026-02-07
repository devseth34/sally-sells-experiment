import { cn } from "../../lib/utils";
import { PHASES, PHASE_ORDER } from "../../constants";
import type { NEPQPhase } from "../../types";
import { Check } from "lucide-react";

interface PhaseIndicatorProps {
  currentPhase: NEPQPhase;
}

export function PhaseIndicator({ currentPhase }: PhaseIndicatorProps) {
  const currentIndex = PHASE_ORDER.indexOf(currentPhase);

  return (
    <div className="flex items-center gap-1">
      {PHASE_ORDER.map((phase, index) => {
        const config = PHASES[phase];
        const isActive = phase === currentPhase;
        const isComplete = index < currentIndex;

        return (
          <div key={phase} className="flex items-center">
            <div
              className={cn(
                "flex items-center justify-center w-6 h-6 rounded-full text-[10px] font-medium transition-all",
                isActive && `${config.bgColor} ${config.color} ring-2 ring-offset-1 ring-offset-zinc-950 ${config.borderColor}`,
                isComplete && "bg-zinc-700 text-zinc-300",
                !isActive && !isComplete && "bg-zinc-800/50 text-zinc-600"
              )}
              title={config.label}
            >
              {isComplete ? <Check className="w-3 h-3" /> : index + 1}
            </div>
            {index < PHASE_ORDER.length - 1 && (
              <div
                className={cn(
                  "w-4 h-0.5 mx-0.5",
                  index < currentIndex ? "bg-zinc-600" : "bg-zinc-800"
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
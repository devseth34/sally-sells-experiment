import { NEPQ_PHASES, getPhaseIndex } from "../../constants";

interface PhaseIndicatorProps {
  currentPhase: string;
}

export function PhaseIndicator({ currentPhase }: PhaseIndicatorProps) {
  const activeIndex = getPhaseIndex(currentPhase);

  return (
    <div className="flex items-center gap-1">
      {NEPQ_PHASES.map((phase, i) => {
        const isActive = i === activeIndex;
        const isCompleted = i < activeIndex;

        return (
          <div key={phase.key} className="flex items-center">
            <div
              className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs transition-all"
              style={{
                background: isActive
                  ? `${phase.color}20`
                  : isCompleted
                  ? `${phase.color}10`
                  : "transparent",
                color: isActive
                  ? phase.color
                  : isCompleted
                  ? `${phase.color}99`
                  : "#52525b",
                borderWidth: 1,
                borderColor: isActive ? `${phase.color}40` : "transparent",
              }}
            >
              <span
                className="w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold"
                style={{
                  background: isActive || isCompleted ? phase.color : "#3f3f46",
                  color: isActive || isCompleted ? "#fff" : "#71717a",
                }}
              >
                {isCompleted ? "✓" : phase.shortLabel}
              </span>
              <span className="hidden sm:inline font-medium">{phase.label}</span>
            </div>
            {i < NEPQ_PHASES.length - 1 && (
              <div
                className="w-3 h-px mx-0.5"
                style={{
                  background: isCompleted ? phase.color : "#3f3f46",
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
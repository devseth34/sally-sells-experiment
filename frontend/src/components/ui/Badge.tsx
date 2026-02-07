import { cn } from "../../lib/utils";
import { PHASES } from "../../constants";
import type { NEPQPhase } from "../../types";

interface BadgeProps {
  phase: NEPQPhase;
  size?: "sm" | "md";
}

export function Badge({ phase, size = "md" }: BadgeProps) {
  const config = PHASES[phase];
  
  return (
    <span
      className={cn(
        "inline-flex items-center font-medium rounded border",
        config.bgColor,
        config.color,
        config.borderColor,
        {
          "text-[10px] px-1.5 py-0.5": size === "sm",
          "text-xs px-2 py-1": size === "md",
        }
      )}
    >
      {config.label}
    </span>
  );
}
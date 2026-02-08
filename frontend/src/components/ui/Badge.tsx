import { cn } from "../../lib/utils";
import type { HTMLAttributes, ReactNode } from "react";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  children: ReactNode;
  variant?: "default" | "success" | "warning" | "danger";
}

export function Badge({
  className,
  children,
  variant = "default",
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider",
        variant === "default" && "bg-zinc-800 text-zinc-300",
        variant === "success" && "bg-emerald-900/50 text-emerald-400",
        variant === "warning" && "bg-amber-900/50 text-amber-400",
        variant === "danger" && "bg-red-900/50 text-red-400",
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}
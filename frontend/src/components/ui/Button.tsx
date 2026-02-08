import { cn } from "../../lib/utils";
import type { ButtonHTMLAttributes, ReactNode } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md";
}

export function Button({
  className,
  children,
  variant = "primary",
  size = "md",
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-md font-medium transition-colors",
        "focus:outline-none focus:ring-1 focus:ring-zinc-500 disabled:opacity-50 disabled:pointer-events-none",
        variant === "primary" && "bg-white text-black hover:bg-zinc-200",
        variant === "secondary" && "bg-zinc-800 text-zinc-100 hover:bg-zinc-700 border border-zinc-700",
        variant === "ghost" && "text-zinc-400 hover:text-white hover:bg-zinc-800",
        size === "sm" && "h-8 px-3 text-xs",
        size === "md" && "h-10 px-4 text-sm",
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
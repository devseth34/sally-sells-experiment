import { cn } from "../../lib/utils";
import type { ButtonHTMLAttributes, ReactNode } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md" | "lg";
  children: ReactNode;
}

export function Button({ 
  variant = "primary", 
  size = "md", 
  className, 
  children, 
  ...props 
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center font-medium transition-all",
        "focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-zinc-900",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        {
          "bg-white text-zinc-900 hover:bg-zinc-200 focus:ring-white": variant === "primary",
          "bg-zinc-800 text-zinc-100 hover:bg-zinc-700 border border-zinc-700 focus:ring-zinc-500": variant === "secondary",
          "text-zinc-400 hover:text-white hover:bg-zinc-800 focus:ring-zinc-500": variant === "ghost",
        },
        {
          "text-xs px-2.5 py-1.5 rounded": size === "sm",
          "text-sm px-4 py-2 rounded-md": size === "md",
          "text-base px-6 py-3 rounded-lg": size === "lg",
        },
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
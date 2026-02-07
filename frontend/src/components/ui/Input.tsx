import { cn } from "../../lib/utils";
import type { InputHTMLAttributes } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {}

export function Input({ className, ...props }: InputProps) {
  return (
    <input
      className={cn(
        "w-full h-10 px-3 rounded-md text-sm",
        "bg-zinc-900 border border-zinc-800 text-white",
        "placeholder:text-zinc-500",
        "focus:outline-none focus:ring-1 focus:ring-zinc-600 focus:border-zinc-600",
        "transition-colors",
        className
      )}
      {...props}
    />
  );
}
"use client";
import { cn } from "@/lib/utils";

export function Badge({ children, variant="default", className }) {
  const variants = {
    default:  "bg-white/5 text-white/60 border-white/10",
    violet:   "bg-violet-500/15 text-violet-300 border-violet-500/25",
    success:  "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
    warning:  "bg-amber-500/15 text-amber-400 border-amber-500/25",
    error:    "bg-red-500/15 text-red-400 border-red-500/25",
    purple:   "bg-purple-500/15 text-purple-300 border-purple-500/25",
    indigo:   "bg-indigo-500/15 text-indigo-300 border-indigo-500/25",
  };
  return (
    <span className={cn("inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border text-xs font-mono font-medium", variants[variant], className)}>
      {children}
    </span>
  );
}

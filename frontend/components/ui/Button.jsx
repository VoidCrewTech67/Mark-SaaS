"use client";
import { cn } from "@/lib/utils";

export function Button({ children, variant="primary", size="md", className, disabled, loading, ...props }) {
  const base = "inline-flex items-center justify-center gap-2 font-semibold rounded-xl transition-all duration-200 focus:outline-none select-none whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed";

  const variants = {
    primary: "bg-violet-600 hover:bg-violet-500 active:scale-[0.98] text-white glow-button",
    secondary: "glass glass-hover text-white/80 hover:text-white",
    ghost: "text-white/50 hover:text-white hover:bg-white/5 rounded-lg",
    danger: "bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20",
  };

  const sizes = { sm:"text-xs px-3 py-1.5 h-7", md:"text-sm px-5 py-2.5 h-10", lg:"text-base px-7 py-3 h-12" };

  return (
    <button className={cn(base, variants[variant], sizes[size], className)} disabled={disabled||loading} {...props}>
      {loading && <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"/>}
      {children}
    </button>
  );
}

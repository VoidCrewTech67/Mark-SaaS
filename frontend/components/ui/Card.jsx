"use client";

import { cn } from "@/lib/utils";

export function Card({ children, className, ...props }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-zinc-800 bg-zinc-900/60 backdrop-blur-sm",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({ children, className }) {
  return (
    <div className={cn("flex items-center justify-between p-4 pb-0", className)}>
      {children}
    </div>
  );
}

export function CardContent({ children, className }) {
  return <div className={cn("p-4", className)}>{children}</div>;
}

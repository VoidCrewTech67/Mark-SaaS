"use client";

import { cn } from "@/lib/utils";

const STEPS = {
  uploading: { label: "Uploading…", pct: 25, color: "bg-indigo-500" },
  uploaded:  { label: "Queued", pct: 40, color: "bg-violet-500" },
  converting:{ label: "Converting…", pct: 70, color: "bg-indigo-500" },
  done:      { label: "Complete", pct: 100, color: "bg-emerald-500" },
  error:     { label: "Failed", pct: 100, color: "bg-red-500" },
};

export default function ConversionProgress({ status, filename }) {
  const step = STEPS[status] ?? STEPS.uploading;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-zinc-400 truncate max-w-[60%]">{filename}</span>
        <span
          className={cn(
            "text-xs font-mono font-medium",
            status === "error" ? "text-red-400" :
            status === "done" ? "text-emerald-400" : "text-zinc-400"
          )}
        >
          {step.label}
        </span>
      </div>
      {/* Progress bar */}
      <div className="h-1 w-full rounded-full bg-zinc-800 overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            step.color,
            status === "converting" || status === "uploading"
              ? "animate-pulse" : ""
          )}
          style={{ width: `${step.pct}%` }}
        />
      </div>
    </div>
  );
}

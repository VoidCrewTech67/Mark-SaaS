"use client";

import { cn } from "@/lib/utils";

export function Select({ value, onChange, options = [], label, className }) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {label && (
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-widest">
          {label}
        </span>
      )}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "w-full h-8 px-3 text-xs font-medium rounded-lg cursor-pointer",
          "bg-zinc-800 border border-zinc-700 text-zinc-100",
          "focus:outline-none focus:border-indigo-500 transition-colors"
        )}
      >
        {options.map((opt) => (
          <option key={opt.value ?? opt} value={opt.value ?? opt}>
            {opt.label ?? opt}
          </option>
        ))}
      </select>
    </div>
  );
}

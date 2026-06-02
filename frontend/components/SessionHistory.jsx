"use client";

import { Sparkles } from "lucide-react";
import { formatNumber } from "@/lib/utils";

export default function SessionHistory({ history, onClear }) {
  if (!history.length) return null;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-mono text-zinc-600 uppercase tracking-widest">
          Session History
        </span>
        <button
          onClick={onClear}
          className="text-[10px] text-zinc-700 hover:text-zinc-400 transition-colors font-mono"
        >
          Clear
        </button>
      </div>

      <div className="flex flex-col gap-1 max-h-48 overflow-y-auto pr-1">
        {history.map((item) => (
          <div
            key={item.id}
            className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-zinc-900/40 border border-zinc-800/60"
          >
            <div className="flex items-center gap-1.5 min-w-0">
              <span className={item.success ? "text-emerald-500" : "text-red-500"}>
                {item.success ? "✓" : "✗"}
              </span>
              <span className="text-xs text-zinc-400 truncate">{item.name}</span>
            </div>
            {item.success && item.tokens > 0 && (
              <span className="text-[10px] font-mono text-zinc-600 flex-shrink-0 ml-2">
                {formatNumber(item.tokens)} tok
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

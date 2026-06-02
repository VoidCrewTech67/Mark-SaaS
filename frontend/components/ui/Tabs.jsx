"use client";
import { useState } from "react";
import { cn } from "@/lib/utils";

export function Tabs({ tabs=[], defaultTab, className }) {
  const [active, setActive] = useState(defaultTab ?? tabs[0]?.key);
  const current = tabs.find(t => t.key === active);

  return (
    <div className={cn("flex flex-col", className)}>
      <div className="flex gap-1 p-1 rounded-xl bg-white/5 border border-white/[0.06]">
        {tabs.map(tab => (
          <button key={tab.key} onClick={() => setActive(tab.key)}
            className={cn(
              "flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-200 whitespace-nowrap",
              active === tab.key
                ? "bg-violet-600/80 text-white shadow-lg shadow-violet-900/40"
                : "text-white/40 hover:text-white/70"
            )}>
            {tab.icon && <span className="text-sm">{tab.icon}</span>}
            {tab.label}
          </button>
        ))}
      </div>
      <div className="pt-4">{current?.content}</div>
    </div>
  );
}

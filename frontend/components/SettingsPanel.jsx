"use client";

import { Select } from "@/components/ui/Select";
import { cn } from "@/lib/utils";

const OCR_OPTIONS = [
  { value: "Disabled", label: "Disabled — fastest" },
  { value: "Smart (Recommended)", label: "Smart — recommended" },
  { value: "Aggressive", label: "Aggressive — OCR everything" },
];

const CHUNK_OPTIONS = [
  { value: "None", label: "None — single output" },
  { value: "4K tokens", label: "4K — GPT-3.5 / small models" },
  { value: "8K tokens", label: "8K — GPT-4 / Claude" },
  { value: "16K tokens", label: "16K — most modern models" },
  { value: "Custom", label: "Custom size…" },
];

export default function SettingsPanel({
  ocrMode, setOcrMode,
  chunkPreset, setChunkPreset,
  customChunkSize, setCustomChunkSize,
  overlapPct, setOverlapPct,
}) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <p className="text-[10px] font-mono text-zinc-600 uppercase tracking-widest mb-3">
        Conversion Settings
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {/* OCR Mode */}
        <Select
          label="Embedded Image OCR"
          value={ocrMode}
          onChange={setOcrMode}
          options={OCR_OPTIONS}
        />

        {/* Smart Chunking */}
        <Select
          label="Smart Chunking"
          value={chunkPreset}
          onChange={setChunkPreset}
          options={CHUNK_OPTIONS}
        />
      </div>

      {/* Custom chunk size */}
      {chunkPreset === "Custom" && (
        <div className="mt-3 flex flex-col gap-1">
          <span className="text-xs font-mono text-zinc-500 uppercase tracking-widest">
            Custom token limit
          </span>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={500}
              max={128000}
              step={500}
              value={customChunkSize}
              onChange={(e) => setCustomChunkSize(Number(e.target.value))}
              className={cn(
                "w-full h-8 px-3 text-xs font-mono rounded-lg",
                "bg-zinc-800 border border-zinc-700 text-zinc-100",
                "focus:outline-none focus:border-indigo-500 transition-colors"
              )}
            />
            <span className="text-xs text-zinc-600 whitespace-nowrap">tokens</span>
          </div>
        </div>
      )}

      {/* Overlap slider */}
      {chunkPreset !== "None" && (
        <div className="mt-3 flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-zinc-500 uppercase tracking-widest">
              Chunk Overlap
            </span>
            <span className="text-xs font-mono text-zinc-400">~{overlapPct}%</span>
          </div>
          <input
            type="range"
            min={0}
            max={25}
            step={5}
            value={overlapPct}
            onChange={(e) => setOverlapPct(Number(e.target.value))}
            className="w-full h-1.5 accent-indigo-500 cursor-pointer"
          />
          <p className="text-[10px] text-zinc-600">
            {overlapPct}% of each chunk repeated at the start of the next for context continuity.
          </p>
        </div>
      )}
    </div>
  );
}

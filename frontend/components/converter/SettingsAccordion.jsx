"use client";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, Settings2 } from "lucide-react";

const OCR_OPTIONS = [
  { value: "Disabled",             label: "Disabled — fastest" },
  { value: "Smart (Recommended)",  label: "Smart — recommended" },
  { value: "Aggressive",           label: "Aggressive — OCR everything" },
];
const CHUNK_OPTIONS = [
  { value: "None",       label: "None — single output" },
  { value: "4K tokens",  label: "4K — GPT-3.5 / small models" },
  { value: "8K tokens",  label: "8K — GPT-4 / Claude" },
  { value: "16K tokens", label: "16K — most modern models" },
  { value: "Custom",     label: "Custom size…" },
];

export default function SettingsAccordion({
  ocrMode, setOcrMode,
  chunkPreset, setChunkPreset,
  customChunkSize, setCustomChunkSize,
  overlapPct, setOverlapPct,
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-2xl overflow-hidden" style={{ border: "1px solid rgba(255,255,255,0.07)" }}>
      {/* Toggle */}
      <button onClick={() => setOpen(p => !p)}
        className="w-full flex items-center justify-between px-6 py-4 transition-all duration-200 group"
        style={{ background: open ? "rgba(139,92,246,0.06)" : "rgba(255,255,255,0.02)" }}>
        <div className="flex items-center gap-3">
          <Settings2 className="w-4 h-4" style={{ color: "#8B5CF6" }}/>
          <span className="text-sm font-semibold text-white">Advanced Options</span>
          <span className="text-xs px-2 py-0.5 rounded-full font-mono" style={{ background: "rgba(139,92,246,0.12)", color: "#A78BFA" }}>
            OCR · Chunking · Overlap
          </span>
        </div>
        <motion.div animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.25 }}>
          <ChevronDown className="w-4 h-4" style={{ color: "#6B7280" }}/>
        </motion.div>
      </button>

      {/* Expandable content */}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div key="content" initial={{ height:0, opacity:0 }} animate={{ height:"auto", opacity:1 }}
            exit={{ height:0, opacity:0 }} transition={{ duration:0.3, ease:[0.22,1,0.36,1] }}
            className="overflow-hidden">
            <div className="px-6 py-5 grid grid-cols-1 sm:grid-cols-2 gap-6"
              style={{ background: "rgba(255,255,255,0.015)", borderTop: "1px solid rgba(255,255,255,0.06)" }}>

              {/* OCR Mode */}
              <Field label="Embedded Image OCR" hint="Heuristic filtering keeps only meaningful text">
                <select value={ocrMode} onChange={e => setOcrMode(e.target.value)}>
                  {OCR_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </Field>

              {/* Chunking */}
              <Field label="Smart Chunking" hint="Heading-aware splits with configurable size">
                <select value={chunkPreset} onChange={e => setChunkPreset(e.target.value)}>
                  {CHUNK_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </Field>

              {/* Custom size */}
              {chunkPreset === "Custom" && (
                <Field label="Custom Token Limit" hint="Tokens per chunk">
                  <div className="flex items-center gap-2">
                    <input type="number" min={500} max={128000} step={500} value={customChunkSize}
                      onChange={e => setCustomChunkSize(Number(e.target.value))}
                      className="flex-1 h-9 px-3 text-sm font-mono rounded-xl outline-none transition-all duration-200"
                      style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)", color: "#D1D5DB" }}/>
                    <span className="text-xs font-mono" style={{ color: "#6B7280" }}>tokens</span>
                  </div>
                </Field>
              )}

              {/* Overlap */}
              {chunkPreset !== "None" && (
                <Field label={`Chunk Overlap — ${overlapPct}%`} hint="Context repeated at chunk boundaries">
                  <input type="range" min={0} max={25} step={5} value={overlapPct}
                    onChange={e => setOverlapPct(Number(e.target.value))} className="w-full"/>
                </Field>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-semibold" style={{ color: "#D1D5DB" }}>{label}</label>
      {hint && <p className="text-[10px]" style={{ color: "#6B7280" }}>{hint}</p>}
      {children}
    </div>
  );
}

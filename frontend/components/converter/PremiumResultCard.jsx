"use client";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, XCircle, ChevronDown, Copy, Check, Download, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Tabs } from "@/components/ui/Tabs";
import { formatBytes, formatNumber, stemName } from "@/lib/utils";

const STATUS_BAR = {
  uploading:  { label:"Uploading…",  pct:25,  color:"#8B5CF6" },
  uploaded:   { label:"Queued",      pct:40,  color:"#6366F1" },
  converting: { label:"Converting…", pct:70,  color:"#8B5CF6" },
  done:       { label:"Complete",    pct:100, color:"#10B981" },
  error:      { label:"Failed",      pct:100, color:"#EF4444" },
};

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  return (
    <button onClick={async () => { try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch{} }}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs transition-all duration-200 font-medium"
      style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)", color: copied ? "#10B981" : "#94A3B8" }}>
      {copied ? <Check className="w-3 h-3"/> : <Copy className="w-3 h-3"/>}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export default function PremiumResultCard({ entry, chunkPreset, chunkSize, overlapPct, onGenerateChunks, onDownloadMd, onDownloadZip, onRemove }) {
  const [expanded, setExpanded] = useState(false);
  const [expandedChunk, setExpandedChunk] = useState(null);
  const { clientId, status, file, originalName, result, error, sizeBytes, chunks, chunkStatus, chunkError } = entry;

  const displayName = originalName || file?.name || clientId;
  const isDone = status === "done";
  const isError = status === "error";
  const isActive = ["uploading","uploaded","converting"].includes(status);
  const bar = STATUS_BAR[status] || STATUS_BAR.uploading;
  const optStats = result?.optimization_stats;
  const optMd = result?.optimized_markdown;

  const tabs = isDone ? [
    {
      key:"preview", label:"Preview", icon:"📝",
      content: (
        <div className="flex flex-col gap-4">
          {/* Stats */}
          {result && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[["Tokens", formatNumber(result.token_estimate), "#8B5CF6"],
                ["Words", formatNumber(result.word_count), "#6366F1"],
                ["Chars", formatNumber(result.char_count), "#A855F7"],
                ["Time", `${result.duration_s?.toFixed(2)}s`, "#10B981"]].map(([l,v,c]) => (
                <div key={l} className="p-3 rounded-xl text-center" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}>
                  <p className="text-base font-mono font-bold" style={{ color: c }}>{v}</p>
                  <p className="text-[10px] mt-0.5" style={{ color: "#6B7280" }}>{l}</p>
                </div>
              ))}
            </div>
          )}
          {/* OCR badges */}
          {(result?.ocr_used || result?.embedded_images_ocr_count > 0) && (
            <div className="flex flex-wrap gap-2">
              {result.ocr_used && <Badge variant="warning">⚡ OCR Fallback</Badge>}
              {result.embedded_images_ocr_count > 0 && <Badge variant="purple">🖼 {result.embedded_images_ocr_count} Images OCR&apos;d</Badge>}
            </div>
          )}
          {/* Markdown preview */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono" style={{ color: "#6B7280" }}>Raw output (preview)</span>
              <CopyButton text={result?.markdown || ""}/>
            </div>
            <pre className="md-output max-h-64 overflow-y-auto p-4 rounded-xl"
              style={{ background: "rgba(0,0,0,0.4)", border: "1px solid rgba(255,255,255,0.07)" }}>
              {(result?.markdown || "").slice(0, 4000)}{(result?.markdown || "").length > 4000 ? "\n\n… (truncated)" : ""}
            </pre>
          </div>
          <button onClick={() => onDownloadMd(clientId)}
            className="flex items-center gap-2 w-fit px-4 py-2 rounded-xl text-sm font-semibold text-white transition-all duration-200 hover:scale-[1.02]"
            style={{ background: "rgba(139,92,246,0.2)", border: "1px solid rgba(139,92,246,0.3)" }}>
            <Download className="w-4 h-4"/> Download .md
          </button>
        </div>
      ),
    },
    {
      key:"optimized", label:"Optimized", icon:"✨",
      content: (
        <div className="flex flex-col gap-4">
          {optStats && (
            <div className="grid grid-cols-4 gap-3">
              {[["Before", formatNumber(optStats.original_tokens), false],
                ["After", formatNumber(optStats.optimized_tokens), false],
                ["Saved", formatNumber(optStats.tokens_saved), true],
                ["–%", `${optStats.percent_saved}%`, true]].map(([l,v,accent]) => (
                <div key={l} className="p-3 rounded-xl text-center" style={{ background: accent ? "rgba(16,185,129,0.08)" : "rgba(255,255,255,0.03)", border: accent ? "1px solid rgba(16,185,129,0.2)" : "1px solid rgba(255,255,255,0.07)" }}>
                  <p className="text-base font-mono font-bold" style={{ color: accent ? "#10B981" : "#D1D5DB" }}>{v}</p>
                  <p className="text-[10px] mt-0.5" style={{ color: "#6B7280" }}>{l}</p>
                </div>
              ))}
            </div>
          )}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono" style={{ color: "#6B7280" }}>Optimized output</span>
              <CopyButton text={optMd || result?.markdown || ""}/>
            </div>
            <pre className="md-output max-h-64 overflow-y-auto p-4 rounded-xl"
              style={{ background: "rgba(0,0,0,0.4)", border: "1px solid rgba(255,255,255,0.07)" }}>
              {(optMd || result?.markdown || "").slice(0, 4000)}
            </pre>
          </div>
          <button onClick={() => { const b = new Blob([optMd || result?.markdown || ""], {type:"text/markdown"}); const u = URL.createObjectURL(b); const a = document.createElement("a"); a.href=u; a.download=stemName(displayName)+"_optimized.md"; a.click(); URL.revokeObjectURL(u); }}
            className="flex items-center gap-2 w-fit px-4 py-2 rounded-xl text-sm font-semibold text-white transition-all duration-200 hover:scale-[1.02]"
            style={{ background: "rgba(16,185,129,0.15)", border: "1px solid rgba(16,185,129,0.3)", color: "#10B981" }}>
            <Download className="w-4 h-4"/> Download Optimized
          </button>
        </div>
      ),
    },
    {
      key:"chunks", label:"Chunks", icon:"🔀",
      content: (
        <div className="flex flex-col gap-3">
          {chunkPreset === "None" ? (
            <p className="text-sm" style={{ color: "#6B7280" }}>Enable chunking in Advanced Options to split this document.</p>
          ) : !chunks && chunkStatus !== "loading" ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm" style={{ color: "#94A3B8" }}>Split into ≤{formatNumber(chunkSize)} token chunks with {overlapPct}% overlap.</p>
              <button onClick={() => onGenerateChunks(clientId)} disabled={chunkStatus === "loading"}
                className="flex items-center gap-2 w-fit px-4 py-2 rounded-xl text-sm font-semibold transition-all duration-200"
                style={{ background: "rgba(139,92,246,0.15)", border: "1px solid rgba(139,92,246,0.3)", color: "#A78BFA" }}>
                {chunkStatus === "loading" ? <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"/> : "🔀"}
                Generate Chunks
              </button>
            </div>
          ) : chunkStatus === "error" ? (
            <p className="text-sm text-red-400">Error: {chunkError}</p>
          ) : chunkStatus === "loading" ? (
            <div className="flex items-center gap-2 text-sm" style={{ color: "#94A3B8" }}>
              <span className="w-4 h-4 border-2 border-violet-500 border-t-transparent rounded-full animate-spin"/>
              Generating chunks…
            </div>
          ) : chunks?.chunks?.length ? (
            <>
              <div className="flex items-center justify-between flex-wrap gap-3">
                <p className="text-sm" style={{ color: "#94A3B8" }}>
                  <span className="font-mono font-bold text-white">{chunks.chunk_count}</span> chunks · ≤{formatNumber(chunks.max_tokens)} tokens · {chunks.source}
                </p>
                <button onClick={() => onDownloadZip(clientId)}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all duration-200"
                  style={{ background: "rgba(139,92,246,0.15)", border: "1px solid rgba(139,92,246,0.3)", color: "#A78BFA" }}>
                  <Download className="w-4 h-4"/> Download ZIP
                </button>
              </div>
              <div className="flex flex-col gap-1.5 max-h-80 overflow-y-auto">
                {chunks.chunks.map((chunk, i) => (
                  <div key={i} className="rounded-xl overflow-hidden" style={{ border: "1px solid rgba(255,255,255,0.07)" }}>
                    <button onClick={() => setExpandedChunk(expandedChunk === i ? null : i)}
                      className="w-full flex items-center justify-between px-4 py-2.5 text-sm transition-all duration-150 hover:bg-white/5">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs" style={{ color: "#8B5CF6" }}>#{String(i+1).padStart(3,"0")}</span>
                        <span style={{ color: "#94A3B8" }}>~{chunk.split(/\s+/).length.toLocaleString()} words</span>
                      </div>
                      <ChevronRight className={`w-4 h-4 transition-transform duration-200 ${expandedChunk === i ? "rotate-90" : ""}`} style={{ color: "#6B7280" }}/>
                    </button>
                    <AnimatePresence>
                      {expandedChunk === i && (
                        <motion.div initial={{ height:0 }} animate={{ height:"auto" }} exit={{ height:0 }}
                          className="overflow-hidden" transition={{ duration:0.25 }}>
                          <pre className="md-output px-4 pb-3 max-h-40 overflow-y-auto text-xs border-t"
                            style={{ borderColor: "rgba(255,255,255,0.06)", background: "rgba(0,0,0,0.3)" }}>
                            {chunk.slice(0,1500)}{chunk.length > 1500 ? "\n…" : ""}
                          </pre>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                ))}
              </div>
            </>
          ) : null}
        </div>
      ),
    },
    {
      key:"raw", label:"Raw", icon:"⬛",
      content: (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono" style={{ color: "#6B7280" }}>Raw markdown text</span>
            <CopyButton text={result?.markdown || ""}/>
          </div>
          <textarea readOnly value={result?.markdown || ""} rows={12}/>
        </div>
      ),
    },
  ] : [];

  return (
    <motion.div layout initial={{ opacity:0, y:20 }} animate={{ opacity:1, y:0 }}
      exit={{ opacity:0, y:-10 }} transition={{ duration:0.4, ease:[0.22,1,0.36,1] }}
      className="rounded-2xl overflow-hidden"
      style={{ background: "rgba(255,255,255,0.025)", border: `1px solid ${isDone ? "rgba(139,92,246,0.25)" : isError ? "rgba(239,68,68,0.25)" : "rgba(255,255,255,0.07)"}` }}>

      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 gap-3">
        <div className="flex items-center gap-3 min-w-0">
          {isDone ? <CheckCircle2 className="w-4 h-4 flex-shrink-0" style={{ color: "#10B981" }}/>
            : isError ? <XCircle className="w-4 h-4 flex-shrink-0" style={{ color: "#EF4444" }}/>
            : <div className="w-4 h-4 rounded-full border-2 border-violet-500 border-t-transparent animate-spin flex-shrink-0"/>}
          <span className="text-sm font-semibold text-white truncate font-mono">{displayName}</span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {isDone && result && <>
            <Badge variant="violet">{result.duration_s?.toFixed(2)}s</Badge>
            <Badge variant="indigo">{formatNumber(result.token_estimate)} tok</Badge>
            {(result.ocr_used || result.embedded_images_ocr_count > 0) && <Badge variant="purple">OCR</Badge>}
          </>}
          {sizeBytes && <Badge variant="default">{formatBytes(sizeBytes)}</Badge>}
          <button onClick={() => onRemove(clientId)}
            className="p-1.5 rounded-lg text-white/25 hover:text-white/60 hover:bg-white/10 transition-all duration-150">
            <XCircle className="w-4 h-4"/>
          </button>
        </div>
      </div>

      {/* Progress bar */}
      {(isActive || isDone || isError) && (
        <div className="px-5 pb-3">
          <div className="h-0.5 w-full rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
            <motion.div className="h-full rounded-full" animate={{ width: `${bar.pct}%` }}
              transition={{ duration:0.6, ease:"easeOut" }} style={{ background: bar.color, boxShadow: `0 0 8px ${bar.color}60` }}/>
          </div>
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="mx-5 mb-4 px-4 py-3 rounded-xl text-sm" style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#FCA5A5" }}>
          {error}
        </div>
      )}

      {/* Expand toggle for done */}
      {isDone && (
        <button onClick={() => setExpanded(p => !p)}
          className="w-full flex items-center justify-between px-5 py-3 text-xs transition-all duration-200 hover:bg-white/5"
          style={{ borderTop: "1px solid rgba(255,255,255,0.06)", color: "#6B7280" }}>
          <span className="font-mono">View results</span>
          <motion.div animate={{ rotate: expanded ? 180 : 0 }} transition={{ duration:0.2 }}>
            <ChevronDown className="w-4 h-4"/>
          </motion.div>
        </button>
      )}

      {/* Expandable tabs */}
      <AnimatePresence>
        {expanded && isDone && (
          <motion.div initial={{ height:0, opacity:0 }} animate={{ height:"auto", opacity:1 }}
            exit={{ height:0, opacity:0 }} transition={{ duration:0.35, ease:[0.22,1,0.36,1] }}
            className="overflow-hidden">
            <div className="px-5 py-5" style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
              <Tabs tabs={tabs} defaultTab="preview"/>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

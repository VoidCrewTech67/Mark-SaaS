"use client";
import { useEffect, useRef, useState } from "react";
import Navbar from "@/components/Navbar";
import Sidebar from "@/components/Sidebar";
import UploadZone from "@/components/UploadZone";
import ResultCard from "@/components/ResultCard";
import { useConversion } from "@/hooks/useConversion";
import { buildZipFromStrings } from "@/lib/clientZip";
import { triggerDownload } from "@/services/api";
import { stemName } from "@/lib/utils";

// ── Document type options ─────────────────────────────────────────────────────
const DOC_TYPE_OPTS = [
  {
    value: "research_paper",
    icon: "🔬",
    label: "Research Paper",
    sub: "Academic · Optimized",
    desc: <>Optimized for <strong>academic papers</strong>. Removes references, acknowledgements, and boilerplate. Preserves title, abstract, equations, tables, and section hierarchy.</>,
  },
  {
    value: "general_document",
    icon: "📋",
    label: "General Document",
    sub: "MarkItDown · Universal",
    desc: <>Uses <strong>Microsoft MarkItDown</strong> for fast, universal extraction. Works with PDF, DOCX, PPTX, XLSX, HTML, and more. Best for non-academic documents.</>,
  },
];

// ── Optimization mode options (research paper only) ───────────────────────────
const OPT_MODE_OPTS = [
  {
    value: "safe",
    label: "Safe",
    desc: "Cleanup only — remove page numbers, repeated headers/footers, normalize whitespace, merge broken lines. Preserves everything else.",
    reduction: "5-10%",
  },
  {
    value: "balanced",
    label: "Balanced",
    desc: "Safe + remove references, bibliography, acknowledgements, funding sections, and copyright notices. Recommended default.",
    reduction: "15-40%",
    recommended: true,
  },
  {
    value: "aggressive",
    label: "Aggressive",
    desc: "Balanced + remove appendices, supplementary material, collapse figure descriptions, strip conference boilerplate and metadata.",
    reduction: "30-60%",
  },
  {
    value: "rag",
    label: "RAG",
    desc: "Balanced reductions + structured section extraction with metadata. Optimized for retrieval-augmented generation pipelines.",
    reduction: "Structured",
  },
];

// ── OCR options ───────────────────────────────────────────────────────────────
const OCR_OPTS = [
  {
    value: "Disabled",
    label: "Disabled",
    desc: "Do not run OCR on embedded images. Fastest processing. Use when documents contain no meaningful images.",
  },
  {
    value: "Smart (Recommended)",
    label: "Smart",
    desc: <>Selective image scanning. Uses heuristics to skip logos, icons, and decorative graphics. <strong>Best balance of speed and accuracy.</strong></>,
  },
  {
    value: "Aggressive",
    label: "Aggressive",
    desc: "Scan every extracted image. Maximum OCR coverage. Slower processing with higher CPU usage.",
  },
];

// ── Chunk options ──────────────────────────────────────────────────────────────
const CHUNK_OPTS = [
  { value: "None",      label: "None",    desc: "Single markdown output. No chunking applied." },
  { value: "4K tokens", label: "4K",      desc: "Optimized for GPT-3.5, GPT-4o Mini, and Gemini Flash." },
  { value: "8K tokens", label: "8K",      desc: "Optimized for GPT-4o, Claude Sonnet, and Gemini Pro." },
  { value: "16K tokens",label: "16K",     desc: "Optimized for Claude Opus, GPT-4o, and long-context workflows." },
  { value: "Custom",    label: "Custom",  desc: "Define your own chunk size in tokens." },
];

export default function HomePage() {
  const conv = useConversion();
  const {
    entryList, processFiles, generateChunks, downloadMd, downloadChunksZip,
    clearAll, clearEntry,
    documentType, setDocumentType,
    optimizationMode, setOptimizationMode,
    ocrMode, setOcrMode,
    chunkPreset, setChunkPreset,
    customChunkSize, setCustomChunkSize, overlapPct, setOverlapPct, chunkSize,
  } = conv;

  const [health, setHealth] = useState(null);
  // Track which card to auto-expand (the latest completed one)
  const [expandedId, setExpandedId] = useState(null);
  const prevDoneRef = useRef(new Set());

  const isProcessing = entryList.some(e => ["uploading","uploaded","converting"].includes(e.status));
  const successful = entryList.filter(e => e.status === "done" && e.result);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/health`)
      .then(r => r.json()).then(setHealth).catch(() => {});
  }, []);

  // Auto-expand: detect newly completed entries, expand the latest one
  useEffect(() => {
    const currentDoneIds = new Set(
      entryList.filter(e => e.status === "done").map(e => e.clientId)
    );
    const newlyDone = [...currentDoneIds].filter(id => !prevDoneRef.current.has(id));
    if (newlyDone.length > 0) {
      // Expand the last one (most recent in process order)
      setExpandedId(newlyDone[newlyDone.length - 1]);
    }
    prevDoneRef.current = currentDoneIds;
  }, [entryList]);

  const handleDownloadAll = async () => {
    if (!successful.length) return;
    const items = successful.map(e => [stemName(e.originalName || "doc") + ".md", e.result?.markdown || ""]);
    const blob = await buildZipFromStrings(items);
    triggerDownload(blob, "markitdown_all.zip");
  };

  const docTypeSelected = DOC_TYPE_OPTS.find(o => o.value === documentType) || DOC_TYPE_OPTS[1];
  const optModeSelected = OPT_MODE_OPTS.find(o => o.value === optimizationMode) || OPT_MODE_OPTS[1];
  const ocrSelected = OCR_OPTS.find(o => o.value === ocrMode) || OCR_OPTS[1];
  const chunkSelected = CHUNK_OPTS.find(o => o.value === chunkPreset) || CHUNK_OPTS[0];

  const isResearchPaper = documentType === "research_paper";

  return (
    <div className="app-shell">
      <Sidebar health={health} />
      <div className="main-wrap">
        <Navbar />
        <div className="main-scroll">
          <div className="page">

            {/* Hero */}
            <div className="hero">
              <div className="hero-badge">⚡ Powered by Microsoft MarkItDown</div>
              <h1>Document <span>→</span> Markdown</h1>
              <p>Convert any file into AI-ready Markdown with OCR, token optimization, embedded image extraction, and smart chunking.</p>
            </div>

            {/* Upload */}
            <UploadZone onConvert={processFiles} disabled={isProcessing} />

            {/* Document Type selector — full width above settings grid */}
            <div style={{
              background: "var(--bg-2)", borderRadius: 10, padding: "14px 16px",
              marginBottom: 14, border: "1px solid var(--border)"
            }}>
              <div className="settings-card-title">Document Type</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {DOC_TYPE_OPTS.map(o => {
                  const sel = documentType === o.value;
                  return (
                    <div
                      key={o.value}
                      onClick={() => setDocumentType(o.value)}
                      style={{
                        display: "flex", flexDirection: "column", gap: 4,
                        padding: "14px 16px", borderRadius: 8, cursor: "pointer",
                        border: sel ? "1.5px solid var(--purple)" : "1.5px solid var(--border)",
                        background: sel ? "var(--purple-dim)" : "var(--bg-3)",
                        transition: "all .2s", userSelect: "none",
                        boxShadow: sel ? "0 0 0 1px rgba(139,92,246,.1)" : "none",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 18 }}>{o.icon}</span>
                        <span style={{
                          fontSize: 13, fontWeight: 700,
                          color: sel ? "var(--purple)" : "var(--text)"
                        }}>{o.label}</span>
                      </div>
                      <span style={{
                        fontSize: 10, fontWeight: 500,
                        color: sel ? "var(--purple)" : "var(--text-3)",
                        opacity: sel ? 0.75 : 1,
                      }}>{o.sub}</span>
                    </div>
                  );
                })}
              </div>
              <div style={{
                fontSize: 11, color: "var(--text-3)", lineHeight: 1.55,
                marginTop: 10, minHeight: 32
              }}>{docTypeSelected.desc}</div>
            </div>

            {/* Settings grid */}
            <div className="settings-grid">

              {/* OCR card — only for General Document */}
              {!isResearchPaper && (
                <div className="settings-card">
                  <div className="settings-card-title">Embedded Image OCR</div>
                  <div className="ocr-options">
                    {OCR_OPTS.map(o => (
                      <button
                        key={o.value}
                        className={`ocr-option${ocrMode === o.value ? " selected" : ""}`}
                        onClick={() => setOcrMode(o.value)}
                      >
                        {o.label}
                      </button>
                    ))}
                  </div>
                  <div className="option-desc">{ocrSelected.desc}</div>
                </div>
              )}

              {/* Optimization Mode card — works for all document types */}
              {(
                <div className="settings-card">
                  <div className="settings-card-title">Optimization Mode</div>
                  <div style={{ display: "flex", gap: 5 }}>
                    {OPT_MODE_OPTS.map(o => {
                      const sel = optimizationMode === o.value;
                      return (
                        <button
                          key={o.value}
                          onClick={() => setOptimizationMode(o.value)}
                          style={{
                            flex: 1, padding: "7px 8px", borderRadius: 7,
                            border: sel ? "1px solid var(--purple)" : "1px solid var(--border)",
                            background: sel ? "var(--purple-dim)" : "var(--bg-3)",
                            cursor: "pointer", fontSize: 11, fontWeight: 500,
                            color: sel ? "var(--purple)" : "var(--text-2)",
                            textAlign: "center", transition: "all .15s",
                            userSelect: "none", fontFamily: "inherit",
                          }}
                        >
                          {o.label}{o.recommended ? " ✦" : ""}
                        </button>
                      );
                    })}
                  </div>
                  <div className="option-desc">
                    {optModeSelected.desc}
                    {optModeSelected.reduction && (
                      <span style={{ display: "block", marginTop: 4, fontSize: 10, color: "var(--purple)", fontWeight: 600 }}>
                        Expected reduction: {optModeSelected.reduction}
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* Chunking card — always visible */}
              <div className="settings-card">
                <div className="settings-card-title">Smart Chunking</div>
                <div className="chunk-presets">
                  {CHUNK_OPTS.map(o => (
                    <button
                      key={o.value}
                      className={`chunk-preset-btn${chunkPreset === o.value ? " selected" : ""}`}
                      onClick={() => setChunkPreset(o.value)}
                    >
                      {o.label}
                    </button>
                  ))}
                </div>
                <div className="option-desc">{chunkSelected.desc}</div>
                {chunkPreset === "Custom" && (
                  <div className="chunk-custom-row">
                    <label>Tokens</label>
                    <input type="number" min={500} max={128000} step={500}
                      value={customChunkSize}
                      onChange={e => setCustomChunkSize(Number(e.target.value))} />
                  </div>
                )}
                {chunkPreset !== "None" && (
                  <div className="chunk-custom-row">
                    <label>Overlap — {overlapPct}%</label>
                    <input type="range" min={0} max={25} step={5}
                      value={overlapPct}
                      onChange={e => setOverlapPct(Number(e.target.value))} />
                  </div>
                )}
              </div>

            </div>

            {/* Results header */}
            {entryList.length > 0 && (
              <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:8 }}>
                <span style={{ fontSize:11.5, fontWeight:600, color:"var(--text-2)" }}>
                  Results — {entryList.length} file{entryList.length !== 1 ? "s" : ""}
                </span>
                <div style={{ display:"flex", gap:5 }}>
                  {successful.length > 1 && (
                    <button className="btn btn-ghost btn-sm" onClick={handleDownloadAll}>⬇ Download All</button>
                  )}
                  <button className="btn btn-ghost btn-sm" onClick={clearAll}>✕ Clear All</button>
                </div>
              </div>
            )}

            {/* Results */}
            {entryList.length > 0 ? (
              <div className="results">
                {entryList.map((entry) => (
                  <ResultCard
                    key={entry.clientId}
                    entry={entry}
                    isActive={entry.clientId === expandedId}
                    chunkPreset={chunkPreset}
                    chunkSize={chunkSize}
                    overlapPct={overlapPct}
                    onGenerateChunks={generateChunks}
                    onDownloadMd={downloadMd}
                    onDownloadZip={downloadChunksZip}
                    onRemove={clearEntry}
                  />
                ))}
              </div>
            ) : (
              <div className="empty-state">
                <span className="empty-icon">📂</span>
                <div className="empty-title">No files uploaded</div>
                <div className="empty-sub">Upload documents above to begin conversion.</div>
              </div>
            )}

          </div>
        </div>
      </div>
    </div>
  );
}


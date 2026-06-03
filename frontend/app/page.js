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
    clearAll, clearEntry, ocrMode, setOcrMode, chunkPreset, setChunkPreset,
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

  const ocrSelected = OCR_OPTS.find(o => o.value === ocrMode) || OCR_OPTS[1];
  const chunkSelected = CHUNK_OPTS.find(o => o.value === chunkPreset) || CHUNK_OPTS[0];

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

            {/* Settings grid */}
            <div className="settings-grid">

              {/* OCR card */}
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

              {/* Chunking card */}
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

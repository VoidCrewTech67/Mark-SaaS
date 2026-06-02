"use client";
import { useEffect, useState } from "react";
import Navbar from "@/components/Navbar";
import Sidebar from "@/components/Sidebar";
import UploadZone from "@/components/UploadZone";
import ResultCard from "@/components/ResultCard";
import { useConversion } from "@/hooks/useConversion";
import { buildZipFromStrings } from "@/lib/clientZip";
import { triggerDownload } from "@/services/api";
import { stemName } from "@/lib/utils";

const OCR_OPTS = [
  { value: "Disabled", label: "Disabled" },
  { value: "Smart (Recommended)", label: "Smart (Recommended)" },
  { value: "Aggressive", label: "Aggressive" },
];
const CHUNK_OPTS = [
  { value: "None", label: "None" },
  { value: "4K tokens", label: "4K tokens" },
  { value: "8K tokens", label: "8K tokens" },
  { value: "16K tokens", label: "16K tokens" },
  { value: "Custom", label: "Custom" },
];

export default function HomePage() {
  const conv = useConversion();
  const {
    entryList, processFiles, generateChunks, downloadMd, downloadChunksZip,
    clearAll, clearEntry, ocrMode, setOcrMode, chunkPreset, setChunkPreset,
    customChunkSize, setCustomChunkSize, overlapPct, setOverlapPct, chunkSize,
  } = conv;

  const [health, setHealth] = useState(null);
  const isProcessing = entryList.some(e => ["uploading","uploaded","converting"].includes(e.status));
  const successful = entryList.filter(e => e.status === "done" && e.result);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/health`)
      .then(r => r.json()).then(setHealth).catch(() => {});
  }, []);

  // Auto-expand logic: expand all if <=3, else expand first only
  const shouldAutoExpand = (index) => {
    const doneCount = entryList.filter(e => e.status === "done").length;
    if (doneCount <= 3) return true;
    // Find first done entry
    const firstDoneIdx = entryList.findIndex(e => e.status === "done");
    return index === firstDoneIdx;
  };

  const handleDownloadAll = async () => {
    if (!successful.length) return;
    const items = successful.map(e => [stemName(e.originalName||"doc")+".md", e.result?.markdown||""]);
    const blob = await buildZipFromStrings(items);
    triggerDownload(blob, "markitdown_all.zip");
  };

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

            {/* Options row */}
            <div className="options-row">
              <div className="opt-group">
                <span className="opt-label">Embedded Image OCR</span>
                <select value={ocrMode} onChange={e => setOcrMode(e.target.value)}>
                  {OCR_OPTS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              <div className="opt-group">
                <span className="opt-label">Smart Chunking</span>
                <select value={chunkPreset} onChange={e => setChunkPreset(e.target.value)}>
                  {CHUNK_OPTS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              {chunkPreset === "Custom" && (
                <div className="opt-group" style={{ minWidth: 100 }}>
                  <span className="opt-label">Token Limit</span>
                  <input type="number" min={500} max={128000} step={500}
                    value={customChunkSize} onChange={e => setCustomChunkSize(Number(e.target.value))} />
                </div>
              )}
              {chunkPreset !== "None" && (
                <div className="opt-group" style={{ minWidth: 130 }}>
                  <span className="opt-label">Overlap — {overlapPct}%</span>
                  <input type="range" min={0} max={25} step={5}
                    value={overlapPct} onChange={e => setOverlapPct(Number(e.target.value))} />
                </div>
              )}
            </div>

            {/* Results header */}
            {entryList.length > 0 && (
              <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginTop:10, marginBottom:6 }}>
                <span style={{ fontSize:11.5, fontWeight:600, color:"var(--text-2)" }}>
                  Results — {entryList.length} file{entryList.length!==1?"s":""}
                </span>
                <div style={{ display:"flex", gap:5 }}>
                  {successful.length > 1 && (
                    <button className="btn btn-ghost btn-sm" onClick={handleDownloadAll}>⬇ All</button>
                  )}
                  <button className="btn btn-ghost btn-sm" onClick={clearAll}>✕ Clear</button>
                </div>
              </div>
            )}

            {/* Results */}
            {entryList.length > 0 ? (
              <div className="results">
                {entryList.map((entry, idx) => (
                  <ResultCard
                    key={entry.clientId}
                    entry={entry}
                    defaultOpen={entry.status === "done" && shouldAutoExpand(idx)}
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

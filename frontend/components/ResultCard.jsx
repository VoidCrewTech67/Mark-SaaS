"use client";
import { useEffect, useRef, useState } from "react";
import { formatNumber, formatBytes, stemName } from "@/lib/utils";

// ── Semantic helpers ────────────────────────────────────────────────────────
function semEmoji(score) {
  if (score >= 98) return "🟢";
  if (score >= 95) return "🟡";
  if (score >= 90) return "🟠";
  return "🔴";
}
function semColor(score) {
  if (score >= 98) return "#10B981";
  if (score >= 95) return "#F59E0B";
  if (score >= 90) return "#F97316";
  return "#EF4444";
}

function ScorePill({ score, label }) {
  if (score == null) return null;
  const color = semColor(score);
  return (
    <div className="stat-pill" style={{ minWidth: 90 }}>
      <div className="stat-value" style={{ color, fontSize: 13 }}>
        {score.toFixed(1)}% <span style={{ fontSize: 10 }}>{semEmoji(score)}</span>
      </div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

const ISSUE_COLORS = { danger: "#EF4444", warning: "#F59E0B", info: "#60607A" };
const ISSUE_ICONS  = { danger: "🔴", warning: "🟡", info: "i" };

function IssuesRow({ issues }) {
  const [open, setOpen] = useState(false);
  if (!issues || issues.length === 0) return null;
  const significant = issues.filter(i => i.severity !== "info");
  if (significant.length === 0) return null;
  return (
    <div style={{ marginBottom: 10 }}>
      <button
        onClick={() => setOpen(p => !p)}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "rgba(249,115,22,.06)", border: "1px solid rgba(249,115,22,.2)",
          borderRadius: 6, padding: "4px 10px", cursor: "pointer",
          fontSize: 11, fontWeight: 600, color: "#F97316", width: "100%",
        }}
      >
        ⚠ Preservation Issues ({significant.length})
        <span style={{ marginLeft: "auto", fontSize: 9, color: "var(--text-3)" }}>{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
          {issues.map((iss, i) => (
            <div key={i} style={{
              display: "flex", alignItems: "flex-start", gap: 6,
              fontSize: 11, color: ISSUE_COLORS[iss.severity] || "var(--text-3)",
              padding: "3px 0",
            }}>
              <span style={{ fontSize: 10, flexShrink: 0 }}>{ISSUE_ICONS[iss.severity]}</span>
              <span>{iss.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Misc helpers ──────────────────────────────────────────────────────────────
const DOT = { uploading:"#8B5CF6", uploaded:"#8B5CF6", converting:"#8B5CF6", done:"#10B981", error:"#EF4444" };
const PROG = {
  uploading:{ pct:25, color:"#8B5CF6", label:"Uploading…" },
  uploaded:{ pct:45, color:"#8B5CF6", label:"Queued" },
  converting:{ pct:70, color:"#8B5CF6", label:"Converting…" },
  done:{ pct:100, color:"#10B981", label:"Done" },
  error:{ pct:100, color:"#EF4444", label:"Error" },
};

function CopyBtn({ text }) {
  const [c, setC] = useState(false);
  const copy = async () => { try { await navigator.clipboard.writeText(text); setC(true); setTimeout(() => setC(false), 2000); } catch {} };
  return <button className={`copy-btn${c ? " copied" : ""}`} onClick={copy}>{c ? "✓ Copied" : "⎘ Copy"}</button>;
}

function Tabs({ tabs }) {
  const [a, setA] = useState(tabs[0]?.key);
  return (
    <div>
      <div className="tabs-bar">
        {tabs.map(t => <button key={t.key} className={`tab-btn${a===t.key?" active":""}`} onClick={() => setA(t.key)}>{t.label}</button>)}
      </div>
      <div className="tab-content">{tabs.find(t => t.key===a)?.content}</div>
    </div>
  );
}

// ── RAG helpers ───────────────────────────────────────────────────────────────
// Output shape is intentionally universal so the same JSON loads cleanly into
// Pinecone (id + metadata + text), ChromaDB (ids/documents/metadatas),
// Qdrant (id + payload), Weaviate (id + properties), LangChain
// (page_content + metadata) and LlamaIndex (text + metadata).
function buildRagExport(result, displayName) {
  const rawChunks = Array.isArray(result?.chunks) ? result.chunks : [];
  const docType =
    result?.detected_document_type || result?.document_type || "generic";
  const sourceFile = displayName || "";
  const documentTitle = stemName(displayName);

  const chunks = rawChunks.map((ch, i) => {
    const isObj = ch && typeof ch === "object";
    const content = isObj ? (ch.content || "") : String(ch);
    const idx = isObj && ch.index != null ? ch.index : i + 1;
    const id =
      isObj && ch.chunk_id ? ch.chunk_id : `chunk_${String(idx).padStart(3, "0")}`;
    const tokenCount = isObj && ch.token_count != null ? ch.token_count : 0;
    const wordCount =
      isObj && ch.word_count != null
        ? ch.word_count
        : content.split(/\s+/).filter(Boolean).length;
    const charCount = isObj && ch.char_count != null ? ch.char_count : content.length;

    const metadata = {
      source_file: sourceFile,
      document_title: documentTitle,
      document_type: docType,
      section: isObj ? (ch.section ?? null) : null,
      page_number: isObj && ch.page_number != null ? ch.page_number : null,
      chunk_index: idx,
      token_count: tokenCount,
      word_count: wordCount,
      char_count: charCount,
      overlap_prev_tokens:
        isObj && ch.overlap_prev_tokens != null ? ch.overlap_prev_tokens : 0,
      has_table: !!(isObj && ch.has_table),
      table_summary: isObj && ch.table_summary != null ? ch.table_summary : null,
    };

    return {
      // Vector-DB canonical
      id,
      text: content,
      metadata,
      // Backward-compat aliases (do not remove — old loaders consume these)
      chunk_id: id,
      index: idx,
      content,
      section: metadata.section,
      token_count: tokenCount,
      word_count: wordCount,
      char_count: charCount,
    };
  });

  return {
    mode: "rag",
    document_id: documentTitle,
    document_title: documentTitle,
    source_file: sourceFile,
    document_type: docType,
    chunk_count: result?.chunk_count ?? chunks.length,
    chunks,
  };
}

function RagView({ result, displayName }) {
  const [openChunk, setOpenChunk] = useState(null);
  const [rawOpen, setRawOpen] = useState(false);
  const exportObj = buildRagExport(result, displayName);
  const jsonStr = JSON.stringify(exportObj, null, 2);
  const chunks = exportObj.chunks;
  const totalTokens = chunks.reduce((s, c) => s + (c.token_count || 0), 0);
  const avgChunkSize = chunks.length ? Math.round(totalTokens / chunks.length) : 0;

  const downloadJson = () => {
    const b = new Blob([jsonStr], { type: "application/json" });
    const u = URL.createObjectURL(b);
    const a = document.createElement("a");
    a.href = u;
    a.download = stemName(displayName) + ".rag.json";
    a.click();
    URL.revokeObjectURL(u);
  };

  return (
    <div>
      {/* Dashboard */}
      <div className="stats-row" style={{ marginBottom: 10 }}>
        <div className="stat-pill">
          <div className="stat-value" style={{ color: "#8B5CF6", fontSize: 13 }}>{exportObj.document_type}</div>
          <div className="stat-label">Document Type</div>
        </div>
        <div className="stat-pill">
          <div className="stat-value" style={{ color: "#6366F1" }}>{formatNumber(exportObj.chunk_count)}</div>
          <div className="stat-label">Chunk Count</div>
        </div>
        <div className="stat-pill">
          <div className="stat-value" style={{ color: "#A855F7" }}>{formatNumber(totalTokens)}</div>
          <div className="stat-label">Total Tokens</div>
        </div>
        <div className="stat-pill">
          <div className="stat-value" style={{ color: "#10B981" }}>{formatNumber(avgChunkSize)}</div>
          <div className="stat-label">Avg Chunk Size</div>
        </div>
      </div>

      {/* Export actions */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, flexWrap: "wrap", gap: 6 }}>
        <span style={{ fontSize: 10.5, color: "var(--text-3)" }}>
          Retrieval-ready JSON · ChromaDB · Pinecone · Qdrant · Weaviate · LangChain · LlamaIndex
        </span>
        <div style={{ display: "flex", gap: 5 }}>
          <CopyBtn text={jsonStr} />
          <button className="btn btn-primary btn-sm" onClick={downloadJson}>⬇ Download JSON</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setRawOpen(p => !p)}>
            {rawOpen ? "Hide" : "View"} Raw JSON
          </button>
        </div>
      </div>

      {rawOpen && (
        <pre className="md-pre" style={{ maxHeight: 280, overflow: "auto", marginBottom: 10 }}>
          {jsonStr.length > 12000 ? jsonStr.slice(0, 12000) + "\n…(truncated, use Download JSON for full)" : jsonStr}
        </pre>
      )}

      {/* Chunk cards */}
      <div className="chunk-list">
        {chunks.map((ch, i) => (
          <div key={ch.chunk_id} className="chunk-item">
            <div className="chunk-header" onClick={() => setOpenChunk(openChunk === i ? null : i)}>
              <span className="chunk-idx">{ch.chunk_id}</span>
              {ch.section && <span className="chunk-meta" style={{ fontWeight: 600 }}>{ch.section}</span>}
              <span className="chunk-meta">{ch.token_count} tok · {ch.word_count} words</span>
              <span style={{ color: "var(--text-3)", fontSize: 9 }}>{openChunk === i ? "▲" : "▼"}</span>
            </div>
            {openChunk === i && (
              <pre className="chunk-pre">
                {ch.content.slice(0, 1500)}{ch.content.length > 1500 ? "\n…" : ""}
              </pre>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── ResultCard ────────────────────────────────────────────────────────────────
export default function ResultCard({
  entry, isActive, chunkPreset, chunkSize, overlapPct,
  onGenerateChunks, onDownloadMd, onDownloadZip, onRemove,
}) {
  const cardRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [openChunk, setOpenChunk] = useState(null);

  const {
    clientId, status, file, originalName, result, error,
    sizeBytes, chunks, chunkStatus, chunkError, zipSource,
  } = entry;

  const displayName = originalName || file?.name || clientId;
  const prog = PROG[status] || PROG.uploading;
  const isDone = status === "done";
  const isError = status === "error";
  const isActive_ = ["uploading","uploaded","converting"].includes(status);

  // Auto-expand + scroll when this card becomes the active one
  useEffect(() => {
    if (isActive && isDone) {
      setOpen(true);
      // Small delay so the DOM has painted before scrolling
      const t = setTimeout(() => {
        cardRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }, 80);
      return () => clearTimeout(t);
    }
  }, [isActive, isDone]);

  const isRag = result?.mode === "rag";

  const tabs = isDone ? [
    { key:"preview", label:"Preview", content: (
      <div>
        {result && (
          <div className="stats-row">
            {[
              ["Tokens",   formatNumber(result.token_estimate), "#8B5CF6"],
              ["Words",    formatNumber(result.word_count),     "#6366F1"],
              ["Chars",    formatNumber(result.char_count),     "#A855F7"],
              ["Time",     `${result.duration_s?.toFixed(2)}s`, "#10B981"],
            ].map(([l,v,c]) => (
              <div key={l} className="stat-pill">
                <div className="stat-value" style={{color:c}}>{v}</div>
                <div className="stat-label">{l}</div>
              </div>
            ))}
            <ScorePill score={result.optimization_stats?.semantic_preservation} label="MEANING" />
            <ScorePill score={result.optimization_stats?.context_preservation}  label="CONTEXT" />
            {result.optimization_stats?.percent_saved != null && (
              <div className="stat-pill">
                <div className="stat-value" style={{ color: "#10B981" }}>-{result.optimization_stats.percent_saved}%</div>
                <div className="stat-label">Token Reduction</div>
              </div>
            )}
          </div>
        )}
        <IssuesRow issues={result?.optimization_stats?.issues} />
        {(result?.ocr_used || result?.embedded_images_ocr_count > 0) && (
          <div style={{ display:"flex", gap:5, marginBottom:8, flexWrap:"wrap" }}>
            {result.ocr_used && <span className="badge badge-orange">⚡ OCR Fallback</span>}
            {result.embedded_images_ocr_count > 0 && <span className="badge badge-purple">🖼 {result.embedded_images_ocr_count} Images OCR'd</span>}
          </div>
        )}
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:5 }}>
          <span style={{ fontSize:10.5, color:"var(--text-3)" }}>Markdown output</span>
          <div style={{ display:"flex", gap:5 }}>
            <CopyBtn text={result?.markdown||""} />
            <button className="btn btn-ghost btn-sm" onClick={() => onDownloadMd(clientId)}>⬇ .md</button>
          </div>
        </div>
        <pre className="md-pre">{(result?.markdown||"").slice(0,5000)}{(result?.markdown||"").length>5000?"\n\n… (truncated)":""}</pre>
      </div>
    )},
    { key:"optimized", label:"Optimized", content: (() => {
      const s = result?.optimization_stats;
      const md = result?.optimized_markdown || result?.markdown || "";
      return (
        <div>
          {s && (
            <div className="stats-row">
              {[
                ["Before",    formatNumber(s.original_tokens),  "var(--text)"],
                ["After",     formatNumber(s.optimized_tokens), "var(--text)"],
                ["Saved",     formatNumber(s.tokens_saved),     "#10B981"],
                ["Reduction", `${s.percent_saved}%`,            "#10B981"],
              ].map(([l,v,c]) => (
                <div key={l} className="stat-pill">
                  <div className="stat-value" style={{color:c}}>{v}</div>
                  <div className="stat-label">{l}</div>
                </div>
              ))}
              <ScorePill score={s.semantic_preservation} label="MEANING" />
              <ScorePill score={s.context_preservation}  label="CONTEXT" />
            </div>
          )}
          <IssuesRow issues={s?.issues} />
          <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:5 }}>
            <span style={{ fontSize:10.5, color:"var(--text-3)" }}>Optimized output</span>
            <div style={{ display:"flex", gap:5 }}>
              <CopyBtn text={md} />
              <button className="btn btn-ghost btn-sm" onClick={() => {
                const b=new Blob([md],{type:"text/markdown"}); const u=URL.createObjectURL(b);
                const a=document.createElement("a"); a.href=u; a.download=stemName(displayName)+"_optimized.md"; a.click(); URL.revokeObjectURL(u);
              }}>⬇ Download</button>
            </div>
          </div>
          <pre className="md-pre">{md.slice(0,5000)}</pre>
        </div>
      );
    })()},
    { key:"chunks", label:"Chunks", content: (
      <div>
        {chunks?.chunks?.length ? (
          <div>
            <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:8 }}>
              <span style={{ fontSize:11.5, color:"var(--text-2)" }}>
                <b style={{color:"var(--text)"}}>{chunks.chunk_count}</b> chunks
                {result?.mode==="rag" && (
                  <span style={{ marginLeft:6, padding:"1px 6px", borderRadius:4, background:"var(--accent-soft, #2a2a3a)", fontSize:10 }}>
                    RAG · {chunks.document_type || result.detected_document_type || "generic"}
                  </span>
                )}
              </span>
              <button className="btn btn-ghost btn-sm" onClick={() => onDownloadZip(clientId)}>⬇ ZIP</button>
            </div>
            <div className="chunk-list">
              {chunks.chunks.map((ch,i) => {
                // Structured chunk (object) or legacy string — handle both.
                const isObj = ch && typeof ch === "object";
                const content = isObj ? (ch.content || "") : String(ch);
                const words = isObj ? (ch.word_count ?? content.split(/\s+/).length) : content.split(/\s+/).length;
                const label = isObj ? (ch.chunk_id || `#${String(i+1).padStart(3,"0")}`) : `#${String(i+1).padStart(3,"0")}`;
                return (
                  <div key={i} className="chunk-item">
                    <div className="chunk-header" onClick={() => setOpenChunk(openChunk===i?null:i)}>
                      <span className="chunk-idx">{label}</span>
                      {isObj && ch.section && <span className="chunk-meta" style={{ fontWeight:600 }}>{ch.section}</span>}
                      <span className="chunk-meta">
                        {isObj && ch.token_count != null ? `${ch.token_count} tok · ` : ""}~{words} words
                      </span>
                      <span style={{color:"var(--text-3)",fontSize:9}}>{openChunk===i?"▲":"▼"}</span>
                    </div>
                    {openChunk===i && <pre className="chunk-pre">{content.slice(0,1200)}{content.length>1200?"\n…":""}</pre>}
                  </div>
                );
              })}
            </div>
          </div>
        ) : chunkStatus==="loading" ? (
          <div style={{ display:"flex", alignItems:"center", gap:6, fontSize:11.5, color:"var(--text-2)" }}><span className="spinner"/>Chunking…</div>
        ) : chunkStatus==="error" ? (
          <div className="error-box">{chunkError}</div>
        ) : chunkPreset==="None" ? (
          <p style={{ fontSize:11.5, color:"var(--text-3)" }}>Enable Smart Chunking in the settings above, or select <b>RAG</b> mode for automatic retrieval-ready chunks.</p>
        ) : (
          <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
            <p style={{ fontSize:11.5, color:"var(--text-2)" }}>Split into ≤{formatNumber(chunkSize)} token chunks with {overlapPct}% overlap.</p>
            <button className="btn btn-primary btn-sm" onClick={() => onGenerateChunks(clientId)} style={{ width:"fit-content" }}>🔀 Generate Chunks</button>
          </div>
        )}
      </div>
    )},
    { key:"raw", label:"Raw", content: (
      <div>
        <div style={{ display:"flex", justifyContent:"flex-end", marginBottom:5 }}><CopyBtn text={result?.markdown||""}/></div>
        <textarea className="md-raw" readOnly value={result?.markdown||""}/>
      </div>
    )},
  ] : [];

  return (
    <div
      ref={cardRef}
      className={`result-card status-${status}${isActive && isDone ? " is-active" : ""}`}
    >
      <div className="result-header" onClick={() => isDone && setOpen(p => !p)}>
        <span className="result-status-dot" style={{ background: DOT[status]||"#6B7280" }}/>
        {isActive_ && <span className="spinner spinner-sm"/>}
        <div style={{ flex:1, minWidth:0 }}>
          <div className="result-name" title={displayName}>{displayName}</div>
          {zipSource && (
            <div style={{ fontSize:9.5, color:"var(--text-3)", marginTop:1 }}>from {zipSource}</div>
          )}
        </div>
        <div className="result-meta">
          {isDone && result && <>
            <span className="badge badge-muted">{formatNumber(result.token_estimate)} tok</span>
            <span className="badge badge-muted">{result.duration_s?.toFixed(2)}s</span>
            {(result.ocr_used||result.embedded_images_ocr_count>0) && <span className="badge badge-purple">OCR</span>}
          </>}
          {sizeBytes && <span className="badge badge-muted">{formatBytes(sizeBytes)}</span>}
          {isActive_ && <span className="badge badge-purple">{prog.label}</span>}
          {isError && <span className="badge badge-red">Failed</span>}
          <button
            onClick={e => { e.stopPropagation(); onRemove(clientId); }}
            style={{ border:"none", background:"none", color:"var(--text-3)", cursor:"pointer", padding:"2px", fontSize:11 }}
            title="Remove"
          >✕</button>
          {isDone && <span className={`result-chevron${open?" open":""}`}>▾</span>}
        </div>
      </div>

      <div className="result-progress">
        <div className="result-progress-bar" style={{ width:`${prog.pct}%`, background:prog.color }}/>
      </div>

      {isError && <div className="error-box">{error}</div>}
      {open && isDone && (
        <div className="result-body">
          {isRag
            ? <RagView result={result} displayName={displayName} />
            : <Tabs tabs={tabs} />}
        </div>
      )}
    </div>
  );
}

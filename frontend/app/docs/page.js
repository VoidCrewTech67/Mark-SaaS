"use client";
import Navbar from "@/components/Navbar";
import Sidebar from "@/components/Sidebar";

const FORMATS = [
  { ext:"PDF", process:"MarkItDown + per-page image OCR", ocr:"✓", limit:"—" },
  { ext:"DOCX", process:"python-docx text + embedded images", ocr:"✓", limit:"—" },
  { ext:"PPTX", process:"python-pptx slides + image OCR", ocr:"✓", limit:"—" },
  { ext:"XLSX/XLS", process:"openpyxl table conversion", ocr:"✗", limit:"No images" },
  { ext:"HTML/HTM", process:"BeautifulSoup4 + img extraction", ocr:"✓", limit:"—" },
  { ext:"TXT/MD/RST", process:"Direct passthrough", ocr:"✗", limit:"—" },
  { ext:"CSV/JSON/XML", process:"Structured text extraction", ocr:"✗", limit:"—" },
  { ext:"JPG/PNG/WEBP", process:"Direct EasyOCR", ocr:"✓", limit:"—" },
  { ext:"MP3/WAV", process:"Audio transcription", ocr:"✗", limit:"Requires ffmpeg" },
  { ext:"EPUB", process:"Chapter extraction", ocr:"✗", limit:"—" },
  { ext:"ZIP", process:"Archive → per-file conversion", ocr:"✓", limit:"No nested archives" },
];
const ROADMAP = ["Google Login","Public REST API","Claude MCP Server","ChatGPT Actions","Chrome Extension","Batch API","Webhook Delivery"];

export default function DocsPage() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-wrap">
        <Navbar />
        <div className="main-scroll">
          <div className="docs-page">
            <div className="hero-badge" style={{ display:"inline-flex",alignItems:"center",gap:4,fontSize:9.5,fontWeight:600,letterSpacing:".08em",textTransform:"uppercase",color:"var(--purple)",background:"var(--purple-dim)",border:"1px solid var(--purple-border)",padding:"2px 7px",borderRadius:14,marginBottom:10 }}>📖 Technical Documentation</div>
            <h1>How MarkItDown Works</h1>
            <p style={{color:"var(--text-2)",fontSize:13}}>Technical reference for the document conversion pipeline.</p>

            <h2>1. Overview</h2>
            <p>MarkItDown converts documents into clean, AI-ready Markdown using Microsoft&apos;s MarkItDown library, EasyOCR for image text extraction, token optimization, and optional smart chunking.</p>
            <div className="docs-flow">
              {["Upload","MarkItDown","Image Extraction","EasyOCR","Optimization","Chunking","Download"].map((s,i,a) => (
                <div key={s} style={{display:"flex",flexDirection:"column",alignItems:"center",gap:2}}>
                  <span>{s}</span>{i<a.length-1 && <span className="docs-flow-arrow">↓</span>}
                </div>
              ))}
            </div>

            <h2>2. Supported Formats</h2>
            <table className="docs-table">
              <thead><tr><th>Format</th><th>Processing</th><th>OCR</th><th>Limits</th></tr></thead>
              <tbody>{FORMATS.map(f => (
                <tr key={f.ext}><td><code>{f.ext}</code></td><td>{f.process}</td><td style={{color:f.ocr==="✓"?"var(--green)":"var(--text-3)"}}>{f.ocr}</td><td style={{color:"var(--text-3)"}}>{f.limit}</td></tr>
              ))}</tbody>
            </table>

            <h2>3. OCR System</h2>
            <h3>EasyOCR Integration</h3>
            <p>EasyOCR singleton initialised at startup. GPU (CUDA/MPS) used when available; falls back to CPU.</p>
            <h3>Fallback OCR</h3>
            <p>Triggered when MarkItDown extracts &lt;80 characters. Handles scanned PDFs and image documents.</p>
            <h3>Embedded Image OCR</h3>
            <p>Each embedded image (PDF pages at 300 DPI, DOCX inline, PPTX slides, HTML img tags) is individually OCR&apos;d and appended as structured code blocks.</p>
            <h3>Smart Filtering Rules</h3>
            <ul>
              <li><strong>Rule 1 — Size:</strong> Skip images &lt;50,000 px² or extreme aspect ratios</li>
              <li><strong>Rule 2 — Length:</strong> Discard results &lt;40 characters</li>
              <li><strong>Rule 3 — Logo:</strong> Skip short title-case results without punctuation</li>
              <li><strong>Rule 4 — Noise:</strong> Skip repeated words, coordinates, fragmented lines</li>
            </ul>
            <h3>SHA-256 Cache</h3>
            <p>Maps <code>sha256(image_bytes)</code> → text. Same image OCR&apos;d exactly once per process lifetime.</p>

            <h2>4. Image Extraction Pipeline</h2>
            <ul>
              <li><strong>PDF:</strong> PyMuPDF renders pages at 300 DPI → PNG bytes</li>
              <li><strong>DOCX:</strong> python-docx extracts inline image blobs</li>
              <li><strong>PPTX:</strong> python-pptx extracts slide shape images</li>
              <li><strong>HTML:</strong> BeautifulSoup4 resolves &lt;img&gt; src paths</li>
              <li><strong>Images:</strong> File passed directly to EasyOCR</li>
            </ul>

            <h2>5. Optimization Pipeline</h2>
            <ol>
              <li><strong>Unicode normalisation:</strong> NFKC (ligatures, non-breaking spaces, zero-width chars)</li>
              <li><strong>Heading cleanup:</strong> Collapse ≥3 blank lines to 2</li>
              <li><strong>Page numbers:</strong> Strip standalone numeric patterns</li>
              <li><strong>Deduplication:</strong> Remove verbatim duplicate paragraphs</li>
              <li><strong>Artifacts:</strong> Remove form feeds, NUL bytes, run-on hyphens</li>
              <li><strong>Whitespace:</strong> Right-strip lines, normalise trailing newlines</li>
            </ol>

            <h2>6. Smart Chunking</h2>
            <p>Heading-aware splitting: breaks at <code>#</code>/<code>##</code>/<code>###</code>, then paragraphs, then sentences. Each chunk ≤ configured token limit (tiktoken <code>cl100k_base</code>).</p>
            <p>Overlap repeats last N tokens of previous chunk (default 10%) to prevent context loss at boundaries.</p>
            <pre><code>{`Chunk 1: tokens 0–8000
Chunk 2: tokens 7200–15200  (800 overlap)
Chunk 3: tokens 14400–22400`}</code></pre>

            <h2>7. Statistics</h2>
            <table className="docs-table">
              <thead><tr><th>Metric</th><th>Method</th></tr></thead>
              <tbody>
                {[["Tokens","tiktoken cl100k_base"],["Words","Whitespace split"],["Characters","len()"],["Time","Wall-clock seconds"],["Savings","(orig − opt) / orig × 100"]].map(([m,d]) => (
                  <tr key={m}><td><code>{m}</code></td><td>{d}</td></tr>
                ))}
              </tbody>
            </table>

            <h2>8. Batch Processing</h2>
            <p>Files processed sequentially (OCR singleton), with independent state per file. ZIP export uses browser <code>CompressionStream</code> API.</p>

            <h2>9. Architecture</h2>
            <div className="docs-flow">
              {[["Next.js (Vercel)","UI + State + ZIP"],["↓",""],["FastAPI (Render)","API + Validation + Cleanup"],["↓",""],["Engine","MarkItDown + OCR + Optimizer"],["↓",""],["Storage","uploads/ + converted/ (TTL: 2h)"]].map(([n,d],i) => (
                n==="↓" ? <span key={i} className="docs-flow-arrow">↓</span> :
                <div key={n} style={{textAlign:"center"}}><div style={{fontWeight:600,color:"var(--text)"}}>{n}</div>{d&&<div style={{fontSize:10.5,color:"var(--text-3)"}}>{d}</div>}</div>
              ))}
            </div>

            <h2>10. Roadmap</h2>
            {ROADMAP.map(item => (
              <div key={item} className="docs-roadmap-item">
                <span className="docs-roadmap-name">{item}</span>
                <span className="badge badge-muted">Coming Soon</span>
              </div>
            ))}
            <div style={{ height: 30 }}/>
          </div>
        </div>
      </div>
    </div>
  );
}

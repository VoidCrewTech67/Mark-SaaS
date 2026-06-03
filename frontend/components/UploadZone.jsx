"use client";
import { useRef, useState, useCallback } from "react";
import { formatBytes } from "@/lib/utils";

const ACCEPT = ".pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.csv,.html,.htm,.txt,.md,.rst,.json,.xml,.zip,.jpg,.jpeg,.png,.gif,.bmp,.webp,.epub,.mp3,.wav";
const FORMATS = ["PDF","DOCX","PPTX","XLSX","CSV","HTML","TXT","JSON","PNG","EPUB","ZIP"];

export default function UploadZone({ onConvert, disabled }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [staged, setStaged] = useState([]);

  const addFiles = useCallback((list) => {
    const arr = Array.from(list);
    setStaged(prev => {
      const names = new Set(prev.map(f => f.name));
      return [...prev, ...arr.filter(f => !names.has(f.name))];
    });
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault(); setDragging(false);
    if (!disabled) addFiles(e.dataTransfer.files);
  }, [addFiles, disabled]);

  const handleConvert = () => {
    if (!staged.length || disabled) return;
    onConvert(staged);
    setStaged([]);
  };

  const removeStaged = (name) => setStaged(p => p.filter(f => f.name !== name));

  return (
    <div>
      {/* Drop area */}
      <div className={`dropzone${dragging ? " dragging" : ""}`}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        style={{ opacity: disabled ? 0.6 : 1, cursor: disabled ? "not-allowed" : "pointer" }}>
        <span className="dropzone-icon">{dragging ? "📂" : "📁"}</span>
        <div className="dropzone-title">{dragging ? "Release to upload" : "Drag & Drop Files Here"}</div>
        <div className="dropzone-sub">or click to browse</div>
        <div className="dropzone-formats">
          {FORMATS.map(f => <span key={f} className="format-badge">{f}</span>)}
          <span className="format-badge">+ more</span>
        </div>
        <input ref={inputRef} type="file" multiple accept={ACCEPT}
          style={{ display: "none" }} onChange={e => addFiles(e.target.files)} disabled={disabled} />
      </div>

      {/* Staged files */}
      {staged.length > 0 && (
        <div className="staged">
          {staged.map(f => (
            <div key={f.name} className="staged-item">
              <span style={{ fontSize: 12 }}>📄</span>
              <span className="staged-name">{f.name}</span>
              <span className="staged-size">{formatBytes(f.size)}</span>
              <button className="staged-remove" onClick={e => { e.stopPropagation(); removeStaged(f.name); }}>✕</button>
            </div>
          ))}
        </div>
      )}

      {/* Toolbar */}
      <div className="upload-toolbar">
        {/* Upload button — primary purple */}
        <button className="btn btn-upload" onClick={() => inputRef.current?.click()} disabled={disabled}>
          📁 Upload Files
        </button>

        {staged.length > 0 && (
          <button className="btn btn-ghost btn-sm" onClick={() => setStaged([])}>✕ Clear</button>
        )}

        <div className="toolbar-right">
          <span className="toolbar-info">500 MB per ZIP · 150 MB per file</span>
          <button className="btn btn-convert" onClick={handleConvert} disabled={!staged.length || disabled}>
            {disabled
              ? <><span className="spinner spinner-sm"/>Converting…</>
              : <>▶ Convert{staged.length > 0 ? ` (${staged.length})` : ""} All</>
            }
          </button>
        </div>
      </div>
    </div>
  );
}

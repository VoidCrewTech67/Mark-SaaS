"use client";
import { useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { UploadCloud, FileText, X } from "lucide-react";
import { formatBytes } from "@/lib/utils";
import { cn } from "@/lib/utils";

const ACCEPTED = ".pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.csv,.html,.htm,.txt,.md,.rst,.json,.xml,.zip,.jpg,.jpeg,.png,.gif,.bmp,.webp,.epub,.mp3,.wav";

export default function DropZone({ onFilesSelected, disabled }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [staged, setStaged] = useState([]);

  const addFiles = useCallback((fileList) => {
    const arr = Array.from(fileList);
    setStaged(prev => {
      const names = new Set(prev.map(f => f.name));
      return [...prev, ...arr.filter(f => !names.has(f.name))];
    });
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault(); setDragging(false);
    if (!disabled) addFiles(e.dataTransfer.files);
  }, [addFiles, disabled]);

  const handleConvert = useCallback(() => {
    if (!staged.length) return;
    onFilesSelected(staged);
    setStaged([]);
  }, [staged, onFilesSelected]);

  return (
    <div className="flex flex-col gap-4">
      {/* Drop area */}
      <motion.div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        animate={{ borderColor: dragging ? "rgba(139,92,246,0.8)" : "rgba(255,255,255,0.10)" }}
        transition={{ duration: 0.2 }}
        className={cn(
          "relative flex flex-col items-center justify-center gap-5 py-20 rounded-2xl cursor-pointer transition-all duration-200 group overflow-hidden",
          dragging && "upload-active",
          disabled && "opacity-50 cursor-not-allowed"
        )}
        style={{ border: "2px dashed rgba(255,255,255,0.10)", background: dragging ? "rgba(139,92,246,0.06)" : "rgba(255,255,255,0.02)" }}>

        {/* Inner glow on drag */}
        <AnimatePresence>
          {dragging && (
            <motion.div key="glow" initial={{ opacity:0 }} animate={{ opacity:1 }} exit={{ opacity:0 }}
              className="absolute inset-0 pointer-events-none"
              style={{ background: "radial-gradient(ellipse at center, rgba(139,92,246,0.12) 0%, transparent 70%)" }}
            />
          )}
        </AnimatePresence>

        {/* Icon */}
        <motion.div
          animate={{ y: dragging ? -4 : 0, scale: dragging ? 1.1 : 1 }}
          className="w-16 h-16 rounded-2xl flex items-center justify-center"
          style={{ background: "rgba(139,92,246,0.12)", border: "1px solid rgba(139,92,246,0.25)" }}>
          <UploadCloud className="w-8 h-8" style={{ color: "#8B5CF6" }}/>
        </motion.div>

        <div className="text-center">
          <p className="text-lg font-semibold text-white mb-1">
            {dragging ? "Release to upload" : "Drag & drop your files"}
          </p>
          <p className="text-sm" style={{ color: "#94A3B8" }}>or click to browse · any format supported</p>
        </div>

        {/* Format grid */}
        <div className="flex flex-wrap justify-center gap-2 max-w-md">
          {["PDF","DOCX","PPTX","XLSX","HTML","CSV","JSON","PNG","MP3","EPUB"].map(f => (
            <span key={f} className="px-2.5 py-1 rounded-lg text-[11px] font-mono font-medium"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)", color: "#6B7280" }}>
              {f}
            </span>
          ))}
        </div>

        <input ref={inputRef} type="file" multiple accept={ACCEPTED} className="hidden"
          onChange={(e) => addFiles(e.target.files)} disabled={disabled}/>
      </motion.div>

      {/* Staged files */}
      <AnimatePresence>
        {staged.length > 0 && (
          <motion.div key="staged" initial={{ opacity:0, height:0 }} animate={{ opacity:1, height:"auto" }} exit={{ opacity:0, height:0 }}
            className="flex flex-col gap-2 overflow-hidden">
            {staged.map(file => (
              <motion.div key={file.name} layout initial={{ opacity:0, x:-10 }} animate={{ opacity:1, x:0 }}
                className="flex items-center gap-3 px-4 py-3 rounded-xl"
                style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}>
                <FileText className="w-4 h-4 flex-shrink-0" style={{ color: "#8B5CF6" }}/>
                <span className="text-sm text-white/80 truncate flex-1 font-medium">{file.name}</span>
                <span className="text-xs font-mono flex-shrink-0" style={{ color: "#6B7280" }}>{formatBytes(file.size)}</span>
                <button onClick={(e) => { e.stopPropagation(); setStaged(p => p.filter(f => f.name !== file.name)); }}
                  className="p-1.5 rounded-lg text-white/30 hover:text-white/80 hover:bg-white/10 transition-all duration-150">
                  <X className="w-3.5 h-3.5"/>
                </button>
              </motion.div>
            ))}

            {/* Convert button */}
            <motion.button layout onClick={handleConvert} disabled={disabled}
              whileHover={{ scale:1.01 }} whileTap={{ scale:0.98 }}
              className="w-full h-12 rounded-xl text-sm font-bold text-white transition-all duration-200 mt-1"
              style={{ background: "linear-gradient(135deg, #8B5CF6 0%, #6366F1 100%)", boxShadow: "0 0 30px rgba(139,92,246,0.35), 0 4px 20px rgba(0,0,0,0.3)" }}>
              Convert {staged.length} File{staged.length > 1 ? "s" : ""}
            </motion.button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

"use client";
import { motion, useMotionValue, useTransform, useSpring } from "framer-motion";
import { CheckCircle2, Loader2, FileText, Image as ImageIcon, Hash, Clock } from "lucide-react";

// Fake file rows shown in the mockup
const FILES = [
  { name: "annual_report.pdf", size: "4.2 MB", status: "done",  tokens: "12,451" },
  { name: "research_paper.docx", size: "1.8 MB", status: "done",  tokens: "6,832" },
  { name: "presentation.pptx", size: "8.1 MB", status: "converting", tokens: null },
];

const MD_PREVIEW = `# Annual Report 2024

## Executive Summary

Revenue grew **34%** YoY driven by
enterprise adoption of AI workflows.

### Key Metrics
- ARR: $12.4M (+34%)
- NRR: 118%
- Customers: 2,840`;

export default function ProductMockup() {
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);
  const rotateX = useSpring(useTransform(mouseY, [-0.5, 0.5], [8, -8]), { stiffness: 200, damping: 30 });
  const rotateY = useSpring(useTransform(mouseX, [-0.5, 0.5], [-10, 10]), { stiffness: 200, damping: 30 });

  const handleMouse = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    mouseX.set((e.clientX - r.left) / r.width - 0.5);
    mouseY.set((e.clientY - r.top) / r.height - 0.5);
  };

  return (
    <div style={{ perspective: "1200px" }} className="w-full" onMouseMove={handleMouse} onMouseLeave={() => { mouseX.set(0); mouseY.set(0); }}>
      <motion.div style={{ rotateX, rotateY, transformStyle: "preserve-3d" }}
        className="relative w-full rounded-2xl overflow-hidden"
        initial={{ opacity: 0, y: 40 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.3 }}>

        {/* Window chrome */}
        <div className="flex items-center gap-2 px-4 py-3" style={{ background: "rgba(11,16,32,0.95)", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
          <div className="w-3 h-3 rounded-full bg-red-500/70"/>
          <div className="w-3 h-3 rounded-full bg-yellow-500/70"/>
          <div className="w-3 h-3 rounded-full bg-green-500/70"/>
          <span className="ml-3 text-xs text-white/30 font-mono">markitdown — converter</span>
        </div>

        {/* App body */}
        <div className="grid grid-cols-[1fr_1.2fr]" style={{ background: "rgba(8,12,28,0.98)", minHeight: "340px" }}>

          {/* Left — file list */}
          <div className="p-4 border-r" style={{ borderColor: "rgba(255,255,255,0.06)" }}>
            <p className="text-[10px] font-mono text-white/30 uppercase tracking-widest mb-3">Files</p>
            <div className="flex flex-col gap-2">
              {FILES.map((f, i) => (
                <div key={i} className="flex items-start gap-2.5 p-2.5 rounded-lg" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}>
                  <FileText className="w-3.5 h-3.5 text-violet-400 mt-0.5 flex-shrink-0"/>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-white/80 font-medium truncate">{f.name}</p>
                    <p className="text-[10px] text-white/30 font-mono">{f.size}</p>
                  </div>
                  {f.status === "done"
                    ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0 mt-0.5"/>
                    : <Loader2 className="w-3.5 h-3.5 text-violet-400 flex-shrink-0 mt-0.5 animate-spin"/>}
                </div>
              ))}
            </div>

            {/* Stats row */}
            <div className="mt-3 grid grid-cols-2 gap-2">
              {[["Tokens", "19,283", Hash, "text-violet-400"],["Time", "4.2s", Clock, "text-indigo-400"]].map(([l,v,Icon,c]) => (
                <div key={l} className="p-2 rounded-lg" style={{ background: "rgba(139,92,246,0.08)", border: "1px solid rgba(139,92,246,0.15)" }}>
                  <Icon className={`w-3 h-3 ${c} mb-1`}/>
                  <p className={`text-sm font-mono font-bold ${c}`}>{v}</p>
                  <p className="text-[9px] text-white/30">{l}</p>
                </div>
              ))}
            </div>

            {/* OCR badge */}
            <div className="mt-2 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg" style={{ background: "rgba(168,85,247,0.1)", border: "1px solid rgba(168,85,247,0.2)" }}>
              <ImageIcon className="w-3 h-3 text-purple-400"/>
              <span className="text-[10px] text-purple-300 font-mono">3 images OCR&apos;d</span>
            </div>
          </div>

          {/* Right — markdown preview */}
          <div className="p-4">
            <p className="text-[10px] font-mono text-white/30 uppercase tracking-widest mb-3">Markdown Output</p>
            <pre className="text-[11px] font-mono leading-relaxed" style={{ color: "#C4B5FD", whiteSpace: "pre-wrap" }}>
              {MD_PREVIEW}
            </pre>
            {/* Optimization pill */}
            <div className="mt-4 flex items-center gap-2 px-3 py-2 rounded-lg" style={{ background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.2)" }}>
              <span className="text-emerald-400 text-sm">✨</span>
              <span className="text-[10px] text-emerald-300 font-mono">–23% tokens after optimization</span>
            </div>
          </div>
        </div>

        {/* Reflection overlay */}
        <div className="absolute inset-0 pointer-events-none rounded-2xl"
          style={{ background: "linear-gradient(135deg, rgba(255,255,255,0.04) 0%, transparent 50%)" }}
        />
      </motion.div>

      {/* Outer glow */}
      <div className="absolute -inset-1 rounded-2xl pointer-events-none"
        style={{ background: "linear-gradient(135deg, rgba(139,92,246,0.15), rgba(99,102,241,0.1))", filter: "blur(20px)", zIndex: -1 }}
      />
    </div>
  );
}

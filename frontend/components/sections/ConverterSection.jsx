"use client";
import { forwardRef } from "react";
import { motion } from "framer-motion";
import DropZone from "@/components/converter/DropZone";
import SettingsAccordion from "@/components/converter/SettingsAccordion";

const STEPS = [
  { n:"01", label:"Upload Files",    desc:"Drop any document format" },
  { n:"02", label:"Configure",       desc:"OCR, chunking, overlap" },
  { n:"03", label:"Convert",         desc:"AI-ready Markdown output" },
];

const ConverterSection = forwardRef(function ConverterSection({ conversion }, ref) {
  const {
    processFiles,
    ocrMode, setOcrMode,
    chunkPreset, setChunkPreset,
    customChunkSize, setCustomChunkSize,
    overlapPct, setOverlapPct,
    entryList,
  } = conversion;

  const isProcessing = entryList.some(e => ["uploading","uploaded","converting"].includes(e.status));

  return (
    <section id="converter" ref={ref} className="relative py-32" style={{ zIndex: 1 }}>
      <div className="max-w-4xl mx-auto px-6 md:px-12">

        {/* Header */}
        <motion.div className="text-center mb-16"
          initial={{ opacity:0, y:20 }} whileInView={{ opacity:1, y:0 }}
          viewport={{ once:true }} transition={{ duration:0.6 }}>
          <p className="text-xs font-mono font-medium mb-4 tracking-[0.2em] uppercase" style={{ color: "#8B5CF6" }}>
            Start Converting
          </p>
          <h2 className="text-4xl md:text-5xl font-black tracking-tight mb-4">
            <span className="gradient-text">Three steps.</span>
            {" "}<span className="gradient-text-white">One workflow.</span>
          </h2>
        </motion.div>

        {/* Step indicators */}
        <motion.div className="flex items-start justify-center gap-0 mb-12"
          initial={{ opacity:0, y:10 }} whileInView={{ opacity:1, y:0 }}
          viewport={{ once:true }} transition={{ duration:0.5, delay:0.1 }}>
          {STEPS.map((s, i) => (
            <div key={s.n} className="flex items-center">
              <div className="flex flex-col items-center gap-2 text-center px-4 sm:px-8">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center text-sm font-mono font-bold"
                  style={{ background: "rgba(139,92,246,0.15)", border: "1px solid rgba(139,92,246,0.3)", color: "#A78BFA" }}>
                  {s.n}
                </div>
                <p className="text-sm font-semibold text-white">{s.label}</p>
                <p className="text-xs hidden sm:block" style={{ color: "#6B7280" }}>{s.desc}</p>
              </div>
              {i < STEPS.length - 1 && (
                <div className="w-12 h-px flex-shrink-0 mt-[-20px]" style={{ background: "linear-gradient(to right, rgba(139,92,246,0.4), rgba(99,102,241,0.2))" }}/>
              )}
            </div>
          ))}
        </motion.div>

        {/* Converter card */}
        <motion.div initial={{ opacity:0, y:30 }} whileInView={{ opacity:1, y:0 }}
          viewport={{ once:true }} transition={{ duration:0.7, ease:[0.22,1,0.36,1] }}
          className="rounded-3xl p-8 flex flex-col gap-6"
          style={{ background: "rgba(255,255,255,0.025)", border: "1px solid rgba(255,255,255,0.08)", backdropFilter: "blur(20px)" }}>

          {/* Step 1 — Upload */}
          <div>
            <StepLabel n="01" label="Upload Files"/>
            <DropZone onFilesSelected={processFiles} disabled={isProcessing}/>
          </div>

          {/* Divider */}
          <div style={{ height:"1px", background: "rgba(255,255,255,0.06)" }}/>

          {/* Step 2 — Settings */}
          <div>
            <StepLabel n="02" label="Advanced Options"/>
            <SettingsAccordion
              ocrMode={ocrMode} setOcrMode={setOcrMode}
              chunkPreset={chunkPreset} setChunkPreset={setChunkPreset}
              customChunkSize={customChunkSize} setCustomChunkSize={setCustomChunkSize}
              overlapPct={overlapPct} setOverlapPct={setOverlapPct}
            />
          </div>
        </motion.div>
      </div>
    </section>
  );
});

function StepLabel({ n, label }) {
  return (
    <div className="flex items-center gap-2.5 mb-4">
      <span className="text-xs font-mono font-bold" style={{ color: "#8B5CF6" }}>{n}</span>
      <span className="text-sm font-semibold text-white">{label}</span>
    </div>
  );
}

export default ConverterSection;

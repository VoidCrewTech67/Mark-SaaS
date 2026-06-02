"use client";
import { motion } from "framer-motion";
import { ArrowRight, ExternalLink } from "lucide-react";
import ProductMockup from "@/components/converter/ProductMockup";

const fadeUp = (delay=0) => ({
  initial: { opacity:0, y:30 },
  animate: { opacity:1, y:0 },
  transition: { duration:0.7, delay, ease:[0.22,1,0.36,1] },
});

export default function HeroSection({ onConvertClick }) {
  return (
    <section className="relative min-h-screen flex items-center pt-16" style={{ zIndex: 1 }}>
      <div className="max-w-7xl mx-auto px-6 md:px-12 w-full py-20">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">

          {/* ── Left ─────────────────────────────────────────── */}
          <div className="flex flex-col items-start">
            {/* Badge */}
            <motion.div {...fadeUp(0)}
              className="flex items-center gap-2 px-4 py-2 rounded-full mb-8 text-xs font-medium"
              style={{ background: "rgba(139,92,246,0.1)", border: "1px solid rgba(139,92,246,0.25)", color: "#A78BFA" }}>
              <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse"/>
              Powered by Microsoft MarkItDown + EasyOCR
            </motion.div>

            {/* Headline */}
            <motion.h1 {...fadeUp(0.1)} className="text-5xl md:text-6xl font-black leading-[1.05] tracking-tight mb-6">
              <span className="gradient-text-white">Convert Documents</span>
              <br />
              <span className="gradient-text">Into AI-Ready</span>
              <br />
              <span className="gradient-text-white">Markdown</span>
            </motion.h1>

            {/* Sub-headline */}
            <motion.p {...fadeUp(0.2)} className="text-lg leading-relaxed mb-10 max-w-lg" style={{ color: "#94A3B8" }}>
              OCR extraction, embedded image analysis, token optimization, smart chunking, and batch processing — in one workflow.
            </motion.p>

            {/* Feature pills */}
            <motion.div {...fadeUp(0.25)} className="flex flex-wrap gap-2 mb-10">
              {["15+ Formats","Smart OCR","Token Optimization","Batch Processing","ZIP Export"].map(f => (
                <span key={f} className="px-3 py-1 rounded-full text-xs font-medium"
                  style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)", color: "#94A3B8" }}>
                  {f}
                </span>
              ))}
            </motion.div>

            {/* CTAs */}
            <motion.div {...fadeUp(0.3)} className="flex items-center gap-4">
              <button onClick={onConvertClick}
                className="flex items-center gap-2 px-7 py-3.5 rounded-xl text-sm font-bold text-white transition-all duration-300 hover:scale-[1.02] active:scale-[0.98]"
                style={{ background: "linear-gradient(135deg, #8B5CF6 0%, #6366F1 100%)", boxShadow: "0 0 40px rgba(139,92,246,0.35), 0 4px 24px rgba(0,0,0,0.3)" }}>
                Convert Documents
                <ArrowRight className="w-4 h-4"/>
              </button>
              <a href="https://github.com/microsoft/markitdown" target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-2 px-6 py-3.5 rounded-xl text-sm font-semibold transition-all duration-200 hover:bg-white/5"
                style={{ color: "#94A3B8", border: "1px solid rgba(255,255,255,0.08)" }}>
                View Source <ExternalLink className="w-3.5 h-3.5"/>
              </a>
            </motion.div>
          </div>

          {/* ── Right — 3D Mockup ─────────────────────────── */}
          <motion.div
            initial={{ opacity:0, x:40 }} animate={{ opacity:1, x:0 }}
            transition={{ duration:0.9, delay:0.2, ease:[0.22,1,0.36,1] }}
            className="relative hidden lg:block">
            <ProductMockup/>
          </motion.div>
        </div>
      </div>

      {/* Bottom fade */}
      <div className="absolute bottom-0 inset-x-0 h-32 pointer-events-none"
        style={{ background: "linear-gradient(to top, #050816, transparent)" }}
      />
    </section>
  );
}

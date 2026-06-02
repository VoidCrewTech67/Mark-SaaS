"use client";
import { motion } from "framer-motion";
import { Eye, Image, Layers, Sparkles, Files, Archive } from "lucide-react";

const FEATURES = [
  { icon: Eye,      color: "#8B5CF6", bg: "rgba(139,92,246,0.12)", label: "Smart OCR",           desc: "EasyOCR with heuristic filtering — logos and icons skipped, meaningful text extracted automatically." },
  { icon: Image,    color: "#A855F7", bg: "rgba(168,85,247,0.12)", label: "Embedded Image OCR",  desc: "Every image inside a PDF or DOCX is individually extracted, analyzed, and appended as structured text." },
  { icon: Layers,   color: "#6366F1", bg: "rgba(99,102,241,0.12)", label: "Smart Chunking",      desc: "Heading-aware splits with configurable token limit and overlap — ready for any context window size." },
  { icon: Sparkles, color: "#C084FC", bg: "rgba(192,132,252,0.12)", label: "Token Optimization", desc: "Unicode normalization, deduplication, and page-number stripping reduce token count by up to 30%." },
  { icon: Files,    color: "#818CF8", bg: "rgba(129,140,248,0.12)", label: "Batch Conversion",   desc: "Upload and convert multiple files simultaneously. Each file tracked independently with full metadata." },
  { icon: Archive,  color: "#A78BFA", bg: "rgba(167,139,250,0.12)", label: "ZIP Export",         desc: "Download individual Markdown files or all chunks packed into a named ZIP archive in one click." },
];

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
};
const card = {
  hidden: { opacity:0, y:30 },
  show:   { opacity:1, y:0, transition: { duration:0.6, ease:[0.22,1,0.36,1] } },
};

export default function FeaturesSection() {
  return (
    <section id="features" className="relative py-32" style={{ zIndex: 1 }}>
      <div className="max-w-7xl mx-auto px-6 md:px-12">

        {/* Header */}
        <motion.div className="text-center mb-20"
          initial={{ opacity:0, y:20 }} whileInView={{ opacity:1, y:0 }}
          viewport={{ once:true }} transition={{ duration:0.6 }}>
          <p className="text-xs font-mono font-medium mb-4 tracking-[0.2em] uppercase" style={{ color: "#8B5CF6" }}>
            Everything Included
          </p>
          <h2 className="text-4xl md:text-5xl font-black tracking-tight mb-5">
            <span className="gradient-text-white">Production-grade</span>
            {" "}<span className="gradient-text">document pipeline</span>
          </h2>
          <p className="text-lg max-w-2xl mx-auto" style={{ color: "#94A3B8" }}>
            Built for engineers who need reliable, high-quality Markdown output at scale.
          </p>
        </motion.div>

        {/* Grid */}
        <motion.div variants={container} initial="hidden" whileInView="show" viewport={{ once:true }}
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map(({ icon: Icon, color, bg, label, desc }) => (
            <motion.div key={label} variants={card}
              whileHover={{ y:-6, scale:1.01 }} transition={{ type:"spring", stiffness:300, damping:20 }}
              className="glass glass-hover rounded-2xl p-7 cursor-default group">
              {/* Icon */}
              <div className="w-11 h-11 rounded-xl flex items-center justify-center mb-5 transition-transform duration-300 group-hover:scale-110"
                style={{ background: bg, border: `1px solid ${color}30` }}>
                <Icon className="w-5 h-5" style={{ color }}/>
              </div>
              <h3 className="text-base font-bold text-white mb-2">{label}</h3>
              <p className="text-sm leading-relaxed" style={{ color: "#94A3B8" }}>{desc}</p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}

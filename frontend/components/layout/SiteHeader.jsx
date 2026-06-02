"use client";
import { motion, useScroll, useMotionValueEvent } from "framer-motion";
import { useState } from "react";
import { GitFork, Zap } from "lucide-react";

export default function SiteHeader({ onConvertClick }) {
  const [scrolled, setScrolled] = useState(false);
  const { scrollY } = useScroll();

  useMotionValueEvent(scrollY, "change", (y) => setScrolled(y > 40));

  return (
    <motion.header
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="fixed top-0 inset-x-0 z-50 flex items-center justify-between px-6 md:px-12 h-16"
      style={{
        background: scrolled ? "rgba(5,8,22,0.85)" : "transparent",
        backdropFilter: scrolled ? "blur(20px)" : "none",
        borderBottom: scrolled ? "1px solid rgba(255,255,255,0.06)" : "none",
        transition: "all 0.3s ease",
      }}
    >
      {/* Logo */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: "linear-gradient(135deg, #8B5CF6, #6366F1)" }}>
          <Zap className="w-4 h-4 text-white" strokeWidth={2.5} />
        </div>
        <span className="text-sm font-bold tracking-tight text-white">MarkItDown</span>
      </div>

      {/* Nav */}
      <nav className="hidden md:flex items-center gap-1">
        {[["Features","#features"],["Converter","#converter"],["API","http://localhost:8000/docs"]].map(([label, href]) => (
          <a key={label} href={href}
            className="px-4 py-2 text-sm text-white/50 hover:text-white rounded-lg hover:bg-white/5 transition-all duration-200">
            {label}
          </a>
        ))}
      </nav>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <a href="https://github.com/microsoft/markitdown" target="_blank" rel="noopener noreferrer"
          className="flex items-center gap-1.5 px-3 py-2 text-xs text-white/50 hover:text-white rounded-lg hover:bg-white/5 transition-all duration-200 border border-white/[0.06]">
          <GitFork className="w-3.5 h-3.5" /> Source
        </a>
        <button onClick={onConvertClick}
          className="px-4 py-2 text-xs font-semibold text-white rounded-lg transition-all duration-200"
          style={{ background: "linear-gradient(135deg, #8B5CF6, #6366F1)", boxShadow: "0 0 20px rgba(139,92,246,0.3)" }}>
          Get Started
        </button>
      </div>
    </motion.header>
  );
}

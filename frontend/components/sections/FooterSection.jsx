"use client";
import { Zap } from "lucide-react";

const LINKS = [
  { label:"GitHub",        href:"https://github.com/microsoft/markitdown", ext:true },
  { label:"API Docs",      href:"http://localhost:8000/docs",               ext:true },
  { label:"Redoc",         href:"http://localhost:8000/redoc",              ext:true },
  { label:"Health Check",  href:"http://localhost:8000/api/health",         ext:true },
];

export default function FooterSection() {
  return (
    <footer className="relative border-t py-16" style={{ borderColor: "rgba(255,255,255,0.06)", zIndex: 1 }}>
      <div className="max-w-7xl mx-auto px-6 md:px-12 flex flex-col md:flex-row items-center justify-between gap-8">
        {/* Brand */}
        <div className="flex flex-col items-center md:items-start gap-3">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center"
              style={{ background: "linear-gradient(135deg, #8B5CF6, #6366F1)" }}>
              <Zap className="w-4 h-4 text-white" strokeWidth={2.5}/>
            </div>
            <span className="text-sm font-bold text-white">MarkItDown</span>
          </div>
          <p className="text-xs text-center md:text-left max-w-xs" style={{ color: "#4B5563" }}>
            Powered by Microsoft MarkItDown + EasyOCR.
            Files auto-deleted after 2 hours.
          </p>
        </div>

        {/* Links */}
        <div className="flex flex-wrap items-center justify-center gap-1">
          {LINKS.map(({ label, href }) => (
            <a key={label} href={href} target="_blank" rel="noopener noreferrer"
              className="px-4 py-2 rounded-lg text-sm transition-all duration-200 hover:bg-white/5 hover:text-white"
              style={{ color: "#4B5563" }}>
              {label}
            </a>
          ))}
        </div>

        {/* Copyright */}
        <p className="text-xs" style={{ color: "#374151" }}>
          © {new Date().getFullYear()} MarkItDown Converter
        </p>
      </div>
    </footer>
  );
}

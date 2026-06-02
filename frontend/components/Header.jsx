"use client";

import { Zap, GitFork } from "lucide-react";

export default function Header() {
  return (
    <header className="sticky top-0 z-50 border-b border-zinc-800/60 bg-zinc-950/80 backdrop-blur-xl">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-900/30">
            <span className="text-white text-xs font-bold">M</span>
          </div>
          <div>
            <span className="text-sm font-bold text-zinc-100 tracking-tight">
              MarkItDown
            </span>
            <span className="hidden sm:inline ml-1.5 text-xs text-zinc-600">
              Converter
            </span>
          </div>
        </div>

        {/* Center badge */}
        <div className="hidden sm:flex items-center gap-1.5 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20">
          <Zap className="w-3 h-3 text-indigo-400" />
          <span className="text-[11px] font-mono font-medium text-indigo-400">
            Microsoft MarkItDown
          </span>
        </div>

        {/* Right actions */}
        <div className="flex items-center gap-2">
          <a
            href="https://github.com/microsoft/markitdown"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors border border-transparent hover:border-zinc-700"
          >
            <GitFork className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Source</span>
          </a>
        </div>
      </div>
    </header>
  );
}

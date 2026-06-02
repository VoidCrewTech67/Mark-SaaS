"use client";

import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/Button";

const PREVIEW_LIMIT = 4000;

export default function MarkdownPreview({ markdown, label = "Preview" }) {
  const [copied, setCopied] = useState(false);

  if (!markdown) {
    return (
      <p className="text-xs text-zinc-600 italic">No content available.</p>
    );
  }

  const isLong = markdown.length > PREVIEW_LIMIT;
  const preview = isLong ? markdown.slice(0, PREVIEW_LIMIT) : markdown;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-mono text-zinc-500 uppercase tracking-widest">
          {label}
          {isLong && (
            <span className="ml-2 text-zinc-700">
              (first {(PREVIEW_LIMIT / 1000).toFixed(0)}K chars shown)
            </span>
          )}
        </span>
        <Button variant="ghost" size="sm" onClick={handleCopy} className="gap-1.5">
          {copied ? (
            <><Check className="w-3 h-3 text-emerald-400" /><span className="text-emerald-400">Copied</span></>
          ) : (
            <><Copy className="w-3 h-3" />Copy</>
          )}
        </Button>
      </div>
      <pre className="md-preview overflow-auto max-h-96 text-xs font-mono leading-relaxed text-zinc-300 bg-zinc-950/80 border border-zinc-800 rounded-xl p-4 whitespace-pre-wrap break-words">
        {preview}
        {isLong && "\n\n… (truncated — use Download for full content)"}
      </pre>
    </div>
  );
}

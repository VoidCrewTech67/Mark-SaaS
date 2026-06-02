"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { formatNumber } from "@/lib/utils";

export default function ChunkViewer({
  chunks,
  chunkStatus,
  chunkError,
  fileId,
  filename,
  chunkPreset,
  chunkSize,
  overlapPct,
  onGenerateChunks,
  onDownloadZip,
}) {
  const [expanded, setExpanded] = useState(null);

  const isNone = chunkPreset === "None";

  if (isNone) {
    return (
      <p className="text-xs text-zinc-600 italic">
        Select a chunk size in settings to split this document.
      </p>
    );
  }

  if (!chunks && chunkStatus !== "loading" && chunkStatus !== "error") {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-xs text-zinc-500">
          Chunk into ≤{formatNumber(chunkSize)} tokens with ~{overlapPct}% overlap.
        </p>
        <Button
          variant="secondary"
          size="sm"
          onClick={onGenerateChunks}
          loading={chunkStatus === "loading"}
        >
          🔀 Generate Chunks
        </Button>
      </div>
    );
  }

  if (chunkStatus === "loading") {
    return (
      <div className="flex items-center gap-2 text-xs text-zinc-500">
        <span className="w-3.5 h-3.5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        Generating chunks…
      </div>
    );
  }

  if (chunkStatus === "error") {
    return (
      <p className="text-xs text-red-400">Chunking error: {chunkError}</p>
    );
  }

  if (!chunks?.chunks?.length) return null;

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-xs text-zinc-400">
          <span className="font-mono font-semibold text-zinc-200">{chunks.chunk_count}</span> chunks ·
          ≤{formatNumber(chunks.max_tokens)} tokens · ~{overlapPct}% overlap ·
          <span className="text-zinc-600 ml-1">{chunks.source}</span>
        </p>
        <Button
          variant="secondary"
          size="sm"
          onClick={onDownloadZip}
        >
          ⬇ Download ZIP
        </Button>
      </div>

      {/* Chunk list */}
      <div className="flex flex-col gap-1.5 max-h-[420px] overflow-y-auto pr-1">
        {chunks.chunks.map((chunk, i) => {
          const isOpen = expanded === i;
          const wordCount = chunk.split(/\s+/).length;
          return (
            <div
              key={i}
              className="border border-zinc-800 rounded-lg overflow-hidden"
            >
              <button
                onClick={() => setExpanded(isOpen ? null : i)}
                className="w-full flex items-center justify-between px-3 py-2 hover:bg-zinc-800/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono text-zinc-500 w-16 text-left">
                    #{String(i + 1).padStart(3, "0")}
                  </span>
                  <span className="text-xs text-zinc-400">
                    ~{wordCount.toLocaleString()} words
                  </span>
                </div>
                {isOpen ? (
                  <ChevronUp className="w-3.5 h-3.5 text-zinc-600" />
                ) : (
                  <ChevronDown className="w-3.5 h-3.5 text-zinc-600" />
                )}
              </button>
              {isOpen && (
                <pre className="px-3 pb-3 text-xs font-mono text-zinc-400 whitespace-pre-wrap break-words max-h-48 overflow-y-auto border-t border-zinc-800/60 bg-zinc-950/40 pt-2">
                  {chunk}
                </pre>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

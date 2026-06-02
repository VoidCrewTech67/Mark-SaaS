"use client";
import { motion, AnimatePresence } from "framer-motion";
import { Download, Trash2 } from "lucide-react";
import PremiumResultCard from "@/components/converter/PremiumResultCard";
import { buildZipFromStrings } from "@/lib/clientZip";
import { triggerDownload } from "@/services/api";
import { stemName } from "@/lib/utils";

export default function ResultsSection({ conversion }) {
  const {
    entryList, generateChunks, downloadMd, downloadChunksZip,
    clearAll, clearEntry, chunkPreset, chunkSize, overlapPct,
  } = conversion;

  const successful = entryList.filter(e => e.status === "done" && e.result?.success);

  const handleDownloadAll = async () => {
    if (!successful.length) return;
    const items = successful.map(e => [stemName(e.originalName || "doc") + ".md", e.result?.markdown || ""]);
    const blob = await buildZipFromStrings(items);
    triggerDownload(blob, "markitdown_all.zip");
  };

  if (!entryList.length) return null;

  return (
    <section className="relative py-16 pb-32" style={{ zIndex: 1 }}>
      <div className="max-w-4xl mx-auto px-6 md:px-12">

        {/* Header */}
        <motion.div initial={{ opacity:0, y:16 }} animate={{ opacity:1, y:0 }}
          className="flex items-center justify-between mb-8 flex-wrap gap-4">
          <div>
            <h2 className="text-2xl font-black tracking-tight gradient-text-white">Results</h2>
            <p className="text-sm mt-0.5" style={{ color: "#6B7280" }}>
              {entryList.length} file{entryList.length > 1 ? "s" : ""} processed
            </p>
          </div>
          <div className="flex items-center gap-3">
            {successful.length > 1 && (
              <button onClick={handleDownloadAll}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold text-white transition-all duration-200 hover:scale-[1.02]"
                style={{ background: "rgba(139,92,246,0.2)", border: "1px solid rgba(139,92,246,0.3)" }}>
                <Download className="w-4 h-4"/> Download All
              </button>
            )}
            <button onClick={clearAll}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 hover:bg-white/5"
              style={{ color: "#6B7280", border: "1px solid rgba(255,255,255,0.07)" }}>
              <Trash2 className="w-4 h-4"/> Clear All
            </button>
          </div>
        </motion.div>

        {/* Cards */}
        <div className="flex flex-col gap-4">
          <AnimatePresence mode="popLayout">
            {entryList.map(entry => (
              <PremiumResultCard
                key={entry.clientId}
                entry={entry}
                chunkPreset={chunkPreset}
                chunkSize={chunkSize}
                overlapPct={overlapPct}
                onGenerateChunks={generateChunks}
                onDownloadMd={downloadMd}
                onDownloadZip={downloadChunksZip}
                onRemove={clearEntry}
              />
            ))}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}

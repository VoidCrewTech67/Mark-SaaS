"use client";

import { formatNumber } from "@/lib/utils";

export default function StatsDisplay({ result, optStats }) {
  if (!result) return null;

  const stats = [
    { label: "Tokens", value: formatNumber(result.token_estimate), mono: true },
    { label: "Words", value: formatNumber(result.word_count), mono: true },
    { label: "Chars", value: formatNumber(result.char_count), mono: true },
    { label: "Size", value: `${(result.file_size_bytes / 1024).toFixed(1)} KB`, mono: true },
    { label: "Time", value: `${result.duration_s?.toFixed(2)}s`, mono: true },
  ];

  if (result.embedded_images_ocr_count > 0) {
    stats.push({
      label: "Img OCR",
      value: `${result.embedded_images_ocr_count} img`,
      mono: true,
    });
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Raw stats chips */}
      <div className="flex flex-wrap gap-1.5">
        {stats.map((s) => (
          <div
            key={s.label}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-800/60 border border-zinc-700/60"
          >
            <span className="text-[10px] text-zinc-500">{s.label}</span>
            <span className="text-xs font-mono font-semibold text-zinc-200">{s.value}</span>
          </div>
        ))}
      </div>

      {/* Optimization stats */}
      {optStats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <OptCell label="Original" value={formatNumber(optStats.original_tokens)} unit="tok" />
          <OptCell label="Optimized" value={formatNumber(optStats.optimized_tokens)} unit="tok" />
          <OptCell label="Saved" value={formatNumber(optStats.tokens_saved)} unit="tok" accent />
          <OptCell label="Reduction" value={`${optStats.percent_saved}%`} accent />
        </div>
      )}

      {/* OCR badges */}
      <div className="flex flex-wrap gap-1.5">
        {result.ocr_used && (
          <span className="px-2 py-0.5 rounded-md bg-amber-500/10 border border-amber-500/20 text-amber-400 text-[10px] font-mono">
            ⚡ OCR Fallback Used
          </span>
        )}
        {result.embedded_images_ocr_count > 0 && (
          <span className="px-2 py-0.5 rounded-md bg-violet-500/10 border border-violet-500/20 text-violet-400 text-[10px] font-mono">
            🖼 {result.embedded_images_ocr_count} Image(s) OCR&apos;d
          </span>
        )}
        {result.ocr_warning && (
          <span className="px-2 py-0.5 rounded-md bg-amber-500/10 border border-amber-500/20 text-amber-400 text-[10px]">
            ⚠️ {result.ocr_warning}
          </span>
        )}
      </div>
    </div>
  );
}

function OptCell({ label, value, unit, accent }) {
  return (
    <div
      className={`flex flex-col items-center p-2.5 rounded-lg border text-center ${
        accent
          ? "bg-emerald-500/5 border-emerald-500/20"
          : "bg-zinc-800/50 border-zinc-700/60"
      }`}
    >
      <span className="text-[10px] font-mono text-zinc-500 uppercase tracking-wider mb-0.5">
        {label}
      </span>
      <span
        className={`text-sm font-mono font-bold ${
          accent ? "text-emerald-400" : "text-zinc-100"
        }`}
      >
        {value}
        {unit && <span className="text-zinc-600 text-[10px] ml-1">{unit}</span>}
      </span>
    </div>
  );
}

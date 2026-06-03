"use client";

import { useState, useCallback } from "react";
import {
  uploadFile,
  uploadZip,
  convertFile,
  chunkDocument,
  downloadMarkdown,
  downloadZip,
  triggerDownload,
} from "@/services/api";
import { stemName } from "@/lib/utils";

/**
 * Status lifecycle for a single file:
 *   idle → uploading → uploaded → converting → done | error
 */
export function useConversion() {
  // Map: clientId (Date.now() + index) → ConversionEntry
  const [entries, setEntries] = useState({});
  // Global settings
  const [ocrMode, setOcrMode] = useState("Smart (Recommended)");
  const [chunkPreset, setChunkPreset] = useState("None");
  const [customChunkSize, setCustomChunkSize] = useState(4000);
  const [overlapPct, setOverlapPct] = useState(10);

  const updateEntry = useCallback((clientId, patch) => {
    setEntries((prev) => ({
      ...prev,
      [clientId]: { ...(prev[clientId] || {}), ...patch },
    }));
  }, []);

  // ── Upload + Convert all at once ─────────────────────────────────────────
  const processFiles = useCallback(
    async (files) => {
      const newEntries = {};
      files.forEach((file, i) => {
        const id = `${Date.now()}_${i}`;
        newEntries[id] = {
          clientId: id,
          file,
          status: "idle",
          fileId: null,
          result: null,
          chunks: null,
          error: null,
        };
      });
      setEntries((prev) => ({ ...prev, ...newEntries }));

      // Process each file sequentially (OCR is a singleton on the server)
      for (const [clientId, entry] of Object.entries(newEntries)) {
        const isZip = entry.file.name?.toLowerCase().endsWith(".zip");

        if (isZip) {
          // ── ZIP: upload + convert + merge in one call ────────────────
          updateEntry(clientId, { status: "uploading" });
          try {
            updateEntry(clientId, { status: "converting" });
            const zipResult = await uploadZip(entry.file);
            updateEntry(clientId, {
              status: "done",
              fileId: zipResult.file_id,
              originalName: entry.file.name,
              sizeBytes: entry.file.size,
              supported: true,
              result: {
                file_id: zipResult.file_id,
                source_name: entry.file.name,
                success: zipResult.succeeded > 0,
                markdown: `Merged ${zipResult.succeeded}/${zipResult.total_files} files (${zipResult.skipped} skipped)`,
                token_estimate: zipResult.merged_token_estimate,
                char_count: zipResult.merged_char_count,
                word_count: 0,
                duration_s: 0,
                optimization_stats: null,
              },
            });
          } catch (err) {
            updateEntry(clientId, {
              status: "error",
              error: `ZIP processing failed: ${err.message}`,
            });
          }
          continue;
        }

        // ── Regular file: upload then convert ──────────────────────────
        updateEntry(clientId, { status: "uploading" });
        let uploadData;
        try {
          uploadData = await uploadFile(entry.file);
          updateEntry(clientId, {
            status: "uploaded",
            fileId: uploadData.file_id,
            originalName: uploadData.original_name,
            sizeBytes: uploadData.size_bytes,
            supported: uploadData.supported,
          });
        } catch (err) {
          updateEntry(clientId, {
            status: "error",
            error: `Upload failed: ${err.message}`,
          });
          continue;
        }

        if (!uploadData.supported) {
          updateEntry(clientId, {
            status: "error",
            error: `File type not supported by the conversion engine.`,
          });
          continue;
        }

        // ── Convert ─────────────────────────────────────────────────────
        updateEntry(clientId, { status: "converting" });
        try {
          const result = await convertFile(uploadData.file_id, {
            embedded_ocr_mode: ocrMode,
          });
          updateEntry(clientId, { status: "done", result });
        } catch (err) {
          updateEntry(clientId, {
            status: "error",
            error: `Conversion failed: ${err.message}`,
          });
        }
      }
    },
    [ocrMode, updateEntry]
  );

  // ── Chunk ────────────────────────────────────────────────────────────────
  const generateChunks = useCallback(
    async (clientId) => {
      const entry = entries[clientId];
      if (!entry?.fileId) return;

      const maxTokens = resolveChunkSize(chunkPreset, customChunkSize);
      if (!maxTokens) return;

      const overlapTokens = Math.round(maxTokens * overlapPct / 100);

      updateEntry(clientId, { chunkStatus: "loading" });
      try {
        const data = await chunkDocument(entry.fileId, {
          max_tokens: maxTokens,
          overlap_tokens: overlapTokens,
          use_optimized: true,
        });
        updateEntry(clientId, { chunks: data, chunkStatus: "done" });
      } catch (err) {
        updateEntry(clientId, {
          chunkStatus: "error",
          chunkError: err.message,
        });
      }
    },
    [entries, chunkPreset, customChunkSize, overlapPct, updateEntry]
  );

  // ── Downloads ────────────────────────────────────────────────────────────
  const downloadMd = useCallback(async (clientId) => {
    const entry = entries[clientId];
    if (!entry?.fileId) return;
    const blob = await downloadMarkdown(entry.fileId);
    triggerDownload(blob, stemName(entry.originalName || entry.fileId) + ".md");
  }, [entries]);

  const downloadChunksZip = useCallback(async (clientId) => {
    const entry = entries[clientId];
    if (!entry?.fileId) return;
    const blob = await downloadZip(entry.fileId);
    triggerDownload(blob, stemName(entry.originalName || entry.fileId) + "_chunks.zip");
  }, [entries]);

  // ── Clear ────────────────────────────────────────────────────────────────
  const clearAll = useCallback(() => setEntries({}), []);

  const clearEntry = useCallback(
    (clientId) =>
      setEntries((prev) => {
        const next = { ...prev };
        delete next[clientId];
        return next;
      }),
    []
  );

  const entryList = Object.values(entries).reverse();

  return {
    entries,
    entryList,
    processFiles,
    generateChunks,
    downloadMd,
    downloadChunksZip,
    clearAll,
    clearEntry,
    // Settings
    ocrMode, setOcrMode,
    chunkPreset, setChunkPreset,
    customChunkSize, setCustomChunkSize,
    overlapPct, setOverlapPct,
    // Derived
    chunkSize: resolveChunkSize(chunkPreset, customChunkSize),
  };
}

function resolveChunkSize(preset, custom) {
  const MAP = { "4K tokens": 4000, "8K tokens": 8000, "16K tokens": 16000 };
  if (preset === "None") return null;
  if (preset === "Custom") return custom;
  return MAP[preset] ?? null;
}

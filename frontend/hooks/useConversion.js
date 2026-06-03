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
 *
 * ZIP uploads expand into N individual entries — one per file inside the ZIP.
 * Each entry is identical to a regular single-file entry.
 */
export function useConversion() {
  // Map: clientId → ConversionEntry
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

  const addEntry = useCallback((clientId, data) => {
    setEntries((prev) => ({
      ...prev,
      [clientId]: { clientId, ...data },
    }));
  }, []);

  // ── processFiles ──────────────────────────────────────────────────────────
  const processFiles = useCallback(
    async (files) => {
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const isZip = file.name?.toLowerCase().endsWith(".zip");

        if (isZip) {
          await processZip(file, i);
        } else {
          await processSingleFile(file, i);
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ocrMode, updateEntry, addEntry]
  );

  // ── Single file ───────────────────────────────────────────────────────────
  async function processSingleFile(file, i) {
    const clientId = `${Date.now()}_${i}`;

    addEntry(clientId, {
      file,
      status: "uploading",
      fileId: null,
      result: null,
      chunks: null,
      error: null,
      isZipChild: false,
    });

    // Upload
    let uploadData;
    try {
      uploadData = await uploadFile(file);
      updateEntry(clientId, {
        status: "uploaded",
        fileId: uploadData.file_id,
        originalName: uploadData.original_name,
        sizeBytes: uploadData.size_bytes,
        supported: uploadData.supported,
      });
    } catch (err) {
      updateEntry(clientId, { status: "error", error: `Upload failed: ${err.message}` });
      return;
    }

    if (!uploadData.supported) {
      updateEntry(clientId, { status: "error", error: "File type not supported." });
      return;
    }

    // Convert
    updateEntry(clientId, { status: "converting" });
    try {
      const result = await convertFile(uploadData.file_id, { embedded_ocr_mode: ocrMode });
      updateEntry(clientId, { status: "done", result });
    } catch (err) {
      updateEntry(clientId, { status: "error", error: `Conversion failed: ${err.message}` });
    }
  }

  // ── ZIP file — expands into N individual entries ───────────────────────────
  async function processZip(file, i) {
    // Show the ZIP itself as a placeholder while we process
    const zipClientId = `${Date.now()}_zip_${i}`;
    addEntry(zipClientId, {
      file,
      status: "uploading",
      fileId: null,
      result: null,
      chunks: null,
      error: null,
      isZipPlaceholder: true,
      originalName: file.name,
    });

    let zipResponse;
    try {
      updateEntry(zipClientId, { status: "converting" });
      zipResponse = await uploadZip(file);
    } catch (err) {
      updateEntry(zipClientId, {
        status: "error",
        error: `ZIP processing failed: ${err.message}`,
      });
      return;
    }

    // Remove the placeholder now that we have real entries
    setEntries((prev) => {
      const next = { ...prev };
      delete next[zipClientId];
      return next;
    });

    // Create one entry per file result from the ZIP
    const timestamp = Date.now();
    const newEntries = {};

    for (let j = 0; j < zipResponse.files.length; j++) {
      const f = zipResponse.files[j];
      const childId = `${timestamp}_zip${i}_${j}`;

      if (f.success) {
        newEntries[childId] = {
          clientId: childId,
          file: null,
          status: "done",
          fileId: f.file_id,
          originalName: f.filename,
          sizeBytes: null,
          supported: true,
          isZipChild: true,
          zipSource: file.name,
          result: {
            file_id: f.file_id,
            source_name: f.filename,
            success: true,
            markdown: f.markdown || "",
            optimized_markdown: f.optimized_markdown || f.markdown || "",
            token_estimate: f.token_estimate,
            char_count: f.char_count,
            word_count: f.word_count,
            duration_s: f.duration_s,
            ocr_used: f.ocr_used,
            embedded_images_ocr_count: f.embedded_images_ocr_count,
            optimization_stats: f.optimization_stats,
          },
          chunks: null,
          error: null,
        };
      } else {
        newEntries[childId] = {
          clientId: childId,
          file: null,
          status: "error",
          fileId: f.file_id,
          originalName: f.filename,
          sizeBytes: null,
          supported: true,
          isZipChild: true,
          zipSource: file.name,
          result: null,
          chunks: null,
          error: f.error || "Conversion failed",
        };
      }
    }

    setEntries((prev) => ({ ...prev, ...newEntries }));
  }

  // ── Chunk ─────────────────────────────────────────────────────────────────
  const generateChunks = useCallback(
    async (clientId) => {
      const entry = entries[clientId];
      if (!entry?.fileId) return;

      const maxTokens = resolveChunkSize(chunkPreset, customChunkSize);
      if (!maxTokens) return;

      const overlapTokens = Math.round((maxTokens * overlapPct) / 100);

      updateEntry(clientId, { chunkStatus: "loading" });
      try {
        const data = await chunkDocument(entry.fileId, {
          max_tokens: maxTokens,
          overlap_tokens: overlapTokens,
          use_optimized: true,
        });
        updateEntry(clientId, { chunks: data, chunkStatus: "done" });
      } catch (err) {
        updateEntry(clientId, { chunkStatus: "error", chunkError: err.message });
      }
    },
    [entries, chunkPreset, customChunkSize, overlapPct, updateEntry]
  );

  // ── Downloads ─────────────────────────────────────────────────────────────
  const downloadMd = useCallback(
    async (clientId) => {
      const entry = entries[clientId];
      if (!entry?.fileId) return;
      const blob = await downloadMarkdown(entry.fileId);
      triggerDownload(blob, stemName(entry.originalName || entry.fileId) + ".md");
    },
    [entries]
  );

  const downloadChunksZip = useCallback(
    async (clientId) => {
      const entry = entries[clientId];
      if (!entry?.fileId) return;
      const blob = await downloadZip(entry.fileId);
      triggerDownload(blob, stemName(entry.originalName || entry.fileId) + "_chunks.zip");
    },
    [entries]
  );

  // ── Clear ─────────────────────────────────────────────────────────────────
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

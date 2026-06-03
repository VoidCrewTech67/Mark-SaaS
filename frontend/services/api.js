/**
 * services/api.js
 * All HTTP calls to the FastAPI backend.
 * Base URL is read from NEXT_PUBLIC_API_URL (set in .env.local).
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {}
    throw new Error(detail);
  }
  return res;
}

async function json(path, options = {}) {
  const res = await request(path, options);
  return res.json();
}

// ── Health ────────────────────────────────────────────────────────────────

export async function getHealth() {
  return json("/api/health");
}

// ── Upload ────────────────────────────────────────────────────────────────

/**
 * Upload a single File object.
 * @param {File} file
 * @returns {Promise<{file_id, original_name, size_bytes, supported}>}
 */
export async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  return json("/api/upload", { method: "POST", body: form });
}

/**
 * Upload a ZIP file containing multiple documents.
 * Each supported file is converted independently.
 * @param {File} zipFile
 * @returns {Promise<{
 *   zip_filename: string,
 *   total_files: number,
 *   succeeded: number,
 *   failed: number,
 *   skipped: number,
 *   files: Array<{
 *     file_id: string, filename: string, success: boolean,
 *     markdown: string, optimized_markdown: string,
 *     token_estimate: number, char_count: number, word_count: number,
 *     duration_s: number, ocr_used: boolean,
 *     embedded_images_ocr_count: number, optimization_stats: object|null
 *   }>
 * }>}
 */
export async function uploadZip(zipFile) {
  const form = new FormData();
  form.append("file", zipFile);
  return json("/api/upload-zip", { method: "POST", body: form });
}

// ── Convert ───────────────────────────────────────────────────────────────

/**
 * Convert a single uploaded file.
 * @param {string} fileId
 * @param {object} opts
 * @param {string} opts.embedded_ocr_mode  "Disabled" | "Smart (Recommended)" | "Aggressive"
 */
export async function convertFile(fileId, opts = {}) {
  return json("/api/convert", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_id: fileId,
      embedded_ocr_mode: opts.embedded_ocr_mode ?? "Smart (Recommended)",
    }),
  });
}

/**
 * Batch convert multiple uploaded files.
 * @param {Array<{file_id, embedded_ocr_mode}>} items
 */
export async function convertBatch(items) {
  return json("/api/convert/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
}

// ── Chunk ─────────────────────────────────────────────────────────────────

/**
 * @param {string} fileId
 * @param {object} opts
 * @param {number} opts.max_tokens
 * @param {number|null} opts.overlap_tokens  null → use 10% default
 * @param {boolean} opts.use_optimized
 */
export async function chunkDocument(fileId, opts = {}) {
  return json("/api/chunk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_id: fileId,
      max_tokens: opts.max_tokens ?? 8000,
      overlap_tokens: opts.overlap_tokens ?? null,
      use_optimized: opts.use_optimized ?? true,
    }),
  });
}

// ── Download ─────────────────────────────────────────────────────────────

/**
 * Returns a Blob of the .md file.
 */
export async function downloadMarkdown(fileId) {
  const res = await request(`/api/download/${fileId}`);
  return res.blob();
}

/**
 * Returns a Blob of the chunks .zip file.
 */
export async function downloadZip(fileId) {
  const res = await request(`/api/download-zip/${fileId}`);
  return res.blob();
}

/**
 * Triggers a browser download for a blob.
 */
export function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Stats ─────────────────────────────────────────────────────────────────

export async function getStats(fileId) {
  return json(`/api/stats/${fileId}`);
}

/**
 * lib/clientZip.js
 * Client-side ZIP builder using the built-in CompressionStream API (DEFLATE).
 * Falls back to storing files uncompressed if CompressionStream is unavailable.
 *
 * This lets us generate chunk ZIPs entirely in the browser from in-memory strings
 * without needing a third-party library.
 */

/**
 * Build a ZIP Blob from an array of [filename, content] string pairs.
 * @param {Array<[string, string]>} items  [[filename, content], ...]
 * @returns {Promise<Blob>} A Blob with mime type "application/zip".
 */
export async function buildZipFromStrings(items) {
  const encoder = new TextEncoder();
  const files = items.map(([name, content]) => ({
    name,
    data: encoder.encode(content),
  }));
  return buildZip(files);
}

/**
 * Internal: assemble a ZIP binary from an array of {name, data: Uint8Array} objects.
 */
async function buildZip(files) {
  const parts = [];
  const centralDir = [];
  let offset = 0;

  for (const file of files) {
    const nameBytes = new TextEncoder().encode(file.name);
    const compressed = await deflateRaw(file.data);

    // Local file header
    const localHeader = buildLocalFileHeader(nameBytes, file.data, compressed);
    parts.push(localHeader);
    centralDir.push(
      buildCentralDirEntry(nameBytes, file.data, compressed, offset)
    );
    offset += localHeader.length + compressed.length;
    parts.push(compressed);
  }

  const centralDirOffset = offset;
  const centralDirBytes = concat(centralDir);
  const eocd = buildEndOfCentralDir(
    files.length,
    centralDirBytes.length,
    centralDirOffset
  );

  const result = concat([...parts, centralDirBytes, eocd]);
  return new Blob([result], { type: "application/zip" });
}

// ── Deflate ──────────────────────────────────────────────────────────────────

async function deflateRaw(data) {
  if (typeof CompressionStream !== "undefined") {
    const cs = new CompressionStream("deflate-raw");
    const writer = cs.writable.getWriter();
    writer.write(data);
    writer.close();
    const chunks = [];
    const reader = cs.readable.getReader();
    let done = false;
    while (!done) {
      const { value, done: d } = await reader.read();
      if (value) chunks.push(value);
      done = d;
    }
    return concat(chunks);
  }
  // Fallback: store uncompressed (compression method 0)
  return data;
}

// ── ZIP structure builders ───────────────────────────────────────────────────

function buildLocalFileHeader(nameBytes, original, compressed) {
  const useDeflate = typeof CompressionStream !== "undefined";
  const view = new DataView(new ArrayBuffer(30 + nameBytes.length));
  view.setUint32(0, 0x04034b50, true);   // signature
  view.setUint16(4, 20, true);           // version needed
  view.setUint16(6, 0, true);            // flags
  view.setUint16(8, useDeflate ? 8 : 0, true); // compression method
  view.setUint16(10, 0, true);           // mod time
  view.setUint16(12, 0, true);           // mod date
  view.setUint32(14, crc32(original), true);
  view.setUint32(18, compressed.length, true);
  view.setUint32(22, original.length, true);
  view.setUint16(26, nameBytes.length, true);
  view.setUint16(28, 0, true);           // extra field length
  const out = new Uint8Array(view.buffer);
  out.set(nameBytes, 30);
  return out;
}

function buildCentralDirEntry(nameBytes, original, compressed, localOffset) {
  const useDeflate = typeof CompressionStream !== "undefined";
  const view = new DataView(new ArrayBuffer(46 + nameBytes.length));
  view.setUint32(0, 0x02014b50, true);
  view.setUint16(4, 20, true);
  view.setUint16(6, 20, true);
  view.setUint16(8, 0, true);
  view.setUint16(10, useDeflate ? 8 : 0, true);
  view.setUint16(12, 0, true);
  view.setUint16(14, 0, true);
  view.setUint32(16, crc32(original), true);
  view.setUint32(20, compressed.length, true);
  view.setUint32(24, original.length, true);
  view.setUint16(28, nameBytes.length, true);
  view.setUint16(30, 0, true);
  view.setUint16(32, 0, true);
  view.setUint16(34, 0, true);
  view.setUint16(36, 0, true);
  view.setUint32(38, 0, true);
  view.setUint32(42, localOffset, true);
  const out = new Uint8Array(view.buffer);
  out.set(nameBytes, 46);
  return out;
}

function buildEndOfCentralDir(count, size, offset) {
  const view = new DataView(new ArrayBuffer(22));
  view.setUint32(0, 0x06054b50, true);
  view.setUint16(4, 0, true);
  view.setUint16(6, 0, true);
  view.setUint16(8, count, true);
  view.setUint16(10, count, true);
  view.setUint32(12, size, true);
  view.setUint32(16, offset, true);
  view.setUint16(20, 0, true);
  return new Uint8Array(view.buffer);
}

// ── Utilities ────────────────────────────────────────────────────────────────

function concat(arrays) {
  const total = arrays.reduce((sum, a) => sum + a.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const a of arrays) {
    out.set(a, off);
    off += a.length;
  }
  return out;
}

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let j = 0; j < 8; j++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    t[i] = c;
  }
  return t;
})();

function crc32(data) {
  let c = 0xffffffff;
  for (let i = 0; i < data.length; i++) {
    c = CRC_TABLE[(c ^ data[i]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

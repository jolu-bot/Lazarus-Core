/**
 * LAZARUS CORE – formatters.js
 * Pure utility functions for formatting values in the UI.
 */

// ── Byte sizes ──────────────────────────────────────────────────
const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];

/**
 * Converts a byte count to a human-readable string.
 * @param {number} n - Number of bytes
 * @param {number} [precision=1] - Decimal places
 */
export function formatBytes(n, precision = 1) {
  if (n == null || isNaN(n) || n < 0) return '0 B';
  if (n === 0) return '0 B';
  const i = Math.min(Math.floor(Math.log2(n) / 10), BYTE_UNITS.length - 1);
  if (i === 0) return `${n} B`;
  return `${(n / Math.pow(1024, i)).toFixed(precision)} ${BYTE_UNITS[i]}`;
}

// ── Dates ───────────────────────────────────────────────────────
/**
 * Formats a Unix timestamp (ms) to a locale-aware string.
 */
export function formatDate(ts) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, {
    year:   'numeric',
    month:  'short',
    day:    '2-digit',
    hour:   '2-digit',
    minute: '2-digit',
  });
}

// ── Confidence ─────────────────────────────────────────────────
/**
 * Returns a Tailwind color class based on confidence score 0–1.
 */
export function confidenceColor(score) {
  if (score >= 0.85) return 'text-accent-green';
  if (score >= 0.65) return 'text-yellow-400';
  return 'text-accent';
}

/**
 * Converts a confidence float to a percentage string.
 */
export function formatConfidence(score) {
  return `${Math.round((score ?? 0) * 100)}%`;
}

// ── File status ─────────────────────────────────────────────────
const STATUS_LABEL = ['Active', 'Deleted', 'Fragmented', 'Partial'];
const STATUS_COLOR = [
  'text-accent-green',
  'text-accent',
  'text-yellow-400',
  'text-orange-400',
];

export function statusLabel(s) { return STATUS_LABEL[s] ?? 'Unknown'; }
export function statusColor(s) { return STATUS_COLOR[s] ?? 'text-text-dim'; }

// ── File system names ───────────────────────────────────────────
const FS_NAMES = ['Unknown', 'NTFS', 'EXT4', 'APFS', 'FAT32', 'RAW'];
export function fsName(id) { return FS_NAMES[id] ?? 'Unknown'; }

// ── Percentages ─────────────────────────────────────────────────
export function formatPercent(n) {
  return `${Math.min(100, Math.max(0, Math.round(n ?? 0)))}%`;
}

// ── Numbers ─────────────────────────────────────────────────────
export function formatCount(n) {
  return n?.toLocaleString() ?? '0';
}

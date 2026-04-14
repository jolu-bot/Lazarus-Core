/**
 * LAZARUS CORE – useFormatBytes hook
 * Memoized byte-to-human-readable formatter.
 */
import { useCallback } from 'react';

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

/**
 * Returns a stable formatBytes function.
 * formatBytes(n: number, precision?: number): string
 */
export function useFormatBytes() {
  return useCallback((n, precision = 1) => {
    if (n == null || isNaN(n) || n < 0) return '0 B';
    if (n === 0) return '0 B';
    const idx = Math.min(Math.floor(Math.log2(n) / 10), UNITS.length - 1);
    const val = n / Math.pow(1024, idx);
    return idx === 0 ? `${n} B` : `${val.toFixed(precision)} ${UNITS[idx]}`;
  }, []);
}

export function formatBytes(n, precision = 1) {
  if (n == null || isNaN(n) || n < 0) return '0 B';
  if (n === 0) return '0 B';
  const idx = Math.min(Math.floor(Math.log2(n) / 10), UNITS.length - 1);
  const val = n / Math.pow(1024, idx);
  return idx === 0 ? `${n} B` : `${val.toFixed(precision)} ${UNITS[idx]}`;
}

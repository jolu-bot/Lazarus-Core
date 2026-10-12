import React, { useEffect, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { CheckCircle2, Circle, Image as ImageIcon, FileQuestion } from 'lucide-react';
import clsx from 'clsx';
import { useAppStore, fileDb } from '../../stores/useAppStore';

const lzr = window.lazarus;
const COLS = 4;
const CELL = 118;

// id -> { src } | { none: true } ; conservé entre les rendus et les changements de filtre
const thumbCache = new Map();
const pending = new Set();

export default function GalleryGrid() {
  const filteredCount = useAppStore((s) => s.filteredCount);
  const filesVersion = useAppStore((s) => s.filesVersion);
  const selectedFile = useAppStore((s) => s.selectedFile);
  const selectFile = useAppStore((s) => s.selectFile);
  const toggleSelect = useAppStore((s) => s.toggleSelect);
  const sessionId = useAppStore((s) => s.sessionId);
  const [, tick] = useState(0);
  const parentRef = useRef(null);
  const timer = useRef(null);
  const rows = Math.ceil(filteredCount / COLS);

  const rv = useVirtualizer({ count: rows, getScrollElement: () => parentRef.current, estimateSize: () => CELL, overscan: 3 });
  const items = rv.getVirtualItems();

  useEffect(() => { thumbCache.clear(); pending.clear(); }, [sessionId]);

  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const need = [];
      for (const vr of items) {
        for (let c = 0; c < COLS; c++) {
          const f = fileDb.filtered[vr.index * COLS + c];
          if (f && f.type === 1 && !thumbCache.has(f.id) && !pending.has(f.id)) need.push(f.id);
        }
      }
      while (need.length) {
        const ids = need.splice(0, 24);
        ids.forEach((i) => pending.add(i));
        const r = await lzr?.invoke('scan:thumbs', ids);
        const got = new Map((r?.thumbs || []).map((t) => [t.id, t]));
        ids.forEach((i) => {
          pending.delete(i);
          const t = got.get(i);
          thumbCache.set(i, t && t.b64 ? { src: `data:${t.mime};base64,${t.b64}` } : { none: true });
        });
        tick((n) => n + 1);
      }
    }, 150);
    return () => clearTimeout(timer.current);
  }, [items.map((i) => i.index).join(','), filesVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={parentRef} className="flex-1 overflow-y-auto">
      <div style={{ height: rv.getTotalSize(), position: 'relative' }}>
        {items.map((vr) => (
          <div key={vr.key} style={{ position: 'absolute', top: vr.start, left: 0, right: 0, height: vr.size }} className="flex gap-1 px-2 py-0.5">
            {Array.from({ length: COLS }, (_, c) => {
              const f = fileDb.filtered[vr.index * COLS + c];
              if (!f) return <div key={c} className="flex-1" />;
              const th = thumbCache.get(f.id);
              const sel = selectedFile && selectedFile.id === f.id;
              const chk = fileDb.selected.has(f.id);
              return (
                <div key={c} onClick={() => selectFile(f)} title={`${f.name}\n${f.path || ''}`}
                  className={clsx('relative flex-1 min-w-0 rounded-lg overflow-hidden bg-surface-2 border cursor-pointer group',
                    sel ? 'border-primary ring-1 ring-primary' : 'border-surface-border hover:border-primary/50')}>
                  {th?.src ? <img src={th.src} alt="" className="w-full h-full object-cover" draggable={false} />
                    : <div className="w-full h-full flex items-center justify-center text-text-dim">{th?.none ? <FileQuestion size={22} className="opacity-40" /> : <ImageIcon size={22} className="opacity-30 animate-pulse" />}</div>}
                  <button onClick={(e) => { e.stopPropagation(); toggleSelect(f.id); tick((n) => n + 1); }}
                    className={clsx('absolute top-1 left-1 rounded-full bg-black/50', chk ? 'text-primary' : 'text-white/70 opacity-0 group-hover:opacity-100')}>
                    {chk ? <CheckCircle2 size={16} /> : <Circle size={16} />}
                  </button>
                  <div className="absolute bottom-0 inset-x-0 px-1 py-0.5 text-[9px] text-white bg-gradient-to-t from-black/70 to-transparent truncate">{f.name}</div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

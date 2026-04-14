import React, { useMemo, useState, useRef, useCallback } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { motion }      from 'framer-motion';
import { useAppStore } from '../../stores/useAppStore';
import {
  Image, Film, Music, FileText, Archive, File,
  Search, SlidersHorizontal, CheckCircle2, Circle,
  Download, Trash2, Star
} from 'lucide-react';
import clsx from 'clsx';

const FILE_TYPE_ICONS = {
  0: File, 1: Image, 2: Film, 3: Music, 4: FileText, 5: Archive, 6: File,
};
const FILE_TYPE_COLORS = {
  0: 'text-text-dim', 1: 'text-blue-400', 2: 'text-purple-400',
  3: 'text-green-400', 4: 'text-yellow-400', 5: 'text-orange-400', 6: 'text-text-dim',
};
const STATUS_LABELS = { 0: 'Active', 1: 'Deleted', 2: 'Fragmented', 3: 'Partial' };
const STATUS_COLORS = {
  0: 'text-accent-green', 1: 'text-accent', 2: 'text-yellow-400', 3: 'text-orange-400'
};

const FILTERS = [
  { id: 'all',       label: 'All' },
  { id: 'images',    label: 'Images'    },
  { id: 'videos',    label: 'Videos'    },
  { id: 'audio',     label: 'Audio'     },
  { id: 'documents', label: 'Documents' },
  { id: 'archives',  label: 'Archives'  },
];

export default function FileList() {
  const {
    filteredFiles, selectedFile, selectFile,
    filter, setFilter, license,
  } = useAppStore();

  const [selected, setSelected]   = useState(new Set());
  const parentRef                 = useRef(null);

  const rowVirtualizer = useVirtualizer({
    count:       filteredFiles.length,
    getScrollElement: () => parentRef.current,
    estimateSize: useCallback(() => 44, []),
    overscan:    10,
  });

  const toggleSelect = (e, id) => {
    e.stopPropagation();
    setSelected((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  };

  const handleRecover = async () => {
    if (!license.features?.recover) {
      alert('Upgrade to Pro to recover files.');
      return;
    }
    const toRecover = filteredFiles.filter((f) => selected.has(f.id));
    if (toRecover.length === 0) return;
    const dir = await window.lazarus?.invoke('dialog:openFolder');
    if (!dir) return;
    for (const f of toRecover) {
      await window.lazarus?.invoke('scan:recover', '', f, dir);
    }
    alert(`Recovery complete: ${toRecover.length} file(s) → ${dir}`);
  };

  return (
    <div className="flex flex-col w-[480px] border-r border-surface-border flex-shrink-0 bg-bg">
      {/* ── Toolbar ─────────────────────────────────────────── */}
      <div className="flex flex-col gap-2 px-3 py-2 border-b border-surface-border bg-bg-2">
        {/* Search */}
        <div className="flex items-center gap-2 bg-surface rounded-lg px-3 py-1.5
                        border border-surface-border focus-within:border-primary/50 transition-colors">
          <Search size={13} className="text-text-dim" />
          <input
            type="text"
            placeholder="Search files…"
            value={filter.search}
            onChange={(e) => setFilter({ search: e.target.value })}
            className="flex-1 bg-transparent text-sm text-text placeholder-text-dim outline-none"
          />
        </div>

        {/* Type filters */}
        <div className="flex gap-1 overflow-x-auto scrollbar-none">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => setFilter({ type: f.id })}
              className={clsx(
                'px-2.5 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition-all duration-150',
                filter.type === f.id
                  ? 'bg-primary/20 text-primary border border-primary/30'
                  : 'text-text-dim hover:text-text hover:bg-surface-2'
              )}
            >
              {f.label}
            </button>
          ))}
          <button
            onClick={() => setFilter({ statusDeleted: !filter.statusDeleted })}
            className={clsx(
              'ml-auto px-2.5 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition-all',
              filter.statusDeleted
                ? 'bg-accent/20 text-accent border border-accent/30'
                : 'text-text-dim hover:text-text hover:bg-surface-2'
            )}
          >
            Deleted only
          </button>
        </div>
      </div>

      {/* ── Count + Batch actions ────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-surface-border
                      bg-bg-2 text-xs text-text-dim">
        <span>{filteredFiles.length.toLocaleString()} files found</span>
        {selected.size > 0 && (
          <button
            onClick={handleRecover}
            className="flex items-center gap-1 text-primary hover:text-primary-hover
                       font-medium transition-colors"
          >
            <Download size={12} />
            Recover {selected.size}
          </button>
        )}
      </div>

      {/* ── Virtual List ────────────────────────────────────── */}
      <div ref={parentRef} className="flex-1 overflow-y-auto">
        {filteredFiles.length === 0 ? (
          <EmptyState />
        ) : (
          <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
            {rowVirtualizer.getVirtualItems().map((vr) => {
              const f    = filteredFiles[vr.index];
              const Icon = FILE_TYPE_ICONS[f.type] || File;
              const isSelected = f === selectedFile;
              const isChecked  = selected.has(f.id);

              return (
                <div
                  key={vr.key}
                  ref={rowVirtualizer.measureElement}
                  style={{ position: 'absolute', top: vr.start, left: 0, right: 0 }}
                  onClick={() => selectFile(f)}
                  className={clsx(
                    'flex items-center gap-2.5 px-3 py-2 cursor-pointer transition-all',
                    'border-b border-surface-border/30',
                    isSelected
                      ? 'bg-primary/10 border-l-2 border-l-primary'
                      : 'hover:bg-surface-2/50'
                  )}
                >
                  {/* Checkbox */}
                  <button
                    onClick={(e) => toggleSelect(e, f.id)}
                    className="flex-shrink-0 text-text-dim hover:text-primary transition-colors"
                  >
                    {isChecked
                      ? <CheckCircle2 size={14} className="text-primary" />
                      : <Circle size={14} />}
                  </button>

                  {/* Icon */}
                  <Icon size={16} className={clsx('flex-shrink-0', FILE_TYPE_COLORS[f.type])} />

                  {/* Name & meta */}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-text truncate font-medium">{f.name}</div>
                    <div className="flex items-center gap-2 text-xs text-text-dim">
                      <span className={STATUS_COLORS[f.status]}>{STATUS_LABELS[f.status]}</span>
                      <span>·</span>
                      <span>{formatSize(f.size)}</span>
                    </div>
                  </div>

                  {/* Confidence */}
                  <div className="flex-shrink-0 text-right">
                    <div className={clsx('text-xs font-mono font-semibold',
                      f.confidence > 0.8 ? 'text-accent-green'
                      : f.confidence > 0.6 ? 'text-yellow-400' : 'text-accent')}>
                      {Math.round(f.confidence * 100)}%
                    </div>
                    <div className="text-xs text-text-dim">.{f.extension || '?'}</div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3 text-text-dim py-20">
      <HardDriveIcon />
      <p className="text-sm">Start a scan to find recoverable files</p>
    </div>
  );
}

function HardDriveIcon() {
  return (
    <div className="w-16 h-16 rounded-2xl bg-surface-2 flex items-center justify-center">
      <FileText size={28} className="text-text-dim" />
    </div>
  );
}

function formatSize(n) {
  if (!n) return '0 B';
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
  return (n / 1073741824).toFixed(2) + ' GB';
}


import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { HardDrive, ChevronDown, Usb, FileDigit, History, Layers, Boxes } from 'lucide-react';
import clsx from 'clsx';
import { useAppStore } from '../../stores/useAppStore';
import { formatBytes } from '../../utils/formatters';
import { useT } from '../../i18n';

const lzr = window.lazarus;

function iconFor(d) {
  if (d.kind === 'image') return FileDigit;
  if (d.kind === 'shadow-sm') return History;
  if (d.kind === 'virtual') return Boxes;
  if (d.kind === 'volume') return Layers;
  if ((d.interface || '').toLowerCase().includes('usb')) return Usb;
  return HardDrive;
}

export default function SourcePicker({ value, onChange, includeShadows = true, disabled = false, allowImage = true }) {
  const t = useT();
  const drives = useAppStore((s) => s.drives);
  const addCustomDrive = useAppStore((s) => s.addCustomDrive);
  const [open, setOpen] = useState(false);
  const [shadows, setShadows] = useState([]);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    if (includeShadows) lzr?.invoke('scan:vss-list').then((s) => setShadows(Array.isArray(s) ? s : [])).catch(() => {});
    return () => document.removeEventListener('mousedown', close);
  }, [open, includeShadows]);

  const openImage = async () => {
    const p = await lzr?.invoke('dialog:openFile');
    setOpen(false);
    if (!p) return;
    const name = p.split(/[\\/]/).pop();
    const d = { path: p, kind: 'image', label: name, model: 'Image disque', interface: 'image', totalSize: 0, fs: '' };
    addCustomDrive(d);
    onChange(d);
  };

  const groups = [
    { title: t('scan.disks'), items: drives.filter((d) => d.kind === 'disk') },
    { title: t('scan.volumes'), items: drives.filter((d) => d.kind === 'volume') },
    { title: t('scan.shadows'), items: shadows },
    { title: 'Images', items: drives.filter((d) => d.kind === 'image') },
    { title: 'RAID / BitLocker (volumes virtuels)', items: drives.filter((d) => d.kind === 'virtual') },
  ].filter((g) => g.items.length);

  const Sel = value ? iconFor(value) : HardDrive;
  return (
    <div className="relative" ref={ref}>
      <button
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 bg-surface-2 border border-surface-border rounded-lg px-3 py-2 text-sm hover:border-primary/50 transition-colors min-w-[300px] max-w-[460px] disabled:opacity-50"
      >
        <Sel size={15} className="text-primary shrink-0" />
        <span className="flex-1 text-left text-text truncate">{value ? value.label || value.path : drives.length === 0 ? t('scan.detecting') : t('scan.select')}</span>
        {value?.totalSize > 0 && <span className="text-xs text-text-dim font-mono">{formatBytes(value.totalSize)}</span>}
        <ChevronDown size={13} className="text-text-dim" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
            className="absolute top-full left-0 mt-1 bg-surface-2 border border-surface-border rounded-xl shadow-panel z-50 min-w-[420px] max-h-[70vh] overflow-y-auto"
          >
            {groups.map((g) => (
              <div key={g.title}>
                <div className="px-4 pt-3 pb-1 text-[10px] uppercase tracking-wider text-text-dim">{g.title}</div>
                {g.items.map((d) => {
                  const Icon = iconFor(d);
                  return (
                    <button
                      key={d.path}
                      onClick={() => { onChange(d); setOpen(false); }}
                      className={clsx('w-full flex items-center gap-2 px-4 py-2 text-sm text-left hover:bg-primary/10 transition-colors',
                        d.path === value?.path && 'text-primary bg-primary/5', d.kind === 'volume' && 'pl-8')}
                    >
                      <Icon size={14} className="shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="font-medium truncate">{d.label || d.path}</div>
                        <div className="text-xs text-text-dim font-mono truncate">
                          {d.path}{d.interface ? ` · ${d.interface}` : ''}{d.mediaType ? ` · ${d.mediaType}` : ''}{d.health && d.health !== 'Healthy' ? ` · ⚠ ${d.health}` : ''}
                        </div>
                      </div>
                      {d.totalSize > 0 && <span className="text-xs text-text-dim">{formatBytes(d.totalSize)}</span>}
                    </button>
                  );
                })}
              </div>
            ))}
            {groups.length === 0 && <div className="px-4 py-3 text-sm text-text-dim">—</div>}
            {allowImage && (
              <button onClick={openImage} className="w-full flex items-center gap-2 px-4 py-3 text-sm text-primary hover:bg-primary/10 border-t border-surface-border">
                <FileDigit size={14} /> {t('scan.openImage')}
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

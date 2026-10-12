import React, { useState, useRef, useCallback, useMemo } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useAppStore, fileDb } from '../../stores/useAppStore';
import {
  Image, Film, Music, FileText, Archive, File, Search, CheckCircle2, Circle, Download, AlertTriangle,
  Wrench, RefreshCcw, ShieldCheck, FileDown, ArrowDownAZ, ArrowUpAZ, LayoutGrid, List,
} from 'lucide-react';
import GalleryGrid from './GalleryGrid';
import clsx from 'clsx';
import { formatBytes } from '../../utils/formatters';
import { useT } from '../../i18n';

const lzr = window.lazarus;
const TYPE_ICONS = { 0: File, 1: Image, 2: Film, 3: Music, 4: FileText, 5: Archive, 6: File };
const TYPE_COLORS = { 0: 'text-text-dim', 1: 'text-blue-400', 2: 'text-purple-400', 3: 'text-green-400', 4: 'text-yellow-400', 5: 'text-orange-400', 6: 'text-text-dim' };
const ST_COLORS = { 0: 'text-accent-green', 1: 'text-accent', 2: 'text-yellow-400', 3: 'text-orange-400' };
const hColor = (s) => (s >= 85 ? '#22c55e' : s >= 70 ? '#eab308' : s >= 50 ? '#f97316' : '#ef4444');
const FILTERS = [['all', 'files.all'], ['images', 'files.images'], ['videos', 'files.videos'], ['audio', 'files.audio'], ['documents', 'files.documents'], ['archives', 'files.archives']];
const SOURCES = ['all', 'ntfs', 'fat', 'exfat', 'ext', 'carve'];

export default function FileList() {
  const t = useT();
  const filter = useAppStore((s) => s.filter);
  const setFilter = useAppStore((s) => s.setFilter);
  const filteredCount = useAppStore((s) => s.filteredCount);
  const totalCount = useAppStore((s) => s.totalCount);
  const filesVersion = useAppStore((s) => s.filesVersion);
  const selectedFile = useAppStore((s) => s.selectedFile);
  const selectFile = useAppStore((s) => s.selectFile);
  const selectionCount = useAppStore((s) => s.selectionCount);
  const selectionBytes = useAppStore((s) => s.selectionBytes);
  const sortKey = useAppStore((s) => s.sortKey);
  const sortDir = useAppStore((s) => s.sortDir);
  const setSort = useAppStore((s) => s.setSort);
  const toggleSelect = useAppStore((s) => s.toggleSelect);
  const selectRange = useAppStore((s) => s.selectRange);
  const selectAllFiltered = useAppStore((s) => s.selectAllFiltered);
  const clearSelection = useAppStore((s) => s.clearSelection);
  const addToast = useAppStore((s) => s.addToast);
  const setRecovery = useAppStore((s) => s.setRecovery);
  const [gallery, setGallery] = useState(false);
  const [lastClicked, setLastClicked] = useState(-1);
  const [reportLoading, setReportLoading] = useState(false);
  const parentRef = useRef(null);
  const [searchDraft, setSearchDraft] = useState('');
  const searchTimer = useRef(null);

  const rv = useVirtualizer({
    count: filteredCount,
    getScrollElement: () => parentRef.current,
    estimateSize: useCallback(() => 54, []),
    overscan: 12,
  });

  const onSearch = (v) => {
    setSearchDraft(v);
    clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => setFilter({ search: v }), 250);
  };

  const sourceOptions = useMemo(() => {
    const set = new Set(SOURCES);
    for (const f of fileDb.files.length < 50000 ? fileDb.files : []) set.add(f.source || 'unknown');
    return Array.from(set);
  }, [filesVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  const exportFiles = async (fmt) => {
    if (!fileDb.filtered.length) { addToast(t('files.empty'), 'error'); return; }
    const r = await lzr?.invoke('app:export-files', { files: fileDb.filtered, format: fmt });
    if (r) addToast(`${fileDb.filtered.length} ${t('files.found')} → ${r}`, 'success');
  };

  const startRecovery = () => {
    const ids = Array.from(fileDb.selected);
    if (!ids.length) return;
    setRecovery({ open: true, phase: 'choose', ids, files: [], result: null, progress: null, blocked: null, dest: useAppStore.getState().outputDir || '' });
  };

  const makeReport = async () => {
    const list = fileDb.selected.size ? fileDb.files.filter((f) => fileDb.selected.has(f.id)) : fileDb.filtered;
    if (!list.length) { addToast(t('files.empty'), 'error'); return; }
    const dir = await lzr?.invoke('dialog:openFolder');
    if (!dir) return;
    setReportLoading(true);
    const s = useAppStore.getState();
    const r = await lzr?.invoke('scan:generate-report', { files: list, outputDir: dir, device: s.selectedDrive?.path });
    setReportLoading(false);
    if (r?.success) { addToast(`${t('files.report')} : ${r.totalFiles}`, 'success'); lzr?.invoke('shell:openPath', dir); }
    else addToast(r?.message || 'Erreur', 'error');
  };

  const rowClick = (e, f, index) => {
    selectFile(f);
    if (e.shiftKey && lastClicked >= 0) selectRange(lastClicked, index);
    setLastClicked(index);
  };

  const items = rv.getVirtualItems();
  return (
    <div className="flex flex-col w-[520px] min-w-[420px] border-r border-surface-border flex-shrink-0 bg-bg">
      <div className="flex flex-col gap-2 px-3 py-2 border-b border-surface-border bg-bg-2">
        <div className="flex items-center gap-2 bg-surface rounded-lg px-3 py-1.5 border border-surface-border focus-within:border-primary/50 transition-colors">
          <Search size={13} className="text-text-dim" />
          <input type="text" placeholder={t('files.search')} value={searchDraft} onChange={(e) => onSearch(e.target.value)}
            className="flex-1 bg-transparent text-sm text-text placeholder-text-dim outline-none" />
        </div>
        <div className="flex gap-1 overflow-x-auto">
          {FILTERS.map(([id, label]) => (
            <button key={id} onClick={() => setFilter({ type: id })}
              className={clsx('px-2.5 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition-all',
                filter.type === id ? 'bg-primary/20 text-primary border border-primary/30' : 'text-text-dim hover:text-text hover:bg-surface-2')}>
              {t(label)}
            </button>
          ))}
          <button onClick={() => setFilter({ statusDeleted: !filter.statusDeleted })}
            className={clsx('ml-auto px-2.5 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition-all',
              filter.statusDeleted ? 'bg-accent/20 text-accent border border-accent/30' : 'text-text-dim hover:text-text hover:bg-surface-2')}>
            {t('files.deletedOnly')}
          </button>
        </div>
        <div className="grid grid-cols-[auto_1fr_auto] items-center gap-x-2 gap-y-1.5 px-1 text-xs">
          <span className="text-text-dim">{t('files.minHealth')}</span>
          <input type="range" min="0" max="100" step="5" value={filter.minHealth || 0} onChange={(e) => setFilter({ minHealth: parseInt(e.target.value, 10) })}
            className="accent-primary cursor-pointer" style={{ height: '3px' }} />
          <span className="font-mono text-text-dim w-9 text-right">{filter.minHealth || 0} %</span>
          <span className="text-text-dim">{t('files.extension')}</span>
          <input type="text" placeholder="jpg" value={filter.ext || ''} onChange={(e) => setFilter({ ext: e.target.value.replace(/^\.+/, '').toLowerCase() })}
            className="col-span-2 bg-surface-2 border border-surface-border rounded-lg px-2 py-0.5 text-xs text-text outline-none focus:border-primary/50" />
          <span className="text-text-dim">{t('files.source')}</span>
          <select value={filter.source || 'all'} onChange={(e) => setFilter({ source: e.target.value })}
            className="col-span-2 bg-surface-2 border border-surface-border rounded-lg px-2 py-0.5 text-xs text-text outline-none focus:border-primary/50">
            {sourceOptions.map((src) => <option key={src} value={src}>{src === 'all' ? t('files.all') : src}</option>)}
          </select>
          <span className="text-text-dim">{t('files.sort')}</span>
          <select value={sortKey} onChange={(e) => setSort(e.target.value, sortDir)}
            className="bg-surface-2 border border-surface-border rounded-lg px-2 py-0.5 text-xs text-text outline-none focus:border-primary/50">
            {['found', 'name', 'size', 'health', 'path'].map((k) => <option key={k} value={k}>{t('files.sort.' + k)}</option>)}
          </select>
          <button onClick={() => setSort(sortKey, sortDir === 'asc' ? 'desc' : 'asc')} className="p-1 rounded text-text-dim hover:text-text">
            {sortDir === 'asc' ? <ArrowDownAZ size={14} /> : <ArrowUpAZ size={14} />}
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-surface-border bg-bg-2 text-xs text-text-dim">
        <span title={`${totalCount.toLocaleString()} total`}>{filteredCount.toLocaleString()} {t('files.found')}{filteredCount !== totalCount ? ` / ${totalCount.toLocaleString()}` : ''}</span>
        <div className="flex items-center gap-2">
          <button onClick={() => setGallery((g) => !g)} title={gallery ? t('files.view.list') : t('files.view.gallery')} className="hover:text-primary transition-colors">{gallery ? <List size={13} /> : <LayoutGrid size={13} />}</button>
          <span className="opacity-30">|</span>
          <button onClick={selectAllFiltered} className="hover:text-primary transition-colors">{t('files.selectAll')}</button>
          <span className="opacity-30">|</span>
          <button onClick={clearSelection} className="hover:text-primary transition-colors">{t('files.selectNone')}</button>
          <span className="opacity-30">|</span>
          <button onClick={() => exportFiles('csv')} className="flex items-center gap-1 hover:text-primary transition-colors"><FileDown size={12} />CSV</button>
          <button onClick={() => exportFiles('json')} className="flex items-center gap-1 hover:text-primary transition-colors"><FileDown size={12} />JSON</button>
          <button onClick={makeReport} disabled={reportLoading} className="flex items-center gap-1 hover:text-green-400 transition-colors disabled:opacity-40"><ShieldCheck size={12} />{reportLoading ? '…' : t('files.report')}</button>
        </div>
      </div>

      {selectionCount > 0 && (
        <button onClick={startRecovery}
          className="flex items-center justify-center gap-2 mx-3 my-2 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary-hover shadow-glow-sm transition-all">
          <Download size={15} /> {t('files.recover')} {selectionCount.toLocaleString()} {t('files.selected')} · {formatBytes(selectionBytes)}
        </button>
      )}

      {gallery && filteredCount > 0 ? <GalleryGrid /> : (
      <div ref={parentRef} className="flex-1 overflow-y-auto">
        {filteredCount === 0 ? <EmptyState /> : (
          <div style={{ height: rv.getTotalSize(), position: 'relative' }}>
            {items.map((vr) => {
              const f = fileDb.filtered[vr.index];
              if (!f) return null;
              const Icon = TYPE_ICONS[f.type] || File;
              const isSel = selectedFile && f.id === selectedFile.id;
              const isChk = fileDb.selected.has(f.id);
              const health = f.health || {};
              const score = health.score ?? Math.round((f.confidence || 0) * 100);
              const rm = health.repairMode ?? 0;
              const st = f.status ?? 0;
              return (
                <div key={vr.key} style={{ position: 'absolute', top: vr.start, left: 0, right: 0, height: vr.size }}
                  onClick={(e) => rowClick(e, f, vr.index)}
                  className={clsx('flex items-center gap-2.5 px-3 cursor-pointer transition-colors border-b border-surface-border/30',
                    isSel ? 'bg-primary/10 border-l-2 border-l-primary' : 'hover:bg-surface-2/50')}>
                  <button onClick={(e) => { e.stopPropagation(); toggleSelect(f.id); setLastClicked(vr.index); }}
                    className="flex-shrink-0 text-text-dim hover:text-primary transition-colors">
                    {isChk ? <CheckCircle2 size={15} className="text-primary" /> : <Circle size={15} />}
                  </button>
                  <Icon size={16} className={clsx('flex-shrink-0', TYPE_COLORS[f.type])} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-text truncate font-medium" title={f.path || f.name}>{f.name}</div>
                    <div className="flex items-center gap-1.5 text-xs text-text-dim mt-0.5 min-w-0">
                      <span className={ST_COLORS[st]}>{t('status.' + st)}</span>
                      <span>·</span><span>{formatBytes(f.size)}</span>
                      <span>·</span><span className="uppercase text-[10px] text-primary/80">{f.source || '?'}</span>
                      {f.dir ? <><span>·</span><span className="truncate" title={f.dir}>{f.dir}</span></> : null}
                      {rm > 0 && (
                        <span className="flex items-center gap-0.5 ml-1 flex-shrink-0">
                          {rm === 1 ? <Wrench size={11} className="text-yellow-400" /> : rm === 2 ? <AlertTriangle size={11} className="text-orange-400" /> : <RefreshCcw size={11} className="text-red-400" />}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex-shrink-0 flex flex-col items-end gap-1">
                    <div className="flex items-center gap-1">
                      <span className="text-xs font-mono font-semibold" style={{ color: hColor(score) }}>{score}%</span>
                      <span className="text-[10px] text-text-dim">.{f.extension || '?'}</span>
                    </div>
                    <div className="w-16 h-1.5 rounded-full bg-surface-border overflow-hidden">
                      <div className="h-full rounded-full" style={{ width: `${score}%`, background: hColor(score) }} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      )}
    </div>
  );
}

function EmptyState() {
  const t = useT();
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-text-dim p-8 text-center">
      <Search size={40} className="opacity-20" />
      <div><p className="text-sm font-medium text-text-muted">{t('files.empty')}</p><p className="text-xs mt-1 opacity-60">{t('files.empty.hint')}</p></div>
    </div>
  );
}

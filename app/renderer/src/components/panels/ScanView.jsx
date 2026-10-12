import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Play, StopCircle, Settings2, RefreshCw, ShieldAlert, AlertTriangle, Layers } from 'lucide-react';
import clsx from 'clsx';
import { useAppStore, MAX_ITEMS } from '../../stores/useAppStore';
import FileList from './FileList';
import PreviewPanel from './PreviewPanel';
import RecoveryDialog from './RecoveryDialog';
import ProgressBar from '../ui/ProgressBar';
import SourcePicker from '../ui/SourcePicker';
import { formatBytes } from '../../utils/formatters';
import { useT } from '../../i18n';

const lzr = window.lazarus;
// catégories de carving -> extensions/groupes de signatures du moteur
const CAT_EXTS = {
  images: ['jpg', 'png', 'gif', 'bmp', 'tif', 'mp4'],
  video: ['mp4', 'mkv', 'wmv', 'flv', 'riff', 'wav'],
  audio: ['mp3', 'ogg', 'flac', 'aiff', 'mid', 'riff', 'wav'],
  documents: ['pdf', 'zip', 'doc', 'pst', 'vcf', 'ics', 'sqlite'],
  archives: ['zip', '7z', 'rar', 'gz', 'cab', 'exe', 'elf', 'vhdx', 'qcow2'],
};
const CAT_LABEL = { images: 'Images', video: 'Vidéos', audio: 'Audio', documents: 'Documents', archives: 'Archives / programmes' };

export default function ScanView() {
  const t = useT();
  const selectedDrive = useAppStore((s) => s.selectedDrive);
  const selectDrive = useAppStore((s) => s.selectDrive);
  const scanState = useAppStore((s) => s.scanState);
  const progress = useAppStore((s) => s.progress);
  const scanOptions = useAppStore((s) => s.scanOptions);
  const setScanOptions = useAppStore((s) => s.setScanOptions);
  const layout = useAppStore((s) => s.layout);
  const warnings = useAppStore((s) => s.warnings);
  const scanResult = useAppStore((s) => s.scanResult);
  const scanStartTime = useAppStore((s) => s.scanStartTime);
  const diag = useAppStore((s) => s.diag);
  const overflowCount = useAppStore((s) => s.overflowCount);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [busyStart, setBusyStart] = useState(false);

  const refreshDrives = () => {
    lzr?.invoke('scan:enumerate-drives', true).then((d) => {
      if (Array.isArray(d)) useAppStore.getState().setDrives(d);
      else if (d?.error) useAppStore.getState().addToast(d.error, 'error', 8000);
    }).catch(() => {});
  };

  // première liste de disques + sélection par défaut
  useEffect(() => {
    lzr?.invoke('scan:enumerate-drives').then((d) => {
      const s = useAppStore.getState();
      if (Array.isArray(d)) {
        s.setDrives(d);
        if (!s.selectedDrive) {
          const first = d.find((x) => x.kind === 'volume') || d[0];
          if (first) s.selectDrive(first);
        }
      } else if (d?.error) s.addToast(d.error, 'error', 10000);
    }).catch(() => {});
  }, []);

  const isScanning = scanState === 'scanning' || scanState === 'stopping';

  const startScan = async () => {
    if (!selectedDrive || busyStart) return;
    setBusyStart(true);
    const s = useAppStore.getState();
    s.clearFiles(); s.clearWarnings(); s.setLayout(null); s.setScanResult(null); s.setSessionId(null);
    s.setScanState('scanning');
    s.setScanStartTime(Date.now());
    s.setProgress({ percent: 0, filesFound: 0, currentPath: '', speed: 0, bytesDone: 0, bytesTotal: 0 });
    try {
      const { carveCats, customSignatures, ...opts } = scanOptions;
      let custom;
      if (customSignatures && customSignatures.trim()) {
        try { custom = JSON.parse(customSignatures); } catch { s.setScanState('idle'); s.addToast('Signatures personnalisées : JSON invalide', 'error', 8000); setBusyStart(false); return; }
      }
      const allCats = Object.keys(CAT_EXTS);
      const carveTypes = carveCats.length && carveCats.length < allCats.length ? [...new Set(carveCats.flatMap((c) => CAT_EXTS[c]))] : undefined;
      const r = await lzr?.invoke('scan:start', {
        devicePath: selectedDrive.path,
        deviceLabel: selectedDrive.label,
        ...opts, carveTypes, customSignatures: custom,
      });
      if (r && r.started === false) {
        s.setScanState('error');
        s.addToast(r.error || t('scan.error'), 'error', 8000);
      } else if (r?.sessionId) s.setSessionId(r.sessionId);
    } catch (e) {
      s.setScanState('error');
      s.addToast(String(e?.message || e), 'error', 8000);
    }
    setBusyStart(false);
  };

  const stopScan = () => {
    useAppStore.getState().setScanState('stopping');
    lzr?.invoke('scan:stop');
  };

  const setMode = (deep) => setScanOptions({ deepScan: deep, enableCarving: deep });

  return (
    <div className="flex flex-col h-full">
      {diag && diag.admin === false && <AdminBanner />}
      {diag && diag.error && <EngineBanner message={diag.error} />}

      <div className="flex items-center gap-3 px-5 py-3 bg-bg-2 border-b border-surface-border flex-shrink-0 flex-wrap">
        <SourcePicker value={selectedDrive} onChange={selectDrive} disabled={isScanning} />
        <button onClick={refreshDrives} title={t('scan.refresh')} disabled={isScanning}
          className="p-2 rounded-lg border border-surface-border text-text-dim hover:text-text hover:border-primary/30 transition-colors disabled:opacity-40">
          <RefreshCw size={14} />
        </button>

        <div className="flex rounded-lg border border-surface-border overflow-hidden text-sm" role="group">
          {[[false, 'scan.mode.quick', 'scan.mode.quick.hint'], [true, 'scan.mode.deep', 'scan.mode.deep.hint']].map(([deep, label, hint]) => (
            <button key={label} title={t(hint)} disabled={isScanning} onClick={() => setMode(deep)}
              className={clsx('px-3 py-2 transition-colors', scanOptions.deepScan === deep ? 'bg-primary/20 text-primary' : 'text-text-dim hover:text-text')}>
              {t(label)}
            </button>
          ))}
        </div>

        <button onClick={() => setOptionsOpen((o) => !o)}
          className={clsx('flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm border transition-colors',
            optionsOpen ? 'border-primary/50 text-primary bg-primary/10' : 'border-surface-border text-text-dim hover:text-text hover:border-primary/30')}>
          <Settings2 size={14} />{t('scan.options')}
        </button>

        <div className="flex-1" />

        <motion.button
          whileTap={{ scale: 0.96 }}
          onClick={isScanning ? stopScan : startScan}
          disabled={(!selectedDrive && !isScanning) || scanState === 'stopping'}
          className={clsx('flex items-center gap-2 px-5 py-2 rounded-lg font-semibold text-sm transition-all duration-200 shadow-glow',
            isScanning ? 'bg-red-500/20 border border-red-500/40 text-red-400 hover:bg-red-500/30' : 'bg-primary border border-primary/60 text-white hover:bg-primary-hover',
            ((!selectedDrive && !isScanning) || scanState === 'stopping') && 'opacity-50 cursor-not-allowed shadow-none')}
        >
          {isScanning ? <><StopCircle size={16} /> {scanState === 'stopping' ? t('scan.stopping') : t('scan.stop')}</> : <><Play size={16} /> {t('scan.start')}</>}
        </motion.button>
      </div>

      <AnimatePresence>
        {optionsOpen && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-b border-surface-border bg-bg-2">
            <div className="flex flex-wrap gap-5 px-5 py-3">
              {[['scanNTFS', 'scan.opt.ntfs'], ['scanFAT', 'scan.opt.fat'], ['scanEXT4', 'scan.opt.ext'],
                ['enableCarving', 'scan.opt.carving'], ['carveAll', 'scan.opt.carveAll'], ['includeExisting', 'scan.opt.existing'], ['deepScan', 'scan.opt.deep']].map(([key, label]) => (
                <label key={key} className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={!!scanOptions[key]} disabled={isScanning}
                    onChange={(e) => setScanOptions({ [key]: e.target.checked })} className="accent-primary w-4 h-4 rounded" />
                  <span className="text-sm text-text-muted">{t(label)}</span>
                </label>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2 px-5 pb-3">
              <label className="flex items-center gap-2 cursor-pointer mr-3">
                <input type="checkbox" checked={!!scanOptions.carveText} disabled={isScanning}
                  onChange={(e) => setScanOptions({ carveText: e.target.checked })} className="accent-primary w-4 h-4 rounded" />
                <span className="text-sm text-text-muted">{t('scan.opt.carveText')}</span>
              </label>
              <span className="text-xs text-text-dim">{t('scan.opt.cats')} :</span>
              {Object.keys(CAT_EXTS).map((c) => {
                const on = scanOptions.carveCats.includes(c);
                return (
                  <button key={c} disabled={isScanning}
                    onClick={() => setScanOptions({ carveCats: on ? scanOptions.carveCats.filter((x) => x !== c) : [...scanOptions.carveCats, c] })}
                    className={clsx('px-2.5 py-1 rounded-lg text-xs border transition-colors', on ? 'bg-primary/20 border-primary/40 text-primary' : 'border-surface-border text-text-dim')}>
                    {CAT_LABEL[c]}
                  </button>
                );
              })}
            </div>
            <details className="px-5 pb-3">
              <summary className="text-xs text-text-dim cursor-pointer">{t('scan.opt.custom')}</summary>
              <textarea value={scanOptions.customSignatures} onChange={(e) => setScanOptions({ customSignatures: e.target.value })} rows={3} spellCheck={false}
                placeholder={'[{"ext":"xyz","header":"4C5A5258","footer":"454E44","maxMB":50}]'}
                className="mt-2 w-full bg-surface-2 border border-surface-border rounded-lg px-3 py-2 text-xs font-mono text-text" />
            </details>
          </motion.div>
        )}
      </AnimatePresence>

      {overflowCount > 0 && (
        <div className="px-5 py-2 bg-yellow-500/10 border-b border-yellow-500/20 text-xs text-yellow-300 flex items-start gap-2">
          <AlertTriangle size={13} className="mt-0.5 flex-shrink-0" />{t('scan.overflow', { max: MAX_ITEMS.toLocaleString(), n: overflowCount.toLocaleString() })}
        </div>
      )}

      {layout?.partitions?.some((p) => p.fs === 'bitlocker' || p.encrypted) && (
        <div className="flex items-center gap-3 px-5 py-2 bg-primary/10 border-b border-primary/20 text-sm">
          <ShieldAlert size={16} className="text-primary flex-shrink-0" />
          <span className="flex-1 text-text-muted">{t('scan.bitlocker')}</span>
          <button onClick={() => useAppStore.getState().setView('tools')} className="px-3 py-1 rounded-lg bg-primary/20 border border-primary/40 text-primary text-xs font-semibold">{t('scan.bitlocker.btn')}</button>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="px-5 py-2 bg-yellow-500/10 border-b border-yellow-500/20 flex flex-col gap-1">
          {warnings.map((w) => (
            <div key={w} className="flex items-start gap-2 text-xs text-yellow-300"><AlertTriangle size={13} className="mt-0.5 flex-shrink-0" />{w}</div>
          ))}
        </div>
      )}

      {layout?.partitions?.length > 0 && (
        <div className="flex items-center gap-2 px-5 py-1.5 bg-bg-2 border-b border-surface-border text-[11px] text-text-dim overflow-x-auto">
          <Layers size={12} className="flex-shrink-0" /><span className="flex-shrink-0">{t('scan.layout')} :</span>
          {layout.partitions.map((p, i) => (
            <span key={i} className={clsx('px-2 py-0.5 rounded bg-surface-2 font-mono whitespace-nowrap', p.source === 'signature' && 'text-primary border border-primary/30')}>
              {p.fs ? p.fs.toUpperCase() : '?'} · {formatBytes(p.size)}{p.desc ? ` · ${p.desc}` : ''}
            </span>
          ))}
        </div>
      )}

      {(isScanning || scanState === 'done' || scanState === 'stopped' || scanState === 'error') && (
        <div className="px-5 py-2 bg-bg-2 border-b border-surface-border flex-shrink-0">
          <ProgressBar
            percent={progress.percent || 0} filesFound={progress.filesFound || 0}
            state={scanState === 'stopping' ? 'scanning' : scanState}
            speed={progress.speed || 0} bytesDone={progress.bytesDone || 0} bytesTotal={progress.bytesTotal || 0}
            currentPath={scanState === 'error' ? (scanResult?.error || '') : progress.currentPath} startTime={scanStartTime}
            extra={scanResult?.badSectors > 0 ? <span className="text-orange-400">{scanResult.badSectors} {t('scan.badSectors')}</span> : null}
          />
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        <FileList />
        <PreviewPanel />
      </div>
      <RecoveryDialog />
    </div>
  );
}

function AdminBanner() {
  const t = useT();
  return (
    <div className="flex items-center gap-3 px-5 py-2.5 bg-red-500/10 border-b border-red-500/30 text-sm">
      <ShieldAlert size={18} className="text-accent flex-shrink-0" />
      <div className="flex-1">
        <span className="font-semibold text-accent">{t('banner.admin.title')}</span>
        <span className="text-text-muted ml-2">{t('banner.admin.text')}</span>
      </div>
      <button onClick={() => lzr?.invoke('app:relaunch-admin')}
        className="px-3 py-1.5 rounded-lg bg-red-500/20 border border-red-500/40 text-accent hover:bg-red-500/30 text-xs font-semibold">
        {t('banner.admin.btn')}
      </button>
    </div>
  );
}

function EngineBanner({ message }) {
  const t = useT();
  return (
    <div className="flex items-center gap-3 px-5 py-2.5 bg-red-500/10 border-b border-red-500/30 text-sm">
      <AlertTriangle size={18} className="text-accent flex-shrink-0" />
      <div className="flex-1"><span className="font-semibold text-accent">{t('banner.engine.title')}</span><span className="text-text-muted ml-2">{message}</span></div>
    </div>
  );
}

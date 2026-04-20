import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Play, StopCircle, HardDrive, ChevronDown, Settings2, RefreshCw, Usb } from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
import FileList        from './FileList';
import PreviewPanel    from './PreviewPanel';
import ProgressBar     from '../ui/ProgressBar';
import clsx            from 'clsx';

const lzr = window.lazarus;

export default function ScanView() {
  const {
    drives, selectedDrive, scanState, progress, scanOptions,
    setDrives, selectDrive, setScanState, setProgress,
    addFile, clearFiles, setScanOptions,
    license,
  } = useAppStore();

  const [driveOpen,   setDriveOpen]   = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [outputDir,   setOutputDir]   = useState('');

  // â”€â”€ Load drives â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  useEffect(() => {
    lzr?.invoke('scan:enumerate-drives')
       .then((d) => { setDrives(d || []); if (d?.length) selectDrive(d[0]); })
       .catch(() => {});
  }, []);

  // â”€â”€ Listen for scan events â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  useEffect(() => {
    const offFile = lzr?.on('scan:file-found', (f)   => addFile(f));
    const offProg = lzr?.on('scan:progress',   (p)   => setProgress(p));
    const offDone = lzr?.on('scan:done',       ()    => setScanState('done'));
    return () => { offFile?.(); offProg?.(); offDone?.(); };
  }, []);

  useEffect(() => {
    const off = lzr?.on('scan:drives-updated', (d) => { setDrives(d || []); });
    return () => off?.();
  }, []);

  const refreshDrives = () => {
    lzr?.invoke('scan:enumerate-drives').then((d) => { setDrives(d || []); }).catch(() => {});
  };

    const startScan = async () => {
    if (!selectedDrive) return;
    clearFiles();
    setScanState('scanning');
    setProgress({ percent: 0, filesFound: 0, filesRecoverable: 0 });

    const dir = outputDir || (await lzr?.invoke('dialog:openFolder').catch(() => null));
    await lzr?.invoke('scan:start', {
      devicePath:    selectedDrive.path,
      outputDir:     dir || '',
      ...scanOptions,
    }).catch((e) => { setScanState('error'); console.error(e); });
  };

  const stopScan = () => {
    // Note: stop is handled by native side via flag
    setScanState('idle');
  };

  const isScanning = scanState === 'scanning';

  return (
    <div className="flex flex-col h-full">
      {/* â”€â”€ Top Control Bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div className="flex items-center gap-3 px-5 py-3
                      bg-bg-2 border-b border-surface-border flex-shrink-0">
        
        {/* Drive selector */}
        <div className="relative">
          <button
            onClick={() => setDriveOpen((o) => !o)}
            className="flex items-center gap-2 bg-surface-2 border border-surface-border
                       rounded-lg px-3 py-2 text-sm hover:border-primary/50
                       transition-colors min-w-[220px]"
          >
            <HardDrive size={15} className="text-primary flex-shrink-0" />
            <span className="flex-1 text-left text-text truncate">
              {selectedDrive ? selectedDrive.label || selectedDrive.path : 'Select driveâ€¦'}
            </span>
            {selectedDrive && selectedDrive.interface && (
              <span className="px-1.5 py-0.5 text-xs rounded bg-surface-3 text-text-dim font-mono">
                {selectedDrive.interface}
              </span>
            )}
            {selectedDrive && (
              <span className="text-xs text-text-dim font-mono">
                {formatBytes(selectedDrive.totalSize)}
              </span>
            )}
            <ChevronDown size={13} className="text-text-dim" />
          </button>
          
          <AnimatePresence>
            {driveOpen && (
              <motion.div
                initial={{ opacity:0, y:-4 }}
                animate={{ opacity:1, y:0 }}
                exit={{ opacity:0, y:-4 }}
                className="absolute top-full left-0 mt-1 bg-surface-2 border border-surface-border
                           rounded-xl shadow-panel z-50 min-w-[260px] overflow-hidden"
              >
                {drives.length === 0 ? (
                  <div className="px-4 py-3 text-sm text-text-dim">No drives found</div>
                ) : drives.map((d, i) => (
                  <button
                    key={i}
                    onClick={() => { selectDrive(d); setDriveOpen(false); }}
                    className={clsx(
                      'w-full flex items-center gap-2 px-4 py-2.5 text-sm text-left',
                      'hover:bg-primary/10 transition-colors',
                      d.path === selectedDrive?.path && 'text-primary bg-primary/5'
                    )}
                  >
                    <HardDrive size={14} />
                    <div className="flex-1">
                      <div className="font-medium">{d.label || d.path}</div>
                      <div className="text-xs text-text-dim font-mono">{d.path}{d.interface ? ' · ' + d.interface : ''}</div>
                    </div>
                    <span className="text-xs text-text-dim">{formatBytes(d.totalSize)}</span>
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Refresh drives */}
        <button onClick={refreshDrives}
          title="Refresh drives"
          className="p-2 rounded-lg border border-surface-border text-text-dim hover:text-text hover:border-primary/30 transition-colors">
          <RefreshCw size={14} />
        </button>

        {/* Options toggle */}
        <button
          onClick={() => setOptionsOpen((o) => !o)}
          className={clsx(
            'flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm border transition-colors',
            optionsOpen
              ? 'border-primary/50 text-primary bg-primary/10'
              : 'border-surface-border text-text-dim hover:text-text hover:border-primary/30'
          )}
        >
          <Settings2 size={14} />
          Options
        </button>

        <div className="flex-1" />

        {/* Scan / Stop button */}
        <motion.button
          whileTap={{ scale: 0.96 }}
          onClick={isScanning ? stopScan : startScan}
          disabled={!selectedDrive && !isScanning}
          className={clsx(
            'flex items-center gap-2 px-5 py-2 rounded-lg font-semibold text-sm',
            'transition-all duration-200 shadow-glow',
            isScanning
              ? 'bg-red-500/20 border border-red-500/40 text-red-400 hover:bg-red-500/30'
              : 'bg-primary border border-primary/60 text-white hover:bg-primary-hover',
            !selectedDrive && !isScanning && 'opacity-40 cursor-not-allowed shadow-none'
          )}
        >
          {isScanning ? (
            <><StopCircle size={16} /> Stop Scan</>
          ) : (
            <><Play size={16} /> Start Scan</>
          )}
        </motion.button>
      </div>

      {/* â”€â”€ Options Panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <AnimatePresence>
        {optionsOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-b border-surface-border bg-bg-2"
          >
            <div className="flex flex-wrap gap-4 px-5 py-3">
              {[
                { key: 'scanNTFS',      label: 'NTFS' },
                { key: 'scanEXT4',      label: 'EXT4' },
                { key: 'scanAPFS',      label: 'APFS' },
                { key: 'enableCarving', label: 'File Carving' },
                { key: 'deepScan',      label: 'Deep Scan' },
              ].map(({ key, label }) => (
                <label key={key} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={scanOptions[key]}
                    onChange={(e) => setScanOptions({ [key]: e.target.checked })}
                    className="accent-primary w-4 h-4 rounded"
                  />
                  <span className="text-sm text-text-muted">{label}</span>
                </label>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* â”€â”€ Progress â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      {(isScanning || scanState === 'done') && (
        <div className="px-5 py-2 bg-bg-2 border-b border-surface-border flex-shrink-0">
          <ProgressBar
            percent={progress.percent}
            filesFound={progress.filesFound}
            done={scanState === 'done'}
          />
        </div>
      )}

      {/* â”€â”€ Main Content â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div className="flex flex-1 overflow-hidden">
        <FileList />
        <PreviewPanel />
      </div>
    </div>
  );
}

function formatBytes(n) {
  if (!n) return '';
  const gb = n / 1e9;
  if (gb >= 1) return gb.toFixed(1) + ' GB';
  const mb = n / 1e6;
  return mb.toFixed(0) + ' MB';
}

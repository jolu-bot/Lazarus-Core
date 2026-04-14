/**
 * LAZARUS CORE – useScanEvents hook
 * Centralises IPC event subscription for scan progress and file discovery.
 */
import { useEffect, useRef } from 'react';
import { useAppStore }       from '../stores/useAppStore';

const lzr = window.lazarus;

/**
 * Subscribes to all scan IPC channels and feeds data into the global store.
 * Mount this hook ONCE in a top-level component (e.g. ScanView).
 */
export function useScanEvents() {
  const {
    addFile,
    setProgress,
    setScanState,
    clearFiles,
  } = useAppStore();

  // Keep stable references to avoid stale closures
  const addFileRef     = useRef(addFile);
  const setProgressRef = useRef(setProgress);
  const setScanRef     = useRef(setScanState);

  useEffect(() => {
    addFileRef.current     = addFile;
    setProgressRef.current = setProgress;
    setScanRef.current     = setScanState;
  });

  useEffect(() => {
    const offFile = lzr?.on('scan:file-found', (file) => {
      addFileRef.current(file);
    });

    const offProg = lzr?.on('scan:progress', (prog) => {
      setProgressRef.current({
        percent:          prog.percent         ?? 0,
        filesFound:       prog.filesFound      ?? 0,
        filesRecoverable: prog.filesRecoverable ?? 0,
        currentPath:      prog.currentPath     ?? '',
      });
    });

    const offDone = lzr?.on('scan:done', () => {
      setScanRef.current('done');
    });

    return () => {
      offFile?.();
      offProg?.();
      offDone?.();
    };
  }, []);
}

/**
 * Triggers a scan with the given options and returns a promise
 * that resolves when the scan request has been dispatched.
 */
export async function startScan({ devicePath, outputDir, scanOptions }) {
  const store = useAppStore.getState();
  store.clearFiles();
  store.setScanState('scanning');
  store.setProgress({ percent: 0, filesFound: 0, filesRecoverable: 0, currentPath: '' });

  return lzr?.invoke('scan:start', {
    devicePath,
    outputDir: outputDir || '',
    ...scanOptions,
  });
}

/**
 * LAZARUS CORE – abonnement centralisé aux évènements du moteur.
 * À monter UNE seule fois au niveau de <App/> : si l'abonnement vivait dans une vue, changer d'onglet
 * pendant une analyse ferait perdre des fichiers.
 */
import { useEffect } from 'react';
import { useAppStore } from '../stores/useAppStore';
import { translate } from '../i18n';

export function useScanEvents() {
  useEffect(() => {
    const lzr = window.lazarus;
    if (!lzr) return undefined;
    const st = () => useAppStore.getState();
    const offs = [
      lzr.on('scan:files-batch', (batch) => st().addFiles(batch)),
      lzr.on('scan:file-found', (f) => st().addFiles([f])),
      lzr.on('scan:progress', (p) => st().setProgress(p)),
      lzr.on('scan:layout', (l) => st().setLayout(l)),
      lzr.on('scan:warning', (w) => st().addWarning(w?.message || String(w))),
      lzr.on('scan:done', (d) => {
        const s = st();
        s.setScanResult(d || null);
        s.setSessionId(d?.sessionId || s.sessionId);
        s.setProgress({ percent: 100, filesFound: d?.filesFound ?? s.progress.filesFound });
        if (d?.error) s.setScanState('error');
        else s.setScanState(d?.stopped ? 'stopped' : 'done');
        lzr.send('app:scan-done', { filesFound: d?.filesFound || 0, drive: s.selectedDrive?.label || s.selectedDrive?.path || '' });
      }),
      lzr.on('scan:drives-updated', (d) => st().setDrives(d)),
      lzr.on('scan:drive-connected', (d) => st().addToast(`${d.label} ${translate(st().language, 'toast.driveConnected')}`, 'success')),
      lzr.on('scan:drive-disconnected', (d) => st().addToast(`${d.label} ${translate(st().language, 'toast.driveDisconnected')}`, 'info')),
      lzr.on('recover:progress', (p) => st().setRecovery({ progress: p })),
      lzr.on('recover:file-done', (r) => {
        const cur = st().recovery;
        st().setRecovery({ files: [...(cur.files || []), r].slice(-500) });
      }),
    ];
    return () => offs.forEach((o) => o && o());
  }, []);
}

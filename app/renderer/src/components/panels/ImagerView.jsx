import React, { useEffect, useState } from 'react';
import { Copy, FolderOpen, Play, StopCircle, CheckCircle2, AlertTriangle, ShieldAlert } from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
import SourcePicker from '../ui/SourcePicker';
import ProgressBar from '../ui/ProgressBar';
import { formatBytes } from '../../utils/formatters';
import { useT } from '../../i18n';

const lzr = window.lazarus;

export default function ImagerView() {
  const t = useT();
  const drive = useAppStore((s) => s.selectedDrive);
  const selectDrive = useAppStore((s) => s.selectDrive);
  const addToast = useAppStore((s) => s.addToast);
  const [dest, setDest] = useState('');
  const [state, setState] = useState('idle');   // idle | running | done | error
  const [prog, setProg] = useState(null);
  const [result, setResult] = useState(null);
  const [warn, setWarn] = useState(null);

  useEffect(() => {
    const off = lzr?.on('image:progress', (p) => setProg(p));
    return () => off && off();
  }, []);

  const pickDest = async () => {
    const base = (drive?.label || 'disque').replace(/[^\w.-]+/g, '_');
    const p = await lzr?.invoke('dialog:saveFile', `${base}.img`);
    if (!p) return;
    setDest(p);
    const chk = await lzr?.invoke('scan:check-dest', drive?.path, p.replace(/[\\/][^\\/]*$/, ''));
    setWarn(chk && chk.safe === false ? chk : null);
  };

  const start = async () => {
    if (!drive || !dest || warn) return;
    setState('running'); setResult(null); setProg(null);
    const r = await lzr?.invoke('scan:image-disk', { device: drive.path, outputImage: dest, length: drive.totalSize || undefined });
    setResult(r);
    setState(r?.success ? 'done' : 'error');
    if (r?.success) addToast(t('clone.done'), 'success');
    else if (r?.message) addToast(r.message, r.stopped ? 'info' : 'error', 9000);
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-lg font-bold text-text mb-2 flex items-center gap-2"><Copy size={18} />{t('clone.title')}</h2>
      <p className="text-sm text-text-muted max-w-2xl mb-6">{t('clone.intro')}</p>
      <div className="max-w-2xl flex flex-col gap-5">
        <div>
          <label className="text-sm font-medium text-text block mb-1.5">{t('clone.source')}</label>
          <SourcePicker value={drive} onChange={selectDrive} includeShadows={false} allowImage={false} disabled={state === 'running'} />
        </div>
        <div>
          <label className="text-sm font-medium text-text block mb-1.5">{t('clone.dest')}</label>
          <div className="flex gap-2">
            <input readOnly value={dest} placeholder="…" className="flex-1 bg-surface-2 border border-surface-border rounded-lg px-3 py-2 text-sm text-text cursor-default" />
            <button onClick={pickDest} disabled={state === 'running'} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-surface-2 border border-surface-border text-text-dim hover:text-text text-sm">
              <FolderOpen size={14} />{t('clone.choose')}
            </button>
          </div>
          <p className="text-xs text-text-dim mt-1.5">{t('clone.resume')}</p>
        </div>

        {warn && (
          <div className="flex gap-3 p-4 rounded-xl border border-red-500/40 bg-red-500/10 text-red-200 text-sm">
            <ShieldAlert size={20} className="shrink-0" /><div>{t('recover.warnText')}</div>
          </div>
        )}

        <div className="flex gap-3">
          {state !== 'running' ? (
            <button onClick={start} disabled={!drive || !dest || !!warn}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-primary text-white font-semibold text-sm hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed">
              <Play size={16} />{t('clone.start')}
            </button>
          ) : (
            <button onClick={() => lzr?.invoke('scan:stop')} className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-red-500/20 border border-red-500/40 text-red-300 font-semibold text-sm">
              <StopCircle size={16} />{t('scan.stop')}
            </button>
          )}
        </div>

        {state === 'running' && prog && (
          <div className="bg-bg-2 border border-surface-border rounded-xl p-4">
            <ProgressBar percent={prog.percent || 0} filesFound={0} state="scanning" speed={prog.speed || 0} bytesDone={prog.bytesDone || 0}
              bytesTotal={prog.bytesTotal || 0} currentPath={prog.currentPath} extra={prog.badSectors ? <span className="text-orange-400">{prog.badSectors} {t('scan.badSectors')}</span> : null} />
          </div>
        )}

        {result && (
          <div className={`rounded-xl border p-4 text-sm ${result.success ? 'border-accent-green/30 bg-accent-green/10' : 'border-yellow-500/30 bg-yellow-500/10'}`}>
            <div className="flex items-center gap-2 font-semibold mb-2">
              {result.success ? <CheckCircle2 size={16} className="text-accent-green" /> : <AlertTriangle size={16} className="text-yellow-300" />}
              {result.success ? t('clone.done') : (result.message || 'Erreur')}
            </div>
            {result.bytes != null && <div className="text-text-muted">{formatBytes(result.bytes)} · {result.seconds} s · {result.badSectors || 0} {t('clone.bad')}</div>}
            {result.sha256 && <div className="text-xs font-mono text-text-dim mt-2 break-all">SHA-256 : {result.sha256}<br />MD5 : {result.md5}</div>}
            {result.imagePath && <button onClick={() => lzr?.invoke('shell:showItem', result.imagePath)} className="mt-3 text-xs text-primary hover:underline">{result.imagePath}</button>}
          </div>
        )}
      </div>
    </div>
  );
}

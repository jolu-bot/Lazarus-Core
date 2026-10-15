import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Download, FolderOpen, ShieldAlert, CheckCircle2, XCircle, AlertCircle, X, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { useAppStore, fileDb } from '../../stores/useAppStore';
import { formatBytes } from '../../utils/formatters';
import { useT } from '../../i18n';

const lzr = window.lazarus;

const INTEGRITY = {
  ok: ['OK', 'text-accent-green'], suspect: ['Suspect', 'text-yellow-400'], corrompu: ['Corrompu', 'text-red-400'], inconnu: ['—', 'text-text-dim'],
};

export default function RecoveryDialog() {
  const t = useT();
  const rec = useAppStore((s) => s.recovery);
  const setRecovery = useAppStore((s) => s.setRecovery);
  const resetRecovery = useAppStore((s) => s.resetRecovery);
  const sessionId = useAppStore((s) => s.sessionId);
  const drive = useAppStore((s) => s.selectedDrive);
  const addToast = useAppStore((s) => s.addToast);
  const setOutputDir = useAppStore((s) => s.setOutputDir);

  if (!rec.open) return null;
  const totalBytes = rec.ids.reduce((a, id) => a + (fileDb.byId.get(id)?.size || 0), 0);
  const device = (fileDb.byId.get(rec.ids[0]) || {}).device || drive?.path;

  const chooseFolder = async () => {
    const dir = await lzr?.invoke('dialog:openFolder');
    if (!dir) return;
    setRecovery({ phase: 'checking', dest: dir, blocked: null });
    const chk = await lzr?.invoke('scan:check-dest', device, dir);
    if (chk && chk.safe === false) {
      setRecovery({ phase: 'choose', dest: dir, blocked: chk });
      return;
    }
    if (chk && chk.freeBytes && chk.freeBytes < totalBytes) {
      setRecovery({ phase: 'choose', dest: dir, blocked: { reason: `Espace libre insuffisant : ${formatBytes(chk.freeBytes)} disponibles pour ${formatBytes(totalBytes)} à récupérer.`, sameDisk: false, soft: true } });
      return;
    }
    setOutputDir(dir);
    setRecovery({ phase: 'ready', dest: dir, blocked: null });
  };

  const start = async () => {
    setRecovery({ phase: 'running', files: [], progress: null, result: null });
    const r = await lzr?.invoke('scan:recover-batch', {
      sessionId, ids: rec.ids, destination: rec.dest, structure: rec.structure ? 'tree' : 'flat', verify: rec.verify, device,
    });
    setRecovery({ phase: 'done', result: r || { success: false, error: 'Aucune réponse du moteur' } });
    if (r?.success) addToast(`${r.recovered} ${t('files.found')} → ${rec.dest}`, 'success');
  };

  const cancel = () => { lzr?.invoke('scan:stop'); };
  const p = rec.progress;
  const pct = p && p.bytesTotal ? Math.min(100, (p.bytesDone / p.bytesTotal) * 100) : 0;
  const result = rec.result;

  return (
    <AnimatePresence>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        className="fixed inset-0 z-9000 bg-black/70 flex items-center justify-center p-6">
        <motion.div initial={{ scale: 0.96, y: 10 }} animate={{ scale: 1, y: 0 }}
          className="w-[720px] max-w-full max-h-[85vh] flex flex-col bg-bg-2 border border-surface-border rounded-2xl shadow-panel overflow-hidden">
          <div className="flex items-center gap-3 px-6 py-4 border-b border-surface-border">
            <Download size={18} className="text-primary" />
            <h3 className="text-base font-semibold text-text flex-1">{t('recover.title')}</h3>
            {rec.phase !== 'running' && (
              <button onClick={resetRecovery} className="text-text-dim hover:text-text"><X size={16} /></button>
            )}
          </div>

          <div className="p-6 overflow-y-auto flex flex-col gap-4">
            <div className="text-sm text-text-muted">
              <b className="text-text">{rec.ids.length.toLocaleString()}</b> {t('files.found')} · <b className="text-text">{formatBytes(totalBytes)}</b>
            </div>

            {(rec.phase === 'choose' || rec.phase === 'checking' || rec.phase === 'ready') && (
              <>
                <button onClick={chooseFolder} disabled={rec.phase === 'checking'}
                  className="flex items-center gap-2 px-4 py-3 rounded-xl border border-dashed border-primary/50 text-primary hover:bg-primary/10 transition-colors text-sm">
                  {rec.phase === 'checking' ? <Loader2 size={16} className="animate-spin" /> : <FolderOpen size={16} />}
                  {rec.dest ? rec.dest : t('recover.choose')}
                </button>

                {rec.blocked && (
                  <div className={clsx('flex gap-3 p-4 rounded-xl border text-sm', rec.blocked.soft ? 'border-yellow-500/30 bg-yellow-500/10 text-yellow-200' : 'border-red-500/40 bg-red-500/10 text-red-200')}>
                    <ShieldAlert size={20} className="shrink-0 mt-0.5" />
                    <div>
                      {!rec.blocked.soft && <div className="font-semibold mb-1">{t('recover.warnTitle')}</div>}
                      <div>{rec.blocked.soft ? rec.blocked.reason : t('recover.warnText')}</div>
                    </div>
                  </div>
                )}

                <label className="flex items-center gap-2 text-sm text-text-muted cursor-pointer">
                  <input type="checkbox" checked={rec.structure} onChange={(e) => setRecovery({ structure: e.target.checked })} className="accent-primary" />
                  {t('recover.structure')}
                </label>
                <label className="flex items-center gap-2 text-sm text-text-muted cursor-pointer">
                  <input type="checkbox" checked={rec.verify} onChange={(e) => setRecovery({ verify: e.target.checked })} className="accent-primary" />
                  {t('recover.verify')}
                </label>

                <div className="flex justify-end gap-2 pt-2">
                  <button onClick={resetRecovery} className="px-4 py-2 rounded-lg border border-surface-border text-text-dim hover:text-text text-sm">{t('recover.cancel')}</button>
                  <button onClick={start} disabled={rec.phase !== 'ready'}
                    className="px-5 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed">
                    {t('recover.start')}
                  </button>
                </div>
              </>
            )}

            {rec.phase === 'running' && (
              <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2 text-sm text-text"><Loader2 size={15} className="animate-spin text-primary" />{t('recover.running')}</div>
                <div className="h-2 rounded-full bg-surface-2 overflow-hidden"><div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} /></div>
                {p && (
                  <div className="text-xs text-text-dim font-mono flex flex-wrap gap-x-4 gap-y-1">
                    <span>{p.index + 1}/{p.total}</span>
                    <span className="truncate max-w-[360px]">{p.name}</span>
                    <span>{formatBytes(p.bytesDone)} / {formatBytes(p.bytesTotal)}</span>
                    <span className="text-primary">{formatBytes(p.speed || 0)}/s</span>
                  </div>
                )}
                <ResultList files={rec.files} />
                <div className="flex justify-end"><button onClick={cancel} className="px-4 py-2 rounded-lg border border-red-500/40 text-red-300 hover:bg-red-500/10 text-sm">{t('scan.stop')}</button></div>
              </div>
            )}

            {rec.phase === 'done' && result && (
              <div className="flex flex-col gap-3">
                {result.blocked ? (
                  <div className="flex gap-3 p-4 rounded-xl border border-red-500/40 bg-red-500/10 text-red-200 text-sm"><ShieldAlert size={20} />{result.error}</div>
                ) : (
                  <div className={clsx('flex items-center gap-2 text-sm font-semibold', result.success ? 'text-accent-green' : 'text-yellow-300')}>
                    {result.success ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                    {t('recover.done')} — {result.recovered ?? 0} {t('recover.ok')}, {result.failed ?? 0} {t('recover.fail')}
                    {result.seconds != null && <span className="text-text-dim font-normal">· {result.seconds} s</span>}
                  </div>
                )}
                {result.error && !result.blocked && <div className="text-xs text-red-300">{result.error}</div>}
                <ResultList files={result.results || rec.files} />
                <div className="flex justify-end gap-2 pt-2">
                  {result.destination && (
                    <button onClick={() => lzr?.invoke('shell:openPath', result.destination)}
                      className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary-hover">
                      <FolderOpen size={14} />{t('recover.open')}
                    </button>
                  )}
                  <button onClick={resetRecovery} className="px-4 py-2 rounded-lg border border-surface-border text-text-dim hover:text-text text-sm">{t('recover.close')}</button>
                </div>
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

function ResultList({ files }) {
  const t = useT();
  if (!files || !files.length) return null;
  const shown = files.slice(-200);
  return (
    <div className="border border-surface-border rounded-xl overflow-hidden">
      <div className="max-h-[260px] overflow-y-auto divide-y divide-surface-border/50">
        {shown.map((f, i) => {
          const [lbl, cls] = INTEGRITY[f.integrity] || INTEGRITY.inconnu;
          return (
            <div key={(f.id ?? i) + ':' + i} className="flex items-center gap-2 px-3 py-1.5 text-xs">
              {f.success ? <CheckCircle2 size={13} className="text-accent-green shrink-0" /> : <XCircle size={13} className="text-red-400 shrink-0" />}
              <span className="flex-1 truncate text-text" title={f.outputPath || f.error}>{f.name}</span>
              {f.success ? <span className={clsx('font-mono', cls)} title={t('recover.integrity')}>{lbl}</span> : <span className="text-red-300 truncate max-w-[200px]">{f.error}</span>}
              {f.sha256 && <span className="font-mono text-text-dim hidden md:inline" title={f.sha256}>{f.sha256.slice(0, 10)}…</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

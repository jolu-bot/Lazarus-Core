import React, { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Wand2, X, Loader2, CheckCircle2, AlertTriangle, FolderOpen, FileSearch, Sparkles, ImagePlus, ExternalLink } from 'lucide-react';
import clsx from 'clsx';
import { useAppStore } from '../../stores/useAppStore';
import { formatBytes } from '../../utils/formatters';
import { useT } from '../../i18n';

const lzr = window.lazarus;
const IMG_FORMATS = ['jpeg', 'png', 'bmp', 'gif'];

/** Assistant de réparation : diagnostic → options → réparation → comparaison avant/après. */
export default function RepairDialog({ file, originalSrc, onClose }) {
  const t = useT();
  const outputDir = useAppStore((s) => s.outputDir);
  const setOutputDir = useAppStore((s) => s.setOutputDir);
  const setRepairResult = useAppStore((s) => s.setRepairResult);
  const addToast = useAppStore((s) => s.addToast);
  const [phase, setPhase] = useState(outputDir || file.outputPath ? 'diagnosing' : 'dest');   // dest | diagnosing | ready | repairing | done | error
  const [dest, setDest] = useState(outputDir || '');   // fichier déjà présent sur disque (outputPath) : aucun dossier à choisir
  const [diag, setDiag] = useState(null);
  const [error, setError] = useState('');
  const [enhance, setEnhance] = useState(false);
  const [reference, setReference] = useState('');
  const [result, setResult] = useState(null);
  const started = useRef(false);

  const isImage = diag && IMG_FORMATS.includes(diag.format);

  const diagnose = async (dir) => {
    setPhase('diagnosing'); setError('');
    const d = await lzr?.invoke('scan:diagnose-file', { file, outputDir: dir }).catch((e) => ({ success: false, message: String(e?.message || e) }));
    if (!d?.success) { setError(d?.message || t('repair.err.diag')); setPhase('error'); return; }
    setDiag(d); setPhase('ready');
  };

  useEffect(() => {
    if ((outputDir || file.outputPath) && !started.current) { started.current = true; diagnose(outputDir || ''); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const chooseFolder = async () => {
    const dir = await lzr?.invoke('dialog:openFolder');
    if (!dir) return;
    const chk = await lzr?.invoke('scan:check-dest', file.device, dir).catch(() => null);
    if (chk && chk.safe === false) { setError(t('recover.warnText')); return; }
    setOutputDir(dir); setDest(dir); started.current = true; diagnose(dir);
  };

  const pickReference = async () => {
    const f = await lzr?.invoke('dialog:openFile', { filters: [{ name: 'JPEG', extensions: ['jpg', 'jpeg'] }, { name: '*', extensions: ['*'] }] });
    if (f) setReference(f);
  };

  const run = async () => {
    setPhase('repairing'); setError('');
    const r = await lzr?.invoke('scan:repair-file', { file, outputDir: dest, sourcePath: diag?.sourcePath, reference, enhance })
      .catch((e) => ({ success: false, message: String(e?.message || e) }));
    if (r?.success) { setResult(r); setRepairResult(file.id, r); setPhase('done'); addToast(t('repair.done'), 'success', 5000); }
    else { setError(r?.message || t('repair.err.fail')); setPhase('ready'); }
  };

  const issues = diag?.issues || [];
  const afterSrc = result?.preview_b64 ? `data:${result.previewMime || 'image/jpeg'};base64,${result.preview_b64}` : null;

  return (
    <div className="fixed inset-0 z-9000 bg-black/70 flex items-center justify-center p-6" role="dialog" aria-modal="true" aria-label={t('repair.title')}>
      <motion.div initial={{ scale: 0.96, y: 10 }} animate={{ scale: 1, y: 0 }}
        className="w-[780px] max-w-full max-h-[90vh] flex flex-col bg-bg-2 border border-surface-border rounded-2xl shadow-panel overflow-hidden">
        <div className="flex items-center gap-3 px-6 py-4 border-b border-surface-border">
          <Wand2 size={18} className="text-primary" />
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-semibold text-text">{t('repair.title')}</h3>
            <p className="text-xs text-text-dim truncate" title={file.name}>{file.name}{file.size ? ` · ${formatBytes(file.size)}` : ''}</p>
          </div>
          {phase !== 'repairing' && <button onClick={onClose} className="text-text-dim hover:text-text" aria-label="close"><X size={16} /></button>}
        </div>

        <div className="p-6 overflow-y-auto flex flex-col gap-4 text-sm">
          {phase === 'dest' && (
            <>
              <p className="text-text-muted">{t('repair.dest.hint')}</p>
              <button onClick={chooseFolder} className="self-start flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary-hover">
                <FolderOpen size={14} />{t('recover.choose')}
              </button>
              {error && <p className="text-xs text-red-400">{error}</p>}
            </>
          )}

          {phase === 'diagnosing' && (
            <div className="flex items-center gap-3 text-text-muted"><Loader2 size={18} className="animate-spin text-primary" />{t('repair.diagnosing')}</div>
          )}

          {phase === 'error' && (
            <div className="flex items-start gap-2 text-red-400"><AlertTriangle size={16} className="mt-0.5 shrink-0" /><span>{error}</span></div>
          )}

          {(phase === 'ready' || phase === 'repairing') && diag && (
            <>
              <div className="rounded-xl border border-surface-border bg-surface-2 p-4">
                <div className="flex items-center gap-2 text-xs text-text-dim mb-2">
                  <FileSearch size={13} className="text-primary" />{t('repair.diag')} · <span className="font-mono uppercase">{diag.format}</span>
                </div>
                {issues.length === 0 ? (
                  <p className="flex items-center gap-2 text-accent-green"><CheckCircle2 size={15} />{t('repair.noissue')}</p>
                ) : (
                  <ul className="flex flex-col gap-1.5">
                    {issues.map((i, k) => <li key={k} className="flex items-start gap-2 text-orange-300"><AlertTriangle size={13} className="mt-0.5 shrink-0" />{i}</li>)}
                  </ul>
                )}
                {diag.canSalvageText && <p className="text-xs text-text-dim mt-3">{t('repair.salvage')}</p>}
              </div>

              {isImage && (
                <div className="flex flex-col gap-3">
                  <label className="flex items-start gap-3 cursor-pointer">
                    <input type="checkbox" checked={enhance} onChange={(e) => setEnhance(e.target.checked)} className="mt-1 accent-purple-500" />
                    <span><span className="text-text font-medium flex items-center gap-1.5"><Sparkles size={13} className="text-purple-400" />{t('repair.enhance')}</span>
                      <span className="block text-xs text-text-dim">{t('repair.enhance.hint')}</span></span>
                  </label>
                  {diag.format === 'jpeg' && (
                    <div>
                      <div className="flex items-center gap-2">
                        <button onClick={pickReference} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-surface-2 border border-surface-border hover:bg-surface-border text-text-muted">
                          <ImagePlus size={13} />{t('repair.reference')}
                        </button>
                        {reference && <span className="text-xs font-mono text-text-dim truncate" title={reference}>{reference.split(/[\\/]/).pop()}</span>}
                        {reference && <button onClick={() => setReference('')} className="text-text-dim hover:text-text"><X size={12} /></button>}
                      </div>
                      <p className="text-xs text-text-dim mt-1">{t('repair.reference.hint')}</p>
                    </div>
                  )}
                </div>
              )}
              {error && <p className="text-xs text-red-400 flex items-start gap-1.5"><AlertTriangle size={13} className="mt-0.5 shrink-0" />{error}</p>}
            </>
          )}

          {phase === 'done' && result && (
            <>
              <div className="flex items-center gap-2 text-accent-green font-medium"><CheckCircle2 size={16} />{t('repair.done')}</div>
              {afterSrc && <CompareSlider before={originalSrc} after={afterSrc} t={t} />}
              {typeof result.completeness === 'number' && (
                <div>
                  <div className="flex justify-between text-xs text-text-dim mb-1"><span>{t('repair.completeness')}</span><span className="font-mono">{result.completeness} %</span></div>
                  <div className="h-1.5 rounded-full bg-surface-border overflow-hidden"><div className="h-full rounded-full bg-primary" style={{ width: `${result.completeness}%` }} /></div>
                  {result.completeness < 100 && <p className="text-xs text-orange-300 mt-2 flex items-start gap-1.5"><AlertTriangle size={12} className="mt-0.5 shrink-0" />{t('repair.estimate')}</p>}
                </div>
              )}
              <ul className="flex flex-col gap-1">
                {(result.operations || []).map((o, k) => <li key={k} className="flex items-start gap-2 text-text-muted text-xs"><CheckCircle2 size={12} className="mt-0.5 text-accent-green shrink-0" />{o}</li>)}
              </ul>
              <div className="flex flex-wrap gap-2">
                {(result.outputs || [result.outputPath]).filter(Boolean).map((p) => (
                  <button key={p} onClick={() => lzr?.invoke('shell:openPath', p)} title={p}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-surface-2 border border-surface-border hover:bg-surface-border text-text-muted">
                    <ExternalLink size={12} />{p.split(/[\\/]/).pop()}
                  </button>
                ))}
                <button onClick={() => lzr?.invoke('shell:showItem', result.outputPath)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-surface-2 border border-surface-border hover:bg-surface-border text-text-muted">
                  <FolderOpen size={12} />{t('repair.show')}
                </button>
              </div>
            </>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-surface-border">
          <span className="text-[11px] text-text-dim">{t('repair.safe')}</span>
          <div className="flex gap-2">
            <button onClick={onClose} disabled={phase === 'repairing'} className="px-4 py-2 rounded-lg text-sm text-text-muted hover:text-text disabled:opacity-40">{phase === 'done' ? t('repair.close') : t('repair.cancel')}</button>
            {(phase === 'ready' || phase === 'repairing') && (
              <button onClick={run} disabled={phase === 'repairing'}
                className={clsx('flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white bg-primary hover:bg-primary-hover', phase === 'repairing' && 'opacity-60 cursor-wait')}>
                {phase === 'repairing' ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}{phase === 'repairing' ? t('repair.running') : t('repair.start')}
              </button>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}

/** Curseur avant / après. */
function CompareSlider({ before, after, t }) {
  const [pos, setPos] = useState(50);
  if (!before) return <img src={after} alt="" className="max-h-72 mx-auto rounded-lg border border-surface-border" />;
  return (
    <div>
      <div className="relative mx-auto w-full max-w-[640px] rounded-lg overflow-hidden border border-surface-border bg-black select-none">
        <img src={after} alt="après" className="block w-full h-auto" draggable={false} />
        <img src={before} alt="avant" className="absolute inset-0 w-full h-full object-fill" style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }} draggable={false} />
        <div className="absolute top-0 bottom-0 w-0.5 bg-white/80" style={{ left: `${pos}%` }} />
        <span className="absolute top-2 left-2 text-[10px] px-1.5 py-0.5 rounded-sm bg-black/60 text-white">{t('repair.before')}</span>
        <span className="absolute top-2 right-2 text-[10px] px-1.5 py-0.5 rounded-sm bg-black/60 text-white">{t('repair.after')}</span>
      </div>
      <input type="range" min={0} max={100} value={pos} onChange={(e) => setPos(+e.target.value)} className="w-full mt-2 accent-purple-500" aria-label="comparaison avant/après" />
    </div>
  );
}

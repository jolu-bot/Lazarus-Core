import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Download, Wand2, ZoomIn, ZoomOut, RotateCcw, Image as ImageIcon, Film, FileText, Music, HardDrive, Sparkles,
  AlertCircle, CheckCircle2, ShieldCheck, Wrench, RefreshCcw, AlertTriangle, Activity, Archive, FolderOpen,
} from 'lucide-react';
import clsx from 'clsx';
import { useAppStore } from '../../stores/useAppStore';
import { formatBytes } from '../../utils/formatters';
import { useT } from '../../i18n';

const lzr = window.lazarus;
const hColor = (s) => (s >= 85 ? '#22c55e' : s >= 70 ? '#eab308' : s >= 50 ? '#f97316' : '#ef4444');
const MIME = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', gif: 'image/gif', bmp: 'image/bmp', webp: 'image/webp',
  mp3: 'audio/mpeg', wav: 'audio/wav', ogg: 'audio/ogg', flac: 'audio/flac', m4a: 'audio/mp4',
  mp4: 'video/mp4', webm: 'video/webm', mov: 'video/mp4', mkv: 'video/webm' };

function b64ToBlobUrl(b64, mime) {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return URL.createObjectURL(new Blob([arr], { type: mime }));
}

export default function PreviewPanel() {
  const t = useT();
  const file = useAppStore((s) => s.selectedFile);
  const aiAvailable = useAppStore((s) => s.aiAvailable);
  const repairResults = useAppStore((s) => s.repairResults);
  const setRepairResult = useAppStore((s) => s.setRepairResult);
  const addToast = useAppStore((s) => s.addToast);
  const outputDir = useAppStore((s) => s.outputDir);
  const setRecovery = useAppStore((s) => s.setRecovery);
  const [zoom, setZoom] = useState(1);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [mediaUrl, setMediaUrl] = useState(null);
  const [repairing, setRepairing] = useState(false);
  const token = useRef(0);

  const repair = file ? repairResults[file.id] : null;

  useEffect(() => {
    setZoom(1); setPreview(null);
    setMediaUrl((old) => { if (old) URL.revokeObjectURL(old); return null; });
    if (!file) return undefined;
    const my = ++token.current;
    setLoading(true);
    const max = file.type === 1 ? 24 * 1024 * 1024 : file.type === 2 || file.type === 3 ? 24 * 1024 * 1024 : 96 * 1024;
    const timer = setTimeout(() => {
      lzr?.invoke('scan:preview-record', file, Math.min(max, Math.max(65536, file.size || 65536))).then((r) => {
        if (my !== token.current) return;
        setPreview(r || null);
        const ext = (file.extension || '').toLowerCase();
        if (r?.success && r.complete && MIME[ext] && (file.type === 2 || file.type === 3)) setMediaUrl(b64ToBlobUrl(r.head_b64, MIME[ext]));
      }).catch(() => {}).finally(() => { if (my === token.current) setLoading(false); });
    }, 120);   // anti-rebond : parcourir la liste au clavier ne déclenche pas une lecture par ligne
    return () => clearTimeout(timer);
  }, [file?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const recoverOne = () => {
    if (!file) return;
    setRecovery({ open: true, phase: 'choose', ids: [file.id], files: [], result: null, progress: null, blocked: null, dest: outputDir || '' });
  };

  const doRepair = async (mode) => {
    if (!file) return;
    setRepairing(true);
    let dir = outputDir;
    if (!dir) dir = await lzr?.invoke('dialog:openFolder').catch(() => null);
    if (!dir) { setRepairing(false); return; }
    const chk = await lzr?.invoke('scan:check-dest', file.device, dir);
    if (chk && chk.safe === false) {
      setRepairing(false);
      addToast(t('recover.warnText'), 'error', 9000);
      return;
    }
    const r = await lzr?.invoke('scan:repair-file', { file, outputDir: dir, mode });
    setRepairing(false);
    if (r?.success) {
      setRepairResult(file.id, r);
      addToast(r.notes || (r.changed === false ? 'Aucune correction nécessaire' : 'Réparation terminée'), 'success', 6000);
    } else addToast(r?.message || 'Réparation impossible', 'error', 8000);
  };

  if (!file) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-bg gap-4 text-text-dim">
        <div className="w-20 h-20 rounded-3xl bg-surface-2 flex items-center justify-center"><HardDrive size={36} /></div>
        <div className="text-center"><p className="text-sm font-medium text-text-muted">{t('preview.none')}</p><p className="text-xs mt-1">{t('preview.none.hint')}</p></div>
      </div>
    );
  }

  const health = repair?.health || file.health || {};
  const score = health.score ?? Math.round((file.confidence || 0) * 100);
  const rm = health.repairMode ?? 0;
  const repaired = !!repair?.repaired;

  return (
    <div className="flex flex-col flex-1 min-w-0 bg-bg overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3 border-b border-surface-border bg-bg-2 flex-shrink-0">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-text truncate" title={file.path}>{file.name}</h3>
          <div className="flex items-center gap-2 text-xs text-text-dim mt-0.5">
            <span>{formatBytes(file.size)}</span><span>·</span><span className="font-mono">.{file.extension || '?'}</span>
            <span>·</span><span className="font-mono" style={{ color: hColor(score) }}>{score} %</span>
            {file.mtime ? <><span>·</span><span>{new Date(file.mtime * 1000).toLocaleDateString()}</span></> : null}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {file.type === 1 && (
            <>
              <IconBtn onClick={() => setZoom((z) => Math.min(z + 0.25, 4))} title="+"><ZoomIn size={15} /></IconBtn>
              <IconBtn onClick={() => setZoom((z) => Math.max(z - 0.25, 0.25))} title="−"><ZoomOut size={15} /></IconBtn>
              <IconBtn onClick={() => setZoom(1)} title="1:1"><RotateCcw size={14} /></IconBtn>
            </>
          )}
          {repair?.outputPath && <IconBtn onClick={() => lzr?.invoke('shell:showItem', repair.outputPath)} title="Afficher"><FolderOpen size={15} /></IconBtn>}
          <button onClick={recoverOne}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-primary text-white hover:bg-primary-hover shadow-glow-sm transition-all">
            <Download size={13} />{t('preview.recover')}
          </button>
        </div>
      </div>

      <HealthPanel health={health} score={score} rm={rm} repaired={repaired} onRepair={doRepair} busy={repairing} aiAvailable={aiAvailable} file={file} />

      <AnimatePresence>
        {repair && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            className={clsx('flex items-center gap-2 px-4 py-1.5 text-xs flex-shrink-0 border-b',
              repair.success ? 'bg-accent-green/10 border-accent-green/20 text-accent-green' : 'bg-accent/10 border-accent/20 text-accent')}>
            {repair.success ? <CheckCircle2 size={13} /> : <AlertCircle size={13} />}
            <span className="truncate">{repair.notes || repair.message}</span>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex-1 overflow-auto flex items-center justify-center bg-[#080810] p-4">
        <PreviewBody file={file} preview={preview} loading={loading} zoom={zoom} mediaUrl={mediaUrl} repairedB64={repair?.image_b64} />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-0.5 px-4 py-2 border-t border-surface-border bg-bg-2 flex-shrink-0 text-[11px] text-text-dim font-mono">
        <span>ID {file.id}</span>
        <span>{file.source?.toUpperCase()}{file.mft_ref != null && file.source === 'ntfs' ? ` · MFT ${file.mft_ref}` : ''}{file.inode ? ` · inode ${file.inode}` : ''}</span>
        <span>{t('status.' + (file.status ?? 0))}</span>
        {file.fragments > 1 && <span>{file.fragments} {t('preview.fragments')}</span>}
        {file.deleted_at ? <span>suppr. {new Date(file.deleted_at * 1000).toLocaleString()}</span> : null}
        {file.compressed && <span className="text-yellow-400">NTFS compressé</span>}
        {file.encrypted && <span className="text-red-400">EFS chiffré</span>}
        {file.path && <span className="truncate max-w-full" title={file.path}>{file.path}</span>}
      </div>
    </div>
  );
}

function PreviewBody({ file, preview, loading, zoom, mediaUrl, repairedB64 }) {
  const t = useT();
  if (loading && !preview) {
    return <div className="flex flex-col items-center gap-3 text-text-dim"><Sparkles size={30} className="animate-spin text-primary opacity-60" /><p className="text-xs">{t('preview.loading')}</p></div>;
  }
  if (!preview?.success) {
    return <Placeholder file={file} message={preview?.message || t('preview.unavailable')} />;
  }
  const ext = (file.extension || '').toLowerCase();
  if (file.type === 1 && MIME[ext]) {
    const src = repairedB64 ? `data:image/jpeg;base64,${repairedB64}` : `data:${MIME[ext]};base64,${preview.head_b64}`;
    return <ImageView src={src} zoom={zoom} fallback={<HexView preview={preview} />} />;
  }
  if (file.type === 2 && mediaUrl) return <video src={mediaUrl} controls className="max-w-full max-h-full rounded-lg shadow-panel" />;
  if (file.type === 3 && mediaUrl) return <div className="flex flex-col items-center gap-4"><Music size={64} className="text-accent-green opacity-60" /><audio src={mediaUrl} controls className="w-80" /></div>;
  if (preview.kind === 'text') {
    const bin = atob(preview.head_b64);
    let txt = '';
    try { txt = decodeURIComponent(escape(bin)); } catch { txt = bin; }
    return <pre className="w-full h-full overflow-auto text-xs font-mono text-text-muted p-4 whitespace-pre-wrap break-words select-text">{txt}</pre>;
  }
  return <HexView preview={preview} />;
}

function ImageView({ src, zoom, fallback }) {
  const [err, setErr] = useState(false);
  useEffect(() => setErr(false), [src]);
  if (err) return fallback;
  return <motion.img src={src} alt="aperçu" onError={() => setErr(true)} initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }}
    style={{ zoom }} className="max-w-full max-h-full object-contain rounded-lg shadow-panel" />;
}

function HexView({ preview }) {
  const t = useT();
  const lines = useMemo(() => {
    const bin = atob(preview.head_b64);
    const out = [];
    for (let i = 0; i < Math.min(bin.length, 2048); i += 16) {
      let hex = ''; let asc = '';
      for (let k = 0; k < 16 && i + k < bin.length; k++) {
        const c = bin.charCodeAt(i + k);
        hex += c.toString(16).padStart(2, '0') + ' ';
        asc += c >= 32 && c < 127 ? bin[i + k] : '.';
      }
      out.push(`${i.toString(16).padStart(8, '0')}  ${hex.padEnd(48, ' ')} |${asc}|`);
    }
    return out;
  }, [preview.head_b64]);
  return (
    <div className="flex flex-col w-full h-full overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-1.5 border-b border-surface-border bg-surface-2 text-xs text-text-dim flex-shrink-0">
        <HardDrive size={11} /><span>{t('preview.hex')}</span><span>·</span>
        <span className="font-mono">{formatBytes(preview.bytes)} / {formatBytes(preview.size)}</span>
      </div>
      <pre className="flex-1 overflow-auto text-[10px] font-mono text-green-400/80 p-4 leading-relaxed whitespace-pre bg-[#050508] select-text">{lines.join('\n')}</pre>
    </div>
  );
}

function Placeholder({ file, message }) {
  const Icon = file.type === 1 ? ImageIcon : file.type === 2 ? Film : file.type === 3 ? Music : file.type === 4 ? FileText : file.type === 5 ? Archive : HardDrive;
  return (
    <div className="flex flex-col items-center gap-4 text-text-dim">
      <Icon size={64} className="opacity-30" />
      <div className="text-center"><p className="text-sm font-medium text-text-muted">{file.name}</p><p className="text-xs mt-1">{formatBytes(file.size)} · .{file.extension || '?'}</p>
        <p className="text-xs text-accent/70 mt-1">{message}</p></div>
    </div>
  );
}

function HealthPanel({ health, score, rm, repaired, onRepair, busy, aiAvailable, file }) {
  const t = useT();
  const [open, setOpen] = useState(true);
  const rmLabel = [t('preview.excellent'), t('preview.repair'), t('preview.repair'), t('preview.rebuild')][rm] || '';
  const rmColor = rm === 0 ? 'text-accent-green' : rm === 1 ? 'text-yellow-400' : rm === 2 ? 'text-orange-400' : 'text-red-400';
  const RmIcon = rm === 0 ? ShieldCheck : rm === 1 ? Wrench : rm === 2 ? AlertTriangle : RefreshCcw;
  const ow = file.overwritten_pct;
  return (
    <div className="flex-shrink-0 border-b border-surface-border bg-bg-2">
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center gap-2 px-4 py-2 text-xs font-medium text-text-dim hover:text-text transition-colors">
        <Activity size={12} className="text-primary" /><span>{t('preview.health')}</span>
        <div className="ml-auto flex items-center gap-2">
          <span style={{ color: hColor(score) }} className="font-mono font-bold">{score} %</span>
          <span className={clsx('flex items-center gap-1', rmColor)}><RmIcon size={11} />{health.label || ''}</span>
          <span>{open ? '▲' : '▼'}</span>
        </div>
      </button>
      {open && (
        <div className="px-4 pb-3 grid grid-cols-2 gap-3">
          <div className="flex items-center gap-3">
            <ScoreRing score={score} />
            <div className="text-[11px] text-text-dim">
              <div className="text-xs font-semibold text-text">{health.label || rmLabel}</div>
              <div>{health.existsOnDisk ? t('preview.onDisk') : t('preview.lost')}</div>
              <div>{file.fragments > 1 ? `${file.fragments} ${t('preview.fragments')}` : t('preview.contiguous')}</div>
              {typeof ow === 'number' && <div className={ow > 0 ? 'text-orange-400' : 'text-accent-green'}>{t('preview.overwritten')} : {ow} %</div>}
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <IntBar label="En-tête" value={health.headerOk ? 100 : 30} />
            <IntBar label="Structure" value={health.structPct ?? score} />
            <IntBar label="Données" value={health.dataPct ?? score} />
          </div>
          <div className="col-span-2 flex flex-wrap gap-2 pt-1">
            {repaired ? <span className="flex items-center gap-1.5 text-xs text-accent-green"><CheckCircle2 size={13} /> Fichier réparé</span> : (
              <>
                {rm >= 1 && <ActionBtn onClick={() => onRepair('minor')} busy={busy} icon={<Wrench size={12} />} label={t('preview.repair')} color="yellow" />}
                {file.type === 1 && aiAvailable && <ActionBtn onClick={() => onRepair('major')} busy={busy} icon={<Wand2 size={12} />} label={t('preview.repairAI')} color="purple" />}
                {rm === 0 && <span className="flex items-center gap-1.5 text-xs text-accent-green"><ShieldCheck size={13} /> {t('preview.excellent')}</span>}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ScoreRing({ score }) {
  const r = 18; const circ = 2 * Math.PI * r;
  return (
    <svg width={48} height={48} viewBox="0 0 48 48">
      <circle cx={24} cy={24} r={r} fill="none" stroke="#1e1e2e" strokeWidth={4} />
      <circle cx={24} cy={24} r={r} fill="none" stroke={hColor(score)} strokeWidth={4} strokeDasharray={`${circ * (score / 100)} ${circ}`}
        strokeLinecap="round" transform="rotate(-90 24 24)" style={{ transition: 'all 0.5s' }} />
      <text x={24} y={24} textAnchor="middle" dominantBaseline="central" fill={hColor(score)} fontSize={11} fontWeight="bold">{score}</text>
    </svg>
  );
}

function IntBar({ label, value }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-text-dim w-16 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-surface-border overflow-hidden"><div className="h-full rounded-full" style={{ width: `${value}%`, background: hColor(value), transition: 'width 0.5s' }} /></div>
      <span className="text-[10px] font-mono" style={{ color: hColor(value) }}>{value} %</span>
    </div>
  );
}

function ActionBtn({ onClick, busy, icon, label, color }) {
  const cls = color === 'yellow' ? 'bg-yellow-500/20 text-yellow-300 hover:bg-yellow-500/30 border-yellow-500/30' : 'bg-purple-500/20 text-purple-300 hover:bg-purple-500/30 border-purple-500/30';
  return (
    <button onClick={onClick} disabled={busy} className={clsx('flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border transition-all', busy ? 'opacity-50 cursor-wait' : cls)}>
      {busy ? <Sparkles size={11} className="animate-spin" /> : icon}{label}
    </button>
  );
}

function IconBtn({ onClick, children, title }) {
  return (
    <button title={title} onClick={onClick} className="w-8 h-8 flex items-center justify-center rounded-lg bg-surface-2 hover:bg-surface-border text-text-muted hover:text-text transition-colors">
      {children}
    </button>
  );
}

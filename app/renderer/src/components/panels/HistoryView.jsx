import React, { useEffect, useState } from 'react';
import { Trash2, Clock, HardDrive, FileText, RefreshCw, FolderOpen } from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
import { useT } from '../../i18n';

const lzr = window.lazarus;
const STATUS_COLOR = { complete: 'text-accent-green', running: 'text-primary', interrupted: 'text-yellow-400', stopped: 'text-yellow-400', error: 'text-red-400' };

export default function HistoryView() {
  const t = useT();
  const [sessions, setSessions] = useState([]);
  const [loadingId, setLoadingId] = useState(null);
  const addToast = useAppStore((s) => s.addToast);

  const refresh = () => lzr?.invoke('session:list').then((s) => setSessions(Array.isArray(s) ? s : [])).catch(() => {});
  useEffect(() => { refresh(); }, []);

  const open = async (m) => {
    setLoadingId(m.id);
    const st = useAppStore.getState();
    st.clearFiles(); st.setScanResult(null); st.clearWarnings(); st.setLayout(null);
    st.setSessionId(m.id);
    const r = await lzr?.invoke('session:load', m.id);
    setLoadingId(null);
    if (r?.success) {
      st.setScanState('done');
      st.setProgress({ percent: 100, filesFound: r.count });
      st.setScanResult({ filesFound: r.count, sessionId: m.id });
      st.setView('scan');
      st.addToast(`${r.count.toLocaleString()} ${t('files.found')}`, 'success');
    } else addToast(r?.message || 'Erreur', 'error');
  };

  const resume = async (m) => {
    const st = useAppStore.getState();
    st.clearFiles(); st.clearWarnings(); st.setLayout(null); st.setScanResult(null);
    st.setSessionId(m.id); st.setScanState('scanning'); st.setScanStartTime(Date.now()); st.setView('scan');
    await lzr?.invoke('session:load', m.id);                       // recharge d'abord ce qui est déjà trouvé
    st.setScanState('scanning');
    await lzr?.invoke('scan:start', { devicePath: m.device, deviceLabel: m.label, resumeSessionId: m.id, skipFs: true, enableCarving: true,
      startOffset: m.lastOffset, deepScan: !!(m.options && m.options.deepScan), carveText: !!(m.options && m.options.deepScan) });
  };
  const remove = async (m) => { await lzr?.invoke('session:delete', m.id); refresh(); };
  const fmt = (iso) => { try { return new Date(iso).toLocaleString(); } catch { return iso; } };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-lg font-bold text-text flex items-center gap-2"><Clock size={18} />{t('sessions.title')}</h2>
        <button onClick={refresh} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-2 border border-surface-border text-text-dim hover:text-text text-xs transition-colors"><RefreshCw size={12} />{t('scan.refresh')}</button>
      </div>
      {sessions.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-48 text-text-dim gap-3"><Clock size={36} className="opacity-30" /><p className="text-sm">{t('sessions.empty')}</p></div>
      ) : (
        <div className="flex flex-col gap-3 max-w-3xl">
          {sessions.map((m) => (
            <div key={m.id} className="bg-surface-2 border border-surface-border rounded-xl p-4 flex items-center gap-4">
              <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0"><HardDrive size={18} className="text-primary" /></div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-text truncate">{m.label || m.device || '—'}</div>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-dim mt-1">
                  <span className="flex items-center gap-1"><Clock size={11} />{fmt(m.started)}</span>
                  <span className="flex items-center gap-1"><FileText size={11} />{(m.filesFound || 0).toLocaleString()} {t('files.found')}</span>
                  <span className={STATUS_COLOR[m.status]}>{t('sessions.status.' + m.status)}</span>
                  {m.options?.deepScan && <span>{t('scan.mode.deep')}</span>}
                  {m.error && <span className="text-red-300 truncate max-w-[240px]" title={m.error}>{m.error}</span>}
                </div>
              </div>
              <button onClick={() => open(m)} disabled={loadingId === m.id || m.status === 'running'}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/20 border border-primary/30 text-primary hover:bg-primary/30 text-xs font-semibold disabled:opacity-40">
                <FolderOpen size={12} />{loadingId === m.id ? '…' : t('sessions.load')}
              </button>
              {m.lastOffset > 0 && m.status !== 'running' && m.status !== 'complete' && (
                <button onClick={() => resume(m)} title={t('sessions.resume.hint')}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-yellow-500/15 border border-yellow-500/30 text-yellow-300 hover:bg-yellow-500/25 text-xs font-semibold">
                  ▶ {t('sessions.resume')}
                </button>
              )}
              <button onClick={() => remove(m)} className="p-2 rounded-lg text-red-400 hover:bg-red-500/10" title={t('sessions.delete')}><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

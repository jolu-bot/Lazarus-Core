import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Compass, X, Trash2, HardDriveDownload, FileQuestion, Camera, Activity, Wand2, ChevronLeft, Play, ShieldAlert } from 'lucide-react';
import clsx from 'clsx';
import { useAppStore } from '../../stores/useAppStore';
import SourcePicker from '../ui/SourcePicker';
import RepairDialog from './RepairDialog';
import { useT } from '../../i18n';

const lzr = window.lazarus;

// scénario -> réglages d'analyse recommandés
const PRESETS = {
  deleted: { deepScan: false, enableCarving: false, carveAll: false, carveText: false, includeExisting: false },
  formatted: { deepScan: true, enableCarving: true, carveAll: false, carveText: false, includeExisting: false, carveCats: ['images', 'video', 'audio', 'documents', 'archives'] },
  raw: { deepScan: true, enableCarving: true, carveAll: false, carveText: false, includeExisting: false, carveCats: ['images', 'video', 'audio', 'documents', 'archives'] },
  media: { deepScan: true, enableCarving: true, carveAll: false, carveText: false, includeExisting: false, carveCats: ['images', 'video', 'audio'] },
};
const SCENARIOS = [
  ['deleted', Trash2, 'assistant.deleted'],
  ['formatted', HardDriveDownload, 'assistant.formatted'],
  ['raw', FileQuestion, 'assistant.raw'],
  ['media', Camera, 'assistant.media'],
  ['failing', Activity, 'assistant.failing'],
  ['repair', Wand2, 'assistant.repair'],
];
const EXT_TYPE = { jpg: 1, jpeg: 1, png: 1, gif: 1, bmp: 1, mp4: 2, mov: 2, mp3: 3, wav: 3 };

/** Assistant guidé : « que s'est-il passé ? » → réglages adaptés → analyse (ou clonage / réparation). */
export default function AssistantDialog({ onClose, onLaunch }) {
  const t = useT();
  const selectedDrive = useAppStore((s) => s.selectedDrive);
  const selectDrive = useAppStore((s) => s.selectDrive);
  const setScanOptions = useAppStore((s) => s.setScanOptions);
  const setView = useAppStore((s) => s.setView);
  const [scenario, setScenario] = useState(null);
  const [repairTarget, setRepairTarget] = useState(null);

  const close = (remember = true) => {
    if (remember) { try { localStorage.setItem('lz-assistant-seen', '1'); } catch { /* stockage indisponible */ } }
    onClose();
  };

  const choose = async (id) => {
    if (id === 'repair') {
      const f = await lzr?.invoke('dialog:openFile', { filters: [{ name: '*', extensions: ['*'] }] });
      if (!f) return;
      const name = f.split(/[\\/]/).pop();
      const ext = (name.split('.').pop() || '').toLowerCase();
      setRepairTarget({ id: -1, name, path: f, outputPath: f, extension: ext, type: EXT_TYPE[ext] || 0, size: 0, device: '', health: {} });
      return;
    }
    setScenario(id);
  };

  const launch = () => {
    setScanOptions(PRESETS[scenario]);
    close();
    setTimeout(() => onLaunch && onLaunch(), 0);
  };

  if (repairTarget) return <RepairDialog file={repairTarget} originalSrc={null} onClose={() => { setRepairTarget(null); close(); }} />;

  return (
    <div className="fixed inset-0 z-[9000] bg-black/70 flex items-center justify-center p-6" role="dialog" aria-modal="true" aria-label={t('assistant.title')}>
      <motion.div initial={{ scale: 0.96, y: 10 }} animate={{ scale: 1, y: 0 }}
        className="w-[760px] max-w-full max-h-[90vh] flex flex-col bg-bg-2 border border-surface-border rounded-2xl shadow-panel overflow-hidden">
        <div className="flex items-center gap-3 px-6 py-4 border-b border-surface-border">
          <Compass size={18} className="text-primary" />
          <h3 className="text-base font-semibold text-text flex-1">{t('assistant.title')}</h3>
          <button onClick={() => close()} className="text-text-dim hover:text-text" aria-label="close"><X size={16} /></button>
        </div>

        <div className="p-6 overflow-y-auto flex flex-col gap-4">
          {!scenario && (
            <>
              <p className="text-sm text-text-muted">{t('assistant.intro')}</p>
              <div className="grid grid-cols-2 gap-3">
                {SCENARIOS.map(([id, Icon, key]) => (
                  <button key={id} onClick={() => choose(id)}
                    className="flex items-start gap-3 text-left p-4 rounded-xl border border-surface-border bg-surface-2 hover:border-primary/50 hover:bg-primary/5 transition-colors">
                    <Icon size={20} className="text-primary shrink-0 mt-0.5" />
                    <span><span className="block text-sm font-semibold text-text">{t(key)}</span>
                      <span className="block text-xs text-text-dim mt-0.5">{t(key + '.hint')}</span></span>
                  </button>
                ))}
              </div>
              <p className="flex items-start gap-2 text-xs text-orange-300"><ShieldAlert size={14} className="shrink-0 mt-0.5" />{t('assistant.warn')}</p>
            </>
          )}

          {scenario === 'failing' && (
            <>
              <button onClick={() => setScenario(null)} className="self-start flex items-center gap-1 text-xs text-text-dim hover:text-text"><ChevronLeft size={13} />{t('assistant.back')}</button>
              <p className="text-sm text-text-muted">{t('assistant.failing.advice')}</p>
              <div className="flex gap-2">
                <button onClick={() => { close(); setView('clone'); }} className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary-hover">{t('assistant.failing.clone')}</button>
                <button onClick={() => { close(); setView('tools'); }} className="px-4 py-2 rounded-lg border border-surface-border text-sm text-text-muted hover:text-text">{t('assistant.failing.health')}</button>
              </div>
            </>
          )}

          {scenario && scenario !== 'failing' && (
            <>
              <button onClick={() => setScenario(null)} className="self-start flex items-center gap-1 text-xs text-text-dim hover:text-text"><ChevronLeft size={13} />{t('assistant.back')}</button>
              <div>
                <p className="text-sm font-semibold text-text mb-1">{t('assistant.source')}</p>
                <SourcePicker value={selectedDrive} onChange={selectDrive} disabled={false} />
              </div>
              <div className="rounded-xl border border-surface-border bg-surface-2 p-4 text-sm">
                <p className="text-text font-medium mb-1">{t('assistant.plan')}</p>
                <p className="text-text-muted text-xs">{t('assistant.plan.' + scenario)}</p>
              </div>
              <p className="flex items-start gap-2 text-xs text-orange-300"><ShieldAlert size={14} className="shrink-0 mt-0.5" />{t('assistant.dest')}</p>
            </>
          )}
        </div>

        <div className={clsx('flex items-center justify-between gap-3 px-6 py-4 border-t border-surface-border')}>
          <span className="text-[11px] text-text-dim">{t('repair.safe')}</span>
          <div className="flex gap-2">
            <button onClick={() => close()} className="px-4 py-2 rounded-lg text-sm text-text-muted hover:text-text">{t('assistant.skip')}</button>
            {scenario && scenario !== 'failing' && (
              <button onClick={launch} disabled={!selectedDrive}
                className={clsx('flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white bg-primary hover:bg-primary-hover', !selectedDrive && 'opacity-50 cursor-not-allowed')}>
                <Play size={14} />{t('scan.start')}
              </button>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}

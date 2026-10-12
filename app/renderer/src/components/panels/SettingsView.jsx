import React, { useState, useEffect } from 'react';
import { Save, FolderOpen, Stethoscope, FlaskConical } from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
import { useT } from '../../i18n';

const lzr = window.lazarus;

export default function SettingsView() {
  const t = useT();
  const { setSettings, setOutputDir, theme, setTheme, language, setLanguage, diag } = useAppStore();
  const [local, setLocal] = useState({ outputDir: '' });
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    lzr?.invoke('app:getSettings').then((s) => { if (s) { setLocal((p) => ({ ...p, ...s })); setSettings(s); } });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const browse = async () => { const r = await lzr?.invoke('dialog:openFolder'); if (r) setLocal((p) => ({ ...p, outputDir: r })); };
  const save = async () => {
    await lzr?.invoke('app:setSettings', local);
    setSettings(local);
    if (local.outputDir) setOutputDir(local.outputDir);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };
  const selftest = async () => {
    setTesting(true); setTestResult(null);
    const r = await lzr?.invoke('scan:selftest', 'C:');
    setTesting(false); setTestResult(r);
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-lg font-bold text-text mb-6">{t('settings.title')}</h2>
      <div className="max-w-xl flex flex-col gap-6">
        <Field label={t('settings.language')}>
          <Seg value={language} onChange={setLanguage} options={[['fr', 'Français'], ['en', 'English']]} />
        </Field>
        <Field label={t('settings.theme')}>
          <Seg value={theme} onChange={setTheme} options={[['dark', t('settings.theme.dark')], ['light', t('settings.theme.light')]]} />
        </Field>
        <Field label={t('settings.output')} hint={t('settings.output.hint')}>
          <div className="flex gap-2">
            <input type="text" value={local.outputDir || ''} readOnly placeholder="—"
              className="flex-1 bg-surface-2 border border-surface-border rounded-lg px-3 py-2 text-text text-sm cursor-default truncate" />
            <button onClick={browse} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-surface-2 border border-surface-border text-text-dim hover:text-text text-xs transition-colors">
              <FolderOpen size={14} />{t('settings.browse')}
            </button>
          </div>
        </Field>
        <button onClick={save}
          className={'flex items-center justify-center gap-2 px-6 py-2.5 rounded-lg text-sm font-semibold transition-all ' + (saved ? 'bg-accent-green/20 border border-accent-green/40 text-accent-green' : 'bg-primary hover:bg-primary-hover text-white')}>
          <Save size={15} />{saved ? t('settings.saved') : t('settings.save')}
        </button>

        <div className="border-t border-surface-border pt-6">
          <h3 className="text-sm font-semibold text-text mb-3 flex items-center gap-2"><Stethoscope size={15} />{t('settings.diag')}</h3>
          <div className="bg-surface-2 border border-surface-border rounded-xl p-4 text-xs font-mono text-text-muted flex flex-col gap-1">
            <div>Moteur : {diag?.engine || '—'} {diag?.version ? `v${diag.version}` : ''}</div>
            <div>Python : {diag?.python || '—'} {diag?.python_version ? `(${diag.python_version})` : ''}</div>
            <div>Administrateur : <span className={diag?.admin ? 'text-accent-green' : 'text-red-400'}>{diag?.admin ? 'oui' : 'non'}</span></div>
            {diag?.logPath && <div className="truncate">Journal : {diag.logPath}</div>}
            {diag?.error && <div className="text-red-300">{diag.error}</div>}
          </div>
        </div>

        <div>
          <h3 className="text-sm font-semibold text-text mb-1 flex items-center gap-2"><FlaskConical size={15} />{t('settings.selftest')}</h3>
          <p className="text-xs text-text-dim mb-3">{t('settings.selftest.hint')}</p>
          <button onClick={selftest} disabled={testing}
            className="px-4 py-2 rounded-lg bg-surface-2 border border-surface-border text-text hover:border-primary/50 text-sm disabled:opacity-50">
            {testing ? '…' : t('settings.selftest.run')}
          </button>
          {testResult && (
            <div className={'mt-3 rounded-xl border p-3 text-xs font-mono ' + (testResult.success ? 'border-accent-green/30 bg-accent-green/10 text-accent-green' : 'border-red-500/30 bg-red-500/10 text-red-300')}>
              {testResult.error ? testResult.error : `${testResult.identical}/${testResult.tested} fichiers identiques (${testResult.skipped} ignorés)`}
              {testResult.details?.map((d) => <div key={d.path}>≠ {d.path}</div>)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Seg({ value, onChange, options }) {
  return (
    <div className="flex gap-2">
      {options.map(([v, label]) => (
        <button key={v} onClick={() => onChange(v)}
          className={'flex-1 py-2 rounded-lg border text-sm font-medium transition-all ' + (value === v ? 'bg-primary/20 border-primary/50 text-primary' : 'bg-surface-2 border-surface-border text-text-dim hover:text-text')}>
          {label}
        </button>
      ))}
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-text">{label}</label>
      {hint && <p className="text-xs text-text-dim -mt-0.5">{hint}</p>}
      {children}
    </div>
  );
}

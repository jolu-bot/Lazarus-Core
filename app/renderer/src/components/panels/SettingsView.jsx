import React, { useState, useEffect } from 'react';
import { Save, FolderOpen } from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
const lzr = window.lzr;
export default function SettingsView() {
  const { settings, setSettings, setOutputDir } = useAppStore();
  const [local, setLocal] = useState({ threads:0, bufferMB:4, outputDir:'' });
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    lzr?.invoke('app:getSettings').then((s) => { if (s) { setLocal(s); setSettings(s); } });
  }, []);
  const upd = (k, v) => setLocal((prev) => ({ ...prev, [k]: v }));
  const browse = async () => {
    const r = await lzr?.invoke('dialog:openFolder');
    if (r) upd('outputDir', r);
  };
  const save = async () => {
    await lzr?.invoke('app:setSettings', local);
    setSettings(local);
    if (local.outputDir) setOutputDir(local.outputDir);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-lg font-bold text-text mb-6">Settings</h2>
      <div className="max-w-md flex flex-col gap-6">
        <Field label="Scan Threads" hint="0 = auto (use all cores)">
          <input type="number" min={0} max={64} value={local.threads}
            onChange={(e) => upd('threads', parseInt(e.target.value) || 0)}
            className="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-text text-sm focus:outline-none focus:border-primary" />
        </Field>
        <Field label="Buffer Size (MB)" hint="Memory buffer per thread during scan">
          <input type="number" min={1} max={256} value={local.bufferMB}
            onChange={(e) => upd('bufferMB', parseInt(e.target.value) || 4)}
            className="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-text text-sm focus:outline-none focus:border-primary" />
        </Field>
        <Field label="Default Output Directory" hint="Pre-selected destination for recovered files">
          <div className="flex gap-2">
            <input type="text" value={local.outputDir} readOnly placeholder="Not set"
              className="flex-1 bg-surface-2 border border-border rounded-lg px-3 py-2 text-text text-sm focus:outline-none cursor-default truncate" />
            <button onClick={browse}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-surface-3 border border-border text-text-dim hover:text-text hover:border-primary/50 text-xs transition-colors">
              <FolderOpen size={14} /> Browse
            </button>
          </div>
        </Field>
        <button onClick={save}
          className={'flex items-center justify-center gap-2 px-6 py-2.5 rounded-lg text-sm font-semibold transition-all ' + (saved ? 'bg-accent-green/20 border border-accent-green/40 text-accent-green' : 'bg-primary hover:bg-primary/90 text-black')}>
          <Save size={15} />{saved ? 'Saved!' : 'Save Settings'}
        </button>
      </div>
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
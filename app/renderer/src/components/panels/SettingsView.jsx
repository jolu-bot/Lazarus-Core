import React from 'react';
import { Settings, Info, Cpu, Monitor } from 'lucide-react';

export default function SettingsView() {
  return (
    <div className="flex flex-col h-full overflow-y-auto p-8 bg-bg">
      <div className="max-w-2xl mx-auto w-full">
        <h1 className="text-2xl font-bold text-text mb-6 flex items-center gap-3">
          <Settings size={24} className="text-primary" />
          Settings
        </h1>
        <div className="space-y-4">
          <Section title="Performance" icon={<Cpu size={16} />}>
            <Setting label="Thread count" desc="Number of parallel scan threads (0 = auto)" type="number" defaultV="0" />
            <Setting label="Buffer size (MB)" desc="Read buffer per thread" type="number" defaultV="4" />
          </Section>
          <Section title="Recovery" icon={<Monitor size={16} />}>
            <Setting label="Default output folder" desc="Where recovered files are saved" type="text" defaultV="~/LazarusRecovered" />
          </Section>
          <Section title="About" icon={<Info size={16} />}>
            <div className="text-sm text-text-muted space-y-1">
              <p>LAZARUS CORE v1.0.0</p>
              <p className="text-text-dim text-xs">Recover the Impossible</p>
              <p className="text-text-dim text-xs mt-2">
                Built with Electron + React + C++ + Python AI
              </p>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}

function Section({ title, icon, children }) {
  return (
    <div className="bg-surface-2 border border-surface-border rounded-2xl p-5">
      <h2 className="text-sm font-semibold text-text mb-4 flex items-center gap-2">
        <span className="text-primary">{icon}</span>
        {title}
      </h2>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function Setting({ label, desc, type, defaultV }) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm text-text-muted">{label}</p>
        <p className="text-xs text-text-dim">{desc}</p>
      </div>
      <input
        type={type}
        defaultValue={defaultV}
        className="bg-bg border border-surface-border rounded-lg px-3 py-1.5
                   text-sm text-text outline-none focus:border-primary/50 w-32 text-right"
      />
    </div>
  );
}

import React from 'react';
import { motion } from 'framer-motion';
import { HardDrive, Settings, Clock, Sparkles, Shield, Copy, LifeBuoy, Wrench } from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
import clsx from 'clsx';
import { useT } from '../../i18n';

export default function Sidebar() {
  const t = useT();
  const { view, setView, license, aiAvailable, scanState } = useAppStore();
  const NAV = [
    { id: 'scan', icon: HardDrive, label: t('nav.scan') },
    { id: 'clone', icon: Copy, label: t('nav.clone') },
    { id: 'tools', icon: Wrench, label: t('nav.tools') },
    { id: 'history', icon: Clock, label: t('nav.sessions') },
    { id: 'guide', icon: LifeBuoy, label: t('nav.guide') },
    { id: 'settings', icon: Settings, label: t('nav.settings') },
  ];
  const scanning = scanState === 'scanning' || scanState === 'stopping';

  return (
    <div className="flex flex-col w-16 bg-bg-2 border-r border-surface-border items-center py-4 gap-2 z-40">
      {NAV.map((item) => {
        const active = view === item.id;
        const Icon = item.icon;
        return (
          <div key={item.id} className="relative group">
            <motion.button whileTap={{ scale: 0.92 }} onClick={() => setView(item.id)}
              className={clsx('w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-200',
                active ? 'bg-primary/20 text-primary shadow-glow-sm' : 'text-text-dim hover:text-text hover:bg-surface-2')}>
              {active && <motion.div layoutId="sidebar-indicator" className="absolute inset-0 rounded-xl bg-primary/10 border border-primary/30" transition={{ type: 'spring', stiffness: 400, damping: 30 }} />}
              <Icon size={18} className="relative z-10" />
              {item.id === 'scan' && scanning && <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-primary animate-pulse z-20" />}
            </motion.button>
            <div className="absolute left-14 top-1/2 -translate-y-1/2 bg-surface-2 border border-surface-border rounded-lg px-3 py-1.5 opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 shadow-panel">
              <span className="text-xs text-text font-medium">{item.label}</span>
            </div>
          </div>
        );
      })}

      <div className="flex-1" />

      <div className="relative group">
        <div className={clsx('w-10 h-10 rounded-xl flex items-center justify-center', aiAvailable ? 'text-accent-green' : 'text-text-dim')}><Sparkles size={16} /></div>
        <div className="absolute left-14 top-1/2 -translate-y-1/2 bg-surface-2 border border-surface-border rounded-lg px-3 py-1.5 opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 shadow-panel">
          <span className="text-xs text-text">IA : {aiAvailable ? 'en ligne' : 'hors ligne'}</span>
        </div>
      </div>

      <div className="relative group">
        <div className={clsx('w-10 h-10 rounded-xl flex items-center justify-center', license.plan > 0 ? 'text-primary' : 'text-text-dim')}><Shield size={16} /></div>
        <div className="absolute left-14 bottom-0 bg-surface-2 border border-surface-border rounded-lg px-3 py-1.5 opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 shadow-panel">
          <span className="text-xs text-text">{license.tier || 'Local'}</span>
        </div>
      </div>
    </div>
  );
}

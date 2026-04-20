import React from 'react';
import { motion }      from 'framer-motion';
import { HardDrive, Settings } from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
import clsx            from 'clsx';

const NAV = [
  { id: 'scan',     icon: HardDrive, label: 'Scan & Recover' },
  { id: 'settings', icon: Settings,  label: 'Settings' },
];

export default function Sidebar() {
  const { view, setView, license, aiAvailable } = useAppStore();

  return (
    <div className="flex flex-col w-16 bg-bg-2 border-r border-surface-border
                    items-center py-4 gap-2 z-40">
      {NAV.map((item) => {
        const active = view === item.id;
        const Icon   = item.icon;
        return (
          <div key={item.id} className="relative group">
            <motion.button
              whileTap={{ scale: 0.92 }}
              onClick={() => setView(item.id)}
              className={clsx(
                'w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-200',
                active
                  ? 'bg-primary/20 text-primary shadow-glow-sm'
                  : 'text-text-dim hover:text-text hover:bg-surface-2'
              )}
            >
              {active && (
                <motion.div
                  layoutId="sidebar-indicator"
                  className="absolute inset-0 rounded-xl bg-primary/10 border border-primary/30"
                  transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                />
              )}
              <Icon size={18} className="relative z-10" />
            </motion.button>
            {/* Tooltip */}
            <div className="absolute left-14 top-1/2 -translate-y-1/2 bg-surface-2
                            border border-surface-border rounded-lg px-3 py-1.5
                            opacity-0 group-hover:opacity-100 pointer-events-none
                            transition-opacity whitespace-nowrap z-50 shadow-panel">
              <span className="text-xs text-text font-medium">{item.label}</span>
            </div>
          </div>
        );
      })}

      <div className="flex-1" />

      {/* AI Badge */}
      <div className="relative group">
        <div className={clsx(
          'w-10 h-10 rounded-xl flex items-center justify-center',
          aiAvailable ? 'text-accent-green' : 'text-text-dim'
        )}>
          <Sparkles size={16} />
        </div>
        <div className="absolute left-14 top-1/2 -translate-y-1/2 bg-surface-2
                        border border-surface-border rounded-lg px-3 py-1.5
                        opacity-0 group-hover:opacity-100 pointer-events-none
                        transition-opacity whitespace-nowrap z-50 shadow-panel">
          <span className="text-xs text-text">
            AI Engine: {aiAvailable ? 'Online' : 'Offline'}
          </span>
        </div>
      </div>

      {/* Plan badge */}
      <div className="relative group">
        <div className={clsx(
          'w-10 h-10 rounded-xl flex items-center justify-center',
          license.plan > 0 ? 'text-primary' : 'text-text-dim'
        )}>
          <Shield size={16} />
        </div>
        <div className="absolute left-14 bottom-0 bg-surface-2
                        border border-surface-border rounded-lg px-3 py-1.5
                        opacity-0 group-hover:opacity-100 pointer-events-none
                        transition-opacity whitespace-nowrap z-50 shadow-panel">
          <span className="text-xs text-text">
            Plan: {['Free','Pro','Pro+','Business'][license.plan] || 'Free'}
          </span>
        </div>
      </div>
    </div>
  );
}

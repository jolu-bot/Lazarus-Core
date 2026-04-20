import React, { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useAppStore }   from './stores/useAppStore';
import TitleBar          from './components/ui/TitleBar';
import Sidebar           from './components/ui/Sidebar';
import ScanView          from './components/panels/ScanView';
import SettingsView      from './components/panels/SettingsView';
import ToastContainer    from './components/ui/Toast';

const lzr = window.lazarus;

export default function App() {
  const { view, setLicense, setAIAvailable } = useAppStore();

  // â”€â”€ Bootstrap â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  useEffect(() => {
    // Load license
    lzr?.invoke('license:get').then((lic) => {
      if (lic) setLicense(lic);
    }).catch(() => {});

    // Check AI health
    lzr?.invoke('ai:health').then((h) => {
      setAIAvailable(h?.ok === true);
    }).catch(() => setAIAvailable(false));
  }, []);

  const views = { scan: ScanView, settings: SettingsView };
  const ActiveView = views[view] || ScanView;

  return (
    <div className="flex flex-col h-screen bg-bg overflow-hidden">
      <TitleBar />
      <ToastContainer />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <AnimatePresence mode="wait">
          <motion.div
            key={view}
            className="flex-1 overflow-hidden"
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -8 }}
            transition={{ duration: 0.2 }}
          >
            <ActiveView />
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

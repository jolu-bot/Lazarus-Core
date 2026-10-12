import React, { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useAppStore } from './stores/useAppStore';
import { useScanEvents } from './hooks/useScanEvents';
import TitleBar from './components/ui/TitleBar';
import Sidebar from './components/ui/Sidebar';
import ScanView from './components/panels/ScanView';
import SettingsView from './components/panels/SettingsView';
import HistoryView from './components/panels/HistoryView';
import ImagerView from './components/panels/ImagerView';
import GuideView from './components/panels/GuideView';
import ToolsView from './components/panels/ToolsView';
import ToastContainer from './components/ui/Toast';

const lzr = window.lazarus;
const VIEWS = { scan: ScanView, clone: ImagerView, tools: ToolsView, history: HistoryView, guide: GuideView, settings: SettingsView };

export default function App() {
  const { view, setLicense, setAIAvailable, theme, setDiag } = useAppStore();
  useScanEvents();

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document.documentElement.classList.toggle('light', theme !== 'dark');
  }, [theme]);

  useEffect(() => {
    lzr?.invoke('license:get').then((lic) => { if (lic) setLicense(lic); }).catch(() => {});
    lzr?.invoke('ai:health').then((h) => setAIAvailable(h?.ok === true)).catch(() => setAIAvailable(false));
    lzr?.invoke('app:diag').then((d) => setDiag(d)).catch((e) => setDiag({ error: String(e?.message || e), admin: true }));
    lzr?.invoke('app:getSettings').then((s) => { if (s?.outputDir) useAppStore.getState().setOutputDir(s.outputDir); }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // La vue Scan reste montée (elle porte la liste de fichiers) ; les autres vues se montent à la demande.
  const Other = view !== 'scan' ? VIEWS[view] : null;

  return (
    <div className="flex flex-col h-screen bg-bg overflow-hidden">
      <TitleBar />
      <ToastContainer />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <div className="flex-1 overflow-hidden relative">
          <div className="absolute inset-0" style={{ display: view === 'scan' ? 'block' : 'none' }}><ScanView /></div>
          <AnimatePresence mode="wait">
            {Other && (
              <motion.div key={view} className="absolute inset-0 flex" initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }} transition={{ duration: 0.15 }}>
                <Other />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

import React, { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, AlertCircle, X, Info } from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
export default function ToastContainer() {
  const { toasts, removeToast } = useAppStore();
  return (
    <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
      <AnimatePresence>
        {toasts.map((t) => (
          <Toast key={t.id} toast={t} onClose={() => removeToast(t.id)} />
        ))}
      </AnimatePresence>
    </div>
  );
}
function Toast({ toast, onClose }) {
  useEffect(() => {
    const timer = setTimeout(onClose, toast.duration || 4000);
    return () => clearTimeout(timer);
  }, []);
  const STYLES = { success:{ Icon:CheckCircle2, cls:'border-accent-green/30 bg-accent-green/10 text-accent-green' }, error:{ Icon:AlertCircle, cls:'border-red-500/30 bg-red-500/10 text-red-400' }, info:{ Icon:Info, cls:'border-primary/30 bg-primary/10 text-primary' } };
  const { Icon, cls } = STYLES[toast.type || 'success'] || STYLES.success;
  return (
    <motion.div initial={{ opacity:0, x:60, scale:0.95 }} animate={{ opacity:1, x:0, scale:1 }} exit={{ opacity:0, x:60, scale:0.95 }}
      className={'pointer-events-auto flex items-start gap-3 px-4 py-3 rounded-xl border backdrop-blur-sm shadow-panel min-w-[260px] max-w-[380px] ' + cls}>
      <Icon size={16} className="flex-shrink-0 mt-0.5" />
      <span className="text-sm flex-1 text-text leading-snug">{toast.msg}</span>
      <button onClick={onClose} className="text-text-dim hover:text-text transition-colors flex-shrink-0 ml-1"><X size={13} /></button>
    </motion.div>
  );
}
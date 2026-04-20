import React, { useEffect } from 'react';
import { Trash2, Clock, HardDrive, FileText, RefreshCw } from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
export default function HistoryView() {
  const { scanHistory, loadScanHistory, clearScanHistory, addToast } = useAppStore();
  useEffect(() => { loadScanHistory(); }, []);
  const handleClear = async () => { await clearScanHistory(); addToast('Scan history cleared','success'); };
  const fmt = (iso) => { try { return new Date(iso).toLocaleString(); } catch { return iso; } };
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-lg font-bold text-text flex items-center gap-2"><Clock size={18}/>Scan History</h2>
        <div className="flex gap-2">
          <button onClick={loadScanHistory} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-2 border border-border text-text-dim hover:text-text text-xs transition-colors"><RefreshCw size={12}/>Refresh</button>
          {scanHistory.length>0&&<button onClick={handleClear} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 text-xs transition-colors"><Trash2 size={12}/>Clear</button>}
        </div>
      </div>
      {scanHistory.length===0?(
        <div className="flex flex-col items-center justify-center h-48 text-text-dim gap-3">
          <Clock size={36} opacity={0.3}/>
          <p className="text-sm">No scan history yet. Run a scan to see results here.</p>
        </div>
      ):(
        <div className="flex flex-col gap-3 max-w-2xl">
          {scanHistory.map((h)=>(
            <div key={h.id} className="bg-surface-2 border border-border rounded-xl p-4 flex items-center gap-4">
              <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                <HardDrive size={18} className="text-primary"/>
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-medium text-text truncate">{h.drive||'Unknown drive'}</span>
                </div>
                <div className="flex items-center gap-4 text-xs text-text-dim">
                  <span className="flex items-center gap-1"><Clock size={11}/>{fmt(h.date)}</span>
                  <span className="flex items-center gap-1"><FileText size={11}/>{h.filesFound?.toLocaleString()||0} files found</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
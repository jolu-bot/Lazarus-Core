import React from 'react';
import { motion } from 'framer-motion';
import clsx from 'clsx';
export default function ProgressBar({ percent=0, filesFound=0, done=false, sectorsScanned=0, sectorsTotal=0, startTime=null }) {
  const elapsed     = startTime ? (Date.now() - startTime) / 1000 : 0;
  const bytesScanned = sectorsScanned * 512;
  const mbps        = elapsed > 2 && bytesScanned > 0 ? (bytesScanned / 1e6 / elapsed).toFixed(1) : null;
  const remaining   = (mbps && sectorsTotal > sectorsScanned && percent > 2)
    ? fmtTime(Math.round((sectorsTotal - sectorsScanned) * 512 / 1e6 / parseFloat(mbps)))
    : null;
  return (
    <div className="flex items-center gap-4">
      <div className="flex-1 bg-surface-2 rounded-full h-1.5 overflow-hidden">
        <motion.div
          className={clsx('h-full rounded-full', done ? 'bg-accent-green' : 'bg-primary')}
          initial={{ width: 0 }}
          animate={{ width: (Math.min(100, percent)) + '%' }}
          transition={{ duration: 0.3 }}
        />
      </div>
      <div className="flex items-center gap-3 text-xs text-text-dim font-mono flex-shrink-0">
        <span className="text-text font-semibold">{done ? '\u2713' : (Math.round(percent) + '%')}</span>
        <span>{filesFound.toLocaleString()} files</span>
        {mbps && !done && <span className="text-primary">{mbps} MB/s</span>}
        {remaining && !done && <span className="text-text-dim">{remaining}</span>}
        {done && <span className="text-accent-green font-semibold">Scan complete</span>}
      </div>
    </div>
  );
}
function fmtTime(sec) {
  if (sec < 60) return sec + 's';
  return Math.floor(sec / 60) + 'm ' + (sec % 60) + 's';
}
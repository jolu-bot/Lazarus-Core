import React from 'react';
import { motion } from 'framer-motion';
import clsx from 'clsx';

export default function ProgressBar({ percent = 0, filesFound = 0, done = false }) {
  return (
    <div className="flex items-center gap-4">
      <div className="flex-1 bg-surface-2 rounded-full h-1.5 overflow-hidden">
        <motion.div
          className={clsx(
            'h-full rounded-full',
            done ? 'bg-accent-green' : 'bg-primary'
          )}
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(100, percent)}%` }}
          transition={{ duration: 0.3 }}
        />
      </div>
      <div className="flex items-center gap-3 text-xs text-text-dim font-mono flex-shrink-0">
        <span className="text-text font-semibold">
          {done ? '✓' : `${Math.round(percent)}%`}
        </span>
        <span>{filesFound.toLocaleString()} files</span>
        {done && <span className="text-accent-green font-semibold">Scan complete</span>}
      </div>
    </div>
  );
}

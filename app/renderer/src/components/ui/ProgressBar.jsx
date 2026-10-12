import React from 'react';
import { motion } from 'framer-motion';
import clsx from 'clsx';
import { formatBytes } from '../../utils/formatters';
import { useT } from '../../i18n';

function fmtTime(sec) {
  if (!isFinite(sec) || sec < 0) return '';
  if (sec < 60) return `${Math.round(sec)} s`;
  if (sec < 3600) return `${Math.floor(sec / 60)} min ${Math.round(sec % 60)} s`;
  return `${Math.floor(sec / 3600)} h ${Math.floor((sec % 3600) / 60)} min`;
}

export default function ProgressBar({ percent = 0, filesFound = 0, state = 'scanning', speed = 0, bytesDone = 0, bytesTotal = 0,
  currentPath = '', startTime = null, extra = null }) {
  const t = useT();
  const done = state === 'done';
  const stopped = state === 'stopped';
  const error = state === 'error';
  const remaining = speed > 0 && bytesTotal > bytesDone && percent > 1 ? fmtTime((bytesTotal - bytesDone) / speed) : '';
  const elapsed = startTime ? fmtTime((Date.now() - startTime) / 1000) : '';
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-4">
        <div className="flex-1 bg-surface-2 rounded-full h-2 overflow-hidden">
          <motion.div
            className={clsx('h-full rounded-full', done ? 'bg-accent-green' : error ? 'bg-red-500' : stopped ? 'bg-yellow-500' : 'bg-primary')}
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(100, done ? 100 : percent)}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>
        <div className="flex items-center gap-3 text-xs text-text-dim font-mono flex-shrink-0">
          <span className="text-text font-semibold">{done ? '✓' : `${Math.round(percent)} %`}</span>
          <span>{filesFound.toLocaleString()} {t('scan.files')}</span>
          {!done && !stopped && speed > 0 && <span className="text-primary">{formatBytes(speed)}/s</span>}
          {!done && !stopped && remaining && <span>~ {remaining}</span>}
          {(done || stopped) && elapsed && <span>{elapsed}</span>}
          {done && <span className="text-accent-green font-semibold">{t('scan.done')}</span>}
          {stopped && <span className="text-yellow-400 font-semibold">{t('scan.stopped')}</span>}
          {extra}
        </div>
      </div>
      {currentPath && !done && <div className="text-[11px] text-text-dim font-mono truncate">{currentPath}</div>}
    </div>
  );
}

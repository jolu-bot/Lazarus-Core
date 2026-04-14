import React from 'react';
import { Minus, Square, X, Cpu } from 'lucide-react';

const lzr = window.lazarus;

export default function TitleBar() {
  return (
    <div className="drag-region flex items-center justify-between h-10 px-4
                    bg-bg-2 border-b border-surface-border flex-shrink-0 z-50">
      {/* Left: Logo */}
      <div className="flex items-center gap-2 no-drag">
        <div className="w-6 h-6 rounded-full bg-gradient-to-br from-primary to-accent
                        flex items-center justify-center shadow-glow-sm">
          <Cpu size={13} className="text-white" />
        </div>
        <span className="text-sm font-semibold text-text tracking-wide">
          LAZARUS CORE
        </span>
        <span className="text-xs text-text-dim font-mono ml-1">v1.0</span>
      </div>

      {/* Center: Tagline */}
      <span className="text-xs text-text-dim font-mono tracking-widest
                       drag-region select-none">
        RECOVER THE IMPOSSIBLE
      </span>

      {/* Right: Window controls */}
      <div className="flex items-center gap-1 no-drag">
        <button onClick={() => lzr?.send('win:minimize')}
          className="w-8 h-8 flex items-center justify-center rounded
                     hover:bg-surface-2 text-text-muted hover:text-text
                     transition-colors">
          <Minus size={14} />
        </button>
        <button onClick={() => lzr?.send('win:maximize')}
          className="w-8 h-8 flex items-center justify-center rounded
                     hover:bg-surface-2 text-text-muted hover:text-text
                     transition-colors">
          <Square size={12} />
        </button>
        <button onClick={() => lzr?.send('win:close')}
          className="w-8 h-8 flex items-center justify-center rounded
                     hover:bg-red-500/20 text-text-muted hover:text-red-400
                     transition-colors">
          <X size={14} />
        </button>
      </div>
    </div>
  );
}

import React, { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Download, Wand2, ZoomIn, ZoomOut, RotateCcw,
  Image, Film, FileText, Music, HardDrive, Sparkles,
  AlertCircle, CheckCircle2
} from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
import clsx from 'clsx';

const lzr = window.lazarus;

export default function PreviewPanel() {
  const { selectedFile, license, aiAvailable, repairedImage, setRepairedImage } = useAppStore();

  const [zoom,        setZoom]        = useState(1);
  const [aiLoading,   setAILoading]   = useState(false);
  const [aiResult,    setAIResult]    = useState(null);
  const [imgError,    setImgError]    = useState(false);
  const [previewSrc,  setPreviewSrc]  = useState(null);
  const [metadata,    setMetadata]    = useState(null);

  // Reset on file change
  useEffect(() => {
    setZoom(1);
    setAIResult(null);
    setImgError(false);
    setRepairedImage(null);

    if (!selectedFile?.path) { setPreviewSrc(null); return; }

    // Load preview for image files
    if (selectedFile.type === 1 && selectedFile.path) {
      setPreviewSrc(`file://${selectedFile.path}`);
    } else {
      setPreviewSrc(null);
    }
  }, [selectedFile]);

  const handleRecover = async () => {
    if (!license.features?.recover) {
      alert('Upgrade to Pro to recover files.');
      return;
    }
    const dir = await lzr?.invoke('dialog:openFolder');
    if (!dir || !selectedFile) return;
    const result = await lzr?.invoke('scan:recover', '', selectedFile, dir);
    if (result?.success) {
      alert(`File recovered to ${dir}`);
    } else {
      alert('Recovery failed: ' + (result?.message || 'Unknown error'));
    }
  };

  const handleAIRepair = async () => {
    if (!license.features?.aiRepair) {
      alert('AI Repair is available in Pro+ and above.');
      return;
    }
    if (!selectedFile?.path) return;
    setAILoading(true);
    try {
      const result = await lzr?.invoke('ai:repair', {
        filePath: selectedFile.path,
        enhance:  true,
        useAI:    true,
      });
      if (result?.success && result.image_b64) {
        const src = `data:image/jpeg;base64,${result.image_b64}`;
        setRepairedImage(src);
        setPreviewSrc(src);
        setAIResult({ success: true, confidence: result.confidence });
      } else {
        setAIResult({ success: false });
      }
    } catch {
      setAIResult({ success: false });
    }
    setAILoading(false);
  };

  if (!selectedFile) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-bg gap-4 text-text-dim">
        <div className="w-20 h-20 rounded-3xl bg-surface-2 flex items-center justify-center">
          <HardDrive size={36} className="text-text-dim" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-text-muted">No file selected</p>
          <p className="text-xs text-text-dim mt-1">Select a file from the list to preview</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 bg-bg overflow-hidden">
      {/* ── Header ────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-3
                      border-b border-surface-border bg-bg-2 flex-shrink-0">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-text truncate">{selectedFile.name}</h3>
          <div className="flex items-center gap-2 text-xs text-text-dim mt-0.5">
            <span>{formatSize(selectedFile.size)}</span>
            <span>·</span>
            <span className="font-mono">.{selectedFile.extension || '?'}</span>
            <span>·</span>
            <span className={clsx(
              selectedFile.confidence > 0.8 ? 'text-accent-green'
              : selectedFile.confidence > 0.6 ? 'text-yellow-400' : 'text-accent'
            )}>
              {Math.round((selectedFile.confidence || 0) * 100)}% confidence
            </span>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5">
          {selectedFile.type === 1 && (
            <>
              <IconBtn onClick={() => setZoom((z) => Math.min(z + 0.25, 4))} title="Zoom in">
                <ZoomIn size={15} />
              </IconBtn>
              <IconBtn onClick={() => setZoom((z) => Math.max(z - 0.25, 0.25))} title="Zoom out">
                <ZoomOut size={15} />
              </IconBtn>
              <IconBtn onClick={() => setZoom(1)} title="Reset">
                <RotateCcw size={14} />
              </IconBtn>
            </>
          )}

          {selectedFile.type === 1 && aiAvailable && (
            <button
              onClick={handleAIRepair}
              disabled={aiLoading || !license.features?.aiRepair}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium',
                'transition-all duration-200',
                aiLoading
                  ? 'bg-primary/10 text-primary/50 cursor-wait'
                  : license.features?.aiRepair
                  ? 'bg-primary/20 text-primary hover:bg-primary/30 border border-primary/30'
                  : 'bg-surface-2 text-text-dim cursor-not-allowed'
              )}
            >
              {aiLoading ? (
                <><Sparkles size={13} className="animate-spin" />Repairing…</>
              ) : (
                <><Wand2 size={13} />AI Repair</>
              )}
            </button>
          )}

          <button
            onClick={handleRecover}
            disabled={!license.features?.recover}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold',
              'transition-all duration-200',
              license.features?.recover
                ? 'bg-primary text-white hover:bg-primary-hover shadow-glow-sm'
                : 'bg-surface-2 text-text-dim cursor-not-allowed'
            )}
          >
            <Download size={13} />
            Recover
          </button>
        </div>
      </div>

      {/* ── AI Result Banner ─────────────────────────────────── */}
      <AnimatePresence>
        {aiResult && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 text-xs',
              aiResult.success
                ? 'bg-accent-green/10 border-b border-accent-green/20 text-accent-green'
                : 'bg-accent/10 border-b border-accent/20 text-accent'
            )}
          >
            {aiResult.success
              ? <><CheckCircle2 size={13} />AI repair complete · {Math.round(aiResult.confidence * 100)}% confidence</>
              : <><AlertCircle size={13} />AI repair failed — file may be too corrupted</>}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Preview Area ──────────────────────────────────────── */}
      <div className="flex-1 overflow-auto flex items-center justify-center bg-[#080810] p-4">
        <AnimatePresence mode="wait">
          {selectedFile.type === 1 ? (
            <ImagePreview
              key={selectedFile.id}
              src={previewSrc}
              zoom={zoom}
              onError={() => setImgError(true)}
              hasError={imgError}
            />
          ) : selectedFile.type === 2 ? (
            <VideoPreview key={selectedFile.id} src={previewSrc} />
          ) : selectedFile.type === 3 ? (
            <AudioPreview key={selectedFile.id} src={previewSrc} />
          ) : (
            <GenericPreview key={selectedFile.id} file={selectedFile} />
          )}
        </AnimatePresence>
      </div>

      {/* ── Metadata Footer ───────────────────────────────────── */}
      <div className="flex items-center gap-4 px-4 py-2
                      border-t border-surface-border bg-bg-2 flex-shrink-0 text-xs
                      text-text-dim font-mono">
        <span>ID: {selectedFile.id}</span>
        <span>·</span>
        <span>MFT: {selectedFile.mft_ref || selectedFile.inode || '—'}</span>
        <span>·</span>
        <span>Status: {['Active','Deleted','Fragmented','Partial'][selectedFile.status]}</span>
        <span>·</span>
        <span>FS: {['Unknown','NTFS','EXT4','APFS','FAT32','RAW'][selectedFile.fs || 0]}</span>
      </div>
    </div>
  );
}

function ImagePreview({ src, zoom, onError, hasError }) {
  if (!src || hasError) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex flex-col items-center gap-3 text-text-dim"
      >
        <Image size={48} className="opacity-30" />
        <p className="text-sm">Preview not available</p>
        <p className="text-xs opacity-60">File may be in recovered output folder</p>
      </motion.div>
    );
  }
  return (
    <motion.img
      src={src}
      alt="preview"
      onError={onError}
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      style={{ zoom }}
      className="max-w-full max-h-full object-contain rounded-lg shadow-panel"
    />
  );
}

function VideoPreview({ src }) {
  if (!src) return <GenericIcon icon={<Film size={48} />} label="Video file" />;
  return (
    <video
      src={src}
      controls
      className="max-w-full max-h-full rounded-lg shadow-panel"
    />
  );
}

function AudioPreview({ src }) {
  if (!src) return <GenericIcon icon={<Music size={48} />} label="Audio file" />;
  return (
    <div className="flex flex-col items-center gap-4">
      <Music size={64} className="text-accent-green opacity-60" />
      <audio src={src} controls className="w-80" />
    </div>
  );
}

function GenericPreview({ file }) {
  const icons = { 4: FileText, 5: HardDrive };
  const Icon  = icons[file.type] || FileText;
  return (
    <div className="flex flex-col items-center gap-4 text-text-dim">
      <Icon size={64} className="opacity-30" />
      <div className="text-center">
        <p className="text-sm font-medium text-text-muted">{file.name}</p>
        <p className="text-xs mt-1">{formatSize(file.size)} · .{file.extension || '?'}</p>
      </div>
    </div>
  );
}

function GenericIcon({ icon, label }) {
  return (
    <div className="flex flex-col items-center gap-3 text-text-dim">
      <div className="opacity-30">{icon}</div>
      <p className="text-sm">{label}</p>
    </div>
  );
}

function IconBtn({ onClick, children, title }) {
  return (
    <button
      title={title}
      onClick={onClick}
      className="w-8 h-8 flex items-center justify-center rounded-lg
                 bg-surface-2 hover:bg-surface-border text-text-muted
                 hover:text-text transition-colors"
    >
      {children}
    </button>
  );
}

function formatSize(n) {
  if (!n) return '0 B';
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
  return (n / 1073741824).toFixed(2) + ' GB';
}

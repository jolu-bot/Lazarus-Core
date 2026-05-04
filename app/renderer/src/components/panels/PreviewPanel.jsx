import React, { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Download, Wand2, ZoomIn, ZoomOut, RotateCcw,
  Image, Film, FileText, Music, HardDrive, Sparkles,
  AlertCircle, CheckCircle2, ShieldCheck, Wrench,
  RefreshCcw, AlertTriangle, Activity, SplitSquareHorizontal, Archive
} from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
import clsx from 'clsx';

const lzr = window.lazarus;

function hColor(s){ return s>=85?'#22c55e':s>=70?'#eab308':s>=50?'#f97316':'#ef4444'; }
function fmtSz(n){ if(!n)return'0 B';if(n<1024)return n+' B';if(n<1048576)return(n/1024).toFixed(1)+' KB';if(n<1073741824)return(n/1048576).toFixed(1)+' MB';return(n/1073741824).toFixed(2)+' GB'; }

export default function PreviewPanel(){
  const { selectedFile,aiAvailable,repairResults,setRepairResult,setRepairedImage,addToast } = useAppStore();
  const [zoom,setZoom]               = useState(1);
  const [aiLoading,setAILoading]     = useState(false);
  const [recovering,setRecovering]   = useState(false);
  const [compareMode,setCompareMode] = useState(false);
  const [previewSrc,setPreviewSrc]   = useState(null);
  const [imgError,setImgError]       = useState(false);
  const [livePreview,setLivePreview]  = useState(null);
  const [liveLoading,setLiveLoading]  = useState(false);

  const repairResult = selectedFile ? repairResults[selectedFile.id] : null;

  useEffect(()=>{
    setZoom(1); setImgError(false); setCompareMode(false); setLivePreview(null);
    if(!selectedFile?.path){ setPreviewSrc(null); return; }
    if(selectedFile.type===1||selectedFile.type===2||selectedFile.type===3){
      setPreviewSrc(`file://${selectedFile.path}`);
    } else {
      setPreviewSrc(null);
      const p = selectedFile.path;
      if(p){
        setLiveLoading(true);
        lzr?.invoke('scan:preview-file', p, 65536).then(r=>{
          setLivePreview(r||null);
        }).catch(()=>{}).finally(()=>setLiveLoading(false));
      }
    }
  },[selectedFile]);

  const handleRecover = async()=>{
    if(!selectedFile)return;
    setRecovering(true);
    const dir = await lzr?.invoke('dialog:openFolder');
    if(!dir){ setRecovering(false); return; }
    const r = await lzr?.invoke('scan:recover','',selectedFile,dir);
    setRecovering(false);
    if(r?.success) addToast('Recovered: '+(r.outputPath||dir));
    else addToast('Recovery failed: '+(r?.message||'Unknown error'),'error');
  };

  const handleRepair = async(mode)=>{
    if(!selectedFile)return;
    setAILoading(true);
    const dir = await lzr?.invoke('dialog:openFolder').catch(()=>null);
    const r   = await lzr?.invoke('scan:repair-file',{ file:selectedFile, outputDir:dir, mode });
    setAILoading(false);
    if(r?.success){
      setRepairResult(selectedFile.id, r);
      if(r.image_b64){
        const src=`data:image/jpeg;base64,${r.image_b64}`;
        setRepairedImage(src);
        setPreviewSrc(src);
      }
    }
  };

  if(!selectedFile){
    return(
      <div className="flex-1 flex flex-col items-center justify-center bg-bg gap-4 text-text-dim">
        <div className="w-20 h-20 rounded-3xl bg-surface-2 flex items-center justify-center">
          <HardDrive size={36} className="text-text-dim"/>
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-text-muted">No file selected</p>
          <p className="text-xs text-text-dim mt-1">Select a file from the list to preview & analyze</p>
        </div>
      </div>
    );
  }

  const health   = repairResult?.health || selectedFile.health || {};
  const score    = health.score ?? Math.round((selectedFile.confidence||0)*100);
  const rm       = health.repairMode ?? 0;
  const repaired = !!repairResult?.repaired;

  return(
    <div className="flex flex-col flex-1 bg-bg overflow-hidden">

      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-surface-border bg-bg-2 flex-shrink-0">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-text truncate">{selectedFile.name}</h3>
          <div className="flex items-center gap-2 text-xs text-text-dim mt-0.5">
            <span>{fmtSz(selectedFile.size)}</span>
            <span>·</span><span className="font-mono">.{selectedFile.extension||'?'}</span>
            <span>·</span>
            <span className="font-mono" style={{color:hColor(score)}}>{score}% health</span>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {selectedFile.type===1&&(
            <>
              <IconBtn onClick={()=>setZoom(z=>Math.min(z+0.25,4))} title="Zoom in"><ZoomIn size={15}/></IconBtn>
              <IconBtn onClick={()=>setZoom(z=>Math.max(z-0.25,0.25))} title="Zoom out"><ZoomOut size={15}/></IconBtn>
              <IconBtn onClick={()=>setZoom(1)} title="Reset zoom"><RotateCcw size={14}/></IconBtn>
              {repaired&&(
                <IconBtn onClick={()=>setCompareMode(c=>!c)} title="Compare before/after">
                  <SplitSquareHorizontal size={15} className={compareMode?'text-primary':''}/>
                </IconBtn>
              )}
            </>
          )}
          <button onClick={handleRecover} disabled={recovering}
            className={clsx('flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all',
              recovering?'bg-primary/30 text-primary/60 cursor-wait':'bg-primary text-white hover:bg-primary-hover shadow-glow-sm')}>
            {recovering?<><Sparkles size={13} className="animate-spin"/>Saving...</>:<><Download size={13}/>Recover</>}
          </button>
        </div>
      </div>

      {/* File Health Analysis Panel */}
      <HealthPanel health={health} score={score} rm={rm} repaired={repaired}
        onRepair={handleRepair} aiLoading={aiLoading} selectedFile={selectedFile}
        aiAvailable={aiAvailable}/>

      {/* Repair result banner */}
      <AnimatePresence>
        {repairResult&&(
          <motion.div initial={{height:0,opacity:0}} animate={{height:'auto',opacity:1}} exit={{height:0,opacity:0}}
            className={clsx('flex items-center gap-2 px-4 py-1.5 text-xs flex-shrink-0',
              repairResult.success?'bg-accent-green/10 border-b border-accent-green/20 text-accent-green'
                                  :'bg-accent/10 border-b border-accent/20 text-accent')}>
            {repairResult.success
              ?<><CheckCircle2 size={13}/>Repair complete &mdash; health improved to {repairResult.health?.score??score}%</>
              :<><AlertCircle size={13}/>Repair partial &mdash; file may be severely fragmented</>}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Preview */}
      <div className="flex-1 overflow-auto flex items-center justify-center bg-[#080810] p-4">
        <AnimatePresence mode="wait">
          {selectedFile.type===1?(
            compareMode && repairResult?.image_b64?(
              <CompareView
                originalSrc={`file://${selectedFile.path}`}
                repairedSrc={`data:image/jpeg;base64,${repairResult.image_b64}`}
                key="compare"/>
            ):(
              <ImagePreview key={selectedFile.id} src={previewSrc} zoom={zoom}
                onError={()=>setImgError(true)} hasError={imgError}/>
            )
          ):selectedFile.type===2?(
            <VideoPreview key={selectedFile.id} src={previewSrc}/>
          ):selectedFile.type===3?(
            <AudioPreview key={selectedFile.id} src={previewSrc}/>
          ):(
            <GenericPreview key={selectedFile.id} file={selectedFile} livePreview={livePreview} loading={liveLoading}/>
          )}
        </AnimatePresence>
      </div>

      {/* Metadata footer */}
      <div className="flex items-center gap-4 px-4 py-2 border-t border-surface-border bg-bg-2 flex-shrink-0 text-xs text-text-dim font-mono">
        <span>ID: {selectedFile.id}</span><span>·</span>
        <span>MFT: {selectedFile.mft_ref||selectedFile.inode||'—'}</span><span>·</span>
        <span>Status: {['Active','Deleted','Fragmented','Partial'][selectedFile.status]}</span><span>·</span>
        <span>FS: {['Unknown','NTFS','EXT4','APFS','FAT32','RAW'][selectedFile.fs||0]}</span>
      </div>
    </div>
  );
}

// ─── Health Analysis Panel ────────────────────────────────────────
function HealthPanel({ health, score, rm, repaired, onRepair, aiLoading, selectedFile, aiAvailable }){
  const [open,setOpen] = useState(true);
  const rmLabel  = ['Excellent','Minor repair','Major repair','Reconstruct'][rm]||'';
  const rmColor  = rm===0?'text-accent-green':rm===1?'text-yellow-400':rm===2?'text-orange-400':'text-red-400';
  const RmIcon   = rm===0?ShieldCheck:rm===1?Wrench:rm===2?AlertTriangle:RefreshCcw;

  return(
    <div className="flex-shrink-0 border-b border-surface-border bg-bg-2">
      <button onClick={()=>setOpen(o=>!o)}
        className="w-full flex items-center gap-2 px-4 py-2 text-xs font-medium text-text-dim hover:text-text transition-colors">
        <Activity size={12} className="text-primary"/>
        <span>File Health Analysis</span>
        <div className="ml-auto flex items-center gap-2">
          <span style={{color:hColor(score)}} className="font-mono font-bold">{score}%</span>
          <span className={clsx('flex items-center gap-1',rmColor)}>
            <RmIcon size={11}/>{rmLabel}
          </span>
          <span className="text-text-dim">{open?'▲':'▼'}</span>
        </div>
      </button>

      <AnimatePresence>
        {open&&(
          <motion.div initial={{height:0,opacity:0}} animate={{height:'auto',opacity:1}} exit={{height:0,opacity:0}}
            className="overflow-hidden">
            <div className="px-4 pb-3 grid grid-cols-2 gap-3">

              {/* Score ring + label */}
              <div className="flex items-center gap-3">
                <ScoreRing score={score}/>
                <div>
                  <div className="text-xs font-semibold text-text">{health.label||rmLabel||'OK'}</div>
                  <div className="text-[11px] text-text-dim mt-0.5">
                    {health.existsOnDisk?'File still on disk':'File deleted/lost'}
                  </div>
                  <div className="text-[11px] text-text-dim">
                    {health.frags>1?`${health.frags} fragments detected`:'Contiguous'}
                  </div>
                </div>
              </div>

              {/* Integrity bars */}
              <div className="flex flex-col gap-1.5">
                <IntBar label="Header"    ok={health.headerOk}           value={health.headerOk?100:30}/>
                <IntBar label="Structure" value={health.structPct??score}/>
                <IntBar label="Data"      value={health.dataPct??score}/>
              </div>

              {/* Action buttons */}
              <div className="col-span-2 flex gap-2 pt-1">
                {repaired?(
                  <span className="flex items-center gap-1.5 text-xs text-accent-green">
                    <CheckCircle2 size={13}/> Already repaired — health improved
                  </span>
                ):(
                  <>
                    {rm>=1&&(
                      <ActionBtn onClick={()=>onRepair('minor')} loading={aiLoading}
                        icon={<Wrench size={12}/>} label="Repair" color="yellow"/>
                    )}
                    {rm>=2&&aiAvailable&&(
                      <ActionBtn onClick={()=>onRepair('major')} loading={aiLoading}
                        icon={<Wand2 size={12}/>} label="AI Repair" color="purple"/>
                    )}
                    {rm>=3&&(
                      <ActionBtn onClick={()=>onRepair('reconstruct')} loading={aiLoading}
                        icon={<RefreshCcw size={12}/>} label="Reconstruct" color="red"/>
                    )}
                    {rm===0&&(
                      <span className="flex items-center gap-1.5 text-xs text-accent-green">
                        <ShieldCheck size={13}/> File is in excellent condition
                      </span>
                    )}
                  </>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ScoreRing({ score }){
  const r=18, circ=2*Math.PI*r;
  const dash=circ*(score/100);
  return(
    <svg width={48} height={48} viewBox="0 0 48 48">
      <circle cx={24} cy={24} r={r} fill="none" stroke="#1e1e2e" strokeWidth={4}/>
      <circle cx={24} cy={24} r={r} fill="none" stroke={hColor(score)} strokeWidth={4}
        strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
        transform="rotate(-90 24 24)" style={{transition:'all 0.5s'}}/>
      <text x={24} y={24} textAnchor="middle" dominantBaseline="central"
        fill={hColor(score)} fontSize={11} fontWeight="bold">{score}</text>
    </svg>
  );
}

function IntBar({ label, value, ok }){
  const pct = ok!==undefined ? (ok?100:25) : (value??0);
  return(
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-text-dim w-16 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-surface-border overflow-hidden">
        <div className="h-full rounded-full" style={{width:`${pct}%`,background:hColor(pct),transition:'width 0.5s'}}/>
      </div>
      <span className="text-[10px] font-mono" style={{color:hColor(pct)}}>{pct}%</span>
    </div>
  );
}

function ActionBtn({ onClick, loading, icon, label, color }){
  const cls = color==='yellow'?'bg-yellow-500/20 text-yellow-300 hover:bg-yellow-500/30 border-yellow-500/30'
            : color==='purple'?'bg-purple-500/20 text-purple-300 hover:bg-purple-500/30 border-purple-500/30'
            : 'bg-red-500/20 text-red-300 hover:bg-red-500/30 border-red-500/30';
  return(
    <button onClick={onClick} disabled={loading}
      className={clsx('flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border transition-all',
        loading?'opacity-50 cursor-wait':cls)}>
      {loading?<Sparkles size={11} className="animate-spin"/>:icon}
      {label}
    </button>
  );
}

function CompareView({ originalSrc, repairedSrc }){
  return(
    <motion.div initial={{opacity:0}} animate={{opacity:1}}
      className="flex gap-3 w-full h-full items-center justify-center">
      <div className="flex-1 flex flex-col items-center gap-2">
        <span className="text-xs text-text-dim bg-surface px-2 py-0.5 rounded">Before (original)</span>
        <img src={originalSrc} alt="original"
          className="max-w-full max-h-full object-contain rounded-lg opacity-75" style={{filter:'contrast(0.9)'}}/>
      </div>
      <div className="w-px h-3/4 bg-surface-border"/>
      <div className="flex-1 flex flex-col items-center gap-2">
        <span className="text-xs text-accent-green bg-surface px-2 py-0.5 rounded">After (repaired)</span>
        <img src={repairedSrc} alt="repaired"
          className="max-w-full max-h-full object-contain rounded-lg ring-1 ring-accent-green/30"/>
      </div>
    </motion.div>
  );
}

function ImagePreview({ src, zoom, onError, hasError }){
  if(!src||hasError) return(
    <motion.div initial={{opacity:0}} animate={{opacity:1}} className="flex flex-col items-center gap-3 text-text-dim">
      <Image size={48} className="opacity-30"/><p className="text-sm">Preview not available</p>
      <p className="text-xs opacity-60">File will appear in the recovery output folder</p>
    </motion.div>
  );
  return(
    <motion.img src={src} alt="preview" onError={onError}
      initial={{opacity:0,scale:0.95}} animate={{opacity:1,scale:1}}
      style={{zoom}} className="max-w-full max-h-full object-contain rounded-lg shadow-panel"/>
  );
}

function VideoPreview({ src }){
  if(!src) return <GenericIcon icon={<Film size={48}/>} label="Video file"/>;
  return <video src={src} controls className="max-w-full max-h-full rounded-lg shadow-panel"/>;
}

function AudioPreview({ src }){
  if(!src) return <GenericIcon icon={<Music size={48}/>} label="Audio file"/>;
  return(<div className="flex flex-col items-center gap-4"><Music size={64} className="text-accent-green opacity-60"/><audio src={src} controls className="w-80"/></div>);
}

function GenericPreview({ file, livePreview, loading }){
  const Icon = file.type===4?FileText:file.type===5?Archive:HardDrive;
  if(loading){
    return(
      <div className="flex flex-col items-center gap-3 text-text-dim">
        <Sparkles size={32} className="animate-spin text-primary opacity-60"/>
        <p className="text-xs">Loading preview...</p>
      </div>
    );
  }
  if(livePreview?.success && livePreview.head_b64){
    if(livePreview.kind==='image'){
      return(
        <motion.img src={`data:image/jpeg;base64,${livePreview.head_b64}`} alt="preview"
          initial={{opacity:0}} animate={{opacity:1}}
          className="max-w-full max-h-full object-contain rounded-lg shadow-panel"/>
      );
    }
    // Hex dump for binary/document/archive
    const bytes = Uint8Array.from(atob(livePreview.head_b64), c=>c.charCodeAt(0));
    const lines = [];
    const ROW = 16;
    for(let i=0;i<Math.min(bytes.length,512);i+=ROW){
      const row = bytes.slice(i,i+ROW);
      const hex = Array.from(row).map(b=>b.toString(16).padStart(2,'0')).join(' ');
      const asc = Array.from(row).map(b=>(b>=32&&b<127)?String.fromCharCode(b):'.').join('');
      lines.push(`${i.toString(16).padStart(8,'0')}  ${hex.padEnd(ROW*3-1,' ')}  |${asc}|`);
    }
    return(
      <motion.div initial={{opacity:0}} animate={{opacity:1}}
        className="flex flex-col w-full h-full overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-1.5 border-b border-surface-border bg-surface-2 text-xs text-text-dim flex-shrink-0">
          <HardDrive size={11}/>
          <span>{livePreview.name}</span>
          <span>·</span>
          <span className="font-mono">{fmtSz(livePreview.size)}</span>
          <span>·</span>
          <span className="uppercase text-primary font-semibold">{livePreview.kind}</span>
        </div>
        <pre className="flex-1 overflow-auto text-[10px] font-mono text-green-400/80 p-4 leading-relaxed whitespace-pre bg-[#050508]">
          {lines.join('\n')}
          {livePreview.bytes < livePreview.size && `\n... (showing first ${fmtSz(livePreview.bytes)} of ${fmtSz(livePreview.size)})`}
        </pre>
      </motion.div>
    );
  }
  return(
    <div className="flex flex-col items-center gap-4 text-text-dim">
      <Icon size={64} className="opacity-30"/>
      <div className="text-center">
        <p className="text-sm font-medium text-text-muted">{file.name}</p>
        <p className="text-xs mt-1">{fmtSz(file.size)} · .{file.extension||'?'}</p>
        {livePreview && !livePreview.success && (
          <p className="text-xs text-accent/60 mt-1">Preview unavailable — file not yet recovered</p>
        )}
      </div>
    </div>
  );
}

function GenericIcon({ icon, label }){
  return(<div className="flex flex-col items-center gap-3 text-text-dim"><div className="opacity-30">{icon}</div><p className="text-sm">{label}</p></div>);
}

function IconBtn({ onClick, children, title }){
  return(
    <button title={title} onClick={onClick}
      className="w-8 h-8 flex items-center justify-center rounded-lg bg-surface-2 hover:bg-surface-border text-text-muted hover:text-text transition-colors">
      {children}
    </button>
  );
}
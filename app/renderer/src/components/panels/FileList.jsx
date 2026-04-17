import React, { useState, useRef, useCallback } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useAppStore }    from '../../stores/useAppStore';
import {
  Image, Film, Music, FileText, Archive, File,
  Search, CheckCircle2, Circle, Download, AlertTriangle,
  Wrench, RefreshCcw, ShieldCheck
} from 'lucide-react';
import clsx from 'clsx';

const TYPE_ICONS   = { 0:File,1:Image,2:Film,3:Music,4:FileText,5:Archive,6:File };
const TYPE_COLORS  = { 0:'text-text-dim',1:'text-blue-400',2:'text-purple-400',3:'text-green-400',4:'text-yellow-400',5:'text-orange-400',6:'text-text-dim' };
const ST_LABELS    = { 0:'Active',1:'Deleted',2:'Fragmented',3:'Partial' };
const ST_COLORS    = { 0:'text-accent-green',1:'text-accent',2:'text-yellow-400',3:'text-orange-400' };

function hColor(s){ return s>=85?'#22c55e':s>=70?'#eab308':s>=50?'#f97316':'#ef4444'; }
function fmtSz(n){ if(!n)return'0 B';if(n<1024)return n+' B';if(n<1048576)return(n/1024).toFixed(1)+' KB';if(n<1073741824)return(n/1048576).toFixed(1)+' MB';return(n/1073741824).toFixed(2)+' GB'; }

const FILTERS=[{id:'all',label:'All'},{id:'images',label:'Images'},{id:'videos',label:'Videos'},{id:'audio',label:'Audio'},{id:'documents',label:'Documents'},{id:'archives',label:'Archives'}];

export default function FileList(){
  const { filteredFiles,selectedFile,selectFile,filter,setFilter }=useAppStore();
  const [selected,setSelected]=useState(new Set());
  const parentRef=useRef(null);

  const rv=useVirtualizer({
    count:filteredFiles.length,
    getScrollElement:()=>parentRef.current,
    estimateSize:useCallback(()=>52,[]),
    overscan:10,
  });

  const toggle=(e,id)=>{ e.stopPropagation(); setSelected(s=>{ const n=new Set(s);n.has(id)?n.delete(id):n.add(id);return n; }); };

  const handleRecover=async()=>{
    const todo=filteredFiles.filter(f=>selected.has(f.id));
    if(!todo.length)return;
    const dir=await window.lazarus?.invoke('dialog:openFolder');
    if(!dir)return;
    let ok=0;
    for(const f of todo){ const r=await window.lazarus?.invoke('scan:recover','',f,dir); if(r?.success)ok++; }
    alert(`Recovery complete: ${ok}/${todo.length} file(s) saved to\n${dir}`);
    setSelected(new Set());
  };

  return(
    <div className="flex flex-col w-[480px] border-r border-surface-border flex-shrink-0 bg-bg">
      <div className="flex flex-col gap-2 px-3 py-2 border-b border-surface-border bg-bg-2">
        <div className="flex items-center gap-2 bg-surface rounded-lg px-3 py-1.5 border border-surface-border focus-within:border-primary/50 transition-colors">
          <Search size={13} className="text-text-dim"/>
          <input type="text" placeholder="Search files..." value={filter.search}
            onChange={e=>setFilter({search:e.target.value})}
            className="flex-1 bg-transparent text-sm text-text placeholder-text-dim outline-none"/>
        </div>
        <div className="flex gap-1 overflow-x-auto scrollbar-none">
          {FILTERS.map(f=>(
            <button key={f.id} onClick={()=>setFilter({type:f.id})}
              className={clsx('px-2.5 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition-all',
                filter.type===f.id?'bg-primary/20 text-primary border border-primary/30':'text-text-dim hover:text-text hover:bg-surface-2')}>
              {f.label}
            </button>
          ))}
          <button onClick={()=>setFilter({statusDeleted:!filter.statusDeleted})}
            className={clsx('ml-auto px-2.5 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition-all',
              filter.statusDeleted?'bg-accent/20 text-accent border border-accent/30':'text-text-dim hover:text-text hover:bg-surface-2')}>
            Deleted
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between px-3 py-1.5 border-b border-surface-border bg-bg-2 text-xs text-text-dim">
        <span>{filteredFiles.length.toLocaleString()} files found</span>
        {selected.size>0&&(
          <button onClick={handleRecover} className="flex items-center gap-1 text-primary hover:text-primary-hover font-medium transition-colors">
            <Download size={12}/> Recover {selected.size}
          </button>
        )}
      </div>

      <div ref={parentRef} className="flex-1 overflow-y-auto">
        {filteredFiles.length===0?(<EmptyState/>):(
          <div style={{height:rv.getTotalSize(),position:'relative'}}>
            {rv.getVirtualItems().map(vr=>{
              const f=filteredFiles[vr.index];
              const Icon=TYPE_ICONS[f.type]||File;
              const isSel=f===selectedFile,isChk=selected.has(f.id);
              const health=f.health||{};
              const score=health.score??Math.round((f.confidence||0)*100);
              const rm=health.repairMode??0;
              return(
                <div key={vr.key} ref={rv.measureElement}
                  style={{position:'absolute',top:vr.start,left:0,right:0}}
                  onClick={()=>selectFile(f)}
                  className={clsx('flex items-center gap-2.5 px-3 py-2 cursor-pointer transition-all border-b border-surface-border/30',
                    isSel?'bg-primary/10 border-l-2 border-l-primary':'hover:bg-surface-2/50')}>
                  <button onClick={e=>toggle(e,f.id)} className="flex-shrink-0 text-text-dim hover:text-primary transition-colors">
                    {isChk?<CheckCircle2 size={14} className="text-primary"/>:<Circle size={14}/>}
                  </button>
                  <Icon size={16} className={clsx('flex-shrink-0',TYPE_COLORS[f.type])}/>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-text truncate font-medium">{f.name}</div>
                    <div className="flex items-center gap-1.5 text-xs text-text-dim mt-0.5">
                      <span className={ST_COLORS[f.status]}>{ST_LABELS[f.status]}</span>
                      <span>·</span><span>{fmtSz(f.size)}</span>
                      {rm>0&&(<span className="flex items-center gap-0.5 ml-1">
                        {rm===1?<Wrench size={11} className="text-yellow-400"/>:rm===2?<AlertTriangle size={11} className="text-orange-400"/>:<RefreshCcw size={11} className="text-red-400"/>}
                        <span className={clsx('text-[10px]',rm===1?'text-yellow-400':rm===2?'text-orange-400':'text-red-400')}>{rm===1?'Minor':rm===2?'Major':'Rebuild'}</span>
                      </span>)}
                    </div>
                  </div>
                  <div className="flex-shrink-0 flex flex-col items-end gap-1">
                    <div className="flex items-center gap-1">
                      <span className="text-xs font-mono font-semibold" style={{color:hColor(score)}}>{score}%</span>
                      <span className="text-[10px] text-text-dim">.{f.extension||'?'}</span>
                    </div>
                    <div className="w-16 h-1.5 rounded-full bg-surface-border overflow-hidden">
                      <div className="h-full rounded-full" style={{width:`${score}%`,background:hColor(score)}}/>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState(){
  return(
    <div className="flex flex-col items-center justify-center h-full gap-4 text-text-dim p-8 text-center">
      <Search size={40} className="opacity-20"/>
      <div><p className="text-sm font-medium text-text-muted">No files found</p><p className="text-xs mt-1 opacity-60">Launch a scan to discover recoverable files</p></div>
    </div>
  );
}
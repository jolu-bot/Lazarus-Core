import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Boxes, KeyRound, Search, Binary, RefreshCw, AlertTriangle, CheckCircle2, ShieldAlert, Plus, Trash2, Play, StopCircle, Download, Unlock } from 'lucide-react';
import clsx from 'clsx';
import { useAppStore } from '../../stores/useAppStore';
import SourcePicker from '../ui/SourcePicker';
import { formatBytes } from '../../utils/formatters';

const lzr = window.lazarus;

function useL() {
  const lang = useAppStore((s) => s.language);
  return (fr, en) => (lang === 'en' ? en : fr);
}

export default function ToolsView() {
  const L = useL();
  const [tab, setTab] = useState('smart');
  const [hexTarget, setHexTarget] = useState(null);
  const tabs = [
    ['smart', Activity, L('Santé des disques', 'Disk health')],
    ['raid', Boxes, L('RAID virtuel', 'Virtual RAID')],
    ['bitlocker', KeyRound, 'BitLocker'],
    ['search', Search, L('Recherche de contenu', 'Content search')],
    ['hex', Binary, L('Explorateur hexadécimal', 'Hex explorer')],
  ];
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex gap-1 px-5 pt-4 border-b border-surface-border bg-bg-2 flex-shrink-0 overflow-x-auto">
        {tabs.map(([id, Icon, label]) => (
          <button key={id} onClick={() => setTab(id)}
            className={clsx('flex items-center gap-2 px-4 py-2 text-sm rounded-t-lg border-b-2 transition-colors whitespace-nowrap',
              tab === id ? 'border-primary text-primary bg-primary/10' : 'border-transparent text-text-dim hover:text-text')}>
            <Icon size={14} />{label}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-6">
        {tab === 'smart' && <SmartTab L={L} />}
        {tab === 'raid' && <RaidTab L={L} />}
        {tab === 'bitlocker' && <BitLockerTab L={L} />}
        {tab === 'search' && <SearchTab L={L} onHex={(t) => { setHexTarget(t); setTab('hex'); }} />}
        {tab === 'hex' && <HexTab L={L} target={hexTarget} />}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ S.M.A.R.T.
function SmartTab({ L }) {
  const [list, setList] = useState(null);
  const load = () => { setList(null); lzr?.invoke('tools:smart').then((r) => setList(Array.isArray(r) ? r : [])); };
  useEffect(load, []);
  const admin = useAppStore((s) => s.diag?.admin);
  const color = { ok: 'text-accent-green border-accent-green/30 bg-accent-green/10', warning: 'text-yellow-400 border-yellow-500/30 bg-yellow-500/10',
    critical: 'text-accent border-accent/40 bg-accent/10' };
  return (
    <div className="max-w-3xl">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-bold text-text">{L('Santé des disques (S.M.A.R.T.)', 'Disk health (S.M.A.R.T.)')}</h2>
        <button onClick={load} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-2 border border-surface-border text-text-dim hover:text-text text-xs"><RefreshCw size={12} />{L('Actualiser', 'Refresh')}</button>
      </div>
      <p className="text-sm text-text-muted mb-4">{L('Un disque qui montre des signes de fatigue doit être cloné avant toute récupération : chaque lecture l\'use davantage.',
        'A failing disk should be cloned before any recovery: every read wears it further.')}</p>
      {!admin && <div className="text-xs text-yellow-300 bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3 mb-4">{L('Sans droits administrateur, Windows masque la température, l\'usure et les erreurs : seul l\'état global est visible.',
        'Without administrator rights Windows hides temperature, wear and error counters: only the overall state is visible.')}</div>}
      {list === null && <p className="text-sm text-text-dim">…</p>}
      {list?.length === 0 && <p className="text-sm text-text-dim">{L('Aucune information disponible.', 'No information available.')}</p>}
      <div className="flex flex-col gap-3">
        {list?.map((d) => (
          <div key={d.path} className={clsx('rounded-xl border p-4', color[d.level])}>
            <div className="flex items-center gap-2 font-semibold text-text">
              {d.level === 'ok' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
              {d.name} <span className="text-xs text-text-dim font-normal">{d.media} {d.bus} · {formatBytes(d.size)}</span>
            </div>
            <div className="text-sm mt-1">{d.advice}</div>
            {d.reasons?.map((r) => <div key={r} className="text-xs mt-1">• {r}</div>)}
            {d.hasCounters && (
              <div className="text-xs text-text-dim font-mono mt-2 flex flex-wrap gap-x-4">
                {d.temp != null && <span>{d.temp} °C</span>}{d.wear != null && <span>{L('usure', 'wear')} {d.wear} %</span>}
                {d.hours != null && <span>{d.hours} h</span>}{d.readErr != null && <span>{L('erreurs lecture', 'read errors')} {d.readErr}</span>}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ RAID virtuel
function RaidTab({ L }) {
  const addCustomDrive = useAppStore((s) => s.addCustomDrive);
  const setView = useAppStore((s) => s.setView);
  const addToast = useAppStore((s) => s.addToast);
  const [members, setMembers] = useState([]);
  const [picker, setPicker] = useState(null);
  const [cfg, setCfg] = useState({ level: 'raid5', stripe: 65536, layout: 'ls', offsetMB: 0, order: '' });
  const [cands, setCands] = useState(null);
  const [busy, setBusy] = useState(false);

  const add = (d) => { if (d) { setMembers((m) => [...m, { path: d.path, label: d.label || d.path }]); setPicker(null); } };
  const spec = (c = cfg) => ({
    level: c.level, stripe: Number(c.stripe), layout: c.layout, offset: Math.round(Number(c.offsetMB || 0) * 1024 * 1024),
    order: c.order ? (Array.isArray(c.order) ? c.order : c.order.split(/[ ,;]+/).filter(Boolean).map(Number)) : undefined,
    members: members.map((m) => m.path),
  });
  const detect = async () => {
    setBusy(true); setCands(null);
    const r = await lzr?.invoke('tools:raid-detect', members.map((m) => m.path), 16);
    setBusy(false);
    if (r?.success) setCands(r.candidates || []);
    else addToast(r?.message || L('Détection impossible', 'Detection failed'), 'error', 8000);
  };
  const create = (c) => {
    const sp = spec(c);
    const n = members.length;
    const d = { path: 'raid:' + JSON.stringify(sp), kind: 'virtual', label: `RAID ${sp.level.replace('raid', '')} (${n} ${L('disques', 'disks')})`, model: 'RAID virtuel', interface: 'raid', totalSize: 0, fs: '' };
    addCustomDrive(d);
    addToast(L('Volume virtuel créé et sélectionné : lancez l\'analyse.', 'Virtual volume created and selected: start the scan.'), 'success');
    setView('scan');
  };
  return (
    <div className="max-w-3xl">
      <h2 className="text-lg font-bold text-text mb-2">{L('RAID virtuel', 'Virtual RAID')}</h2>
      <p className="text-sm text-text-muted mb-4">{L('Reconstruisez un RAID 0, 1, 5, 10 ou un volume agrégé à partir de ses disques (ou images) pour le récupérer comme un disque normal. Un disque manquant d\'un RAID 5 est reconstruit par parité.',
        'Rebuild a RAID 0/1/5/10 or spanned volume from its disks (or images) and recover it like a normal disk. One missing RAID 5 disk is rebuilt from parity.')}</p>
      <div className="flex flex-col gap-2 mb-3">
        {members.map((m, i) => (
          <div key={i} className="flex items-center gap-2 bg-surface-2 border border-surface-border rounded-lg px-3 py-2 text-sm">
            <span className="font-mono text-primary w-6">#{i}</span><span className="flex-1 truncate">{m.path ? m.label : L('(disque manquant)', '(missing disk)')}</span>
            <button onClick={() => setMembers((x) => x.filter((_, k) => k !== i))} className="text-text-dim hover:text-accent"><Trash2 size={14} /></button>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 mb-5">
        <SourcePicker value={picker} onChange={add} includeShadows={false} />
        <button onClick={() => setMembers((m) => [...m, { path: null, label: '' }])} className="flex items-center gap-1 px-3 py-2 rounded-lg border border-surface-border text-text-dim hover:text-text text-sm"><Plus size={13} />{L('Disque manquant', 'Missing disk')}</button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 text-sm">
        <label className="flex flex-col gap-1 text-text-dim">{L('Niveau', 'Level')}
          <select value={cfg.level} onChange={(e) => setCfg({ ...cfg, level: e.target.value })} className="bg-surface-2 border border-surface-border rounded-lg px-2 py-1.5 text-text">
            {['raid5', 'raid0', 'raid1', 'raid10', 'span'].map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}</select></label>
        <label className="flex flex-col gap-1 text-text-dim">{L('Taille de bande', 'Stripe size')}
          <select value={cfg.stripe} onChange={(e) => setCfg({ ...cfg, stripe: e.target.value })} className="bg-surface-2 border border-surface-border rounded-lg px-2 py-1.5 text-text">
            {[4, 8, 16, 32, 64, 128, 256, 512, 1024].map((k) => <option key={k} value={k * 1024}>{k} Ko</option>)}</select></label>
        <label className="flex flex-col gap-1 text-text-dim">{L('Parité (RAID 5)', 'Parity (RAID 5)')}
          <select value={cfg.layout} onChange={(e) => setCfg({ ...cfg, layout: e.target.value })} className="bg-surface-2 border border-surface-border rounded-lg px-2 py-1.5 text-text">
            <option value="ls">left-symmetric</option><option value="la">left-asymmetric</option><option value="rs">right-symmetric</option><option value="ra">right-asymmetric</option></select></label>
        <label className="flex flex-col gap-1 text-text-dim">{L('Décalage des données (Mo)', 'Data offset (MB)')}
          <input type="number" min="0" value={cfg.offsetMB} onChange={(e) => setCfg({ ...cfg, offsetMB: e.target.value })} className="bg-surface-2 border border-surface-border rounded-lg px-2 py-1.5 text-text" /></label>
        <label className="flex flex-col gap-1 text-text-dim col-span-2">{L('Ordre des disques (ex. 1,0,2)', 'Disk order (e.g. 1,0,2)')}
          <input value={cfg.order} onChange={(e) => setCfg({ ...cfg, order: e.target.value })} placeholder="0,1,2" className="bg-surface-2 border border-surface-border rounded-lg px-2 py-1.5 text-text" /></label>
      </div>
      <div className="flex gap-2 mb-5">
        <button onClick={detect} disabled={members.length < 2 || busy} className="px-4 py-2 rounded-lg bg-surface-2 border border-primary/40 text-primary text-sm hover:bg-primary/10 disabled:opacity-40">
          {busy ? L('Analyse des paramètres…', 'Detecting…') : L('Détecter automatiquement', 'Auto-detect parameters')}</button>
        <button onClick={() => create()} disabled={members.length < 2} className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary-hover disabled:opacity-40">{L('Créer le volume virtuel', 'Create virtual volume')}</button>
      </div>
      {cands && (
        <div className="border border-surface-border rounded-xl overflow-hidden">
          <div className="px-3 py-2 text-xs text-text-dim bg-surface-2">{cands.length ? L('Configurations vraisemblables (cliquez pour utiliser) :', 'Plausible configurations (click to use):') : L('Aucune configuration cohérente trouvée : vérifiez les disques ou renseignez les paramètres à la main.', 'No consistent configuration found.')}</div>
          {cands.slice(0, 12).map((c, i) => (
            <button key={i} onClick={() => create(c)} className="w-full flex items-center gap-4 px-3 py-2 text-xs font-mono text-left hover:bg-primary/10 border-t border-surface-border/50">
              <span className="uppercase text-primary w-14">{c.level}</span><span>{c.stripe / 1024} Ko</span><span>{c.layout}</span><span>{L('ordre', 'order')} [{c.order.join(',')}]</span><span>{L('décalage', 'offset')} {c.offset / 1048576} Mo</span><span className="ml-auto text-text-dim">score {c.score}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ BitLocker
function BitLockerTab({ L }) {
  const addCustomDrive = useAppStore((s) => s.addCustomDrive);
  const setView = useAppStore((s) => s.setView);
  const addToast = useAppStore((s) => s.addToast);
  const [src, setSrc] = useState(null);
  const [parts, setParts] = useState([]);
  const [sel, setSel] = useState(null);
  const [info, setInfo] = useState(null);
  const [key, setKey] = useState('');
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const pick = async (d) => {
    setSrc(d); setParts([]); setSel(null); setInfo(null); setErr('');
    const r = await lzr?.invoke('tools:partitions', d.path);
    const list = (r?.partitions || []).filter((p) => p.fs === 'bitlocker' || p.encrypted);
    if (list.length) { setParts(list); choose(d, list[0]); }
    else {
      const p0 = await lzr?.invoke('tools:bitlocker-probe', d.path, 0);   // volume (ou image) directement chiffré
      if (p0?.bitlocker) { const whole = { start: 0, size: d.totalSize || 0, desc: L('Volume complet', 'Whole volume') }; setParts([whole]); choose(d, whole); }
      else setErr(L('Aucune partition BitLocker détectée sur cette source.', 'No BitLocker partition detected on this source.'));
    }
  };
  const choose = async (d, p) => { setSel(p); setInfo(null); setInfo(await lzr?.invoke('tools:bitlocker-probe', d.path, p.start)); };
  const unlock = async () => {
    setBusy(true); setErr('');
    const spec = { inner: src.path, start: sel.start, size: sel.size || undefined, recoveryPassword: key.trim() || undefined, password: pw || undefined };
    const path = 'bitlocker:' + JSON.stringify(spec);
    const t = await lzr?.invoke('tools:hex', path, 0, 512);       // vérifie la clé en déchiffrant le premier secteur
    setBusy(false);
    if (!t?.success) { setErr((t?.error || t?.message || L('Clé refusée', 'Key rejected')).replace(/^.*DeviceError:\s*/, '')); return; }
    const sig = atob(t.data_b64).slice(3, 11);
    if (!/NTFS|EXFAT|MSDOS|MSWIN/i.test(sig)) { setErr(L('Déchiffrement effectué mais le contenu n\'est pas un système de fichiers reconnu (clé du mauvais volume ?).', 'Decrypted but the content is not a recognised file system.')); return; }
    addCustomDrive({ path, kind: 'virtual', label: `${src.label || src.path} — ${L('BitLocker déverrouillé', 'BitLocker unlocked')}`, model: 'BitLocker', interface: 'bitlocker', totalSize: sel.size || 0, fs: sig.trim() });
    addToast(L('Volume déverrouillé : il est sélectionné pour l\'analyse.', 'Volume unlocked and selected for scanning.'), 'success');
    setView('scan');
  };
  return (
    <div className="max-w-2xl">
      <h2 className="text-lg font-bold text-text mb-2">{L('Déverrouiller un volume BitLocker', 'Unlock a BitLocker volume')}</h2>
      <p className="text-sm text-text-muted mb-4">{L('Si le disque est celui de Windows en cours d\'exécution, choisissez plutôt le VOLUME (C:) : Windows le déchiffre déjà. Pour un disque retiré, un autre PC ou une image, fournissez la clé de récupération (48 chiffres) ou le mot de passe. Le déchiffrement se fait à la volée, en lecture seule.',
        'If this is the running Windows disk, pick the VOLUME (C:) instead: Windows already decrypts it. For a removed disk, another PC or an image, supply the 48-digit recovery key or the password. Decryption is on-the-fly and read-only.')}</p>
      <SourcePicker value={src} onChange={pick} includeShadows={false} />
      {err && <div className="mt-4 flex gap-2 text-sm text-accent bg-accent/10 border border-accent/30 rounded-lg p-3"><ShieldAlert size={16} className="flex-shrink-0" />{err}</div>}
      {sel && (
        <div className="mt-5 flex flex-col gap-3">
          {parts.length > 1 && <select onChange={(e) => choose(src, parts[Number(e.target.value)])} className="bg-surface-2 border border-surface-border rounded-lg px-2 py-1.5 text-text text-sm">
            {parts.map((p, i) => <option key={i} value={i}>{p.desc || 'Partition'} — {formatBytes(p.size)}</option>)}</select>}
          {info && (
            <div className="text-xs font-mono bg-surface-2 border border-surface-border rounded-lg p-3 text-text-muted">
              {L('Méthode', 'Method')} : {info.method} {info.supported === false && <span className="text-accent">({L('non prise en charge', 'unsupported')})</span>}<br />
              {L('Protecteurs', 'Protectors')} : {(info.protectors || []).map((p) => p.type).join(', ') || '—'}
            </div>
          )}
          <label className="flex flex-col gap-1 text-sm text-text-dim">{L('Clé de récupération (8 groupes de 6 chiffres)', 'Recovery key (8 groups of 6 digits)')}
            <input value={key} onChange={(e) => setKey(e.target.value)} placeholder="123456-123456-123456-123456-123456-123456-123456-123456" className="bg-surface-2 border border-surface-border rounded-lg px-3 py-2 text-text font-mono text-xs" /></label>
          <label className="flex flex-col gap-1 text-sm text-text-dim">{L('… ou mot de passe BitLocker', '… or BitLocker password')}
            <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} className="bg-surface-2 border border-surface-border rounded-lg px-3 py-2 text-text text-sm" /></label>
          <button onClick={unlock} disabled={busy || (!key.trim() && !pw)} className="self-start flex items-center gap-2 px-5 py-2.5 rounded-lg bg-primary text-white font-semibold text-sm hover:bg-primary-hover disabled:opacity-40">
            <Unlock size={15} />{busy ? L('Dérivation de la clé (quelques secondes)…', 'Deriving key (a few seconds)…') : L('Déverrouiller', 'Unlock')}</button>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ Recherche de contenu
function decodeSnippet(h) {
  try {
    const bin = atob(h.snippet_b64);
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    let txt;
    if (h.enc === 'utf16') {
      const start = (h.offset - h.snippet_start) % 2 ? 1 : 0;
      txt = new TextDecoder('utf-16le').decode(bytes.slice(start));
    } else txt = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
    return txt.replace(/[\u0000-\u001f]+/g, ' ');
  } catch { return ''; }
}

function SearchTab({ L, onHex }) {
  const addToast = useAppStore((s) => s.addToast);
  const [src, setSrc] = useState(null);
  const [text, setText] = useState('');
  const [hex, setHex] = useState('');
  const [enc, setEnc] = useState({ utf8: true, utf16: true, ascii: false });
  const [hits, setHits] = useState([]);
  const [prog, setProg] = useState(null);
  const [running, setRunning] = useState(false);
  const [res, setRes] = useState(null);
  useEffect(() => {
    const a = lzr?.on('search:hits', (b) => setHits((h) => [...h, ...b].slice(0, 5000)));
    const p = lzr?.on('search:progress', (d) => setProg(d));
    return () => { a && a(); p && p(); };
  }, []);
  const start = async () => {
    setHits([]); setRes(null); setRunning(true); setProg(null);
    const r = await lzr?.invoke('tools:search-start', { device: src.path, text: hex ? '' : text, hex, encodings: Object.keys(enc).filter((k) => enc[k]), nocase: true });
    setRunning(false); setRes(r);
    if (!r?.success) addToast(r?.message || r?.error || 'Erreur', 'error', 8000);
  };
  const exportHit = async (h) => {
    const dest = await lzr?.invoke('dialog:saveFile', `extrait_${h.offset}.bin`);
    if (!dest) return;
    const start0 = Math.max(0, h.offset - (h.offset % 512));
    const r = await lzr?.invoke('tools:export-range', src.path, start0, 256 * 1024, dest);
    addToast(r?.success ? `${formatBytes(r.bytes)} → ${dest}` : (r?.message || 'Erreur'), r?.success ? 'success' : 'error');
  };
  return (
    <div className="max-w-4xl">
      <h2 className="text-lg font-bold text-text mb-2">{L('Recherche de contenu', 'Content search')}</h2>
      <p className="text-sm text-text-muted mb-4">{L('Retrouvez un document dont vous vous rappelez un passage (nom, phrase, numéro) : le support entier est parcouru, y compris l\'espace libre et supprimé. Idéal pour les textes, e-mails, notes et documents que le carving par signature ne peut pas reconnaître.',
        'Find a document by a phrase you remember: the whole medium is scanned, including free and deleted space. Ideal for text, e-mails and notes that signature carving cannot recognise.')}</p>
      <div className="flex flex-wrap items-end gap-3 mb-3">
        <SourcePicker value={src} onChange={setSrc} includeShadows={false} disabled={running} />
        <label className="flex-1 min-w-[220px] flex flex-col gap-1 text-xs text-text-dim">{L('Texte à chercher', 'Text to find')}
          <input value={text} onChange={(e) => setText(e.target.value)} className="bg-surface-2 border border-surface-border rounded-lg px-3 py-2 text-text text-sm" /></label>
        <label className="w-56 flex flex-col gap-1 text-xs text-text-dim">{L('ou séquence hexadécimale', 'or hex sequence')}
          <input value={hex} onChange={(e) => setHex(e.target.value)} placeholder="ff d8 ff e1" className="bg-surface-2 border border-surface-border rounded-lg px-3 py-2 text-text text-sm font-mono" /></label>
      </div>
      <div className="flex items-center gap-4 mb-4 text-sm text-text-muted">
        {['utf8', 'utf16', 'ascii'].map((k) => (
          <label key={k} className="flex items-center gap-1.5"><input type="checkbox" checked={enc[k]} onChange={(e) => setEnc({ ...enc, [k]: e.target.checked })} className="accent-primary" />{k.toUpperCase()}</label>))}
        <div className="flex-1" />
        {!running ? <button onClick={start} disabled={!src || (!text && !hex)} className="flex items-center gap-2 px-5 py-2 rounded-lg bg-primary text-white font-semibold text-sm disabled:opacity-40"><Play size={14} />{L('Rechercher', 'Search')}</button>
          : <button onClick={() => lzr?.invoke('tools:search-stop')} className="flex items-center gap-2 px-5 py-2 rounded-lg bg-red-500/20 border border-red-500/40 text-accent text-sm font-semibold"><StopCircle size={14} />{L('Arrêter', 'Stop')}</button>}
      </div>
      {running && prog && <div className="text-xs text-text-dim font-mono mb-3">{prog.percent} % · {prog.currentPath} · {hits.length} {L('occurrence(s)', 'hit(s)')}</div>}
      {res?.success && !running && <div className="text-xs text-text-dim mb-3">{res.hits} {L('occurrence(s)', 'hit(s)')}{res.truncated ? L(' (limité)', ' (truncated)') : ''}</div>}
      <div className="border border-surface-border rounded-xl divide-y divide-surface-border/50 max-h-[55vh] overflow-y-auto">
        {hits.map((h, i) => (
          <div key={i} className="px-3 py-2 text-xs">
            <div className="flex items-center gap-3 font-mono text-text-dim">
              <span className="text-primary">0x{h.offset.toString(16)}</span><span>{formatBytes(h.offset)}</span><span className="uppercase">{h.enc}</span><div className="flex-1" />
              <button onClick={() => onHex({ device: src, offset: h.offset })} className="text-primary hover:underline">{L('Voir en hexa', 'View hex')}</button>
              <button onClick={() => exportHit(h)} className="text-primary hover:underline flex items-center gap-1"><Download size={11} />{L('Extraire 256 Ko', 'Extract 256 KB')}</button>
            </div>
            <div className="mt-1 text-text break-words">{decodeSnippet(h)}</div>
          </div>
        ))}
        {!hits.length && <div className="p-4 text-sm text-text-dim">{running ? '…' : L('Aucun résultat pour l\'instant.', 'No results yet.')}</div>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Explorateur hexadécimal
function HexTab({ L, target }) {
  const [src, setSrc] = useState(target?.device || null);
  const [offset, setOffset] = useState(target?.offset ?? 0);
  const [input, setInput] = useState(String(target?.offset ?? 0));
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const PAGE = 4096;
  const load = async (off) => {
    if (!src) return;
    const o = Math.max(0, off - (off % 16));
    const r = await lzr?.invoke('tools:hex', src.path, o, PAGE);
    if (r?.success) { setData({ ...r, bytes: Uint8Array.from(atob(r.data_b64), (c) => c.charCodeAt(0)) }); setOffset(o); setInput(String(o)); setErr(''); }
    else setErr((r?.error || r?.message || 'Erreur').replace(/^.*DeviceError:\s*/, ''));
  };
  useEffect(() => { if (src) load(offset); }, [src]); // eslint-disable-line react-hooks/exhaustive-deps
  const parse = (s) => { const t = s.trim().toLowerCase(); if (t.startsWith('s')) return parseInt(t.slice(1), 10) * (data?.sectorSize || 512); return t.startsWith('0x') ? parseInt(t, 16) : parseInt(t, 10); };
  const lines = useMemo(() => {
    if (!data) return [];
    const out = [];
    for (let i = 0; i < data.bytes.length; i += 16) {
      const row = data.bytes.slice(i, i + 16);
      let hex = ''; let asc = '';
      row.forEach((b) => { hex += b.toString(16).padStart(2, '0') + ' '; asc += b >= 32 && b < 127 ? String.fromCharCode(b) : '.'; });
      out.push(`${(offset + i).toString(16).padStart(12, '0')}  ${hex.padEnd(48, ' ')} ${asc}`);
    }
    return out;
  }, [data, offset]);
  return (
    <div className="max-w-5xl">
      <h2 className="text-lg font-bold text-text mb-4">{L('Explorateur hexadécimal (lecture seule)', 'Hex explorer (read-only)')}</h2>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <SourcePicker value={src} onChange={setSrc} includeShadows={false} />
        <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && load(parse(input))}
          placeholder="0x1F400 | 128000 | s250" className="w-48 bg-surface-2 border border-surface-border rounded-lg px-3 py-2 text-sm font-mono text-text" />
        <button onClick={() => load(parse(input))} className="px-3 py-2 rounded-lg bg-primary text-white text-sm">{L('Aller', 'Go')}</button>
        <button onClick={() => load(offset - PAGE)} className="px-3 py-2 rounded-lg border border-surface-border text-text-dim hover:text-text text-sm">◀</button>
        <button onClick={() => load(offset + PAGE)} className="px-3 py-2 rounded-lg border border-surface-border text-text-dim hover:text-text text-sm">▶</button>
        {data?.size ? <span className="text-xs text-text-dim font-mono">{formatBytes(data.size)} · {L('secteur', 'sector')} {Math.floor(offset / (data.sectorSize || 512))}</span> : null}
      </div>
      {err && <div className="text-sm text-accent mb-2">{err}</div>}
      <pre className="bg-[#050508] text-green-400/80 text-[11px] font-mono leading-relaxed p-4 rounded-xl overflow-auto max-h-[65vh] select-text">{lines.join('\n') || '—'}</pre>
    </div>
  );
}

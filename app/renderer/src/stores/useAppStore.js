import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';

export const FileType = { UNKNOWN: 0, IMAGE: 1, VIDEO: 2, AUDIO: 3, DOCUMENT: 4, ARCHIVE: 5, OTHER: 6 };
export const FileStatus = { ACTIVE: 0, DELETED: 1, FRAGMENTED: 2, PARTIAL: 3 };

const FULL_FEATURES = { scan: true, recover: true, aiRepair: true, videoRecovery: true, forensic: true };
const DEFAULT_LICENSE = { valid: true, plan: 3, tier: 'Business - Local Edition', features: FULL_FEATURES, freeMode: true };

/**
 * Les fichiers trouvés vivent hors de l'état React (tableaux mutables) : une analyse peut produire des
 * centaines de milliers d'éléments, et recopier un tableau à chaque lot serait quadratique.
 * L'état ne porte que des compteurs de version pour déclencher les rendus.
 */
export const fileDb = {
  files: [],            // tous les éléments
  filtered: [],         // éléments visibles (filtre + tri)
  byId: new Map(),
  selected: new Set(),  // ids sélectionnés
  selectedBytes: 0,
  overflow: 0,          // éléments non affichés au-delà de MAX_ITEMS (restent dans la session enregistrée)
};
export const MAX_ITEMS = 750000;

export const DEFAULT_FILTER = { type: 'all', source: 'all', search: '', statusDeleted: false, minHealth: 0, ext: '', minSize: 0, maxSize: 0 };
const TYPE_MAP = { images: 1, videos: 2, audio: 3, documents: 4, archives: 5 };

function isDefaultFilter(f) {
  return f.type === 'all' && f.source === 'all' && !f.search && !f.statusDeleted && !f.minHealth && !f.ext && !f.minSize && !f.maxSize;
}

function matches(f, filter, q, extN) {
  if (filter.type !== 'all' && f.type !== TYPE_MAP[filter.type]) return false;
  if (filter.statusDeleted && !(f.deleted || f.status === 1 || f.status === 3)) return false;
  if (filter.source !== 'all' && (f.source || 'unknown') !== filter.source) return false;
  if (q) {
    if (!((f.name || '').toLowerCase().includes(q) || (f.path || '').toLowerCase().includes(q))) return false;
  }
  if (filter.minHealth > 0 && (f.health?.score ?? 100) < filter.minHealth) return false;
  if (extN && (f.extension || '').toLowerCase() !== extN) return false;
  if (filter.minSize > 0 && (f.size || 0) < filter.minSize) return false;
  if (filter.maxSize > 0 && (f.size || 0) > filter.maxSize) return false;
  return true;
}

const SORTERS = {
  found: null,
  name: (a, b) => (a.name || '').localeCompare(b.name || ''),
  size: (a, b) => (a.size || 0) - (b.size || 0),
  health: (a, b) => (a.health?.score ?? 0) - (b.health?.score ?? 0),
  path: (a, b) => (a.path || '').localeCompare(b.path || ''),
};

function applySort(sortKey, sortDir) {
  const fn = SORTERS[sortKey];
  if (!fn) {
    fileDb.filtered.sort((a, b) => a.id - b.id);
  } else {
    const dir = sortDir === 'desc' ? -1 : 1;
    fileDb.filtered.sort((a, b) => dir * fn(a, b));
  }
}

function recompute(filter, sortKey, sortDir) {
  const q = (filter.search || '').toLowerCase();
  const extN = (filter.ext || '').toLowerCase().replace(/^\./, '');
  fileDb.filtered = isDefaultFilter(filter) ? fileDb.files.slice() : fileDb.files.filter((f) => matches(f, filter, q, extN));
  if (sortKey !== 'found') applySort(sortKey, sortDir);
}

const initialLang = (() => { try { return localStorage.getItem('lz.lang') || 'fr'; } catch { return 'fr'; } })();
const initialTheme = (() => { try { return localStorage.getItem('lz.theme') || 'dark'; } catch { return 'dark'; } })();

export const useAppStore = create(
  subscribeWithSelector((set, get) => ({
    language: initialLang,
    setLanguage: (l) => { try { localStorage.setItem('lz.lang', l); } catch { /* ignore */ } set({ language: l }); },

    diag: null,
    setDiag: (diag) => set({ diag }),

    drives: [],
    selectedDrive: null,
    setDrives: (drives) => set((s) => {
      const list = Array.isArray(drives) ? drives : [];
      const custom = s.drives.filter((d) => d.kind === 'image');
      const merged = [...list, ...custom.filter((c) => !list.some((d) => d.path === c.path))];
      const sel = s.selectedDrive && merged.find((d) => d.path === s.selectedDrive.path);
      return { drives: merged, selectedDrive: sel || s.selectedDrive };
    }),
    addCustomDrive: (d) => set((s) => ({ drives: [...s.drives.filter((x) => x.path !== d.path), d], selectedDrive: d })),
    selectDrive: (drive) => set({ selectedDrive: drive }),

    scanState: 'idle',   // idle | scanning | stopping | done | stopped | error
    progress: { percent: 0, filesFound: 0, currentPath: '' },
    layout: null,
    warnings: [],
    sessionId: null,
    scanResult: null,
    scanOptions: { scanNTFS: true, scanFAT: true, scanEXT4: true, enableCarving: false, carveAll: false, carveText: false, deepScan: false, includeExisting: false,
      carveCats: ['images', 'video', 'audio', 'documents', 'archives'], customSignatures: '' },
    setScanState: (s) => set({ scanState: s }),
    setProgress: (p) => set((s) => ({ progress: { ...s.progress, ...p } })),
    setLayout: (l) => set({ layout: l }),
    addWarning: (w) => set((s) => ({ warnings: [...s.warnings.filter((x) => x !== w), w] })),
    clearWarnings: () => set({ warnings: [] }),
    setSessionId: (id) => set({ sessionId: id }),
    setScanResult: (r) => set({ scanResult: r }),
    setScanOptions: (opts) => set((s) => ({ scanOptions: { ...s.scanOptions, ...opts } })),

    // ----- fichiers
    filesVersion: 0,
    totalCount: 0,
    overflowCount: 0,
    filteredCount: 0,
    selectionCount: 0,
    selectionBytes: 0,
    filter: { ...DEFAULT_FILTER },
    sortKey: 'found',
    sortDir: 'asc',

    addFiles: (batch) => {
      if (!batch || !batch.length) return;
      const { filter, sortKey, sortDir } = get();
      const q = (filter.search || '').toLowerCase();
      const extN = (filter.ext || '').toLowerCase().replace(/^\./, '');
      const dflt = isDefaultFilter(filter);
      for (const f of batch) {
        if (fileDb.byId.has(f.id)) continue;
        if (fileDb.files.length >= MAX_ITEMS) { fileDb.overflow++; continue; }
        fileDb.byId.set(f.id, f);
        fileDb.files.push(f);
        if (dflt || matches(f, filter, q, extN)) fileDb.filtered.push(f);
      }
      if (sortKey !== 'found' && fileDb.filtered.length < 200000) applySort(sortKey, sortDir);
      set((s) => ({ filesVersion: s.filesVersion + 1, totalCount: fileDb.files.length, filteredCount: fileDb.filtered.length, overflowCount: fileDb.overflow }));
    },
    clearFiles: () => {
      fileDb.files = []; fileDb.filtered = []; fileDb.byId = new Map(); fileDb.selected = new Set(); fileDb.selectedBytes = 0; fileDb.overflow = 0;
      set((s) => ({ overflowCount: 0, filesVersion: s.filesVersion + 1, totalCount: 0, filteredCount: 0, selectedFile: null, selectionCount: 0, selectionBytes: 0 }));
    },
    setFilter: (f) => {
      const filter = { ...get().filter, ...f };
      const { sortKey, sortDir } = get();
      recompute(filter, sortKey, sortDir);
      set((s) => ({ filter, filesVersion: s.filesVersion + 1, filteredCount: fileDb.filtered.length }));
    },
    setSort: (sortKey, sortDir) => {
      const { filter } = get();
      recompute(filter, sortKey, sortDir);
      set((s) => ({ sortKey, sortDir, filesVersion: s.filesVersion + 1 }));
    },

    selectedFile: null,
    selectFile: (file) => set({ selectedFile: file }),

    toggleSelect: (id) => {
      const f = fileDb.byId.get(id);
      if (!f) return;
      if (fileDb.selected.has(id)) { fileDb.selected.delete(id); fileDb.selectedBytes -= f.size || 0; }
      else { fileDb.selected.add(id); fileDb.selectedBytes += f.size || 0; }
      set({ selectionCount: fileDb.selected.size, selectionBytes: fileDb.selectedBytes });
    },
    selectRange: (fromIdx, toIdx) => {
      const [a, b] = fromIdx < toIdx ? [fromIdx, toIdx] : [toIdx, fromIdx];
      for (let i = a; i <= b && i < fileDb.filtered.length; i++) {
        const f = fileDb.filtered[i];
        if (!fileDb.selected.has(f.id)) { fileDb.selected.add(f.id); fileDb.selectedBytes += f.size || 0; }
      }
      set({ selectionCount: fileDb.selected.size, selectionBytes: fileDb.selectedBytes });
    },
    selectAllFiltered: () => {
      for (const f of fileDb.filtered) {
        if (!fileDb.selected.has(f.id)) { fileDb.selected.add(f.id); fileDb.selectedBytes += f.size || 0; }
      }
      set((s) => ({ selectionCount: fileDb.selected.size, selectionBytes: fileDb.selectedBytes, filesVersion: s.filesVersion + 1 }));
    },
    clearSelection: () => {
      fileDb.selected = new Set(); fileDb.selectedBytes = 0;
      set((s) => ({ selectionCount: 0, selectionBytes: 0, filesVersion: s.filesVersion + 1 }));
    },

    license: DEFAULT_LICENSE,
    setLicense: (lic) => set({ license: lic }),

    view: 'scan',
    setView: (v) => set({ view: v }),

    aiAvailable: false,
    setAIAvailable: (v) => set({ aiAvailable: v }),

    repairResults: {},
    setRepairResult: (fileId, result) => set((s) => ({ repairResults: { ...s.repairResults, [fileId]: result } })),
    repairedImage: null,
    setRepairedImage: (img) => set({ repairedImage: img }),

    toasts: [],
    addToast: (msg, tp, duration) => set((s) => ({ toasts: [...s.toasts, { id: Date.now() + Math.random(), msg, type: tp || 'success', duration }] })),
    removeToast: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),

    outputDir: '',
    setOutputDir: (d) => set({ outputDir: d }),

    // ----- récupération (fenêtre modale)
    recovery: { open: false, phase: 'idle', dest: '', blocked: null, progress: null, result: null, ids: [], structure: true, verify: true },
    setRecovery: (patch) => set((s) => ({ recovery: { ...s.recovery, ...patch } })),
    resetRecovery: () => set({ recovery: { open: false, phase: 'idle', dest: '', blocked: null, progress: null, result: null, ids: [], structure: true, verify: true } }),

    settings: { outputDir: '' },
    setSettings: (sv) => set((prev) => ({ settings: { ...prev.settings, ...sv } })),

    scanStartTime: null,
    setScanStartTime: (ti) => set({ scanStartTime: ti }),

    scanHistory: [],
    loadScanHistory: async () => {
      const h = await window.lazarus?.invoke('history:get');
      if (h) set({ scanHistory: h });
    },
    clearScanHistory: async () => {
      await window.lazarus?.invoke('history:clear');
      set({ scanHistory: [] });
    },

    theme: initialTheme,
    setTheme: (t) => {
      try { localStorage.setItem('lz.theme', t); } catch { /* ignore */ }
      set({ theme: t });
      document.documentElement.classList.toggle('dark', t === 'dark');
      document.documentElement.classList.toggle('light', t !== 'dark');
    },
  }))
);

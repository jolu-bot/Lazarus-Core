import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';

export const FileType = { UNKNOWN: 0, IMAGE: 1, VIDEO: 2, AUDIO: 3, DOCUMENT: 4, ARCHIVE: 5, OTHER: 6 };
export const FileStatus = { ACTIVE: 0, DELETED: 1, FRAGMENTED: 2, PARTIAL: 3 };

const FULL_FEATURES = { scan: true, recover: true, aiRepair: true, videoRecovery: true, forensic: true };
const DEFAULT_LICENSE = { valid: true, plan: 3, tier: 'Business - Local Edition', features: FULL_FEATURES, freeMode: true };

export const useAppStore = create(
  subscribeWithSelector((set, get) => ({
    drives: [],
    selectedDrive: null,
    setDrives: (drives) => set({ drives }),
    selectDrive: (drive) => set({ selectedDrive: drive }),

    scanState: 'idle',
    progress: { percent: 0, filesFound: 0, filesRecoverable: 0, currentPath: '' },
    files: [],
    filteredFiles: [],
    scanOptions: { scanNTFS: true, scanEXT4: true, scanAPFS: true, enableCarving: true, deepScan: false },
    setScanState: (s) => set({ scanState: s }),
    setProgress: (p) => set({ progress: p }),
    setScanOptions: (opts) => set((s) => ({ scanOptions: { ...s.scanOptions, ...opts } })),

    addFile: (file) => set((s) => {
      const files = [...s.files, file];
      return { files, filteredFiles: applyFilter(files, s.filter) };
    }),
    clearFiles: () => set({ files: [], filteredFiles: [] }),

    filter: { type: 'all', source: 'all', search: '', statusDeleted: false, minHealth: 0, ext: '', minSize: 0, maxSize: 0 },
    setFilter: (f) => set((s) => {
      const filter = { ...s.filter, ...f };
      return { filter, filteredFiles: applyFilter(s.files, filter) };
    }),

    selectedFile: null,
    selectFile: (file) => set({ selectedFile: file }),

    license: DEFAULT_LICENSE,
    setLicense: (lic) => set({ license: lic }),

    view: 'scan',
    setView: (v) => set({ view: v }),

    aiAvailable: false,
    setAIAvailable: (v) => set({ aiAvailable: v }),

    repairResults: {},
    setRepairResult: (fileId, result) =>
      set((s) => ({ repairResults: { ...s.repairResults, [fileId]: result } })),

    repairedImage: null,
    setRepairedImage: (img) => set({ repairedImage: img }),

    toasts: [],
    addToast: (msg, tp) =>
      set((s) => ({ toasts: [...s.toasts, { id: Date.now() + Math.random(), msg, type: tp || 'success' }] })),
    removeToast: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),

    outputDir: '',
    setOutputDir: (d) => set({ outputDir: d }),

    settings: { threads: 0, bufferMB: 4, outputDir: '' },
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

    theme: 'dark',
    setTheme: (t) => {
      set({ theme: t });
      document.documentElement.classList.toggle('dark', t === 'dark');
      document.documentElement.classList.toggle('light', t !== 'dark');
    },
  }))
);

function applyFilter(files, filter) {
  return files.filter((f) => {
    if (filter.type !== 'all') {
      const typeMap = { images: 1, videos: 2, audio: 3, documents: 4, archives: 5 };
      if (f.type !== typeMap[filter.type]) return false;
    }
    if (filter.statusDeleted && f.status !== 1) return false;
    if (filter.source !== 'all' && (f.source || 'unknown') !== filter.source) return false;
    if (filter.search) {
      const q = filter.search.toLowerCase();
      if (!f.name.toLowerCase().includes(q)) return false;
    }
    if (filter.minHealth > 0 && (f.health?.score ?? 100) < filter.minHealth) return false;
    if (filter.ext && !f.name?.toLowerCase().endsWith('.' + filter.ext.toLowerCase().replace(/^\./, ''))) return false;
    if (filter.minSize > 0 && (f.size || 0) < filter.minSize) return false;
    if (filter.maxSize > 0 && (f.size || 0) > filter.maxSize) return false;
    return true;
  });
}

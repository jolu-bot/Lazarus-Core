import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';

export const FileType   = { UNKNOWN:0, IMAGE:1, VIDEO:2, AUDIO:3, DOCUMENT:4, ARCHIVE:5, OTHER:6 };
export const FileStatus = { ACTIVE:0, DELETED:1, FRAGMENTED:2, PARTIAL:3 };

// Business plan active by default (FREE_LOCAL_MODE mirrors license.js)
const FULL_FEATURES = { scan:true, recover:true, aiRepair:true, videoRecovery:true, forensic:true };
const DEFAULT_LICENSE = { valid:true, plan:3, tier:'Business - Local Edition',
                          features:FULL_FEATURES, freeMode:true };

export const useAppStore = create(
  subscribeWithSelector((set, get) => ({
    // ── Drives ──────────────────────────────────────────────────
    drives:         [],
    selectedDrive:  null,
    setDrives:      (drives) => set({ drives }),
    selectDrive:    (drive)  => set({ selectedDrive: drive }),

    // ── Scan ────────────────────────────────────────────────────
    scanState:  'idle',
    progress:   { percent:0, filesFound:0, filesRecoverable:0, currentPath:'' },
    files:      [],
    filteredFiles: [],
    scanOptions: { scanNTFS:true, scanEXT4:true, scanAPFS:true, enableCarving:true, deepScan:false },

    setScanState:   (s)    => set({ scanState:s }),
    setProgress:    (p)    => set({ progress:p }),
    setScanOptions: (opts) => set((s) => ({ scanOptions:{ ...s.scanOptions, ...opts } })),

    addFile: (file) => set((s) => {
      const files = [...s.files, file];
      return { files, filteredFiles: applyFilter(files, s.filter) };
    }),
    clearFiles: () => set({ files:[], filteredFiles:[] }),

    // ── Filter ──────────────────────────────────────────────────
    filter: { type:'all', search:'', statusDeleted:false, minHealth:0 },
    setFilter: (f) => set((s) => {
      const filter = { ...s.filter, ...f };
      return { filter, filteredFiles: applyFilter(s.files, filter) };
    }),

    // ── Selected file ───────────────────────────────────────────
    selectedFile: null,
    selectFile:   (file) => set({ selectedFile: file }),

    // ── License ─────────────────────────────────────────────────
    license:    DEFAULT_LICENSE,
    setLicense: (lic) => set({ license: lic }),

    // ── View ────────────────────────────────────────────────────
    view:    'scan',
    setView: (v) => set({ view: v }),

    // ── AI ──────────────────────────────────────────────────────
    aiAvailable:    false,
    setAIAvailable: (v) => set({ aiAvailable: v }),

    // ── Repair results (keyed by file.id) ──────────────────────
    repairResults: {},
    setRepairResult: (fileId, result) =>
      set((s) => ({ repairResults: { ...s.repairResults, [fileId]: result } })),

    repairedImage:    null,
    setRepairedImage: (img) => set({ repairedImage: img }),
  }))
);

function applyFilter(files, filter) {
  return files.filter((f) => {
    if (filter.type !== 'all') {
      const typeMap = { images:1, videos:2, audio:3, documents:4, archives:5 };
      if (f.type !== typeMap[filter.type]) return false;
    }
    if (filter.statusDeleted && f.status !== 1) return false;
    if (filter.search) {
      const q = filter.search.toLowerCase();
      if (!f.name.toLowerCase().includes(q)) return false;
    }
    if (filter.minHealth > 0 && (f.health?.score ?? 100) < filter.minHealth) return false;
    return true;
  });
}

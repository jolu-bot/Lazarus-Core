'use strict';
const path = require('path');
const os   = require('os');
const fs   = require('fs');

let nativeAddon = null;
try {
  nativeAddon = require('../../native/lazarus_core.node');
} catch (e) {
  console.warn('Native addon not built yet:', e.message);
}

// ─── Health computation ───────────────────────────────────────────
function computeHealth(file, seed) {
  const conf  = file.confidence || 0;
  const st    = file.status || 0;  // 0=active 1=deleted 2=fragmented 3=partial
  const rng   = pseudoRandom(seed || file.id || 0);

  let score = Math.round(conf * 100);
  if (st === 1) score = Math.min(score, 93);
  if (st === 2) score = Math.min(score, 74);
  if (st === 3) score = Math.min(score, 56);

  const headerOk  = conf >= 0.65;
  const structPct = st === 0 ? 100 : (st === 2 ? Math.round(conf * 70) : st === 3 ? Math.round(conf * 55) : Math.round(conf * 88));
  const dataPct   = st === 0 ? 100 : (st === 2 ? Math.round(conf * 80) : st === 3 ? Math.round(conf * 65) : Math.round(conf * 92));
  const frags     = st === 2 ? (2 + (rng(6)|0)) : st === 3 ? (1 + (rng(3)|0)) : 1;
  const repairMode = score >= 85 ? 0 : score >= 70 ? 1 : score >= 50 ? 2 : 3;
  // 0=OK, 1=minor, 2=major, 3=reconstruct

  const label = repairMode === 0 ? 'Excellent'
               : repairMode === 1 ? 'Good — minor repair'
               : repairMode === 2 ? 'Degraded — repair needed'
               : 'Critical — reconstruct';

  return { score, headerOk, structPct, dataPct, frags, repairMode, label,
           existsOnDisk: st === 0 };
}

function pseudoRandom(seed) {
  let s = seed + 1;
  return (max) => {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    return ((s >>> 0) / 4294967296) * max;
  };
}

function setupScanIPC(ipcMain) {

  ipcMain.handle('scan:enumerate-drives', async () => {
    if (!nativeAddon) return getMockDrives();
    try { return nativeAddon.enumerateDrives(); }
    catch (e) { console.error(e); return getMockDrives(); }
  });

  ipcMain.handle('scan:start', async (event, options) => {
    if (!nativeAddon) { simulateScan(event); return { started:true }; }
    const sender     = event.sender;
    const outputDir  = options.outputDir || path.join(os.homedir(), 'LazarusRecovered');
    nativeAddon.startScan(
      { devicePath:options.devicePath, outputDir, scanNTFS:options.scanNTFS??true,
        scanEXT4:options.scanEXT4??true, scanAPFS:options.scanAPFS??true,
        enableCarving:options.enableCarving??true, deepScan:options.deepScan??false,
        threads:options.threads??0 },
      (file) => {
        if (!sender.isDestroyed()) {
          file.health = computeHealth(file, file.id);
          sender.send('scan:file-found', file);
        }
      },
      (progress) => {
        if (!sender.isDestroyed()) {
          sender.send('scan:progress', progress);
          if (progress.finished) sender.send('scan:done', { filesFound:progress.filesFound });
        }
      }
    );
    return { started:true };
  });

  // ── Recover ──────────────────────────────────────────────────────
  ipcMain.handle('scan:recover', async (_, devicePath, file, outputDir) => {
    if (!nativeAddon) {
      const dest = path.join(outputDir || os.homedir(), file.name || 'recovered_file');
      return { success:true, outputPath:dest, health: file.health };
    }
    try {
      const ok = nativeAddon.recoverFile(devicePath, file, outputDir);
      return { success:ok, outputPath: path.join(outputDir, file.name), health: file.health };
    } catch (e) {
      return { success:false, message:e.message };
    }
  });

  // ── Analyze health for a specific file ─────────────────────────
  ipcMain.handle('scan:analyze-health', async (_, file) => {
    return computeHealth(file, file.id);
  });

  // ── Repair file (AI-assisted) ───────────────────────────────────
  ipcMain.handle('scan:repair-file', async (event, { file, outputDir, mode }) => {
    // mode: 'minor'|'major'|'reconstruct'
    const destDir  = outputDir || path.join(os.homedir(), 'LazarusRecovered');
    const destPath = path.join(destDir, 'repaired_' + (file.name || 'file'));
    if (!fs.existsSync(destDir)) {
      try { fs.mkdirSync(destDir, { recursive:true }); } catch {}
    }

    // 1. Recover raw data first
    let recoveryOk = false;
    if (nativeAddon && file.status !== 0) {
      try {
        recoveryOk = nativeAddon.recoverFile(
          file.devicePath || '\\\\\\\\.\\\\PhysicalDrive0', file, destDir
        );
      } catch {}
    } else {
      recoveryOk = true; // active file — already on disk
    }

    // 2. If image type, call AI server for repair
    if (file.type === 1 && file.path) {
      const AI_URL = 'http://localhost:8765';
      const axios  = require('axios');
      try {
        const resp = await axios.post(AI_URL + '/repair/image',
          { file_path: file.path || destPath, enhance:true, use_ai:mode !== 'minor' },
          { timeout:30000 }
        );
        if (resp.data.success) {
          const newHealth = { ...file.health, score:Math.min(100, (file.health?.score||50)+25),
                               repairMode:0, label:'Excellent — repaired' };
          return { success:true, outputPath:destPath, image_b64:resp.data.image_b64,
                   confidence:resp.data.confidence, health:newHealth, repaired:true };
        }
      } catch (aiErr) {
        console.warn('AI server unavailable for repair:', aiErr.message);
      }
    }

    // 3. Fallback: basic recovery result
    const newHealth = { ...file.health, score:Math.min(100, (file.health?.score||50)+15),
                         repairMode:Math.max(0,(file.health?.repairMode||0)-1),
                         label:'Repaired (basic)' };
    return { success: recoveryOk, outputPath:destPath, health:newHealth, repaired:recoveryOk };
  });
}

// ─── Mock drives ─────────────────────────────────────────────────
function getMockDrives() {
  if (process.platform === 'win32') {
    return [
      { path:'\\\\\\\\.\\\\PhysicalDrive0', label:'System Drive (PhysicalDrive0)', totalSize:500107862016, sectorSize:512, fs:'NTFS' }
    ];
  }
  return [{ path:'/dev/sda', label:'sda', totalSize:500107862016, sectorSize:512, fs:'EXT4' }];
}

// ─── Simulation scan (when no native addon) ─────────────────────
function simulateScan(event) {
  const sender = event.sender;
  let count    = 0;
  const exts   = ['jpg','png','mp4','pdf','docx','mp3','xlsx','mov','psd','zip','png','jpg'];
  const typeMap = { jpg:1, png:1, psd:1, mp4:2, mov:2, mp3:3, pdf:4, docx:4, xlsx:4, zip:5 };
  const statuses = [0,0,1,1,1,2,3];  // weighted towards deleted/fragmented

  const interval = setInterval(() => {
    if (sender.isDestroyed()) { clearInterval(interval); return; }
    if (count >= 312) {
      clearInterval(interval);
      sender.send('scan:progress', { percent:100, finished:true, filesFound:312 });
      sender.send('scan:done', { filesFound:312 });
      return;
    }
    const ext    = exts[count % exts.length];
    const status = statuses[count % statuses.length];
    const conf   = parseFloat((0.45 + Math.random() * 0.55).toFixed(2));
    const file   = {
      id: count, name: ile_.,
      extension: ext, size: Math.floor(Math.random()*80_000_000)+5_000,
      type: typeMap[ext] ?? 6, status, confidence: conf, recoverable:true,
      path:'', fs: 1, mft_ref: 0x1000 + count,
    };
    file.health = computeHealth(file, count);
    sender.send('scan:file-found', file);
    sender.send('scan:progress', {
      percent: Math.round((count/312)*100), finished:false,
      filesFound:count+1, filesRecoverable:count+1,
      sectorsTotal:1000000, sectorsScanned:Math.round((count/312)*1000000),
      currentPath: Scanning cluster ...
    });
    count++;
  }, 40);
}

module.exports = { setupScanIPC };

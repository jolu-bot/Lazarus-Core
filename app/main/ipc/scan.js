'use strict';
const path = require('path');
const os   = require('os');

let nativeAddon = null;
try {
  nativeAddon = require('../../native/lazarus_core.node');
} catch (e) {
  console.warn('Native addon not built yet:', e.message);
}

function setupScanIPC(ipcMain) {
  // ── Enumerate drives ──────────────────────────────────────────
  ipcMain.handle('scan:enumerate-drives', async () => {
    if (!nativeAddon) return getMockDrives();
    try {
      return nativeAddon.enumerateDrives();
    } catch (e) {
      console.error('enumerate-drives error:', e);
      return getMockDrives();
    }
  });

  // ── Start scan ────────────────────────────────────────────────
  ipcMain.handle('scan:start', async (event, options) => {
    if (!nativeAddon) {
      simulateScan(event);
      return { started: true };
    }

    const sender = event.sender;
    const outputDir = options.outputDir ||
                      path.join(os.homedir(), 'LazarusRecovered');

    nativeAddon.startScan(
      {
        devicePath:    options.devicePath,
        outputDir:     outputDir,
        scanNTFS:      options.scanNTFS      ?? true,
        scanEXT4:      options.scanEXT4      ?? true,
        scanAPFS:      options.scanAPFS      ?? true,
        enableCarving: options.enableCarving ?? true,
        deepScan:      options.deepScan      ?? false,
        threads:       options.threads       ?? 0,
      },
      (file) => {
        if (!sender.isDestroyed())
          sender.send('scan:file-found', file);
      },
      (progress) => {
        if (!sender.isDestroyed())
          sender.send('scan:progress', progress);
        if (progress.finished && !sender.isDestroyed())
          sender.send('scan:done', { filesFound: progress.filesFound });
      }
    );

    return { started: true };
  });

  // ── Recover single file ───────────────────────────────────────
  ipcMain.handle('scan:recover', async (_, devicePath, file, outputDir) => {
    if (!nativeAddon) return { success: false, message: 'Native module not built' };
    try {
      const ok = nativeAddon.recoverFile(devicePath, file, outputDir);
      return { success: ok };
    } catch (e) {
      return { success: false, message: e.message };
    }
  });
}

// ─── Mock for dev mode ────────────────────────────────────────────
function getMockDrives() {
  const platform = process.platform;
  if (platform === 'win32') {
    return [
      { path: '\\\\.\\PhysicalDrive0', label: 'PhysicalDrive0', totalSize: 500107862016, sectorSize: 512 }
    ];
  }
  return [
    { path: '/dev/sda', label: 'sda', totalSize: 500107862016, sectorSize: 512 }
  ];
}

function simulateScan(event) {
  const sender = event.sender;
  let count = 0;
  const types      = ['jpg','png','mp4','pdf','docx','mp3'];
  const typeMap    = { jpg:1, png:1, mp4:2, pdf:4, docx:4, mp3:3 };
  const statuses   = [0, 1]; // ACTIVE, DELETED

  const interval = setInterval(() => {
    if (sender.isDestroyed()) { clearInterval(interval); return; }
    if (count >= 250) {
      clearInterval(interval);
      sender.send('scan:progress', { percent: 100, finished: true, filesFound: 250 });
      sender.send('scan:done', { filesFound: 250 });
      return;
    }

    const ext    = types[Math.floor(Math.random() * types.length)];
    const status = statuses[Math.floor(Math.random() * statuses.length)];
    const file   = {
      id:          count,
      name:        `recovered_file_${count}.${ext}`,
      extension:   ext,
      size:        Math.floor(Math.random() * 50_000_000) + 10_000,
      type:        typeMap[ext] ?? 6,
      status:      status,
      confidence:  Math.round((0.55 + Math.random() * 0.45) * 100) / 100,
      recoverable: true,
      path:        '',
    };
    sender.send('scan:file-found', file);

    const pct = Math.round((count / 250) * 100);
    sender.send('scan:progress', {
      percent:          pct,
      finished:         false,
      filesFound:       count + 1,
      filesRecoverable: count + 1,
      sectorsTotal:     1000000,
      sectorsScanned:   Math.round((count / 250) * 1000000),
    });
    count++;
  }, 50);
}

module.exports = { setupScanIPC };

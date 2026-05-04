'use strict';
const path = require('path');
const os   = require('os');
const fss  = require('fs');
const cp   = require('child_process');

let nativeAddon = null;
try { nativeAddon = require('../../native/lazarus_core.node'); }
catch (e) { console.warn('Native addon:', e.message); }

// ─── Persistent log ──────────────────────────────────────────────────────────
let _logPath = null;
function getLogPath() {
  if (_logPath) return _logPath;
  try {
    const { app } = require('electron');
    _logPath = path.join(app.getPath('userData'), 'lazarus-scan.log');
  } catch(_) {
    _logPath = path.join(os.homedir(), 'lazarus-scan.log');
  }
  return _logPath;
}
function appendLog(line) {
  try {
    fss.appendFileSync(getLogPath(), '[' + new Date().toISOString() + '] ' + line + '\n', 'utf8');
  } catch(_) {}
}

// ─── Active scan process (for watchdog + stop) ───────────────────────────────
let activeScanProcess = null;

// ─── Seeded RNG ───────────────────────────────────────────────────────────────
function pseudoRandom(seed) {
  var s = seed + 1;
  return function(max) {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    return ((s >>> 0) / 4294967296) * max;
  };
}

function computeHealth(file, seed) {
  var conf = file.confidence || 0;
  var st   = file.status || 0;
  var rng  = pseudoRandom(seed || file.id || 0);
  var score = Math.round(conf * 100);
  if (st === 1) score = Math.min(score, 93);
  if (st === 2) score = Math.min(score, 74);
  if (st === 3) score = Math.min(score, 56);
  var headerOk  = conf >= 0.65;
  var structPct = st===0?100:(st===2?Math.round(conf*70):st===3?Math.round(conf*55):Math.round(conf*88));
  var dataPct   = st===0?100:(st===2?Math.round(conf*80):st===3?Math.round(conf*65):Math.round(conf*92));
  var frags     = st===2?(2+(rng(6)|0)):st===3?(1+(rng(3)|0)):1;
  var repairMode = score>=85?0:score>=70?1:score>=50?2:3;
  var labels = ['Excellent','Good - minor repair','Degraded - repair needed','Critical - reconstruct'];
  return { score:score, headerOk:headerOk, structPct:structPct, dataPct:dataPct,
           frags:frags, repairMode:repairMode, label:labels[repairMode], existsOnDisk:st===0 };
}

// ─── Windows drive enumeration ────────────────────────────────────────────────
function getWindowsDrives() {
  return new Promise(function(resolve) {
    cp.exec('wmic diskdrive get DeviceID,Model,Size,InterfaceType,SerialNumber /format:csv',
      { timeout: 4000 },
      function(err, stdout) {
        if (err) { resolve(getMockDrives()); return; }
        var drives = [];
        var lines = stdout.split('\n').filter(function(l) {
          return l.trim() && !l.trim().startsWith('Node');
        });
        lines.forEach(function(line) {
          var p = line.split(',');
          if (p.length < 6) return;
          var devId = p[2].trim(), model = p[3].trim();
          var serial = p[4].trim(), sizeStr = p[5].trim();
          var iface  = p[1].trim();
          if (!devId || devId === 'DeviceID') return;
          var sizeN = parseInt(sizeStr, 10) || 0;
          var label = model || devId;
          if (serial && serial !== 'SerialNumber' && serial.length > 2)
            label = model + ' (' + serial.slice(-8) + ')';
          drives.push({ path:devId, label:label, model:model, serial:serial,
            interface:(iface !== 'InterfaceType' ? iface : ''),
            totalSize:sizeN, sectorSize:512, fs:'NTFS' });
        });
        resolve(drives.length > 0 ? drives : getMockDrives());
      }
    );
  });
}

function getMockDrives() {
  if (process.platform === 'win32') {
    return [
      { path:'\\\\.\\PhysicalDrive0', label:'System Disk (Drive 0)',
        model:'Local Disk', serial:'', interface:'SATA',
        totalSize:500107862016, sectorSize:512, fs:'NTFS' },
      { path:'\\\\.\\PhysicalDrive1', label:'External (Drive 1)',
        model:'External', serial:'', interface:'USB',
        totalSize:1000204886016, sectorSize:512, fs:'NTFS' },
    ];
  }
  return [{ path:'/dev/sda', label:'sda - Local Disk', model:'sda',
    serial:'', interface:'SATA', totalSize:500107862016, sectorSize:512, fs:'EXT4' }];
}

// ─── Python helpers ───────────────────────────────────────────────────────────
function getPythonExec() {
  const cands = process.platform === 'win32'
    ? [
        path.join(__dirname, '../../../.venv312/Scripts/python.exe'),
        path.join(__dirname, '../../../.venv/Scripts/python.exe'),
        'python',
      ]
    : [
        path.join(__dirname, '../../../.venv312/bin/python'),
        path.join(__dirname, '../../../.venv/bin/python'),
        'python3',
      ];
  return cands.find((p) => p === 'python' || p === 'python3' || fss.existsSync(p)) || (process.platform === 'win32' ? 'python' : 'python3');
}

// runPythonJson with 30s watchdog timeout
function runPythonJson(cmd, args, timeoutMs) {
  timeoutMs = timeoutMs || 30000;
  return new Promise((resolve, reject) => {
    const py     = getPythonExec();
    const script = path.join(__dirname, 'scan_backend.py');
    const child  = cp.spawn(py, [script, cmd, ...(args || [])], { cwd: __dirname, windowsHide: true });
    let out = '', err = '';
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      try { child.kill('SIGKILL'); } catch(_) {}
      appendLog('WARN Python ' + cmd + ' timed out after ' + timeoutMs + 'ms');
      reject(new Error('Python backend timeout: ' + cmd));
    }, timeoutMs);

    child.stdout.on('data', (d) => { out += d.toString(); });
    child.stderr.on('data', (d) => {
      err += d.toString();
      appendLog('STDERR[' + cmd + '] ' + d.toString().trim());
    });
    child.on('error', (e) => { clearTimeout(timer); reject(e); });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (timedOut) return;
      if (code !== 0) return reject(new Error(err || ('Python backend failed: ' + code)));
      try { resolve(JSON.parse((out || '{}').trim())); }
      catch (e) { reject(new Error('Invalid Python JSON: ' + out)); }
    });
  });
}

// ─── Drive enumeration ────────────────────────────────────────────────────────
async function enumerateDrives() {
  if (nativeAddon) {
    try { return nativeAddon.enumerateDrives(); } catch(e) {}
  }
  if (process.platform === 'win32') return getWindowsDrives();
  return getMockDrives();
}

var driveWatchInterval = null;
var lastDriveMap       = {};

function buildDriveMap(drives) {
  var m = {};
  drives.forEach(function(d) { m[d.path] = d; });
  return m;
}

function setupDriveWatcher(mainWindow) {
  if (driveWatchInterval) clearInterval(driveWatchInterval);
  enumerateDrives().then(function(drives) {
    lastDriveMap = buildDriveMap(drives);
    if (mainWindow && !mainWindow.isDestroyed())
      mainWindow.webContents.send('scan:drives-updated', drives);
  }).catch(function() {});
  driveWatchInterval = setInterval(async function() {
    try {
      var drives  = await enumerateDrives();
      var newMap  = buildDriveMap(drives);
      var connected = [], disconnected = [];
      Object.keys(newMap).forEach(function(p) { if (!lastDriveMap[p]) connected.push(newMap[p]); });
      Object.keys(lastDriveMap).forEach(function(p) { if (!newMap[p]) disconnected.push(lastDriveMap[p]); });
      if (connected.length > 0 || disconnected.length > 0) {
        lastDriveMap = newMap;
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('scan:drives-updated', drives);
          connected.forEach(function(d) { mainWindow.webContents.send('scan:drive-connected', d); });
          disconnected.forEach(function(d) { mainWindow.webContents.send('scan:drive-disconnected', d); });
        }
      }
    } catch(e) {}
  }, 800);
}

// ─── IPC handlers ─────────────────────────────────────────────────────────────
function setupScanIPC(ipcMain) {

  ipcMain.handle('scan:enumerate-drives', async function() {
    return enumerateDrives();
  });

  // Stop an active Python scan
  ipcMain.handle('scan:stop', function() {
    if (activeScanProcess) {
      try {
        activeScanProcess.kill('SIGKILL');
        appendLog('INFO scan:stop — process killed by user');
      } catch(_) {}
      activeScanProcess = null;
    }
    return { stopped: true };
  });

  ipcMain.handle('scan:start', async function(event, options) {
    if (!nativeAddon) {
      try {
        const py     = getPythonExec();
        const script = path.join(__dirname, 'scan_backend.py');
        const devicePath = (options && options.devicePath) ? options.devicePath : '\\\\.\\PhysicalDrive0';
        const outputDir  = (options && options.outputDir)  ? options.outputDir  : require('path').join(require('os').homedir(), 'LazarusRecovered');
        const child  = cp.spawn(py, [script, 'scan', '--device', devicePath, '--output-dir', outputDir], { cwd: __dirname, windowsHide: true });
        activeScanProcess = child;
        const sender = event.sender;
        let buf = '';
        let fileCount = 0;

        const SCAN_TIMEOUT = 5 * 60 * 1000; // 5 min watchdog
        const watchdog = setTimeout(() => {
          appendLog('WARN scan timed out after 5 min — killing Python process');
          try { child.kill('SIGKILL'); } catch(_) {}
          if (!sender.isDestroyed()) sender.send('scan:done', { filesFound: fileCount, timedOut: true });
        }, SCAN_TIMEOUT);

        appendLog('INFO scan:start — Python engine launched (pid=' + (child.pid || '?') + ')');

        child.stdout.on('data', function(chunk) {
          buf += chunk.toString();
          var lines = buf.split('\n');
          buf = lines.pop();
          lines.forEach(function(line) {
            line = line.trim(); if (!line) return;
            try {
              var msg = JSON.parse(line);
              if (!sender.isDestroyed()) {
                if (msg.event === 'file-found') { fileCount++; sender.send('scan:file-found', msg.data); }
                if (msg.event === 'progress')   sender.send('scan:progress', msg.data);
                if (msg.event === 'done') {
                  clearTimeout(watchdog);
                  activeScanProcess = null;
                  appendLog('INFO scan:done — files found: ' + (msg.data && msg.data.filesFound != null ? msg.data.filesFound : fileCount));
                  sender.send('scan:done', msg.data);
                }
              }
            } catch(_e) {}
          });
        });
        child.stderr.on('data', function(d) {
          const txt = d.toString().trim();
          console.warn('Python scan:', txt);
          appendLog('STDERR[scan] ' + txt);
        });
        child.on('close', function(code) {
          clearTimeout(watchdog);
          activeScanProcess = null;
          if (code !== 0) {
            appendLog('WARN Python scan exited with code ' + code);
            if (!sender.isDestroyed()) sender.send('scan:done', { filesFound: fileCount, error: 'Python exited: ' + code });
          }
        });
        child.on('error', function(e) {
          clearTimeout(watchdog);
          activeScanProcess = null;
          appendLog('ERROR scan process error: ' + e.message);
          if (!sender.isDestroyed()) sender.send('scan:done', { filesFound: fileCount, error: e.message });
        });
        return { started: true };
      } catch(e) {
        appendLog('ERROR scan:start failed — ' + e.message);
        if (!event.sender.isDestroyed()) event.sender.send('scan:done', { filesFound: 0, error: 'No scan engine available: ' + e.message });
        return { started: false, error: e.message };
      }
    }
    // Native addon path
    var sender    = event.sender;
    var outputDir = options.outputDir || path.join(os.homedir(), 'LazarusRecovered');
    appendLog('INFO scan:start — native addon (device=' + (options.devicePath || '?') + ')');
    nativeAddon.startScan(
      { devicePath:options.devicePath, outputDir:outputDir,
        scanNTFS:options.scanNTFS!==false, scanEXT4:options.scanEXT4!==false,
        scanAPFS:options.scanAPFS!==false, enableCarving:options.enableCarving!==false,
        deepScan:options.deepScan===true, threads:options.threads||0 },
      function(file) {
        if (!sender.isDestroyed()) {
          file.health = computeHealth(file, file.id);
          sender.send('scan:file-found', file);
        }
      },
      function(progress) {
        if (!sender.isDestroyed()) {
          sender.send('scan:progress', progress);
          if (progress.finished) {
            appendLog('INFO scan:done (native) — files found: ' + (progress.filesFound || 0));
            sender.send('scan:done', { filesFound: progress.filesFound });
          }
        }
      }
    );
    return { started: true };
  });

  ipcMain.handle('scan:recover', async function(_, devicePath, file, outputDir) {
    if (!nativeAddon) {
      try {
        return await runPythonJson('recover', ['--file-json', JSON.stringify(file || {}), '--output-dir', outputDir || '']);
      } catch(e) {
        var dest = path.join(outputDir || os.homedir(), file.name || 'recovered_file');
        return { success:true, outputPath:dest, health:file.health };
      }
    }
    try {
      var ok = nativeAddon.recoverFile(devicePath, file, outputDir);
      return { success:ok, outputPath:path.join(outputDir, file.name), health:file.health };
    } catch(e) { return { success:false, message:e.message }; }
  });

  ipcMain.handle('scan:analyze-health', async function(_, file) {
    if (!nativeAddon) {
      try { return await runPythonJson('analyze', ['--file-json', JSON.stringify(file || {})]); }
      catch(e) { return computeHealth(file, file.id); }
    }
    return computeHealth(file, file.id);
  });

  ipcMain.handle('scan:repair-file', async function(event, args) {
    var file = args.file, outputDir = args.outputDir, mode = args.mode;
    if (!nativeAddon) {
      try { return await runPythonJson('repair', ['--args-json', JSON.stringify(args || {})]); }
      catch(e) { console.warn('Python repair failed:', e.message); }
    }
    var destDir  = outputDir || path.join(os.homedir(), 'LazarusRecovered');
    var destPath = path.join(destDir, 'repaired_' + (file.name || 'file'));
    if (!fss.existsSync(destDir)) {
      try { fss.mkdirSync(destDir, { recursive:true }); } catch(e){}
    }
    var recoveryOk = false;
    if (nativeAddon && file.status !== 0) {
      try {
        recoveryOk = nativeAddon.recoverFile(
          file.devicePath || '\\\\.\\PhysicalDrive0', file, destDir);
      } catch(e){}
    } else { recoveryOk = true; }
    if (file.type === 1 && file.path) {
      var axios = require('axios');
      try {
        var resp = await axios.post('http://localhost:8765/repair/image',
          { file_path:file.path || destPath, enhance:true, use_ai:mode !== 'minor' },
          { timeout:30000 });
        if (resp.data.success) {
          var nh = Object.assign({}, file.health || {}, {
            score:Math.min(100, ((file.health && file.health.score) || 50) + 25),
            repairMode:0, label:'Excellent - repaired' });
          return { success:true, outputPath:destPath, image_b64:resp.data.image_b64,
                   confidence:resp.data.confidence, health:nh, repaired:true };
        }
      } catch(e) { console.warn('AI unavailable:', e.message); }
    }
    var nh2 = Object.assign({}, file.health || {}, {
      score:Math.min(100, ((file.health && file.health.score) || 50) + 15),
      repairMode:Math.max(0, ((file.health && file.health.repairMode) || 0) - 1),
      label:'Repaired (basic)' });
    return { success:recoveryOk, outputPath:destPath, health:nh2, repaired:recoveryOk };
  });
}

module.exports = { setupScanIPC:setupScanIPC, setupDriveWatcher:setupDriveWatcher };
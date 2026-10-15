'use strict';
/**
 * Pont entre l'interface et le moteur Python (scan_backend.py).
 * - une seule opération lourde à la fois (analyse / récupération / imagerie) ;
 * - évènements « file-found » regroupés en lots pour ne pas saturer l'IPC ;
 * - arrêt propre via stdin (« stop »), puis arrêt forcé si le moteur ne répond pas ;
 * - sessions d'analyse sauvegardées (JSONL) : un scan de plusieurs heures n'est jamais perdu.
 */
const path = require('path');
const os   = require('os');
const fs   = require('fs');
const cp   = require('child_process');

// ─── Journal persistant ──────────────────────────────────────────────────────
let _logPath = null;
function userDataDir() {
  try { return require('electron').app.getPath('userData'); }
  catch (_) { return path.join(os.homedir(), '.lazarus-core'); }
}
function getLogPath() {
  if (!_logPath) _logPath = path.join(userDataDir(), 'lazarus-engine.log');
  return _logPath;
}
function appendLog(line) {
  try {
    fs.mkdirSync(path.dirname(getLogPath()), { recursive: true });
    const p = getLogPath();
    try { if (fs.statSync(p).size > 5 * 1024 * 1024) fs.renameSync(p, p + '.old'); } catch (_) {}
    fs.appendFileSync(p, '[' + new Date().toISOString() + '] ' + line + '\n', 'utf8');
  } catch (_) {}
}

// ─── Localisation du moteur ──────────────────────────────────────────────────
function getIpcDir() {
  // En production les scripts sont « unpacked » hors de l'archive asar.
  return __dirname.replace(/app\.asar(?=[\\/]|$)/, 'app.asar.unpacked');
}

let _engine = null;
function pythonWorks(cmd, pre) {
  try {
    const r = cp.spawnSync(cmd, [...pre, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'],
      { timeout: 8000, windowsHide: true });
    return r.status === 0;
  } catch (_) { return false; }
}

/** Retourne { cmd, pre:[...], script:bool } : exécutable gelé (PyInstaller) ou interpréteur Python. */
function getEngine() {
  if (_engine) return _engine;
  const res = process.resourcesPath || '';
  const frozen = process.platform === 'win32' ? 'lazarus-engine.exe' : 'lazarus-engine';
  // moteur gelé : dossier PyInstaller (resources/engine/lazarus-engine/…) ou, à défaut, exécutable unique
  for (const frozenPath of [path.join(res, 'engine', 'lazarus-engine', frozen), path.join(res, 'engine', frozen)]) {
    if (res && fs.existsSync(frozenPath)) {
      _engine = { cmd: frozenPath, pre: [], script: false, kind: 'embedded' };
      return _engine;
    }
  }
  const root = path.join(__dirname, '..', '..', '..');
  const cands = [];
  if (process.env.LAZARUS_PYTHON) cands.push([process.env.LAZARUS_PYTHON, []]);
  if (process.platform === 'win32') {
    cands.push([path.join(root, '.venv312', 'Scripts', 'python.exe'), []]);
    cands.push([path.join(root, '.venv', 'Scripts', 'python.exe'), []]);
    cands.push(['python', []], ['py', ['-3']], ['python3', []]);
  } else {
    cands.push([path.join(root, '.venv312', 'bin', 'python'), []]);
    cands.push([path.join(root, '.venv', 'bin', 'python'), []]);
    cands.push(['python3', []], ['python', []]);
  }
  for (const [cmd, pre] of cands) {
    if (path.isAbsolute(cmd) && !fs.existsSync(cmd)) continue;
    if (pythonWorks(cmd, pre)) {
      _engine = { cmd, pre, script: true, kind: 'python' };
      return _engine;
    }
  }
  throw new Error("Python 3.8+ est introuvable. Installez Python (python.org) ou définissez LAZARUS_PYTHON, puis relancez Lazarus Core.");
}

function engineArgs(command, args) {
  const eng = getEngine();
  const base = eng.script ? [...eng.pre, path.join(getIpcDir(), 'scan_backend.py')] : [];
  return { cmd: eng.cmd, args: [...base, command, ...(args || [])] };
}

function spawnEngine(command, args) {
  const { cmd, args: a } = engineArgs(command, args);
  return cp.spawn(cmd, a, {
    cwd: getIpcDir(), windowsHide: true,
    env: Object.assign({}, process.env, { PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' }),
    stdio: ['pipe', 'pipe', 'pipe'],
  });
}

/** Découpe stdout en lignes JSON ; appelle onEvent(event, data) ou onResult(obj). */
function attachJsonLines(child, onEvent, onResult, cmdName) {
  let buf = '';
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {
    buf += chunk;
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line || (line[0] !== '{' && line[0] !== '[')) continue;
      try {
        const obj = JSON.parse(line);
        if (obj && !Array.isArray(obj) && obj.event) onEvent(obj.event, obj.data);
        else if (onResult) onResult(obj);
      } catch (_) { /* ligne tronquée : ignorée */ }
    }
  });
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', (d) => { const t = String(d).trim(); if (t) appendLog('[' + cmdName + '] ' + t); });
}

/** Commande simple : exécute et retourne le dernier objet JSON (hors évènements). */
function runEngineJson(command, args, timeoutMs, requestObj) {
  return new Promise((resolve, reject) => {
    let reqFile = null;
    let argv = args || [];
    try {
      if (requestObj !== undefined) {
        reqFile = path.join(os.tmpdir(), 'lazarus-req-' + process.pid + '-' + Date.now() + '-' + Math.random().toString(36).slice(2) + '.json');
        fs.writeFileSync(reqFile, JSON.stringify(requestObj), 'utf8');
        argv = [...argv, '--request-file', reqFile];
      }
    } catch (e) { return reject(e); }
    let child;
    try { child = spawnEngine(command, argv); } catch (e) { return reject(e); }
    let last = null; let err = '';
    const timer = setTimeout(() => { try { child.kill('SIGKILL'); } catch (_) {} reject(new Error('Délai dépassé : ' + command)); }, timeoutMs || 30000);
    attachJsonLines(child, () => {}, (o) => { last = o; }, command);
    child.stderr.on('data', (d) => { err += d; });
    child.on('error', (e) => { clearTimeout(timer); cleanup(); reject(e); });
    child.on('close', (code) => {
      clearTimeout(timer); cleanup();
      if (last !== null) return resolve(last);
      reject(new Error(err.trim().split('\n').pop() || ('Le moteur a échoué (code ' + code + ')')));
    });
    function cleanup() { if (reqFile) { try { fs.unlinkSync(reqFile); } catch (_) {} } }
  });
}

// ─── Opération active ────────────────────────────────────────────────────────
let current = null; // { kind, child, sender, killTimer }

function requestStop() {
  if (!current) return false;
  const c = current;
  try { c.child.stdin.write('stop\n'); } catch (_) {}
  if (!c.killTimer) {
    c.killTimer = setTimeout(() => { try { c.child.kill('SIGKILL'); } catch (_) {} }, 15000);
  }
  return true;
}

// ─── Sessions ────────────────────────────────────────────────────────────────
function sessionsDir() {
  const d = path.join(userDataDir(), 'sessions');
  fs.mkdirSync(d, { recursive: true });
  return d;
}
let activeSessionId = null;   // session dont les enregistrements complets servent à la récupération
function sessionPathOf(id) {
  const safe = String(id || activeSessionId || '').replace(/[^0-9A-Za-z\-_]/g, '');
  return path.join(sessionsDir(), safe + '.jsonl');
}
/** Allège un enregistrement pour l'interface : les extents restent dans le fichier de session. */
function slim(f) {
  const o = Object.assign({}, f);
  delete o.extents; delete o.resident_b64;
  return o;
}
function writeMeta(id, patch) {
  const p = path.join(sessionsDir(), id + '.meta.json');
  let m = {};
  try { m = JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) {}
  m = Object.assign(m, patch, { id });
  try { fs.writeFileSync(p, JSON.stringify(m, null, 2), 'utf8'); } catch (_) {}
  return m;
}
function markStaleSessions() {
  try {
    for (const f of fs.readdirSync(sessionsDir())) {
      if (!f.endsWith('.meta.json')) continue;
      const p = path.join(sessionsDir(), f);
      const m = JSON.parse(fs.readFileSync(p, 'utf8'));
      if (m.status === 'running') { m.status = 'interrupted'; fs.writeFileSync(p, JSON.stringify(m, null, 2)); }
    }
  } catch (_) {}
}

// ─── Surveillance des disques ────────────────────────────────────────────────
let driveCache = { t: 0, data: null };
async function enumerateDrives(force) {
  if (!force && driveCache.data && Date.now() - driveCache.t < 4000) return driveCache.data;
  const data = await runEngineJson('enumerate', [], 60000);
  driveCache = { t: Date.now(), data: Array.isArray(data) ? data : [] };
  return driveCache.data;
}

let driveWatchTimer = null;
let lastDriveMap = null;
let lastLetters = '';
/** Lettres de lecteurs présentes (test instantané, sans lancer PowerShell). */
function presentLetters() {
  if (process.platform !== 'win32') return 'x';
  let out = '';
  for (const l of 'CDEFGHIJKLMNOPQRSTUVWXYZ') { try { if (fs.existsSync(l + ':\\')) out += l; } catch (_) {} }
  return out;
}
function setupDriveWatcher(mainWindow) {
  if (driveWatchTimer) clearInterval(driveWatchTimer);
  const push = (drives) => { if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('scan:drives-updated', drives); };
  const refresh = async () => {
    const drives = await enumerateDrives(true);
    const map = new Map(drives.map((x) => [x.path, x]));
    if (lastDriveMap) {
      const added = drives.filter((d) => !lastDriveMap.has(d.path));
      const removed = [...lastDriveMap.values()].filter((d) => !map.has(d.path));
      if (mainWindow && !mainWindow.isDestroyed()) {
        added.forEach((d) => mainWindow.webContents.send('scan:drive-connected', d));
        removed.forEach((d) => mainWindow.webContents.send('scan:drive-disconnected', d));
      }
    }
    lastDriveMap = map;
    push(drives);
  };
  lastLetters = presentLetters();
  refresh().catch((e) => appendLog('WARN énumération initiale: ' + e.message));
  let ticks = 0;
  driveWatchTimer = setInterval(async () => {
    if (current) return;                       // aucune interférence pendant une opération disque
    ticks++;
    const letters = presentLetters();
    // changement de lecteurs détecté immédiatement ; sinon vérification complète toutes les 2 minutes
    if (letters !== lastLetters || ticks % 24 === 0) {
      lastLetters = letters;
      try { await refresh(); } catch (_) {}
    }
  }, 5000);
}

// ─── IPC ─────────────────────────────────────────────────────────────────────
function setupScanIPC(ipcMain) {
  markStaleSessions();

  // Réponse immédiate (API Win32, ~0,5 s) puis liste complète (modèles, partitions, santé) poussée en arrière-plan.
  let fullEnumRunning = false;
  ipcMain.handle('scan:enumerate-drives', async (event, force) => {
    if (!force && driveCache.data && Date.now() - driveCache.t < 4000) return driveCache.data;
    let fast = [];
    try { fast = await runEngineJson('enumerate-fast', [], 20000); } catch (e) { appendLog('WARN énumération rapide: ' + e.message); }
    if (!fullEnumRunning) {
      fullEnumRunning = true;
      enumerateDrives(true).then((d) => {
        if (!event.sender.isDestroyed()) event.sender.send('scan:drives-updated', d);
      }).catch((e) => appendLog('WARN énumération complète: ' + e.message)).finally(() => { fullEnumRunning = false; });
    }
    if (Array.isArray(fast) && fast.length) return fast;
    try { return await enumerateDrives(!!force); }
    catch (e) { appendLog('ERROR énumération: ' + e.message); return { error: e.message, drives: [] }; }
  });

  ipcMain.handle('app:diag', async () => {
    const out = { engine: null, admin: false, python: null, error: null, logPath: getLogPath() };
    try {
      const eng = getEngine();
      out.engine = eng.kind;
      const d = await runEngineJson('diag', [], 20000);
      Object.assign(out, d, { python: eng.cmd, python_version: d.python, engine: eng.kind });
    } catch (e) { out.error = e.message; }
    return out;
  });

  ipcMain.handle('app:relaunch-admin', async () => {
    if (process.platform !== 'win32') return { success: false, message: 'Relancez avec sudo.' };
    try {
      const { app } = require('electron');
      const exe = process.env.PORTABLE_EXECUTABLE_FILE || process.execPath;   // version portable : relancer l'exécutable d'origine, pas la copie temporaire
      const args = app.isPackaged ? [] : [app.getAppPath()];
      const argList = args.map((a) => "'" + a.replace(/'/g, "''") + "'").join(',');
      const ps = "Start-Process -FilePath '" + exe.replace(/'/g, "''") + "' " + (argList ? '-ArgumentList ' + argList + ' ' : '') + '-Verb RunAs';
      cp.spawn('powershell', ['-NoProfile', '-Command', ps], { windowsHide: true, detached: true, stdio: 'ignore' }).unref();
      setTimeout(() => app.quit(), 600);
      return { success: true };
    } catch (e) { return { success: false, message: e.message }; }
  });

  // ---- Analyse ----
  ipcMain.handle('scan:start', async (event, options) => {
    if (current) return { started: false, error: 'Une opération est déjà en cours.' };
    options = options || {};
    const sender = event.sender;
    const resuming = options.resumeSessionId ? String(options.resumeSessionId).replace(/[^0-9A-Za-z\-_]/g, '') : '';
    const id = resuming || new Date().toISOString().replace(/[:.]/g, '-');
    const sessionPath = path.join(sessionsDir(), id + '.jsonl');
    const req = Object.assign({}, options, { device: options.devicePath, sessionPath });
    delete req.devicePath;
    let child;
    let reqFile;
    try {
      reqFile = path.join(os.tmpdir(), 'lazarus-scan-' + process.pid + '-' + Date.now() + '.json');
      fs.writeFileSync(reqFile, JSON.stringify(req), 'utf8');
      child = spawnEngine('scan', ['--request-file', reqFile]);
    } catch (e) {
      appendLog('ERROR scan:start ' + e.message);
      sender.send('scan:done', { filesFound: 0, error: e.message, engineMissing: true });
      return { started: false, error: e.message };
    }
    current = { kind: 'scan', child, sender, killTimer: null };
    activeSessionId = id;
    writeMeta(id, { status: 'running', device: options.devicePath, label: options.deviceLabel || options.devicePath,
      ...(resuming ? {} : { started: new Date().toISOString() }), options: { deepScan: !!options.deepScan, enableCarving: options.enableCarving !== false,
        includeExisting: !!options.includeExisting }, filesFound: 0 });
    appendLog('INFO scan démarré: ' + options.devicePath + ' (session ' + id + ')');

    let batch = [];
    let total = 0;
    let doneSent = false;
    let lastOffset = 0;
    let lastMetaWrite = 0;
    const flush = () => {
      if (batch.length && !sender.isDestroyed()) sender.send('scan:files-batch', batch);
      batch = [];
    };
    const flushTimer = setInterval(flush, 150);
    const finish = (data) => {
      if (doneSent) return;
      doneSent = true;
      clearInterval(flushTimer); flush();
      clearTimeout(current && current.killTimer);
      current = null;
      try { fs.unlinkSync(reqFile); } catch (_) {}
      writeMeta(id, { status: data.error ? 'error' : (data.stopped ? 'stopped' : 'complete'), ended: new Date().toISOString(),
        filesFound: data.filesFound != null ? data.filesFound : total, engines: data.engines || [], error: data.error || null,
        lastOffset: (data.stopped || data.error) ? lastOffset : 0 });
      if (!sender.isDestroyed()) sender.send('scan:done', Object.assign({ sessionId: id }, data));
    };
    attachJsonLines(child, (ev, data) => {
      if (ev === 'file-found') { total++; batch.push(slim(data)); if (batch.length >= 500) flush(); }
      else if (ev === 'progress') {
        if (data && data.engine === 'carve' && data.offset) {
          lastOffset = data.offset;
          if (Date.now() - lastMetaWrite > 8000) { lastMetaWrite = Date.now(); writeMeta(id, { lastOffset }); }
        }
        if (!sender.isDestroyed()) sender.send('scan:progress', data);
      }
      else if (ev === 'layout') { if (!sender.isDestroyed()) sender.send('scan:layout', data); }
      else if (ev === 'warning') { if (!sender.isDestroyed()) sender.send('scan:warning', data); }
      else if (ev === 'done') { finish(data); }
    }, null, 'scan');
    child.on('error', (e) => { appendLog('ERROR moteur: ' + e.message); finish({ filesFound: total, error: e.message, engineMissing: true }); });
    child.on('close', (code) => {
      if (!doneSent) {
        appendLog('WARN le moteur s\'est arrêté (code ' + code + ') sans message de fin');
        finish({ filesFound: total, error: code === 0 ? null : 'Le moteur s\'est arrêté de façon inattendue (code ' + code + '). Consultez le journal.' });
      }
    });
    return { started: true, sessionId: id };
  });

  ipcMain.handle('scan:stop', () => ({ stopped: requestStop() }));

  // ---- Récupération par lots ----
  ipcMain.handle('scan:recover-batch', async (event, opts) => {
    if (current) return { success: false, error: 'Une opération est déjà en cours.' };
    opts = opts || {};
    const sender = event.sender;
    let reqFile;
    let child;
    try {
      reqFile = path.join(os.tmpdir(), 'lazarus-rec-' + process.pid + '-' + Date.now() + '.json');
      fs.writeFileSync(reqFile, JSON.stringify({
        sessionPath: sessionPathOf(opts.sessionId), ids: opts.ids || [],
        destination: opts.destination, structure: opts.structure || 'tree',
        verify: opts.verify !== false, device: opts.device, allowSameDisk: !!opts.allowSameDisk,
      }), 'utf8');
      child = spawnEngine('recover', ['--request-file', reqFile]);
    } catch (e) { return { success: false, error: e.message }; }
    current = { kind: 'recover', child, sender, killTimer: null };
    return await new Promise((resolve) => {
      let result = null;
      attachJsonLines(child, (ev, data) => {
        if (sender.isDestroyed()) return;
        if (ev === 'recover-progress') sender.send('recover:progress', data);
        else if (ev === 'recover-file-done') sender.send('recover:file-done', data);
      }, (o) => { result = o; }, 'recover');
      child.on('error', (e) => { cleanup(); resolve({ success: false, error: e.message }); });
      child.on('close', (code) => {
        cleanup();
        resolve(result || { success: false, error: 'La récupération s\'est interrompue (code ' + code + ')' });
      });
      function cleanup() { clearTimeout(current && current.killTimer); current = null; try { fs.unlinkSync(reqFile); } catch (_) {} }
    });
  });

  // Compatibilité : récupération d'un seul fichier
  ipcMain.handle('scan:recover', async (event, devicePath, file, outputDir) => {
    if (!file) return { success: false, message: 'Aucun fichier' };
    return await runSingleRecover(event, devicePath, file, outputDir);
  });

  async function runSingleRecover(event, devicePath, file, outputDir) {
    if (current) return { success: false, message: 'Une opération est déjà en cours.' };
    try {
      const res = await runEngineJson('recover', [], 6 * 3600 * 1000, {
        sessionPath: sessionPathOf(), ids: [file.id], destination: outputDir || path.join(os.homedir(), 'LazarusRecovered'),
        structure: 'flat', verify: true, device: devicePath || file.device || undefined });
      const first = res.results && res.results[0];
      if (res.blocked) return { success: false, blocked: true, message: res.error };
      return { success: !!(first && first.success), outputPath: first && first.outputPath, message: (first && first.error) || res.error,
        md5: first && first.md5, sha256: first && first.sha256, integrity: first && first.integrity, health: file.health };
    } catch (e) { return { success: false, message: e.message }; }
  }

  ipcMain.handle('scan:check-dest', async (_e, device, destination) => {
    try { return await runEngineJson('check-dest', [], 40000, { device, destination }); }
    catch (e) { return { safe: true, error: e.message }; }
  });

  // ---- Aperçu ----
  ipcMain.handle('scan:preview-record', async (_e, record, maxBytes) => {
    try {
      return await runEngineJson('preview-record', [], 90000, { sessionPath: sessionPathOf(), id: record && record.id,
        maxBytes: maxBytes || 262144, device: (record && record.device) || undefined });
    }
    catch (e) { return { success: false, message: e.message }; }
  });
  ipcMain.handle('scan:thumbs', async (_e, ids) => {
    try { return await runEngineJson('thumbs', [], 120000, { sessionPath: sessionPathOf(), ids: (ids || []).slice(0, 48) }); }
    catch (e) { return { success: false, thumbs: [], message: e.message }; }
  });
  ipcMain.handle('scan:preview-file', async (_e, filePath, maxBytes) => {
    if (!filePath) return { success: false, message: 'Chemin manquant' };
    try { return await runEngineJson('preview', ['--file', String(filePath), '--max-bytes', String(maxBytes || 65536)], 30000); }
    catch (e) { return { success: false, message: e.message }; }
  });

  ipcMain.handle('scan:analyze-health', async (_e, file) => {
    try { return await runEngineJson('analyze', ['--file-json', JSON.stringify(file || {})], 15000); }
    catch (e) { return (file && file.health) || {}; }
  });

  // ---- Réparation (moteur intégré : aucun serveur, aucun modèle à télécharger) ----
  let aiCaps = null;
  ipcMain.handle('ai:health', async () => {
    if (!aiCaps) {
      try { const e = await runEngineJson('engines', [], 20000); aiCaps = Object.assign({ ok: !!(e.ai && e.ai.images) }, e.ai || {}); }
      catch (_) { return { ok: false }; }
    }
    return aiCaps;
  });

  // Fichier à réparer : déjà récupéré, ou extrait à la volée du support avant diagnostic
  async function ensureRecovered(event, file, outDir) {
    if (file.outputPath && fs.existsSync(file.outputPath)) return file.outputPath;
    const rec = await runSingleRecover(event, file.device, file, outDir);
    if (!rec.success) throw new Error(rec.message || 'Récupération impossible avant réparation');
    return rec.outputPath;
  }

  ipcMain.handle('scan:diagnose-file', async (event, args) => {
    args = args || {};
    const file = args.file || {};
    try {
      const src = await ensureRecovered(event, file, args.outputDir || path.join(os.homedir(), 'LazarusRecovered'));
      const d = await runEngineJson('diagnose', [], 120000, { path: src });
      return Object.assign({}, d, { sourcePath: src });
    } catch (e) { return { success: false, message: e.message }; }
  });

  ipcMain.handle('scan:repair-file', async (event, args) => {
    args = args || {};
    const file = args.file || {};
    const outDir = args.outputDir || path.join(os.homedir(), 'LazarusRecovered');
    try {
      const src = args.sourcePath && fs.existsSync(args.sourcePath) ? args.sourcePath : await ensureRecovered(event, file, outDir);
      const reference = args.reference && fs.existsSync(args.reference) ? args.reference : '';
      const out = Object.assign({ health: file.health },
        await runEngineJson('fix', [], 900000, { path: src, outputDir: path.dirname(src), reference, enhance: !!args.enhance }));
      if (out.success && out.repaired) {
        const h = Object.assign({}, file.health || {});
        h.score = Math.min(100, (h.score || 50) + 25); h.repairMode = Math.max(0, (h.repairMode || 0) - 1);
        h.label = 'Réparé'; h.headerOk = true; out.health = h;
      }
      return out;
    } catch (e) { return { success: false, message: e.message }; }
  });

  // ---- Clichés instantanés, imagerie ----
  ipcMain.handle('scan:vss-list', async () => {
    try { return await runEngineJson('vss-list', [], 40000); } catch (_) { return []; }
  });

  ipcMain.handle('scan:image-disk', async (event, opts) => {
    if (!opts || !opts.device || !opts.outputImage) return { success: false, message: 'Source ou destination manquante' };
    if (current) return { success: false, message: 'Une opération est déjà en cours.' };
    const sender = event.sender;
    let child; let reqFile;
    try {
      reqFile = path.join(os.tmpdir(), 'lazarus-img-' + process.pid + '-' + Date.now() + '.json');
      fs.writeFileSync(reqFile, JSON.stringify({ device: opts.device, outputImage: opts.outputImage, start: opts.start || 0, length: opts.length || null }));
      child = spawnEngine('image-disk', ['--request-file', reqFile]);
    } catch (e) { return { success: false, message: e.message }; }
    current = { kind: 'image', child, sender, killTimer: null };
    return await new Promise((resolve) => {
      let result = null;
      attachJsonLines(child, (ev, data) => { if (ev === 'progress' && !sender.isDestroyed()) sender.send('image:progress', data); },
        (o) => { result = o; }, 'image');
      const end = (r) => { clearTimeout(current && current.killTimer); current = null; try { fs.unlinkSync(reqFile); } catch (_) {} resolve(r); };
      child.on('error', (e) => end({ success: false, message: e.message }));
      child.on('close', (code) => end(result || { success: false, message: 'Imagerie interrompue (code ' + code + ')' }));
    });
  });

  // ---- Rapport, auto-test ----
  ipcMain.handle('scan:generate-report', async (_e, opts) => {
    if (!opts || !opts.files || !opts.outputDir) return { success: false, message: 'Fichiers ou dossier manquant' };
    try {
      return await runEngineJson('report', [], 300000, { files: opts.files, device: opts.device || 'inconnu',
        scanStarted: opts.scanStarted || '', scanEnded: opts.scanEnded || '', outputDir: opts.outputDir });
    } catch (e) { return { success: false, message: e.message }; }
  });

  ipcMain.handle('scan:selftest', async (_e, volume) => {
    try { return await runEngineJson('selftest', ['--volume', String(volume || 'C:'), '--count', '30'], 15 * 60 * 1000); }
    catch (e) { return { success: false, error: e.message }; }
  });


  // ---- Outils d'investigation ------------------------------------------------------------------
  ipcMain.handle('tools:smart', async () => { try { return await runEngineJson('smart', [], 90000); } catch (e) { return []; } });
  ipcMain.handle('tools:hex', async (_e, device, offset, length) => {
    try { return await runEngineJson('hex-read', [], 30000, { device, offset, length }); } catch (e) { return { success: false, message: e.message }; }
  });
  ipcMain.handle('tools:export-range', async (_e, device, offset, length, dest) => {
    try { return await runEngineJson('export-range', [], 600000, { device, offset, length, dest }); } catch (e) { return { success: false, message: e.message }; }
  });
  ipcMain.handle('tools:raid-detect', async (_e, members, cacheMB) => {
    try { return await runEngineJson('raid-detect', [], 30 * 60 * 1000, { members, cacheMB }); } catch (e) { return { success: false, message: e.message }; }
  });
  ipcMain.handle('tools:bitlocker-probe', async (_e, device, start) => {
    try { return await runEngineJson('bitlocker-probe', [], 60000, { device, start }); } catch (e) { return { bitlocker: false, error: e.message }; }
  });
  ipcMain.handle('tools:partitions', async (_e, device) => {
    try { return await runEngineJson('partitions', [], 180000, { device }); } catch (e) { return { success: false, error: e.message }; }
  });

  ipcMain.handle('tools:search-start', async (event, opts) => {
    if (current) return { success: false, message: 'Une opération est déjà en cours.' };
    const sender = event.sender;
    let child; let reqFile;
    try {
      reqFile = path.join(os.tmpdir(), 'lazarus-search-' + process.pid + '-' + Date.now() + '.json');
      fs.writeFileSync(reqFile, JSON.stringify(opts || {}), 'utf8');
      child = spawnEngine('search', ['--request-file', reqFile]);
    } catch (e) { return { success: false, message: e.message }; }
    current = { kind: 'search', child, sender, killTimer: null };
    return await new Promise((resolve) => {
      let result = null; let batch = [];
      const flush = () => { if (batch.length && !sender.isDestroyed()) sender.send('search:hits', batch); batch = []; };
      const timer = setInterval(flush, 200);
      attachJsonLines(child, (ev, data) => {
        if (ev === 'hit') batch.push(data);
        else if (ev === 'progress' && !sender.isDestroyed()) sender.send('search:progress', data);
      }, (o) => { result = o; }, 'search');
      const end = (r) => { clearInterval(timer); flush(); clearTimeout(current && current.killTimer); current = null; try { fs.unlinkSync(reqFile); } catch (_) {} resolve(r); };
      child.on('error', (e) => end({ success: false, message: e.message }));
      child.on('close', (code) => end(result || { success: false, message: 'Recherche interrompue (code ' + code + ')' }));
    });
  });
  ipcMain.handle('tools:search-stop', () => ({ stopped: requestStop() }));

  // ---- Sessions sauvegardées ----
  ipcMain.handle('session:list', async () => {
    try {
      return fs.readdirSync(sessionsDir()).filter((f) => f.endsWith('.meta.json')).map((f) => {
        try { return JSON.parse(fs.readFileSync(path.join(sessionsDir(), f), 'utf8')); } catch (_) { return null; }
      }).filter(Boolean).sort((a, b) => String(b.started).localeCompare(String(a.started)));
    } catch (_) { return []; }
  });

  ipcMain.handle('session:load', async (event, id) => {
    const safe = String(id || '').replace(/[^0-9A-Za-z\-_]/g, '');
    const p = path.join(sessionsDir(), safe + '.jsonl');
    if (!safe || !fs.existsSync(p)) return { success: false, message: 'Session introuvable' };
    const sender = event.sender;
    activeSessionId = safe;
    const rl = require('readline').createInterface({ input: fs.createReadStream(p, { encoding: 'utf8' }), crlfDelay: Infinity });
    let batch = []; let n = 0;
    for await (const line of rl) {
      if (!line) continue;
      try { batch.push(slim(JSON.parse(line))); n++; } catch (_) { continue; }
      if (batch.length >= 2000) { if (!sender.isDestroyed()) sender.send('scan:files-batch', batch); batch = []; await new Promise((r) => setImmediate(r)); }
    }
    if (batch.length && !sender.isDestroyed()) sender.send('scan:files-batch', batch);
    let meta = {};
    try { meta = JSON.parse(fs.readFileSync(path.join(sessionsDir(), safe + '.meta.json'), 'utf8')); } catch (_) {}
    return { success: true, count: n, meta };
  });

  ipcMain.handle('session:delete', async (_e, id) => {
    const safe = String(id || '').replace(/[^0-9A-Za-z\-_]/g, '');
    for (const ext of ['.jsonl', '.meta.json']) { try { fs.unlinkSync(path.join(sessionsDir(), safe + ext)); } catch (_) {} }
    return true;
  });
}

function stopEverything() {
  if (current) { try { current.child.kill('SIGKILL'); } catch (_) {} current = null; }
  if (driveWatchTimer) clearInterval(driveWatchTimer);
}

module.exports = { setupScanIPC, setupDriveWatcher, stopEverything, appendLog, getEngine, getIpcDir };

'use strict';

const { app, BrowserWindow, ipcMain, dialog, shell, Menu, Tray, nativeImage, Notification } = require('electron');
const path = require('path');
const os = require('os');
const fs = require('fs');
const { autoUpdater } = require('electron-updater');
const Store = require('electron-store');
const store = new Store();

const { setupLicenseIPC } = require('./ipc/license');
const { setupScanIPC, setupDriveWatcher, stopEverything } = require('./ipc/scan');
const { setupPaymentIPC } = require('./ipc/payment');

const isDev = process.env.NODE_ENV === 'development' || process.argv.includes('--dev');
const RENDERER_URL = isDev ? 'http://localhost:3000' : null;

if (!isDev) {
  // Keep production logs readable by hiding noisy Node deprecation warnings.
  process.noDeprecation = true;
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

let mainWindow = null;
let tray = null;
let isQuitting = false;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    frame: false,
    titleBarStyle: 'hidden',
    trafficLightPosition: { x: 20, y: 20 },
    backgroundColor: '#0A0A0F',
    show: false,
    icon: path.join(__dirname, '../assets/icons/icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
    },
  });

  // Aucune navigation ni fenêtre externe depuis l'interface (défense en profondeur)
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith('file://') && !url.startsWith('http://localhost:3000')) e.preventDefault();
  });

  if (RENDERER_URL) {
    mainWindow.loadURL(RENDERER_URL);
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    mainWindow.loadFile(path.join(__dirname, '../renderer/dist/index.html'));
  }

  // If renderer crashes before ready-to-show, force showing the window anyway.
  const forceShowTimer = setTimeout(() => {
    if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) {
      mainWindow.show();
    }
  }, 4000);

  mainWindow.once('ready-to-show', () => {
    clearTimeout(forceShowTimer);
    mainWindow.show();
    if (!isDev) checkForUpdates();
  });

  mainWindow.webContents.on('did-fail-load', async (_e, code, desc, url) => {
    console.error('Renderer failed to load:', code, desc, url);
    if (!mainWindow || mainWindow.isDestroyed()) return;
    try {
      await mainWindow.loadFile(path.join(__dirname, 'boot-error.html'), {
        query: {
          code: String(code ?? ''),
          reason: String(desc ?? ''),
          url: String(url || 'n/a'),
        },
      });
    } catch (err) {
      // Last-resort fallback if the local error page is unavailable.
      await mainWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('Lazarus Core failed to load UI.'));
    }
    mainWindow.show();
  });

  mainWindow.webContents.on('render-process-gone', (_e, details) => {
    console.error('Renderer process gone:', details);
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  ipcMain.on('win:minimize', () => mainWindow?.minimize());
  ipcMain.on('win:maximize', () => {
    if (mainWindow?.isMaximized()) mainWindow.unmaximize();
    else mainWindow?.maximize();
  });
  ipcMain.on('win:close', () => mainWindow?.close());
}

function setupTray() {
  if (tray) return;
  let icon;
  try {
    icon = nativeImage.createFromPath(path.join(__dirname, '../assets/icons/icon.png')).resize({ width: 16, height: 16 });
  } catch (_e) {
    icon = nativeImage.createEmpty();
  }

  tray = new Tray(icon);
  tray.setToolTip('Lazarus Core');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show', click: () => { if (mainWindow) mainWindow.show(); } },
    {
      label: 'Quit',
      click: () => {
        isQuitting = true;
        if (tray) {
          tray.destroy();
          tray = null;
        }
        app.quit();
      },
    },
  ]));
  tray.on('double-click', () => { if (mainWindow) mainWindow.show(); });
}

app.whenReady().then(async () => {
  createWindow();
  setupTray();

  setupLicenseIPC(ipcMain, store);
  setupScanIPC(ipcMain);
  setupDriveWatcher(mainWindow);
  setupPaymentIPC(ipcMain, store);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('before-quit', () => {
  isQuitting = true;
  stopEverything();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('second-instance', () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  } else {
    createWindow();
  }
});

function checkForUpdates() {
  autoUpdater.checkForUpdatesAndNotify().catch(console.error);
  autoUpdater.on('update-available', (info) => {
    mainWindow?.webContents.send('update:available', info);
  });
  autoUpdater.on('update-downloaded', (info) => {
    mainWindow?.webContents.send('update:ready', info);
  });
}

ipcMain.on('update:install', () => {
  autoUpdater.quitAndInstall();
});

ipcMain.handle('dialog:openFolder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('dialog:saveFile', async (_, defaultName) => {
  const result = await dialog.showSaveDialog(mainWindow, {
    defaultPath: path.join(os.homedir(), defaultName || 'recovered'),
  });
  return result.canceled ? null : result.filePath;
});

ipcMain.handle('dialog:openFile', async (_, opts) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: (opts && opts.filters) || [
      { name: 'Images disque', extensions: ['img', 'dd', 'raw', 'bin', 'iso', 'vhd', 'e01'] },
      { name: 'Tous les fichiers', extensions: ['*'] },
    ],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('shell:openPath', async (_, p) => shell.openPath(p));
ipcMain.handle('shell:showItem', async (_, p) => { shell.showItemInFolder(p); return true; });
ipcMain.handle('app:getVersion', () => app.getVersion());
ipcMain.handle('app:getPlatform', () => process.platform);
ipcMain.handle('app:getSettings', () => store.get('settings', { threads: 0, bufferMB: 4, outputDir: '' }));
ipcMain.handle('app:setSettings', (_, s) => { store.set('settings', s); return true; });

ipcMain.on('app:scan-done', (_, data) => {
  const hist = store.get('scanHistory', []);
  hist.unshift({
    id: Date.now(),
    date: new Date().toISOString(),
    filesFound: data.filesFound || 0,
    drive: data.drive || '',
  });
  if (hist.length > 50) hist.splice(50);
  store.set('scanHistory', hist);

  try {
    if (Notification.isSupported()) {
      new Notification({
        title: 'Lazarus Core',
        body: 'Scan complete - ' + (data.filesFound || 0) + ' files found',
      }).show();
    }
  } catch (_e) {}
});

ipcMain.handle('history:get', () => store.get('scanHistory', []));
ipcMain.handle('history:clear', () => { store.delete('scanHistory'); return true; });

ipcMain.handle('app:export-files', async (_, data) => {
  const { files, format } = data;
  const ext = format === 'csv' ? '.csv' : '.json';
  const res = await dialog.showSaveDialog(mainWindow, {
    defaultPath: path.join(os.homedir(), 'lazarus-export' + ext),
    filters: format === 'csv'
      ? [{ name: 'CSV', extensions: ['csv'] }]
      : [{ name: 'JSON', extensions: ['json'] }],
  });
  if (res.canceled) return null;

  if (format === 'csv') {
    const q = (v) => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
    const header = 'nom,extension,taille,statut,sante,moteur,chemin,md5,sha256';
    const rows = files.map((f) => [
      q(f.name), q(f.extension), f.size || 0, f.status || 0, (f.health && f.health.score) || 0,
      q(f.source), q(f.path), q(f.md5), q(f.sha256),
    ].join(','));
    fs.writeFileSync(res.filePath, '﻿' + [header, ...rows].join('\r\n'), 'utf8');
  } else {
    fs.writeFileSync(res.filePath, JSON.stringify(files, null, 2), 'utf8');
  }

  return res.filePath;
});

ipcMain.on('app:tray-toggle', (_, enable) => {
  if (enable && !tray) setupTray();
  if (!enable && tray) {
    tray.destroy();
    tray = null;
  }
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show();
    mainWindow.focus();
  }
});

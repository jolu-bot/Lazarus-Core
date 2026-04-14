'use strict';

const { app, BrowserWindow, ipcMain, dialog, shell, Menu, Tray, nativeImage } = require('electron');
const path    = require('path');
const os      = require('os');
const fs      = require('fs');
const { autoUpdater } = require('electron-updater');
const Store   = require('electron-store');
const store   = new Store();

const { setupLicenseIPC }  = require('./ipc/license');
const { setupScanIPC }     = require('./ipc/scan');
const { setupPaymentIPC }  = require('./ipc/payment');
const { setupAIIPC }       = require('./ipc/ai');
const { startAIServer, stopAIServer } = require('./ai_process');

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;
const RENDERER_URL = isDev ? 'http://localhost:3000' : null;

// ─── Security: disable remote module ─────────────────────────────
app.disableHardwareAcceleration = false;

// ─── Single instance lock ─────────────────────────────────────────
if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

let mainWindow = null;
let tray       = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width:           1400,
    height:          900,
    minWidth:        1100,
    minHeight:       700,
    frame:           false,
    titleBarStyle:   'hidden',
    trafficLightPosition: { x: 20, y: 20 },
    backgroundColor: '#0A0A0F',
    show:            false,
    icon:            path.join(__dirname, '../assets/icons/icon.png'),
    webPreferences: {
      preload:            path.join(__dirname, 'preload.js'),
      contextIsolation:   true,
      nodeIntegration:    false,
      sandbox:            false,
      webSecurity:        true,
      allowRunningInsecureContent: false,
    },
  });

  if (RENDERER_URL) {
    mainWindow.loadURL(RENDERER_URL);
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    mainWindow.loadFile(path.join(__dirname, '../renderer/dist/index.html'));
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (!isDev) checkForUpdates();
  });

  mainWindow.on('closed', () => { mainWindow = null; });

  // Window controls IPC
  ipcMain.on('win:minimize', () => mainWindow?.minimize());
  ipcMain.on('win:maximize', () => {
    if (mainWindow?.isMaximized()) mainWindow.unmaximize();
    else mainWindow?.maximize();
  });
  ipcMain.on('win:close', () => mainWindow?.close());
}

// ─── App lifecycle ────────────────────────────────────────────────
app.whenReady().then(async () => {
  createWindow();
  setupLicenseIPC(ipcMain, store);
  setupScanIPC(ipcMain);
  setupPaymentIPC(ipcMain, store);
  setupAIIPC(ipcMain);

  // Start Python AI server
  try {
    await startAIServer();
  } catch (e) {
    console.warn('AI server not started:', e.message);
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  stopAIServer();
  if (process.platform !== 'darwin') app.quit();
});

app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

// ─── Auto Updater ─────────────────────────────────────────────────
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

// ─── Dialog helpers ───────────────────────────────────────────────
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

ipcMain.handle('shell:openPath', async (_, p) => {
  return shell.openPath(p);
});

ipcMain.handle('app:getVersion', () => app.getVersion());
ipcMain.handle('app:getPlatform', () => process.platform);

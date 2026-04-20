'use strict';

const { app, BrowserWindow, ipcMain, dialog, shell, Menu, Tray, nativeImage, Notification } = require('electron');
const path    = require('path');
const os      = require('os');
const fs      = require('fs');
const { autoUpdater } = require('electron-updater');
const Store   = require('electron-store');
const store   = new Store();

const { setupLicenseIPC }  = require('./ipc/license');
const { setupScanIPC, setupDriveWatcher } = require('./ipc/scan');
const { setupPaymentIPC }  = require('./ipc/payment');
const { setupAIIPC }       = require('./ipc/ai');
const { startAIServer, stopAIServer } = require('./ai_process');

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;
const RENDERER_URL = isDev ? 'http://localhost:3000' : null;

// â”€â”€â”€ Security: disable remote module â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
app.disableHardwareAcceleration = false;

// â”€â”€â”€ Single instance lock â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

// â”€â”€â”€ App lifecycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
app.whenReady().then(async () => {
  createWindow();
  setupLicenseIPC(ipcMain, store);
  setupScanIPC(ipcMain);
  setupDriveWatcher(mainWindow);
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

// â”€â”€â”€ Auto Updater â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

// â”€â”€â”€ Dialog helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

ipcMain.handle('app:getSettings', () => store.get('settings', { threads:0, bufferMB:4, outputDir:'' }));
ipcMain.handle('app:setSettings', (_, s) => { store.set('settings', s); return true; });
ipcMain.on('app:scan-done', (_, data) => {
  try {
    if (Notification.isSupported())
      new Notification({ title:'Lazarus Core', body:'Scan complete - ' + (data.filesFound||0) + ' files found' }).show();
  } catch(e) {}
});

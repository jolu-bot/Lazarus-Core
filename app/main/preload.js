'use strict';
const { contextBridge, ipcRenderer } = require('electron');

const VALID_SEND = new Set([
  'win:minimize', 'win:maximize', 'win:close', 'update:install', 'app:scan-done', 'app:tray-toggle',
]);
const VALID_INVOKE = new Set([
  'dialog:openFolder', 'dialog:saveFile', 'dialog:openFile', 'shell:openPath', 'shell:showItem',
  'app:getVersion', 'app:getPlatform', 'app:diag', 'app:relaunch-admin',
  'scan:start', 'scan:stop', 'scan:recover', 'scan:recover-batch', 'scan:check-dest', 'scan:enumerate-drives',
  'scan:analyze-health', 'scan:repair-file', 'scan:preview-file', 'scan:preview-record', 'scan:thumbs', 'scan:vss-list',
  'scan:image-disk', 'scan:generate-report', 'scan:selftest',
  'session:list', 'session:load', 'session:delete',
  'tools:smart', 'tools:hex', 'tools:export-range', 'tools:raid-detect', 'tools:bitlocker-probe', 'tools:partitions',
  'tools:search-start', 'tools:search-stop',
  'license:validate', 'license:get', 'license:activate',
  'app:getSettings', 'app:setSettings', 'app:export-files',
  'history:get', 'history:clear',
  'payment:createSession', 'payment:checkStatus',
  'ai:repair', 'ai:analyze', 'ai:health', 'ai:repair-audio', 'ai:repair-document',
]);
const VALID_ON = new Set([
  'update:available', 'update:ready',
  'scan:progress', 'scan:files-batch', 'scan:file-found', 'scan:done', 'scan:layout', 'scan:warning',
  'scan:drives-updated', 'scan:drive-connected', 'scan:drive-disconnected',
  'recover:progress', 'recover:file-done', 'image:progress', 'search:hits', 'search:progress',
]);

contextBridge.exposeInMainWorld('lazarus', {
  send: (ch, ...a) => {
    if (VALID_SEND.has(ch)) ipcRenderer.send(ch, ...a);
  },
  invoke: (ch, ...a) => {
    if (VALID_INVOKE.has(ch)) return ipcRenderer.invoke(ch, ...a);
    return Promise.reject(new Error('Canal invalide : ' + ch));
  },
  on: (ch, fn) => {
    if (!VALID_ON.has(ch)) return () => {};
    const sub = (_, ...a) => fn(...a);
    ipcRenderer.on(ch, sub);
    return () => ipcRenderer.removeListener(ch, sub);
  },
});

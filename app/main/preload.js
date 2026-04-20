'use strict';
const { contextBridge, ipcRenderer } = require('electron');

const VALID_SEND   = new Set(['win:minimize','win:maximize','win:close','update:install']);
const VALID_INVOKE = new Set([
  'dialog:openFolder','dialog:saveFile','shell:openPath',
  'app:getVersion','app:getPlatform',
  'scan:start','scan:stop','scan:recover','scan:enumerate-drives',
  'scan:analyze-health','scan:repair-file',
  'license:validate','license:get','license:activate',
  'payment:createSession','payment:checkStatus',
  'ai:repair','ai:analyze','ai:health',
]);
const VALID_ON = new Set([
  'update:available','update:ready',
  'scan:progress','scan:file-found','scan:done','scan:drives-updated',
]);

contextBridge.exposeInMainWorld('lazarus', {
  send: (ch, ...a) => {
    if (VALID_SEND.has(ch)) ipcRenderer.send(ch, ...a);
  },
  invoke: (ch, ...a) => {
    if (VALID_INVOKE.has(ch)) return ipcRenderer.invoke(ch, ...a);
    return Promise.reject(new Error('Invalid channel: ' + ch));
  },
  on: (ch, fn) => {
    if (!VALID_ON.has(ch)) return;
    const sub = (_, ...a) => fn(...a);
    ipcRenderer.on(ch, sub);
    return () => ipcRenderer.removeListener(ch, sub);
  },
});

'use strict';
const axios    = require('axios');
const FormData = require('form-data');
const fs       = require('fs');
const { AI_PORT, AI_SECRET } = require('../ai_process');

const AI_BASE = `http://127.0.0.1:${AI_PORT}`;

function setupAIIPC(ipcMain) {
  ipcMain.handle('ai:health', async () => {
    try {
      const r = await axios.get(`${AI_BASE}/health`, { timeout: 2000 });
      return { ok: true, ...r.data };
    } catch {
      return { ok: false };
    }
  });

  ipcMain.handle('ai:analyze', async (_, filePath) => {
    try {
      const form = new FormData();
      form.append('file', fs.createReadStream(filePath));
      const r = await axios.post(`${AI_BASE}/analyze`, form, {
        headers: { ...form.getHeaders(), 'x-api-key': AI_SECRET },
        timeout: 30000,
      });
      return { success: true, ...r.data };
    } catch (e) {
      return { success: false, message: e.message };
    }
  });

  ipcMain.handle('ai:repair', async (_, { filePath, enhance, useAI }) => {
    try {
      const form = new FormData();
      form.append('file', fs.createReadStream(filePath));
      const params = new URLSearchParams();
      if (enhance) params.set('enhance', 'true');
      if (useAI)   params.set('use_ai',  'true');

      const r = await axios.post(
        `${AI_BASE}/repair/image?${params}`,
        form,
        {
          headers: { ...form.getHeaders(), 'x-api-key': AI_SECRET },
          timeout: 120000,
        }
      );
      return r.data; // { success, image_b64, confidence }
    } catch (e) {
      return { success: false, message: e.message };
    }
  });
}

module.exports = { setupAIIPC };

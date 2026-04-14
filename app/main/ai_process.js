'use strict';
const { spawn } = require('child_process');
const path      = require('path');
const fs        = require('fs');
const app_root  = require('electron').app;

let aiProcess = null;
const AI_PORT  = process.env.LAZARUS_AI_PORT || '8765';
const AI_SECRET = process.env.LAZARUS_AI_SECRET || 'dev_only_secret_change_in_prod';

function getAIPythonPath() {
  const isPackaged = require('electron').app.isPackaged;
  if (isPackaged) {
    const resourcesPath = process.resourcesPath;
    return {
      script: path.join(resourcesPath, 'ai', 'server.py'),
      cwd:    path.join(resourcesPath, 'ai'),
    };
  }
  return {
    script: path.join(__dirname, '../../ai/server.py'),
    cwd:    path.join(__dirname, '../../ai'),
  };
}

async function startAIServer() {
  const { script, cwd } = getAIPythonPath();
  if (!fs.existsSync(script)) {
    console.warn('AI server script not found:', script);
    return;
  }

  const pythonBin = process.platform === 'win32' ? 'python' : 'python3';
  const env = {
    ...process.env,
    LAZARUS_AI_PORT:     AI_PORT,
    LAZARUS_AI_SECRET:   AI_SECRET,
    PYTHONUNBUFFERED:    '1',
  };

  aiProcess = spawn(pythonBin, [script], { cwd, env, stdio: 'pipe' });

  aiProcess.stderr.on('data', (d) => console.error('[AI]', d.toString()));
  aiProcess.on('exit', (code) => {
    console.log('[AI] process exited with code', code);
    aiProcess = null;
  });

  // Wait for server ready
  await new Promise((resolve) => {
    const http = require('http');
    let tries = 0;
    const check = () => {
      http.get(`http://127.0.0.1:${AI_PORT}/health`, (res) => {
        if (res.statusCode === 200) resolve();
        else retry();
      }).on('error', retry);
    };
    const retry = () => {
      if (++tries > 30) { resolve(); return; }
      setTimeout(check, 500);
    };
    setTimeout(check, 1000);
  });
}

function stopAIServer() {
  if (aiProcess) {
    aiProcess.kill('SIGTERM');
    aiProcess = null;
  }
}

module.exports = { startAIServer, stopAIServer, AI_PORT, AI_SECRET };

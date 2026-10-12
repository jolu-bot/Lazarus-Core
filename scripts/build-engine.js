'use strict';
/**
 * Gèle le moteur Python en exécutable autonome (PyInstaller) pour que l'application installée
 * ne dépende plus d'un Python installé sur la machine de l'utilisateur.
 *   node scripts/build-engine.js
 * Résultat : app/engine-bin/lazarus-engine(.exe) — embarqué par electron-builder dans resources/engine.
 */
const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const root = path.join(__dirname, '..');
const out = path.join(root, 'app', 'engine-bin');
const script = path.join(root, 'app', 'main', 'ipc', 'scan_backend.py');
const work = path.join(root, 'build', 'pyinstaller');
const py = process.env.LAZARUS_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

function run(args, label) {
  const r = spawnSync(py, args, { stdio: 'inherit', cwd: root });
  if (r.status !== 0) { console.error('Échec : ' + label); process.exit(r.status || 1); }
}

fs.mkdirSync(out, { recursive: true });
run(['-m', 'pip', 'install', '--quiet', '--upgrade', 'pyinstaller', '-r', path.join(path.dirname(script), 'requirements.txt')],
  'installation de PyInstaller et des dépendances du moteur');
run(['-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--console', '--name', 'lazarus-engine',
  '--distpath', out, '--workpath', work, '--specpath', work,
  '--paths', path.dirname(script), '--collect-submodules', 'engine',
  '--hidden-import', 'cryptography', '--exclude-module', 'tkinter', '--exclude-module', 'numpy', '--exclude-module', 'cv2',
  script], 'gel du moteur');
console.log('Moteur gelé dans', out);

'use strict';
/**
 * Gèle le moteur Python en application autonome (PyInstaller, mode « dossier ») : l'application installée ne dépend
 * ni d'un Python, ni de pip, ni de Node installés sur la machine de l'utilisateur.
 * Le mode dossier (et non fichier unique) évite de décompresser ~150 Mo à chaque lancement du moteur, qui est démarré
 * des dizaines de fois par session (analyse, miniatures, aperçus, outils).
 *   node scripts/build-engine.js
 * Résultat : app/engine-bin/lazarus-engine/lazarus-engine(.exe) — embarqué par electron-builder dans resources/engine.
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

fs.rmSync(path.join(out, 'lazarus-engine'), { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });
run(['-m', 'pip', 'install', '--quiet', '--upgrade', 'pyinstaller', '-r', path.join(path.dirname(script), 'requirements.txt')],
  'installation de PyInstaller et des dépendances du moteur');
const excludes = ['tkinter', 'matplotlib', 'scipy', 'pandas', 'IPython', 'pytest', 'setuptools', 'PIL'];
run(['-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--console', '--name', 'lazarus-engine',
  '--distpath', out, '--workpath', work, '--specpath', work,
  '--paths', path.dirname(script), '--collect-submodules', 'engine',
  '--hidden-import', 'cryptography', '--hidden-import', 'cv2', '--hidden-import', 'numpy',
  ...excludes.flatMap((m) => ['--exclude-module', m]),
  script], 'gel du moteur');

const exe = path.join(out, 'lazarus-engine', process.platform === 'win32' ? 'lazarus-engine.exe' : 'lazarus-engine');
if (!fs.existsSync(exe)) { console.error('Moteur introuvable après gel : ' + exe); process.exit(1); }
console.log('Moteur gelé :', exe);

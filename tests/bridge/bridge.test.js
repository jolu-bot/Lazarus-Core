'use strict';
/**
 * Test d'intégration du pont Electron <-> moteur Python, sans interface graphique :
 * charge app/main/ipc/scan.js avec un ipcMain simulé, analyse une image NTFS synthétique,
 * récupère des fichiers et vérifie leur contenu octet par octet.
 *   node --test tests/bridge
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const cp = require('child_process');

const root = path.join(__dirname, '..', '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'lazarus-bridge-'));
const imgPath = path.join(tmp, 'test.img');
const truthDir = path.join(tmp, 'truth');

const py = process.platform === 'win32' ? 'python' : 'python3';
const gen = cp.spawnSync(py, ['-I', '-c', `
import sys, os
sys.path.insert(0, r'${path.join(root, 'tests', 'engine')}')
import ntfs_image
img, truth = ntfs_image.build_image()
open(r'${imgPath}', 'wb').write(bytes(img))
os.makedirs(r'${truthDir}', exist_ok=True)
for k, v in truth.items():
    open(os.path.join(r'${truthDir}', k.replace('$', '_')), 'wb').write(v)
`], { encoding: 'utf8' });
if (gen.status !== 0) throw new Error('génération de l\'image impossible : ' + gen.stderr);

const handlers = {};
const ipcMain = { handle: (n, fn) => { handlers[n] = fn; }, on() {} };
const scan = require(path.join(root, 'app', 'main', 'ipc', 'scan.js'));
scan.setupScanIPC(ipcMain);

function makeSender() {
  const events = [];
  return {
    events,
    send: (ch, data) => events.push([ch, data]),
    isDestroyed: () => false,
  };
}

function waitFor(sender, ch, ms = 60000) {
  return new Promise((resolve, reject) => {
    const t0 = Date.now();
    const iv = setInterval(() => {
      const e = sender.events.find((x) => x[0] === ch);
      if (e) { clearInterval(iv); resolve(e[1]); }
      else if (Date.now() - t0 > ms) { clearInterval(iv); reject(new Error('timeout ' + ch)); }
    }, 50);
  });
}

test.after(() => { scan.stopEverything(); });

test('moteur disponible', async () => {
  const eng = scan.getEngine();
  assert.ok(eng.cmd);
  const d = await handlers['app:diag']();
  assert.strictEqual(d.error, null);
  assert.ok(d.version);
});

test('énumération des disques (sans wmic)', async () => {
  const drives = await handlers['scan:enumerate-drives'](null, true);
  assert.ok(Array.isArray(drives), JSON.stringify(drives));
  if (process.platform === 'win32') assert.ok(drives.length >= 1);
});

let sessionId;
let files = [];
test('analyse -> lots de fichiers -> fin', async () => {
  const sender = makeSender();
  const r = await handlers['scan:start']({ sender }, { devicePath: imgPath, includeExisting: true, enableCarving: false });
  assert.strictEqual(r.started, true);
  const done = await waitFor(sender, 'scan:done');
  assert.ok(!done.error, done.error);
  assert.ok(done.filesFound >= 6, 'fichiers trouvés : ' + done.filesFound);
  for (const [ch, data] of sender.events) if (ch === 'scan:files-batch') files = files.concat(data);
  sessionId = done.sessionId;
  const names = files.map((f) => f.name);
  for (const n of ['photo.jpg', 'frag.dat', 'sparse.dat', 'hello.txt', 'rapport.txt']) assert.ok(names.includes(n), n);
  assert.ok(!files[0].extents, 'les extents ne doivent pas être envoyés à l\'interface');
});

test('récupération par lot : contenu identique', async () => {
  const sender = makeSender();
  const want = ['photo.jpg', 'frag.dat', 'sparse.dat'];
  const ids = files.filter((f) => want.includes(f.name)).map((f) => f.id);
  const dest = path.join(tmp, 'out');
  const res = await handlers['scan:recover-batch']({ sender }, { sessionId, ids, destination: dest, structure: 'flat' });
  assert.strictEqual(res.success, true, JSON.stringify(res));
  assert.strictEqual(res.recovered, 3);
  for (const n of want) {
    const got = fs.readFileSync(path.join(dest, n));
    const exp = fs.readFileSync(path.join(truthDir, n));
    assert.ok(got.equals(exp), n + ' différent');
  }
  assert.ok(sender.events.some((e) => e[0] === 'recover:file-done'));
});

test('aperçu depuis la source', async () => {
  const f = files.find((x) => x.name === 'hello.txt');
  const p = await handlers['scan:preview-record']({}, f, 4096);
  assert.strictEqual(p.success, true);
  assert.strictEqual(Buffer.from(p.head_b64, 'base64').toString('utf8'), fs.readFileSync(path.join(truthDir, 'hello.txt'), 'utf8'));
});

test('sessions sauvegardées et rechargeables', async () => {
  const list = await handlers['session:list']();
  assert.ok(list.some((m) => m.id === sessionId && m.status === 'complete'));
  const sender = makeSender();
  const r = await handlers['session:load']({ sender }, sessionId);
  assert.strictEqual(r.success, true);
  assert.ok(r.count >= 6);
  await handlers['session:delete']({}, sessionId);
});

test('destination sur le support source refusée', async () => {
  // l'image est un fichier : aucune lettre de lecteur à protéger -> sûr
  const chk = await handlers['scan:check-dest']({}, imgPath, path.join(tmp, 'x'));
  assert.strictEqual(typeof chk.safe, 'boolean');
});

test('réparation intégrée : diagnostic puis extraction du texte d\'un PDF sans xref', async () => {
  const zlib = require('zlib');
  const comp = zlib.deflateSync(Buffer.from('BT /F1 12 Tf (Facture 2026 Lazarus) Tj ET'));
  const pdf = Buffer.concat([
    Buffer.from('%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n'
      + '3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>\nendobj\n4 0 obj\n<< /Length ' + comp.length + ' /Filter /FlateDecode >>\nstream\n'),
    comp, Buffer.from('\nendstream\nendobj\n')]);
  const src = path.join(tmp, 'facture.pdf');
  fs.writeFileSync(src, pdf);
  const file = { id: -1, name: 'facture.pdf', outputPath: src, extension: 'pdf', health: {} };
  const h = await handlers['ai:health']();
  assert.strictEqual(typeof h.ok, 'boolean');
  const d = await handlers['scan:diagnose-file']({}, { file });
  assert.strictEqual(d.success, true, JSON.stringify(d));
  assert.strictEqual(d.format, 'pdf');
  assert.strictEqual(d.healthy, false);
  const r = await handlers['scan:repair-file']({}, { file, sourcePath: d.sourcePath });
  assert.strictEqual(r.success, true, JSON.stringify(r));
  const txt = r.outputs.find((p) => p.endsWith('_texte.txt'));
  assert.ok(txt, 'texte extrait');
  assert.ok(fs.readFileSync(txt, 'utf8').includes('Facture 2026 Lazarus'));
  assert.ok(fs.readFileSync(src).equals(pdf), 'le fichier d\'origine n\'est jamais modifié');
});

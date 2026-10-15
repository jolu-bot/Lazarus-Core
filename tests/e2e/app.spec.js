const { test, expect, _electron: electron } = require('@playwright/test');
const path = require('path');

let app, page;
const consoleErrors = [];

test.beforeAll(async () => {
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;       // sinon Electron démarre comme un simple Node
  app = await electron.launch({
    args: [path.join(__dirname, '../../app/main/index.js')],
    env,
  });
  page = await app.firstWindow();
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => consoleErrors.push(e.message));
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2500);
});

test.afterAll(async () => {
  await app.close();
});

test('la fenêtre s\'ouvre avec le pont IPC', async () => {
  expect(await page.title()).toBe('Lazarus Core');
  expect(await page.evaluate(() => !!window.lazarus)).toBe(true);
});

test('la vue Analyse affiche la barre de contrôle', async () => {
  const text = await page.evaluate(() => document.body.innerText);
  expect(text).toContain('LAZARUS CORE');
  expect(text).toContain('Lancer l’analyse');
});

test('toutes les vues se chargent sans erreur', async () => {
  for (let i = 1; i <= 5; i++) {
    await page.evaluate((idx) => document.querySelectorAll('.w-16 button')[idx].click(), i);
    await page.waitForTimeout(300);
  }
  expect(consoleErrors).toEqual([]);
});

test('l\'énumération des disques répond', async () => {
  const drives = await page.evaluate(() => window.lazarus.invoke('scan:enumerate-drives', true));
  expect(Array.isArray(drives)).toBe(true);
});

test('la réparation intégrée est disponible (aucun serveur externe)', async () => {
  const h = await page.evaluate(() => window.lazarus.invoke('ai:health'));
  expect(h.ok).toBe(true);
  expect(h.images).toBe(true);
});

test('l\'onglet « Réparer un fichier » est proposé dans les outils', async () => {
  await page.evaluate(() => document.querySelectorAll('.w-16 button')[2].click());
  await page.waitForTimeout(400);
  expect(await page.evaluate(() => document.body.innerText)).toContain('Réparer un fichier');
});

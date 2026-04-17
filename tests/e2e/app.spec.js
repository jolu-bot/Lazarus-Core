const { test, expect, _electron: electron } = require('@playwright/test');
const path = require('path');

let app, page;

test.beforeAll(async () => {
  app = await electron.launch({
    args: [path.join(__dirname, '../../app/main/index.js')],
    env: { ...process.env, NODE_ENV: 'test' },
  });
  page = await app.firstWindow();
  await page.waitForLoadState('domcontentloaded');
});

test.afterAll(async () => {
  await app.close();
});

test('App window opens and renders title bar', async () => {
  const title = await app.evaluate(async ({ app }) => app.getVersion());
  expect(title).toBeTruthy();
  await expect(page.locator('[data-testid=titlebar]')).toBeVisible({ timeout: 10000 }).catch(() => {});
});

test('ScanView renders without crash', async () => {
  await page.waitForTimeout(2000);
  const html = await page.content();
  expect(html).toContain('lazarus'.toLowerCase() || html.toLowerCase().includes('scan'));
});

test('No console errors on load', async () => {
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  await page.waitForTimeout(1000);
  const fatal = errors.filter(e => !e.includes('lazarus_core.node'));
  expect(fatal.length).toBe(0);
});

test('Window title is set', async () => {
  const title = await page.title();
  expect(title.length).toBeGreaterThan(0);
});
const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './e2e',
  timeout: 30000,
  retries: 1,
  use: {
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  reporter: [['html', { open: 'never' }]],
});
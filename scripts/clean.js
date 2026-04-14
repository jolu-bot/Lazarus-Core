const fs   = require('fs');
const path = require('path');

const toClean = [
  'app/renderer/dist',
  'app/renderer/node_modules/.vite',
  'core/build',
];

for (const p of toClean) {
  const full = path.join(__dirname, '..', p);
  if (fs.existsSync(full)) {
    fs.rmSync(full, { recursive: true, force: true });
    console.log('Cleaned:', p);
  }
}
console.log('Clean done.');

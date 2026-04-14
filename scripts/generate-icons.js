/**
 * LAZARUS CORE – Icon Generator
 * Generates PNG icons for Electron from an SVG source.
 * Run: node generate-icons.js
 *
 * Requires: npm install -g sharp @electron/packager (or just sharp locally)
 * Alternatively: convert manually from the SVG in root folder.
 */
const path = require('path');
const fs   = require('fs');

// Check if sharp is available
let sharp;
try {
  sharp = require('sharp');
} catch {
  console.log('sharp not found. Install with: npm install sharp');
  console.log('Alternatively, use an online SVG→ICO converter with the SVG files in the root folder.');
  console.log('Required sizes: 16, 32, 48, 64, 128, 256, 512, 1024px');
  process.exit(0);
}

const SIZES     = [16, 32, 48, 64, 128, 256, 512, 1024];
const SVG_PATH  = path.join(__dirname, '..', '..', 'logo lazarus core.svg');
const OUT_DIR   = path.join(__dirname, '..', 'app', 'assets', 'icons');
const PUB_DIR   = path.join(__dirname, '..', 'app', 'renderer', 'public');

if (!fs.existsSync(SVG_PATH)) {
  console.error(`SVG not found: ${SVG_PATH}`);
  process.exit(1);
}

fs.mkdirSync(OUT_DIR, { recursive: true });
fs.mkdirSync(PUB_DIR, { recursive: true });

async function generate() {
  const svgData = fs.readFileSync(SVG_PATH);

  for (const size of SIZES) {
    const outFile = path.join(OUT_DIR, `icon-${size}.png`);
    await sharp(svgData).resize(size, size).png().toFile(outFile);
    console.log(`Generated ${size}x${size} → ${outFile}`);
  }

  // Main icon (256px) used by Electron tray + taskbar
  await sharp(svgData).resize(256, 256).png()
        .toFile(path.join(OUT_DIR, 'icon.png'));

  // Copy to renderer public
  await sharp(svgData).resize(256, 256).png()
        .toFile(path.join(PUB_DIR, 'icon.png'));

  console.log('\nIcon generation complete!');
  console.log('Note: Convert app/assets/icons/icon-256.png to .ico and .icns');
  console.log('  Windows ICO: https://convertio.co/png-ico/');
  console.log('  macOS ICNS:  iconutil (on Mac) or https://cloudconvert.com/png-to-icns');
}

generate().catch(console.error);

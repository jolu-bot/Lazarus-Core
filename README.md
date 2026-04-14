# 🔥 LAZARUS CORE — *Recover the Impossible*

> World-class data recovery software. Compete with R-Studio, Disk Drill, EaseUS.

---

## Architecture Overview

```
LAZARUS CORE/
├── core/                    ← C++17 Engine (native .node module)
│   ├── include/             ← Headers: types, parsers, carver
│   ├── src/
│   │   ├── disk/            ← Raw sector I/O (Windows + macOS/Linux)
│   │   ├── ntfs/            ← Full MFT + data run parser
│   │   ├── ext4/            ← Superblock + inode scanner
│   │   ├── apfs/            ← Container detection
│   │   ├── carver/          ← Signature-based file carving
│   │   ├── rebuilder/       ← File reconstruction from runs
│   │   └── scan_engine.cpp  ← Multi-threaded orchestrator
│   ├── binding.gyp          ← node-gyp build config
│   └── CMakeLists.txt       ← CMake build config
│
├── ai/                      ← Python AI Microservice (FastAPI)
│   ├── repair/
│   │   ├── image_repair.py  ← OpenCV inpainting + CLAHE
│   │   └── model.py         ← PyTorch U-Net autoencoder
│   ├── server.py            ← FastAPI endpoints
│   └── requirements.txt
│
├── app/                     ← Electron Desktop App
│   ├── main/
│   │   ├── index.js         ← Main process
│   │   ├── preload.js       ← Secure context bridge
│   │   ├── ai_process.js    ← Python server manager
│   │   └── ipc/
│   │       ├── scan.js      ← Scan IPC handler
│   │       ├── license.js   ← HMAC license system
│   │       ├── payment.js   ← Stripe integration
│   │       └── ai.js        ← AI service bridge
│   ├── renderer/            ← React + Vite + Tailwind UI
│   │   └── src/
│   │       ├── App.jsx
│   │       ├── stores/      ← Zustand state
│   │       └── components/
│   │           ├── ui/      ← TitleBar, Sidebar, ProgressBar
│   │           └── panels/  ← ScanView, FileList, PreviewPanel, LicenseView
│   ├── assets/              ← Icons + entitlements
│   └── package.json         ← Electron + electron-builder config
│
├── scripts/
│   ├── build-all.ps1
│   └── clean.js
└── package.json             ← Root monorepo scripts
```

---

## Quick Start

### Prerequisites
- **Node.js** 20+
- **Python** 3.10+
- **Visual Studio 2022** (Windows) or **Xcode** (macOS) for C++ build
- **node-gyp**: `npm install -g node-gyp`

### 1. Install Dependencies
```powershell
# All at once
npm run install:all

# Install Python AI dependencies
npm run install:ai
```

### 2. Build Native Module (C++)
```powershell
npm run build:native
# Copies .node file to app/native/
```

### 3. Development Mode
```powershell
npm run dev
```

### 4. Production Build
```powershell
# Windows
npm run build:win

# macOS
npm run build:mac
```

---

## Configuration

Copy `.env.example` to `.env` and fill in:

```env
LAZARUS_LICENSE_SECRET=your_strong_secret
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PRICE_PRO=price_...
LAZARUS_AI_SECRET=your_ai_secret
```

---

## Business Model

| Plan        | Price  | Features                                    |
|-------------|--------|---------------------------------------------|
| **Free**    | $0     | Scan + Preview                              |
| **Pro**     | $49    | Full recovery · NTFS/EXT4/APFS · Video      |
| **Pro+**    | $79    | AI repair · Deep carving · All Pro features |
| **Business**| $199   | Forensic tools · 3 licenses · Priority      |

---

## C++ Engine — Key Features

| Module            | Description                                          |
|-------------------|------------------------------------------------------|
| `DiskReader`      | Sector-level access, Windows IOCTL + POSIX           |
| `NTFSParser`      | Full MFT scan, data run decode, deleted file detect  |
| `Ext4Parser`      | Superblock + inode table + deletion date detection   |
| `ApfsParser`      | Container detection, volume enumeration              |
| `FileCarver`      | 11 signature types: JPEG,PNG,MP4,PDF,ZIP,MP3,GIF,AVI|
| `FileRebuilder`   | Cluster run reconstruction, sparse support           |
| `ScanEngine`      | Thread pool, parallel FS + carving, progress events  |

---

## AI Module

- **Image inpainting**: OpenCV TELEA inpainting on auto-detected corrupted regions
- **Enhancement**: CLAHE + fastNlMeans denoising
- **Deep reconstruction**: U-Net autoencoder (PyTorch) for fragment prediction
- **FastAPI server**: Callable from Electron via localhost HTTP with API key auth

---

## Security

- `contextIsolation: true` + `nodeIntegration: false` in Electron
- Whitelist-only IPC channels via preload.js
- Machine-bound license keys (HMAC-SHA256)
- AI server auth via `x-api-key` header
- Content-Security-Policy on renderer index.html
- Stripe server-side session creation (no client-side secret)

---

## Roadmap

### MVP (v1.0) — Current
- [x] NTFS full MFT scan
- [x] File carving engine
- [x] Electron UI with preview
- [x] License + payment system
- [x] AI image repair

### v1.5 — Pro
- [ ] APFS B-tree full implementation
- [ ] AI-assisted fragment ordering
- [ ] Video container reconstruction (moov atom rebuild)
- [ ] Resume interrupted scans

### v2.0 — Enterprise
- [ ] Disk image creation (.img / .E01)
- [ ] Hash verification (MD5/SHA256)
- [ ] Forensic report export (PDF)
- [ ] Cloud backup integration
- [ ] VSS snapshot support

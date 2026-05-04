# LAZARUS CORE — *Recover the Impossible*

> La stack de récupération de données la plus complète jamais construite en open source.  
> NTFS · FAT32 · exFAT · ext2/3/4 · APFS · VSS · AI Repair · Disk Imager · 60+ signatures

---

## Comparaison avec les leaders du marché

| Fonctionnalité | **Lazarus Core** | Wondershare Recoverit | Disk Drill | Recuva | R-Studio |
|---|:---:|:---:|:---:|:---:|:---:|
| **NTFS MFT multi-extent** | ✅ VCN + gap fill | ✅ | ✅ | ✅ | ✅ |
| **FAT12 / FAT16 / FAT32** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **exFAT** | ✅ | ✅ | ✅ | ❌ | ✅ |
| **ext2 / ext3 / ext4** | ✅ inode bitmap | ✅ | ✅ | ❌ | ✅ |
| **APFS** | ✅ détection + carving | ✅ | ✅ | ❌ | ✅ |
| **VSS Shadow Copies** | ✅ | ❌ | ❌ | ❌ | ✅ |
| **Disk Imager bad-sector** | ✅ | ✅ (payant) | ✅ (payant) | ❌ | ✅ |
| **Raw carving (60+ sigs)** | ✅ | ✅ 550+ | ✅ 400+ | ✅ ~25 | ✅ |
| **AI inpainting image** | ✅ TELEA+NS+boundary | ❌ | ❌ | ❌ | ❌ |
| **AI repair audio MP3/WAV** | ✅ frame-par-frame | ❌ | ❌ | ❌ | ❌ |
| **AI repair PDF/ZIP/Office** | ✅ structure rebuild | ❌ | ❌ | ❌ | ❌ |
| **Réparation binaire réelle** | ✅ 12 formats | partielle | partielle | ❌ | partielle |
| **Hex preview live** | ✅ | ❌ | ❌ | ❌ | ✅ |
| **Open source** | ✅ | ❌ | ❌ | ✅ (abandonné) | ❌ |
| **Gratuit sans limite scan** | ✅ | ❌ | ❌ | ✅ | ❌ |
| **Prix récupération** | $0–$199 | $79.99/an | $89/an | gratuit | $79.99 |

### Avantages exclusifs de Lazarus Core

- **Seul outil open source** avec AI multi-méthode (boundary propagation + TELEA + NS blend)
- **VSS Shadow Copies** : accès aux versions précédentes sans suppression (absent de Wondershare, Disk Drill)
- **Réparation audio réelle** : resynchronisation frame-par-frame MP3, interpolation WAV — aucun concurrent ne le fait
- **Reconstruction ZIP/PDF/Office depuis structure binaire** — sans passer par un serveur cloud
- **Architecture extensible** : Python + FastAPI + Electron = plugins en 10 lignes

### Ce que les concurrents font encore mieux (honnêtement)

| Aspect | Concurrents | Lazarus Core |
|--------|-------------|--------------|
| Nombre de signatures carving | 400–550 | 60+ (à étendre) |
| APFS B-tree natif complet | Disk Drill, R-Studio | Détection + carving |
| Interface multi-langues | Oui (5–15 langues) | EN uniquement |
| Support NAS / RAID | R-Studio | Non |
| Certifications forensiques | R-Studio | Non |

---

## Architecture

```
LAZARUS CORE/
├── app/
│   ├── main/
│   │   ├── index.js          ← Main process Electron
│   │   ├── preload.js        ← contextBridge sécurisé (whitelist IPC)
│   │   ├── ai_process.js     ← Gestionnaire serveur FastAPI
│   │   └── ipc/
│   │       ├── scan.js       ← Handlers IPC scan/recover/repair/preview/imager/vss
│   │       ├── scan_backend.py  ← Moteur Python multi-FS (1400+ lignes)
│   │       ├── photorec_win.exe ← PhotoRec bundlé (asarUnpack)
│   │       ├── license.js    ← Licences HMAC-SHA256
│   │       ├── payment.js    ← Stripe
│   │       └── ai.js         ← Bridge AI
│   └── renderer/src/
│       ├── components/panels/
│       │   ├── ScanView.jsx
│       │   ├── FileList.jsx   ← Virtualisation @tanstack, filtres, export CSV/JSON
│       │   └── PreviewPanel.jsx ← Image/Vidéo/Audio + hex dump live + AI repair UI
│       └── stores/useAppStore.js ← Zustand
│
├── ai/
│   ├── server.py             ← FastAPI : /repair/image, /repair/audio, /repair/document
│   └── repair/
│       ├── model.py          ← Inpainting TELEA+NS+boundary propagation (onion-peeling)
│       ├── audio_repair.py   ← WAV interpolation + MP3 frame resync
│       └── document_repair.py ← ZIP Central Dir rebuild + PDF xref rebuild
│
└── core/                     ← Module natif C++ (addon optionnel)
```

---

## Moteurs de scan — `scan_backend.py`

| Moteur | Systèmes de fichiers | Méthode |
|--------|----------------------|---------|
| **NTFS MFT** | NTFS | Lecture directe MFT, fixup USA, resident + non-resident, multi-extent VCN |
| **FAT scanner** | FAT12/16/32/exFAT | Entrées `0xE5` supprimées, cluster chain FAT, BPB parser |
| **ext scanner** | ext2/3/4 | Superblock `0xEF53`, inode bitmap, blocs directs, dtime > 0 |
| **APFS scanner** | APFS | Détection container `NXSB`, raw carving intégré |
| **Raw carver** | Tout | 60+ signatures, sliding window, footer detection |
| **PhotoRec** | Tout | Wrapper si `photorec_win.exe` disponible |
| **VSS** | NTFS (Windows) | `vssadmin list shadows`, scan de chaque volume shadow |
| **Logical** | Tout | `$Recycle.Bin`, `Windows.old`, `TEMP` |

### Auto-détection FS

```python
# cmd_scan détecte automatiquement :
is_fat  → scan_fat_volume()
is_ext  → scan_ext_volume()
is_apfs → scan_apfs_volume()
else    → run_raw_carver() → run_logical_scan()
```

---

## Réparation binaire — 12 formats

| Format | Méthode |
|--------|---------|
| JPEG | SOI `FFD8` + EOI `FFD9` + reconstruction |
| PNG | CRC recalculé chunk par chunk |
| PDF | xref + trailer reconstruits depuis objets `N obj...endobj` |
| ZIP/DOCX/XLSX/PPTX/ODT | Central Directory reconstruit depuis Local File Headers |
| MP3 | Resync frame-par-frame, préserve ID3v2, tables bitrate/samplerate |
| WAV | Correction RIFF/data size headers |
| MP4/MOV/M4V | Réordonnancement moov avant mdat |
| DOC/XLS/PPT | Localisation signature OLE `D0CF11E0` |

---

## AI — Serveur FastAPI (`ai/server.py`, port dynamique)

| Route | Entrée | Sortie |
|-------|--------|--------|
| `POST /repair/image` | image (form-data) | image réparée base64 |
| `POST /repair/audio` | mp3/wav | fichier réparé base64 |
| `POST /repair/document` | pdf/zip/docx | fichier réparé base64 |
| `GET /health` | — | `{"status":"ok"}` |
| `POST /analyze` | image | score de corruption |

### Algorithme inpainting image

1. **Score < 5% corrompu** → TELEA seul
2. **5–25%** → blend TELEA (60%) + NS (40%)
3. **> 25%** → boundary propagation onion-peeling (60 itérations) + Gaussian feathering

---

## Disk Imager — récupération sur disques défaillants

```python
cmd_image_disk(device, output_image)
# - Clone secteur par secteur
# - Secteurs illisibles → 0x00 + comptage bad sectors
# - Arrêt après 200 erreurs consécutives
# - Émission progress en temps réel vers l'UI
```

---

## VSS Shadow Copies (Windows uniquement)

```python
enumerate_vss_shadows()  # → liste des volumes shadow via vssadmin
scan_vss_shadow(path)    # → fichiers récupérables depuis snapshot
```
IPC : `scan:vss-list` / scan intégré dans `scan:start`

---

## Preview UI — hex dump live

Pour tout fichier non-image/vidéo/audio sélectionné dans FileList :
- Appel IPC `scan:preview-file` → Python lit les 64 KB de tête
- Affichage hex dump 16 colonnes + ASCII côte à côte dans le panneau droit
- Pour les images : aperçu inline même avant récupération

---

## Quick Start

### Prérequis

- **Node.js** 20+
- **Python** 3.10+ avec `.venv` à la racine
- **Visual Studio 2022** (pour le module natif C++ optionnel)

### Démarrage développement

```powershell
# Installer les dépendances
Set-Location app; npm install

# Démarrer en mode dev
npm run dev
```

### Build production Windows

```powershell
Set-Location app
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
npm run build:win
# → dist-build/Lazarus Core Setup 1.0.1.exe
```

### Variables d'environnement

```env
LAZARUS_LICENSE_SECRET=your_strong_secret_min_32_chars
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PRICE_PRO=price_...
LAZARUS_AI_SECRET=your_ai_secret
```

---

## Sécurité

- `contextIsolation: true` + `nodeIntegration: false`
- Whitelist IPC stricte dans `preload.js` (`VALID_INVOKE`, `VALID_ON`, `VALID_SEND`)
- Licences HMAC-SHA256 liées à la machine
- Clé API sur le serveur AI (`x-api-key`)
- `requestedExecutionLevel: requireAdministrator` (accès disque brut)
- Stripe côté serveur uniquement

---

## Modèle économique

| Plan | Prix | Inclus |
|------|------|--------|
| **Free** | $0 | Scan · Preview hex · Récupération illimitée |
| **Pro** | $49 | + AI repair · Deep scan · Export CSV/JSON |
| **Pro+** | $79 | + Disk imager · VSS · Réparation audio/document |
| **Business** | $199 | + 3 licences · Rapport forensique · Priorité |

---

## Roadmap

### v1.0 — Actuel (commit `2d7b29c`)
- [x] NTFS MFT complet (fixup USA, resident, non-resident, multi-extent VCN)
- [x] FAT12/FAT16/FAT32/exFAT parser
- [x] ext2/ext3/ext4 inode scanner
- [x] APFS détection + raw carving
- [x] VSS Shadow Copies (Windows)
- [x] Disk Imager avec résilience bad sectors
- [x] Raw carving 60+ signatures
- [x] PhotoRec wrapper
- [x] Réparation binaire réelle (12 formats)
- [x] AI inpainting image (TELEA + NS + boundary propagation)
- [x] AI repair audio WAV/MP3
- [x] AI repair PDF/ZIP/Office
- [x] Preview UI hex dump live
- [x] FileList virtualisé + filtres multi-critères + export CSV/JSON
- [x] Licences HMAC + paiement Stripe

### v1.5 — En cours
- [ ] APFS B-tree natif complet (volume superblock + inode tree)
- [ ] Extension signatures carving à 200+ formats
- [ ] Reconstruction vidéo (moov atom rebuild + fragment MP4)
- [ ] Support NAS via partage réseau SMB
- [ ] Hash verification (MD5/SHA256) post-récupération
- [ ] Rapport forensique PDF

### v2.0 — Planifié
- [ ] Parseur EXT4 avec extents (extent tree niveau 2+)
- [ ] Support RAID 0/5 reconstruction logicielle
- [ ] Format image E01 (EnCase compatible)
- [ ] Interface multi-langues (FR/EN/ES/DE)
- [ ] Mode forensique avec journal d'audit signé

---

*Lazarus Core — parce que rien n'est vraiment perdu.*
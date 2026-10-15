# LAZARUS CORE — *Récupérez l'impossible*

Logiciel de récupération de données **en lecture seule** : Lazarus Core ne modifie jamais le support analysé.
Interface Electron/React (français et anglais) + moteur Python **intégré** (aucune installation de Python, Node ou de service
tiers), open source, sans limite artificielle, sans licence à acheter.

> **Données déjà perdues ? Lisez d'abord le [guide d'urgence](#-données-perdues--que-faire-maintenant).**

## Télécharger et utiliser

Deux exécutables autonomes sont produits par `.\scripts\build-all.ps1` (ou par le workflow GitHub « Build and Release ») :

| Fichier | Usage |
|---|---|
| `Lazarus Core-Setup-2.1.0.exe` | Installateur Windows (raccourcis, désinstallation) |
| `Lazarus Core-Portable-2.1.0.exe` | Un seul fichier, à lancer depuis une clé USB — **idéal pour ne rien écrire sur le disque à récupérer** |

Aucun prérequis : le moteur de récupération (Python, OpenCV, NumPy, cryptographie) est embarqué.
Pour lire un disque brut, cliquez sur **« Relancer en administrateur »** dans le bandeau rouge au premier lancement.

### Parcours guidé (« Assistant »)
Au premier lancement, l'**Assistant** demande ce qui s'est passé — fichiers supprimés, disque formaté, disque « RAW », photos
d'une carte SD, disque qui claque, fichier endommagé — et règle lui-même l'analyse (rapide / approfondie, types de fichiers,
clonage conseillé avant toute lecture d'un disque défaillant).

### Réparation intelligente intégrée
Aucun serveur, aucun modèle à télécharger : tout est dans le moteur. Menu **Outils → Réparer un fichier** ou bouton
*Réparation intelligente* dans l'aperçu d'un fichier récupéré. Le fichier d'origine n'est **jamais** modifié.

| Format | Ce qui est fait |
|---|---|
| **JPEG** | diagnostic (EOI absent, octets parasites, % du bas manquant) ; image tronquée complétée par estimation (jusqu'à 50 % de la hauteur, signalée comme telle) ; **greffe d'en-tête** depuis une photo de référence du même appareil quand l'en-tête est détruit |
| **PNG / BMP** | lignes de pixels complètes sauvées au bit près, CRC recalculés, lignes manquantes complétées |
| **Option « Améliorer »** | débruitage adaptatif (bruit mesuré), contraste local, netteté légère |
| **DOCX/XLSX/PPTX/ODT/ZIP** | répertoire central reconstruit ; si l'archive est irréparable, **texte du document extrait** à part |
| **PDF** | table xref reconstruite ; texte extrait des flux |
| **SQLite** | zones détruites sautées, toutes les lignes lisibles recopiées dans une base neuve |
| **MP3 / WAV / MP4** | resynchronisation des trames, en-têtes recalculés, atome `mdat` tronqué |
| **DOC/XLS et inconnus** | extraction des chaînes ASCII/UTF-16 lisibles |

> Une zone d'image « reconstruite » est une **estimation plausible**, pas la donnée d'origine : l'interface l'indique et affiche
> la part réellement retrouvée (« 66,7 % »). Aucun outil ne peut recréer des pixels qui n'existent plus.

---

## Validé sur de vrais volumes Windows (pas seulement des images de test)

Le script [`tests/tools/validate_on_real_volumes.py`](tests/tools/validate_on_real_volumes.py) crée de vrais disques virtuels
Windows (NTFS, FAT32, exFAT, BitLocker, VHD/VHDX dynamiques), y écrit des fichiers, en supprime, formate, puis compare **octet par
octet (SHA-256)** ce que le moteur récupère. Résultats mesurés :

| Scénario (vrai volume Windows 11) | Résultat |
|---|---|
| **Auto-test NTFS sur le vrai disque système** (40 fichiers lus par la MFT brute vs lecture normale) | **40 / 40 identiques** |
| FAT32 / exFAT : fichiers supprimés | **30 / 30**, noms d'origine conservés |
| FAT32 / exFAT : **après formatage rapide** | **60 / 60**, noms conservés (dossiers orphelins) |
| NTFS : fichiers supprimés + Corbeille (noms d'origine restitués) + fichiers **compressés** | tous ceux dont l'enregistrement MFT n'a pas été réutilisé |
| NTFS après formatage rapide / partition supprimée | fichiers à signature + **texte** (Windows 11 efface la MFT au formatage : aucun outil ne peut restituer noms et dossiers) |
| **BitLocker réel** (XTS-AES 128) : clé de récupération → fichiers | **tous les fichiers existants à l'identique**, mauvaise clé refusée |
| **VHD / VHDX dynamiques** lus directement (sans montage) | identique au volume monté |
| Carving : 358 fichiers réels (JPEG, PNG, MP4, PDF, DLL, EXE, CAB signés…) | **358 / 358** à la taille exacte, 0 faux positif |

Les enregistrements MFT réutilisés par Windows (Corbeille, fichiers `FVE2` de BitLocker…) ne peuvent pas être restitués par aucun
logiciel ; c'est une limite du système de fichiers, pas du moteur.

---

## Ce qui distingue Lazarus Core

| | Lazarus Core | Outils commerciaux typiques |
|---|---|---|
| **Sécurité des données** | Lecture seule ; refuse d'écrire sur le disque à récupérer ; clonage tolérant aux secteurs défectueux avec reprise | Parfois possible d'écrire sur la source par erreur |
| **Score de récupérabilité réel** | % de clusters réattribués lu dans le **bitmap réel** du volume (NTFS, FAT, exFAT, ext) | Estimation par type de fichier |
| **Carving** | Taille réelle par parseur de format (35+ formats), **espace non alloué uniquement**, **texte sans signature**, signatures **personnalisées**, reprise après interruption | Signatures simples, résultats pollués par les fichiers existants |
| **Recherche de contenu** | Recherche texte/hexa sur tout le support (UTF-8/UTF-16), extraction de la zone trouvée | Rare |
| **RAID virtuel** | RAID 0/1/5/10 + JBOD, **disque manquant reconstruit par parité**, **détection automatique** de la taille de bande, de l'ordre et de la parité | Réservé aux éditions « pro » |
| **BitLocker** | Déverrouillage par clé de récupération / mot de passe, à la volée, en lecture seule — **vérifié sur un vrai volume** | Partiel selon les outils |
| **Images** | Disque, `.img/.dd`, **VHD, VHDX, VMDK**, fichiers découpés `.001`, clichés **VSS** | Variable |
| **Santé** | S.M.A.R.T./fiabilité + conseil « clonez avant de récupérer » | Rarement intégré |
| **Traçabilité** | SHA-256 + MD5 de chaque fichier, vérification d'intégrité, rapport JSON/HTML | Limité |
| **Galerie photo** | Miniatures EXIF lues directement sur le disque, sans récupérer le fichier | Oui chez certains |
| **Coût / ouverture** | Open source, aucune limite de taille, interface en français | Licence annuelle, aperçu limité |

### Ce que les leaders (R-Studio, UFS Explorer) font encore mieux
RAID 6/ZFS/Btrfs/Synology, APFS/HFS+/ReFS par métadonnées, images E01/AFF, récupération réseau, journal ext3/4 (jbd2),
reconstruction de fichiers fragmentés sans métadonnées. Ces points figurent dans la feuille de route.

---

## Fonctionnalités

| Domaine | Détails |
|---|---|
| **NTFS** | MFT fragmentée (par ses propres *data runs*, `$MFTMirr` de secours), `$ATTRIBUTE_LIST`, fichiers creux, **compressés (LZNT1)**, taille initialisée, chiffrés (signalés), chemins complets avec contrôle des séquences, noms d'origine de la **Corbeille**, « MFT carving » (volume reformaté, anciens enregistrements retrouvés) |
| **FAT12/16/32, exFAT** | Fichiers supprimés, noms longs, dossiers supprimés, **dossiers orphelins après formatage rapide** (FAT : entrées `.`/`..` ; exFAT : ensembles d'entrées 0x85/0xC0/0xC1) |
| **ext2/3/4** | Inodes supprimés (extents, blocs indirects), noms dans le *slack* des répertoires, bitmap de blocs |
| **Partitions** | MBR, GPT (table de secours), étendues, **partitions perdues** retrouvées par signature |
| **Récupération** | Extraction par lots, arborescence conservée, noms sûrs, SHA-256, vérification d'intégrité (ZIP, SQLite, PNG, JPEG, PDF, MP4…), blocage si destination sur le disque source |
| **Réparation** | Diagnostic + réparation intégrés : JPEG/PNG tronqués (reconstruction signalée), greffe d'en-tête JPEG, PDF, Office/ZIP (+ extraction du texte), SQLite, MP3/WAV/MP4 — voir [Réparation intelligente](#réparation-intelligente-intégrée) |
| **Sessions** | Chaque analyse est sauvegardée ; on peut la rouvrir ou **la reprendre** après un arrêt |
| **Outils** | Réparer un fichier · Santé des disques · RAID virtuel · BitLocker · Recherche de contenu · Explorateur hexadécimal |
| **Assistant** | Parcours guidé par situation (supprimé, formaté, RAW, carte SD, disque défaillant, fichier abîmé) |
| **Auto-test** | `Paramètres → Auto-test du moteur NTFS` compare 30 fichiers du vrai disque (SHA-256) |

### Limites
- **SSD avec TRIM** : les blocs supprimés sont effacés par le contrôleur — irrécupérables.
- **Windows 11 efface la MFT au formatage rapide** d'un volume NTFS : seuls les fichiers à signature (et le texte) sont retrouvés, sans noms.
- **BitLocker** : XTS-AES 128/256 (Windows 10+) ; les volumes AES-CBC + diffuseur (Vista/7) et le mode « espace utilisé seulement » pour le contenu supprimé ne sont pas gérés.
- **APFS, HFS+, ReFS** : détectés, carving seulement. **VHD/VHDX différentiels** : utilisez le disque fusionné.
- Le module C++ `core/` est expérimental et **n'est plus utilisé** (le moteur Python est la référence testée).

---

## 🚨 Données perdues : que faire maintenant

1. **Cessez d'utiliser le disque concerné.** Chaque écriture peut écraser définitivement vos fichiers. Si c'est le disque Windows, éteignez l'ordinateur.
2. **Ne récupérez jamais vers le même disque.** Branchez une clé USB / un disque externe assez grand. Lazarus Core refuse les destinations situées sur le disque analysé.
3. **Idéalement, travaillez hors ligne** : retirez le disque (boîtier USB) sur un autre PC, ou démarrez sur une clé Windows PE/Linux.
4. **Disque qui claque, lent, ou état « Dégradé » (Outils → Santé)** : *Clonage de disque* d'abord, puis analysez l'**image**.
5. **Analyse rapide** (fichiers supprimés, noms et dossiers) ; **approfondie** (+ carving de l'espace libre, partitions perdues, MFT détruite, texte).
6. Disque **BitLocker** retiré de son PC : *Outils → BitLocker* avec la clé de récupération (compte Microsoft : `aka.ms/myrecoverykey`).
7. Vous vous souvenez d'une phrase du document perdu ? *Outils → Recherche de contenu*.
8. Lancez l'application **en administrateur** (obligatoire pour l'accès disque brut).

---

## Démarrage

### Prérequis
Node.js 20+ · Python 3.8+ (développement ; l'installateur embarque un moteur autonome) · `pip install -r app/main/ipc/requirements.txt` (BitLocker)

### Développement
```powershell
cd app; npm install
cd renderer; npm install; cd ..
npm run dev            # terminal administrateur pour l'accès disque brut
```

### Tests
```powershell
npm test               # moteur (NTFS, FAT, exFAT, ext, carving, partitions, RAID, conteneurs, BitLocker, outils) + pont Electron↔Python
python tests/tools/validate_on_real_volumes.py   # (administrateur) validation sur de vrais volumes Windows
python tests/tools/validate_carver_on_real_files.py   # carving sur vos propres fichiers réels
```

### Mode console
```powershell
python app/main/ipc/scan_backend.py scan --request-file req.json      # {"device":"\\\\.\\C:","deepScan":true,"sessionPath":"s.jsonl"}
python app/main/ipc/scan_backend.py recover --request-file rec.json   # {"sessionPath":"s.jsonl","ids":[1,2],"destination":"E:\\Recup"}
python app/main/ipc/scan_backend.py smart | enumerate | vss-list | selftest --volume C:
```

### Exécutables Windows (installateur + portable)
```powershell
.\scripts\build-all.ps1          # tests, interface, moteur autonome (PyInstaller, mode dossier), installateur NSIS + portable
# résultat : app\dist-build\Lazarus Core-Setup-2.1.0.exe  et  Lazarus Core-Portable-2.1.0.exe
```
Le premier lancement du portable décompresse l'application (~25 s) ; l'installateur démarre instantanément.

---

## Architecture

```
app/main/ipc/
├─ scan.js            pont Electron : analyse, récupération par lots, clonage, sessions, outils, arrêt propre
├─ scan_backend.py    CLI du moteur (JSON ligne par ligne, « stop » sur stdin)
└─ engine/            moteur Python (lecture seule)
   devio  containers  raid  bitlocker      accès aux sources (disque, VHD/VHDX/VMDK, RAID, BitLocker)
   partitions  ntfs  fat  ext              systèmes de fichiers
   carver  sizers  tools                   carving, validateurs de format, recherche/hexa/miniatures
   recover  repair  imager  report  system  lznt1
app/renderer/         React + Zustand (fr/en), listes virtualisées (centaines de milliers d'éléments), galerie
server/  tests/engine  tests/bridge  tests/e2e  tests/tools
   (réparation : engine/aifix.py + inpaint.py — intégrée au moteur, plus aucun serveur ni modèle externe)
```

## Sécurité
`contextIsolation`, `sandbox`, CSP stricte, liste blanche IPC ; sources ouvertes en lecture seule ; noms récupérés assainis ;
rapports HTML échappés ; serveur de licences : clé admin obligatoire, comparaison à temps constant, aucun secret par défaut.
Plus de serveur HTTP local pour la réparation (ancienne surface d'attaque supprimée). `npm audit` : **0 vulnérabilité** sur
l'application, l'interface, le serveur et les tests ; l'audit est rejoué à chaque intégration continue et Dependabot surveille
npm, pip et GitHub Actions.

## Licence
Mode local gratuit par défaut. Serveur de licences et Stripe optionnels.

*Lazarus Core — parce que rien n'est vraiment perdu (tant qu'on n'écrit pas dessus).*

"""Éléments partagés par tous les moteurs : évènements JSON, enregistrements fichier, santé."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Dict, List, Optional

_emit_lock = threading.Lock()
STOP = threading.Event()     # demande d'arrêt propre (reçue sur stdin)

# Statuts d'un fichier
ST_ACTIVE = 0      # présent dans le système de fichiers
ST_DELETED = 1     # supprimé, métadonnées intactes
ST_FRAGMENTED = 2  # reconstitué / fragments possibles
ST_PARTIAL = 3     # données partiellement écrasées

SRC_FS = {'ntfs': 1, 'fat': 3, 'exfat': 4, 'ext': 2, 'apfs': 5, 'carve': 0, 'logical': 1, 'vss': 1}

TYPE_IMAGE, TYPE_VIDEO, TYPE_AUDIO, TYPE_DOC, TYPE_ARCHIVE, TYPE_OTHER = 1, 2, 3, 4, 5, 6

TYPE_MAP = {}
for _t, _exts in {
    TYPE_IMAGE: 'jpg jpeg png gif bmp tif tiff webp psd heic heif avif cr2 cr3 nef arw raf dng orf rw2 ico icns jp2 j2k svg xcf',
    TYPE_VIDEO: 'mp4 avi mov wmv mkv 3gp flv webm vob mpeg mpg m4v ts mts m2ts asf',
    TYPE_AUDIO: 'mp3 wav flac aac ogg m4a aiff aif amr mid midi wma opus',
    TYPE_DOC: 'pdf doc docx xls xlsx ppt pptx odt ods odp rtf ps pst ost eml msg vcf ics accdb mdb txt csv md html htm xml json one key pages numbers wpd',
    TYPE_ARCHIVE: 'zip rar 7z gz tar bz2 xz cab iso vhd vhdx vmdk vdi qcow2 dmg tgz lz zst',
}.items():
    for _e in _exts.split():
        TYPE_MAP[_e] = _t


def type_for_ext(ext: str) -> int:
    return TYPE_MAP.get((ext or '').lower(), TYPE_OTHER)


def emit(event: str, data: dict):
    line = json.dumps({'event': event, 'data': data}, ensure_ascii=True)
    with _emit_lock:
        sys.stdout.write(line + '\n')
        sys.stdout.flush()


def log(msg: str):
    with _emit_lock:
        sys.stderr.write('[LAZARUS] ' + msg + '\n')
        sys.stderr.flush()


def split_name(name: str):
    base = name.replace('\\', '/').rsplit('/', 1)[-1]
    ext = base.rsplit('.', 1)[-1].lower() if '.' in base.strip('.') else ''
    return base, ext


def compute_health(f: dict, seed: int = 0) -> dict:
    """Score de santé 0-100 déterministe, calculé à partir de données réelles."""
    conf = max(0.0, min(1.0, float(f.get('confidence') or 0)))
    st = int(f.get('status') or 0)
    score = round(conf * 100)
    ow = f.get('overwritten_pct')
    if isinstance(ow, (int, float)) and ow > 0:
        score = min(score, max(0, int(100 - ow)))
    if st == ST_DELETED:
        score = min(score, 96)
    elif st == ST_FRAGMENTED:
        score = min(score, 80)
    elif st == ST_PARTIAL:
        score = min(score, 55)
    rm = 0 if score >= 85 else 1 if score >= 70 else 2 if score >= 50 else 3
    labels = ['Excellent', 'Bon - réparation mineure', 'Dégradé - réparation requise', 'Critique - reconstruction']
    return {
        'score': score,
        'headerOk': conf >= 0.65,
        'structPct': 100 if st == ST_ACTIVE else max(0, min(100, score)),
        'dataPct': 100 if ow in (None, 0) else max(0, int(100 - ow)),
        'frags': len(f.get('extents') or []) or 1,
        'repairMode': rm,
        'label': labels[rm],
        'existsOnDisk': st == ST_ACTIVE,
    }


def merge_extents(extents: List[List[int]]) -> List[List[int]]:
    """Fusionne les extents consécutifs (hors zones creuses -1)."""
    out: List[List[int]] = []
    for off, ln in extents:
        if ln <= 0:
            continue
        if out and off >= 0 and out[-1][0] >= 0 and out[-1][0] + out[-1][1] == off:
            out[-1][1] += ln
        elif out and off < 0 and out[-1][0] < 0:
            out[-1][1] += ln
        else:
            out.append([off, ln])
    return out


class FileSink:
    """Numérote, enrichit et diffuse les fichiers trouvés ; journalise dans le fichier de session."""

    def __init__(self, device: str, session_path: Optional[str] = None, device_label: str = ''):
        self.device = device
        self.next_id = 0
        self.count = 0
        self.lock = threading.Lock()
        self._fh = None
        self.seen_keys = set()
        self.starts = set()
        if session_path:
            try:
                if os.path.exists(session_path):          # reprise : les identifiants continuent après le dernier enregistré
                    last = -1
                    with open(session_path, 'r', encoding='utf-8') as old:
                        for line in old:
                            try:
                                last = max(last, int(json.loads(line).get('id', -1)))
                            except (ValueError, AttributeError):
                                continue
                    self.next_id = last + 1
                os.makedirs(os.path.dirname(session_path), exist_ok=True)
                self._fh = open(session_path, 'a', encoding='utf-8')
            except OSError:
                self._fh = None

    def add(self, f: dict, dedupe_key=None) -> Optional[dict]:
        with self.lock:
            if dedupe_key is not None:
                if dedupe_key in self.seen_keys:
                    return None
                self.seen_keys.add(dedupe_key)
            f['id'] = self.next_id
            self.next_id += 1
            self.count += 1
        ex = f.get('extents')
        if ex and ex[0][0] >= 0:
            self.starts.add(ex[0][0])
        f.setdefault('device', self.device)
        f.setdefault('recoverable', True)
        f.setdefault('outputPath', '')
        base, ext = split_name(f.get('name', ''))
        f['name'] = f.get('name') or base
        f.setdefault('extension', ext)
        f.setdefault('type', type_for_ext(f['extension']))
        f.setdefault('fs', SRC_FS.get(f.get('source', ''), 0))
        f['mft_ref'] = f.get('mft_ref', f['id'])
        f['health'] = compute_health(f, f['id'])
        emit('file-found', f)
        if self._fh:
            try:
                self._fh.write(json.dumps(f, ensure_ascii=True) + '\n')
                if self.count % 50 == 0:
                    self._fh.flush()
            except OSError:
                pass
        return f

    def close(self):
        if self._fh:
            try:
                self._fh.flush()
                self._fh.close()
            except OSError:
                pass


class Progress:
    """Émet des évènements de progression limités à ~4 par seconde."""

    def __init__(self, engine: str, total_bytes: int = 0, sink: Optional[FileSink] = None):
        self.engine = engine
        self.total = total_bytes
        self.sink = sink
        self.t0 = time.time()
        self.last = 0.0
        self.base_pct = 0
        self.span_pct = 100

    def window(self, base: int, span: int):
        self.base_pct = base
        self.span_pct = span

    def update(self, done_bytes: int, current: str = '', force: bool = False, **extra):
        now = time.time()
        if not force and now - self.last < 0.25:
            return
        self.last = now
        frac = (done_bytes / self.total) if self.total else 0.0
        pct = self.base_pct + min(1.0, frac) * self.span_pct
        el = max(now - self.t0, 0.001)
        data = {
            'percent': round(min(99.0, pct), 1), 'finished': False, 'engine': self.engine,
            'filesFound': self.sink.count if self.sink else 0,
            'currentPath': current, 'bytesDone': int(done_bytes), 'bytesTotal': int(self.total),
            'sectorsScanned': int(done_bytes // 512), 'sectorsTotal': int(self.total // 512),
            'speed': round(done_bytes / el),
        }
        data.update(extra)
        emit('progress', data)

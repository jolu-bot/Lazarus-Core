"""Extraction des fichiers retrouvés : lecture des extents, décompression NTFS, hachage, vérification."""
from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import sqlite3
import struct
import time
import zipfile
from typing import Callable, Dict, List, Optional

from . import lznt1, sizers
from .common import STOP, emit, log
from .devio import DeviceError, Reader, open_reader

CHUNK = 4 * 1024 * 1024
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}


def load_records(session_path: str, ids) -> List[dict]:
    """Relit dans le fichier de session (JSONL) les enregistrements complets correspondant aux ids."""
    import json
    want = {int(i) for i in ids}
    out: List[dict] = []
    if not session_path or not os.path.isfile(session_path):
        return out
    with open(session_path, 'r', encoding='utf-8') as fh:
        for line in fh:
            if not want:
                break
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            rid = rec.get('id')
            if rid in want:
                want.discard(rid)
                out.append(rec)
    order = {int(i): n for n, i in enumerate(ids)}
    out.sort(key=lambda r: order.get(r.get('id'), 0))
    return out


def safe_component(s: str, fallback: str = '_') -> str:
    s = _INVALID.sub('_', s or '').strip().rstrip('. ')
    if s in ('', '.', '..'):
        return fallback
    if s.split('.')[0].upper() in _RESERVED:
        s = '_' + s
    if len(s) > 180:
        root, dot, ext = s.rpartition('.')
        s = (root[:170] + '.' + ext[:8]) if dot and len(ext) <= 8 else s[:180]
    return s


def safe_relpath(path: str) -> List[str]:
    parts = [safe_component(p) for p in re.split(r'[\\/]+', path or '') if p not in ('', '.')]
    return parts or ['fichier']


class RecordReader:
    """Lit le contenu logique d'un enregistrement (extents, résident, creux, NTFS compressé)."""

    def __init__(self, reader: Optional[Reader], rec: dict):
        self.r = reader
        self.rec = rec
        self.size = int(rec.get('size') or 0)
        self.extents: List[List[int]] = rec.get('extents') or []
        self.resident: Optional[bytes] = base64.b64decode(rec['resident_b64']) if rec.get('resident_b64') else None
        self.compressed = bool(rec.get('compressed'))
        vs = rec.get('valid_size')
        self.valid = int(vs) if isinstance(vs, int) and vs >= 0 else None
        self.unit = int(rec.get('cluster_size') or 4096) << int(rec.get('comp_unit') or 4)
        self._starts: List[int] = []
        acc = 0
        for _o, ln in self.extents:
            self._starts.append(acc)
            acc += ln
        self.total = acc
        self._cache_unit = -1
        self._cache = b''

    def _raw(self, off: int, n: int) -> bytes:
        """Lecture dans le flux d'extents (sans décompression)."""
        import bisect
        out = bytearray()
        if not self.extents:
            return b'\x00' * n
        i = max(0, bisect.bisect_right(self._starts, off) - 1)
        pos = off
        end = off + n
        while pos < end and i < len(self.extents):
            eo, el = self.extents[i]
            es = self._starts[i]
            if pos >= es + el:
                i += 1
                continue
            take = min(end, es + el) - pos
            if eo < 0:
                out += b'\x00' * take
            else:
                data = self.r.read_at(eo + (pos - es), take) if self.r else b''
                out += data.ljust(take, b'\x00')
            pos += take
            i += 1
        if pos < end:
            out += b'\x00' * (end - pos)
        return bytes(out)

    def _unit_data(self, u: int) -> bytes:
        if u == self._cache_unit:
            return self._cache
        a, b = u * self.unit, (u + 1) * self.unit
        # découpe de l'unité en morceaux creux / réels
        sparse = real = 0
        pieces = []
        for (eo, el), es in zip(self.extents, self._starts):
            lo, hi = max(a, es), min(b, es + el)
            if lo < hi:
                pieces.append((eo, lo, hi))
                if eo < 0:
                    sparse += hi - lo
                else:
                    real += hi - lo
        explicit_sparse = sparse               # creux déclarés par les data runs (hors fin de flux)
        covered = sparse + real
        if covered < self.unit:
            sparse += self.unit - covered
        if real == 0:
            data = b'\x00' * self.unit
        elif explicit_sparse == 0:
            data = self._raw(a, self.unit)     # unité entièrement allouée = non compressée
        else:
            comp = b''.join(self._raw(lo, hi - lo) for eo, lo, hi in pieces if eo >= 0)
            data = lznt1.decompress(comp, self.unit)
            data = data[:self.unit].ljust(self.unit, b'\x00')
        self._cache_unit, self._cache = u, data
        return data

    def read(self, off: int, n: int) -> bytes:
        n = max(0, min(n, self.size - off))
        if n <= 0:
            return b''
        data = self._read(off, n)
        if self.valid is not None and off + len(data) > self.valid:
            keep = max(0, self.valid - off)
            data = data[:keep] + b'\x00' * (len(data) - keep)
        return data

    def _read(self, off: int, n: int) -> bytes:
        if self.resident is not None:
            return self.resident[off:off + n].ljust(n, b'\x00')
        if not self.compressed:
            return self._raw(off, n)
        out = bytearray()
        pos = off
        while pos < off + n:
            u = pos // self.unit
            data = self._unit_data(u)
            s = pos - u * self.unit
            take = min(len(data) - s, off + n - pos)
            out += data[s:s + take]
            pos += take
        return bytes(out)


class ReaderPool:
    def __init__(self):
        self._r: Dict[str, Reader] = {}

    def get(self, device: str) -> Reader:
        if device not in self._r:
            self._r[device] = open_reader(device)
        return self._r[device]

    def close(self):
        for r in self._r.values():
            r.close()
        self._r = {}


def verify_file(path: str, ext: str) -> str:
    """'ok' | 'suspect' | 'corrompu' | 'inconnu' — contrôle rapide d'intégrité du fichier extrait."""
    ext = (ext or '').lower()
    try:
        size = os.path.getsize(path)
        if size == 0:
            return 'corrompu'
        if ext in ('zip', 'docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp', 'jar', 'apk', 'epub'):
            if not zipfile.is_zipfile(path):
                return 'corrompu'
            with zipfile.ZipFile(path) as z:
                bad = z.testzip()
            return 'ok' if bad is None else 'corrompu'
        if ext == 'sqlite' or ext == 'db':
            c = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
            try:
                r = c.execute('pragma quick_check').fetchone()
            finally:
                c.close()
            return 'ok' if r and r[0] == 'ok' else 'corrompu'
        sizer = {'jpg': sizers.jpeg, 'jpeg': sizers.jpeg, 'png': sizers.png, 'gif': sizers.gif, 'bmp': sizers.bmp,
                 'pdf': sizers.pdf, 'mp4': sizers.isobmff, 'mov': sizers.isobmff, 'm4a': sizers.isobmff,
                 'heic': sizers.isobmff, 'ogg': sizers.ogg, 'mp3': sizers.mp3, 'wav': sizers.riff,
                 'avi': sizers.riff, 'doc': sizers.ole2, 'xls': sizers.ole2, 'ppt': sizers.ole2,
                 'exe': sizers.pe, 'dll': sizers.pe, 'mkv': sizers.ebml, 'tif': sizers.tiff}.get(ext)
        if not sizer:
            return 'inconnu'
        r = Reader(path)
        try:
            res = sizer(sizers.WindowIO(r), 0, size)
        finally:
            r.close()
        if res is None:
            return 'corrompu'
        if res[0] == sizers.UNKNOWN:
            return 'suspect'
        if res[0] > size:
            return 'suspect'          # fichier tronqué
        return 'ok'
    except Exception as e:
        log(f'vérification {path}: {e}')
        return 'inconnu'


def drives_hosting(device: str) -> List[str]:
    """Lettres de lecteurs situées sur le disque physique `device` (pour éviter d'écraser la source)."""
    import subprocess
    letters: List[str] = []
    m = re.search(r'(?i)physicaldrive(\d+)', device or '')
    v = re.fullmatch(r'(?i)(?:\\\\\.\\)?([a-z]):\\?', (device or '').strip())
    if v:
        return [v.group(1).upper()]
    if m and os.name == 'nt':
        try:
            out = subprocess.check_output(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command',
                 f'(Get-Partition -DiskNumber {int(m.group(1))} -ErrorAction SilentlyContinue | '
                 f'Where-Object DriveLetter | ForEach-Object {{ $_.DriveLetter }}) -join ","'],
                text=True, timeout=15, creationflags=0x08000000)
            letters = [x.strip().upper() for x in out.strip().split(',') if x.strip()]
        except Exception:
            pass
    return letters


def check_destination(device: str, dest: str) -> dict:
    """Refuse (ou avertit) si la destination est sur le support à récupérer."""
    d = os.path.abspath(dest)
    drive = d[:1].upper() if len(d) > 1 and d[1] == ':' else ''
    hosting = drives_hosting(device)
    same = bool(drive and drive in hosting)
    free = 0
    try:
        os.makedirs(d, exist_ok=True)
        free = shutil.disk_usage(d).free
    except OSError:
        pass
    return {'safe': not same, 'sameDisk': same, 'freeBytes': free, 'drive': drive, 'sourceDrives': hosting,
            'reason': ("La destination est sur le disque à récupérer : écrire dessus peut détruire définitivement "
                       "les données perdues.") if same else ''}


def unique_path(p: str) -> str:
    if not os.path.exists(p):
        return p
    root, ext = os.path.splitext(p)
    for i in range(1, 100000):
        c = f'{root} ({i}){ext}'
        if not os.path.exists(c):
            return c
    return p


def recover_one(pool: ReaderPool, rec: dict, dest_root: str, structure: str = 'tree',
                verify: bool = True, device: Optional[str] = None,
                progress: Optional[Callable[[int, int], None]] = None) -> dict:
    t0 = time.time()
    name = safe_component(rec.get('name') or 'fichier')
    if structure == 'flat':
        rel = [name]
    else:
        src = {'ntfs': 'NTFS', 'fat': 'FAT', 'exfat': 'exFAT', 'ext': 'ext', 'carve': 'Carving'}.get(
            rec.get('source', ''), 'Autres')
        d = rec.get('dir') or ''
        rel = [src] + safe_relpath(d) if d else [src]
        rel = rel + [name]
    out_dir = os.path.join(dest_root, *rel[:-1])
    size = int(rec.get('size') or 0)
    try:
        os.makedirs(out_dir, exist_ok=True)
        if shutil.disk_usage(out_dir).free < size + 16 * 1024 * 1024:
            return {'success': False, 'error': "Espace disque insuffisant sur la destination"}
    except OSError as e:
        return {'success': False, 'error': f'Dossier de destination inaccessible : {e}'}
    out_path = unique_path(os.path.join(out_dir, rel[-1]))

    dev = device or rec.get('device') or ''
    reader = None
    if rec.get('resident_b64') is None and (rec.get('extents')):
        try:
            reader = pool.get(dev)
        except DeviceError as e:
            return {'success': False, 'error': str(e)}
    elif rec.get('resident_b64') is None:
        # fichier « logique » : copie directe
        src_path = rec.get('sourcePath') or rec.get('path') or ''
        if src_path and os.path.isfile(src_path):
            try:
                shutil.copy2(src_path, out_path)
                h = hash_file(out_path)
                return {'success': True, 'outputPath': out_path, 'integrity': 'inconnu', **h,
                        'seconds': round(time.time() - t0, 2)}
            except OSError as e:
                return {'success': False, 'error': str(e)}
        return {'success': False, 'error': 'Aucune donnée récupérable pour cet élément'}

    rr = RecordReader(reader, rec)
    md5, sha = hashlib.md5(), hashlib.sha256()
    written = 0
    try:
        with open(out_path, 'wb') as fh:
            while written < size:
                if STOP.is_set():
                    raise InterruptedError()
                data = rr.read(written, CHUNK)
                if not data:
                    break
                fh.write(data)
                md5.update(data)
                sha.update(data)
                written += len(data)
                if progress:
                    progress(written, size)
        mt = rec.get('mtime')
        if mt:
            try:
                os.utime(out_path, (mt, mt))
            except OSError:
                pass
    except InterruptedError:
        try:
            os.remove(out_path)
        except OSError:
            pass
        return {'success': False, 'error': 'Interrompu par l’utilisateur'}
    except OSError as e:
        return {'success': False, 'error': f'Écriture impossible : {e}'}
    result = {'success': written == size or size == 0, 'outputPath': out_path, 'bytes': written,
              'md5': md5.hexdigest(), 'sha256': sha.hexdigest(), 'seconds': round(time.time() - t0, 2),
              'badSectors': reader.bad_count if reader else 0}
    if verify:
        result['integrity'] = verify_file(out_path, rec.get('extension') or os.path.splitext(out_path)[1][1:])
    return result


def hash_file(path: str) -> dict:
    md5, sha = hashlib.md5(), hashlib.sha256()
    n = 0
    with open(path, 'rb') as fh:
        while True:
            c = fh.read(1 << 20)
            if not c:
                break
            n += len(c)
            md5.update(c)
            sha.update(c)
    return {'bytes': n, 'md5': md5.hexdigest(), 'sha256': sha.hexdigest()}


def recover_batch(records: List[dict], dest_root: str, structure: str = 'tree', verify: bool = True,
                  device: Optional[str] = None, stop_flag: Optional[Callable[[], bool]] = None) -> dict:
    pool = ReaderPool()
    ok = fail = 0
    total_bytes = sum(int(r.get('size') or 0) for r in records)
    done_bytes = 0
    t0 = time.time()
    results = []
    try:
        for i, rec in enumerate(records):
            if stop_flag and stop_flag():
                break
            last = [0.0]

            def prog(w, s, rec=rec, i=i):
                now = time.time()
                if now - last[0] < 0.2:
                    return
                last[0] = now
                emit('recover-progress', {'index': i, 'total': len(records), 'name': rec.get('name'),
                                          'fileBytes': w, 'fileSize': s, 'bytesDone': done_bytes + w,
                                          'bytesTotal': total_bytes, 'speed': (done_bytes + w) / max(now - t0, .001)})
            res = recover_one(pool, rec, dest_root, structure, verify, device, prog)
            res['id'] = rec.get('id')
            res['name'] = rec.get('name')
            if res.get('success'):
                ok += 1
            else:
                fail += 1
            done_bytes += int(rec.get('size') or 0)
            results.append({k: res.get(k) for k in ('id', 'name', 'success', 'outputPath', 'md5', 'sha256',
                                                    'integrity', 'error', 'bytes')})
            emit('recover-file-done', res)
    finally:
        pool.close()
    return {'success': fail == 0 and ok > 0, 'recovered': ok, 'failed': fail, 'bytes': done_bytes,
            'seconds': round(time.time() - t0, 1), 'results': results, 'destination': dest_root}


def preview_bytes(rec: dict, max_bytes: int, device: Optional[str] = None) -> dict:
    """Aperçu d'un enregistrement directement depuis la source, sans extraction préalable."""
    pool = ReaderPool()
    try:
        reader = None
        if rec.get('extents') and not rec.get('resident_b64'):
            reader = pool.get(device or rec.get('device') or '')
        rr = RecordReader(reader, rec)
        n = max(1024, min(int(max_bytes or 65536), 32 * 1024 * 1024))
        data = rr.read(0, n)
        ext = (rec.get('extension') or '').lower()
        kind = ('image' if ext in ('jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tif', 'tiff') else
                'audio' if ext in ('mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac') else
                'video' if ext in ('mp4', 'mov', 'avi', 'mkv', 'wmv', 'webm', 'flv') else
                'document' if ext in ('pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp') else
                'text' if ext in ('txt', 'csv', 'log', 'json', 'xml', 'html', 'md', 'ini', 'py', 'js') else 'binary')
        return {'success': True, 'kind': kind, 'name': rec.get('name'), 'size': rr.size,
                'head_b64': base64.b64encode(data).decode('ascii'), 'bytes': len(data),
                'complete': len(data) >= rr.size}
    except DeviceError as e:
        return {'success': False, 'message': str(e)}
    finally:
        pool.close()

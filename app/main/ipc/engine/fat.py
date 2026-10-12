"""Moteurs FAT12/16/32 et exFAT : fichiers existants et supprimés, noms longs, dossiers supprimés,
dossiers orphelins (volume reformaté rapidement)."""
from __future__ import annotations

import calendar
import struct
from typing import Dict, Iterator, List, Optional, Tuple

from .common import FileSink, Progress, ST_ACTIVE, ST_DELETED, ST_PARTIAL, STOP, log, merge_extents
from .devio import Reader, iter_blocks
from .partitions import parse_fat_bpb


def dos_time(date: int, tm: int) -> int:
    try:
        y = 1980 + (date >> 9)
        mo = max(1, min(12, (date >> 5) & 15))
        d = max(1, min(31, date & 31))
        return calendar.timegm((y, mo, d, min(23, tm >> 11), min(59, (tm >> 5) & 63), min(59, (tm & 31) * 2)))
    except Exception:
        return 0


def lfn_checksum(short11: bytes) -> int:
    s = 0
    for b in short11:
        s = (((s & 1) << 7) + (s >> 1) + b) & 0xFF
    return s


class FatVolume:
    def __init__(self, reader: Reader, base: int):
        self.r = reader
        self.base = base
        boot = reader.read_at(base, 512)
        info = parse_fat_bpb(boot)
        if not info:
            raise ValueError('BPB FAT invalide')
        self.info = info
        self.bps = info['bps']
        self.cs = info['bps'] * info['spc']
        self.variant = info['variant']
        self.fat_off = base + info['reserved'] * self.bps
        self.fat_bytes = info['fat_sectors'] * self.bps
        self.root_off = self.fat_off + info['nfats'] * self.fat_bytes
        self.data_off = self.root_off + info['root_sectors'] * self.bps
        self.clusters = info['clusters']
        self.max_cluster = self.clusters + 1
        entry = {'fat12': 1.5, 'fat16': 2, 'fat32': 4}[self.variant]
        need = min(self.fat_bytes, int((self.max_cluster + 1) * entry) + 8)
        self.fat = reader.read_at(self.fat_off, need)
        if self.variant == 'fat16':
            self._f16 = memoryview(self.fat[:len(self.fat) // 2 * 2]).cast('H')
        elif self.variant == 'fat32':
            self._f32 = memoryview(self.fat[:len(self.fat) // 4 * 4]).cast('I')

    def fat_get(self, c: int) -> int:
        try:
            if self.variant == 'fat32':
                return self._f32[c] & 0x0FFFFFFF
            if self.variant == 'fat16':
                return self._f16[c]
            o = c + (c >> 1)
            v = self.fat[o] | (self.fat[o + 1] << 8)
            return (v >> 4) if (c & 1) else (v & 0xFFF)
        except (IndexError, ValueError):
            return 0xFFFFFFF

    def is_eoc(self, v: int) -> bool:
        return v >= {'fat12': 0xFF8, 'fat16': 0xFFF8, 'fat32': 0x0FFFFFF8}[self.variant]

    def is_bad(self, v: int) -> bool:
        return v == {'fat12': 0xFF7, 'fat16': 0xFFF7, 'fat32': 0x0FFFFFF7}[self.variant]

    def coff(self, c: int) -> int:
        return self.data_off + (c - 2) * self.cs

    def chain(self, first: int, limit: int = 1 << 24) -> List[int]:
        out = []
        c = first
        seen = set()
        while 2 <= c <= self.max_cluster and c not in seen and len(out) < limit:
            seen.add(c)
            out.append(c)
            n = self.fat_get(c)
            if self.is_eoc(n) or self.is_bad(n) or n < 2:
                break
            c = n
        return out

    def clusters_to_extents(self, cl: List[int]) -> List[List[int]]:
        ext: List[List[int]] = []
        for c in cl:
            ext.append([self.coff(c), self.cs])
        return merge_extents(ext)

    def read_chain(self, cl: List[int]) -> bytes:
        return b''.join(self.r.read_at(self.coff(c), self.cs) for c in cl)


def _parse_dir(data: bytes, deleted_dir: bool = False) -> Iterator[dict]:
    """Itère les entrées d'un répertoire FAT -> dict(name,short,attr,cluster,size,deleted,mtime)."""
    lfn: List[Tuple[int, int, str]] = []
    for i in range(0, len(data) - 31, 32):
        e = data[i:i + 32]
        b0 = e[0]
        if b0 == 0x00:
            if deleted_dir:
                continue
            break
        attr = e[11]
        if attr == 0x0F and e[12] == 0 and e[26:28] == b'\x00\x00':
            chars = e[1:11] + e[14:26] + e[28:32]
            part = chars.decode('utf-16le', errors='ignore')
            for term in ('\x00', '\uffff'):
                part = part.split(term)[0]
            lfn.append((b0, e[13], part))
            continue
        deleted = b0 == 0xE5
        if attr & 0x08:            # étiquette de volume
            lfn = []
            continue
        short_raw = bytes(e[0:11])
        name8 = short_raw[:8].rstrip(b' ')
        ext3 = short_raw[8:11].rstrip(b' ')
        if deleted:
            name8 = b'_' + name8[1:]
        elif short_raw[0] == 0x05:
            name8 = b'\xe5' + name8[1:]
        nt = e[12]
        n = name8.decode('cp437', errors='replace')
        x = ext3.decode('cp437', errors='replace')
        if nt & 0x08:
            n = n.lower()
        if nt & 0x10:
            x = x.lower()
        short = n + ('.' + x if x else '')
        name = short
        if lfn:
            want = lfn[0][1]
            ok = all(p[1] == want for p in lfn)
            if ok and deleted:
                # le 1er octet du nom court est perdu : on retrouve celui qui redonne la somme de contrôle
                ok = any(lfn_checksum(bytes([c]) + short_raw[1:]) == want for c in range(256))
            elif ok:
                ok = lfn_checksum(short_raw) == want
            if ok:
                name = ''.join(p[2] for p in reversed(lfn)) or short   # ordre physique : du plus haut au plus bas
        lfn = []
        if short in ('.', '..'):
            continue
        cl = struct.unpack_from('<H', e, 26)[0] | (struct.unpack_from('<H', e, 20)[0] << 16)
        size = struct.unpack_from('<I', e, 28)[0]
        mdate, mtime = struct.unpack_from('<H', e, 24)[0], struct.unpack_from('<H', e, 22)[0]
        yield {'name': name, 'short': short, 'attr': attr, 'cluster': cl, 'size': size, 'deleted': deleted,
               'mtime': dos_time(mdate, mtime), 'is_dir': bool(attr & 0x10)}


def _file_record(v: FatVolume, ent: dict, dirpath: str, label: str, dir_deleted: bool) -> Optional[dict]:
    size = ent['size']
    cl0 = ent['cluster']
    if size == 0 or cl0 < 2 or cl0 > v.max_cluster:
        return None
    n = -(-size // v.cs)
    deleted = ent['deleted'] or dir_deleted
    ow = None
    if not deleted:
        chain = v.chain(cl0, n + 1)
        if len(chain) < n:        # chaîne tronquée : on complète en contigu
            chain = chain + list(range(chain[-1] + 1, chain[-1] + 1 + n - len(chain))) if chain else []
        ext = v.clusters_to_extents(chain[:n])
        conf = 1.0
    else:
        if cl0 + n - 1 > v.max_cluster:
            return None
        used = sum(1 for c in range(cl0, cl0 + n) if v.fat_get(c) != 0)
        ow = round(used * 100.0 / n, 1)
        ext = [[v.coff(cl0), n * v.cs]]
        conf = 0.9 * (1 - ow / 100.0)
    name = ent['name']
    path = (dirpath + '\\' + name) if dirpath else name
    status = ST_ACTIVE if not deleted else (ST_PARTIAL if (ow or 0) >= 50 else ST_DELETED)
    return {'name': name, 'dir': dirpath, 'path': path, 'size': int(size), 'status': status,
            'confidence': round(max(conf, 0.05), 3), 'source': 'fat', 'mtime': ent['mtime'], 'extents': ext,
            'volume': label, 'overwritten_pct': ow, 'cluster_size': v.cs, 'deleted': deleted,
            'fragments': len(ext), 'first_cluster': cl0}


def scan_fat(reader: Reader, base: int, sink: FileSink, progress: Progress, mode: str = 'deleted',
             part_label: str = '', deep: bool = False, min_size: int = 1, alloc_out: Optional[list] = None) -> int:
    try:
        v = FatVolume(reader, base)
    except ValueError as e:
        log(f'FAT : {e}')
        return 0
    label = part_label or v.variant.upper()
    if alloc_out is not None:
        def _alloc(off, v=v):
            if off < v.data_off:
                return True                       # zone réservée / FAT / racine
            c = (off - v.data_off) // v.cs + 2
            return c <= v.max_cluster and v.fat_get(c) != 0
        alloc_out.append((base, base + v.info['total_sectors'] * v.bps, _alloc))
    progress.window(0, 60)
    progress.total = max(v.clusters, 1)
    emitted = 0
    visited_dirs = set()
    stack: List[Tuple[Optional[int], str, bool]] = [(None if v.variant != 'fat32' else v.info['root_cluster'], '', False)]
    dirs_done = 0

    def emit_ent(ent, path, dir_deleted):
        nonlocal emitted
        if mode == 'deleted' and not (ent['deleted'] or dir_deleted):
            return
        rec = _file_record(v, ent, path, label, dir_deleted)
        if rec and rec['size'] >= min_size:
            if sink.add(rec, dedupe_key=('fat', base, rec['first_cluster'], rec['size'], rec['name'])) is not None:
                emitted += 1

    while stack:
        if STOP.is_set():
            break
        cl, path, ddel = stack.pop()
        if cl is None:   # racine FAT12/16
            data = reader.read_at(v.root_off, v.info['root_sectors'] * v.bps)
        else:
            if cl in visited_dirs:
                continue
            visited_dirs.add(cl)
            if ddel:
                chain = [cl]
                c = cl
                while len(chain) < 16 and v.fat_get(c) == 0 and c + 1 <= v.max_cluster and v.fat_get(c + 1) == 0:
                    c += 1
                    chain.append(c)
                data = v.read_chain(chain)
            else:
                data = v.read_chain(v.chain(cl, 1 << 16))
        dirs_done += 1
        for ent in _parse_dir(data, deleted_dir=ddel):
            if ent['is_dir']:
                sub = ent['cluster']
                if 2 <= sub <= v.max_cluster and sub not in visited_dirs:
                    stack.append((sub, (path + '\\' if path else '') + ent['name'], ddel or ent['deleted']))
                continue
            emit_ent(ent, path, ddel)
        progress.update(min(dirs_done, v.clusters), f'{label} : {path or "racine"}')

    if deep or emitted == 0:
        emitted += _scan_orphan_dirs(v, sink, progress, mode, label, visited_dirs, min_size)
    return emitted


def _scan_orphan_dirs(v: FatVolume, sink: FileSink, progress: Progress, mode: str, label: str,
                      known_dirs: set, min_size: int) -> int:
    """Cherche dans toute la zone de données des clusters de répertoire (« . » et « .. ») non référencés."""
    progress.window(60, 38)
    total = v.clusters * v.cs
    progress.total = total
    orphans: Dict[int, Tuple[int, bytes]] = {}       # cluster -> (cluster parent, données)
    dot = b'.          '
    dotdot = b'..         '
    for pos, block in iter_blocks(v.r, v.data_off, v.data_off + total, 8 * 1024 * 1024):
        for k in range(0, len(block) - 64 + 1, v.cs):
            if block[k:k + 11] == dot and block[k + 32:k + 43] == dotdot and (block[k + 11] & 0x10):
                cl = (pos + k - v.data_off) // v.cs + 2
                own = struct.unpack_from('<H', block, k + 26)[0] | (struct.unpack_from('<H', block, k + 20)[0] << 16)
                if own != cl or cl in known_dirs:
                    continue
                par = struct.unpack_from('<H', block, k + 58)[0] | (struct.unpack_from('<H', block, k + 52)[0] << 16)
                data = block[k:k + v.cs]
                if len(data) < v.cs:
                    data = v.r.read_at(v.coff(cl), v.cs)
                orphans[cl] = (par, data)
        progress.update(pos + len(block) - v.data_off, f'{label} : recherche de dossiers orphelins')
    names: Dict[int, str] = {}
    entries: Dict[int, List[dict]] = {}
    for cl, (par, data) in orphans.items():
        ents = list(_parse_dir(data[64:], deleted_dir=True))
        entries[cl] = ents
        for e in ents:
            if e['is_dir']:
                names.setdefault(e['cluster'], e['name'])

    def dpath(cl: int) -> str:
        parts = []
        seen = set()
        cur = cl
        while cur in orphans and cur not in seen:
            seen.add(cur)
            parts.append(names.get(cur, f'Dossier_{cur}'))
            cur = orphans[cur][0]
        root_ok = cur == 0
        parts.reverse()
        return ('' if root_ok else '[Orphelins]\\') + '\\'.join(parts)

    n = 0
    for cl, ents in entries.items():
        path = dpath(cl)
        for e in ents:
            if e['is_dir']:
                continue
            e = dict(e)
            e['deleted'] = True if mode == 'deleted' else e['deleted']
            rec = _file_record(v, e, path, label, True)
            if rec and rec['size'] >= min_size:
                rec['recovered_by'] = 'orphan_dir'
                if sink.add(rec, dedupe_key=('fat', v.base, rec['first_cluster'], rec['size'], rec['name'])) is not None:
                    n += 1
    return n


# ------------------------------------------------------------------ exFAT
class ExfatVolume:
    def __init__(self, reader: Reader, base: int):
        self.r = reader
        self.base = base
        b = reader.read_at(base, 512)
        if b[3:11] != b'EXFAT   ':
            raise ValueError('pas exFAT')
        self.bps = 1 << b[108]
        self.cs = self.bps << b[109]
        self.fat_off = base + struct.unpack_from('<I', b, 80)[0] * self.bps
        self.fat_len = struct.unpack_from('<I', b, 84)[0] * self.bps
        self.heap_off = base + struct.unpack_from('<I', b, 88)[0] * self.bps
        self.clusters = struct.unpack_from('<I', b, 92)[0]
        self.root = struct.unpack_from('<I', b, 96)[0]
        need = min(self.fat_len, (self.clusters + 2) * 4)
        fat = reader.read_at(self.fat_off, need)
        self.fat = memoryview(fat[:len(fat) // 4 * 4]).cast('I')
        self.bitmap: Optional[bytes] = None
        self.max_cluster = self.clusters + 1

    def coff(self, c: int) -> int:
        return self.heap_off + (c - 2) * self.cs

    def chain(self, first: int, nofat: bool, size: int) -> List[int]:
        if nofat:
            n = -(-size // self.cs)
            return list(range(first, first + n))
        out, c, seen = [], first, set()
        while 2 <= c <= self.max_cluster and c not in seen and len(out) < (1 << 24):
            seen.add(c)
            out.append(c)
            try:
                n = self.fat[c]
            except IndexError:
                break
            if n >= 0xFFFFFFF7 or n < 2:
                break
            c = n
        return out

    def is_allocated(self, c: int) -> Optional[bool]:
        if self.bitmap is None:
            return None
        i = c - 2
        if (i >> 3) >= len(self.bitmap):
            return None
        return bool(self.bitmap[i >> 3] & (1 << (i & 7)))


def _exfat_entries(data: bytes) -> Iterator[dict]:
    i = 0
    n = len(data)
    while i + 32 <= n:
        t = data[i]
        if t == 0x00:
            break
        if t in (0x85, 0x05):
            cnt = data[i + 1]
            attr = struct.unpack_from('<H', data, i + 4)[0]
            mt = struct.unpack_from('<I', data, i + 12)[0]
            stream = None
            name = ''
            for j in range(1, cnt + 1):
                o = i + j * 32
                if o + 32 > n:
                    break
                tj = data[o]
                if tj in (0xC0, 0x40):
                    stream = (data[o + 1], data[o + 3], struct.unpack_from('<Q', data, o + 8)[0],
                              struct.unpack_from('<I', data, o + 20)[0], struct.unpack_from('<Q', data, o + 24)[0])
                elif tj in (0xC1, 0x41):
                    name += data[o + 2:o + 32].decode('utf-16le', errors='replace')
            if stream:
                flags, nlen, valid, first, length = stream
                yield {'name': name[:stream[1]] or '(sans nom)', 'attr': attr, 'is_dir': bool(attr & 0x10),
                       'deleted': t == 0x05, 'nofat': bool(flags & 2), 'cluster': first, 'size': length,
                       'valid': valid, 'mtime': dos_time(mt >> 16, mt & 0xFFFF)}
            i += (cnt + 1) * 32
            continue
        i += 32


def _exfat_orphans(v: 'ExfatVolume', reader: Reader, sink: FileSink, progress: Progress, mode: str, label: str,
                   base: int, min_size: int, known_dirs: set) -> int:
    """Formatage rapide exFAT : le répertoire racine est effacé mais les clusters de dossiers (ensembles d'entrées
    0x85/0xC0/0xC1) subsistent. On les retrouve en inspectant le début de chaque cluster de la zone de données."""
    progress.window(60, 38)
    total = v.clusters * v.cs
    progress.total = total
    dir_clusters: Dict[int, List[dict]] = {}
    for pos, block in iter_blocks(reader, v.heap_off, v.heap_off + total, 8 * 1024 * 1024):
        for k in range(0, len(block) - 96, v.cs):
            hit = False
            for s in range(0, min(8, v.cs // 32 - 2)):
                o = k + s * 32
                if block[o] in (0x85, 0x05) and block[o + 32] in (0xC0, 0x40) and block[o + 64] in (0xC1, 0x41):
                    hit = True
                    break
            if not hit:
                continue
            cl = (pos + k - v.heap_off) // v.cs + 2
            if cl in known_dirs:
                continue
            ents = list(_exfat_entries(block[k:k + v.cs]))
            ents = [e for e in ents if e['name'] and all(ord(ch) >= 32 for ch in e['name']) and e['valid'] <= e['size']
                    and (e['is_dir'] or (2 <= e['cluster'] <= v.max_cluster and 0 < e['size'] < (1 << 40)))]
            if ents:
                dir_clusters[cl] = ents
        progress.update(pos + len(block) - v.heap_off, f'{label} : recherche d’entrées de dossiers orphelines')
    names = {}
    for ents in dir_clusters.values():
        for e in ents:
            if e['is_dir']:
                names.setdefault(e['cluster'], e['name'])
    n = 0
    for cl, ents in dir_clusters.items():
        path = '[Orphelins]\\' + names.get(cl, f'Dossier_{cl}')
        for e in ents:
            if e['is_dir'] or e['size'] < max(1, min_size) or not (2 <= e['cluster'] <= v.max_cluster):
                continue
            nclu = -(-e['size'] // v.cs)
            if e['cluster'] + nclu - 1 > v.max_cluster:
                continue
            cl_list = list(range(e['cluster'], e['cluster'] + nclu))
            if not e['nofat']:
                ch = v.chain(e['cluster'], False, e['size'])
                if len(ch) >= nclu:
                    cl_list = ch[:nclu]
            ow = None
            if v.bitmap is not None:
                ow = round(sum(1 for c in cl_list if v.is_allocated(c)) * 100.0 / len(cl_list), 1)
            ext = merge_extents([[v.coff(c), v.cs] for c in cl_list])
            rec = {'name': e['name'], 'dir': path, 'path': path + '\\' + e['name'], 'size': int(e['size']),
                   'status': ST_PARTIAL if (ow or 0) >= 50 else ST_DELETED,
                   'confidence': round(max(0.7 * (1 - (ow or 0) / 100.0), 0.05), 3), 'source': 'exfat',
                   'mtime': e['mtime'], 'extents': ext, 'volume': label, 'overwritten_pct': ow, 'cluster_size': v.cs,
                   'deleted': True, 'fragments': len(ext), 'recovered_by': 'orphan_dir'}
            if sink.add(rec, dedupe_key=('exfat', base, e['cluster'], e['size'], e['name'])) is not None:
                n += 1
    return n


def scan_exfat(reader: Reader, base: int, sink: FileSink, progress: Progress, mode: str = 'deleted',
               part_label: str = '', deep: bool = False, min_size: int = 1, alloc_out: Optional[list] = None) -> int:
    try:
        v = ExfatVolume(reader, base)
    except ValueError as e:
        log(f'exFAT : {e}')
        return 0
    label = part_label or 'exFAT'
    progress.window(0, 95)
    progress.total = max(v.clusters, 1)

    def read_dir(first: int, nofat: bool, size: int, deleted: bool) -> bytes:
        if deleted:
            # chaîne éventuellement libérée : suppose contigu (jusqu'à 16 clusters)
            n = max(1, min(16, -(-size // v.cs))) if size else 1
            return b''.join(reader.read_at(v.coff(first + k), v.cs) for k in range(n))
        cl = v.chain(first, nofat, size or v.cs)
        return b''.join(reader.read_at(v.coff(c), v.cs) for c in cl)

    # bitmap d'allocation
    root_data = read_dir(v.root, False, 0, False)
    for i in range(0, len(root_data) - 31, 32):
        if root_data[i] == 0x81:
            first = struct.unpack_from('<I', root_data, i + 20)[0]
            ln = struct.unpack_from('<Q', root_data, i + 24)[0]
            if 2 <= first <= v.max_cluster and ln < 256 * 1024 * 1024:
                cl = v.chain(first, False, int(ln))
                v.bitmap = b''.join(reader.read_at(v.coff(c), v.cs) for c in cl)[:int(ln)]
            break
    if alloc_out is not None and v.bitmap is not None:
        def _alloc_x(off, v=v):
            if off < v.heap_off:
                return True
            c = (off - v.heap_off) // v.cs + 2
            r = v.is_allocated(c)
            return True if r is None else r
        alloc_out.append((base, base + (v.clusters * v.cs) + (v.heap_off - base), _alloc_x))

    stack: List[Tuple[int, bool, int, str, bool]] = [(v.root, False, 0, '', False)]
    visited = set()
    emitted = 0
    done = 0
    while stack:
        if STOP.is_set():
            break
        first, nofat, size, path, ddel = stack.pop()
        if first in visited:
            continue
        visited.add(first)
        data = root_data if first == v.root and not ddel else read_dir(first, nofat, size, ddel)
        done += 1
        for e in _exfat_entries(data):
            deleted = e['deleted'] or ddel
            if e['is_dir']:
                if 2 <= e['cluster'] <= v.max_cluster:
                    stack.append((e['cluster'], e['nofat'], e['size'], (path + '\\' if path else '') + e['name'],
                                  deleted))
                continue
            if mode == 'deleted' and not deleted:
                continue
            size_f = e['size']
            if size_f < max(1, min_size) or not (2 <= e['cluster'] <= v.max_cluster):
                continue
            ow = None
            if deleted:
                cl = list(range(e['cluster'], e['cluster'] + -(-size_f // v.cs)))
                if not e['nofat']:
                    ch = v.chain(e['cluster'], False, size_f)
                    if len(ch) >= len(cl):
                        cl = ch[:len(cl)]
                if cl and cl[-1] > v.max_cluster:
                    continue
                al = [v.is_allocated(c) for c in cl]
                if v.bitmap is not None and cl:
                    ow = round(sum(1 for x in al if x) * 100.0 / len(cl), 1)
            else:
                cl = v.chain(e['cluster'], e['nofat'], size_f)
            ext = merge_extents([[v.coff(c), v.cs] for c in cl])
            conf = 1.0 if not deleted else 0.9 * (1 - (ow or 0) / 100.0)
            status = ST_ACTIVE if not deleted else (ST_PARTIAL if (ow or 0) >= 50 else ST_DELETED)
            rec = {'name': e['name'], 'dir': path, 'path': (path + '\\' + e['name']) if path else e['name'],
                   'size': int(size_f), 'status': status, 'confidence': round(max(conf, 0.05), 3),
                   'source': 'exfat', 'mtime': e['mtime'], 'extents': ext, 'volume': label,
                   'overwritten_pct': ow, 'cluster_size': v.cs, 'deleted': deleted, 'fragments': len(ext),
                   'valid_size': int(e['valid'])}
            if sink.add(rec, dedupe_key=('exfat', base, e['cluster'], size_f, e['name'])) is not None:
                emitted += 1
        progress.update(min(done, v.clusters), f'{label} : {path or "racine"}')
    if deep or emitted == 0:
        emitted += _exfat_orphans(v, reader, sink, progress, mode, label, base, min_size, visited)
    return emitted

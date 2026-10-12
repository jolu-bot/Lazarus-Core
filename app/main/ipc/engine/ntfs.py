"""Moteur NTFS : lecture de la $MFT (fragmentée ou non), fichiers supprimés, chemins, détection d'écrasement.

Fonctionnalités :
  * $MFT lue via ses propres data runs (record 0, ou $MFTMirr si le record 0 est détruit) ;
  * fichiers supprimés ET existants, chemins complets reconstruits (avec contrôle des numéros de séquence) ;
  * $ATTRIBUTE_LIST et records d'extension (fichiers très fragmentés) ;
  * fichiers creux, compressés (LZNT1) et chiffrés (signalés) ;
  * $Bitmap : pourcentage de clusters réattribués depuis la suppression -> score de récupérabilité réel ;
  * Corbeille : retrouve le nom d'origine via les fichiers $I ;
  * mode « MFT carving » : retrouve les records FILE0 sur tout le disque (volume formaté ou $MFT détruite).
"""
from __future__ import annotations

import bisect
import struct
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from .common import (FileSink, Progress, ST_ACTIVE, ST_DELETED, ST_FRAGMENTED, ST_PARTIAL, emit, log,
                     merge_extents, split_name)
from .devio import Reader, iter_blocks

EPOCH_DELTA = 116444736000000000
ATTR_STD, ATTR_LIST, ATTR_NAME, ATTR_DATA, ATTR_END = 0x10, 0x20, 0x30, 0x80, 0xFFFFFFFF
ATTR_BITMAP = 0xB0


def ft_to_epoch(ft: int) -> int:
    if not ft or ft < EPOCH_DELTA:
        return 0
    return int((ft - EPOCH_DELTA) // 10000000)


def parse_runs(data: bytes, start_vcn: int = 0) -> List[Tuple[int, Optional[int], int]]:
    """Décode une liste de runs -> [(vcn, lcn|None(creux), longueur)]."""
    out = []
    i, vcn, lcn = 0, start_vcn, 0
    n = len(data)
    while i < n:
        h = data[i]
        i += 1
        if h == 0:
            break
        ls, os_ = h & 0x0F, h >> 4
        if ls == 0 or i + ls + os_ > n:
            break
        length = int.from_bytes(data[i:i + ls], 'little')
        i += ls
        if os_ == 0:
            out.append((vcn, None, length))
        else:
            lcn += int.from_bytes(data[i:i + os_], 'little', signed=True)
            if lcn < 0:
                break
            out.append((vcn, lcn, length))
        i += os_
        vcn += length
    return out


def apply_fixup(rec: bytearray) -> bool:
    usa_off, usa_cnt = struct.unpack_from('<HH', rec, 4)
    if usa_cnt < 2 or usa_off < 42 or usa_off + usa_cnt * 2 > len(rec):
        return False
    usn = bytes(rec[usa_off:usa_off + 2])
    for i in range(1, usa_cnt):
        tail = i * 512 - 2
        if tail + 2 > len(rec):
            return False
        if bytes(rec[tail:tail + 2]) != usn:
            return False
        rec[tail:tail + 2] = rec[usa_off + i * 2:usa_off + i * 2 + 2]
    return True


class Entry:
    """Un record MFT analysé."""
    __slots__ = ('idx', 'seq', 'flags', 'base', 'names', 'mtime', 'pieces', 'resident', 'real_size', 'alloc_size',
                 'dflags', 'comp_unit', 'attr_list', 'has_data', 'attr_list_nonres', 'bitmap_pieces',
                 'init_size')

    def __init__(self):
        self.idx = 0
        self.seq = 0
        self.flags = 0
        self.base = 0
        self.names: List[Tuple[int, str, int, int]] = []   # (namespace, nom, parent_idx, parent_seq)
        self.mtime = 0
        self.pieces: List[Tuple[int, bytes]] = []          # (start_vcn, runs bruts)
        self.resident: Optional[bytes] = None
        self.real_size = 0
        self.alloc_size = 0
        self.init_size = 0
        self.dflags = 0
        self.comp_unit = 0
        self.attr_list: Optional[bytes] = None
        self.attr_list_nonres: Optional[Tuple[int, int, bytes]] = None
        self.has_data = False
        self.bitmap_pieces: List[Tuple[int, bytes]] = []

    @property
    def in_use(self):
        return bool(self.flags & 1)

    @property
    def is_dir(self):
        return bool(self.flags & 2)

    def best_name(self) -> Optional[Tuple[str, int, int]]:
        if not self.names:
            return None
        pref = {1: 0, 3: 0, 0: 1, 2: 2}
        n = sorted(self.names, key=lambda t: pref.get(t[0], 3))[0]
        return n[1], n[2], n[3]


def parse_record(raw: bytes, rec_size: int, want_data: bool = True) -> Optional[Entry]:
    if len(raw) < 48 or raw[:4] != b'FILE':
        return None
    rec = bytearray(raw[:rec_size] if len(raw) >= rec_size else raw)
    if not apply_fixup(rec):
        return None
    e = Entry()
    attr_off = struct.unpack_from('<H', rec, 20)[0]
    e.flags = struct.unpack_from('<H', rec, 22)[0]
    used = struct.unpack_from('<I', rec, 24)[0]
    e.seq = struct.unpack_from('<H', rec, 16)[0]
    base_ref = struct.unpack_from('<Q', rec, 32)[0]
    e.base = base_ref & 0xFFFFFFFFFFFF
    if attr_off < 42 or attr_off >= len(rec):
        return None
    limit = min(len(rec), used) if 48 <= used <= len(rec) else len(rec)
    p = attr_off
    while p + 16 <= limit:
        atype = struct.unpack_from('<I', rec, p)[0]
        if atype == ATTR_END:
            break
        alen = struct.unpack_from('<I', rec, p + 4)[0]
        if alen < 16 or alen % 8 or p + alen > len(rec):
            break
        nonres = rec[p + 8]
        name_len = rec[p + 9]
        flags = struct.unpack_from('<H', rec, p + 12)[0]
        if atype == ATTR_NAME and nonres == 0:
            voff = struct.unpack_from('<H', rec, p + 20)[0]
            vlen = struct.unpack_from('<I', rec, p + 16)[0]
            v = rec[p + voff:p + voff + vlen]
            if len(v) >= 66:
                par = struct.unpack_from('<Q', v, 0)[0]
                nlen = v[64]
                ns = v[65]
                nm = bytes(v[66:66 + nlen * 2]).decode('utf-16le', errors='replace')
                if nm:
                    e.names.append((ns, nm, par & 0xFFFFFFFFFFFF, par >> 48))
        elif atype == ATTR_STD and nonres == 0:
            voff = struct.unpack_from('<H', rec, p + 20)[0]
            v = rec[p + voff:p + voff + 48]
            if len(v) >= 16:
                e.mtime = ft_to_epoch(struct.unpack_from('<Q', v, 8)[0])
        elif atype == ATTR_DATA and name_len == 0 and want_data:
            e.has_data = True
            if nonres == 0:
                vlen = struct.unpack_from('<I', rec, p + 16)[0]
                voff = struct.unpack_from('<H', rec, p + 20)[0]
                e.resident = bytes(rec[p + voff:p + voff + vlen])
                e.real_size = vlen
            else:
                svcn = struct.unpack_from('<Q', rec, p + 16)[0]
                runs_off = struct.unpack_from('<H', rec, p + 32)[0]
                if svcn == 0:
                    e.comp_unit = struct.unpack_from('<H', rec, p + 34)[0]
                    e.alloc_size = struct.unpack_from('<Q', rec, p + 40)[0]
                    e.real_size = struct.unpack_from('<Q', rec, p + 48)[0]
                    e.init_size = struct.unpack_from('<Q', rec, p + 56)[0]
                    e.dflags = flags
                e.pieces.append((svcn, bytes(rec[p + runs_off:p + alen])))
        elif atype == ATTR_LIST and want_data:
            if nonres == 0:
                vlen = struct.unpack_from('<I', rec, p + 16)[0]
                voff = struct.unpack_from('<H', rec, p + 20)[0]
                e.attr_list = bytes(rec[p + voff:p + voff + vlen])
            else:
                runs_off = struct.unpack_from('<H', rec, p + 32)[0]
                real = struct.unpack_from('<Q', rec, p + 48)[0]
                e.attr_list_nonres = (0, real, bytes(rec[p + runs_off:p + alen]))
        elif atype == ATTR_BITMAP and name_len == 0 and nonres == 1 and want_data:
            svcn = struct.unpack_from('<Q', rec, p + 16)[0]
            runs_off = struct.unpack_from('<H', rec, p + 32)[0]
            e.bitmap_pieces.append((svcn, bytes(rec[p + runs_off:p + alen])))
        p += alen
    return e


class NtfsError(Exception):
    pass


class Volume:
    def __init__(self, reader: Reader, base: int = 0, size_hint: int = 0, cluster_size: int = 0, rec_size: int = 0):
        self.r = reader
        self.base = base
        boot = reader.read_at(base, 512)
        self.have_boot = boot[3:11] == b'NTFS    '
        if self.have_boot:
            self.bps = struct.unpack_from('<H', boot, 11)[0]
            self.spc = boot[13]
            if self.bps not in (512, 1024, 2048, 4096) or self.spc == 0 or (self.spc & (self.spc - 1)):
                raise NtfsError('secteur de démarrage NTFS invalide')
            self.cs = self.bps * self.spc
            self.total_sectors = struct.unpack_from('<Q', boot, 40)[0]
            self.mft_lcn = struct.unpack_from('<Q', boot, 48)[0]
            self.mirr_lcn = struct.unpack_from('<Q', boot, 56)[0]
            cpr = struct.unpack_from('<b', boot, 64)[0]
            self.rec_size = (1 << -cpr) if cpr < 0 else cpr * self.cs
            self.vol_size = self.total_sectors * self.bps
        else:
            self.bps = 512
            self.cs = cluster_size or 4096
            self.mft_lcn = 0
            self.mirr_lcn = 0
            self.rec_size = rec_size or 1024
            self.vol_size = size_hint
            self.total_sectors = size_hint // 512
        if self.rec_size not in (512, 1024, 2048, 4096):
            self.rec_size = 1024
        self.total_clusters = (self.vol_size // self.cs) if self.vol_size else 0
        self.mft_segs: List[Tuple[int, Optional[int], int]] = []
        self.mft_size = 0
        self.bitmap: Optional[bytes] = None
        self._seg_vcns: List[int] = []

    # ------------------------------------------------------------ lecture logique via runs
    def abs_off(self, lcn: int) -> int:
        return self.base + lcn * self.cs

    def read_segments(self, segs, offset: int, n: int) -> bytes:
        """Lit n octets à l'offset logique du flux décrit par segs (creux = zéros)."""
        out = bytearray()
        cs = self.cs
        cached = getattr(self, '_vc', None)
        if cached is None or cached[0] is not segs or cached[2] != len(segs):
            cached = (segs, [s[0] for s in segs], len(segs))
            self._vc = cached
        vcns = cached[1]
        i = max(0, bisect.bisect_right(vcns, offset // cs) - 1)
        pos = offset
        end = offset + n
        while pos < end and i < len(segs):
            vcn, lcn, ln = segs[i]
            seg_start = vcn * cs
            seg_end = (vcn + ln) * cs
            if pos >= seg_end:
                i += 1
                continue
            if pos < seg_start:           # trou : complète par des zéros
                gap = min(seg_start, end) - pos
                out += b'\x00' * gap
                pos += gap
                continue
            take = min(end, seg_end) - pos
            if lcn is None:
                out += b'\x00' * take
            else:
                data = self.r.read_at(self.abs_off(lcn) + (pos - seg_start), take)
                out += data
                if len(data) < take:
                    out += b'\x00' * (take - len(data))
            pos += take
            i += 1
        if pos < end:
            out += b'\x00' * (end - pos)
        return bytes(out)

    # ------------------------------------------------------------ $MFT
    def load_mft(self):
        candidates = []
        if self.have_boot:
            candidates.append(self.base + self.mft_lcn * self.cs)
            if self.mirr_lcn:
                candidates.append(self.base + self.mirr_lcn * self.cs)
        last_err = 'record 0 de la $MFT illisible'
        for off in candidates:
            raw = self.r.read_at(off, self.rec_size)
            ent = parse_record(raw, self.rec_size)
            if not ent or not ent.pieces:
                continue
            segs = self._collect_segments(ent)
            if not segs:
                continue
            self.mft_segs = segs
            self.mft_size = ent.real_size or sum(s[2] for s in segs) * self.cs
            if ent.attr_list or ent.attr_list_nonres:
                ent.idx = 0
                full, _ok = self.full_data_segments(ent)
                if full:
                    self.mft_segs = full
            if off != candidates[0]:
                log('NTFS : record 0 détruit, $MFTMirr utilisée (seuls les 4 premiers records sont dupliqués)')
            return
        raise NtfsError(last_err)

    def _collect_segments(self, ent: Entry, extra_pieces=None) -> List[Tuple[int, Optional[int], int]]:
        pieces = list(ent.pieces) + (extra_pieces or [])
        pieces.sort(key=lambda t: t[0])
        segs: List[Tuple[int, Optional[int], int]] = []
        for svcn, blob in pieces:
            segs.extend(parse_runs(blob, svcn))
        segs.sort(key=lambda s: s[0])
        return segs

    def read_mft_record(self, idx: int) -> Optional[bytes]:
        if not self.mft_segs:
            return None
        off = idx * self.rec_size
        if off + self.rec_size > self.mft_size:
            return None
        return self.read_segments(self.mft_segs, off, self.rec_size)

    def iter_mft(self, progress: Optional[Callable[[int, int], None]] = None) -> Iterator[Tuple[int, bytes]]:
        total = self.mft_size
        block = (4 * 1024 * 1024 // self.rec_size) * self.rec_size
        fetch = lambda off, n: self.read_segments(self.mft_segs, off, n)  # noqa: E731
        for pos, data in iter_blocks(self.r, 0, total, block, fetch=fetch):
            rs = self.rec_size
            for k in range(0, len(data) - rs + 1, rs):
                yield (pos + k) // rs, data[k:k + rs]
            if progress:
                progress(pos + len(data), total)

    def live_ranges(self) -> List[Tuple[int, int]]:
        """Plages d'octets absolues occupées par la $MFT actuelle."""
        return [(self.base + lcn * self.cs, self.base + (lcn + ln) * self.cs)
                for _v, lcn, ln in self.mft_segs if lcn is not None]

    # ------------------------------------------------------------ $Bitmap
    def load_bitmap(self):
        try:
            raw = self.read_mft_record(6)
            if not raw:
                return
            ent = parse_record(raw, self.rec_size)
            if not ent or not ent.pieces:
                return
            segs = self._collect_segments(ent)
            size = ent.real_size
            if not size or size > 512 * 1024 * 1024:
                return
            self.bitmap = self.read_segments(segs, 0, size)
        except Exception as e:  # pragma: no cover
            log(f'NTFS : $Bitmap illisible ({e})')

    def allocated_fraction(self, segs) -> Optional[float]:
        """Part (0-1) des clusters du fichier actuellement marqués comme alloués."""
        if self.bitmap is None:
            return None
        total = alloc = 0
        bm = self.bitmap
        for _vcn, lcn, ln in segs:
            if lcn is None:
                continue
            total += ln
            end = lcn + ln
            first_byte, last_byte = lcn >> 3, (end - 1) >> 3
            if last_byte >= len(bm):
                continue
            if first_byte == last_byte:
                v = bm[first_byte] >> (lcn & 7)
                bits = ln
                alloc += bin(v & ((1 << bits) - 1)).count('1')
                continue
            alloc += bin(bm[first_byte] >> (lcn & 7)).count('1')
            alloc += bin(bm[last_byte] & ((1 << (((end - 1) & 7) + 1)) - 1)).count('1')
            if last_byte - first_byte > 1:
                mid = int.from_bytes(bm[first_byte + 1:last_byte], 'little')
                alloc += bin(mid).count('1')
        return (alloc / total) if total else None

    # ------------------------------------------------------------ data d'un record (avec extensions)
    def full_data_segments(self, ent: Entry) -> Tuple[List[Tuple[int, Optional[int], int]], bool]:
        """Retourne (segments, complet?) en tenant compte des records d'extension via $ATTRIBUTE_LIST."""
        extra: List[Tuple[int, bytes]] = []
        complete = True
        al = ent.attr_list
        if al is None and ent.attr_list_nonres:
            try:
                _, real, blob = ent.attr_list_nonres
                segs = [(v, l, n) for (v, l, n) in parse_runs(blob, 0)]
                al = self.read_segments(segs, 0, min(real, 4 * 1024 * 1024))
            except Exception:
                al = None
        if al:
            p = 0
            seen = set()
            while p + 26 <= len(al):
                atype = struct.unpack_from('<I', al, p)[0]
                rlen = struct.unpack_from('<H', al, p + 4)[0]
                nlen = al[p + 6]
                if rlen < 26:
                    break
                ref = struct.unpack_from('<Q', al, p + 16)[0] & 0xFFFFFFFFFFFF
                if atype == ATTR_DATA and nlen == 0 and ref != ent.idx and ref not in seen:
                    seen.add(ref)
                    raw = self.read_mft_record(ref)
                    sub = parse_record(raw, self.rec_size) if raw else None
                    if sub and sub.pieces and sub.base == ent.idx:
                        extra.extend(sub.pieces)
                    else:
                        complete = False
                p += rlen
        return self._collect_segments(ent, extra), complete


def decode_recycle_i(data: bytes) -> Optional[Tuple[str, int, int]]:
    """Fichier $I de la Corbeille -> (chemin d'origine, taille, date de suppression epoch)."""
    if len(data) < 28:
        return None
    ver, size, dt = struct.unpack_from('<QQQ', data, 0)
    if ver == 2:
        n = struct.unpack_from('<I', data, 24)[0]
        name = data[28:28 + n * 2].decode('utf-16le', errors='ignore').rstrip('\x00')
    elif ver == 1:
        name = data[24:24 + 520].decode('utf-16le', errors='ignore').split('\x00')[0]
    else:
        return None
    return (name, size, ft_to_epoch(dt)) if name else None


class PathResolver:
    def __init__(self):
        self.dirs: Dict[int, Tuple[str, int, int, int]] = {}   # idx -> (nom, parent, parent_seq, seq)
        self.cache: Dict[int, str] = {5: ''}

    def add(self, idx: int, name: str, parent: int, pseq: int, seq: int):
        self.dirs[idx] = (name, parent, pseq, seq)

    def path_of_dir(self, idx: int) -> str:
        if idx in self.cache:
            return self.cache[idx]
        chain = []
        cur = idx
        seen = set()
        orphan = False
        while cur != 5:
            if cur in seen or len(chain) > 128:
                orphan = True
                break
            seen.add(cur)
            d = self.dirs.get(cur)
            if not d:
                orphan = True
                break
            chain.append((cur, d[0]))
            par, pseq = d[1], d[2]
            pd = self.dirs.get(par)
            if par != 5 and pd and pseq and pd[3] and pseq != pd[3]:
                orphan = True      # le parent a été recyclé depuis : lien non fiable
                break
            cur = par
        chain.reverse()
        path = '\\'.join(n for _, n in chain)
        if orphan:
            path = '[Orphelins]\\' + path if path else '[Orphelins]'
        self.cache[idx] = path
        return path


def _segments_to_extents(vol: Volume, segs) -> Optional[List[List[int]]]:
    ext: List[List[int]] = []
    expect = 0
    cs = vol.cs
    for vcn, lcn, ln in segs:
        if ln <= 0:
            continue
        if vcn > expect:
            ext.append([-1, (vcn - expect) * cs])
        if lcn is None:
            ext.append([-1, ln * cs])
        else:
            if vol.total_clusters and lcn + ln > vol.total_clusters + 8:
                return None
            ext.append([vol.abs_off(lcn), ln * cs])
        expect = vcn + ln
    return merge_extents(ext)


def scan_volume(reader: Reader, base: int, sink: FileSink, progress: Progress, mode: str = 'deleted',
                size_hint: int = 0, part_label: str = '', min_size: int = 1,
                carve_records: bool = False, alloc_out: Optional[list] = None) -> int:
    """Analyse une partition NTFS. mode = 'deleted' | 'all'. Retourne le nombre de fichiers émis."""
    try:
        vol = Volume(reader, base, size_hint)
    except NtfsError as e:
        log(f'NTFS : {e}')
        return 0
    if not carve_records:
        try:
            vol.load_mft()
        except NtfsError as e:
            log(f'NTFS : {e} — bascule sur la recherche de records MFT (carving)')
            carve_records = True
    if carve_records:
        return scan_mft_carve(reader, base, sink, progress, vol, mode, part_label, min_size)

    vol.load_bitmap()
    if vol.bitmap is not None and alloc_out is not None:
        bm, cs, bs_ = vol.bitmap, vol.cs, base

        def _alloc(off, bm=bm, cs=cs, bs_=bs_):
            c = (off - bs_) // cs
            return (c >> 3) < len(bm) and bool(bm[c >> 3] & (1 << (c & 7)))
        alloc_out.append((base, base + (vol.vol_size or len(bm) * 8 * cs), _alloc))
    nrec = vol.mft_size // vol.rec_size
    label = part_label or 'NTFS'
    log(f'NTFS : {nrec} records MFT, cluster {vol.cs} octets, record {vol.rec_size} octets')

    resolver = PathResolver()
    progress.window(0, 25)
    progress.total = vol.mft_size

    # ---- Passe 1 : arborescence (répertoires)
    for idx, raw in vol.iter_mft(lambda d, t: progress.update(d, f'{label} : arborescence')):
        if raw[:4] != b'FILE' or not (raw[22] & 2):
            continue
        e = parse_record(raw, vol.rec_size, want_data=False)
        if not e or e.base:
            continue
        bn = e.best_name()
        if bn:
            resolver.add(idx, bn[0], bn[1], bn[2], e.seq)

    # ---- Passe 2 : fichiers
    progress.window(25, 70)
    emitted = 0
    recycle_i: Dict[Tuple[int, str], Tuple[str, int, int]] = {}
    recycle_r: Dict[Tuple[int, str], dict] = {}

    def build_record(e: Entry, idx: int) -> Optional[dict]:
        bn = e.best_name()
        if not bn:
            return None
        name, parent, _ps = bn
        deleted = not e.in_use
        if e.resident is not None:
            ext: List[List[int]] = []
            size = len(e.resident)
            ow = None
            segs: list = []
            complete = True
        else:
            if not e.pieces and not e.attr_list and not e.attr_list_nonres:
                return None
            segs, complete = vol.full_data_segments(e)
            if not segs:
                return None
            ext_try = _segments_to_extents(vol, segs)
            if ext_try is None:
                return None
            ext = ext_try
            if not any(x[0] >= 0 for x in ext):
                return None           # aucune donnée réelle (fichier cloud « à la demande », stub de reparse point…)
            size = e.real_size
            frac = vol.allocated_fraction(segs) if deleted else None
            ow = round(frac * 100, 1) if frac is not None else None
        if size < min_size:
            return None
        dpath = resolver.path_of_dir(parent)
        if mode != 'all' and dpath.lower().startswith('system volume information'):
            return None           # magasin des clichés VSS, métadonnées BitLocker (FVE2.*) : bruit système, jamais des fichiers utilisateur
        status = ST_DELETED if deleted else ST_ACTIVE
        conf = 1.0 if not deleted else 0.96
        if ow:
            conf = max(0.05, conf * (1 - ow / 100.0))
            status = ST_PARTIAL if ow >= 50 else ST_DELETED
        if not complete:
            conf *= 0.6
            status = ST_PARTIAL if status == ST_DELETED else status
        rec = {
            'name': name, 'dir': dpath, 'path': (dpath + '\\' + name) if dpath else name,
            'size': int(size), 'status': status, 'confidence': round(conf, 3), 'source': 'ntfs',
            'mft_ref': idx, 'mtime': e.mtime, 'extents': ext, 'volume': label,
            'overwritten_pct': ow, 'cluster_size': vol.cs, 'deleted': deleted, 'fragments': len(ext),
        }
        if e.resident is not None:
            import base64
            rec['resident_b64'] = base64.b64encode(e.resident).decode('ascii')
        if e.dflags & 0x0001:
            rec['compressed'] = True
            rec['comp_unit'] = e.comp_unit
        elif e.resident is None and 0 < e.init_size < e.real_size:
            # taille « initialisée » : au-delà, NTFS renvoie des zéros (les clusters contiennent des restes d'anciens fichiers)
            rec['valid_size'] = int(e.init_size)
        if e.dflags & 0x4000:
            rec['encrypted'] = True
            rec['confidence'] = min(rec['confidence'], 0.4)
        if e.dflags & 0x8000:
            rec['sparse'] = True
        return rec

    def flush_recycle():
        nonlocal emitted
        for key, rec in recycle_r.items():
            info = recycle_i.get(key)
            if info:
                orig, osize, dt = info
                base_name, _ = split_name(orig)
                rec['name'] = base_name or rec['name']
                rec['path'] = 'Corbeille\\' + orig.replace(':', '')
                rec['dir'] = rec['path'].rsplit('\\', 1)[0]
                rec['original_path'] = orig
                if dt:
                    rec['deleted_at'] = dt
                rec['status'] = ST_DELETED if rec['status'] == ST_ACTIVE else rec['status']
            if sink.add(rec) is not None:
                emitted += 1

    for idx, raw in vol.iter_mft(lambda d, t: progress.update(d, f'{label} : analyse des fichiers')):
        if idx < 24 or raw[:4] != b'FILE':
            continue
        flags = raw[22] | (raw[23] << 8)
        if flags & 2:
            continue
        e = parse_record(raw, vol.rec_size)
        if not e or e.base:
            continue
        e.idx = idx
        bn = e.best_name()
        if not bn:
            continue
        name, parent, _ = bn
        if name.startswith('$I') and len(name) > 2 and e.resident is not None:
            info = decode_recycle_i(e.resident)
            if info:
                recycle_i[(parent, name[2:])] = info
                if '$recycle.bin' in resolver.path_of_dir(parent).lower():
                    continue          # métadonnée de la Corbeille : fusionnée dans l'entrée $R correspondante
        if mode == 'deleted' and e.in_use and not name.startswith('$R'):
            continue
        rec = build_record(e, idx)
        if not rec:
            continue
        if name.startswith('$R') and len(name) > 2 and '$recycle.bin' in rec['dir'].lower():
            recycle_r[(parent, name[2:])] = rec
            continue
        if mode == 'deleted' and not rec['status']:
            continue
        if sink.add(rec, dedupe_key=('ntfs', base, idx, e.seq)) is not None:
            emitted += 1
    flush_recycle()
    progress.update(vol.mft_size, force=True)
    return emitted


def scan_mft_carve(reader: Reader, base: int, sink: FileSink, progress: Progress, vol: Volume, mode: str,
                   part_label: str, min_size: int = 1, live_ranges: Optional[list] = None) -> int:
    """Recherche des records FILE0 sur tout le volume (MFT détruite, volume reformaté)."""
    import base64
    total = vol.vol_size or (reader.size or 0) - base
    progress.total = total
    progress.window(0, 95)
    resolver = PathResolver()
    cands: List[Entry] = []
    found_base = None
    rs = vol.rec_size
    n_records = 0
    log(f'NTFS carving MFT : taille de record {rs}, cluster {vol.cs}')
    max_keep = 3_000_000
    live = live_ranges or []

    def in_live(abs_off: int) -> bool:
        return any(a <= abs_off < b for a, b in live)
    for pos, block in iter_blocks(reader, base, base + total, 8 * 1024 * 1024):
        i = block.find(b'FILE0')
        while i != -1:
            if (pos + i - base) % 512 == 0 and i + 48 <= len(block):
                alloc = struct.unpack_from('<I', block, i + 28)[0]
                size = alloc if alloc in (512, 1024, 2048, 4096) else rs
                if i + size <= len(block):
                    raw = bytes(block[i:i + size])
                    e = parse_record(raw, size)
                    if e and not e.base:
                        n_records += 1
                        e.idx = struct.unpack_from('<I', raw, 44)[0]
                        if e.idx == 0 and found_base is None and not vol.have_boot and e.pieces:
                            segs0 = parse_runs(e.pieces[0][1], 0)
                            if segs0 and segs0[0][1] is not None:
                                found_base = (pos + i) - segs0[0][1] * vol.cs
                        if e.is_dir:
                            bn = e.best_name()
                            if bn:
                                resolver.add(e.idx, bn[0], bn[1], bn[2], e.seq)
                        elif e.idx >= 24 and len(cands) < max_keep and not in_live(pos + i):
                            # hors de la MFT actuelle = reste d'une ancienne MFT (volume reformaté, MFT déplacée) :
                            # ces enregistrements, même marqués « en service », sont des fichiers de l'ancien volume
                            cands.append(e)
            i = block.find(b'FILE0', i + 1)
        progress.update(pos + len(block) - base, f'{part_label or "NTFS"} : recherche de records MFT',
                        recordsFound=n_records)
    if not vol.have_boot:
        vol.base = found_base if found_base is not None else base
        if found_base is not None:
            log(f'NTFS carving : base du volume déduite = {found_base}')
    log(f'NTFS carving : {n_records} records exploitables, {len(cands)} fichiers candidats')

    emitted = 0
    for e in cands:
        bn = e.best_name()
        if not bn:
            continue
        name, parent, _ = bn
        if e.resident is not None:
            ext: List[List[int]] = []
            size = len(e.resident)
        elif e.pieces:
            segs = vol._collect_segments(e)
            ext_try = _segments_to_extents(vol, segs)
            if ext_try is None:
                continue
            ext = ext_try
            size = e.real_size
        else:
            continue
        if size < min_size:
            continue
        dpath = resolver.path_of_dir(parent)
        rec = {'name': name, 'dir': dpath, 'path': (dpath + '\\' + name) if dpath else name, 'size': int(size),
               'status': ST_DELETED, 'confidence': 0.7, 'source': 'ntfs',
               'mft_ref': e.idx, 'mtime': e.mtime, 'extents': ext, 'volume': part_label or 'NTFS',
               'cluster_size': vol.cs, 'recovered_by': 'mft_carve', 'deleted': True,
               'fragments': len(ext)}
        if e.resident is not None:
            rec['resident_b64'] = base64.b64encode(e.resident).decode('ascii')
        if e.dflags & 0x0001:
            rec['compressed'] = True
            rec['comp_unit'] = e.comp_unit
        if sink.add(rec, dedupe_key=('ntfs', base, e.idx, e.seq)) is not None:
            emitted += 1
    return emitted

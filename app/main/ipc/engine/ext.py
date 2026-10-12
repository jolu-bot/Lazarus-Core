"""Moteur ext2/ext3/ext4 : inodes supprimés (extents ou blocs indirects), noms via les « slack » de répertoires,
détection de réallocation par le bitmap de blocs."""
from __future__ import annotations

import struct
from typing import Dict, List, Optional, Tuple

from .common import FileSink, Progress, ST_ACTIVE, ST_DELETED, ST_PARTIAL, STOP, log, merge_extents
from .devio import Reader

EXT_MAGIC = 0xEF53
FL_EXTENTS = 0x80000
FL_INLINE = 0x10000000
INC_64BIT = 0x80


class ExtVolume:
    def __init__(self, reader: Reader, base: int):
        self.r = reader
        self.base = base
        sb = reader.read_at(base + 1024, 1024)
        if len(sb) < 1024 or struct.unpack_from('<H', sb, 56)[0] != EXT_MAGIC:
            raise ValueError('superbloc ext introuvable')
        self.sb = sb
        self.log_bs = struct.unpack_from('<I', sb, 24)[0]
        if self.log_bs > 6:
            raise ValueError('taille de bloc invalide')
        self.bs = 1024 << self.log_bs
        self.blocks_lo = struct.unpack_from('<I', sb, 4)[0]
        self.first_data = struct.unpack_from('<I', sb, 20)[0]
        self.bpg = struct.unpack_from('<I', sb, 32)[0]
        self.ipg = struct.unpack_from('<I', sb, 40)[0]
        rev = struct.unpack_from('<I', sb, 76)[0]
        self.isz = struct.unpack_from('<H', sb, 88)[0] if rev >= 1 else 128
        self.incompat = struct.unpack_from('<I', sb, 96)[0]
        self.blocks = self.blocks_lo | ((struct.unpack_from('<I', sb, 0x150)[0] << 32) if self.incompat & INC_64BIT else 0)
        self.desc_size = struct.unpack_from('<H', sb, 254)[0] if self.incompat & INC_64BIT else 32
        if self.desc_size < 32:
            self.desc_size = 32
        if not self.bpg or not self.ipg or self.isz < 128 or self.isz > self.bs:
            raise ValueError('géométrie ext invalide')
        self.groups = -(-(self.blocks - self.first_data) // self.bpg)
        self.inodes = struct.unpack_from('<I', sb, 0)[0]
        self.is_ext4 = bool(struct.unpack_from('<I', sb, 100)[0] & 0x8 or self.incompat & 0x40)
        gdt_block = self.first_data + 1
        raw = reader.read_at(base + gdt_block * self.bs, self.groups * self.desc_size)
        self.gd = []
        for g in range(self.groups):
            d = raw[g * self.desc_size:(g + 1) * self.desc_size]
            if len(d) < 32:
                break
            bb, ib, it = struct.unpack_from('<III', d, 0)
            flags = struct.unpack_from('<H', d, 18)[0]
            if self.desc_size >= 64 and len(d) >= 44:
                bb |= struct.unpack_from('<I', d, 0x20)[0] << 32
                ib |= struct.unpack_from('<I', d, 0x24)[0] << 32
                it |= struct.unpack_from('<I', d, 0x28)[0] << 32
            self.gd.append({'bb': bb, 'ib': ib, 'it': it, 'flags': flags})
        self.bitmap: Optional[bytearray] = None

    def blk(self, n: int, count: int = 1) -> bytes:
        return self.r.read_at(self.base + n * self.bs, count * self.bs)

    def load_block_bitmap(self):
        bm = bytearray()
        per = self.bpg // 8
        for g, d in enumerate(self.gd):
            if d['flags'] & 0x2 or not d['bb'] or d['bb'] >= self.blocks:      # BLOCK_UNINIT
                bm += b'\x00' * per
                continue
            data = self.blk(d['bb'])
            bm += data[:per].ljust(per, b'\x00')
        self.bitmap = bm

    def alloc_fraction(self, exts: List[List[int]]) -> Optional[float]:
        if self.bitmap is None:
            return None
        total = used = 0
        for off, ln in exts:
            if off < 0:
                continue
            b0 = (off - self.base) // self.bs - self.first_data
            nb = ln // self.bs
            for b in range(b0, b0 + nb):
                if (b >> 3) >= len(self.bitmap) or b < 0:
                    break
                total += 1
                if self.bitmap[b >> 3] & (1 << (b & 7)):
                    used += 1
            if total > 2_000_000:       # extrapolation pour les très gros fichiers
                break
        return (used / total) if total else None

    # ---- extents
    def _walk_extents(self, node: bytes, deleted: bool, depth_guard: int = 6) -> List[Tuple[int, int, int]]:
        out: List[Tuple[int, int, int]] = []
        if len(node) < 12 or struct.unpack_from('<H', node, 0)[0] != 0xF30A:
            return out
        entries, maxe, depth = struct.unpack_from('<HHH', node, 2)
        n = min(maxe, (len(node) - 12) // 12) if (deleted and entries == 0) else min(entries, (len(node) - 12) // 12)
        for i in range(n):
            e = node[12 + i * 12:24 + i * 12]
            if depth == 0:
                lb, ln, hi, lo = struct.unpack('<IHHI', e)
                if ln > 32768:
                    ln -= 32768
                phys = (hi << 32) | lo
                if ln == 0 or phys == 0 or phys >= self.blocks:
                    continue
                out.append((lb, phys, ln))
            elif depth_guard > 0:
                lb, lo, hi, _ = struct.unpack('<IIHH', e)
                child = (hi << 32) | lo
                if child and child < self.blocks:
                    out.extend(self._walk_extents(self.blk(child), deleted, depth_guard - 1))
        return out

    def _indirect(self, blockno: int, level: int, out: List[int], limit: int):
        if blockno == 0 or blockno >= self.blocks or len(out) >= limit:
            return
        data = self.blk(blockno)
        ptrs = struct.unpack('<%dI' % (len(data) // 4), data[:len(data) // 4 * 4])
        for p in ptrs:
            if len(out) >= limit:
                return
            if level == 1:
                out.append(p)
            else:
                self._indirect(p, level - 1, out, limit)

    def file_extents(self, inode: bytes, size: int, deleted: bool) -> List[List[int]]:
        flags = struct.unpack_from('<I', inode, 32)[0]
        iblock = inode[40:100]
        need = -(-size // self.bs)
        segs: List[Tuple[int, int, int]] = []
        if flags & FL_EXTENTS:
            segs = self._walk_extents(iblock, deleted)
        else:
            blocks: List[int] = []
            ptr = struct.unpack('<15I', iblock)
            blocks.extend(ptr[:12])
            for lvl, idx in ((1, 12), (2, 13), (3, 14)):
                self._indirect(ptr[idx], lvl, blocks, need + 1)
            blocks = blocks[:need]
            for lb, pb in enumerate(blocks):
                if pb and pb < self.blocks:
                    segs.append((lb, pb, 1))
        segs.sort()
        out: List[List[int]] = []
        expect = 0
        for lb, pb, ln in segs:
            if lb > expect:
                out.append([-1, (lb - expect) * self.bs])
            if lb < expect:
                continue
            out.append([self.base + pb * self.bs, ln * self.bs])
            expect = lb + ln
        return merge_extents(out)


def _dir_entries(data: bytes):
    """Itère les entrées d'un bloc de répertoire, y compris les entrées cachées dans le slack."""
    p = 0
    n = len(data)
    while p + 8 <= n:
        ino, rec_len, name_len, ftype = struct.unpack_from('<IHBB', data, p)
        if rec_len < 8 or rec_len % 4 or p + rec_len > n:
            break
        if ino and name_len and 8 + name_len <= rec_len:
            yield ino, data[p + 8:p + 8 + name_len], ftype, False
        used = (8 + name_len + 3) & ~3
        q = p + used
        end = p + rec_len
        # slack : entrées supprimées fusionnées dans l'enregistrement précédent
        while q + 8 <= end:
            i2, rl2, nl2, ft2 = struct.unpack_from('<IHBB', data, q)
            if rl2 < 8 or rl2 % 4 or q + rl2 > end or 8 + nl2 > rl2 or nl2 == 0:
                break
            if i2:
                yield i2, data[q + 8:q + 8 + nl2], ft2, True
            q += (8 + nl2 + 3) & ~3
            if q >= end:
                break
        p += rec_len


def scan_ext(reader: Reader, base: int, sink: FileSink, progress: Progress, mode: str = 'deleted',
             part_label: str = '', min_size: int = 1, alloc_out: Optional[list] = None) -> int:
    try:
        v = ExtVolume(reader, base)
    except ValueError as e:
        log(f'ext : {e}')
        return 0
    label = part_label or ('ext4' if v.is_ext4 else 'ext')
    v.load_block_bitmap()
    if alloc_out is not None and v.bitmap is not None:
        def _alloc(off, v=v):
            b = (off - v.base) // v.bs - v.first_data
            return b < 0 or ((b >> 3) < len(v.bitmap) and bool(v.bitmap[b >> 3] & (1 << (b & 7))))
        alloc_out.append((base, base + v.blocks * v.bs, _alloc))
    progress.total = max(v.groups, 1)
    progress.window(0, 80)
    dirs: Dict[int, List[List[int]]] = {}
    cands: List[Tuple[int, dict]] = []
    isz, ipg = v.isz, v.ipg
    for g, d in enumerate(v.gd):
        if STOP.is_set():
            break
        if d['flags'] & 0x1 or not d['it'] or d['it'] >= v.blocks:       # INODE_UNINIT
            progress.update(g + 1, f'{label} : groupe {g + 1}/{v.groups}')
            continue
        table = v.r.read_at(base + d['it'] * v.bs, ipg * isz)
        for k in range(min(ipg, len(table) // isz)):
            ino = g * ipg + k + 1
            raw = table[k * isz:k * isz + isz]
            mode_ = struct.unpack_from('<H', raw, 0)[0]
            if mode_ == 0:
                # un inode supprimé sous ext4 conserve parfois son mode ; mode==0 = jamais utilisé/effacé
                continue
            fmt = mode_ & 0xF000
            size = struct.unpack_from('<I', raw, 4)[0] | (struct.unpack_from('<I', raw, 108)[0] << 32)
            dtime = struct.unpack_from('<I', raw, 20)[0]
            links = struct.unpack_from('<H', raw, 26)[0]
            mtime = struct.unpack_from('<I', raw, 16)[0]
            deleted = dtime != 0 and links == 0
            if fmt == 0x4000 and not deleted:
                try:
                    dirs[ino] = v.file_extents(raw, size, False)
                except Exception:
                    pass
                continue
            if fmt != 0x8000 or size < max(1, min_size):
                continue
            if mode == 'deleted' and not deleted:
                continue
            if struct.unpack_from('<I', raw, 32)[0] & FL_INLINE:
                continue
            try:
                ext = v.file_extents(raw, size, deleted)
            except Exception:
                continue
            if not ext:
                continue
            cands.append((ino, {'raw_size': size, 'mtime': mtime, 'deleted': deleted, 'ext': ext,
                                'dtime': dtime}))
        progress.update(g + 1, f'{label} : groupe {g + 1}/{v.groups}')

    # ---- noms et chemins via les répertoires
    progress.window(80, 18)
    names: Dict[int, Tuple[str, int]] = {}       # inode -> (nom, inode du répertoire parent)
    dirnames: Dict[int, Tuple[str, int]] = {2: ('', 2)}
    wanted = {ino for ino, _ in cands}
    for dino, exts in dirs.items():
        for off, ln in exts:
            if off < 0:
                continue
            for b in range(0, ln, v.bs):
                data = reader.read_at(off + b, v.bs)
                for ino, nm, ft, slack in _dir_entries(data):
                    try:
                        name = nm.decode('utf-8', errors='replace')
                    except Exception:
                        continue
                    if name in ('.', '..'):
                        continue
                    if ft == 2 and not slack:
                        dirnames.setdefault(ino, (name, dino))
                    if ino in wanted and (ino not in names or slack is False):
                        names[ino] = (name, dino)
        progress.update(0, f'{label} : lecture des répertoires')

    def dpath(ino: int) -> str:
        parts = []
        seen = set()
        cur = ino
        while cur != 2 and cur in dirnames and cur not in seen:
            seen.add(cur)
            parts.append(dirnames[cur][0])
            cur = dirnames[cur][1]
        parts.reverse()
        return '\\'.join(parts) if cur == 2 else '[Orphelins]\\' + '\\'.join(parts)

    emitted = 0
    for ino, c in cands:
        nm = names.get(ino)
        deleted = c['deleted']
        name = nm[0] if nm else f'inode_{ino}'
        d = dpath(nm[1]) if nm else '[Sans nom]'
        frac = v.alloc_fraction(c['ext']) if deleted else None
        ow = round(frac * 100, 1) if frac is not None else None
        conf = 1.0 if not deleted else 0.75 * (1 - (ow or 0) / 100.0)
        if deleted and not nm:
            conf *= 0.9
        status = ST_ACTIVE if not deleted else (ST_PARTIAL if (ow or 0) >= 50 else ST_DELETED)
        rec = {'name': name, 'dir': d, 'path': (d + '\\' + name) if d else name, 'size': int(c['raw_size']),
               'status': status, 'confidence': round(max(conf, 0.05), 3), 'source': 'ext', 'mtime': c['mtime'],
               'extents': c['ext'], 'volume': label, 'overwritten_pct': ow, 'cluster_size': v.bs,
               'deleted': deleted, 'fragments': len(c['ext']), 'inode': ino}
        if deleted and c['dtime']:
            rec['deleted_at'] = c['dtime']
        if sink.add(rec, dedupe_key=('ext', base, ino)) is not None:
            emitted += 1
    return emitted

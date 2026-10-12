"""Conteneurs d'images disque : VHD (fixe/dynamique), VHDX, VMDK (monolithique, plat ou « sparse »), fichiers découpés.

Tous exposent la même interface que devio.Reader (read_at, size, sector_size, bad_count…) : les moteurs
(NTFS, FAT, carving, partitions…) fonctionnent donc à l'identique sur un disque physique, une image brute, un VHD ou un RAID.
"""
from __future__ import annotations

import os
import re
import struct
import uuid
from typing import List, Optional

from .devio import DeviceError, Reader


class VirtualReader:
    """Base commune des lecteurs virtuels."""
    raw = False

    def __init__(self, path: str):
        self.path = path
        self.size: Optional[int] = 0
        self.sector_size = 512
        self.bad_sectors: List[int] = []
        self.bad_count = 0

    def read_at(self, off: int, n: int) -> bytes:  # pragma: no cover - surchargé
        raise NotImplementedError

    def read_strict(self, off: int, n: int):
        return self.read_at(off, n), True

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


# ----------------------------------------------------------------------------- VHD
class VhdReader(VirtualReader):
    def __init__(self, path: str):
        super().__init__(path)
        self.f = Reader(path)
        fsize = self.f.size or os.path.getsize(path)
        footer = self.f.read_at(fsize - 512, 512)
        if footer[:8] != b'conectix':
            footer = self.f.read_at(0, 512)         # copie en tête de fichier (VHD dynamique)
            if footer[:8] != b'conectix':
                raise DeviceError('Pas un VHD valide (signature « conectix » absente)')
        self.disk_type = struct.unpack('>I', footer[60:64])[0]
        self.size = struct.unpack('>Q', footer[48:56])[0]
        if self.disk_type == 2:                      # fixe : données brutes au début du fichier
            self.dynamic = False
        elif self.disk_type == 3:
            self.dynamic = True
            doff = struct.unpack('>Q', footer[16:24])[0]
            hdr = self.f.read_at(doff, 1024)
            if hdr[:8] != b'cxsparse':
                raise DeviceError('En-tête dynamique VHD invalide')
            self.bat_off = struct.unpack('>Q', hdr[16:24])[0]
            self.max_entries = struct.unpack('>I', hdr[28:32])[0]
            self.block_size = struct.unpack('>I', hdr[32:36])[0]
            raw = self.f.read_at(self.bat_off, self.max_entries * 4)
            self.bat = struct.unpack('>%dI' % (len(raw) // 4), raw[:len(raw) // 4 * 4])
            bitmap = -(-(self.block_size // 512) // 8)
            self.bitmap_bytes = -(-bitmap // 512) * 512
        else:
            raise DeviceError('VHD différentiel (disque enfant) non pris en charge : utilisez le disque parent fusionné')

    def read_at(self, off: int, n: int) -> bytes:
        if n <= 0 or off < 0 or off >= self.size:
            return b''
        n = min(n, self.size - off)
        if not self.dynamic:
            return self.f.read_at(off, n)
        out = bytearray()
        while n > 0:
            idx, inner = divmod(off, self.block_size)
            take = min(n, self.block_size - inner)
            sec = self.bat[idx] if idx < len(self.bat) else 0xFFFFFFFF
            if sec == 0xFFFFFFFF:
                out += b'\x00' * take
            else:
                out += self.f.read_at(sec * 512 + self.bitmap_bytes + inner, take).ljust(take, b'\x00')
            off += take
            n -= take
        return bytes(out)

    def close(self):
        self.f.close()


# ----------------------------------------------------------------------------- VHDX
_G_BAT = uuid.UUID('2DC27766-F623-4200-9D64-115E9BFD4A08')
_G_META = uuid.UUID('8B7CA206-4790-4B9A-B8FE-575F050F886E')
_G_PARAMS = uuid.UUID('CAA16737-FA36-4D43-B3B6-33F0AA44E76B')
_G_VSIZE = uuid.UUID('2FA54224-CD1B-4876-B211-5DBED83BF4B8')
_G_LSEC = uuid.UUID('8141BF1D-A96F-4709-BA47-F233A8FAAB5F')


class VhdxReader(VirtualReader):
    def __init__(self, path: str):
        super().__init__(path)
        self.f = Reader(path)
        if self.f.read_at(0, 8) != b'vhdxfile':
            raise DeviceError('Pas un VHDX valide')
        rt = self.f.read_at(192 * 1024, 64 * 1024)
        if rt[:4] != b'regi':
            raise DeviceError('Table de régions VHDX illisible')
        count = struct.unpack_from('<I', rt, 8)[0]
        regions = {}
        for i in range(min(count, 2047)):
            e = rt[16 + i * 32:48 + i * 32]
            regions[uuid.UUID(bytes_le=bytes(e[:16]))] = (struct.unpack_from('<Q', e, 16)[0], struct.unpack_from('<I', e, 24)[0])
        if _G_BAT not in regions or _G_META not in regions:
            raise DeviceError('Régions VHDX BAT/métadonnées absentes')
        moff, mlen = regions[_G_META]
        meta = self.f.read_at(moff, mlen)
        if meta[:8] != b'metadata':
            raise DeviceError('Métadonnées VHDX invalides')
        items = {}
        for i in range(struct.unpack_from('<H', meta, 10)[0]):
            e = meta[32 + i * 32:64 + i * 32]
            items[uuid.UUID(bytes_le=bytes(e[:16]))] = (struct.unpack_from('<I', e, 16)[0], struct.unpack_from('<I', e, 20)[0])
        o, _ = items[_G_PARAMS]
        self.block_size, flags = struct.unpack_from('<II', meta, o)
        if flags & 2:
            raise DeviceError('VHDX différentiel (avec parent) non pris en charge')
        self.size = struct.unpack_from('<Q', meta, items[_G_VSIZE][0])[0]
        self.sector_size = struct.unpack_from('<I', meta, items[_G_LSEC][0])[0] if _G_LSEC in items else 512
        self.chunk_ratio = (1 << 23) * self.sector_size // self.block_size
        boff, blen = regions[_G_BAT]
        raw = self.f.read_at(boff, blen)
        self.bat = struct.unpack('<%dQ' % (len(raw) // 8), raw[:len(raw) // 8 * 8])

    def read_at(self, off: int, n: int) -> bytes:
        if n <= 0 or off < 0 or off >= self.size:
            return b''
        n = min(n, self.size - off)
        out = bytearray()
        while n > 0:
            blk, inner = divmod(off, self.block_size)
            take = min(n, self.block_size - inner)
            bi = blk + blk // self.chunk_ratio
            entry = self.bat[bi] if bi < len(self.bat) else 0
            state = entry & 7
            if state in (6, 7):
                out += self.f.read_at(((entry >> 20) << 20) + inner, take).ljust(take, b'\x00')
            else:
                out += b'\x00' * take
            off += take
            n -= take
        return bytes(out)

    def close(self):
        self.f.close()


# ----------------------------------------------------------------------------- VMDK
class VmdkReader(VirtualReader):
    """VMDK monolithique « sparse » (KDMV) ou descripteur texte pointant vers un fichier plat."""

    def __init__(self, path: str):
        super().__init__(path)
        head = open(path, 'rb').read(512)
        self.flat: Optional[Reader] = None
        self.f: Optional[Reader] = None
        if head[:4] == b'KDMV':
            self.f = Reader(path)
            (_ver, _flags, cap, grain, desc_off, desc_sz, n_gte, _rgd, gd_off, _ovh) = struct.unpack_from('<IIQQQQIQQQ', head, 4)
            if n_gte == 0 or grain == 0:
                raise DeviceError('VMDK invalide')
            self.size = cap * 512
            self.grain = grain * 512
            self.gtes_per_gt = n_gte
            gd_entries = -(-cap // (grain * n_gte))
            raw = self.f.read_at(gd_off * 512, gd_entries * 4)
            self.gd = struct.unpack('<%dI' % (len(raw) // 4), raw[:len(raw) // 4 * 4])
            self._gt_cache = {}
        else:
            text = open(path, 'r', encoding='utf-8', errors='ignore').read(65536)
            m = re.search(r'RW\s+(\d+)\s+FLAT\s+"([^"]+)"\s*(\d*)', text)
            if not m:
                raise DeviceError('Descripteur VMDK non reconnu (seuls les formats monolithique sparse et plat sont pris en charge)')
            fp = os.path.join(os.path.dirname(os.path.abspath(path)), m.group(2))
            self.flat = Reader(fp)
            self.skip = int(m.group(3) or 0) * 512
            self.size = int(m.group(1)) * 512

    def _gt(self, gdi: int):
        if gdi in self._gt_cache:
            return self._gt_cache[gdi]
        sec = self.gd[gdi] if gdi < len(self.gd) else 0
        if not sec:
            gt = None
        else:
            raw = self.f.read_at(sec * 512, self.gtes_per_gt * 4)
            gt = struct.unpack('<%dI' % (len(raw) // 4), raw[:len(raw) // 4 * 4])
        self._gt_cache[gdi] = gt
        return gt

    def read_at(self, off: int, n: int) -> bytes:
        if n <= 0 or off < 0 or off >= self.size:
            return b''
        n = min(n, self.size - off)
        if self.flat is not None:
            return self.flat.read_at(self.skip + off, n)
        out = bytearray()
        while n > 0:
            g, inner = divmod(off, self.grain)
            take = min(n, self.grain - inner)
            gdi, gti = divmod(g, self.gtes_per_gt)
            gt = self._gt(gdi)
            sec = gt[gti] if gt and gti < len(gt) else 0
            if sec <= 1:
                out += b'\x00' * take
            else:
                out += self.f.read_at(sec * 512 + inner, take).ljust(take, b'\x00')
            off += take
            n -= take
        return bytes(out)

    def close(self):
        for r in (self.f, self.flat):
            if r:
                r.close()


# ----------------------------------------------------------------------------- fichiers découpés
class SplitReader(VirtualReader):
    """image.001, image.002, … concaténés."""

    def __init__(self, first: str):
        super().__init__(first)
        base, ext = os.path.splitext(first)
        width = len(ext) - 1
        self.parts: List[Reader] = []
        self.starts: List[int] = []
        total = 0
        i = int(ext[1:])
        while True:
            p = f'{base}.{i:0{width}d}'
            if not os.path.exists(p):
                break
            r = Reader(p)
            self.parts.append(r)
            self.starts.append(total)
            total += r.size or 0
            i += 1
        if not self.parts:
            raise DeviceError('Fichiers découpés introuvables')
        self.size = total

    def read_at(self, off: int, n: int) -> bytes:
        out = bytearray()
        for r, s in zip(self.parts, self.starts):
            sz = r.size or 0
            if off + n <= s or off >= s + sz:
                continue
            a = max(off, s)
            b = min(off + n, s + sz)
            out += r.read_at(a - s, b - a)
        return bytes(out)

    def close(self):
        for r in self.parts:
            r.close()

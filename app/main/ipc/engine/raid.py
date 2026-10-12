"""RAID virtuel logiciel (JBOD/span, RAID 0, 1, 5, 10) avec reconstruction d'un disque manquant et détection automatique
des paramètres (taille de bande, ordre des disques, disposition de la parité).

Le volume virtuel s'utilise comme n'importe quelle source : partitions, NTFS, carving… s'appliquent directement.
Spécification textuelle :   raid:{"level":"raid5","stripe":65536,"layout":"ls","order":[0,1,2],"offset":0,
                                  "members":["\\\\.\\PhysicalDrive1","d2.img",null]}
"""
from __future__ import annotations

import itertools
import json
from typing import Dict, List, Optional

from .containers import VirtualReader
from .devio import DeviceError

LAYOUTS = ('ls', 'la', 'rs', 'ra')     # left/right × symmetric/asymmetric (nomenclature mdadm)


class MemReader(VirtualReader):
    """Lecteur sur octets en mémoire (cache des premiers Mio d'un membre pour la détection)."""

    def __init__(self, data: bytes, size: Optional[int] = None):
        super().__init__('mem')
        self.data = data
        self.size = size if size is not None else len(data)

    def read_at(self, off: int, n: int) -> bytes:
        return self.data[off:off + n] if off < len(self.data) else b''


class VirtualRaid(VirtualReader):
    def __init__(self, members: list, level: str = 'raid5', stripe: int = 65536, layout: str = 'ls',
                 order: Optional[List[int]] = None, offset: int = 0, label: str = 'raid'):
        super().__init__(label)
        order = order or list(range(len(members)))
        self.members = [members[i] for i in order]
        self.n = len(self.members)
        self.level = level.lower()
        self.stripe = int(stripe)
        self.layout = layout
        self.offset = int(offset)
        present = [m for m in self.members if m is not None]
        if not present:
            raise DeviceError('RAID : aucun disque membre')
        missing = self.n - len(present)
        if missing > (1 if self.level in ('raid5',) else 0) and self.level != 'raid1' and self.level != 'raid10':
            raise DeviceError('RAID : trop de disques manquants pour ce niveau')
        msize = min((m.size or 0) for m in present) - self.offset
        if msize <= 0:
            raise DeviceError('RAID : taille des membres inconnue')
        self.msize = msize
        sec = max(m.sector_size for m in present)
        self.sector_size = sec
        lv = self.level
        if lv in ('jbod', 'span'):
            self.size = sum(((m.size or 0) - self.offset) for m in self.members if m is not None)
        elif lv == 'raid0':
            self.size = msize // self.stripe * self.stripe * self.n
        elif lv == 'raid1':
            self.size = msize
        elif lv == 'raid5':
            if self.n < 3:
                raise DeviceError('RAID 5 : au moins 3 disques')
            self.size = msize // self.stripe * self.stripe * (self.n - 1)
        elif lv == 'raid10':
            if self.n < 4 or self.n % 2:
                raise DeviceError('RAID 10 : nombre pair de disques (≥ 4)')
            self.size = msize // self.stripe * self.stripe * (self.n // 2)
        else:
            raise DeviceError(f'Niveau RAID non pris en charge : {level}')

    # -- lecture d'un membre (avec reconstruction RAID 5 si absent)
    def _m(self, idx: int, off: int, n: int) -> bytes:
        m = self.members[idx]
        return m.read_at(self.offset + off, n).ljust(n, b'\x00')

    def _raid5_locate(self, chunk: int):
        row, d = divmod(chunk, self.n - 1)
        n = self.n
        if self.layout in ('ls', 'la'):
            p = (n - 1) - (row % n)
        else:
            p = row % n
        if self.layout in ('ls', 'rs'):
            disk = (p + 1 + d) % n
        else:
            disk = d if d < p else d + 1
        return row, disk

    def read_at(self, off: int, n: int) -> bytes:
        if n <= 0 or off < 0 or off >= self.size:
            return b''
        n = min(n, self.size - off)
        out = bytearray()
        lv = self.level
        while n > 0:
            if lv in ('jbod', 'span'):
                pos = off
                got = False
                for m in self.members:
                    if m is None:
                        continue
                    sz = (m.size or 0) - self.offset
                    if pos < sz:
                        take = min(n, sz - pos)
                        out += m.read_at(self.offset + pos, take).ljust(take, b'\x00')
                        off += take
                        n -= take
                        got = True
                        break
                    pos -= sz
                if not got:
                    break
                continue
            if lv == 'raid1':
                data = b''
                for m in self.members:
                    if m is not None:
                        data = m.read_at(self.offset + off, n)
                        if data:
                            break
                out += data.ljust(n, b'\x00')
                break
            chunk, inner = divmod(off, self.stripe)
            take = min(n, self.stripe - inner)
            if lv == 'raid0':
                row, disk = divmod(chunk, self.n)
                out += self._m(disk, row * self.stripe + inner, take)
            elif lv == 'raid10':
                pairs = self.n // 2
                row, pair = divmod(chunk, pairs)
                for k in (pair * 2, pair * 2 + 1):
                    if self.members[k] is not None:
                        out += self._m(k, row * self.stripe + inner, take)
                        break
                else:
                    out += b'\x00' * take
            else:  # raid5
                row, disk = self._raid5_locate(chunk)
                moff = row * self.stripe + inner
                if self.members[disk] is not None:
                    out += self._m(disk, moff, take)
                else:       # disque manquant : XOR de tous les autres (données + parité)
                    acc = bytearray(take)
                    for k in range(self.n):
                        if k == disk or self.members[k] is None:
                            continue
                        blk = self._m(k, moff, take)
                        acc = bytearray(a ^ b for a, b in zip(acc, blk)) if take < 4096 else \
                            (int.from_bytes(acc, 'little') ^ int.from_bytes(blk, 'little')).to_bytes(take, 'little')
                    out += bytes(acc)
            off += take
            n -= take
        return bytes(out)

    def close(self):
        for m in self.members:
            if m is not None and hasattr(m, 'close'):
                try:
                    m.close()
                except Exception:
                    pass


def build_from_spec(spec: dict):
    from .devio import open_reader
    members = [open_reader(p) if p else None for p in spec['members']]
    return VirtualRaid(members, spec.get('level', 'raid5'), int(spec.get('stripe', 65536)), spec.get('layout', 'ls'),
                       spec.get('order'), int(spec.get('offset', 0)), label='raid:' + json.dumps(spec, separators=(',', ':')))


def _ntfs_mft_ok(raid, start: int) -> bool:
    """L'enregistrement $MFT (très loin du début du volume) est-il lisible à travers la reconstruction ?"""
    import struct
    boot = raid.read_at(start, 512)
    if boot[3:11] != b'NTFS    ':
        return False
    bps = struct.unpack_from('<H', boot, 11)[0]
    cs = bps * boot[13]
    lcn = struct.unpack_from('<Q', boot, 48)[0]
    return raid.read_at(start + lcn * cs, 4) == b'FILE'


def _ntfs_backup_ok(raid, start: int, part_size: int = 0) -> bool:
    """Secteur de démarrage NTFS de secours (dernier secteur du volume) : dépend de la taille ET de la reconstruction."""
    import struct
    boot = raid.read_at(start, 512)
    if boot[3:11] != b'NTFS    ':
        return False
    bps = struct.unpack_from('<H', boot, 11)[0]
    tot = struct.unpack_from('<Q', boot, 40)[0]
    for off in {start + tot * bps, start + part_size - 512 if part_size else -1}:
        if off > 0 and raid.read_at(off, 512)[3:11] == b'NTFS    ':
            return True
    return False


def _mft_coherence(raid, start: int, max_records: int = 4096) -> int:
    """0-400 : part des premiers enregistrements $MFT lisibles (signature FILE + fixups valides) à travers la reconstruction.
    Une mauvaise taille de bande / un mauvais ordre mélange les disques dès que la MFT dépasse une bande."""
    import struct
    from . import ntfs
    boot = raid.read_at(start, 512)
    if boot[3:11] != b'NTFS    ':
        return 0
    bps = struct.unpack_from('<H', boot, 11)[0]
    cs = bps * boot[13]
    lcn = struct.unpack_from('<Q', boot, 48)[0]
    cpr = struct.unpack_from('<b', boot, 64)[0]
    rs = (1 << -cpr) if cpr < 0 else cpr * cs
    if rs not in (1024, 2048, 4096):
        return 0
    data = raid.read_at(start + lcn * cs, max_records * rs)
    total = good = 0
    for k in range(0, len(data) - rs + 1, rs):
        rec = data[k:k + rs]
        if rec[:4] == b'FILE':
            total += 1
            if ntfs.parse_record(rec, rs, want_data=False) is not None:
                good += 1
        elif rec.count(0) == rs:
            continue                    # enregistrement jamais utilisé (zéros) : neutre
        else:
            total += 1                  # contenu étranger à l'endroit d'un enregistrement : mauvais signe
    return int(400 * good / total) if total else 0


def _score(raid: VirtualRaid, deep: bool = False) -> int:
    """Vraisemblance de la reconstruction : signatures de système de fichiers / table de partitions au début du volume."""
    from . import partitions
    score = 0
    try:
        head = raid.read_at(0, 4096)
        if len(head) < 1024:
            return 0
        info = partitions.probe_fs(raid, 0)
        if info.get('fs'):
            score += 200
            if deep and info['fs'] == 'ntfs':
                score += 300 if _ntfs_mft_ok(raid, 0) else 0
                score += 300 if _ntfs_backup_ok(raid, 0) else 0
                score += _mft_coherence(raid, 0)
        if head[510:512] == b'\x55\xaa':
            score += 20
        gpt = raid.read_at(raid.sector_size, 512)
        if gpt[:8] == b'EFI PART':
            score += 100
            parts = partitions.parse_gpt(raid, 1, raid.sector_size)
            for g in parts[:6]:
                st = g['first'] * raid.sector_size
                if st + 4096 < (raid.size or 0) and partitions.probe_fs(raid, st).get('fs'):
                    score += 150
                    if deep and _ntfs_mft_ok(raid, st):
                        score += 300
                    if deep and _ntfs_backup_ok(raid, st, g['last'] * raid.sector_size - st + raid.sector_size):
                        score += 300
                    if deep:
                        score += _mft_coherence(raid, st)
        elif head[510:512] == b'\x55\xaa':
            for m in partitions.parse_mbr(head)[:4]:
                st = m['lba'] * raid.sector_size
                if st and st + 4096 < (raid.size or 0) and partitions.probe_fs(raid, st).get('fs'):
                    score += 150
                    if deep and _ntfs_mft_ok(raid, st):
                        score += 300
                    if deep and _ntfs_backup_ok(raid, st, m['sectors'] * raid.sector_size):
                        score += 300
                    if deep:
                        score += _mft_coherence(raid, st)
    except Exception:
        return 0
    return score


def detect(members: list, cache_mb: int = 16) -> List[Dict]:
    """Teste niveaux/tailles de bande/ordres/dispositions ; retourne les meilleurs candidats (score décroissant)."""
    cached = []
    for m in members:
        if m is None:
            cached.append(None)
            continue
        cached.append(MemReader(m.read_at(0, cache_mb * 1024 * 1024), m.size))
    n = len(members)
    present = [i for i, m in enumerate(cached) if m is not None]
    cands: List[Dict] = []
    stripes = [4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576]
    offsets = [0, 1024 * 1024]
    levels = ['span'] + (['raid0'] if len(present) == n else []) + (['raid5'] if n >= 3 else []) + (['raid10'] if n >= 4 and n % 2 == 0 else [])
    orders = list(itertools.permutations(range(n))) if n <= 5 else [tuple(range(n))]
    for lv in levels:
        for order in orders:
            if lv == 'span' and order != tuple(range(n)) and n > 2:
                continue
            for off in offsets:
                for stripe in ([65536] if lv == 'span' else stripes):
                    for layout in (LAYOUTS if lv == 'raid5' else ('ls',)):
                        try:
                            r = VirtualRaid(cached, lv, stripe, layout, list(order), off)
                        except DeviceError:
                            continue
                        sc = _score(r)
                        if sc >= 100:
                            cands.append({'level': lv, 'stripe': stripe, 'layout': layout, 'order': list(order),
                                          'offset': off, 'score': sc})
    cands.sort(key=lambda c: -c['score'])
    # 2e étage : les meilleurs candidats sont re-notés sur les VRAIS disques (l'en-tête MFT NTFS, très éloigné du début,
    # départage tailles de bande, ordre et parité que le début du volume ne distingue pas)
    top = cands[:800]
    for c in top:
        try:
            r = VirtualRaid(members, c['level'], c['stripe'], c['layout'], c['order'], c['offset'])
            c['score'] = _score(r, deep=True)
        except DeviceError:
            c['score'] = 0
    top.sort(key=lambda c: -c['score'])
    return top[:40]

"""Détection des systèmes de fichiers, tables de partitions MBR/GPT et partitions perdues."""
from __future__ import annotations

import struct
import uuid
from typing import Callable, Dict, List, Optional

from .devio import Reader, iter_blocks

GPT_TYPES = {
    'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7': 'Microsoft Basic Data',
    'c12a7328-f81f-11d2-ba4b-00a0c93ec93b': 'EFI System',
    'e3c9e316-0b5c-4db8-817d-f92df00215ae': 'Microsoft Reserved',
    'de94bba4-06d1-4d40-a16a-bfd50179d6ac': 'Windows Recovery',
    '0fc63daf-8483-4772-8e79-3d69d8477de4': 'Linux filesystem',
    '48465300-0000-11aa-aa11-00306543ecc9': 'Apple HFS+',
    '7c3457ef-0000-11aa-aa11-00306543ecc9': 'Apple APFS',
}
MBR_TYPES = {
    0x01: 'FAT12', 0x04: 'FAT16', 0x06: 'FAT16', 0x07: 'NTFS/exFAT', 0x0B: 'FAT32', 0x0C: 'FAT32 LBA',
    0x0E: 'FAT16 LBA', 0x17: 'NTFS caché', 0x27: 'Windows RE', 0x82: 'Linux swap', 0x83: 'Linux',
    0xAF: 'Apple HFS', 0xEE: 'GPT protecteur', 0xEF: 'EFI', 0xA5: 'FreeBSD', 0xFD: 'Linux RAID',
}


def probe_fs(reader: Reader, offset: int) -> Dict:
    """Identifie le système de fichiers au décalage donné. Retourne {'fs': nom, ...} ou {'fs': None}."""
    head = reader.read_at(offset, 4096)
    if len(head) < 512:
        return {'fs': None}
    boot = head[:512]
    sig_ok = boot[510:512] == b'\x55\xaa'
    if boot[3:11] == b'NTFS    ':
        bps = struct.unpack_from('<H', boot, 11)[0]
        spc = boot[13]
        if bps in (512, 1024, 2048, 4096) and spc and (spc & (spc - 1)) == 0:
            total = struct.unpack_from('<Q', boot, 40)[0]
            return {'fs': 'ntfs', 'size': total * bps, 'bps': bps, 'valid': sig_ok}
    if boot[3:11] == b'EXFAT   ':
        shift = boot[108]
        total = struct.unpack_from('<Q', boot, 72)[0]
        if 9 <= shift <= 12:
            return {'fs': 'exfat', 'size': total << shift, 'bps': 1 << shift, 'valid': sig_ok}
    if boot[3:11] == b'-FVE-FS-' or boot[160:168] == b'-FVE-FS-':
        return {'fs': 'bitlocker', 'encrypted': True}
    if boot[3:7] == b'ReFS':
        return {'fs': 'refs'}
    if boot[82:90] == b'FAT32   ' or boot[54:62] in (b'FAT16   ', b'FAT12   ', b'FAT     '):
        info = parse_fat_bpb(boot)
        if info:
            return {'fs': 'fat', 'variant': info['variant'], 'size': info['total_sectors'] * info['bps'],
                    'bps': info['bps'], 'valid': sig_ok}
    if sig_ok and boot[0] in (0xEB, 0xE9):
        info = parse_fat_bpb(boot)
        if info:
            return {'fs': 'fat', 'variant': info['variant'], 'size': info['total_sectors'] * info['bps'],
                    'bps': info['bps'], 'valid': True}
    if len(head) >= 2048:
        if struct.unpack_from('<H', head, 1024 + 56)[0] == 0xEF53:
            sb = head[1024:2048]
            bs = 1024 << struct.unpack_from('<I', sb, 24)[0]
            blocks = struct.unpack_from('<I', sb, 4)[0]
            incompat = struct.unpack_from('<I', sb, 96)[0]
            if incompat & 0x80 and len(sb) >= 0x154:
                blocks |= struct.unpack_from('<I', sb, 0x150)[0] << 32
            return {'fs': 'ext', 'size': blocks * bs, 'block_size': bs}
        if head[1024:1026] in (b'H+', b'HX'):
            return {'fs': 'hfs'}
    if head[32:36] == b'NXSB':
        bs = struct.unpack_from('<I', head, 36)[0]
        blocks = struct.unpack_from('<Q', head, 40)[0]
        return {'fs': 'apfs', 'size': bs * blocks, 'block_size': bs}
    return {'fs': None}


def parse_fat_bpb(b: bytes) -> Optional[Dict]:
    if len(b) < 90:
        return None
    bps = struct.unpack_from('<H', b, 11)[0]
    spc = b[13]
    reserved = struct.unpack_from('<H', b, 14)[0]
    nfats = b[16]
    root_entries = struct.unpack_from('<H', b, 17)[0]
    total16 = struct.unpack_from('<H', b, 19)[0]
    fat16 = struct.unpack_from('<H', b, 22)[0]
    total32 = struct.unpack_from('<I', b, 32)[0]
    fat32 = struct.unpack_from('<I', b, 36)[0]
    if bps not in (512, 1024, 2048, 4096) or spc == 0 or (spc & (spc - 1)) != 0:
        return None
    if reserved == 0 or nfats == 0 or nfats > 4:
        return None
    total = total16 or total32
    fat_sz = fat16 or fat32
    if total == 0 or fat_sz == 0:
        return None
    root_sectors = (root_entries * 32 + bps - 1) // bps
    data_sectors = total - (reserved + nfats * fat_sz + root_sectors)
    if data_sectors <= 0:
        return None
    clusters = data_sectors // spc
    variant = 'fat12' if clusters < 4085 else 'fat16' if clusters < 65525 else 'fat32'
    if variant == 'fat32' and fat16 != 0:
        return None
    return {'bps': bps, 'spc': spc, 'reserved': reserved, 'nfats': nfats, 'root_entries': root_entries,
            'total_sectors': total, 'fat_sectors': fat_sz, 'clusters': clusters, 'variant': variant,
            'root_cluster': struct.unpack_from('<I', b, 44)[0] if variant == 'fat32' else 0,
            'root_sectors': root_sectors}


def _guid(raw: bytes) -> str:
    return str(uuid.UUID(bytes_le=raw))


def parse_mbr(sector: bytes) -> List[Dict]:
    out = []
    if len(sector) < 512 or sector[510:512] != b'\x55\xaa':
        return out
    for i in range(4):
        e = sector[446 + i * 16: 462 + i * 16]
        ptype = e[4]
        lba, cnt = struct.unpack_from('<II', e, 8)
        if ptype == 0 or cnt == 0:
            continue
        out.append({'type': ptype, 'lba': lba, 'sectors': cnt, 'boot': e[0] == 0x80})
    return out


def parse_gpt(reader: Reader, header_lba: int, ss: int) -> List[Dict]:
    hdr = reader.read_at(header_lba * ss, ss)
    if hdr[:8] != b'EFI PART':
        return []
    entries_lba = struct.unpack_from('<Q', hdr, 72)[0]
    n = struct.unpack_from('<I', hdr, 80)[0]
    esz = struct.unpack_from('<I', hdr, 84)[0]
    if esz < 128 or esz > 1024 or n == 0 or n > 512:
        return []
    raw = reader.read_at(entries_lba * ss, n * esz)
    out = []
    for i in range(n):
        e = raw[i * esz:(i + 1) * esz]
        if len(e) < 128 or e[:16] == b'\x00' * 16:
            continue
        first, last = struct.unpack_from('<QQ', e, 32)
        if last < first:
            continue
        name = e[56:128].decode('utf-16le', errors='ignore').split('\x00')[0]
        out.append({'type_guid': _guid(e[:16]), 'first': first, 'last': last, 'name': name})
    return out


def detect_layout(reader: Reader) -> List[Dict]:
    """Retourne la liste des partitions : {index,start,size,fs,desc,source,...}."""
    ss = reader.sector_size
    parts: List[Dict] = []
    whole = probe_fs(reader, 0)
    sector0 = reader.read_at(0, 512)

    gpt = []
    if sector0[450:451] == b'\xee' or sector0[510:512] == b'\x55\xaa':
        gpt = parse_gpt(reader, 1, ss)
        if not gpt and reader.size:
            gpt = parse_gpt(reader, reader.size // ss - 1, ss)  # table de secours en fin de disque
    mbr = parse_mbr(sector0)

    if whole['fs'] and not gpt:
        parts.append({'index': 0, 'start': 0, 'size': whole.get('size') or (reader.size or 0), 'fs': whole['fs'],
                      'variant': whole.get('variant', ''), 'desc': 'Volume complet', 'source': 'volume'})
        return parts

    if gpt:
        for i, g in enumerate(gpt):
            start = g['first'] * ss
            size = (g['last'] - g['first'] + 1) * ss
            fp = probe_fs(reader, start)
            parts.append({'index': i + 1, 'start': start, 'size': size, 'fs': fp['fs'],
                          'variant': fp.get('variant', ''), 'encrypted': bool(fp.get('encrypted')),
                          'desc': g['name'] or GPT_TYPES.get(g['type_guid'], g['type_guid']),
                          'source': 'gpt'})
        return parts

    idx = 0
    for m in mbr:
        if m['type'] in (0x05, 0x0F, 0x85):
            # partition étendue : suivre la chaîne de EBR
            ebr_lba = m['lba']
            base = m['lba']
            for _ in range(128):
                s = reader.read_at(ebr_lba * ss, 512)
                ents = parse_mbr(s)
                if not ents:
                    break
                logical = ents[0]
                start = (ebr_lba + logical['lba']) * ss
                fp = probe_fs(reader, start)
                idx += 1
                parts.append({'index': idx, 'start': start, 'size': logical['sectors'] * ss, 'fs': fp['fs'],
                              'variant': fp.get('variant', ''), 'desc': MBR_TYPES.get(logical['type'], hex(logical['type'])),
                              'source': 'mbr'})
                nxt = [e for e in ents[1:] if e['type'] in (0x05, 0x0F, 0x85)]
                if not nxt:
                    break
                ebr_lba = base + nxt[0]['lba']
            continue
        if m['type'] == 0xEE:
            continue
        start = m['lba'] * ss
        fp = probe_fs(reader, start)
        idx += 1
        parts.append({'index': idx, 'start': start, 'size': m['sectors'] * ss, 'fs': fp['fs'],
                      'variant': fp.get('variant', ''), 'encrypted': bool(fp.get('encrypted')),
                      'desc': MBR_TYPES.get(m['type'], hex(m['type'])), 'source': 'mbr'})
    if not parts and whole['fs']:
        parts.append({'index': 0, 'start': 0, 'size': whole.get('size') or (reader.size or 0), 'fs': whole['fs'],
                      'variant': whole.get('variant', ''), 'desc': 'Volume complet', 'source': 'volume'})
    return parts


def find_lost_partitions(reader: Reader, known: List[Dict], progress: Optional[Callable[[int, int], None]] = None,
                         max_hits: int = 64) -> List[Dict]:
    """Cherche en tout le disque des secteurs de démarrage NTFS/exFAT/FAT32 (partitions supprimées/formatées)
    et des superblocs ext aux positions alignées sur 1 Mio."""
    total = reader.size or 0
    ss = reader.sector_size
    known_starts = {p['start'] for p in known if p.get('fs')}
    known_ranges = [(p['start'], p['start'] + (p.get('size') or 0)) for p in known if p.get('fs') and p.get('size')]

    def inside_known(off: int) -> bool:
        return any(a < off < b for a, b in known_ranges)     # ex. secteur de démarrage de secours en fin de volume
    found: List[Dict] = []
    seen = set()
    needles = (b'NTFS    ', b'EXFAT   ', b'-FVE-FS-')
    for pos, block in iter_blocks(reader, 0, total, 8 * 1024 * 1024):
        for nd in needles:
            i = block.find(nd)
            while i != -1:
                sec_start = pos + i - 3
                if i >= 3 and sec_start % ss == 0 and sec_start not in known_starts and sec_start not in seen and not inside_known(sec_start):
                    fp = probe_fs(reader, sec_start)
                    if fp['fs'] in ('ntfs', 'exfat', 'bitlocker') and fp.get('valid', True):
                        seen.add(sec_start)
                        found.append({'index': 100 + len(found), 'start': sec_start, 'size': fp.get('size') or 0,
                                      'fs': fp['fs'], 'variant': '', 'desc': 'Partition retrouvée (signature)',
                                      'source': 'signature', 'encrypted': fp['fs'] == 'bitlocker'})
                i = block.find(nd, i + 1)
        j = block.find(b'FAT32   ')
        while j != -1:
            sec_start = pos + j - 82
            if j >= 82 and sec_start % ss == 0 and sec_start not in known_starts and sec_start not in seen and not inside_known(sec_start):
                fp = probe_fs(reader, sec_start)
                if fp['fs'] == 'fat':
                    seen.add(sec_start)
                    found.append({'index': 100 + len(found), 'start': sec_start, 'size': fp.get('size') or 0,
                                  'fs': 'fat', 'variant': fp.get('variant', ''),
                                  'desc': 'Partition retrouvée (signature)', 'source': 'signature'})
            j = block.find(b'FAT32   ', j + 1)
        for k in range(0, len(block), 1024 * 1024):
            off = pos + k
            if off in known_starts or off in seen or k + 1082 > len(block) or inside_known(off):
                continue
            if block[k + 1080:k + 1082] == b'\x53\xef':
                fp = probe_fs(reader, off)
                if fp['fs'] == 'ext':
                    seen.add(off)
                    found.append({'index': 100 + len(found), 'start': off, 'size': fp.get('size') or 0, 'fs': 'ext',
                                  'variant': '', 'desc': 'Partition retrouvée (signature)', 'source': 'signature'})
        if len(found) >= max_hits:
            break
        if progress:
            progress(pos + len(block), total)
    # Dédoublonnage : une partition NTFS de sauvegarde en fin de volume ne doit pas dupliquer
    found.sort(key=lambda p: p['start'])
    return found

"""Réparations binaires réelles de fichiers récupérés (JPEG, PNG, PDF, WAV, MP3, MP4, ZIP/OOXML)."""
from __future__ import annotations

import os
import re
import struct
import zipfile
import zlib
from typing import Callable, Dict, Optional, Tuple

from . import sizers


def repair_jpeg(data: bytes) -> Tuple[bytes, str]:
    soi = data.find(b'\xff\xd8\xff')
    if soi < 0:
        return data, "En-tête JPEG introuvable"
    out = data[soi:]
    res = sizers.jpeg(sizers.WindowIO(_Mem(out)), 0, len(out))
    notes = []
    if res and res[0] != sizers.UNKNOWN:
        if res[0] < len(out):
            out = out[:res[0]]
            notes.append('données parasites supprimées après EOI')
        return out, '; '.join(notes) or 'JPEG valide'
    out = out.rstrip(b'\x00')
    if not out.endswith(b'\xff\xd9'):
        out += b'\xff\xd9'
        notes.append('marqueur de fin EOI ajouté (image tronquée)')
    return out, '; '.join(notes) or 'JPEG réparé'


def repair_png(data: bytes) -> Tuple[bytes, str]:
    sig = b'\x89PNG\r\n\x1a\n'
    i = data.find(sig)
    if i < 0:
        return data, "Signature PNG introuvable"
    pos = i + 8
    out = bytearray(sig)
    fixed_crc = 0
    ended = False
    while pos + 12 <= len(data):
        clen = struct.unpack('>I', data[pos:pos + 4])[0]
        ctyp = data[pos + 4:pos + 8]
        if clen > len(data) or not all(65 <= c <= 122 for c in ctyp):
            break
        if pos + 12 + clen > len(data):
            if ctyp == b'IDAT':        # IDAT tronqué : on garde ce qu'il reste
                cdat = data[pos + 8:]
                clen = len(cdat)
            else:
                break
        else:
            cdat = data[pos + 8:pos + 8 + clen]
        crc = zlib.crc32(cdat, zlib.crc32(ctyp)) & 0xFFFFFFFF
        stored = struct.unpack('>I', data[pos + 8 + clen:pos + 12 + clen])[0] if pos + 12 + clen <= len(data) else -1
        if stored != crc:
            fixed_crc += 1
        out += struct.pack('>I', clen) + ctyp + cdat + struct.pack('>I', crc)
        pos += 12 + clen
        if ctyp == b'IEND':
            ended = True
            break
    if not ended:
        out += struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND') & 0xFFFFFFFF)
    notes = []
    if fixed_crc:
        notes.append(f'{fixed_crc} CRC recalculés')
    if not ended:
        notes.append('chunk IEND ajouté')
    return bytes(out), '; '.join(notes) or 'PNG valide'


def repair_pdf(data: bytes) -> Tuple[bytes, str]:
    i = data.find(b'%PDF-')
    if i < 0:
        return data, "En-tête PDF introuvable"
    body = data[i:]
    objs = {}
    for m in re.finditer(rb'(?m)^(\d+)\s+(\d+)\s+obj\b', body):
        objs[int(m.group(1))] = (m.start(), int(m.group(2)))
    if not objs:
        return body, "Aucun objet PDF trouvé"
    root = None
    for m in re.finditer(rb'(\d+)\s+\d+\s+obj\b(?:(?!endobj).){0,400}?/Type\s*/Catalog', body, re.S):
        root = int(m.group(1))
    has_trailer = b'trailer' in body and b'startxref' in body[-2048:] and body.rstrip().endswith(b'%%EOF')
    if has_trailer and root is not None:
        return body, 'Structure PDF déjà complète'
    cut = body.rfind(b'endobj')
    base = body[:cut + 6] + b'\n' if cut >= 0 else body
    objs = {k: v for k, v in objs.items() if v[0] < len(base)}
    maxn = max(objs)
    xref_pos = len(base)
    lines = [b'xref\n', b'0 %d\n' % (maxn + 1), b'0000000000 65535 f \n']
    for n in range(1, maxn + 1):
        if n in objs:
            lines.append(b'%010d %05d n \n' % (objs[n][0], objs[n][1]))
        else:
            lines.append(b'0000000000 65535 f \n')
    trailer = b'trailer\n<< /Size %d %s>>\nstartxref\n%d\n%%%%EOF\n' % (
        maxn + 1, (b'/Root %d 0 R ' % root) if root else b'', xref_pos)
    note = 'table xref reconstruite' + ('' if root else ' (catalogue /Root introuvable : lecture possible mais partielle)')
    return base + b''.join(lines) + trailer, note


def repair_wav(data: bytes) -> Tuple[bytes, str]:
    if len(data) < 44 or data[:4] != b'RIFF':
        return data, "En-tête RIFF/WAV introuvable"
    out = bytearray(data)
    struct.pack_into('<I', out, 4, len(out) - 8)
    p = 12
    fixed = False
    while p + 8 <= len(out):
        cid = bytes(out[p:p + 4])
        sz = struct.unpack_from('<I', out, p + 4)[0]
        if cid == b'data':
            real = len(out) - (p + 8)
            if sz != real:
                struct.pack_into('<I', out, p + 4, real)
                fixed = True
            break
        p += 8 + sz + (sz & 1)
    return bytes(out), 'tailles RIFF/data recalculées' if fixed else 'WAV valide'


def repair_mp3(data: bytes) -> Tuple[bytes, str]:
    out = bytearray()
    pos = 0
    if data[:3] == b'ID3' and len(data) > 10:
        sz = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
        total = sz + 10
        out += data[:total]
        pos = total
    frames = skipped = 0
    while pos + 4 <= len(data):
        fs = sizers.mp3_frame(data[pos:pos + 4])
        if fs and pos + fs <= len(data) and (pos + fs + 4 > len(data) or sizers.mp3_frame(data[pos + fs:pos + fs + 4])):
            out += data[pos:pos + fs]
            pos += fs
            frames += 1
        else:
            pos += 1
            skipped += 1
    if not frames:
        return data, "Aucune trame MP3 valide"
    return bytes(out), f'{frames} trames resynchronisées, {skipped} octets corrompus supprimés'


def repair_mp4(data: bytes) -> Tuple[bytes, str]:
    pos = 0
    out = bytearray()
    have = set()
    while pos + 8 <= len(data):
        size = struct.unpack('>I', data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        if not all(32 <= c < 127 for c in typ):
            break
        hdr = 8
        if size == 1 and pos + 16 <= len(data):
            size = struct.unpack('>Q', data[pos + 8:pos + 16])[0]
            hdr = 16
        elif size == 0:
            size = len(data) - pos
        if size < hdr:
            break
        have.add(typ)
        if pos + size > len(data):         # atome tronqué (typiquement mdat)
            remain = len(data) - pos
            if typ == b'mdat':
                out += struct.pack('>I', remain) + typ + data[pos + 8:] if hdr == 8 else data[pos:]
                pos = len(data)
            break
        out += data[pos:pos + size]
        pos += size
    if b'moov' not in have:
        return data, ("Atome « moov » absent : le fichier est une vidéo incomplète — la reconstruction nécessite une "
                      "vidéo de référence du même appareil (non disponible)")
    return bytes(out), 'structure MP4 réparée'


def repair_zip(data: bytes) -> Tuple[bytes, str]:
    lfh, cdh, eocd = b'PK\x03\x04', b'PK\x01\x02', b'PK\x05\x06'
    entries = []
    pos = 0
    while pos < len(data):
        idx = data.find(lfh, pos)
        if idx == -1 or idx + 30 > len(data):
            break
        try:
            ver, flags, comp, mtime, mdate, crc, csz, usz, fnlen, exlen = struct.unpack('<HHHHHIIIHH', data[idx + 4:idx + 30])
        except struct.error:
            pos = idx + 4
            continue
        fn_end = idx + 30 + fnlen
        ex_end = fn_end + exlen
        if fn_end > len(data) or fnlen == 0:
            pos = idx + 4
            continue
        fname = data[idx + 30:fn_end]
        ds = ex_end
        if flags & 8 and csz == 0:
            m = re.compile(b'PK\x07\x08').search(data, ds)
            while m:
                d = data[m.start():m.start() + 16]
                if len(d) == 16 and struct.unpack('<I', d[8:12])[0] == m.start() - ds:
                    crc, csz, usz = struct.unpack('<III', d[4:16])
                    break
                m = re.compile(b'PK\x07\x08').search(data, m.start() + 1)
            else:
                nxt = data.find(lfh, ds + 4)
                csz = (nxt - ds) if nxt > ds else len(data) - ds
                usz = csz
        elif csz == 0:
            nxt = data.find(lfh, ds + 4)
            csz = (nxt - ds) if nxt > ds else len(data) - ds
        fdata = data[ds:ds + csz]
        if comp == 8:                       # vérifie la décompression ; recalcule CRC/taille si possible
            try:
                d = zlib.decompressobj(-15)
                raw = d.decompress(fdata)
                crc = zlib.crc32(raw) & 0xFFFFFFFF
                usz = len(raw)
                fdata = fdata[:len(fdata) - len(d.unused_data)]
            except zlib.error:
                pos = ds + max(csz, 1)
                continue
        elif comp == 0:
            crc = zlib.crc32(fdata) & 0xFFFFFFFF
            usz = len(fdata)
        entries.append((fname, comp, mtime, mdate, crc, len(fdata), usz, fdata))
        pos = ds + len(fdata)
    if not entries:
        return data, "Aucune entrée ZIP exploitable"
    out = bytearray()
    offs = []
    for fname, comp, mt, md, crc, csz, usz, fdata in entries:
        offs.append(len(out))
        out += lfh + struct.pack('<HHHHHIIIHH', 20, 0, comp, mt, md, crc, csz, usz, len(fname), 0) + fname + fdata
    cd = len(out)
    for (fname, comp, mt, md, crc, csz, usz, _f), o in zip(entries, offs):
        out += cdh + struct.pack('<HHHHHHIIIHHHHHII', 20, 20, 0, comp, mt, md, crc, csz, usz, len(fname), 0, 0, 0, 0, 0, o) + fname
    out += eocd + struct.pack('<HHHHIIH', 0, 0, len(entries), len(entries), len(out) - cd, cd, 0)
    return bytes(out), f'répertoire central reconstruit ({len(entries)} entrées)'


class _Mem:
    sector_size = 512

    def __init__(self, d: bytes):
        self.d = d

    def read_at(self, off: int, n: int) -> bytes:
        return self.d[off:off + n]


REPAIRERS: Dict[str, Callable[[bytes], Tuple[bytes, str]]] = {
    'jpg': repair_jpeg, 'jpeg': repair_jpeg, 'png': repair_png, 'pdf': repair_pdf, 'wav': repair_wav,
    'mp3': repair_mp3, 'mp4': repair_mp4, 'mov': repair_mp4, 'm4a': repair_mp4, 'm4v': repair_mp4,
    'zip': repair_zip, 'docx': repair_zip, 'xlsx': repair_zip, 'pptx': repair_zip, 'odt': repair_zip,
    'ods': repair_zip, 'odp': repair_zip, 'jar': repair_zip, 'epub': repair_zip,
}


def repair_file(src: str, ext: str, out_path: Optional[str] = None) -> dict:
    ext = (ext or os.path.splitext(src)[1][1:]).lower()
    fn = REPAIRERS.get(ext)
    if not fn:
        return {'success': False, 'message': f"Aucun réparateur pour le format .{ext}"}
    if not os.path.isfile(src):
        return {'success': False, 'message': 'Fichier introuvable : ' + src}
    raw = open(src, 'rb').read()
    fixed, note = fn(raw)
    changed = fixed != raw
    if out_path is None:
        root, e = os.path.splitext(src)
        out_path = root + '_repare' + e
    if not changed:
        return {'success': True, 'changed': False, 'outputPath': src, 'notes': note}
    if len(fixed) < max(64, len(raw) // 4) and ext not in ('pdf',):
        return {'success': False, 'message': f'Réparation abandonnée (perte excessive de données) : {note}'}
    with open(out_path, 'wb') as f:
        f.write(fixed)
    return {'success': True, 'changed': True, 'outputPath': out_path, 'notes': note, 'before': len(raw),
            'after': len(fixed)}

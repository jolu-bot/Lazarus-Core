"""Outils d'investigation : explorateur hexadécimal, recherche de contenu sur tout le support, export d'une plage."""
from __future__ import annotations

import base64
import os
import re
from typing import Dict, List, Optional

from .common import STOP, emit
from .devio import iter_blocks, open_reader


def hex_read(device: str, offset: int, length: int = 4096) -> dict:
    length = max(1, min(int(length), 1024 * 1024))
    rd = open_reader(device)
    try:
        data = rd.read_at(max(0, int(offset)), length)
        return {'success': True, 'offset': int(offset), 'size': rd.size, 'sectorSize': rd.sector_size,
                'data_b64': base64.b64encode(data).decode('ascii'), 'length': len(data)}
    finally:
        rd.close()


def _variants(text: str, encodings: List[str]) -> List[Dict]:
    out = []
    for enc in encodings:
        try:
            if enc == 'utf16':
                b = text.encode('utf-16le')
            elif enc == 'ascii':
                b = text.encode('ascii')
            else:
                b = text.encode('utf-8')
        except UnicodeEncodeError:
            continue
        if b and not any(v['bytes'] == b for v in out):
            out.append({'enc': enc, 'bytes': b})
    return out


def search(device: str, text: str = '', hex_pattern: str = '', encodings: Optional[List[str]] = None, nocase: bool = True,
           start: int = 0, end: Optional[int] = None, max_hits: int = 2000, context: int = 96) -> dict:
    """Recherche toutes les occurrences d'un texte (UTF-8/UTF-16/ASCII) ou d'une séquence hexadécimale."""
    rd = open_reader(device)
    try:
        total = rd.size or 0
        end = end if end is not None else total
        if hex_pattern:
            try:
                variants = [{'enc': 'hex', 'bytes': bytes.fromhex(re.sub(r'\s+', '', hex_pattern))}]
            except ValueError:
                return {'success': False, 'message': 'Séquence hexadécimale invalide'}
            nocase = False
        else:
            variants = _variants(text, encodings or ['utf8', 'utf16'])
        variants = [v for v in variants if len(v['bytes']) >= 2]
        if not variants:
            return {'success': False, 'message': 'Motif trop court ou vide'}
        regexes = []
        for v in variants:
            pat = re.escape(v['bytes'])
            if nocase and v['enc'] in ('utf8', 'ascii'):
                regexes.append((v, re.compile(pat, re.IGNORECASE)))
            elif nocase and v['enc'] == 'utf16':
                # insensibilité à la casse ASCII pour UTF-16 LE : chaque lettre suivie de \x00
                alt = b''.join((b'[' + c.lower() + c.upper() + b']\x00') if c.isalpha() else re.escape(c + b'\x00')
                               for c in (bytes([x]) for x in text.encode('ascii', 'ignore')))
                regexes.append((v, re.compile(alt)) if alt else (v, re.compile(pat)))
            else:
                regexes.append((v, re.compile(pat)))
        overlap = max(len(v['bytes']) for v in variants) + 8
        hits = 0
        carry = b''
        prev_end = start
        for pos, block in iter_blocks(rd, start, end, 8 * 1024 * 1024):
            buf = carry + block
            base = pos - len(carry)
            for v, rx in regexes:
                for m in rx.finditer(buf):
                    a = base + m.start()
                    if base + m.end() <= prev_end:
                        continue                      # déjà signalé lors du bloc précédent (zone de recouvrement)
                    lo = max(0, m.start() - context)
                    snippet = buf[lo:m.end() + context]
                    emit('hit', {'offset': a, 'enc': v['enc'], 'length': len(v['bytes']),
                                 'snippet_b64': base64.b64encode(snippet).decode('ascii'),
                                 'snippet_start': base + lo})
                    hits += 1
                    if hits >= max_hits:
                        return {'success': True, 'hits': hits, 'truncated': True}
            carry = buf[-overlap:]
            prev_end = pos + len(block)
            emit('progress', {'percent': round(min(99.0, (pos + len(block) - start) * 100.0 / max(end - start, 1)), 1),
                              'finished': False, 'engine': 'search', 'filesFound': hits, 'bytesDone': pos + len(block) - start,
                              'bytesTotal': end - start, 'currentPath': f'{(pos + len(block)) // (1024 * 1024)} Mo'})
            if STOP.is_set():
                return {'success': True, 'hits': hits, 'stopped': True}
        return {'success': True, 'hits': hits}
    finally:
        rd.close()


def export_range(device: str, offset: int, length: int, dest: str) -> dict:
    length = max(1, min(int(length), 4 * 1024 * 1024 * 1024))
    rd = open_reader(device)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or '.', exist_ok=True)
        written = 0
        with open(dest, 'wb') as fh:
            while written < length:
                chunk = rd.read_at(int(offset) + written, min(4 * 1024 * 1024, length - written))
                if not chunk:
                    break
                fh.write(chunk)
                written += len(chunk)
        return {'success': written > 0, 'path': dest, 'bytes': written}
    finally:
        rd.close()


def exif_thumbnail(head: bytes) -> bytes:
    """Miniature JPEG intégrée à l'EXIF (IFD1) — quelques Ko, extraite sans lire le fichier entier."""
    import struct
    if head[:2] != b'\xff\xd8':
        return b''
    pos = 2
    while pos + 4 <= len(head):
        if head[pos] != 0xFF:
            return b''
        mk = head[pos + 1]
        if mk == 0xDA or mk == 0xD9:
            return b''
        ln = struct.unpack('>H', head[pos + 2:pos + 4])[0]
        if mk == 0xE1 and head[pos + 4:pos + 10] == b'Exif\x00\x00':
            tiff = head[pos + 10:pos + 2 + ln]
            bo = '<' if tiff[:2] == b'II' else '>' if tiff[:2] == b'MM' else None
            if not bo:
                return b''
            try:
                ifd0 = struct.unpack(bo + 'I', tiff[4:8])[0]
                n = struct.unpack(bo + 'H', tiff[ifd0:ifd0 + 2])[0]
                nxt = struct.unpack(bo + 'I', tiff[ifd0 + 2 + n * 12:ifd0 + 6 + n * 12])[0]
                if not nxt:
                    return b''
                n1 = struct.unpack(bo + 'H', tiff[nxt:nxt + 2])[0]
                off = length = 0
                for i in range(n1):
                    tag, _t, _c, val = struct.unpack(bo + 'HHII', tiff[nxt + 2 + i * 12:nxt + 14 + i * 12])
                    if tag == 0x0201:
                        off = val
                    elif tag == 0x0202:
                        length = val
                th = tiff[off:off + length]
                return th if th[:2] == b'\xff\xd8' and len(th) == length else b''
            except (struct.error, IndexError):
                return b''
        pos += 2 + ln
    return b''


def thumbnail_batch(records: list, device: str = '', max_full: int = 400 * 1024) -> list:
    """Miniatures pour une page de la galerie : EXIF si disponible, sinon image complète si elle est petite."""
    import base64 as b64
    from .recover import ReaderPool, RecordReader
    pool = ReaderPool()
    out = []
    try:
        for rec in records:
            ext = (rec.get('extension') or '').lower()
            item = {'id': rec.get('id'), 'none': True}
            try:
                reader = pool.get(device or rec.get('device') or '') if rec.get('extents') else None
                rr = RecordReader(reader, rec)
                if ext in ('jpg', 'jpeg'):
                    head = rr.read(0, 262144)
                    th = exif_thumbnail(head)
                    if th:
                        item = {'id': rec['id'], 'mime': 'image/jpeg', 'b64': b64.b64encode(th).decode('ascii'), 'exif': True}
                    elif rr.size <= max_full:
                        item = {'id': rec['id'], 'mime': 'image/jpeg', 'b64': b64.b64encode(rr.read(0, rr.size)).decode('ascii')}
                elif ext in ('png', 'gif', 'bmp', 'webp') and rr.size <= max_full:
                    mime = {'png': 'image/png', 'gif': 'image/gif', 'bmp': 'image/bmp', 'webp': 'image/webp'}[ext]
                    item = {'id': rec['id'], 'mime': mime, 'b64': b64.b64encode(rr.read(0, rr.size)).decode('ascii')}
            except Exception:
                pass
            out.append(item)
    finally:
        pool.close()
    return out

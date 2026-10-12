"""Carving par signatures avec validation structurelle (taille réelle, pas de fichiers fantômes).

Contrairement à un carving naïf, chaque candidat est validé par un parseur de format : la taille
est déterminée par la structure du fichier (JPEG/PNG/GIF/MP4/ZIP/PDF/OLE2/...). Aucun fichier n'est
écrit pendant l'analyse : on mémorise seulement (offset, taille) ; l'extraction se fait à la demande.
"""
from __future__ import annotations

import struct
from typing import Callable, Dict, List, Optional, Tuple

from . import sizers
from .common import FileSink, Progress, ST_DELETED, log, type_for_ext
from .devio import Reader, iter_blocks

MB = 1024 * 1024
GB = 1024 * MB


class Sig:
    __slots__ = ('ext', 'magic', 'offset', 'sizer', 'max_size', 'group')

    def __init__(self, ext, magic, sizer, max_size, offset=0, group=None):
        self.ext = ext
        self.magic = magic
        self.sizer = sizer
        self.max_size = max_size
        self.offset = offset
        self.group = group or ext


def _cab(io, off, cap):
    h = io.read(off, 36)
    if len(h) < 36 or h[:4] != b'MSCF':
        return None
    size = struct.unpack('<I', h[8:12])[0]
    if not (36 < size <= cap):
        return None
    tail = io.read(off + size, 16)
    # signature Authenticode (PKCS#7 DER) ajoutée après le cabinet
    if len(tail) >= 15 and tail[0] == 0x30 and tail[1] == 0x82 and tail[4:15] == bytes.fromhex('06092a864886f70d010702'):
        size += (4 + ((tail[2] << 8) | tail[3]) + 7) // 8 * 8      # la signature est complétée à un multiple de 8 octets
    return (size, 'cab')


def _pst(io, off, cap):
    h = io.read(off, 200)
    if len(h) < 200 or h[:4] != b'!BDN':
        return None
    ver = struct.unpack('<H', h[10:12])[0]
    if ver in (23, 36):
        size = struct.unpack('<Q', h[184:192])[0]
        ext = 'ost' if h[8:10] == b'SO' else 'pst'
        return (size, ext) if 1024 < size <= cap else None
    return None


def _iff_aiff(io, off, cap):
    h = io.read(off, 12)
    if len(h) < 12 or h[:4] != b'FORM' or h[8:12] not in (b'AIFF', b'AIFC'):
        return None
    size = struct.unpack('>I', h[4:8])[0] + 8
    return (size + (size & 1), 'aiff') if 12 < size <= cap else None


def _midi(io, off, cap):
    h = io.read(off, 14)
    if len(h) < 14 or h[:4] != b'MThd' or struct.unpack('>I', h[4:8])[0] != 6:
        return None
    ntr = struct.unpack('>H', h[10:12])[0]
    pos = off + 14
    for _ in range(ntr):
        t = io.read(pos, 8)
        if len(t) < 8 or t[:4] != b'MTrk':
            return None
        pos += 8 + struct.unpack('>I', t[4:8])[0]
    return (pos - off, 'mid') if pos - off <= cap else None


def _text_block(ext, begin, end):
    return sizers.footer_sizer(ext, begin, end, window=8 * MB)


def _build() -> List[Sig]:
    S = Sig
    sigs = [
        S('jpg', b'\xff\xd8\xff', sizers.jpeg, 200 * MB),
        S('png', b'\x89PNG\r\n\x1a\n', sizers.png, 300 * MB),
        S('gif', b'GIF8', sizers.gif, 200 * MB),
        S('bmp', b'BM', sizers.bmp, 400 * MB),
        S('tif', b'II*\x00', sizers.tiff, 4 * GB, group='tif'),
        S('tif', b'MM\x00*', sizers.tiff, 4 * GB, group='tif'),
        S('wav', b'RIFF', sizers.riff, 4 * GB, group='riff'),
        S('mp4', b'ftyp', sizers.isobmff, 16 * GB, offset=4, group='mp4'),
        S('mkv', b'\x1a\x45\xdf\xa3', sizers.ebml, 16 * GB),
        S('wmv', bytes.fromhex('3026b2758e66cf11a6d900aa0062ce6c'), sizers.asf, 8 * GB),
        S('ogg', b'OggS', sizers.ogg, 2 * GB),
        S('mp3', b'ID3', sizers.mp3, 500 * MB),
        S('mp3', b'\xff\xfb', sizers.mp3, 500 * MB),
        S('mp3', b'\xff\xfa', sizers.mp3, 500 * MB),
        S('mp3', b'\xff\xf3', sizers.mp3, 500 * MB),
        S('mp3', b'\xff\xf2', sizers.mp3, 500 * MB),
        S('flac', b'fLaC', sizers.flac, 2 * GB),
        S('aiff', b'FORM', _iff_aiff, 2 * GB),
        S('mid', b'MThd', _midi, 20 * MB),
        S('flv', b'FLV\x01', sizers.fixed_header('flv', b'FLV\x01'), 4 * GB),
        S('pdf', b'%PDF-', sizers.pdf, 2 * GB),
        S('zip', b'PK\x03\x04', sizers.zipf, 8 * GB),
        S('doc', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', sizers.ole2, 1 * GB),
        S('sqlite', b'SQLite format 3\x00', sizers.sqlite, 4 * GB),
        S('7z', b'7z\xbc\xaf\x27\x1c', sizers.sevenz, 16 * GB),
        S('gz', b'\x1f\x8b\x08', sizers.gzip, 1 * GB),
        S('cab', b'MSCF', _cab, 2 * GB),
        S('rar', b'Rar!\x1a\x07', sizers.fixed_header('rar', b'Rar!\x1a\x07'), 4 * GB),
        S('pst', b'!BDN', _pst, 64 * GB),
        S('exe', b'MZ', sizers.pe, 1 * GB),
        S('elf', b'\x7fELF', sizers.elf, 1 * GB),
        S('vcf', b'BEGIN:VCARD', _text_block('vcf', b'BEGIN:VCARD', b'END:VCARD'), 8 * MB),
        S('ics', b'BEGIN:VCALENDAR', _text_block('ics', b'BEGIN:VCALENDAR', b'END:VCALENDAR'), 8 * MB),
        S('vhdx', b'vhdxfile', sizers.fixed_header('vhdx', b'vhdxfile'), 64 * GB),
        S('qcow2', b'QFI\xfb\x00\x00\x00', sizers.fixed_header('qcow2', b'QFI\xfb\x00\x00\x00'), 64 * GB),
    ]
    return sigs


SIGNATURES = _build()
SUPPORTED_EXTENSIONS = sorted({s.ext for s in SIGNATURES} | {'avi', 'webp', 'mov', 'm4a', 'heic', 'avif', 'cr2', 'nef',
                                                             'arw', 'dng', 'docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp',
                                                             'xls', 'ppt', 'dll', 'jar', 'apk', 'epub', 'webm', 'ost'})


def _index(sigs: List[Sig]):
    by2: Dict[bytes, List[Sig]] = {}
    ftyp: List[Sig] = []
    for s in sigs:
        if s.offset == 4 and s.magic == b'ftyp':
            ftyp.append(s)
        elif s.offset == 0:
            by2.setdefault(s.magic[:2], []).append(s)
    return by2, ftyp




_TEXT_OK = bytes([9, 10, 13]) + bytes(range(32, 127)) + bytes(range(128, 256))
_TEXT_BAD = bytes(b for b in range(256) if b not in set(_TEXT_OK))
_LETTERS = bytes(range(65, 91)) + bytes(range(97, 123))
_NOT_LETTERS = bytes(b for b in range(256) if b not in set(_LETTERS) and b != 32)


def _text_score(chunk: bytes) -> float:
    """Part (0-1) d'octets « texte » ; 0 si le bloc ne ressemble pas à du texte humain."""
    if not chunk or chunk.count(0) > len(chunk) // 8:
        return 0.0
    good = len(chunk.translate(None, _TEXT_BAD))
    letters = len(chunk.translate(None, _NOT_LETTERS))
    if letters < len(chunk) * 0.35:
        return 0.0
    return good / len(chunk)


def text_extent(io, off: int, limit: int, ss: int = 512) -> int:
    """Taille d'un fichier texte sans signature : secteurs « texte » consécutifs, coupés au dernier octet non nul."""
    pos = off
    last = off
    while pos - off < limit:
        chunk = io.read(pos, 65536)
        if not chunk:
            break
        stop = False
        for k in range(0, len(chunk), ss):
            sec = chunk[k:k + ss]
            stripped = sec.rstrip(b'\x00')
            if not stripped:
                stop = True            # secteur nul : fin du fichier
                break
            if _text_score(stripped) < 0.9 and len(stripped) > 16:
                stop = True            # contenu binaire : fin du fichier
                break
            last = pos + k + len(stripped)
            if len(stripped) < len(sec):
                stop = True            # secteur partiel : dernier secteur du fichier
                break
        if stop:
            break
        pos += len(chunk)
    return last - off


def _guess_text_ext(head: bytes, whole: bytes) -> str:
    h = head.lstrip()[:200].lower()
    if h.startswith(b'<?xml'):
        return 'xml'
    if h.startswith(b'<!doctype html') or h.startswith(b'<html'):
        return 'html'
    if h[:1] in (b'{', b'[') and len(whole) < 4 * MB:
        try:
            import json as _json
            _json.loads(whole.decode('utf-8'))
            return 'json'
        except Exception:
            pass
    lines = [ln for ln in whole[:4096].split(b'\n')[:-1] if ln.strip()]
    if len(lines) > 3 and all(ln.count(b',') >= 2 and ln.count(b',') == lines[0].count(b',') for ln in lines):
        return 'csv'
    return 'txt'


def make_custom_sig(d: dict) -> Optional[Sig]:
    """Signature définie par l'utilisateur : {ext, header (hex), footer (hex, optionnel), maxMB, offset}."""
    try:
        header = bytes.fromhex(str(d.get('header', '')).replace(' ', ''))
        footer = bytes.fromhex(str(d.get('footer', '')).replace(' ', '')) if d.get('footer') else b''
        ext = ''.join(ch for ch in str(d.get('ext', 'bin')).lower() if ch.isalnum())[:8] or 'bin'
        maxsz = int(float(d.get('maxMB', 64)) * MB)
        offset = int(d.get('offset', 0))
    except (ValueError, TypeError):
        return None
    if len(header) < 2:
        return None
    if footer:
        sizer = sizers.footer_sizer(ext, header, footer, window=maxsz)
    else:
        sizer = sizers.fixed_header(ext, header, offset)
    return Sig(ext, header, sizer, maxsz, offset=offset, group='custom')


def carve(reader: Reader, sink: FileSink, progress: Progress, start: int = 0, end: Optional[int] = None,
          groups: Optional[set] = None, min_size: int = 64, unknown_cap: int = 64 * MB,
          is_allocated: Optional[Callable[[int], bool]] = None, label: str = '', text: bool = False,
          custom: Optional[list] = None) -> int:
    """Parcourt [start,end) et émet les fichiers reconnus. Retourne le nombre de fichiers."""
    end = end if end is not None else (reader.size or 0)
    if end <= start:
        return 0
    align = max(reader.sector_size, 512)
    sigs = [s for s in SIGNATURES if not groups or s.ext in groups or s.group in groups]
    for d in custom or []:
        cs = make_custom_sig(d)
        if cs:
            sigs.append(cs)
    by2, ftyp = _index(sigs)
    io = sizers.WindowIO(reader)
    progress.total = end - start
    n = 0
    skip_until = start
    max_head = 64
    first = max(0, start)
    def text_attempt(i: int, abs_off: int, block: bytes):
        """Fichier texte sans signature démarrant au secteur courant (appelé quand aucune signature ne correspond)."""
        nonlocal n, skip_until
        if _text_score(block[i:i + 512]) < 0.97 or abs_off in sink.starts:
            return
        if is_allocated is not None and is_allocated(abs_off):
            return
        size = text_extent(io, abs_off, min(unknown_cap, 16 * MB), align)
        if size < 128:
            return
        whole = io.read(abs_off, size) if size <= (1 << 19) else block[i:i + 4096]
        ext = _guess_text_ext(block[i:i + 512], whole)
        name = f'f{abs_off // 512}.{ext}'
        rec = {'name': name, 'dir': 'Carved\\' + ext, 'path': 'Carved\\' + ext + '\\' + name,
               'size': int(size), 'status': ST_DELETED, 'confidence': 0.35, 'source': 'carve',
               'extents': [[abs_off, int(size)]], 'extension': ext, 'type': type_for_ext(ext),
               'volume': label, 'deleted': True, 'fragments': 1, 'size_known': False, 'text_heuristic': True}
        if sink.add(rec) is not None:
            n += 1
        skip_until = abs_off + (-(-size // align)) * align

    for pos, block in iter_blocks(reader, first, end, 8 * MB):
        blen = len(block)
        base_pad = (-pos) % align       # blocs alignés : base_pad = 0 en pratique
        for i in range(base_pad, blen, align):
            abs_off = pos + i
            if abs_off < skip_until:
                continue
            cands = by2.get(block[i:i + 2])
            if cands is None:
                if block[i + 4:i + 8] == b'ftyp':
                    cands = ftyp
                else:
                    if text:
                        text_attempt(i, abs_off, block)
                    continue
            head = block[i:i + max_head] if i + max_head <= blen else reader.read_at(abs_off, max_head)
            for s in cands:
                m = s.magic
                if s.offset:
                    if head[s.offset:s.offset + len(m)] != m:
                        continue
                elif head[:len(m)] != m:
                    continue
                if is_allocated is not None and is_allocated(abs_off):
                    continue
                if abs_off in sink.starts:
                    break
                try:
                    res = s.sizer(io, abs_off, min(s.max_size, end - abs_off))
                except Exception as e:  # validateur défaillant sur données corrompues
                    log(f'carve: {s.ext}@{abs_off}: {e}')
                    res = None
                if res is None:
                    continue
                size, ext = res
                known = size != sizers.UNKNOWN
                if not known:
                    size = min(unknown_cap, s.max_size, end - abs_off)
                if size < (min_size if known else 512):
                    continue
                name = f'f{abs_off // 512}.{ext}'
                rec = {
                    'name': name, 'dir': 'Carved\\' + ext, 'path': 'Carved\\' + ext + '\\' + name, 'size': int(size),
                    'status': ST_DELETED, 'confidence': 0.92 if known else 0.4, 'source': 'carve',
                    'extents': [[abs_off, int(size)]], 'extension': ext, 'type': type_for_ext(ext),
                    'volume': label, 'deleted': True, 'fragments': 1, 'size_known': known,
                }
                if sink.add(rec) is not None:
                    n += 1
                if known:
                    skip_until = abs_off + (-(-size // align)) * align
                break
            else:
                if text:
                    text_attempt(i, abs_off, block)
        progress.update(pos + blen - start, f'Carving : {(pos + blen) // MB} Mo / {end // MB} Mo',
                        carved=n, offset=pos + blen)
    progress.update(end - start, force=True, carved=n)
    return n

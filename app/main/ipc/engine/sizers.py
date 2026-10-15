"""Validateurs structurels : déterminent la taille réelle d'un fichier à partir de son contenu.

Chaque fonction reçoit (io, off, cap) où ``io.read(off, n)`` lit des octets absolus, et retourne
  * (taille, extension)           — taille déterminée et validée ;
  * (UNKNOWN, extension)          — en-tête valide mais fin indéterminée ;
  * None                          — faux positif.
"""
from __future__ import annotations

import re
import struct
import zlib
from typing import Optional, Tuple

UNKNOWN = -1
Result = Optional[Tuple[int, str]]


class WindowIO:
    """Lecture avec fenêtre de cache : les validateurs font beaucoup de petites lectures."""

    def __init__(self, reader, window: int = 1024 * 1024):
        self.r = reader
        self.window = window
        self._start = -1
        self._data = b''

    def read(self, off: int, n: int) -> bytes:
        if n <= 0 or off < 0:
            return b''
        if n > self.window // 2:
            return self.r.read_at(off, n)
        if self._start <= off and off + n <= self._start + len(self._data):
            rel = off - self._start
            return self._data[rel:rel + n]
        ss = max(self.r.sector_size, 512)
        s = off - (off % ss)
        self._data = self.r.read_at(s, self.window)
        self._start = s
        rel = off - s
        return self._data[rel:rel + n]


# ---------------------------------------------------------------- images
_JPEG_MARK = re.compile(rb'\xff[\x01-\xcf\xd8-\xfe]')


def jpeg(io, off, cap) -> Result:
    h = io.read(off, 4)
    if len(h) < 4 or h[:2] != b'\xff\xd8' or h[2] != 0xFF or h[3] in (0x00, 0xFF, 0xD8):
        return None
    pos = off + 2
    sos_seen = False
    segs = 0
    while segs < 4000 and pos - off < cap:
        m = io.read(pos, 4)
        if len(m) < 2 or m[0] != 0xFF:
            return (UNKNOWN, 'jpg') if sos_seen else None
        mk = m[1]
        if mk == 0xD9:
            return (pos + 2 - off, 'jpg') if sos_seen else None
        if mk == 0xFF:
            pos += 1
            continue
        if mk in (0xD8, 0x01) or 0xD0 <= mk <= 0xD7:
            pos += 2
            continue
        if len(m) < 4:
            return None
        ln = (m[2] << 8) | m[3]
        if ln < 2:
            return None
        segs += 1
        if mk == 0xDA:
            sos_seen = True
            pos += 2 + ln
            while pos - off < cap:
                chunk = io.read(pos, 65536)
                if len(chunk) < 2:                 # fin des données (évite une boucle infinie sur un dernier octet isolé)
                    return (UNKNOWN, 'jpg')
                mm = _JPEG_MARK.search(chunk)
                if mm:
                    pos += mm.start()
                    break
                pos += len(chunk) - 1
            else:
                return (UNKNOWN, 'jpg')
            continue
        pos += 2 + ln
    return (UNKNOWN, 'jpg') if sos_seen else None


def png(io, off, cap) -> Result:
    h = io.read(off, 33)
    if len(h) < 33 or h[:8] != b'\x89PNG\r\n\x1a\n' or h[12:16] != b'IHDR' or struct.unpack('>I', h[8:12])[0] != 13:
        return None
    pos = off + 8
    for _ in range(100000):
        c = io.read(pos, 8)
        if len(c) < 8:
            return (UNKNOWN, 'png')
        ln = struct.unpack('>I', c[:4])[0]
        t = c[4:8]
        if ln > 0x7FFFFFFF or not all(65 <= b <= 122 for b in t):
            return (UNKNOWN, 'png')
        pos += 12 + ln
        if t == b'IEND':
            return (pos - off, 'png')
        if pos - off > cap:
            break
    return (UNKNOWN, 'png')


def gif(io, off, cap) -> Result:
    h = io.read(off, 13)
    if len(h) < 13 or h[:3] != b'GIF' or h[3:6] not in (b'87a', b'89a'):
        return None
    w, hgt = struct.unpack('<HH', h[6:10])
    if w == 0 or hgt == 0:
        return None
    pos = off + 13
    if h[10] & 0x80:
        pos += 3 * (1 << ((h[10] & 7) + 1))
    for _ in range(200000):
        b = io.read(pos, 1)
        if not b:
            return (UNKNOWN, 'gif')
        if b[0] == 0x3B:
            return (pos + 1 - off, 'gif')
        if b[0] == 0x21:
            pos += 2
        elif b[0] == 0x2C:
            d = io.read(pos, 10)
            if len(d) < 10:
                return (UNKNOWN, 'gif')
            pos += 10
            if d[9] & 0x80:
                pos += 3 * (1 << ((d[9] & 7) + 1))
            pos += 1
        else:
            return (UNKNOWN, 'gif')
        while True:
            s = io.read(pos, 1)
            if not s:
                return (UNKNOWN, 'gif')
            pos += 1
            if s[0] == 0:
                break
            pos += s[0]
        if pos - off > cap:
            break
    return (UNKNOWN, 'gif')


def bmp(io, off, cap) -> Result:
    h = io.read(off, 30)
    if len(h) < 30 or h[:2] != b'BM':
        return None
    size, r1, r2, data_off, dib = struct.unpack('<IHHII', h[2:18])
    if r1 or r2 or dib not in (12, 40, 52, 56, 64, 108, 124) or not (54 <= size <= cap) or data_off >= size:
        return None
    if dib >= 40:
        w, hg = struct.unpack('<ii', h[18:26])
        if w == 0 or hg == 0 or abs(w) > 100000 or abs(hg) > 100000:
            return None
    return (size, 'bmp')


def riff(io, off, cap) -> Result:
    h = io.read(off, 12)
    if len(h) < 12 or h[:4] != b'RIFF':
        return None
    form = h[8:12]
    ext = {b'WAVE': 'wav', b'AVI ': 'avi', b'WEBP': 'webp', b'ACON': 'ani', b'CDRX': 'cdr'}.get(form)
    if not ext:
        return None
    size = struct.unpack('<I', h[4:8])[0] + 8
    if size < 44 or size > cap:
        return (UNKNOWN, ext) if ext == 'avi' else None
    return (size + (size & 1), ext)


def _tiff_ifd(io, off, bo, ifd_off, depth=0):
    """Retourne (fin max en octets relatif, make, flags)."""
    end = 0
    make = b''
    dng = False
    seen = set()
    nxt = ifd_off
    while nxt and nxt not in seen and len(seen) < 8:
        seen.add(nxt)
        n = io.read(off + nxt, 2)
        if len(n) < 2:
            break
        cnt = struct.unpack(bo + 'H', n)[0]
        if cnt == 0 or cnt > 2000:
            break
        raw = io.read(off + nxt + 2, cnt * 12 + 4)
        if len(raw) < cnt * 12 + 4:
            break
        end = max(end, nxt + 2 + cnt * 12 + 4)
        tags = {}
        for i in range(cnt):
            tag, typ, count, val = struct.unpack(bo + 'HHII', raw[i * 12:i * 12 + 12])
            tags[tag] = (typ, count, val, raw[i * 12 + 8:i * 12 + 12])
        sz = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
        for _tag, (typ_, count_, val_, _inl) in tags.items():       # profils ICC, XMP, chaînes… hors ligne
            span = count_ * sz.get(typ_, 1)
            if span > 4 and val_ < (1 << 31):
                end = max(end, val_ + span)

        def values(tag):
            typ, count, val, inline = tags[tag]
            tsz = sz.get(typ, 1)
            if count * tsz <= 4:
                data = inline[:count * tsz]
            else:
                data = io.read(off + val, min(count * tsz, 1 << 20))
                end_local = val + count * tsz
                nonlocal_end[0] = max(nonlocal_end[0], end_local)
            fmt = {1: 'B', 2: 'B', 3: 'H', 4: 'I', 7: 'B', 8: 'h', 9: 'i', 16: 'Q'}.get(typ)
            if not fmt:
                return []
            k = struct.calcsize(fmt)
            return list(struct.unpack(bo + fmt * (len(data) // k), data[:len(data) // k * k]))

        nonlocal_end = [0]
        for off_tag, cnt_tag in ((273, 279), (324, 325)):
            if off_tag in tags and cnt_tag in tags:
                try:
                    offs, cnts = values(off_tag), values(cnt_tag)
                    for a, b in zip(offs, cnts):
                        end = max(end, a + b)
                except Exception:
                    pass
        if 513 in tags and 514 in tags:
            try:
                end = max(end, values(513)[0] + values(514)[0])
            except Exception:
                pass
        if 271 in tags and not make:
            try:
                typ, count, val, inline = tags[271]
                make = (inline[:count] if count <= 4 else io.read(off + val, min(count, 64))).split(b'\x00')[0]
            except Exception:
                pass
        if 50706 in tags:
            dng = True
        end = max(end, nonlocal_end[0])
        if 330 in tags and depth == 0:
            try:
                for sub in values(330)[:4]:
                    e2, _m, _d = _tiff_ifd(io, off, bo, sub, 1)
                    end = max(end, e2)
            except Exception:
                pass
        n2 = io.read(off + nxt + 2 + cnt * 12, 4)
        nxt = struct.unpack(bo + 'I', n2)[0] if len(n2) == 4 else 0
    return end, make, dng


def tiff(io, off, cap) -> Result:
    h = io.read(off, 16)
    if len(h) < 16:
        return None
    if h[:4] == b'II*\x00':
        bo = '<'
    elif h[:4] == b'MM\x00*':
        bo = '>'
    else:
        return None
    ifd0 = struct.unpack(bo + 'I', h[4:8])[0]
    if ifd0 < 8 or ifd0 > 1 << 24:
        return None
    end, make, dng = _tiff_ifd(io, off, bo, ifd0)
    if h[8:10] == b'CR':
        ext = 'cr2'
    elif dng:
        ext = 'dng'
    else:
        m = make.upper()
        ext = ('nef' if b'NIKON' in m else 'arw' if b'SONY' in m else 'cr2' if b'CANON' in m else
               'orf' if b'OLYMPUS' in m else 'pef' if b'PENTAX' in m else 'rw2' if b'PANASONIC' in m else 'tif')
    if end <= 0 or end > cap:
        return None
    return (end, ext)


# ---------------------------------------------------------------- vidéo / conteneurs
_BRANDS = {b'qt  ': 'mov', b'M4A ': 'm4a', b'M4B ': 'm4a', b'M4V ': 'm4v', b'heic': 'heic', b'heix': 'heic',
           b'mif1': 'heic', b'msf1': 'heic', b'avif': 'avif', b'crx ': 'cr3', b'3gp4': '3gp', b'3gp5': '3gp',
           b'3gp6': '3gp', b'3g2a': '3g2', b'f4v ': 'f4v'}


def isobmff(io, off, cap) -> Result:
    h = io.read(off, 16)
    if len(h) < 16 or h[4:8] != b'ftyp':
        return None
    size0 = struct.unpack('>I', h[:4])[0]
    if size0 < 16 or size0 > 4096:
        return None
    brand = h[8:12]
    ext = _BRANDS.get(brand) or ('3gp' if brand[:3] == b'3gp' else 'mp4')
    pos = off
    total = 0
    have = set()
    for _ in range(20000):
        a = io.read(pos, 16)
        if len(a) < 8:
            break
        sz = struct.unpack('>I', a[:4])[0]
        typ = a[4:8]
        if not all(32 <= c < 127 for c in typ):
            break
        if sz == 1 and len(a) >= 16:
            sz = struct.unpack('>Q', a[8:16])[0]
        elif sz == 0:
            break
        if sz < 8 or total + sz > cap:
            break
        have.add(typ)
        pos += sz
        total += sz
    if total == 0 or not (have & {b'moov', b'mdat'}):
        return None
    return (total, ext)


def _vint(b: bytes, i: int):
    if i >= len(b):
        return None, 0
    first = b[i]
    ln = 1
    mask = 0x80
    while ln <= 8 and not (first & mask):
        ln += 1
        mask >>= 1
    if ln > 8 or i + ln > len(b):
        return None, 0
    v = first & (mask - 1)
    allones = v == mask - 1
    for k in range(1, ln):
        v = (v << 8) | b[i + k]
        allones = allones and b[i + k] == 0xFF
    return (None if allones else v), ln


def ebml(io, off, cap) -> Result:
    h = io.read(off, 4096)
    if len(h) < 12 or h[:4] != b'\x1a\x45\xdf\xa3':
        return None
    hl, n = _vint(h, 4)
    if hl is None:
        return None
    pos = 4 + n + hl
    doc = h[4 + n:4 + n + hl]
    ext = 'webm' if b'webm' in doc else 'mkv'
    seg = io.read(off + pos, 16)
    if seg[:4] != b'\x18\x53\x80\x67':
        return None
    sl, sn = _vint(seg, 4)
    if sl is None:
        return (UNKNOWN, ext)
    total = pos + 4 + sn + sl
    return (total, ext) if total <= cap else (UNKNOWN, ext)


_ASF_HDR = bytes.fromhex('3026b2758e66cf11a6d900aa0062ce6c')
_ASF_FILEPROP = bytes.fromhex('a1dcab8c47a9cf118ee400c00c205365')


def asf(io, off, cap) -> Result:
    h = io.read(off, 30)
    if len(h) < 30 or h[:16] != _ASF_HDR:
        return None
    hsize = struct.unpack('<Q', h[16:24])[0]
    nobj = struct.unpack('<I', h[24:28])[0]
    if hsize < 30 or hsize > 1 << 24:
        return None
    body = io.read(off + 30, int(hsize) - 30)
    p = 0
    ext = 'wmv'
    for _ in range(nobj):
        if p + 24 > len(body):
            break
        guid = body[p:p + 16]
        sz = struct.unpack('<Q', body[p + 16:p + 24])[0]
        if guid == _ASF_FILEPROP and p + 48 <= len(body):
            fsz = struct.unpack('<Q', body[p + 40:p + 48])[0]
            if 0 < fsz <= cap:
                return (fsz, ext)
        if sz < 24:
            break
        p += sz
    return (UNKNOWN, ext)


def ogg(io, off, cap) -> Result:
    pos = off
    serial = None
    pages = 0
    while pos - off < cap and pages < 2000000:
        h = io.read(pos, 27)
        if len(h) < 27 or h[:4] != b'OggS':
            break
        ns = h[26]
        segs = io.read(pos + 27, ns)
        if len(segs) < ns:
            break
        s = struct.unpack('<I', h[14:18])[0]
        if serial is None:
            serial = s
        pos += 27 + ns + sum(segs)
        pages += 1
        if h[5] & 4:
            return (pos - off, 'ogg')
    return (pos - off, 'ogg') if pages > 2 else None


# ---------------------------------------------------------------- audio
_MP3_BR = {
    (3, 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 0],
    (3, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0],
    (3, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    (2, 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0],
    (2, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
    (2, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
}
_MP3_SR = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def mp3_frame(h: bytes) -> int:
    if len(h) < 4 or h[0] != 0xFF or (h[1] & 0xE0) != 0xE0:
        return 0
    ver = (h[1] >> 3) & 3
    layer = 4 - ((h[1] >> 1) & 3)
    if ver == 1 or layer == 4:
        return 0
    br_i, sr_i, pad = h[2] >> 4, (h[2] >> 2) & 3, (h[2] >> 1) & 1
    if br_i in (0, 15) or sr_i == 3:
        return 0
    key = (3 if ver == 3 else 2, layer)
    br = _MP3_BR[key][br_i] * 1000
    sr = _MP3_SR[ver][sr_i]
    if not br:
        return 0
    if layer == 1:
        return (12 * br // sr + pad) * 4
    if layer == 3 and ver != 3:
        return 72 * br // sr + pad
    return 144 * br // sr + pad


def mp3(io, off, cap) -> Result:
    h = io.read(off, 10)
    if len(h) < 10:
        return None
    pos = off
    if h[:3] == b'ID3':
        if h[3] not in (2, 3, 4) or any(b & 0x80 for b in h[6:10]):
            return None
        pos += 10 + ((h[6] << 21) | (h[7] << 14) | (h[8] << 7) | h[9]) + (10 if h[5] & 0x10 else 0)
    frames = 0
    while pos - off < cap:
        fh = io.read(pos, 4)
        fs = mp3_frame(fh)
        if not fs:
            break
        pos += fs
        frames += 1
    if frames < 5 and h[:3] != b'ID3':
        return None
    if frames < 2:
        return None
    if io.read(pos, 3) == b'TAG':
        pos += 128
    return (pos - off, 'mp3')


def flac(io, off, cap) -> Result:
    h = io.read(off, 8)
    if len(h) < 8 or h[:4] != b'fLaC' or (h[4] & 0x7F) != 0:
        return None
    return (UNKNOWN, 'flac')


# ---------------------------------------------------------------- documents / archives
def _find_eof(io, pos, limit):
    """Position (absolue) juste après le prochain « %%EOF » (+ saut de ligne), ou None."""
    start = pos
    carry = b''
    while pos - start < limit:
        chunk = io.read(pos, 1024 * 1024)
        if not chunk:
            return None
        buf = carry + chunk
        i = buf.find(b'%%EOF')
        if i != -1:
            end = pos - len(carry) + i + 5
            tail = io.read(end, 2)
            if tail[:2] == b'\r\n':
                end += 2
            elif tail[:1] in (b'\n', b'\r'):
                end += 1
            return end
        carry = buf[-4:]
        pos += len(chunk)
    return None


_PDF_UPDATE = re.compile(rb'\s*(\d+\s+\d+\s+obj|xref)')


def pdf(io, off, cap) -> Result:
    h = io.read(off, 16)
    if len(h) < 8 or h[:5] != b'%PDF-' or not (h[5:6].isdigit() and h[6:7] == b'.'):
        return None
    limit = min(cap, 1024 * 1024 * 1024)
    e = _find_eof(io, off, limit)
    if e is None:
        return (UNKNOWN, 'pdf')
    for _ in range(64):         # mises à jour incrémentales : plusieurs « %%EOF » successifs
        if not _PDF_UPDATE.match(io.read(e, 64)):
            break
        nxt = _find_eof(io, e, limit - (e - off))
        if nxt is None:
            break
        between = io.read(e, min(nxt - e, 16 * 1024 * 1024))
        if b'startxref' not in between or b'%PDF-' in between:
            break
        e = nxt
    return (e - off, 'pdf')


_OOXML = (('word/', 'docx'), ('xl/', 'xlsx'), ('ppt/', 'pptx'), ('visio/', 'vsdx'))


def zipf(io, off, cap) -> Result:
    h = io.read(off, 30)
    if len(h) < 30 or h[:4] != b'PK\x03\x04':
        return None
    pos = off
    names = []
    mimetype = b''
    for _ in range(200000):
        lh = io.read(pos, 30)
        if len(lh) < 30:
            return (UNKNOWN, 'zip')
        sig = lh[:4]
        if sig == b'PK\x01\x02' or sig == b'PK\x05\x06' or sig == b'PK\x06\x06':
            break
        if sig != b'PK\x03\x04':
            return (UNKNOWN, 'zip') if names else None
        ver, flags, comp, _t, _d, crc, csz, usz, nl, xl = struct.unpack('<HHHHHIIIHH', lh[4:30])
        if ver > 100 or nl == 0 or nl > 1024:
            return (UNKNOWN, 'zip') if names else None
        nm = io.read(pos + 30, nl)
        if len(names) < 60:
            names.append(nm)
        data_start = pos + 30 + nl + xl
        if csz == 0xFFFFFFFF:      # zip64 : taille dans l'extra
            ex = io.read(pos + 30 + nl, xl)
            k = 0
            while k + 4 <= len(ex):
                tid, tl = struct.unpack('<HH', ex[k:k + 4])
                if tid == 1 and tl >= 16:
                    usz, csz = struct.unpack('<QQ', ex[k + 4:k + 20])
                    break
                k += 4 + tl
        if flags & 8 and csz == 0:
            # descripteur de données : cherche la signature PK\x07\x08 dont la taille concorde
            p = data_start
            found = False
            while p - data_start < cap:
                chunk = io.read(p, 262144)
                if not chunk:
                    break
                i = chunk.find(b'PK\x07\x08')
                while i != -1:
                    d = chunk[i:i + 16]
                    if len(d) == 16 and struct.unpack('<I', d[8:12])[0] == (p + i - data_start):
                        csz = p + i - data_start
                        pos = p + i + 16
                        found = True
                        break
                    i = chunk.find(b'PK\x07\x08', i + 1)
                if found:
                    break
                p += len(chunk) - 3
            if not found:
                return (UNKNOWN, 'zip')
            continue
        if nm == b'mimetype' and comp == 0 and csz < 256:
            mimetype = io.read(data_start, csz)
        pos = data_start + csz
        if flags & 8:
            d = io.read(pos, 4)
            pos += 16 if d == b'PK\x07\x08' else 12
        if pos - off > cap:
            return (UNKNOWN, 'zip')
    # répertoire central
    for _ in range(300000):
        ch = io.read(pos, 46)
        if len(ch) >= 4 and ch[:4] == b'PK\x01\x02' and len(ch) == 46:
            nl, xl, cl = struct.unpack('<HHH', ch[28:34])
            pos += 46 + nl + xl + cl
            continue
        break
    sig = io.read(pos, 4)
    if sig == b'PK\x06\x06':
        sz = struct.unpack('<Q', io.read(pos + 4, 8))[0]
        pos += 12 + sz
        if io.read(pos, 4) == b'PK\x06\x07':
            pos += 20
        sig = io.read(pos, 4)
    if sig != b'PK\x05\x06':
        return (UNKNOWN, 'zip')
    eocd = io.read(pos, 22)
    if len(eocd) < 22:
        return (UNKNOWN, 'zip')
    clen = struct.unpack('<H', eocd[20:22])[0]
    total = pos + 22 + clen - off
    joined = b'\n'.join(names)
    ext = 'zip'
    if mimetype.startswith(b'application/vnd.oasis.opendocument.text'):
        ext = 'odt'
    elif mimetype.startswith(b'application/vnd.oasis.opendocument.spreadsheet'):
        ext = 'ods'
    elif mimetype.startswith(b'application/vnd.oasis.opendocument.presentation'):
        ext = 'odp'
    elif mimetype.startswith(b'application/epub'):
        ext = 'epub'
    elif b'AndroidManifest.xml' in joined:
        ext = 'apk'
    elif b'META-INF/MANIFEST.MF' in joined or b'META-INF/' in joined and b'.class' in joined:
        ext = 'jar'
    else:
        for pref, e in _OOXML:
            if pref.encode() in joined and b'[Content_Types].xml' in joined:
                ext = e
                break
    return (total, ext)


def ole2(io, off, cap) -> Result:
    h = io.read(off, 512)
    if len(h) < 512 or h[:8] != b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        return None
    shift = struct.unpack('<H', h[30:32])[0]
    if shift not in (9, 12):
        return None
    ss = 1 << shift
    nfat = struct.unpack('<I', h[44:48])[0]
    dir_start = struct.unpack('<I', h[48:52])[0]
    difat = list(struct.unpack('<109I', h[76:76 + 436]))
    if nfat == 0 or nfat > 100000:
        return None
    fat_secs = [s for s in difat if s < 0xFFFFFFFA][:nfat]
    extra_difat = struct.unpack('<I', h[68:72])[0]
    ndifat = struct.unpack('<I', h[72:76])[0]
    p = extra_difat
    for _ in range(min(ndifat, 256)):
        if p >= 0xFFFFFFFA or len(fat_secs) >= nfat:
            break
        sec = io.read(off + (p + 1) * ss, ss)
        vals = struct.unpack('<%dI' % (ss // 4), sec)
        fat_secs += [s for s in vals[:-1] if s < 0xFFFFFFFA]
        p = vals[-1]
    fat_secs = fat_secs[:nfat]
    fat = []
    for s in fat_secs:
        sec = io.read(off + (s + 1) * ss, ss)
        if len(sec) < ss:
            return None
        fat += struct.unpack('<%dI' % (ss // 4), sec)
    last = 0
    for i in range(len(fat) - 1, -1, -1):
        if fat[i] != 0xFFFFFFFF:
            last = i
            break
    size = (last + 2) * ss
    if size > cap or size < 512:
        return None
    # classification via le répertoire racine
    ext = 'doc'
    seen = set()
    sec = dir_start
    names = []
    while sec < 0xFFFFFFFA and sec not in seen and len(seen) < 64 and sec < len(fat):
        seen.add(sec)
        d = io.read(off + (sec + 1) * ss, ss)
        for i in range(0, len(d) - 127, 128):
            nl = struct.unpack('<H', d[i + 64:i + 66])[0]
            if 2 <= nl <= 64:
                names.append(d[i:i + nl - 2].decode('utf-16le', errors='ignore'))
        sec = fat[sec]
    nm = set(names)
    if 'WordDocument' in nm:
        ext = 'doc'
    elif 'Workbook' in nm or 'Book' in nm:
        ext = 'xls'
    elif 'PowerPoint Document' in nm:
        ext = 'ppt'
    elif '__properties_version1.0' in nm:
        ext = 'msg'
    elif any(n.startswith('Visio') for n in nm):
        ext = 'vsd'
    else:
        ext = 'ole'
    return (size, ext)


def sqlite(io, off, cap) -> Result:
    h = io.read(off, 100)
    if len(h) < 100 or h[:16] != b'SQLite format 3\x00':
        return None
    ps = struct.unpack('>H', h[16:18])[0]
    ps = 65536 if ps == 1 else ps
    if ps < 512 or ps > 65536 or (ps & (ps - 1)):
        return None
    pages = struct.unpack('>I', h[28:32])[0]
    chg, valid_for = struct.unpack('>I', h[24:28])[0], struct.unpack('>I', h[92:96])[0]
    if pages == 0 or chg != valid_for or ps * pages > cap:
        return (UNKNOWN, 'sqlite')
    return (ps * pages, 'sqlite')


def sevenz(io, off, cap) -> Result:
    h = io.read(off, 32)
    if len(h) < 32 or h[:6] != b'7z\xbc\xaf\x27\x1c':
        return None
    if zlib.crc32(h[12:32]) & 0xFFFFFFFF != struct.unpack('<I', h[8:12])[0]:
        return None
    noff, nsz = struct.unpack('<QQ', h[12:28])
    total = 32 + noff + nsz
    return (total, '7z') if 32 < total <= cap else (UNKNOWN, '7z')


def gzip(io, off, cap) -> Result:
    h = io.read(off, 10)
    if len(h) < 10 or h[:3] != b'\x1f\x8b\x08' or h[3] & 0xE0 or h[8] not in (0, 2, 4):
        return None
    d = zlib.decompressobj(31)
    pos = off
    out = 0
    try:
        while pos - off < min(cap, 256 * 1024 * 1024):
            chunk = io.read(pos, 262144)
            if not chunk:
                return None
            data = d.decompress(chunk, 64 * 1024 * 1024)
            out += len(data)
            if d.eof:
                return (pos - off + len(chunk) - len(d.unused_data), 'gz')
            if d.unconsumed_tail:
                return (UNKNOWN, 'gz')
            pos += len(chunk)
    except zlib.error:
        return None
    return (UNKNOWN, 'gz')


def pe(io, off, cap) -> Result:
    h = io.read(off, 64)
    if len(h) < 64 or h[:2] != b'MZ':
        return None
    lf = struct.unpack('<I', h[60:64])[0]
    if lf < 64 or lf > 4096:
        return None
    nt = io.read(off + lf, 24 + 240)
    if len(nt) < 24 or nt[:4] != b'PE\x00\x00':
        return None
    machine, nsec, _t, _p, _n, optsz, chars = struct.unpack('<HHIIIHH', nt[4:24])
    if machine not in (0x14c, 0x8664, 0x1c0, 0xaa64) or nsec == 0 or nsec > 96 or optsz < 96:
        return None
    opt = nt[24:24 + optsz]
    magic = struct.unpack('<H', opt[:2])[0]
    sub = struct.unpack('<H', opt[68:70])[0] if len(opt) >= 70 else 0
    end = 0
    secs = io.read(off + lf + 24 + optsz, nsec * 40)
    for i in range(min(nsec, len(secs) // 40)):
        raw_sz, raw_ptr = struct.unpack('<II', secs[i * 40 + 16:i * 40 + 24])
        end = max(end, raw_ptr + raw_sz)
    ddoff = 96 if magic == 0x10B else 112
    if len(opt) >= ddoff + 8 * 5:
        cert_off, cert_sz = struct.unpack('<II', opt[ddoff + 32:ddoff + 40])
        if cert_off and cert_sz:
            end = max(end, cert_off + cert_sz)
    if end < 512 or end > cap:
        return None
    ext = 'dll' if chars & 0x2000 else ('sys' if sub == 1 else 'exe')
    return (end, ext)


def elf(io, off, cap) -> Result:
    h = io.read(off, 64)
    if len(h) < 52 or h[:4] != b'\x7fELF' or h[4] not in (1, 2) or h[5] not in (1, 2):
        return None
    le = '<' if h[5] == 1 else '>'
    if h[4] == 2:
        shoff = struct.unpack(le + 'Q', h[40:48])[0]
        shentsize, shnum = struct.unpack(le + 'HH', h[58:62])
    else:
        shoff = struct.unpack(le + 'I', h[32:36])[0]
        shentsize, shnum = struct.unpack(le + 'HH', h[46:50])
    end = shoff + shentsize * shnum
    if end < 64 or end > cap:
        return (UNKNOWN, 'elf')
    return (end, 'elf')


# ---------------------------------------------------------------- footer générique
def footer_sizer(ext: str, header: bytes, footer: bytes, tail_extra: int = 0, window: int = 64 * 1024 * 1024):
    def fn(io, off, cap):
        if io.read(off, len(header)) != header:
            return None
        pos = off + len(header)
        limit = min(cap, window)
        while pos - off < limit:
            chunk = io.read(pos, 1024 * 1024)
            if not chunk:
                break
            i = chunk.find(footer)
            if i != -1:
                return (pos - off + i + len(footer) + tail_extra, ext)
            pos += max(1, len(chunk) - len(footer) + 1)
        return None
    return fn


def fixed_header(ext: str, magic: bytes, offset: int = 0):
    """Format reconnu uniquement par sa signature (taille inconnue)."""
    def fn(io, off, cap):
        return (UNKNOWN, ext) if io.read(off + offset, len(magic)) == magic else None
    return fn

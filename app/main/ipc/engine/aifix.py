"""Réparation intelligente de fichiers récupérés — intégrée au moteur (aucun serveur, aucun modèle à télécharger).

Images  : décodage partiel des JPEG/PNG tronqués, détection de la zone manquante, reconstruction par inpainting
          (TELEA + Navier-Stokes + propagation de bord), greffe des en-têtes d'un fichier de référence du même appareil
          (JPEG dont l'en-tête est détruit), amélioration optionnelle (débruitage, contraste, netteté).
Audio   : resynchronisation MP3, en-têtes WAV, interpolation des trous.
Documents : zip/OOXML/ODF (répertoire central reconstruit), PDF (xref), **récupération du texte** de documents
          irréparables (docx/xlsx/pptx/odt/pdf/doc/xls), bases SQLite partiellement corrompues (ligne par ligne).
Les dépendances lourdes (numpy, OpenCV) sont importées à la demande.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import sqlite3
import struct
import tempfile
import zipfile
import zlib
from typing import Dict, List, Optional, Tuple

from . import repair as basic
from . import sizers

MAX_BYTES = 512 * 1024 * 1024
RECONSTRUCT_MAX = 0.5       # au-delà, l'image est rognée à sa partie valide plutôt qu'inventée


def _read(path: str) -> bytes:
    with open(path, 'rb') as f:
        return f.read(MAX_BYTES)


def _write(path: str, data: bytes) -> None:
    with open(path, 'wb') as f:
        f.write(data)


def capabilities() -> Dict:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        return {'images': True, 'documents': True, 'audio': True, 'sqlite': True, 'opencv': cv2.__version__}
    except Exception as e:
        return {'images': False, 'documents': True, 'audio': True, 'sqlite': True, 'opencv': None, 'error': str(e)}


def _cv():
    import cv2
    import numpy as np
    return cv2, np


def sniff(data: bytes, ext: str = '') -> str:
    fmt = _sniff(data)
    if fmt == 'unknown' and ext in ('jpg', 'jpeg', 'jpe') and b'\xff\xda' in data[:262144]:
        return 'jpeg'                       # en-tête détruit mais données d'image présentes : greffe possible
    return fmt


def _sniff(data: bytes) -> str:
    h = data[:16]
    if h[:2] == b'\xff\xd8':
        return 'jpeg'
    if h[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if h[:3] == b'GIF':
        return 'gif'
    if h[:2] == b'BM':
        return 'bmp'
    if h[:5] == b'%PDF-':
        return 'pdf'
    if h[:4] == b'PK\x03\x04':
        names = data[:4096]
        return 'ooxml' if (b'[Content_Types]' in names or b'word/' in names or b'xl/' in names or b'ppt/' in names) else 'zip'
    if h[:4] == b'RIFF' and h[8:12] == b'WAVE':
        return 'wav'
    if h[:3] == b'ID3' or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0):
        return 'mp3'
    if h[:15] == b'SQLite format 3':
        return 'sqlite'
    if h[4:8] == b'ftyp':
        return 'mp4'
    if h[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        return 'ole'
    return 'unknown'


ALIASES = {'jpeg': {'jpg', 'jpeg', 'jpe', 'jfif'}, 'png': {'png'}, 'gif': {'gif'}, 'bmp': {'bmp', 'dib'}, 'pdf': {'pdf'},
           'wav': {'wav'}, 'mp3': {'mp3'}, 'sqlite': {'sqlite', 'sqlite3', 'db', 'db3'},
           'mp4': {'mp4', 'mov', 'm4a', 'm4v', '3gp'},
           'ooxml': {'zip', 'docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp', 'jar', 'apk', 'epub', 'vsdx'},
           'zip': {'zip', 'docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp', 'jar', 'apk', 'epub', 'vsdx'},
           'ole': {'doc', 'xls', 'ppt', 'msg', 'vsd'}}
EXT_FOR = {'jpeg': 'jpg', 'png': 'png', 'bmp': 'bmp', 'gif': 'gif', 'pdf': 'pdf', 'wav': 'wav', 'mp3': 'mp3', 'sqlite': 'sqlite',
           'mp4': 'mp4', 'zip': 'zip', 'ooxml': 'zip', 'ole': 'doc'}


# ============================================================================ analyse
def analyze(path: str) -> Dict:
    """Diagnostic d'un fichier récupéré : format, problèmes détectés, réparation possible."""
    if not os.path.isfile(path):
        return {'success': False, 'message': 'Fichier introuvable'}
    data = _read(path)
    ext = os.path.splitext(path)[1][1:].lower()
    fmt = sniff(data, ext)
    issues: List[str] = []
    repairable = True
    info: Dict = {'format': fmt, 'size': len(data)}
    try:
        if fmt == 'jpeg':
            res = sizers.jpeg(sizers.WindowIO(_Mem(data)), 0, len(data))
            if res is None:
                issues.append("Structure JPEG invalide (en-tête ou segments corrompus)")
            elif res[0] == sizers.UNKNOWN:
                issues.append('Fichier tronqué : le marqueur de fin (EOI) est absent')
            elif res[0] < len(data):
                issues.append(f'{len(data) - res[0]} octets parasites après la fin du fichier')
            img = _decode(basic.repair_jpeg(data)[0])        # décodage de la version dotée d'un EOI : sinon un JPEG tronqué est rejeté
            if img is None:
                issues.append("L'image ne peut pas être décodée")
            else:
                cv2, np = _cv()
                missing = _tail_missing_rows(img)
                info.update({'width': int(img.shape[1]), 'height': int(img.shape[0])})
                if missing:
                    issues.append(f'{round(100 * missing / img.shape[0])} % du bas de l\'image est manquant')
                    info['missingPct'] = round(100 * missing / img.shape[0], 1)
        elif fmt == 'png':
            info.update(_png_info(data))
            issues += info.pop('issues', [])
        elif fmt == 'bmp':
            issues += _bmp_issues(data)
        elif fmt in ('zip', 'ooxml'):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    bad = z.testzip()
                    if bad:
                        issues.append(f'Entrée corrompue : {bad}')
            except zipfile.BadZipFile:
                issues.append('Archive ZIP/Office endommagée (répertoire central absent ou invalide)')
        elif fmt == 'pdf':
            if b'%%EOF' not in data[-2048:]:
                issues.append('Fin de fichier PDF absente (tronqué)')
            if b'startxref' not in data[-2048:] or b'trailer' not in data:
                issues.append('Table de références (xref) absente ou invalide')
        elif fmt == 'sqlite':
            ok, msg = _sqlite_check(data)
            if not ok:
                issues.append('Base SQLite corrompue : ' + msg)
        elif fmt in ('mp3', 'wav'):
            res = basic.REPAIRERS[EXT_FOR[fmt]](data)
            if res[0] != data:
                issues.append(res[1])
        elif fmt == 'mp4':
            _fixed, note = basic.repair_mp4(data)
            if _fixed == data and 'moov' in note:
                issues.append(note)
                repairable = False
        elif fmt == 'unknown':
            issues.append("Format non reconnu : seule l'extraction de texte est possible")
    except Exception as e:     # pragma: no cover
        issues.append(f'Analyse partielle : {e}')
    known = set().union(*ALIASES.values())
    if ext in known and fmt in ALIASES and ext not in ALIASES[fmt]:
        issues.append("L'extension .%s ne correspond pas au contenu (%s)" % (ext, fmt))
    return {'success': True, 'format': fmt, 'issues': issues, 'healthy': not issues, 'repairable': repairable, 'info': info,
            'canSalvageText': fmt in ('ooxml', 'zip', 'pdf', 'ole', 'unknown')}


class _Mem:
    sector_size = 512

    def __init__(self, d: bytes):
        self.d = d

    def read_at(self, off: int, n: int) -> bytes:
        return self.d[off:off + n]


# ============================================================================ images
def _decode(data: bytes):
    cv2, np = _cv()
    try:
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None


def _tail_missing_rows(img) -> int:
    """Nombre de lignes du bas rendues en gris uniforme par un décodage JPEG interrompu."""
    cv2, np = _cv()
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h = g.shape[0]
    cnt = 0
    for y in range(h - 1, -1, -1):
        row = g[y]
        if float(row.std()) < 1.0:
            cnt += 1
        else:
            break
    if cnt < 8:
        return 0
    mean = float(g[h - 1].mean())
    # le décodeur remplit en gris (≈128) ; un aplat noir/blanc légitime au bas d'une image est possible : on exige du gris
    if not (100 <= mean <= 156) and cnt < h // 6:
        return 0
    return min(h - 1, cnt + 16)       # marge d'un MCU : la dernière rangée décodée est souvent altérée


def _inpaint_rows(img, valid_h: int):
    cv2, np = _cv()
    h = img.shape[0]
    mask = np.zeros(img.shape[:2], np.uint8)
    mask[valid_h:, :] = 255
    base = img.copy()
    base[valid_h:, :] = base[valid_h - 1:valid_h, :]            # amorce : prolongation de la dernière ligne valide
    from .inpaint import reconstruct
    return reconstruct(base, mask)


def _enhance(img):
    cv2, np = _cv()
    sigma = _noise_sigma(img)
    h = float(min(22.0, max(3.0, sigma * 0.85)))                   # force du débruitage adaptée au bruit mesuré
    den = cv2.fastNlMeansDenoisingColored(img, None, h, h, 7, 21)
    lab = cv2.cvtColor(den, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(l)
    out = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    if sigma < 10:                                                  # la netteté n'est ajoutée que sur une image peu bruitée
        blur = cv2.GaussianBlur(out, (0, 0), 1.2)
        out = cv2.addWeighted(out, 1.3, blur, -0.3, 0)
    return out


def _noise_sigma(img) -> float:
    """Écart-type du bruit (méthode d'Immerkaer)."""
    cv2, np = _cv()
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    r = cv2.filter2D(g, -1, k)[1:-1, 1:-1]
    return float(np.sqrt(np.pi / 2) * np.abs(r).sum() / (6.0 * r.size))


def _jpeg_header_transplant(damaged: bytes, reference: bytes) -> Optional[bytes]:
    """En-tête (SOI…SOS) du fichier de référence + données entropiques du fichier endommagé."""
    def sos_end(d: bytes) -> int:
        pos = 2
        while pos + 4 <= len(d):
            if d[pos] != 0xFF:
                return -1
            mk = d[pos + 1]
            ln = struct.unpack('>H', d[pos + 2:pos + 4])[0]
            if mk == 0xDA:
                return pos + 2 + ln
            pos += 2 + ln
        return -1
    ref_end = sos_end(reference)
    if ref_end < 0:
        return None
    # les données entropiques du fichier abîmé commencent après son propre SOS ; à défaut on cherche le SOS brut
    dmg_end = sos_end(damaged) if damaged[:2] == b'\xff\xd8' else -1
    candidates = []
    if dmg_end > 0:
        candidates.append(dmg_end)
    for m in re.finditer(b'\xff\xda', damaged[:262144]):
        ln = struct.unpack('>H', damaged[m.start() + 2:m.start() + 4])[0] if m.start() + 4 <= len(damaged) else 0
        candidates.append(m.start() + 2 + ln)
    for c in dict.fromkeys(candidates):
        out = reference[:ref_end] + damaged[c:]
        if not out.endswith(b'\xff\xd9'):
            out += b'\xff\xd9'
        if _decode(out) is not None:
            return out
    return None


def repair_image(data: bytes, fmt: str, reference: Optional[bytes] = None, enhance: bool = False) -> Tuple[Optional[bytes], str, List[str], Dict]:
    """Retourne (octets, extension, opérations, infos). octets=None si irréparable."""
    cv2, np = _cv()
    ops: List[str] = []
    info: Dict = {}
    if fmt == 'jpeg':
        fixed, note = basic.repair_jpeg(data)
        img = _decode(fixed)
        if img is None and reference:
            tr = _jpeg_header_transplant(data, reference)
            if tr is not None:
                fixed, img = tr, _decode(tr)
                ops.append("En-tête reconstruit à partir du fichier de référence")
        if img is None:
            return None, 'jpg', ops, {'reason': "Aucune donnée d'image décodable (essayez avec un fichier de référence du même appareil)"}
        if fixed != data and not ops:
            ops.append('Structure JPEG réparée (' + note + ')')
        missing = _tail_missing_rows(img)
        h = img.shape[0]
        if missing:
            valid = h - missing
            info['completeness'] = round(100 * valid / h, 1)
            info.update({'validRows': valid, 'height': h, 'width': int(img.shape[1])})
            if valid < 16:
                return None, 'jpg', ops, {'reason': 'Moins de 16 lignes exploitables'}
            if missing / h <= RECONSTRUCT_MAX:
                img = _inpaint_rows(img, valid)
                ops.append(f"Zone manquante reconstruite par inpainting ({round(100 * missing / h)} % de la hauteur)")
            else:
                img = img[:valid]
                ops.append(f"Image tronquée à la partie valide ({round(100 * valid / h)} %) — trop de données manquantes pour une reconstruction fiable")
        else:
            info['completeness'] = 100.0
        if enhance:
            img = _enhance(img)
            ops.append('Amélioration : débruitage, contraste, netteté')
        if not missing and not enhance:
            return fixed, 'jpg', ops or ['Fichier déjà valide'], info
        ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return buf.tobytes(), 'jpg', ops, info
    if fmt == 'png':
        rebuilt, pops, pinfo = _png_rebuild(data)
        ops += pops
        info.update(pinfo)
        if rebuilt is None:
            return None, 'png', ops, {'reason': 'PNG illisible (données de pixels absentes)'}
        img = _decode(rebuilt)
        if img is None:
            return None, 'png', ops, {'reason': 'PNG illisible après reconstruction'}
        w, full_h = pinfo.get('width', img.shape[1]), pinfo.get('height', img.shape[0])
        if img.shape[0] < full_h:
            valid = img.shape[0]
            miss = full_h - valid
            if miss / full_h <= RECONSTRUCT_MAX and valid >= 8:
                canvas = np.zeros((full_h, img.shape[1], 3), np.uint8)
                canvas[:valid] = img
                img = _inpaint_rows(canvas, valid)
                ops.append(f'Lignes manquantes reconstruites par inpainting ({round(100 * miss / full_h)} %)')
            else:
                ops.append(f'Image tronquée à la partie valide ({round(100 * valid / full_h)} %)')
            info['completeness'] = round(100 * valid / full_h, 1)
            info.update({'validRows': valid, 'height': full_h, 'width': int(w)})
        else:
            info['completeness'] = 100.0
        if enhance:
            img = _enhance(img)
            ops.append('Amélioration : débruitage, contraste, netteté')
        if info['completeness'] == 100.0 and not enhance:
            return rebuilt, 'png', ops or ['Fichier déjà valide'], info
        ok, buf = cv2.imencode('.png', img)
        return buf.tobytes(), 'png', ops, info
    if fmt == 'bmp':
        img = _decode(data)
        if img is None:
            fixed = _bmp_pad(data)
            img = _decode(fixed)
        if img is None:
            return None, 'bmp', ops, {'reason': 'BMP illisible'}
        ops.append('Image BMP rechargée et réécrite')
        ok, buf = cv2.imencode('.png', _enhance(img) if enhance else img)
        return buf.tobytes(), 'png', ops, {'completeness': 100.0}
    img = _decode(data)
    if img is None:
        return None, 'png', ops, {'reason': 'Format image non pris en charge'}
    ok, buf = cv2.imencode('.png', _enhance(img) if enhance else img)
    return buf.tobytes(), 'png', ['Image convertie en PNG'], {'completeness': 100.0}


def _png_chunks(data: bytes):
    pos = 8
    while pos + 8 <= len(data):
        ln = struct.unpack('>I', data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        if ln > len(data):
            return
        yield typ, data[pos + 8:pos + 8 + ln], pos
        pos += 12 + ln
        if typ == b'IEND':
            return


def _png_info(data: bytes) -> Dict:
    issues: List[str] = []
    info: Dict = {}
    ihdr = None
    idat = b''
    seen_end = False
    crc_bad = 0
    pos = 8
    while pos + 8 <= len(data):
        ln = struct.unpack('>I', data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        if pos + 12 + ln > len(data):
            issues.append('Fichier PNG tronqué')
            idat += data[pos + 8:] if typ == b'IDAT' else b''
            break
        body = data[pos + 8:pos + 8 + ln]
        crc = struct.unpack('>I', data[pos + 8 + ln:pos + 12 + ln])[0]
        if zlib.crc32(typ + body) & 0xFFFFFFFF != crc:
            crc_bad += 1
        if typ == b'IHDR':
            ihdr = body
        elif typ == b'IDAT':
            idat += body
        elif typ == b'IEND':
            seen_end = True
        pos += 12 + ln
    if crc_bad:
        issues.append(f'{crc_bad} bloc(s) avec somme de contrôle (CRC) invalide')
    if not seen_end and 'Fichier PNG tronqué' not in issues:
        issues.append('Bloc de fin IEND absent')
    if ihdr and len(ihdr) >= 13:
        w, h, depth, ctype, _c, _f, interlace = struct.unpack('>IIBBBBB', ihdr[:13])
        info.update({'width': w, 'height': h})
        chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype, 3)
        rowlen = (w * chans * depth + 7) // 8
        d = zlib.decompressobj()
        try:
            raw = d.decompress(idat)
        except zlib.error:
            raw = b''
            issues.append('Flux de pixels (zlib) corrompu')
        rows = len(raw) // (rowlen + 1)
        if rows < h:
            issues.append(f'{round(100 * (h - rows) / h)} % des lignes de pixels sont manquantes')
        info['rowsOk'] = rows
    else:
        issues.append('En-tête IHDR illisible')
    info['issues'] = issues
    return info


def _png_rebuild(data: bytes) -> Tuple[Optional[bytes], List[str], Dict]:
    """Reconstruit un PNG valide à partir des lignes de pixels complètes qu'il contient."""
    ops: List[str] = []
    ihdr = None
    plte = b''
    idat = b''
    pos = 8
    ancillary = []
    while pos + 8 <= len(data):
        ln = struct.unpack('>I', data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if typ == b'IHDR':
            ihdr = body
        elif typ == b'PLTE':
            plte = body
        elif typ == b'IDAT':
            idat += body
        elif typ in (b'tRNS', b'gAMA', b'sRGB', b'pHYs', b'iCCP'):
            ancillary.append((typ, body))
        pos += 12 + ln
        if typ == b'IEND' or pos > len(data):
            break
    if not ihdr or len(ihdr) < 13 or not idat:
        return None, ops, {}
    w, h, depth, ctype, comp, flt, interlace = struct.unpack('>IIBBBBB', ihdr[:13])
    if interlace:
        # entrelacé (Adam7) : réparation simple (CRC) seulement
        fixed, _n = basic.repair_png(data)
        return fixed, ['PNG entrelacé : somme de contrôle des blocs recalculée'], {'width': w, 'height': h}
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype, 3)
    rowlen = (w * chans * depth + 7) // 8
    d = zlib.decompressobj()
    try:
        raw = d.decompress(idat)
    except zlib.error:
        raw = b''
    rows = len(raw) // (rowlen + 1)
    if rows == 0:
        return None, ops, {}
    if rows < h:
        ops.append(f'Flux de pixels interrompu : {rows} lignes sur {h} exploitables')
    nh = min(rows, h)

    def chunk(t: bytes, b: bytes) -> bytes:
        return struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b) & 0xFFFFFFFF)
    out = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, nh, depth, ctype, comp, flt, 0))
    if plte:
        out += chunk(b'PLTE', plte)
    for t, b in ancillary:
        out += chunk(t, b)
    out += chunk(b'IDAT', zlib.compress(raw[:nh * (rowlen + 1)], 6)) + chunk(b'IEND', b'')
    if nh == h:
        ops.append('Blocs PNG reconstruits (CRC, IEND)')
    return out, ops, {'width': w, 'height': h}


def _bmp_issues(data: bytes) -> List[str]:
    out: List[str] = []
    if len(data) < 54:
        return ['En-tête BMP incomplet']
    size = struct.unpack('<I', data[2:6])[0]
    off = struct.unpack('<I', data[10:14])[0]
    w, h = struct.unpack('<ii', data[18:26])
    bpp = struct.unpack('<H', data[28:30])[0]
    need = off + (((abs(w) * bpp + 31) // 32) * 4) * abs(h)
    if len(data) < need:
        out.append(f'Données de pixels incomplètes ({round(100 * len(data) / need)} %)')
    if size != len(data):
        out.append('Taille déclarée incorrecte')
    return out


def _bmp_pad(data: bytes) -> bytes:
    if len(data) < 54:
        return data
    off = struct.unpack('<I', data[10:14])[0]
    w, h = struct.unpack('<ii', data[18:26])
    bpp = struct.unpack('<H', data[28:30])[0]
    need = off + (((abs(w) * bpp + 31) // 32) * 4) * abs(h)
    out = bytearray(data[:need].ljust(need, b'\x80'))
    struct.pack_into('<I', out, 2, len(out))
    return bytes(out)


# ============================================================================ documents
def _entries(data: bytes) -> List[Tuple[str, int, bytes]]:
    """(nom, méthode, données compressées éventuellement tronquées) lus dans les en-têtes locaux ZIP."""
    out = []
    pos = 0
    while True:
        i = data.find(b'PK\x03\x04', pos)
        if i < 0 or i + 30 > len(data):
            break
        try:
            _v, flags, comp, _t, _d, _crc, csz, usz, nl, xl = struct.unpack('<HHHHHIIIHH', data[i + 4:i + 30])
        except struct.error:
            break
        name = data[i + 30:i + 30 + nl].decode('utf-8', errors='replace')
        ds = i + 30 + nl + xl
        if flags & 8 and csz == 0:
            nxt = data.find(b'PK\x03\x04', ds)
            blob = data[ds:nxt if nxt > 0 else len(data)]
        else:
            blob = data[ds:ds + csz] if csz else data[ds:data.find(b'PK\x03\x04', ds) if data.find(b'PK\x03\x04', ds) > 0 else len(data)]
        out.append((name, comp, blob))
        pos = ds + max(len(blob), 1)
    return out


def _inflate_partial(blob: bytes, method: int) -> bytes:
    if method == 0:
        return blob
    d = zlib.decompressobj(-15)
    try:
        return d.decompress(blob)
    except zlib.error:
        # on récupère ce qui a pu être décompressé avant l'erreur, octet par bloc
        out = b''
        d = zlib.decompressobj(-15)
        for k in range(0, len(blob), 256):
            try:
                out += d.decompress(blob[k:k + 256])
            except zlib.error:
                break
        return out


_TAG = re.compile(r'<[^>]+>')


def _xml_text(xml: str, para: str, run: str) -> str:
    paras = re.findall(rf'<{para}[ >].*?</{para}>', xml, re.S) or [xml]
    lines = []
    for p in paras:
        parts = re.findall(rf'<{run}[^>]*>(.*?)</{run}>', p, re.S)
        t = ''.join(parts) if parts else ''
        t = (t.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&apos;', "'"))
        if t.strip():
            lines.append(t)
    return '\n'.join(lines)


def salvage_text(data: bytes, fmt: str) -> str:
    """Texte lisible extrait d'un document irréparable."""
    text = ''
    if fmt in ('zip', 'ooxml'):
        parts = []
        for name, comp, blob in _entries(data):
            low = name.lower()
            if not (low.startswith(('word/document', 'xl/sharedstrings', 'ppt/slides/slide', 'content.xml')) or low.endswith('content.xml')):
                continue
            xml = _inflate_partial(blob, comp).decode('utf-8', errors='ignore')
            if low.startswith('word/'):
                parts.append(_xml_text(xml, 'w:p', 'w:t'))
            elif low.startswith('xl/'):
                parts.append(_xml_text(xml, 'si', 't'))
            elif low.startswith('ppt/'):
                parts.append(f'--- {name} ---\n' + _xml_text(xml, 'a:p', 'a:t'))
            else:
                parts.append(_xml_text(xml, 'text:p', 'text:p') or _TAG.sub(' ', xml))
        text = '\n'.join(p for p in parts if p)
    elif fmt == 'pdf':
        chunks = []
        for m in re.finditer(rb'stream\r?\n(.*?)endstream', data, re.S):
            try:
                body = zlib.decompress(m.group(1))
            except zlib.error:
                try:
                    body = zlib.decompressobj().decompress(m.group(1))
                except zlib.error:
                    body = m.group(1)
            for t in re.findall(rb'\(((?:\\.|[^\\()])*)\)\s*(?:Tj|\'|")', body):
                chunks.append(t.decode('latin-1', errors='ignore').replace('\\(', '(').replace('\\)', ')').replace('\\\\', '\\'))
            for arr in re.findall(rb'\[(.*?)\]\s*TJ', body, re.S):
                chunks.append(''.join(x.decode('latin-1', errors='ignore') for x in re.findall(rb'\(((?:\\.|[^\\()])*)\)', arr)))
        text = '\n'.join(c for c in chunks if c.strip())
    if len(text.strip()) < 20:
        text = _strings(data)
    return text


def _strings(data: bytes, min_len: int = 8) -> str:
    """Chaînes ASCII et UTF-16 lisibles (dernier recours : .doc/.xls, fichiers inconnus)."""
    seen = set()
    out: List[str] = []
    for m in re.finditer(rb'[\x20-\x7e\xa0-\xff\r\n\t]{%d,}' % min_len, data):
        s = m.group().decode('latin-1').strip()
        if s and s not in seen and sum(c.isalpha() for c in s) > len(s) * 0.4:
            seen.add(s)
            out.append(s)
    for m in re.finditer(rb'(?:[\x20-\x7e\xa0-\xff]\x00|[\r\n\t]\x00){%d,}' % min_len, data):
        s = m.group().decode('utf-16le', errors='ignore').strip()
        if s and s not in seen and sum(c.isalpha() for c in s) > len(s) * 0.4:
            seen.add(s)
            out.append(s)
    return '\n'.join(out[:20000])


def _sqlite_check(data: bytes) -> Tuple[bool, str]:
    fd, p = tempfile.mkstemp(suffix='.db')
    os.write(fd, data)
    os.close(fd)
    try:
        c = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
        try:
            r = c.execute('pragma integrity_check').fetchone()
            return (r[0] == 'ok'), str(r[0])[:120]
        finally:
            c.close()
    except sqlite3.DatabaseError as e:
        return False, str(e)
    finally:
        try:
            os.unlink(p)
        except OSError:
            pass


def _next_readable(s, name: str, k: int):
    """Plus petit rowid > k à partir duquel la table est de nouveau lisible (pages détruites sautées) ; None = fin."""
    q = f'select rowid from "{name}" where rowid >= ? order by rowid limit 1'

    def probe(x):
        try:
            r = s.execute(q, (x,)).fetchone()
            return 'ok', (r[0] if r else None)
        except sqlite3.DatabaseError:
            return 'bad', None
    step = 1
    prev = k
    while step < (1 << 62):
        cand = k + step
        st, val = probe(cand)
        if st == 'ok':
            if val is None:
                return None
            lo, hi = prev, cand            # lo illisible (ou k), hi lisible : dichotomie sur la frontière
            while hi - lo > 1:
                mid = (lo + hi) // 2
                st2, v2 = probe(mid)
                if st2 == 'ok' and v2 is not None:
                    hi = mid
                else:
                    lo = mid
            st3, v3 = probe(hi)
            return v3 if st3 == 'ok' else None
        prev = cand
        step *= 2
    return None


def _copy_rows(s, dst, name: str, cols: int) -> Tuple[int, int]:
    ins = f'insert into "{name}" values ({",".join("?" * cols)})'
    got = skipped = 0
    k = -(1 << 62)
    batch = 200
    ok_streak = 0
    q = f'select rowid,* from "{name}" where rowid >= ? order by rowid limit ?'
    while True:
        try:
            rows = s.execute(q, (k, batch)).fetchall()
        except sqlite3.DatabaseError:
            if batch > 1:
                batch, ok_streak = 1, 0
                continue
            nxt = _next_readable(s, name, k)
            skipped += 1
            if nxt is None:
                break
            k = nxt
            continue
        if not rows:
            break
        for r in rows:
            try:
                dst.execute(ins, r[1:])
                got += 1
            except sqlite3.DatabaseError:
                pass
        k = rows[-1][0] + 1
        ok_streak += len(rows)
        if batch == 1 and ok_streak >= 64:
            batch = 200
    return got, skipped


def repair_sqlite(data: bytes, out_path: str) -> Tuple[bool, List[str]]:
    """Recopie dans une base neuve tout ce qui reste lisible : les zones détruites sont sautées, le reste est sauvé."""
    ops: List[str] = []
    fd, src = tempfile.mkstemp(suffix='.db')
    os.write(fd, data)
    os.close(fd)
    try:
        if os.path.exists(out_path):
            os.remove(out_path)
        dst = sqlite3.connect(out_path)
        try:
            s = sqlite3.connect(f'file:{src}?mode=ro', uri=True)
            try:
                try:
                    schema = s.execute("select type,name,sql from sqlite_master where sql is not null").fetchall()
                except sqlite3.DatabaseError:
                    schema = []
                recovered = holes = 0
                for typ, name, sql in schema:
                    if typ == 'table' and not name.startswith('sqlite_'):
                        try:
                            dst.execute(sql)
                        except sqlite3.DatabaseError:
                            continue
                        cols = len(dst.execute(f'pragma table_info("{name}")').fetchall())
                        try:
                            n, h = _copy_rows(s, dst, name, cols)
                        except sqlite3.DatabaseError:        # table sans rowid : lecture séquentielle
                            n, h = 0, 1
                            try:
                                cur = s.execute(f'select * from "{name}"')
                                while True:
                                    row = cur.fetchone()
                                    if row is None:
                                        break
                                    dst.execute(f'insert into "{name}" values ({",".join("?" * cols)})', row)
                                    n += 1
                            except sqlite3.DatabaseError:
                                pass
                        recovered += n
                        holes += h
                for typ, name, sql in schema:
                    if typ in ('index', 'view', 'trigger'):
                        try:
                            dst.execute(sql)
                        except sqlite3.DatabaseError:
                            pass
                dst.commit()
                ops.append(f'{recovered} ligne(s) recopiée(s) dans une base neuve'
                           + (f' ; {holes} zone(s) illisible(s) ignorée(s)' if holes else ''))
                return recovered > 0 or bool(schema), ops
            finally:
                s.close()
        finally:
            dst.close()
    finally:
        try:
            os.unlink(src)
        except OSError:
            pass


# ============================================================================ orchestration
def repair_auto(src: str, out_dir: str, reference: str = '', enhance: bool = False, mode: str = 'auto') -> Dict:
    """Détecte le format, applique la meilleure réparation et écrit le résultat. Ne modifie jamais le fichier d'origine."""
    if not os.path.isfile(src):
        return {'success': False, 'message': 'Fichier introuvable : ' + src}
    data = _read(src)
    fmt = sniff(data, os.path.splitext(src)[1][1:].lower())
    base = os.path.splitext(os.path.basename(src))[0]
    os.makedirs(out_dir, exist_ok=True)
    outputs: List[str] = []
    ops: List[str] = []
    info: Dict = {}
    notes = ''
    preview = None

    def unique(name: str) -> str:
        p = os.path.join(out_dir, name)
        root, ext = os.path.splitext(p)
        k = 1
        while os.path.exists(p):
            p = f'{root} ({k}){ext}'
            k += 1
        return p

    try:
        if fmt in ('jpeg', 'png', 'bmp', 'gif'):
            cvok = capabilities()['images']
            if not cvok:
                return {'success': False, 'message': "OpenCV est indisponible : la réparation d'image par reconstruction nécessite le moteur complet"}
            ref = _read(reference) if reference and os.path.isfile(reference) else None
            res, ext, ops, info = repair_image(data, fmt, ref, enhance)
            if res is None:
                text = ''
                return {'success': False, 'message': info.get('reason', 'Réparation impossible'), 'operations': ops, 'format': fmt}
            out = unique(f'{base}_repare.{ext}')
            _write(out, res)
            outputs.append(out)
            if len(res) < 12 * 1024 * 1024:
                import base64
                preview = base64.b64encode(res).decode('ascii')
            notes = '; '.join(ops)
        elif fmt in ('zip', 'ooxml'):
            fixed, note = basic.repair_zip(data)
            ok = False
            try:
                with zipfile.ZipFile(io.BytesIO(fixed)) as z:
                    ok = z.testzip() is None
            except zipfile.BadZipFile:
                ok = False
            ext = os.path.splitext(src)[1] or '.zip'
            if ok:
                out = unique(f'{base}_repare{ext}')
                _write(out, fixed)
                outputs.append(out)
                ops.append(note)
            text = salvage_text(data, fmt)
            if text.strip():
                t = unique(f'{base}_texte.txt')
                _write(t, text.encode('utf-8'))
                outputs.append(t)
                ops.append(f'Texte du document extrait ({len(text)} caractères)')
            notes = '; '.join(ops)
        elif fmt == 'pdf':
            fixed, note = basic.repair_pdf(data)
            out = unique(f'{base}_repare.pdf')
            _write(out, fixed)
            outputs.append(out)
            ops.append(note)
            text = salvage_text(data, 'pdf')
            if text.strip():
                t = unique(f'{base}_texte.txt')
                _write(t, text.encode('utf-8'))
                outputs.append(t)
                ops.append(f'Texte extrait ({len(text)} caractères)')
            notes = '; '.join(ops)
        elif fmt == 'sqlite':
            out = unique(f'{base}_repare.sqlite')
            ok, ops = repair_sqlite(data, out)
            if ok:
                outputs.append(out)
            notes = '; '.join(ops)
        elif fmt in ('mp3', 'wav'):
            fn = basic.REPAIRERS['mp3' if fmt == 'mp3' else 'wav']
            fixed, note = fn(data)
            out = unique(f'{base}_repare.{fmt}')
            _write(out, fixed)
            outputs.append(out)
            ops.append(note)
            notes = note
        elif fmt == 'mp4':
            fixed, note = basic.repair_mp4(data)
            if fixed != data:
                out = unique(f'{base}_repare.mp4')
                _write(out, fixed)
                outputs.append(out)
            ops.append(note)
            notes = note
        elif fmt == 'ole' or fmt == 'unknown':
            text = _strings(data)
            if text.strip():
                t = unique(f'{base}_texte.txt')
                _write(t, text.encode('utf-8'))
                outputs.append(t)
                ops.append('Contenu textuel extrait (le format binaire ne peut pas être reconstruit)')
            notes = '; '.join(ops)
        if not outputs:
            return {'success': False, 'message': notes or 'Aucune réparation possible', 'operations': ops, 'format': fmt}
        return {'success': True, 'changed': True, 'repaired': True, 'format': fmt, 'outputPath': outputs[0], 'outputs': outputs,
                'operations': ops, 'notes': notes, 'completeness': info.get('completeness'), 'preview_b64': preview,
                'previewMime': 'image/png' if outputs[0].lower().endswith('.png') else 'image/jpeg'}
    except Exception as e:
        return {'success': False, 'message': f'Erreur pendant la réparation : {e}', 'format': fmt}

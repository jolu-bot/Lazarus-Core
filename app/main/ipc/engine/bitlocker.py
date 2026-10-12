"""Déverrouillage BitLocker en lecture seule (Windows 8+ : AES-XTS 128/256) avec clé de récupération (48 chiffres),
mot de passe utilisateur, ou FVEK/VMK fournie. Les secteurs sont déchiffrés à la volée : aucune écriture, aucune copie.

Format (métadonnées FVE) : secteur de démarrage « -FVE-FS- » -> 3 blocs de métadonnées -> entrées VMK (clé protégée par la
clé de récupération via une dérivation SHA-256 itérée 2^20 fois) -> FVEK chiffrée par la VMK en AES-CCM -> secteurs AES-XTS.
Nécessite le paquet « cryptography » (inclus dans le moteur autonome).
"""
from __future__ import annotations

import hashlib
import re
import struct
import uuid
from typing import Dict, List, Optional

from .containers import VirtualReader
from .devio import DeviceError

METHODS = {0x8000: 'AES-CBC 128 + diffuseur', 0x8001: 'AES-CBC 256 + diffuseur', 0x8002: 'AES-CBC 128',
           0x8003: 'AES-CBC 256', 0x8004: 'AES-XTS 128', 0x8005: 'AES-XTS 256'}
PROTECTION = {0x0000: 'clé claire', 0x0100: 'TPM', 0x0200: 'clé de démarrage', 0x0500: 'TPM + PIN',
              0x0800: 'mot de passe de récupération', 0x2000: 'mot de passe'}


def _crypto():
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.ciphers.aead import AESCCM
        return Cipher, algorithms, modes, AESCCM
    except ImportError as e:     # pragma: no cover
        raise DeviceError("BitLocker : le paquet Python « cryptography » est requis (pip install cryptography)") from e


def recovery_password_to_key(pw: str) -> bytes:
    groups = re.findall(r'\d{6}', pw)
    if len(groups) != 8 or len(re.sub(r'\D', '', pw)) != 48:
        raise DeviceError('Clé de récupération invalide : 8 groupes de 6 chiffres attendus')
    raw = b''
    for g in groups:
        v = int(g)
        if v % 11 or v // 11 > 0xFFFF:
            raise DeviceError(f'Clé de récupération invalide (groupe {g} incorrect : faute de frappe ?)')
        raw += struct.pack('<H', v // 11)
    return hashlib.sha256(raw).digest()


def password_to_key(pw: str) -> bytes:
    return hashlib.sha256(hashlib.sha256(pw.encode('utf-16le')).digest()).digest()


def stretch(password_hash: bytes, salt: bytes) -> bytes:
    """Dérivation BitLocker : SHA-256 de (hash courant | hash du mot de passe | sel | compteur) répété 2^20 fois."""
    last = b'\x00' * 32
    sha = hashlib.sha256
    pack = struct.Struct('<Q').pack
    tail = password_hash + salt
    for i in range(0x100000):
        last = sha(last + tail + pack(i)).digest()
    return last


def parse_entries(buf: bytes, off: int = 0, end: Optional[int] = None) -> List[Dict]:
    """Entrées de métadonnées FVE : size u16, entry_type u16, value_type u16, version u16, données."""
    out = []
    end = len(buf) if end is None else end
    while off + 8 <= end:
        size, etype, vtype, ver = struct.unpack_from('<HHHH', buf, off)
        if size < 8 or off + size > len(buf):
            break
        out.append({'type': etype, 'vtype': vtype, 'ver': ver, 'data': buf[off + 8:off + size], 'off': off, 'size': size})
        off += size
    return out


def _ccm_decrypt(key: bytes, datum: bytes) -> bytes:
    """datum = nonce[12] | mac[16] | données chiffrées."""
    _, _, _, AESCCM = _crypto()
    nonce, mac, enc = datum[:12], datum[12:28], datum[28:]
    try:
        return AESCCM(key, tag_length=16).decrypt(nonce, enc + mac, None)
    except Exception as e:
        raise DeviceError('BitLocker : clé incorrecte (échec de l\'authentification)') from e


class BitLockerReader(VirtualReader):
    def __init__(self, inner, start: int = 0, size: Optional[int] = None, recovery_password: str = '', password: str = '',
                 fvek: str = '', label: str = 'bitlocker'):
        super().__init__(label)
        Cipher, algorithms, modes, _ = _crypto()
        self._Cipher, self._alg, self._modes = Cipher, algorithms, modes
        self.inner = inner
        self.start = int(start)
        boot = inner.read_at(self.start, 512)
        if boot[3:11] != b'-FVE-FS-':
            raise DeviceError('Ce volume n\'est pas chiffré par BitLocker (signature « -FVE-FS- » absente)')
        self.bps = struct.unpack_from('<H', boot, 11)[0] or 512
        self.sector_size = self.bps
        total = struct.unpack_from('<Q', boot, 40)[0] or 0
        self.size = size if size else total * self.bps
        offsets = [struct.unpack_from('<Q', boot, o)[0] for o in (0xB0, 0xB8, 0xC0)]
        meta = None
        for off in offsets:
            if not off or off > (inner.size or (1 << 62)):
                continue
            blk = inner.read_at(self.start + off, 64 * 1024)
            if blk[:8] == b'-FVE-FS-':
                meta = blk
                break
        if meta is None:
            raise DeviceError('BitLocker : métadonnées FVE introuvables (les 3 copies sont illisibles)')
        self.meta_header = meta
        hdr_size = struct.unpack_from('<H', meta, 8)[0]
        self.version = struct.unpack_from('<H', meta, 10)[0]
        self.encrypted_size = struct.unpack_from('<Q', meta, 16)[0]
        self.hdr_sectors = struct.unpack_from('<I', meta, 28)[0]
        self.hdr_backup_off = struct.unpack_from('<Q', meta, 56)[0]
        mh_off = 64
        mlen = struct.unpack_from('<I', meta, mh_off)[0]
        self.method = struct.unpack_from('<H', meta, mh_off + 36)[0]
        entries_end = min(len(meta), mh_off + mlen)
        self.entries = parse_entries(meta, mh_off + 48, entries_end)
        if self.method not in (0x8004, 0x8005):
            raise DeviceError(f'BitLocker : méthode de chiffrement non prise en charge ({METHODS.get(self.method, hex(self.method))}) '
                              f'— seuls AES-XTS 128/256 (Windows 10+) sont pris en charge')
        fvek_bytes = bytes.fromhex(fvek) if fvek else self._derive_fvek(recovery_password, password)
        klen = 32 if self.method == 0x8004 else 64
        self.key = fvek_bytes[:klen]
        if len(self.key) != klen:
            raise DeviceError('BitLocker : FVEK de longueur inattendue')
        self._zero16 = b'\x00' * 16

    # ------------------------------------------------------------------ clés
    def _vmk_candidates(self) -> List[Dict]:
        vmks = []
        for e in self.entries:
            if e['type'] == 2 and e['vtype'] == 8 and len(e['data']) > 28:
                d = e['data']
                prot = struct.unpack_from('<H', d, 26)[0]
                nested = parse_entries(d, 28)
                vmks.append({'guid': str(uuid.UUID(bytes_le=bytes(d[:16]))), 'protection': prot, 'nested': nested})
        return vmks

    def describe(self) -> Dict:
        return {'version': self.version, 'method': METHODS.get(self.method, hex(self.method)),
                'protectors': [PROTECTION.get(v['protection'], hex(v['protection'])) for v in self._vmk_candidates()],
                'encryptedSize': self.encrypted_size}

    def _derive_fvek(self, recovery_password: str, password: str) -> bytes:
        vmk = None
        errors = []
        for cand in self._vmk_candidates():
            prot = cand['protection']
            if prot == 0x0800 and recovery_password:
                ph = recovery_password_to_key(recovery_password)
            elif prot == 0x2000 and password:
                ph = password_to_key(password)
            else:
                continue
            stretch_e = next((n for n in cand['nested'] if n['vtype'] == 3), None)
            ccm_e = next((n for n in cand['nested'] if n['vtype'] == 5), None)
            if not stretch_e or not ccm_e:
                continue
            salt = stretch_e['data'][4:20]
            key = stretch(ph, salt)
            try:
                plain = _ccm_decrypt(key, ccm_e['data'])
            except DeviceError as e:
                errors.append(str(e))
                continue
            vmk = plain[12:44]
            break
        if vmk is None:
            have = ', '.join(PROTECTION.get(v['protection'], hex(v['protection'])) for v in self._vmk_candidates()) or 'aucun'
            if errors:
                raise DeviceError('BitLocker : la clé fournie est incorrecte (protecteurs présents : ' + have + ')')
            raise DeviceError('BitLocker : aucun protecteur utilisable avec ce que vous avez fourni (protecteurs présents : ' + have + ')')
        fvek_e = next((e for e in self.entries if e['type'] == 3 and e['vtype'] == 5), None)
        if not fvek_e:
            raise DeviceError('BitLocker : entrée FVEK introuvable')
        plain = _ccm_decrypt(vmk, fvek_e['data'])
        return plain[12:]

    # ------------------------------------------------------------------ déchiffrement
    def _decrypt_sector(self, data: bytes, sector_no: int) -> bytes:
        tweak = struct.pack('<Q', sector_no) + b'\x00' * 8
        c = self._Cipher(self._alg.AES(self.key), self._modes.XTS(tweak)).decryptor()
        return c.update(data) + c.finalize()

    def _logical_sector(self, s: int) -> bytes:
        """Secteur logique s déchiffré (les premiers secteurs du volume d'origine sont déplacés par BitLocker)."""
        bps = self.bps
        if s < self.hdr_sectors and self.hdr_backup_off:
            phys = self.hdr_backup_off + s * bps
            raw = self.inner.read_at(self.start + phys, bps)
            return self._decrypt_sector(raw.ljust(bps, b'\x00'), phys // bps)
        pos = s * bps
        raw = self.inner.read_at(self.start + pos, bps).ljust(bps, b'\x00')
        if self.encrypted_size and pos >= self.encrypted_size:
            return raw                                   # zone pas (encore) chiffrée
        return self._decrypt_sector(raw, pos // bps)

    def read_at(self, off: int, n: int) -> bytes:
        if n <= 0 or off < 0 or (self.size and off >= self.size):
            return b''
        if self.size:
            n = min(n, self.size - off)
        bps = self.bps
        first = off // bps
        last = (off + n - 1) // bps
        out = bytearray()
        # lecture groupée des secteurs situés après l'en-tête déplacé
        s = first
        while s <= last:
            if s < self.hdr_sectors:
                out += self._logical_sector(s)
                s += 1
                continue
            run_end = last
            raw = self.inner.read_at(self.start + s * bps, (run_end - s + 1) * bps)
            for k in range(0, len(raw) - bps + 1, bps):
                pos = (s + k // bps) * bps
                sec = raw[k:k + bps]
                out += sec if (self.encrypted_size and pos >= self.encrypted_size) else self._decrypt_sector(sec, pos // bps)
            s = run_end + 1
        rel = off - first * bps
        return bytes(out[rel:rel + n])

    def close(self):
        if hasattr(self.inner, 'close'):
            self.inner.close()


def open_from_spec(spec: dict):
    from .devio import open_reader
    inner = open_reader(spec['inner'])
    return BitLockerReader(inner, int(spec.get('start', 0)), spec.get('size'), spec.get('recoveryPassword', ''),
                           spec.get('password', ''), spec.get('fvek', ''), label='bitlocker:' + spec['inner'])


def probe(inner, start: int = 0) -> Dict:
    """Informations lisibles SANS clé : méthode de chiffrement, protecteurs présents, état de conversion."""
    boot = inner.read_at(int(start), 512)
    if boot[3:11] != b'-FVE-FS-':
        return {'bitlocker': False}
    for o in (0xB0, 0xB8, 0xC0):
        off = struct.unpack_from('<Q', boot, o)[0]
        if not off:
            continue
        meta = inner.read_at(int(start) + off, 64 * 1024)
        if meta[:8] != b'-FVE-FS-':
            continue
        mlen = struct.unpack_from('<I', meta, 64)[0]
        method = struct.unpack_from('<H', meta, 64 + 36)[0]
        entries = parse_entries(meta, 64 + 48, min(len(meta), 64 + mlen))
        prots = []
        for e in entries:
            if e['type'] == 2 and e['vtype'] == 8 and len(e['data']) > 28:
                prots.append({'guid': str(uuid.UUID(bytes_le=bytes(e['data'][:16]))),
                              'type': PROTECTION.get(struct.unpack_from('<H', e['data'], 26)[0], 'inconnu'),
                              'code': struct.unpack_from('<H', e['data'], 26)[0]})
        return {'bitlocker': True, 'method': METHODS.get(method, hex(method)), 'supported': method in (0x8004, 0x8005),
                'protectors': prots, 'version': struct.unpack_from('<H', meta, 10)[0],
                'encryptedSize': struct.unpack_from('<Q', meta, 16)[0]}
    return {'bitlocker': True, 'error': 'métadonnées illisibles'}

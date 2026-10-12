"""BitLocker (cohérence interne : volume fabriqué selon la spécification FVE ; validation sur un vrai volume Windows via
tests/tools/validate_on_real_volumes.py), recherche de contenu, explorateur hexadécimal."""
import base64
import json
import os
import struct
import sys
import tempfile
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'app', 'main', 'ipc')))

from engine import bitlocker, common, ntfs, tools  # noqa: E402
from engine.devio import Reader, open_reader  # noqa: E402
import ntfs_image  # noqa: E402
from test_misc import tmpfile  # noqa: E402
from test_ntfs import Collector, read_extents  # noqa: E402

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False


def entry(etype, vtype, data, ver=1):
    size = 8 + len(data)
    return struct.pack('<HHHH', size, etype, vtype, ver) + data


def build_bitlocker(plain: bytes, recovery: str, hdr_sectors=16):
    """Volume BitLocker XTS-AES-128 synthétique, mêmes structures que Windows 8+."""
    bps = 512
    vmk = os.urandom(32)
    fvek = os.urandom(32) + b'\x00' * 32          # 2 clés AES-128 pour XTS + remplissage
    salt = os.urandom(16)
    stretched = bitlocker.stretch(bitlocker.recovery_password_to_key(recovery), salt)

    def ccm(key, plaintext):
        nonce = os.urandom(12)
        ct = AESCCM(key, tag_length=16).encrypt(nonce, plaintext, None)
        return nonce + ct[-16:] + ct[:-16]            # nonce | mac | données

    vmk_plain = struct.pack('<HHHHI', 44, 0, 1, 1, 0x8004) + vmk
    vmk_blob = ccm(stretched, vmk_plain)
    fvek_plain = struct.pack('<HHHHI', 76, 0, 1, 1, 0x8004) + fvek
    fvek_blob = ccm(vmk, fvek_plain)
    nested = entry(0, 3, struct.pack('<I', 0x1000) + salt) + entry(0, 5, vmk_blob)
    vmk_entry = entry(2, 8, uuid.uuid4().bytes_le + b'\x00' * 8 + struct.pack('<HH', 0, 0x0800) + nested)
    fvek_entry = entry(3, 5, fvek_blob)
    entries = vmk_entry + fvek_entry
    total_sectors = len(plain) // bps
    MB = 1024 * 1024
    meta_at = (6 * MB, 6 * MB + 65536, 6 * MB + 131072)
    hdr_backup = 7 * MB
    enc = bytearray(len(plain))
    key = fvek[:32]

    def xts(sector_bytes, sno):
        c = Cipher(algorithms.AES(key), modes.XTS(struct.pack('<Q', sno) + b'\x00' * 8)).encryptor()
        return c.update(sector_bytes) + c.finalize()

    # secteurs de données chiffrés (tweak = numéro de secteur physique)
    for s in range(total_sectors):
        enc[s * bps:(s + 1) * bps] = xts(plain[s * bps:(s + 1) * bps], s)
    # l'en-tête d'origine (hdr_sectors premiers secteurs) est déplacé puis chiffré à son nouvel emplacement
    for s in range(hdr_sectors):
        phys = hdr_backup + s * bps
        enc[phys:phys + bps] = xts(plain[s * bps:(s + 1) * bps], phys // bps)
    # métadonnées FVE (3 copies)
    meta_len = 48 + len(entries)
    block = bytearray(64 * 1024)
    block[0:8] = b'-FVE-FS-'
    struct.pack_into('<HH', block, 8, 0x40, 2)
    struct.pack_into('<Q', block, 16, len(plain))
    struct.pack_into('<I', block, 28, hdr_sectors)
    struct.pack_into('<Q', block, 56, hdr_backup)
    struct.pack_into('<IIII', block, 64, meta_len, 1, 48, meta_len)
    struct.pack_into('<H', block, 64 + 36, 0x8004)
    block[112:112 + len(entries)] = entries
    boot = bytearray(512)
    boot[0:3] = b'\xeb\x58\x90'
    boot[3:11] = b'-FVE-FS-'
    struct.pack_into('<H', boot, 11, bps)
    boot[13] = 8
    struct.pack_into('<Q', boot, 40, total_sectors)
    for i, o in enumerate((0xB0, 0xB8, 0xC0)):
        struct.pack_into('<Q', boot, o, meta_at[i])
    boot[510:512] = b'\x55\xaa'
    enc[0:512] = boot
    for o in meta_at:
        enc[o:o + len(block)] = block
    return bytes(enc), vmk, fvek


def make_recovery():
    import random
    r = random.Random(5)
    return '-'.join('%06d' % (r.randrange(0, 5900) * 11) for _ in range(8))


@unittest.skipUnless(HAVE_CRYPTO, 'paquet cryptography absent')
class BitLockerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        img, cls.truth = ntfs_image.build_image()
        cls.plain = bytes(img)
        cls.recovery = make_recovery()
        cls.enc, _vmk, _fvek = build_bitlocker(cls.plain, cls.recovery)
        cls.path = tmpfile(cls.enc)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def test_probe_without_key(self):
        r = Reader(self.path)
        info = bitlocker.probe(r, 0)
        r.close()
        self.assertTrue(info['bitlocker'])
        self.assertEqual(info['method'], 'AES-XTS 128')
        self.assertIn('mot de passe de récupération', [p['type'] for p in info['protectors']])

    def test_decrypt_matches_plaintext(self):
        r = open_reader('bitlocker:' + json.dumps({'inner': self.path, 'recoveryPassword': self.recovery,
                                                   'size': len(self.plain)}))
        try:
            got = r.read_at(0, len(self.plain))
            MB = 1024 * 1024
            expected = bytearray(self.plain)
            for a, b in ((6 * MB, 6 * MB + 3 * 65536), (7 * MB, 7 * MB + 16 * 512)):   # zones de métadonnées / sauvegarde
                expected[a:b] = got[a:b]
            self.assertEqual(got, bytes(expected))
            self.assertEqual(r.read_at(777, 5000), self.plain[777:5777])
            sink = Collector()
            ntfs.scan_volume(r, 0, sink, common.Progress('n', 0, sink), mode='deleted')
            f = [x for x in sink.files if x['name'] == 'photo.jpg'][0]
            self.assertEqual(read_extents(r, f), self.truth['photo.jpg'])
        finally:
            r.close()

    def test_wrong_key_rejected(self):
        from engine.devio import DeviceError
        bad = '-'.join(['000011'] * 8)
        with self.assertRaises(DeviceError):
            open_reader('bitlocker:' + json.dumps({'inner': self.path, 'recoveryPassword': bad}))
        with self.assertRaises(DeviceError):
            open_reader('bitlocker:' + json.dumps({'inner': self.path, 'recoveryPassword': '123456-123456'}))

    def test_recovery_key_checksum_validation(self):
        from engine.devio import DeviceError
        with self.assertRaises(DeviceError):
            bitlocker.recovery_password_to_key('-'.join(['000012'] * 8))        # 12 n'est pas multiple de 11


class ToolsTest(unittest.TestCase):
    def setUp(self):
        import random
        rnd = random.Random(2)
        self.img = bytearray(rnd.randbytes(3 * 1024 * 1024))
        self.img[1000000:1000000 + 19] = 'Contrat Lazarus 2026'.encode()[:19]
        u16 = 'Contrat Lazarus 2026'.encode('utf-16le')
        self.img[2000000:2000000 + len(u16)] = u16
        self.path = tmpfile(self.img)

    def tearDown(self):
        os.unlink(self.path)

    def test_search_text_utf8_and_utf16_case_insensitive(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = tools.search(self.path, text='CONTRAT lazarus')
        hits = [json.loads(ln)['data'] for ln in buf.getvalue().splitlines() if '"hit"' in ln]
        self.assertTrue(res['success'])
        offs = {(h['offset'], h['enc']) for h in hits}
        self.assertIn((1000000, 'utf8'), offs)
        self.assertIn((2000000, 'utf16'), offs)

    def test_search_across_block_boundary_and_hex(self):
        import io
        from contextlib import redirect_stdout
        pos = 8 * 1024 * 1024 - 5            # à cheval sur la frontière de blocs de 8 Mo
        img = bytearray(os.urandom(9 * 1024 * 1024))
        img[pos:pos + 10] = b'LAZARUSKEY'
        p = tmpfile(img)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                tools.search(p, hex_pattern='4c415a41525553' + '4b4559')
            hits = [json.loads(ln)['data'] for ln in buf.getvalue().splitlines() if '"hit"' in ln]
            self.assertEqual([h['offset'] for h in hits], [pos])
        finally:
            os.unlink(p)

    def test_exif_thumbnail_extraction(self):
        import numpy as np
        import cv2
        small = cv2.imencode('.jpg', (np.random.RandomState(0).rand(16, 16, 3) * 255).astype('uint8'))[1].tobytes()
        # TIFF little-endian : IFD0 vide -> IFD1 avec JPEGInterchangeFormat / Length
        ifd0_off = 8
        ifd1_off = ifd0_off + 2 + 0 * 12 + 4
        thumb_off = ifd1_off + 2 + 2 * 12 + 4
        tiff = b'II*\x00' + struct.pack('<I', ifd0_off) + struct.pack('<H', 0) + struct.pack('<I', ifd1_off)
        tiff += struct.pack('<H', 2) + struct.pack('<HHII', 0x0201, 4, 1, thumb_off) + struct.pack('<HHII', 0x0202, 4, 1, len(small))
        tiff += struct.pack('<I', 0) + small
        app1 = b'Exif\x00\x00' + tiff
        big = cv2.imencode('.jpg', (np.random.RandomState(1).rand(64, 64, 3) * 255).astype('uint8'))[1].tobytes()
        jpg = big[:2] + b'\xff\xe1' + struct.pack('>H', len(app1) + 2) + app1 + big[2:]
        self.assertEqual(tools.exif_thumbnail(jpg), small)
        self.assertEqual(tools.exif_thumbnail(big), b'')               # pas d'EXIF : rien

    def test_hex_read_and_export(self):
        r = tools.hex_read(self.path, 1000000, 19)
        self.assertEqual(base64.b64decode(r['data_b64']), b'Contrat Lazarus 202')
        out = os.path.join(tempfile.mkdtemp(), 'x.bin')
        e = tools.export_range(self.path, 1000000, 19, out)
        self.assertEqual(open(out, 'rb').read(), b'Contrat Lazarus 202')
        self.assertTrue(e['success'])


if __name__ == '__main__':
    unittest.main()

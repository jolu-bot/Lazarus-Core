"""Réparation intelligente : images tronquées (inpainting), greffe d'en-tête JPEG, PNG partiel, OOXML/PDF/SQLite."""
import io
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'app', 'main', 'ipc')))

from engine import aifix  # noqa: E402

try:
    import cv2
    import numpy as np
    HAVE_CV = True
except ImportError:
    HAVE_CV = False


def photo(w=320, h=240):
    """Image lisse et texturée type photo (dégradés, formes, léger bruit)."""
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.float32)
    img[..., 0] = 90 + 80 * np.sin(xx / 37.0) * np.cos(yy / 53.0)
    img[..., 1] = 120 + 22 * np.cos(yy / 41.0)
    img[..., 2] = 140 + 50 * np.sin((xx + yy) / 61.0)
    img += np.random.RandomState(3).randn(h, w, 3) * 4
    out = np.clip(img, 0, 255).astype(np.uint8)
    cv2.circle(out, (w // 2, h // 2 - 30), 40, (30, 200, 240), -1)
    cv2.rectangle(out, (20, 20), (90, 70), (200, 60, 60), -1)
    return out


def psnr(a, b):
    mse = float(((a.astype(np.float32) - b.astype(np.float32)) ** 2).mean())
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def write(data, suffix):
    fd, p = tempfile.mkstemp(suffix=suffix)
    os.write(fd, data)
    os.close(fd)
    return p


@unittest.skipUnless(HAVE_CV, 'OpenCV absent')
class ImageRepairTest(unittest.TestCase):
    def setUp(self):
        self.img = photo()
        self.jpg = cv2.imencode('.jpg', self.img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
        self.out = tempfile.mkdtemp()

    def test_truncated_jpeg_is_diagnosed_and_reconstructed(self):
        cut = self.jpg[:int(len(self.jpg) * 0.72)]
        p = write(cut, '.jpg')
        d = aifix.analyze(p)
        self.assertTrue(d['success'])
        self.assertFalse(d['healthy'])
        self.assertTrue(any('manquant' in i or 'tronqué' in i for i in d['issues']), d['issues'])
        r = aifix.repair_auto(p, self.out)
        self.assertTrue(r['success'], r)
        fixed = cv2.imread(r['outputPath'])
        self.assertEqual(fixed.shape, self.img.shape)                       # hauteur d'origine restituée
        self.assertLess(r['completeness'], 100)
        valid = int(self.img.shape[0] * r['completeness'] / 100) - 20
        ref = cv2.imdecode(np.frombuffer(self.jpg, np.uint8), cv2.IMREAD_COLOR)
        self.assertGreater(psnr(fixed[:valid], ref[:valid]), 30)            # la partie intacte est conservée
        # près de la frontière la reconstruction prolonge réellement l'image (bien mieux qu'un aplat gris) ; plus loin elle reste plausible
        flat = np.full_like(ref, 128)
        near = slice(valid + 20, valid + 60)
        self.assertGreater(psnr(fixed[near], ref[near]), psnr(flat[near], ref[near]) + 3)
        self.assertGreater(psnr(fixed[valid + 20:], ref[valid + 20:]), psnr(flat[valid + 20:], ref[valid + 20:]) - 1)
        os.unlink(p)

    def test_valid_jpeg_untouched(self):
        p = write(self.jpg, '.jpg')
        d = aifix.analyze(p)
        self.assertTrue(d['healthy'], d['issues'])
        r = aifix.repair_auto(p, self.out)
        self.assertTrue(r['success'])
        self.assertEqual(open(r['outputPath'], 'rb').read(), self.jpg)
        os.unlink(p)

    def test_jpeg_with_destroyed_header_uses_reference(self):
        ref_img = photo()
        ref = cv2.imencode('.jpg', ref_img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()      # même appareil / mêmes tables
        broken = b'\x00' * 300 + self.jpg[300:]                                 # SOI, DQT, SOF… perdus ; SOS et données intacts
        self.assertIn(b'\xff\xda', broken)
        p = write(broken, '.jpg')
        rp = write(ref, '.jpg')
        r0 = aifix.repair_auto(p, self.out)
        self.assertFalse(r0['success'])                                         # sans référence : impossible
        r = aifix.repair_auto(p, self.out, reference=rp)
        self.assertTrue(r['success'], r)
        fixed = cv2.imread(r['outputPath'])
        ref_dec = cv2.imdecode(np.frombuffer(self.jpg, np.uint8), cv2.IMREAD_COLOR)
        self.assertGreater(psnr(fixed, ref_dec), 40)
        os.unlink(p)
        os.unlink(rp)

    def test_truncated_png_rows_recovered(self):
        png = cv2.imencode('.png', self.img)[1].tobytes()
        cut = png[:int(len(png) * 0.8)]
        p = write(cut, '.png')
        d = aifix.analyze(p)
        self.assertFalse(d['healthy'])
        r = aifix.repair_auto(p, self.out)
        self.assertTrue(r['success'], r)
        fixed = cv2.imread(r['outputPath'])
        self.assertEqual(fixed.shape, self.img.shape)
        valid = int(self.img.shape[0] * r['completeness'] / 100)
        self.assertTrue(np.array_equal(fixed[:valid], self.img[:valid]))        # pixels valides inchangés au bit près
        os.unlink(p)

    def test_enhance_option_changes_pixels(self):
        noisy = np.clip(self.img.astype(np.int16) + np.random.RandomState(1).randn(*self.img.shape) * 18, 0, 255).astype(np.uint8)
        p = write(cv2.imencode('.png', noisy)[1].tobytes(), '.png')
        r = aifix.repair_auto(p, self.out, enhance=True)
        self.assertTrue(r['success'])
        out = cv2.imread(r['outputPath'])
        lap = lambda a: cv2.Laplacian(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        self.assertLess(lap(out), lap(noisy) * 0.5)                             # le bruit haute fréquence est nettement réduit
        os.unlink(p)


class DocumentRepairTest(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()

    def make_docx(self):
        import random
        rnd = random.Random(4)
        words = ['contrat', 'facture', 'client', 'livraison', 'paiement', 'projet', 'société', 'rapport', 'budget', 'équipe']
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('[Content_Types].xml', '<Types/>')
            body = ''.join(f'<w:p><w:r><w:t>Ligne {i} Lazarus ' + ' '.join(rnd.choice(words) + str(rnd.randrange(10000)) for _ in range(12))
                           + '</w:t></w:r></w:p>' for i in range(300))
            z.writestr('word/document.xml', f'<w:document><w:body>{body}</w:body></w:document>')
        return buf.getvalue()

    def test_docx_central_directory_destroyed(self):
        d = self.make_docx()
        eocd = d.rfind(b'PK\x05\x06')
        cd = struct.unpack('<I', d[eocd + 16:eocd + 20])[0]
        broken = d[:cd]                                                          # répertoire central perdu
        p = write(broken, '.docx')
        dg = aifix.analyze(p)
        self.assertFalse(dg['healthy'])
        r = aifix.repair_auto(p, self.out)
        self.assertTrue(r['success'], r)
        with zipfile.ZipFile(r['outputPath']) as z:
            self.assertIn('Ligne 299 Lazarus', z.read('word/document.xml').decode())
        os.unlink(p)

    def test_docx_text_salvaged_when_archive_is_truncated_mid_stream(self):
        d = self.make_docx()
        i = d.find(b'word/document.xml')
        cut = d[:i + 30 + (len(d) - i) // 2]                                     # coupure au milieu du flux compressé
        p = write(cut, '.docx')
        r = aifix.repair_auto(p, self.out)
        self.assertTrue(r['success'], r)
        txts = [o for o in r['outputs'] if o.endswith('_texte.txt')]
        self.assertTrue(txts, r)
        with open(txts[0], encoding='utf-8') as f:
            txt = f.read()
        self.assertIn('Ligne 0 Lazarus', txt)
        self.assertIn('Ligne 20 Lazarus', txt)
        os.unlink(p)

    def test_pdf_text_and_xref(self):
        content = b'BT /F1 12 Tf (Facture 2026 Lazarus) Tj ET'
        comp = zlib.compress(content)
        pdf = (b'%%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n'
               b'3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>\nendobj\n4 0 obj\n<< /Length %d /Filter /FlateDecode >>\nstream\n'
               % len(comp)) + comp + b'\nendstream\nendobj\n'
        p = write(pdf, '.pdf')                                                   # pas de xref/trailer : tronqué
        d = aifix.analyze(p)
        self.assertFalse(d['healthy'])
        r = aifix.repair_auto(p, self.out)
        self.assertTrue(r['success'], r)
        self.assertTrue(any(o.endswith('_texte.txt') for o in r['outputs']))
        txt = [o for o in r['outputs'] if o.endswith('_texte.txt')][0]
        self.assertIn('Facture 2026 Lazarus', open(txt, encoding='utf-8').read())
        os.unlink(p)

    def test_sqlite_corrupted_pages_salvaged(self):
        fd, db = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        c = sqlite3.connect(db)
        c.execute('create table clients (id integer primary key, nom text, note text)')
        c.executemany('insert into clients values (?,?,?)', [(i, f'Client {i}', 'x' * 200) for i in range(400)])
        c.commit()
        c.close()
        raw = bytearray(open(db, 'rb').read())
        ps = struct.unpack('>H', raw[16:18])[0]
        # détruit une page de données au milieu du fichier
        mid = (len(raw) // ps // 2) * ps
        raw[mid:mid + ps] = os.urandom(ps)
        p = write(bytes(raw), '.sqlite')
        d = aifix.analyze(p)
        self.assertFalse(d['healthy'])
        r = aifix.repair_auto(p, self.out)
        self.assertTrue(r['success'], r)
        c = sqlite3.connect(r['outputPath'])
        n = c.execute('select count(*) from clients').fetchone()[0]
        c.close()
        self.assertGreater(n, 250)
        os.unlink(p)
        os.unlink(db)

    def test_unknown_binary_gets_text_extraction(self):
        blob = os.urandom(5000) + 'Rapport confidentiel de la société Lazarus Core'.encode('utf-16le') + os.urandom(3000)
        p = write(blob, '.doc')
        r = aifix.repair_auto(p, self.out)
        self.assertTrue(r['success'], r)
        self.assertIn('Rapport confidentiel', open(r['outputPath'], encoding='utf-8').read())
        os.unlink(p)

    def test_extension_mismatch_reported(self):
        p = write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 40, '.jpg')
        d = aifix.analyze(p)
        self.assertTrue(any('extension' in i for i in d['issues']), d['issues'])
        os.unlink(p)


if __name__ == '__main__':
    unittest.main()

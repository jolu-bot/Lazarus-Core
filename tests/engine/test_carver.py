import gzip
import io
import os
import random
import sqlite3
import struct
import sys
import tempfile
import unittest
import wave
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'app', 'main', 'ipc')))

from engine import carver, common  # noqa: E402
from engine.devio import Reader  # noqa: E402
from test_ntfs import Collector  # noqa: E402


def make_png(w=40, h=30):
    raw = b''.join(b'\x00' + bytes((x * 5 + y) & 0xFF for x in range(w * 3)) for y in range(h))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def make_jpeg():
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    img = (np.random.RandomState(1).rand(64, 64, 3) * 255).astype('uint8')
    ok, buf = cv2.imencode('.jpg', img)
    return bytes(buf) if ok else None


def make_zip():
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<xml/>' * 50)
        z.writestr('word/document.xml', 'Bonjour' * 400)
    return b.getvalue()


def make_sqlite():
    fd, p = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    c = sqlite3.connect(p)
    c.execute('create table t(a,b)')
    c.executemany('insert into t values(?,?)', [(i, 'x' * 50) for i in range(500)])
    c.commit()
    c.close()
    d = open(p, 'rb').read()
    os.unlink(p)
    return d


def make_wav():
    b = io.BytesIO()
    with wave.open(b, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(bytes(range(256)) * 40)
    return b.getvalue()


def make_pdf():
    return (b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n0000000000 65535 f \n'
            b'trailer\n<< /Root 1 0 R >>\nstartxref\n9\n%%EOF\n') + b'\x00' * 10


def make_mp4():
    def atom(t, d):
        return struct.pack('>I', 8 + len(d)) + t + d
    return atom(b'ftyp', b'isom\x00\x00\x02\x00isomiso2') + atom(b'mdat', os.urandom(3000)) + atom(b'moov', b'\x00' * 200)


def make_mp3():
    frame = b'\xff\xfb\x90\x00' + b'\x00' * 413     # 128 kbps 44.1 kHz = 417 octets
    return frame * 20


class CarveTest(unittest.TestCase):
    def test_carve_real_formats(self):
        rnd = random.Random(7)
        ss = 512
        items = {}
        payload = {
            'png': make_png(), 'zip': make_zip(), 'sqlite': make_sqlite(), 'wav': make_wav(),
            'pdf': make_pdf().rstrip(b'\x00'), 'mp4': make_mp4(), 'mp3': make_mp3(),
            'gz': gzip.compress(b'lazarus ' * 5000),
        }
        jpg = make_jpeg()
        if jpg:
            payload['jpg'] = jpg
        img = bytearray(rnd.randbytes(6 * 1024 * 1024))
        # faux positifs : 'BM' et 'PK' aléatoires alignés sur des secteurs
        for k in range(40):
            o = rnd.randrange(0, len(img) // ss) * ss
            img[o:o + 2] = rnd.choice([b'BM', b'PK', b'MZ', b'\xff\xd8'])
        pos = 64 * ss
        for ext, data in payload.items():
            img[pos:pos + len(data)] = data
            items[ext] = (pos, len(data))
            pos += (-(-len(data) // ss) + rnd.randrange(3, 40)) * ss
        fd, path = tempfile.mkstemp(suffix='.img')
        os.write(fd, bytes(img))
        os.close(fd)
        r = Reader(path)
        try:
            sink = Collector()
            sink.starts = set()
            carver.carve(r, sink, common.Progress('carve', 0, sink), label='T')
            found = {}
            for f in sink.files:
                found.setdefault(f['extents'][0][0], f)
            for ext, (off, ln) in items.items():
                self.assertIn(off, found, f'{ext} non trouvé')
                self.assertEqual(found[off]['size'], ln, f'{ext}: taille {found[off]["size"]} != {ln}')
            self.assertEqual(found[items['zip'][0]]['extension'], 'docx')
            self.assertEqual(found[items['wav'][0]]['extension'], 'wav')
            # aucun faux positif parmi les entêtes aléatoires
            real = {off for off, _ in items.values()}
            bogus = [f for off, f in found.items() if off not in real]
            self.assertEqual([(f['extension'], f['size']) for f in bogus], [])
        finally:
            r.close()
            os.unlink(path)


class TextAndCustomCarveTest(unittest.TestCase):
    def run_carve(self, img, **kw):
        fd, path = tempfile.mkstemp(suffix='.img')
        os.write(fd, bytes(img))
        os.close(fd)
        r = Reader(path)
        try:
            sink = Collector()
            sink.starts = set()
            carver.carve(r, sink, common.Progress('carve', 0, sink), **kw)
            return sink.files
        finally:
            r.close()
            os.unlink(path)

    def test_text_files_without_signature(self):
        rnd = random.Random(3)
        img = bytearray(rnd.randbytes(2 * 1024 * 1024))
        text = ('Bonjour, ceci est un document texte sans aucune signature de format. ' * 80).encode()
        csv = b''.join(b'%d,nom%d,valeur%d\n' % (i, i, i * 7) for i in range(300))
        for off, data in ((100 * 512, text), (400 * 512, csv)):
            img[off:off + len(data)] = data
            pad = (-(off + len(data))) % 512
            img[off + len(data):off + len(data) + pad] = b'\x00' * pad
            nxt = off + len(data) + pad
            img[nxt:nxt + 1024] = b'\x00' * 1024
        files = self.run_carve(img, text=True)
        by = {f['extents'][0][0]: f for f in files}
        self.assertEqual(by[100 * 512]['size'], len(text))
        self.assertEqual(by[100 * 512]['extension'], 'txt')
        self.assertEqual(by[400 * 512]['size'], len(csv))
        self.assertEqual(by[400 * 512]['extension'], 'csv')
        # sans l'option, rien (le texte n'a pas de signature)
        self.assertEqual(self.run_carve(img), [])

    def test_custom_signature(self):
        rnd = random.Random(4)
        img = bytearray(rnd.randbytes(1024 * 1024))
        blob = b'LZRX\x01\x02' + b'payload' * 100 + b'ENDLZ'
        img[2048:2048 + len(blob)] = blob
        files = self.run_carve(img, custom=[{'ext': 'lzrx', 'header': '4c5a525801', 'footer': '454e444c5a', 'maxMB': 1}])
        self.assertEqual([(f['extension'], f['size']) for f in files], [('lzrx', len(blob))])


if __name__ == '__main__':
    unittest.main()

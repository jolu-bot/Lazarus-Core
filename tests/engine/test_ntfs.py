import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'app', 'main', 'ipc')))

from engine import common, ntfs  # noqa: E402
from engine.devio import Reader  # noqa: E402
import ntfs_image  # noqa: E402


class Collector(common.FileSink):
    def __init__(self):
        super().__init__('test')
        self.files = []

    def add(self, f, dedupe_key=None):
        if dedupe_key is not None:
            if dedupe_key in self.seen_keys:
                return None
            self.seen_keys.add(dedupe_key)
        f['id'] = len(self.files)
        self.files.append(f)
        self.count += 1
        return f


def read_extents(reader, rec):
    out = b''
    for off, ln in rec['extents']:
        out += (b'\x00' * ln) if off < 0 else reader.read_at(off, ln)
    if rec.get('resident_b64'):
        import base64
        out = base64.b64decode(rec['resident_b64'])
    return out[:rec['size']]


class NtfsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img, cls.truth = ntfs_image.build_image()
        fd, cls.path = tempfile.mkstemp(suffix='.img')
        os.write(fd, bytes(cls.img))
        os.close(fd)
        cls.reader = Reader(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.reader.close()
        os.unlink(cls.path)

    def scan(self, mode):
        sink = Collector()
        prog = common.Progress('ntfs', 0, sink)
        ntfs.scan_volume(self.reader, 0, sink, prog, mode=mode, part_label='T')
        return {f['name']: f for f in sink.files}

    def test_deleted_mode_finds_deleted_and_recycle(self):
        files = self.scan('deleted')
        for n in ('photo.jpg', 'big.bin', 'sparse.dat', 'frag.dat'):
            self.assertIn(n, files, n)
        self.assertNotIn('hello.txt', files)       # actif : absent en mode « supprimés »
        self.assertIn('rapport.txt', files)        # nom d'origine retrouvé via $I

    def test_content_recovery(self):
        files = self.scan('all')
        self.assertEqual(read_extents(self.reader, files['photo.jpg']), self.truth['photo.jpg'])
        self.assertEqual(read_extents(self.reader, files['frag.dat']), self.truth['frag.dat'])
        self.assertEqual(read_extents(self.reader, files['sparse.dat']), self.truth['sparse.dat'])
        self.assertEqual(read_extents(self.reader, files['hello.txt']), self.truth['hello.txt'])
        self.assertEqual(read_extents(self.reader, files['rapport.txt']), self.truth['$R1ABC.txt'])

    def test_paths_and_status(self):
        files = self.scan('all')
        self.assertEqual(files['photo.jpg']['path'], 'Docs\\photo.jpg')
        self.assertEqual(files['photo.jpg']['status'], common.ST_DELETED)
        self.assertEqual(files['hello.txt']['status'], common.ST_ACTIVE)
        self.assertEqual(files['photo.jpg']['fragments'], 2)

    def test_overwrite_detection(self):
        files = self.scan('deleted')
        self.assertEqual(files['photo.jpg']['overwritten_pct'], 0.0)
        self.assertEqual(files['big.bin']['overwritten_pct'], 100.0)
        self.assertEqual(files['big.bin']['status'], common.ST_PARTIAL)
        self.assertLess(files['big.bin']['confidence'], 0.1)
        self.assertGreater(files['photo.jpg']['confidence'], 0.9)

    def test_recycle_original_path(self):
        files = self.scan('deleted')
        r = files['rapport.txt']
        self.assertEqual(r['original_path'], 'C:\\Users\\Moi\\Documents\\rapport.txt')
        self.assertEqual(r['deleted_at'], 1700000500)

    def test_mft_carve_on_destroyed_mft(self):
        # détruit le record 0 et le miroir : le moteur doit basculer en carving
        img = bytearray(self.img)
        off = 4 * ntfs_image.CS
        img[off:off + 1024] = b'\x00' * 1024
        off2 = 100 * ntfs_image.CS
        img[off2:off2 + 1024] = b'\x00' * 1024
        fd, p = tempfile.mkstemp(suffix='.img')
        os.write(fd, bytes(img))
        os.close(fd)
        r = Reader(p)
        try:
            sink = Collector()
            prog = common.Progress('ntfs', 0, sink)
            ntfs.scan_volume(r, 0, sink, prog, mode='deleted', part_label='T')
            names = {f['name'] for f in sink.files}
            self.assertIn('photo.jpg', names)
            self.assertIn('frag.dat', names)
            f = [x for x in sink.files if x['name'] == 'photo.jpg'][0]
            self.assertEqual(read_extents(r, f), self.truth['photo.jpg'])
        finally:
            r.close()
            os.unlink(p)


if __name__ == '__main__':
    unittest.main()

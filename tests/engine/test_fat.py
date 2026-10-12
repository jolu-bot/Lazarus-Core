import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'app', 'main', 'ipc')))

from engine import common, fat  # noqa: E402
from engine.devio import Reader  # noqa: E402
import fat_image  # noqa: E402
from test_ntfs import Collector, read_extents  # noqa: E402


def make_reader(img):
    fd, path = tempfile.mkstemp(suffix='.img')
    os.write(fd, bytes(img))
    os.close(fd)
    return Reader(path), path


class Names(dict):
    """Recherche tolérante : un nom court supprimé perd son 1er caractère (comportement FAT réel)."""

    def __getitem__(self, k):
        if dict.__contains__(self, k):
            return dict.__getitem__(self, k)
        for n in dict.keys(self):
            if len(n) == len(k) and n[1:] == k[1:]:
                return dict.__getitem__(self, n)
        raise KeyError(k)

    def __contains__(self, k):
        try:
            self[k]
            return True
        except KeyError:
            return False


class FatTest(unittest.TestCase):
    def run_variant(self, variant):
        img, truth = fat_image.build_fat(variant)
        r, path = make_reader(img)
        try:
            sink = Collector()
            prog = common.Progress('fat', 0, sink)
            fat.scan_fat(r, 0, sink, prog, mode='all', part_label='T')
            files = {f['name']: f for f in sink.files}
            files = Names(files)
            self.assertEqual(read_extents(r, files['README.TXT']), truth['README.TXT'])
            self.assertEqual(files['README.TXT']['status'], common.ST_ACTIVE)
            self.assertEqual(read_extents(r, files['FRAG.BIN']), truth['FRAG.BIN'])
            self.assertEqual(files['FRAG.BIN']['fragments'], 2)
            self.assertIn('Mon Rapport Final.docx', files)
            self.assertEqual(read_extents(r, files['Mon Rapport Final.docx']), truth['Mon Rapport Final.docx'])
            self.assertEqual(files['Mon Rapport Final.docx']['status'], common.ST_DELETED)
            self.assertEqual(files['Mon Rapport Final.docx']['overwritten_pct'], 0.0)
            inner = files['INNER.TXT']
            self.assertEqual(read_extents(r, inner), truth['INNER.TXT'])
            self.assertTrue(inner['path'].endswith('NNER.TXT'))
            self.assertGreater(files['LOST.DAT']['overwritten_pct'], 0)
            self.assertLess(files['LOST.DAT']['confidence'], files['INNER.TXT']['confidence'])
            # mode « supprimés » : pas de fichier actif
            sink2 = Collector()
            fat.scan_fat(r, 0, sink2, common.Progress('fat', 0, sink2), mode='deleted')
            names = Names({f['name']: f for f in sink2.files})
            self.assertNotIn('README.TXT', names)
            self.assertIn('Mon Rapport Final.docx', names)
        finally:
            r.close()
            os.unlink(path)

    def test_fat16(self):
        self.run_variant('fat16')

    def test_fat32(self):
        self.run_variant('fat32')

    def test_orphan_dirs_after_quick_format(self):
        img, truth = fat_image.build_fat('fat32')
        r0, p0 = make_reader(img)
        v = fat.FatVolume(r0, 0)
        r0.close()
        os.unlink(p0)
        # « formatage rapide » : FAT et racine remises à zéro
        bps = v.bps
        img[v.fat_off:v.fat_off + v.fat_bytes * 2] = b'\x00' * (v.fat_bytes * 2)
        img[v.coff(2):v.coff(2) + bps * 4] = b'\x00' * (bps * 4)
        r, path = make_reader(img)
        try:
            sink = Collector()
            fat.scan_fat(r, 0, sink, common.Progress('fat', 0, sink), mode='deleted', deep=True)
            names = Names({f['name']: f for f in sink.files})
            self.assertIn('INNER.TXT', names)
            f = names['INNER.TXT']
            self.assertEqual(read_extents(r, f), truth['INNER.TXT'])
        finally:
            r.close()
            os.unlink(path)


class ExfatTest(unittest.TestCase):
    def test_exfat(self):
        img, truth = fat_image.build_exfat()
        r, path = make_reader(img)
        try:
            sink = Collector()
            fat.scan_exfat(r, 0, sink, common.Progress('exfat', 0, sink), mode='all', part_label='T')
            files = {f['name']: f for f in sink.files}
            self.assertEqual(read_extents(r, files['present.bin']), truth['present.bin'])
            n = 'Photo déjà supprimée.jpg'
            self.assertIn(n, files)
            self.assertEqual(read_extents(r, files[n]), truth[n])
            self.assertEqual(files[n]['status'], common.ST_DELETED)
            self.assertEqual(files['ecrase.dat']['status'], common.ST_PARTIAL)
            self.assertEqual(files['ecrase.dat']['overwritten_pct'], 100.0)
        finally:
            r.close()
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()

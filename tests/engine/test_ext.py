import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'app', 'main', 'ipc')))

from engine import common, ext, partitions  # noqa: E402
from engine.devio import Reader  # noqa: E402
import ext_image  # noqa: E402
from test_ntfs import Collector, read_extents  # noqa: E402


class ExtTest(unittest.TestCase):
    def test_ext(self):
        img, truth = ext_image.build_ext()
        fd, path = tempfile.mkstemp(suffix='.img')
        os.write(fd, bytes(img))
        os.close(fd)
        r = Reader(path)
        try:
            self.assertEqual(partitions.probe_fs(r, 0)['fs'], 'ext')
            sink = Collector()
            ext.scan_ext(r, 0, sink, common.Progress('ext', 0, sink), mode='all', part_label='T')
            files = {f['name']: f for f in sink.files}
            self.assertIn('live.txt', files)
            self.assertEqual(read_extents(r, files['live.txt']), truth['live.txt'])
            self.assertEqual(files['live.txt']['path'], 'docs\\live.txt')
            # fichier supprimé, extents « vidés » mais récupérables, nom retrouvé dans le slack
            self.assertIn('gone.txt', files)
            self.assertEqual(read_extents(r, files['gone.txt']), truth['gone.txt'])
            self.assertEqual(files['gone.txt']['status'], common.ST_DELETED)
            # blocs indirects + réallocation partielle détectée
            f = files['deleted.jpg']
            self.assertEqual(read_extents(r, f), truth['deleted.jpg'])
            self.assertGreater(f['overwritten_pct'], 0)
            self.assertEqual(f['path'], 'docs\\deleted.jpg')
        finally:
            r.close()
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()

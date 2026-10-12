import json
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'app', 'main', 'ipc')))

from engine import common, imager, lznt1, partitions, recover  # noqa: E402
from engine.devio import Reader  # noqa: E402
import fat_image  # noqa: E402
import ntfs_image  # noqa: E402


def tmpfile(data=b''):
    fd, p = tempfile.mkstemp(suffix='.img')
    os.write(fd, bytes(data))
    os.close(fd)
    return p


@unittest.skipUnless(os.name == 'nt', 'ntdll uniquement sous Windows')
class Lznt1Test(unittest.TestCase):
    def test_against_windows_implementation(self):
        import ctypes
        nt = ctypes.WinDLL('ntdll')
        data = (b'Lazarus Core recupere vos donnees. ' * 200 + bytes(range(256)) * 20 + b'\x00' * 3000)[:12000]
        ws = ctypes.c_ulong(0)
        frag = ctypes.c_ulong(0)
        FMT = 2 | 0x100        # LZNT1 | STANDARD
        self.assertEqual(nt.RtlGetCompressionWorkSpaceSize(FMT, ctypes.byref(ws), ctypes.byref(frag)), 0)
        work = ctypes.create_string_buffer(ws.value)
        out = ctypes.create_string_buffer(len(data) * 2)
        n = ctypes.c_ulong(0)
        st = nt.RtlCompressBuffer(FMT, data, len(data), out, len(out), 4096, ctypes.byref(n), work)
        self.assertEqual(st, 0)
        self.assertEqual(lznt1.decompress(out.raw[:n.value]), data)


@unittest.skipUnless(os.name == 'nt', 'ntdll uniquement sous Windows')
class NtfsCompressedFileTest(unittest.TestCase):
    def test_compressed_file_roundtrip(self):
        import ctypes
        from test_ntfs import Collector, read_extents
        from engine import ntfs
        nt = ctypes.WinDLL('ntdll')
        data = (b'Lazarus Core compresse. ' * 4000)[:65536]
        FMT = 2 | 0x100
        ws, frag = ctypes.c_ulong(0), ctypes.c_ulong(0)
        nt.RtlGetCompressionWorkSpaceSize(FMT, ctypes.byref(ws), ctypes.byref(frag))
        out = ctypes.create_string_buffer(len(data) * 2)
        n = ctypes.c_ulong(0)
        work = ctypes.create_string_buffer(ws.value)
        self.assertEqual(nt.RtlCompressBuffer(FMT, data, len(data), out, len(out), 4096, ctypes.byref(n), work), 0)
        comp = out.raw[:n.value]
        k = -(-len(comp) // ntfs_image.CS)
        self.assertLess(k, 16)
        img, _ = ntfs_image.build_image()
        img[300 * ntfs_image.CS:300 * ntfs_image.CS + len(comp)] = comp
        rec = ntfs_image.make_record(40, [
            ntfs_image.std_info(), ntfs_image.file_name('compressed.txt', 24),
            ntfs_image.attr_nonres(0x80, [(300, k), (None, 16 - k)], 0, 15, 65536, 65536, flags=0x0001, comp_unit=4)], 0)
        off = 4 * ntfs_image.CS + 40 * 1024
        img[off:off + 1024] = rec
        p = tmpfile(img)
        r = Reader(p)
        try:
            sink = Collector()
            ntfs.scan_volume(r, 0, sink, common.Progress('n', 0, sink), mode='deleted')
            f = [x for x in sink.files if x['name'] == 'compressed.txt'][0]
            self.assertTrue(f['compressed'])
            rr = recover.RecordReader(r, f)
            self.assertEqual(rr.read(0, 65536), data)
        finally:
            r.close()
            os.unlink(p)


class NtfsInitializedSizeTest(unittest.TestCase):
    def test_bytes_beyond_initialized_size_are_zero(self):
        from test_ntfs import Collector
        from engine import ntfs
        img, _ = ntfs_image.build_image()
        img[300 * ntfs_image.CS:300 * ntfs_image.CS + 8192] = b'\xab' * 8192          # restes d'un ancien fichier
        rec = ntfs_image.make_record(41, [
            ntfs_image.std_info(), ntfs_image.file_name('prealloue.bin', 24),
            ntfs_image.attr_nonres(0x80, [(300, 2)], 0, 1, 8192, 8000, init=4096)], 0)
        off = 4 * ntfs_image.CS + 41 * 1024
        img[off:off + 1024] = rec
        p = tmpfile(img)
        r = Reader(p)
        try:
            sink = Collector()
            ntfs.scan_volume(r, 0, sink, common.Progress('n', 0, sink), mode='deleted')
            f = [x for x in sink.files if x['name'] == 'prealloue.bin'][0]
            self.assertEqual(f['valid_size'], 4096)
            data = recover.RecordReader(r, f).read(0, 8000)
            self.assertEqual(data[:4096], b'\xab' * 4096)
            self.assertEqual(data[4096:], b'\x00' * (8000 - 4096))
        finally:
            r.close()
            os.unlink(p)


class PartitionTest(unittest.TestCase):
    def make_disk(self, gpt=False):
        ntfs_img, _ = ntfs_image.build_image()
        fat_img, _ = fat_image.build_fat('fat16')
        start1 = 2048 * 512
        start2 = start1 + len(ntfs_img) + 1024 * 1024
        disk = bytearray(start2 + len(fat_img) + 2 * 1024 * 1024)
        disk[start1:start1 + len(ntfs_img)] = ntfs_img
        disk[start2:start2 + len(fat_img)] = fat_img
        mbr = bytearray(512)
        if not gpt:
            def ent(i, ptype, lba, n):
                struct.pack_into('<B3sB3sII', mbr, 446 + i * 16, 0, b'\0\0\0', ptype, b'\0\0\0', lba, n)
            ent(0, 0x07, start1 // 512, len(ntfs_img) // 512)
            ent(1, 0x06, start2 // 512, len(fat_img) // 512)
        else:
            struct.pack_into('<B3sB3sII', mbr, 446, 0, b'\0\0\0', 0xEE, b'\0\0\0', 1, 0xFFFFFFFF)
            hdr = bytearray(512)
            hdr[0:8] = b'EFI PART'
            struct.pack_into('<QQ', hdr, 72, 2, 0)
            struct.pack_into('<I', hdr, 80, 4)
            struct.pack_into('<I', hdr, 84, 128)
            disk[512:1024] = hdr
            ents = bytearray(4 * 128)
            for i, (a, b) in enumerate(((start1, len(ntfs_img)), (start2, len(fat_img)))):
                e = bytearray(128)
                e[0:16] = bytes([0xA2, 0xA0, 0xD0, 0xEB, 0xE5, 0xB9, 0x33, 0x44, 0x87, 0xC0, 0x68, 0xB6, 0xB7, 0x26, 0x99, 0xC7])
                struct.pack_into('<QQ', e, 32, a // 512, (a + b) // 512 - 1)
                e[56:56 + 12] = f'Part{i}'.encode('utf-16le')
                ents[i * 128:(i + 1) * 128] = e
            disk[1024:1024 + len(ents)] = ents
        mbr[510:512] = b'\x55\xaa'
        disk[0:512] = mbr
        return disk, start1, start2

    def test_mbr(self):
        disk, s1, s2 = self.make_disk()
        p = tmpfile(disk)
        r = Reader(p)
        try:
            parts = partitions.detect_layout(r)
            self.assertEqual([(x['start'], x['fs']) for x in parts], [(s1, 'ntfs'), (s2, 'fat')])
        finally:
            r.close()
            os.unlink(p)

    def test_gpt(self):
        disk, s1, s2 = self.make_disk(gpt=True)
        p = tmpfile(disk)
        r = Reader(p)
        try:
            parts = partitions.detect_layout(r)
            self.assertEqual([(x['start'], x['fs']) for x in parts], [(s1, 'ntfs'), (s2, 'fat')])
        finally:
            r.close()
            os.unlink(p)

    def test_lost_partitions_after_table_wipe(self):
        disk, s1, s2 = self.make_disk()
        disk[0:512] = b'\x00' * 512
        p = tmpfile(disk)
        r = Reader(p)
        try:
            self.assertFalse(any(x['fs'] for x in partitions.detect_layout(r)))
            lost = partitions.find_lost_partitions(r, [])
            starts = {(x['start'], x['fs']) for x in lost}
            self.assertIn((s1, 'ntfs'), starts)
        finally:
            r.close()
            os.unlink(p)


class ImagerTest(unittest.TestCase):
    def test_bad_sectors_and_resume(self):
        src_data = os.urandom(3 * 1024 * 1024 + 1024)
        src = tmpfile(src_data)
        out_dir = tempfile.mkdtemp()
        out = os.path.join(out_dir, 'copy.img')
        bad_lo, bad_hi = 1024 * 1024 + 4096, 1024 * 1024 + 4096 + 8192     # 16 secteurs illisibles
        orig = Reader._raw_pread

        def flaky(self, off, n):
            if off < bad_hi and off + n > bad_lo:
                return b'', False
            return orig(self, off, n)

        Reader._raw_pread = flaky
        try:
            res = imager.image_disk(src, out)
        finally:
            Reader._raw_pread = orig
        self.assertTrue(res['success'])
        self.assertEqual(res['badSectors'], 16)
        got = open(out, 'rb').read()
        self.assertEqual(len(got), len(src_data))
        self.assertEqual(got[:bad_lo], src_data[:bad_lo])
        self.assertEqual(got[bad_lo:bad_hi], b'\x00' * (bad_hi - bad_lo))
        self.assertEqual(got[bad_hi:], src_data[bad_hi:])
        m = json.load(open(out + '.lazmap.json'))
        self.assertTrue(m['complete'])
        self.assertEqual(m['badCount'], 16)
        import hashlib
        self.assertEqual(res['sha256'], hashlib.sha256(got).hexdigest())
        os.unlink(src)


class SafePathTest(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(recover.safe_relpath('..\\..\\Windows\\evil.dll'), ['_', '_', 'Windows', 'evil.dll'])
        self.assertEqual(recover.safe_component('CON'), '_CON')
        self.assertEqual(recover.safe_component('a<b>c:d.txt'), 'a_b_c_d.txt')
        self.assertEqual(recover.safe_relpath('C:\\x\\y'), ['C_', 'x', 'y'])

    def test_recover_never_escapes_destination(self):
        dest = tempfile.mkdtemp()
        rec = {'name': '..\\..\\escape.txt', 'dir': '..\\..\\..', 'source': 'ntfs', 'size': 3, 'resident_b64': 'YWJj',
               'extension': 'txt'}
        res = recover.recover_one(recover.ReaderPool(), rec, dest, 'tree', False)
        self.assertTrue(res['success'])
        self.assertTrue(os.path.abspath(res['outputPath']).startswith(os.path.abspath(dest)))


if __name__ == '__main__':
    unittest.main()

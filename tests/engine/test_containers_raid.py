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

from engine import common, containers, ntfs, raid  # noqa: E402
from engine.devio import Reader, open_reader  # noqa: E402
import ntfs_image  # noqa: E402
from test_misc import PartitionTest, tmpfile  # noqa: E402
from test_ntfs import Collector, read_extents  # noqa: E402


# ---------------------------------------------------------------- constructeurs de conteneurs
def build_vhd_dynamic(raw: bytes, block=2 * 1024 * 1024) -> bytes:
    size = len(raw)
    nblocks = -(-size // block)
    footer = bytearray(512)
    footer[0:8] = b'conectix'
    struct.pack_into('>IIQ', footer, 8, 2, 0x00010000, 512)          # features, version, data offset
    struct.pack_into('>QQ', footer, 40, size, size)
    struct.pack_into('>I', footer, 60, 3)
    hdr = bytearray(1024)
    hdr[0:8] = b'cxsparse'
    struct.pack_into('>QQ', hdr, 8, 0xFFFFFFFFFFFFFFFF, 1536)       # table offset
    struct.pack_into('>III', hdr, 24, 0x00010000, nblocks, block)
    bat_size = -(-nblocks * 4 // 512) * 512
    bitmap = -(-(block // 512) // 8)
    bitmap = -(-bitmap // 512) * 512
    data = bytearray()
    bat = []
    pos = 1536 + bat_size
    for b in range(nblocks):
        chunk = raw[b * block:(b + 1) * block].ljust(block, b'\x00')
        if chunk.count(0) == len(chunk):
            bat.append(0xFFFFFFFF)
            continue
        bat.append(pos // 512)
        data += b'\xff' * bitmap + chunk
        pos += bitmap + block
    batb = struct.pack('>%dI' % nblocks, *bat).ljust(bat_size, b'\xff')
    return bytes(footer) + bytes(hdr) + batb + bytes(data) + bytes(footer)


def build_vhdx(raw: bytes, block=1024 * 1024, sector=512) -> bytes:
    size = len(raw)
    nblocks = -(-size // block)
    chunk_ratio = (1 << 23) * sector // block
    nbat = nblocks + (nblocks // chunk_ratio) + 1
    out = bytearray(4 * 1024 * 1024)
    out[0:8] = b'vhdxfile'
    out[65536:65540] = b'head'
    out[131072:131076] = b'head'
    rt = bytearray(65536)
    rt[0:4] = b'regi'
    struct.pack_into('<II', rt, 8, 2, 0)
    for i, (g, off, ln) in enumerate(((uuid.UUID('2DC27766-F623-4200-9D64-115E9BFD4A08'), 3 * 1024 * 1024, 1024 * 1024),
                                      (uuid.UUID('8B7CA206-4790-4B9A-B8FE-575F050F886E'), 2 * 1024 * 1024, 1024 * 1024))):
        rt[16 + i * 32:32 + i * 32] = g.bytes_le
        struct.pack_into('<QII', rt, 32 + i * 32, off, ln, 1)
    out[192 * 1024:192 * 1024 + 65536] = rt
    meta = bytearray(1024 * 1024)
    meta[0:8] = b'metadata'
    struct.pack_into('<H', meta, 10, 3)
    items = ((uuid.UUID('CAA16737-FA36-4D43-B3B6-33F0AA44E76B'), struct.pack('<II', block, 0)),
             (uuid.UUID('2FA54224-CD1B-4876-B211-5DBED83BF4B8'), struct.pack('<Q', size)),
             (uuid.UUID('8141BF1D-A96F-4709-BA47-F233A8FAAB5F'), struct.pack('<I', sector)))
    off = 65536
    for i, (g, val) in enumerate(items):
        meta[32 + i * 32:48 + i * 32] = g.bytes_le
        struct.pack_into('<II', meta, 48 + i * 32, off, len(val))
        meta[off:off + len(val)] = val
        off += 64
    out[2 * 1024 * 1024:3 * 1024 * 1024] = meta
    bat = [0] * nbat
    payload = bytearray()
    pos = 4 * 1024 * 1024
    for b in range(nblocks):
        chunk = raw[b * block:(b + 1) * block].ljust(block, b'\x00')
        if chunk.count(0) == len(chunk):
            continue
        bat[b + b // chunk_ratio] = ((pos >> 20) << 20) | 6
        payload += chunk
        pos += block
    batb = struct.pack('<%dQ' % nbat, *bat).ljust(1024 * 1024, b'\x00')
    out[3 * 1024 * 1024:4 * 1024 * 1024] = batb
    return bytes(out) + bytes(payload)


def build_vmdk_sparse(raw: bytes, grain_sectors=128, gtes=512) -> bytes:
    cap = -(-len(raw) // 512)
    grain = grain_sectors * 512
    ngrains = -(-len(raw) // grain)
    ngt = -(-ngrains // gtes)
    gd_sec = 2
    gts_sec = gd_sec + 1
    data_sec = gts_sec + ngt * (gtes * 4 // 512)
    gt = [[0] * gtes for _ in range(ngt)]
    payload = bytearray()
    pos = data_sec
    for g in range(ngrains):
        chunk = raw[g * grain:(g + 1) * grain].ljust(grain, b'\x00')
        if chunk.count(0) == len(chunk):
            continue
        gt[g // gtes][g % gtes] = pos
        payload += chunk
        pos += grain_sectors
    head = bytearray(512)
    head[0:4] = b'KDMV'
    struct.pack_into('<IIQQQQIQQQ', head, 4, 1, 3, cap, grain_sectors, 0, 0, gtes, 0, gd_sec, data_sec)
    gd = struct.pack('<%dI' % ngt, *[gts_sec + i * (gtes * 4 // 512) for i in range(ngt)]).ljust(512, b'\x00')
    gts = b''.join(struct.pack('<%dI' % gtes, *t) for t in gt)
    return bytes(head).ljust(512, b'\x00') + b'\x00' * 512 + gd + gts + bytes(payload)


class ContainerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        img, cls.truth = ntfs_image.build_image()
        cls.raw = bytes(img)

    def check(self, path):
        r = open_reader(path)
        try:
            self.assertEqual(r.size, len(self.raw))
            self.assertEqual(r.read_at(0, 8 * 1024 * 1024), self.raw)
            self.assertEqual(r.read_at(5000, 3000), self.raw[5000:8000])
            sink = Collector()
            ntfs.scan_volume(r, 0, sink, common.Progress('n', 0, sink), mode='deleted')
            f = [x for x in sink.files if x['name'] == 'photo.jpg'][0]
            self.assertEqual(read_extents(r, f), self.truth['photo.jpg'])
        finally:
            r.close()
            os.unlink(path)

    def test_vhd_dynamic(self):
        p = tmpfile(build_vhd_dynamic(self.raw))
        p2 = p + '.vhd'
        os.rename(p, p2)
        self.check(p2)

    def test_vhd_fixed(self):
        footer = bytearray(512)
        footer[0:8] = b'conectix'
        struct.pack_into('>QQ', footer, 40, len(self.raw), len(self.raw))
        struct.pack_into('>I', footer, 60, 2)
        p = tmpfile(self.raw + bytes(footer))
        os.rename(p, p + '.vhd')
        self.check(p + '.vhd')

    def test_vhdx(self):
        p = tmpfile(build_vhdx(self.raw))
        os.rename(p, p + '.vhdx')
        self.check(p + '.vhdx')

    def test_vmdk_sparse(self):
        p = tmpfile(build_vmdk_sparse(self.raw))
        os.rename(p, p + '.vmdk')
        self.check(p + '.vmdk')

    def test_split_files(self):
        d = tempfile.mkdtemp()
        third = len(self.raw) // 3
        for i, part in enumerate((self.raw[:third], self.raw[third:2 * third], self.raw[2 * third:]), start=1):
            open(os.path.join(d, f'disk.{i:03d}'), 'wb').write(part)
        r = open_reader(os.path.join(d, 'disk.001'))
        try:
            self.assertEqual(r.read_at(0, len(self.raw)), self.raw)
        finally:
            r.close()


# ---------------------------------------------------------------- RAID
def split_raid5(data: bytes, n: int, stripe: int, layout: str):
    """Fabrique les n membres d'un RAID 5 à partir des données logiques (même formules que le lecteur... vérifiées à part)."""
    members = [bytearray() for _ in range(n)]
    nchunks = -(-len(data) // stripe)
    rows = -(-nchunks // (n - 1))
    for row in range(rows):
        if layout in ('ls', 'la'):
            p = (n - 1) - (row % n)
        else:
            p = row % n
        parity = bytearray(stripe)
        for d in range(n - 1):
            chunk = data[(row * (n - 1) + d) * stripe:(row * (n - 1) + d + 1) * stripe].ljust(stripe, b'\x00')
            disk = (p + 1 + d) % n if layout in ('ls', 'rs') else (d if d < p else d + 1)
            members[disk] += chunk
            parity = bytearray(a ^ b for a, b in zip(parity, chunk))
        members[p] += parity
    return [bytes(m) for m in members]


def split_raid0(data: bytes, n: int, stripe: int):
    members = [bytearray() for _ in range(n)]
    for c in range(-(-len(data) // stripe)):
        members[c % n] += data[c * stripe:(c + 1) * stripe].ljust(stripe, b'\x00')
    return [bytes(m) for m in members]


class RaidTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        disk, _s1, _s2 = PartitionTest().make_disk()
        cls.disk = bytes(disk)
        cls.logical = cls.disk[:len(cls.disk) // (3 * 65536 * 2) * (3 * 65536 * 2)]

    def readers(self, parts, missing=None):
        out = []
        for i, p in enumerate(parts):
            out.append(None if i == missing else containers.VirtualReader.__new__(containers.VirtualReader) if False else raid.MemReader(p))
        return out

    def test_raid0(self):
        parts = split_raid0(self.logical, 3, 65536)
        r = raid.VirtualRaid([raid.MemReader(p) for p in parts], 'raid0', 65536)
        self.assertEqual(r.read_at(0, len(self.logical)), self.logical[:r.size])

    def test_raid5_all_layouts_and_degraded(self):
        for layout in raid.LAYOUTS:
            parts = split_raid5(self.logical, 3, 65536, layout)
            r = raid.VirtualRaid([raid.MemReader(p) for p in parts], 'raid5', 65536, layout)
            self.assertEqual(r.read_at(0, r.size), self.logical[:r.size], layout)
            for miss in range(3):               # disque manquant : reconstruction par XOR
                members = [None if i == miss else raid.MemReader(p) for i, p in enumerate(parts)]
                rd = raid.VirtualRaid(members, 'raid5', 65536, layout)
                self.assertEqual(rd.read_at(0, rd.size), self.logical[:rd.size], f'{layout} sans disque {miss}')

    def test_detection_of_parameters(self):
        parts = split_raid5(self.logical, 3, 65536, 'ls')
        order = [2, 0, 1]                        # disques fournis dans le désordre
        shuffled = [raid.MemReader(parts[i]) for i in order]
        cands = raid.detect(shuffled, cache_mb=4)
        self.assertTrue(cands, 'aucun candidat')
        # vérité terrain : disques fournis dans l'ordre [2,0,1] => ordre logique [1,2,0] ; plusieurs paramétrages peuvent
        # être indiscernables sur un volume presque vide (données creuses) : la bonne combinaison doit figurer parmi eux
        truth = {'level': 'raid5', 'stripe': 65536, 'layout': 'ls', 'order': [1, 2, 0], 'offset': 0}
        self.assertIn(truth, [{k: c[k] for k in truth} for c in cands])
        best = cands[0]['score']
        self.assertGreaterEqual(best, 900)

    def test_spec_string_with_real_files(self):
        parts = split_raid0(self.logical, 2, 32768)
        paths = [tmpfile(p) for p in parts]
        spec = 'raid:' + json.dumps({'level': 'raid0', 'stripe': 32768, 'members': paths})
        r = open_reader(spec)
        try:
            self.assertEqual(r.read_at(0, 1 << 20), self.logical[:1 << 20])
        finally:
            r.close()
            for p in paths:
                os.unlink(p)


if __name__ == '__main__':
    unittest.main()

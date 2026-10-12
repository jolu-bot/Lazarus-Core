"""Image ext synthétique (blocs de 1 Kio) : extents, blocs indirects, fichiers supprimés, noms cachés dans le slack."""
import struct

BS = 1024
BLOCKS = 4096
IPG = 64
ISZ = 128


def inode(mode, size, links=1, dtime=0, flags=0, iblock=b'', mtime=1700000000):
    b = bytearray(ISZ)
    struct.pack_into('<HHI', b, 0, mode, 0, size & 0xFFFFFFFF)
    struct.pack_into('<IIII', b, 8, mtime, mtime, mtime, dtime)
    struct.pack_into('<HH', b, 24, 0, links)
    struct.pack_into('<II', b, 28, 0, flags)
    b[40:40 + len(iblock)] = iblock
    struct.pack_into('<I', b, 108, size >> 32)
    return bytes(b)


def extent_block(entries, count_override=None):
    n = len(entries) if count_override is None else count_override
    out = struct.pack('<HHHHI', 0xF30A, n, 4, 0, 0)
    for lb, ln, phys in entries:
        out += struct.pack('<IHHI', lb, ln, phys >> 32, phys & 0xFFFFFFFF)
    return out.ljust(60, b'\x00')


def direct_block(ptrs, ind=0):
    p = list(ptrs) + [0] * (12 - len(ptrs))
    return struct.pack('<15I', *(p + [ind, 0, 0]))


def dirent(ino, name, ftype, rec_len):
    nm = name.encode()
    return (struct.pack('<IHBB', ino, rec_len, len(nm), ftype) + nm).ljust(rec_len, b'\x00')


def dir_block(entries_with_hidden):
    """entries: [(ino,name,ftype)] ; hidden: entrée supprimée glissée dans le slack de la dernière."""
    entries, hidden = entries_with_hidden
    out = b''
    for i, (ino, name, ft) in enumerate(entries):
        real = (8 + len(name) + 3) & ~3
        if i == len(entries) - 1:
            rec = BS - len(out)
            blk = struct.pack('<IHBB', ino, rec, len(name), ft) + name.encode()
            blk = blk.ljust(real, b'\x00')
            if hidden:
                h_ino, h_name, h_ft = hidden
                h_rec = rec - real
                blk += struct.pack('<IHBB', h_ino, h_rec, len(h_name), h_ft) + h_name.encode()
            out += blk.ljust(rec, b'\x00')
        else:
            out += dirent(ino, name, ft, real)
    return out


def pat(n, seed):
    return bytes((seed * 17 + i * 3 + (i >> 8)) & 0xFF for i in range(n))


def build_ext():
    img = bytearray(BLOCKS * BS)
    truth = {}

    def put(block, data):
        img[block * BS:block * BS + len(data)] = data

    # superbloc
    sb = bytearray(1024)
    struct.pack_into('<II', sb, 0, IPG, BLOCKS)
    struct.pack_into('<I', sb, 20, 1)
    struct.pack_into('<I', sb, 24, 0)
    struct.pack_into('<I', sb, 32, 8192)
    struct.pack_into('<I', sb, 40, IPG)
    struct.pack_into('<H', sb, 56, 0xEF53)
    struct.pack_into('<I', sb, 76, 1)
    struct.pack_into('<H', sb, 88, ISZ)
    struct.pack_into('<I', sb, 96, 0x42)           # filetype | extents
    img[1024:2048] = sb
    # descripteur de groupe
    gd = struct.pack('<III', 3, 4, 5).ljust(32, b'\x00')
    put(2, gd)

    inodes = {}
    # racine
    put(13, dir_block(([(2, '.', 2), (2, '..', 2), (12, 'docs', 2)], (14, 'gone.txt', 1))))
    inodes[2] = inode(0x41ED, BS, 3, iblock=direct_block([13]))
    # docs
    put(14, dir_block(([(12, '.', 2), (2, '..', 2), (13, 'live.txt', 1)], (15, 'deleted.jpg', 1))))
    inodes[12] = inode(0x41ED, BS, 2, iblock=direct_block([14]))
    # live.txt (extents, blocs 20-21)
    d1 = pat(2000, 1)
    put(20, d1)
    inodes[13] = inode(0x81A4, 2000, 1, flags=0x80000, iblock=extent_block([(0, 2, 20)]))
    truth['live.txt'] = d1
    # gone.txt : supprimé, header d'extents avec 0 entrée mais entrée intacte, blocs 30-31
    d2 = pat(1500, 2)
    put(30, d2)
    inodes[14] = inode(0x81A4, 1500, 0, dtime=1700001000, flags=0x80000, iblock=extent_block([(0, 2, 30)], count_override=0))
    truth['gone.txt'] = d2
    # deleted.jpg : bloc indirect (ext2), 12 directs (33..44) + indirect(45)->[46,47]
    d3 = pat(14 * BS, 3)
    blocks = list(range(33, 45)) + [46, 47]
    for i, b in enumerate(blocks):
        put(b, d3[i * BS:(i + 1) * BS])
    put(45, struct.pack('<2I', 46, 47))
    inodes[15] = inode(0x81A4, 14 * BS, 0, dtime=1700002000, flags=0, iblock=direct_block(blocks[:12], ind=45))
    truth['deleted.jpg'] = d3

    for ino, raw in inodes.items():
        off = 5 * BS + (ino - 1) * ISZ
        img[off:off + ISZ] = raw
    # bitmaps
    bbm = bytearray(1024)
    used = set(range(1, 13)) | {13, 14, 20, 21, 33}      # 33 réalloué -> écrasement partiel de deleted.jpg
    for b in used:
        bbm[(b - 1) >> 3] |= 1 << ((b - 1) & 7)
    put(3, bytes(bbm))
    ibm = bytearray(1024)
    for i in range(1, 14):
        ibm[(i - 1) >> 3] |= 1 << ((i - 1) & 7)
    put(4, bytes(ibm))
    return img, truth

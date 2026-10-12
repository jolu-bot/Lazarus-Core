"""Fabrique des images FAT16/FAT32/exFAT synthétiques."""
import struct

from engine.fat import lfn_checksum  # noqa: E402


def dos_dt(epoch_like=(2024, 5, 17, 10, 30, 22)):
    y, mo, d, h, mi, s = epoch_like
    return ((y - 1980) << 9) | (mo << 5) | d, (h << 11) | (mi << 5) | (s // 2)


def short_entry(name83: bytes, attr, cluster, size, deleted=False):
    d, t = dos_dt()
    e = bytearray(32)
    e[0:11] = name83
    e[11] = attr
    struct.pack_into('<H', e, 20, cluster >> 16)
    struct.pack_into('<HH', e, 22, t, d)
    struct.pack_into('<H', e, 26, cluster & 0xFFFF)
    struct.pack_into('<I', e, 28, size)
    if deleted:
        e[0] = 0xE5
    return bytes(e)


def lfn_entries(long_name: str, short83: bytes, deleted=False):
    chk = lfn_checksum(short83)
    units = long_name.encode('utf-16le') + b'\x00\x00'
    units += b'\xff\xff' * ((-len(units) // 2) % 13)
    chunks = [units[i:i + 26] for i in range(0, len(units), 26)]
    out = []
    for idx, ch in enumerate(chunks, start=1):
        e = bytearray(32)
        e[0] = idx | (0x40 if idx == len(chunks) else 0)
        e[1:11] = ch[0:10]
        e[11] = 0x0F
        e[13] = chk
        e[14:26] = ch[10:22]
        e[28:32] = ch[22:26]
        if deleted:
            e[0] = 0xE5
        out.append(bytes(e))
    return list(reversed(out))


def pat(n, seed):
    return bytes((seed * 31 + i * 5 + (i >> 7)) & 0xFF for i in range(n))


def build_fat(variant='fat16'):
    bps, spc = 512, 1
    if variant == 'fat16':
        total_clusters = 8192
        reserved, root_entries, fat_sectors = 1, 512, 32
        nfats = 2
    else:
        total_clusters = 66000
        reserved, root_entries, fat_sectors = 32, 0, (66000 + 2) * 4 // 512 + 1
        nfats = 2
    root_sectors = root_entries * 32 // bps
    total_sectors = reserved + nfats * fat_sectors + root_sectors + total_clusters * spc
    img = bytearray(total_sectors * bps)
    b = bytearray(512)
    b[0:3] = b'\xeb\x3c\x90'
    b[3:11] = b'MSDOS5.0'
    struct.pack_into('<HBHBHHBHHHII', b, 11, bps, spc, reserved, nfats, root_entries,
                     total_sectors if (variant == 'fat16' and total_sectors < 65536) else 0, 0xF8,
                     fat_sectors if variant == 'fat16' else 0, 32, 64, 0,
                     0 if (variant == 'fat16' and total_sectors < 65536) else total_sectors)
    if variant == 'fat16':
        b[54:62] = b'FAT16   '
    else:
        struct.pack_into('<IHHI', b, 36, fat_sectors, 0, 0, 2)
        b[82:90] = b'FAT32   '
    b[510:512] = b'\x55\xaa'
    img[0:512] = b

    fat_off = reserved * bps
    data_off = (reserved + nfats * fat_sectors + root_sectors) * bps
    root_off = (reserved + nfats * fat_sectors) * bps
    fat = {}

    def fat_set(c, v):
        fat[c] = v

    next_free = [3 if variant == 'fat32' else 2]
    if variant == 'fat32':
        fat_set(2, 0x0FFFFFFF)       # cluster racine

    def alloc(n):
        cl = list(range(next_free[0], next_free[0] + n))
        next_free[0] += n
        return cl

    def coff(c):
        return data_off + (c - 2) * bps

    EOC = 0xFFFF if variant == 'fat16' else 0x0FFFFFFF

    def write_file(data, chain_free=False, clusters=None):
        n = -(-len(data) // bps)
        cl = clusters or alloc(n)
        for i, c in enumerate(cl):
            chunk = data[i * bps:(i + 1) * bps]
            img[coff(c):coff(c) + len(chunk)] = chunk
        if not chain_free:
            for a, c in zip(cl, cl[1:] + [None]):
                fat_set(a, c if c else EOC)
        return cl

    truth = {}
    root_entries_list = []

    # fichier existant, contigu
    d1 = pat(1300, 1)
    cl = write_file(d1)
    root_entries_list.append(short_entry(b'README  TXT', 0x20, cl[0], len(d1)))
    truth['README.TXT'] = d1

    # fichier existant, fragmenté (clusters non contigus)
    d2 = pat(3 * bps, 2)
    a = alloc(2)
    alloc(5)
    b2 = alloc(1)
    cl = write_file(d2, clusters=a + b2)
    root_entries_list.append(short_entry(b'FRAG    BIN', 0x20, cl[0], len(d2)))
    truth['FRAG.BIN'] = d2

    # fichier supprimé avec nom long
    d3 = pat(2500, 3)
    cl = write_file(d3, chain_free=True)
    short = b'MYLONG~1DOC'
    root_entries_list += lfn_entries('Mon Rapport Final.docx', short, deleted=True)
    root_entries_list.append(short_entry(short, 0x20, cl[0], len(d3), deleted=True))
    truth['Mon Rapport Final.docx'] = d3

    # dossier supprimé contenant un fichier
    d4 = pat(900, 4)
    dir_cl = alloc(1)[0]
    fcl = write_file(d4, chain_free=True)
    dirdata = bytearray(bps)
    dirdata[0:32] = short_entry(b'.          ', 0x10, dir_cl, 0)
    dirdata[32:64] = short_entry(b'..         ', 0x10, 0 if variant == 'fat16' else 2, 0)
    dirdata[64:96] = short_entry(b'INNER   TXT', 0x20, fcl[0], len(d4), deleted=True)
    img[coff(dir_cl):coff(dir_cl) + bps] = dirdata
    root_entries_list.append(short_entry(b'OLD        ', 0x10, dir_cl, 0, deleted=True))
    truth['INNER.TXT'] = d4

    # fichier supprimé dont un cluster a été réalloué
    d5 = pat(3 * bps, 5)
    cl5 = write_file(d5, chain_free=True)
    fat_set(cl5[1], EOC)          # cluster du milieu réutilisé
    root_entries_list.append(short_entry(b'LOST    DAT', 0x20, cl5[0], len(d5), deleted=True))
    truth['LOST.DAT'] = d5

    rootdata = b''.join(root_entries_list)
    if variant == 'fat16':
        img[root_off:root_off + len(rootdata)] = rootdata
    else:
        img[coff(2):coff(2) + len(rootdata)] = rootdata

    # écrit la FAT (2 copies)
    entry = 2 if variant == 'fat16' else 4
    for k in range(nfats):
        for c, v in fat.items():
            struct.pack_into('<H' if entry == 2 else '<I', img, fat_off + k * fat_sectors * bps + c * entry, v)
    return img, truth


def build_exfat():
    bps_shift, spc_shift = 9, 0
    bps, cs = 512, 512
    clusters = 4096
    fat_off_s, fat_len_s = 24, 40
    heap_off_s = 64
    total_sectors = heap_off_s + clusters
    img = bytearray(total_sectors * bps)
    b = bytearray(512)
    b[0:3] = b'\xeb\x76\x90'
    b[3:11] = b'EXFAT   '
    struct.pack_into('<Q', b, 72, total_sectors)
    struct.pack_into('<IIII', b, 80, fat_off_s, fat_len_s, heap_off_s, clusters)
    struct.pack_into('<I', b, 96, 5)           # cluster racine
    b[108], b[109], b[110] = bps_shift, spc_shift, 1
    b[510:512] = b'\x55\xaa'
    img[0:512] = b

    def coff(c):
        return (heap_off_s + c - 2) * bps

    fat = {}
    bitmap = bytearray(clusters // 8)

    def mark(c):
        bitmap[(c - 2) >> 3] |= 1 << ((c - 2) & 7)

    nxt = [6]

    def alloc(n):
        cl = list(range(nxt[0], nxt[0] + n))
        nxt[0] += n
        return cl

    def entry_set(name, attr, first, size, nofat, deleted):
        units = name.encode('utf-16le')
        parts = [units[i:i + 30] for i in range(0, len(units), 30)] or [b'']
        sec = 1 + len(parts)
        d, t = dos_dt()
        a = bytearray(32)
        a[0] = 0x05 if deleted else 0x85
        a[1] = sec
        struct.pack_into('<H', a, 4, attr)
        struct.pack_into('<I', a, 12, (d << 16) | t)
        s = bytearray(32)
        s[0] = 0x40 if deleted else 0xC0
        s[1] = 0x01 | (0x02 if nofat else 0)
        s[3] = len(name)
        struct.pack_into('<Q', s, 8, size)
        struct.pack_into('<I', s, 20, first)
        struct.pack_into('<Q', s, 24, size)
        out = bytes(a) + bytes(s)
        for p in parts:
            n = bytearray(32)
            n[0] = 0x41 if deleted else 0xC1
            n[2:2 + len(p)] = p
            out += bytes(n)
        return out

    truth = {}
    root = bytearray()
    # bitmap d'allocation (cluster 2) - 512 octets = 1 cluster
    bm_cl = 2
    ent = bytearray(32)
    ent[0] = 0x81
    struct.pack_into('<I', ent, 20, bm_cl)
    struct.pack_into('<Q', ent, 24, len(bitmap))
    root += ent
    for c in (2, 3, 4, 5):
        mark(c)
    fat[2] = 0xFFFFFFFF
    fat[5] = 0xFFFFFFFF

    # fichier existant contigu (NoFatChain)
    d1 = bytes((i * 3) & 0xFF for i in range(1500))
    cl = alloc(3)
    for i, c in enumerate(cl):
        img[coff(c):coff(c) + 512] = d1[i * 512:(i + 1) * 512].ljust(512, b'\x00')
        mark(c)
    root += entry_set('present.bin', 0x20, cl[0], len(d1), True, False)
    truth['present.bin'] = d1

    # fichier supprimé (clusters libres)
    d2 = bytes((i * 11 + 5) & 0xFF for i in range(2000))
    cl = alloc(4)
    for i, c in enumerate(cl):
        img[coff(c):coff(c) + 512] = d2[i * 512:(i + 1) * 512].ljust(512, b'\x00')
    root += entry_set('Photo déjà supprimée.jpg', 0x20, cl[0], len(d2), True, True)
    truth['Photo déjà supprimée.jpg'] = d2

    # fichier supprimé dont les clusters sont réalloués
    d3 = bytes((i * 13 + 1) & 0xFF for i in range(1024))
    cl = alloc(2)
    for i, c in enumerate(cl):
        img[coff(c):coff(c) + 512] = d3[i * 512:(i + 1) * 512]
        mark(c)
    root += entry_set('ecrase.dat', 0x20, cl[0], len(d3), True, True)
    img[coff(5):coff(5) + len(root)] = root
    # bitmap
    img[coff(bm_cl):coff(bm_cl) + len(bitmap)] = bitmap
    for c, v in fat.items():
        struct.pack_into('<I', img, fat_off_s * bps + c * 4, v)
    return img, truth

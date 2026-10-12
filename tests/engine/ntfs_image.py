"""Fabrique une petite image NTFS synthétique pour tester le moteur sans disque réel."""
import struct

CS = 4096          # taille de cluster
REC = 1024         # taille de record MFT
TOTAL_CLUSTERS = 2048


def pad8(b: bytes) -> bytes:
    return b + b'\x00' * (-len(b) % 8)


def runs_bytes(runs):
    """runs: [(lcn|None, length)] -> octets de mapping pairs (deltas signés)."""
    out = bytearray()
    prev = 0
    for lcn, ln in runs:
        ls = max(1, (ln.bit_length() + 7) // 8)
        if lcn is None:
            out.append(ls)
            out += ln.to_bytes(ls, 'little')
            continue
        delta = lcn - prev
        prev = lcn
        os_ = 1
        while True:
            try:
                d = delta.to_bytes(os_, 'little', signed=True)
                break
            except OverflowError:
                os_ += 1
        out.append((os_ << 4) | ls)
        out += ln.to_bytes(ls, 'little') + d
    out.append(0)
    return bytes(out)


def attr_resident(atype, value, name=b'', flags=0, aid=0):
    nm_p = pad8(name)
    hdr = struct.pack('<IIBBHHH', atype, 0, 0, len(name) // 2, 24 if name else 0, flags, aid)
    hdr += struct.pack('<IHBB', len(value), 24 + len(nm_p), 0, 0)
    body = pad8(hdr + nm_p + value)
    return struct.pack('<II', atype, len(body)) + body[8:]


def attr_nonres(atype, runs, svcn, evcn, alloc, real, init=None, flags=0, comp_unit=0, aid=0):
    rb = pad8(runs_bytes(runs))
    hdr = struct.pack('<IIBBHHH', atype, 0, 1, 0, 64, flags, aid)
    hdr += struct.pack('<QQHH4xQQQ', svcn, evcn, 64, comp_unit, alloc, real, real if init is None else init)
    out = hdr + rb
    return struct.pack('<II', atype, len(out)) + out[8:]


def filetime(epoch):
    return (epoch * 10000000) + 116444736000000000


def std_info(mtime=1700000000):
    ft = filetime(mtime)
    return attr_resident(0x10, struct.pack('<QQQQI', ft, ft, ft, ft, 0) + b'\x00' * 20)


def file_name(name, parent, parent_seq=1, is_dir=False, ns=1):
    nm = name.encode('utf-16le')
    v = struct.pack('<Q', parent | (parent_seq << 48))
    v += struct.pack('<QQQQ', 0, 0, 0, 0)
    v += struct.pack('<QQ', 0, 0)
    v += struct.pack('<II', 0x10000000 if is_dir else 0x20, 0)
    v += struct.pack('<BB', len(name), ns) + nm
    return attr_resident(0x30, v)


def make_record(idx, attrs, flags, seq=1, base=0):
    body = b''.join(attrs) + struct.pack('<I', 0xFFFFFFFF) + b'\x00' * 4
    usa_cnt = REC // 512 + 1
    first = 0x38
    used = first + len(body)
    rec = bytearray(REC)
    rec[0:4] = b'FILE'
    struct.pack_into('<HH', rec, 4, 0x30, usa_cnt)
    struct.pack_into('<Q', rec, 8, 0)
    struct.pack_into('<HH', rec, 16, seq, 1)
    struct.pack_into('<HHII', rec, 20, first, flags, used, REC)
    struct.pack_into('<Q', rec, 32, base)
    struct.pack_into('<HH', rec, 40, 7, 0)
    struct.pack_into('<I', rec, 44, idx)
    rec[first:first + len(body)] = body
    usn = b'\x05\x00'
    rec[0x30:0x32] = usn
    for i in range(1, usa_cnt):
        tail = i * 512 - 2
        rec[0x30 + i * 2:0x30 + i * 2 + 2] = rec[tail:tail + 2]
        rec[tail:tail + 2] = usn
    return bytes(rec)


def pattern(n, seed):
    return bytes((seed + i * 7 + (i >> 8)) & 0xFF for i in range(n))


def build_image():
    """Retourne (image: bytearray, vérité: dict)."""
    img = bytearray(TOTAL_CLUSTERS * CS)
    boot = bytearray(512)
    boot[0:3] = b'\xeb\x52\x90'
    boot[3:11] = b'NTFS    '
    struct.pack_into('<HBH', boot, 11, 512, 8, 0)
    boot[21] = 0xF8
    struct.pack_into('<Q', boot, 40, TOTAL_CLUSTERS * 8 - 1)
    struct.pack_into('<QQ', boot, 48, 4, 100)   # $MFT lcn 4, $MFTMirr lcn 100
    struct.pack_into('<b', boot, 64, -10)
    struct.pack_into('<b', boot, 68, 1)
    boot[510:512] = b'\x55\xaa'
    img[0:512] = boot
    img[len(img) - 512:] = boot        # secteur de démarrage de secours (dernier secteur du volume)

    truth = {}
    mft_lcn, mft_clusters = 4, 16          # 64 records
    recs = {}

    def put_clusters(lcn, data):
        img[lcn * CS:lcn * CS + len(data)] = data

    used_clusters = set(range(0, 20)) | {100}

    # $MFT
    recs[0] = make_record(0, [std_info(), file_name('$MFT', 5, is_dir=False),
                              attr_nonres(0x80, [(mft_lcn, mft_clusters)], 0, mft_clusters - 1,
                                          mft_clusters * CS, mft_clusters * CS)], 1)
    # répertoire racine
    recs[5] = make_record(5, [std_info(), file_name('.', 5, is_dir=True)], 3)
    # dossier Docs
    recs[24] = make_record(24, [std_info(), file_name('Docs', 5, is_dir=True)], 3)
    # fichier résident actif
    txt = b'Bonjour Lazarus, ceci est un petit fichier residant.'
    recs[25] = make_record(25, [std_info(), file_name('hello.txt', 24), attr_resident(0x80, txt)], 1)
    truth['hello.txt'] = txt

    # photo.jpg : supprimé, 2 fragments (lcn 20 x3 puis lcn 40 x2)
    size = 5 * CS - 100
    data = pattern(size, 3)
    put_clusters(20, data[:3 * CS])
    put_clusters(40, data[3 * CS:].ljust(2 * CS, b'\x00'))
    recs[26] = make_record(26, [std_info(), file_name('photo.jpg', 24),
                                attr_nonres(0x80, [(20, 3), (40, 2)], 0, 4, 5 * CS, size)], 0)
    truth['photo.jpg'] = data

    # big.bin : supprimé, mais ses clusters ont été réalloués (50..53 marqués utilisés)
    data2 = pattern(4 * CS, 9)
    put_clusters(50, data2)
    used_clusters |= {50, 51, 52, 53}
    recs[27] = make_record(27, [std_info(), file_name('big.bin', 24),
                                attr_nonres(0x80, [(50, 4)], 0, 3, 4 * CS, 4 * CS)], 0)
    truth['big.bin'] = data2

    # sparse.dat : 1 cluster de données, 2 clusters creux, 1 cluster de données
    d3a, d3b = pattern(CS, 1), pattern(CS, 2)
    put_clusters(60, d3a)
    put_clusters(61, d3b)
    recs[28] = make_record(28, [std_info(), file_name('sparse.dat', 24),
                                attr_nonres(0x80, [(60, 1), (None, 2), (61, 1)], 0, 3, 4 * CS, 4 * CS,
                                            flags=0x8000)], 0)
    truth['sparse.dat'] = d3a + b'\x00' * (2 * CS) + d3b

    # fragmenté avec $ATTRIBUTE_LIST : base 30, extension 31
    d4 = pattern(4 * CS - 10, 5)
    put_clusters(70, d4[:2 * CS])
    put_clusters(80, d4[2 * CS:].ljust(2 * CS, b'\x00'))
    al = b''
    for atype, ref, svcn in ((0x10, 30, 0), (0x30, 30, 0), (0x80, 30, 0), (0x80, 31, 2)):
        ent = struct.pack('<IHBBQQHBB', atype, 32, 0, 26, svcn, ref | (1 << 48), 0, 0, 0)
        al += ent.ljust(32, b'\x00')
    recs[30] = make_record(30, [std_info(), attr_resident(0x20, al), file_name('frag.dat', 24),
                                attr_nonres(0x80, [(70, 2)], 0, 1, 4 * CS, 4 * CS - 10)], 0)
    recs[31] = make_record(31, [attr_nonres(0x80, [(80, 2)], 2, 3, 0, 0)], 0, base=30 | (1 << 48))
    truth['frag.dat'] = d4

    # corbeille
    recs[32] = make_record(32, [std_info(), file_name('$Recycle.Bin', 5, is_dir=True)], 3)
    recs[33] = make_record(33, [std_info(), file_name('S-1-5-21-1', 32, is_dir=True)], 3)
    rtxt = b'contenu du fichier dans la corbeille'
    recs[34] = make_record(34, [std_info(), file_name('$R1ABC.txt', 33), attr_resident(0x80, rtxt)], 1)
    orig = 'C:\\Users\\Moi\\Documents\\rapport.txt'
    i_data = struct.pack('<QQQI', 2, len(rtxt), filetime(1700000500), len(orig) + 1) + (orig + '\x00').encode('utf-16le')
    recs[35] = make_record(35, [std_info(), file_name('$I1ABC.txt', 33), attr_resident(0x80, i_data)], 1)
    truth['$R1ABC.txt'] = rtxt

    # $Bitmap
    bm = bytearray(TOTAL_CLUSTERS // 8)
    for c in used_clusters:
        bm[c >> 3] |= 1 << (c & 7)
    put_clusters(90, bytes(bm))
    recs[6] = make_record(6, [std_info(), file_name('$Bitmap', 5),
                              attr_nonres(0x80, [(90, 1)], 0, 0, CS, len(bm))], 1)

    for idx, r in recs.items():
        off = mft_lcn * CS + idx * REC
        img[off:off + REC] = r
    # copie de secours des 4 premiers records
    for idx in range(4):
        if idx in recs:
            off = 100 * CS + idx * REC
            img[off:off + REC] = recs[idx]
    return img, truth

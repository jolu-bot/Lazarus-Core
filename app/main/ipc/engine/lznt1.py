"""Décompression LZNT1 (fichiers NTFS compressés)."""
from __future__ import annotations

import struct


def decompress(data: bytes, max_out: int = 0) -> bytes:
    out = bytearray()
    pos = 0
    n = len(data)
    while pos + 2 <= n:
        hdr = struct.unpack_from('<H', data, pos)[0]
        if hdr == 0:
            break
        size = (hdr & 0x0FFF) + 1          # octets de données dans ce chunk
        compressed = bool(hdr & 0x8000)
        pos += 2
        chunk = data[pos:pos + size]
        pos += size
        if not compressed:
            out += chunk
        else:
            start = len(out)
            i = 0
            cl = len(chunk)
            while i < cl:
                flags = chunk[i]
                i += 1
                for bit in range(8):
                    if i >= cl:
                        break
                    if not (flags >> bit) & 1:
                        out.append(chunk[i])
                        i += 1
                        continue
                    if i + 2 > cl:
                        i = cl
                        break
                    tok = chunk[i] | (chunk[i + 1] << 8)
                    i += 2
                    cur = len(out) - start
                    lg = 0
                    t = cur - 1
                    while t >= 0x10:
                        t >>= 1
                        lg += 1
                    length = (tok & (0xFFF >> lg)) + 3
                    off = (tok >> (12 - lg)) + 1
                    if off > len(out) - start:
                        i = cl
                        break
                    src = len(out) - off
                    for k in range(length):
                        out.append(out[src + k])
        if max_out and len(out) >= max_out:
            break
    return bytes(out)

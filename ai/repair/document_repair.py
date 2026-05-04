from __future__ import annotations
import io, re, struct, zipfile
from typing import Optional


def repair_document_bytes(data: bytes, ext: str = "") -> Optional[bytes]:
    if data[:4] == b'PK': return repair_zip_doc(data)
    if data[:4] == b'%PDF':       return repair_pdf(data)
    return None


def repair_zip_doc(data: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(data), 'r') as _: return data
    except Exception: pass
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:
        pos = 0
        while pos < len(data)-30:
            if data[pos:pos+4] != b'PK': pos += 1; continue
            try:
                fl  = struct.unpack_from('<H', data, pos+26)[0]
                el  = struct.unpack_from('<H', data, pos+28)[0]
                fname = data[pos+30:pos+30+fl].decode('utf-8', errors='replace')
                csz = struct.unpack_from('<I', data, pos+18)[0]
                cm  = struct.unpack_from('<H', data, pos+8)[0]
                ds  = pos+30+fl+el; de = ds+csz
                if de > len(data): pos += 4; continue
                if cm == 8:
                    import zlib
                    try: raw = zlib.decompress(data[ds:de], -15)
                    except zlib.error: pos = de; continue
                elif cm == 0: raw = data[ds:de]
                else: pos = de; continue
                zout.writestr(fname, raw); pos = de
            except Exception: pos += 4
    res = out.getvalue()
    return res if len(res) > 22 else data


def repair_pdf(data: bytes) -> bytes:
    start = data.find(b'%PDF-')
    if start < 0: return data
    data = data[start:]
    out  = bytearray()
    vend = data.find(b'\n', 0)
    if vend < 0: vend = 8
    out.extend(data[:vend+1])
    out.extend(b'%\xe2\xe3\xcf\xd3\n')
    xref = {}
    pat  = re.compile(rb'(\d+)\s+\d+\s+obj\b')
    pos  = vend+1
    while pos < len(data):
        m = pat.search(data, pos)
        if not m: break
        oid = int(m.group(1))
        end = data.find(b'endobj', m.start())
        if end < 0: break
        ep = end+6
        while ep < len(data) and data[ep:ep+1] in (b'\n', b'\r', b' '): ep += 1
        xref[oid] = len(out)
        out.extend(data[m.start():ep]); out.extend(b'\n')
        pos = ep
    if not xref: return data
    xoff = len(out); mx = max(xref.keys())
    out.extend(b'xref\n')
    out.extend(f'0 {mx+2}\n'.encode())
    out.extend(b'0000000000 65535 f \n')
    for i in range(1, mx+2):
        off = xref.get(i, 0); iu = 'n' if i in xref else 'f'
        out.extend(f'{off:010d} 00000 {iu} \n'.encode())
    root_id = min(xref.keys())
    out.extend(b'trailer\n')
    out.extend(f'<< /Size {mx+2} /Root {root_id} 0 R >>\n'.encode())
    out.extend(b'startxref\n')
    out.extend(f'{xoff}\n'.encode())
    out.extend(b'%%%%EOF\n')
    return bytes(out)

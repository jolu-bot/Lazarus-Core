from __future__ import annotations
import struct
from typing import Optional

_MPEG1_BR = [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320,0]
_MPEG2_BR = [0,8,16,24,32,40,48,56,64,80,96,112,128,144,160,0]
_SR = {3:[44100,48000,32000],2:[22050,24000,16000],0:[11025,12000,8000]}


def repair_audio_bytes(data: bytes, filename: str = "") -> Optional[bytes]:
    if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
        return repair_wav(data)
    if data[:3] == b'ID3' or (len(data)>1 and data[0]==0xFF and (data[1]&0xE0)==0xE0):
        return repair_mp3(data)
    return None


def repair_wav(data: bytes) -> bytes:
    if len(data) < 44: return data
    try:
        arr = bytearray(data)
        struct.pack_into('<I', arr, 4, len(arr)-8)
        fmt = _find_chunk(data, b'fmt ')
        if fmt < 0: return bytes(arr)
        channels = struct.unpack_from('<H', data, fmt+10)[0]
        bit_depth = struct.unpack_from('<H', data, fmt+22)[0]
        bps = max(1, bit_depth//8)
        dc = _find_chunk(data, b'data')
        if dc < 0: return bytes(arr)
        astart = dc+8
        aend = min(astart+struct.unpack_from('<I',data,dc+4)[0], len(data))
        struct.pack_into('<I', arr, dc+4, aend-astart)
        block = bps*channels
        if block >= 2:
            ab = bytearray(arr[astart:aend])
            _interp_silent(ab, block)
            arr[astart:aend] = ab
        return bytes(arr)
    except Exception: return data


def _find_chunk(data: bytes, tag: bytes) -> int:
    pos = 12
    while pos < len(data)-8:
        if data[pos:pos+4] == tag: return pos
        sz = struct.unpack_from('<I', data, pos+4)[0]
        pos += 8+sz+(sz&1)
    return -1


def _interp_silent(buf: bytearray, block: int, thr: int = 8) -> None:
    n = len(buf)//block
    if n < 3: return
    i = 0
    while i < n-1:
        try: val = abs(struct.unpack_from('<h', buf, i*block)[0])
        except struct.error: break
        if val < thr:
            j = i+1
            while j < n:
                try:
                    if abs(struct.unpack_from('<h', buf, j*block)[0]) >= thr: break
                except struct.error: break
                j += 1
            if i > 0 and j < n:
                run = j-i
                for k in range(run):
                    t = (k+1)/(run+1)
                    for b in range(block):
                        prev = buf[(i-1)*block+b]
                        nxt = buf[j*block+b]
                        buf[(i+k)*block+b] = int(prev+(nxt-prev)*t)&0xFF
            i = j
        else: i += 1


def repair_mp3(data: bytes) -> bytes:
    out = bytearray()
    pos = 0
    if data[:3] == b'ID3' and len(data) > 10:
        sz = ((data[6]&0x7F)<<21|(data[7]&0x7F)<<14|(data[8]&0x7F)<<7|(data[9]&0x7F))
        total = sz+10+(10 if data[5]&0x10 else 0)
        out.extend(data[:total])
        pos = total
    frames = 0
    while pos < len(data)-3:
        b0,b1 = data[pos],data[pos+1]
        if b0 != 0xFF or (b1&0xE0) != 0xE0: pos += 1; continue
        vb = (b1>>3)&3; lb = (b1>>1)&3
        b2 = data[pos+2]
        bi = (b2>>4)&0xF; si = (b2>>2)&3
        if bi in (0,15): pos += 1; continue
        rates = _MPEG1_BR if vb==3 else _MPEG2_BR
        br = rates[bi]*1000
        srl = _SR.get(vb,[44100,48000,32000])
        if si >= len(srl) or srl[si]==0: pos += 1; continue
        sr = srl[si]; pad = (b2>>1)&1
        fsz = (12*br//sr+pad)*4 if lb==3 else 144*br//sr+pad
        if fsz < 4 or pos+fsz > len(data): pos += 1; continue
        out.extend(data[pos:pos+fsz])
        pos += fsz; frames += 1
    return bytes(out) if frames > 0 else data

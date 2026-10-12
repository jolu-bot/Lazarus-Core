"""Imagerie disque tolérante aux secteurs défectueux (stratégie ddrescue simplifiée en 2 passes)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from typing import Callable, List, Optional, Tuple

from .common import emit, log
from .devio import DeviceError, Reader, open_reader

MB = 1024 * 1024


def image_disk(device: str, out_path: str, start: int = 0, length: Optional[int] = None,
               stop_flag: Optional[Callable[[], bool]] = None, hash_output: bool = True) -> dict:
    t0 = time.time()
    try:
        rd = open_reader(device)
    except DeviceError as e:
        return {'success': False, 'message': str(e)}
    ss = rd.sector_size
    total = rd.size or 0
    if length is None:
        length = max(0, total - start)
    if not length:
        rd.close()
        return {'success': False, 'message': "Taille du périphérique inconnue : indiquez la longueur à copier"}
    start -= start % ss
    out_dir = os.path.dirname(os.path.abspath(out_path)) or '.'
    os.makedirs(out_dir, exist_ok=True)
    map_path = out_path + '.lazmap.json'

    # reprise éventuelle
    done = 0
    retry: List[List[int]] = []
    bad: List[int] = []
    phase = 1
    if os.path.exists(out_path) and os.path.exists(map_path):
        try:
            m = json.load(open(map_path, encoding='utf-8'))
            if m.get('device') == rd.path and m.get('start') == start and m.get('length') == length:
                done = int(m.get('done', 0))
                retry = m.get('retry', [])
                bad = m.get('bad', [])
                phase = int(m.get('phase', 1))
                log(f'Reprise de l\'image à {done} octets (phase {phase})')
        except (OSError, ValueError):
            pass
    if done == 0 and os.path.exists(out_path):
        os.remove(out_path)
    try:
        need = length - done
        if shutil.disk_usage(out_dir).free < need + 64 * MB:
            rd.close()
            return {'success': False, 'message': "Espace insuffisant sur la destination de l'image"}
    except OSError:
        pass

    mode = 'r+b' if os.path.exists(out_path) else 'w+b'
    fh = open(out_path, mode)
    last_save = [time.time()]
    last_emit = [0.0]

    def save_map(complete=False, extra=None):
        data = {'device': rd.path, 'start': start, 'length': length, 'sectorSize': ss, 'done': done, 'phase': phase,
                'retry': retry, 'bad': bad[:200000], 'badCount': len(bad), 'complete': complete}
        if extra:
            data.update(extra)
        tmp = map_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        os.replace(tmp, map_path)

    def progress(pos, label):
        now = time.time()
        if now - last_emit[0] < 0.25:
            return
        last_emit[0] = now
        el = max(now - t0, 0.001)
        speed = (pos - 0) / el
        emit('progress', {'percent': round(min(99.0, pos * 100.0 / length), 1), 'finished': False, 'engine': 'imager',
                          'currentPath': label, 'bytesDone': pos, 'bytesTotal': length,
                          'sectorsScanned': pos // 512, 'sectorsTotal': length // 512, 'speed': round(speed),
                          'badSectors': len(bad), 'filesFound': 0})

    stopped = False
    try:
        # ---------------- passe 1 : copie rapide, blocs défectueux mis de côté
        if phase == 1:
            block = MB
            consecutive = 0
            fh.seek(done)
            while done < length:
                if stop_flag and stop_flag():
                    stopped = True
                    break
                n = min(block, length - done)
                data, ok = rd.read_strict(start + done, n)
                if ok and len(data) == n:
                    consecutive = 0
                    fh.seek(done)
                    fh.write(data)
                elif ok and not data:
                    # fin du périphérique
                    length = done
                    break
                else:
                    fh.seek(done)
                    fh.write(b'\x00' * n)
                    retry.append([done, n])
                    consecutive += 1
                    if consecutive >= 4:                  # zone très abîmée : on saute plus loin
                        skip = min(8 * MB, length - done - n)
                        if skip > 0:
                            fh.seek(done + n)
                            fh.write(b'\x00' * skip)
                            retry.append([done + n, skip])
                            done += skip
                done += n
                progress(done, "Copie (passe 1)")
                if time.time() - last_save[0] > 5:
                    save_map()
                    last_save[0] = time.time()
            if not stopped:
                phase = 2
                save_map()
        # ---------------- passe 2 : reprise fine des zones en échec
        if phase == 2 and not stopped:
            work = retry
            retry = []
            idx = 0
            while idx < len(work):
                off, ln = work[idx]
                idx += 1
                pos = off
                end = off + ln
                step = 64 * 1024
                while pos < end:
                    if stop_flag and stop_flag():
                        stopped = True
                        retry = work[idx - 1:]
                        break
                    n = min(step, end - pos)
                    data, ok = rd.read_strict(start + pos, n)
                    if ok and len(data) == n:
                        fh.seek(pos)
                        fh.write(data)
                    else:
                        for s in range(pos, pos + n, ss):
                            sec, ok2 = rd.read_strict(start + s, ss)
                            if not ok2:
                                sec, ok2 = rd.read_strict(start + s, ss)
                            if ok2 and len(sec) == ss:
                                fh.seek(s)
                                fh.write(sec)
                            else:
                                bad.append(start + s)
                    pos += n
                    progress(length, f"Reprise des zones défectueuses ({idx}/{len(work)})")
                if stopped:
                    break
            if not stopped:
                retry = []
    finally:
        fh.flush()
        fh.close()
    save_map()
    result = {'success': not stopped, 'stopped': stopped, 'bytes': done, 'badSectors': len(bad),
              'seconds': round(time.time() - t0, 1), 'imagePath': out_path, 'mapPath': map_path}
    rd.close()
    if stopped:
        result['message'] = "Imagerie interrompue — relancez avec la même destination pour reprendre."
        return result
    if hash_output:
        md5, sha = hashlib.md5(), hashlib.sha256()
        with open(out_path, 'rb') as f:
            hd = 0
            while True:
                c = f.read(4 * MB)
                if not c:
                    break
                md5.update(c)
                sha.update(c)
                hd += len(c)
                now = time.time()
                if now - last_emit[0] > 0.25:
                    last_emit[0] = now
                    emit('progress', {'percent': 99.0, 'finished': False, 'engine': 'imager',
                                      'currentPath': 'Calcul des empreintes', 'bytesDone': hd, 'bytesTotal': length,
                                      'filesFound': 0})
        result['md5'], result['sha256'] = md5.hexdigest(), sha.hexdigest()
    save_map(True, {k: result[k] for k in ('md5', 'sha256') if k in result})
    emit('progress', {'percent': 100, 'finished': True, 'engine': 'imager', 'filesFound': 0})
    return result

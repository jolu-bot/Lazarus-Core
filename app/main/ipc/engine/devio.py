"""Accès bas niveau aux périphériques bruts, volumes, images disque et fichiers.

Principes :
  * lecture seule — aucun octet n'est jamais écrit sur la source ;
  * lectures alignées sur le secteur physique (obligatoire pour \\\\.\\PhysicalDriveN) ;
  * un secteur illisible ne casse jamais l'analyse : il est rempli de zéros et
    enregistré dans ``bad_sectors``.
"""
from __future__ import annotations

import os
import queue
import re
import struct
import threading
from typing import Iterator, List, Optional, Tuple

from .common import STOP

IS_WIN = os.name == 'nt'

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _k32.CreateFileW.restype = wintypes.HANDLE
    _k32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                      ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
    _k32.SetFilePointerEx.restype = wintypes.BOOL
    _k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    _k32.ReadFile.restype = wintypes.BOOL
    _k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                     wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                     wintypes.LPVOID]
    _k32.DeviceIoControl.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL

    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 1
    FILE_SHARE_WRITE = 2
    FILE_SHARE_DELETE = 4
    OPEN_EXISTING = 3
    IOCTL_DISK_GET_DRIVE_GEOMETRY = 0x70000
    IOCTL_DISK_GET_LENGTH_INFO = 0x7405C

MAX_IO = 4 * 1024 * 1024


class DeviceError(Exception):
    pass


def normalize_path(path: str) -> str:
    """Accepte 'C:', 'C:\\', 'PhysicalDrive0', '\\\\.\\PhysicalDrive0', un chemin d'image, etc."""
    p = (path or '').strip().strip('"')
    if not IS_WIN:
        return p
    if re.fullmatch(r'[A-Za-z]:\\?', p):
        return '\\\\.\\' + p[:2].upper()
    if re.fullmatch(r'(?i)(physicaldrive|harddisk)\d+', p):
        return '\\\\.\\' + p
    if re.fullmatch(r'(?i)\\\\\.\\[A-Za-z]:\\?', p):
        return p.rstrip('\\')
    return p


def is_raw_device(path: str) -> bool:
    p = normalize_path(path)
    if IS_WIN:
        return p.startswith('\\\\.\\') or p.startswith('\\\\?\\GLOBALROOT')
    return p.startswith('/dev/')


class Reader:
    """Lecteur aléatoire en lecture seule avec alignement et tolérance aux secteurs défectueux."""

    def __init__(self, path: str):
        self.path = normalize_path(path)
        self.raw = is_raw_device(self.path)
        self.size: Optional[int] = None
        self.sector_size = 512
        self.bad_sectors: List[int] = []
        self.bad_count = 0
        self._lock = threading.Lock()
        self._h = None
        self._fd = None
        self._open()

    # ------------------------------------------------------------------ open
    def _open(self):
        if IS_WIN:
            h = _k32.CreateFileW(self.path, GENERIC_READ,
                                 FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                 None, OPEN_EXISTING, 0, None)
            if h in (None, -1, 0xFFFFFFFFFFFFFFFF, ctypes.c_void_p(-1).value):
                err = ctypes.get_last_error()
                if err == 5:
                    raise DeviceError("Accès refusé (erreur 5) — lancez Lazarus Core en tant qu'administrateur")
                if err == 2 or err == 3:
                    raise DeviceError(f'Périphérique introuvable : {self.path}')
                raise DeviceError(f'Impossible d\'ouvrir {self.path} (erreur Windows {err})')
            self._h = h
            if self.raw:
                self._probe_windows_geometry()
            else:
                self.size = os.path.getsize(self.path)
        else:
            flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)
            try:
                self._fd = os.open(self.path, flags)
            except PermissionError:
                raise DeviceError('Accès refusé — exécutez avec les droits administrateur (sudo)')
            except OSError as e:
                raise DeviceError(f'Impossible d\'ouvrir {self.path}: {e}')
            try:
                self.size = os.lseek(self._fd, 0, os.SEEK_END)
                os.lseek(self._fd, 0, os.SEEK_SET)
            except OSError:
                self.size = None
            if self.raw:
                self._probe_unix_sector()

    def _probe_windows_geometry(self):
        buf = ctypes.create_string_buffer(8)
        ret = wintypes.DWORD(0)
        if _k32.DeviceIoControl(self._h, IOCTL_DISK_GET_LENGTH_INFO, None, 0, buf, 8, ctypes.byref(ret), None):
            self.size = struct.unpack('<Q', buf.raw[:8])[0]
        geo = ctypes.create_string_buffer(64)
        if _k32.DeviceIoControl(self._h, IOCTL_DISK_GET_DRIVE_GEOMETRY, None, 0, geo, 64,
                                ctypes.byref(ret), None):
            bps = struct.unpack_from('<I', geo.raw, 20)[0]
            if bps in (512, 1024, 2048, 4096, 8192):
                self.sector_size = bps

    def _probe_unix_sector(self):
        try:
            import fcntl  # type: ignore
            BLKSSZGET = 0x1268
            buf = bytearray(4)
            fcntl.ioctl(self._fd, BLKSSZGET, buf)
            v = struct.unpack('<I', bytes(buf))[0]
            if v in (512, 1024, 2048, 4096):
                self.sector_size = v
        except Exception:
            pass

    def set_size_hint(self, size: int):
        if not self.size:
            self.size = size

    # ------------------------------------------------------------------ read
    def _raw_pread(self, off: int, n: int) -> Tuple[bytes, bool]:
        """Lit n octets (alignés) à off. Retourne (données, ok)."""
        if IS_WIN:
            pos = ctypes.c_longlong(0)
            if not _k32.SetFilePointerEx(self._h, off, ctypes.byref(pos), 0):
                return b'', False
            buf = ctypes.create_string_buffer(n)
            got = wintypes.DWORD(0)
            ok = _k32.ReadFile(self._h, buf, n, ctypes.byref(got), None)
            if not ok:
                return buf.raw[:got.value], False
            return buf.raw[:got.value], True
        try:
            data = os.pread(self._fd, n, off)
            return data, True
        except OSError:
            return b'', False

    def _read_aligned(self, a0: int, length: int) -> bytes:
        ss = self.sector_size
        out = bytearray()
        pos = a0
        end = a0 + length
        while pos < end:
            n = min(MAX_IO, end - pos)
            data, ok = self._raw_pread(pos, n)
            if ok:
                if not data:
                    break  # EOF
                out += data
                if len(data) < n:
                    break
                pos += n
                continue
            # Erreur de lecture : repli secteur par secteur
            sp = pos
            while sp < pos + n:
                sec, ok2 = self._raw_pread(sp, ss)
                if not ok2:
                    sec, ok2 = self._raw_pread(sp, ss)  # un nouvel essai
                if not ok2:
                    self.bad_count += 1
                    if len(self.bad_sectors) < 200000:
                        self.bad_sectors.append(sp)
                    sec = b'\x00' * ss
                elif not sec:
                    return bytes(out)  # fin du périphérique
                elif len(sec) < ss:
                    sec = sec + b'\x00' * (ss - len(sec))
                out += sec
                sp += ss
            pos += n
        return bytes(out)

    def read_strict(self, off: int, n: int) -> Tuple[bytes, bool]:
        """Lecture alignée sans repli : (données, ok). Utilisé par l'imageur pour contrôler les erreurs."""
        with self._lock:
            data, ok = self._raw_pread(off, n)
        return data, ok

    def read_at(self, off: int, n: int) -> bytes:
        if n <= 0 or off < 0:
            return b''
        if self.size is not None:
            if off >= self.size:
                return b''
            n = min(n, self.size - off)
        ss = self.sector_size
        a0 = off - (off % ss)
        end = off + n
        a1 = -(-end // ss) * ss
        with self._lock:
            data = self._read_aligned(a0, a1 - a0)
        rel = off - a0
        return data[rel:rel + n]

    def close(self):
        try:
            if IS_WIN and self._h:
                _k32.CloseHandle(self._h)
            elif self._fd is not None:
                os.close(self._fd)
        except Exception:
            pass
        self._h = None
        self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def open_reader(path: str) -> Reader:
    return Reader(path)


def iter_blocks(reader, start: int, end: int, block: int = 8 * 1024 * 1024,
                depth: int = 3, fetch=None) -> Iterator[Tuple[int, bytes]]:
    """Itère (offset, données) avec lecture anticipée dans un thread (E/S et analyse se chevauchent)."""
    fetch = fetch or reader.read_at
    q: 'queue.Queue' = queue.Queue(depth)
    stop = threading.Event()

    def put(item) -> bool:
        while not stop.is_set():
            try:
                q.put(item, timeout=0.2)
                return True
            except queue.Full:
                continue
        return False

    def worker():
        pos = start
        try:
            while pos < end and not stop.is_set():
                n = min(block, end - pos)
                data = fetch(pos, n)
                if not data:
                    break
                if not put((pos, data)):
                    return
                pos += len(data)
                if len(data) < n:
                    break
        except Exception as e:  # pragma: no cover
            put(e)
        finally:
            put(None)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    try:
        while True:
            if STOP.is_set():
                break
            try:
                item = q.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        stop.set()


def open_reader(spec: str):
    """Fabrique : disque/volume/fichier brut, conteneurs (VHD, VHDX, VMDK, .001), RAID virtuel (« raid:{json} »)
    ou volume BitLocker déverrouillé (« bitlocker:{json} »)."""
    import json as _json
    s = (spec or '').strip()
    if s.startswith('raid:'):
        from .raid import build_from_spec
        return build_from_spec(_json.loads(s[5:]))
    if s.startswith('bitlocker:'):
        from .bitlocker import open_from_spec
        return open_from_spec(_json.loads(s[10:]))
    if s and not is_raw_device(s) and os.path.isfile(s):
        low = s.lower()
        try:
            if low.endswith('.vhd'):
                from .containers import VhdReader
                return VhdReader(s)
            if low.endswith('.vhdx'):
                from .containers import VhdxReader
                return VhdxReader(s)
            if low.endswith('.vmdk'):
                from .containers import VmdkReader
                return VmdkReader(s)
            if re.search(r'\.0*1$', low) and os.path.exists(s[:-1] + '2'):
                from .containers import SplitReader
                return SplitReader(s)
        except DeviceError:
            if low.endswith(('.vhd',)):
                return Reader(s)          # VHD sans pied de page : traité comme une image brute
            raise
    return Reader(s)

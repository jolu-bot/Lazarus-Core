"""Énumération des disques, volumes et clichés instantanés (VSS) — sans wmic (supprimé de Windows 11 24H2+)."""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Dict, List

CREATE_NO_WINDOW = 0x08000000

_PS_DRIVES = r"""
$ErrorActionPreference = 'SilentlyContinue'
$disks = @(Get-CimInstance Win32_DiskDrive | Select-Object DeviceID, Index, Model, Size, InterfaceType, SerialNumber, MediaType, BytesPerSector, Partitions)
$parts = @(Get-Partition | Select-Object DiskNumber, PartitionNumber, DriveLetter, Size, Offset, Type, GptType, IsBoot, IsSystem)
$vols = @(Get-Volume | Select-Object DriveLetter, FileSystemLabel, FileSystemType, Size, SizeRemaining, HealthStatus, DriveType)
$pd = @(Get-PhysicalDisk | Select-Object DeviceId, MediaType, BusType, HealthStatus, FriendlyName)
[pscustomobject]@{ disks = $disks; parts = $parts; vols = $vols; pd = $pd } | ConvertTo-Json -Depth 4 -Compress
"""

_PS_VSS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$vols = @{}
Get-CimInstance Win32_Volume | ForEach-Object { $vols[$_.DeviceID] = $_.DriveLetter }
$s = @(Get-CimInstance Win32_ShadowCopy | ForEach-Object {
  [pscustomobject]@{ id = $_.ID; device = $_.DeviceObject; created = ($_.InstallDate).ToString('o'); volume = $_.VolumeName; letter = $vols[$_.VolumeName]; state = $_.State }
})
ConvertTo-Json -InputObject $s -Depth 3 -Compress
"""


def _ps(script: str, timeout: int = 40) -> str:
    return subprocess.check_output(
        ['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script],
        text=True, encoding='utf-8', errors='replace', timeout=timeout, creationflags=CREATE_NO_WINDOW)


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _windows_drives() -> List[dict]:
    raw = _ps(_PS_DRIVES).strip()
    data = json.loads(raw) if raw else {}
    disks = _as_list(data.get('disks'))
    parts = _as_list(data.get('parts'))
    vols = {str(v.get('DriveLetter')): v for v in _as_list(data.get('vols')) if v.get('DriveLetter')}
    pd = {int(p['DeviceId']): p for p in _as_list(data.get('pd')) if p.get('DeviceId') is not None}
    out: List[dict] = []
    for d in sorted(disks, key=lambda x: x.get('Index', 0)):
        idx = int(d.get('Index', 0))
        size = int(d.get('Size') or 0)
        model = (d.get('Model') or f'Disque {idx}').strip()
        p_ = pd.get(idx, {})
        item = {
            'path': f'\\\\.\\PhysicalDrive{idx}', 'kind': 'disk', 'label': f'{model} (Disque {idx})', 'model': model,
            'serial': (d.get('SerialNumber') or '').strip(), 'interface': str(p_.get('BusType') or d.get('InterfaceType') or ''),
            'mediaType': str(p_.get('MediaType') or d.get('MediaType') or ''), 'health': str(p_.get('HealthStatus') or ''),
            'totalSize': size, 'sectorSize': int(d.get('BytesPerSector') or 512), 'fs': '', 'partitions': [],
        }
        for pt in [p for p in parts if p.get('DiskNumber') == idx]:
            letter = pt.get('DriveLetter')
            letter = chr(letter) if isinstance(letter, int) and letter else (str(letter) if letter else '')
            v = vols.get(letter, {})
            item['partitions'].append({
                'number': pt.get('PartitionNumber'), 'letter': letter, 'size': int(pt.get('Size') or 0),
                'offset': int(pt.get('Offset') or 0), 'fs': v.get('FileSystemType') or '',
                'label': v.get('FileSystemLabel') or '', 'type': str(pt.get('Type') or ''),
            })
        out.append(item)
        for pt in item['partitions']:
            if pt['letter']:
                v = vols.get(pt['letter'], {})
                out.append({
                    'path': f'\\\\.\\{pt["letter"]}:', 'kind': 'volume',
                    'label': f'{pt["label"] or "Volume"} ({pt["letter"]}:) — {pt["fs"] or "?"}',
                    'model': model, 'serial': '', 'interface': item['interface'], 'totalSize': pt['size'],
                    'sectorSize': item['sectorSize'], 'fs': pt['fs'], 'parentDisk': item['path'],
                    'freeSize': int(v.get('SizeRemaining') or 0), 'letter': pt['letter'],
                })
    # volumes sans partition (disques virtuels, réseau exclu)
    known = {o.get('letter') for o in out if o.get('letter')}
    for letter, v in vols.items():
        if letter not in known and int(v.get('Size') or 0) > 0 and str(v.get('DriveType')) in ('Fixed', '3', 'Removable', '2'):
            out.append({'path': f'\\\\.\\{letter}:', 'kind': 'volume',
                        'label': f'{v.get("FileSystemLabel") or "Volume"} ({letter}:) — {v.get("FileSystemType") or "?"}',
                        'model': '', 'serial': '', 'interface': '', 'totalSize': int(v.get('Size') or 0),
                        'sectorSize': 512, 'fs': v.get('FileSystemType') or '', 'letter': letter})
    return out


def _linux_drives() -> List[dict]:
    try:
        raw = subprocess.check_output(
            ['lsblk', '-J', '-b', '-o', 'NAME,PATH,SIZE,MODEL,SERIAL,TRAN,FSTYPE,LABEL,TYPE,MOUNTPOINT,PHY-SEC'],
            text=True, timeout=15)
        data = json.loads(raw)
    except Exception:
        return []
    out: List[dict] = []
    for d in data.get('blockdevices', []):
        if d.get('type') not in ('disk',):
            continue
        out.append({'path': d.get('path'), 'kind': 'disk', 'label': f'{d.get("model") or d.get("name")} ({d.get("name")})',
                    'model': d.get('model') or '', 'serial': d.get('serial') or '', 'interface': d.get('tran') or '',
                    'totalSize': int(d.get('size') or 0), 'sectorSize': int(d.get('phy-sec') or 512), 'fs': '',
                    'partitions': []})
        for c in d.get('children', []) or []:
            out.append({'path': c.get('path'), 'kind': 'volume',
                        'label': f'{c.get("label") or c.get("name")} — {c.get("fstype") or "?"}',
                        'model': d.get('model') or '', 'serial': '', 'interface': d.get('tran') or '',
                        'totalSize': int(c.get('size') or 0), 'sectorSize': int(d.get('phy-sec') or 512),
                        'fs': c.get('fstype') or '', 'parentDisk': d.get('path')})
    return out


def _mac_drives() -> List[dict]:
    import plistlib
    try:
        raw = subprocess.check_output(['diskutil', 'list', '-plist'], timeout=15)
        data = plistlib.loads(raw)
    except Exception:
        return []
    out: List[dict] = []
    for disk in data.get('AllDisksAndPartitions', []):
        dev = disk.get('DeviceIdentifier')
        out.append({'path': f'/dev/r{dev}', 'kind': 'disk', 'label': f'Disque {dev}', 'model': '', 'serial': '',
                    'interface': '', 'totalSize': int(disk.get('Size') or 0), 'sectorSize': 512, 'fs': '',
                    'partitions': []})
        for p in disk.get('Partitions', []) or []:
            pid = p.get('DeviceIdentifier')
            out.append({'path': f'/dev/r{pid}', 'kind': 'volume', 'label': f'{p.get("VolumeName") or pid} — {p.get("Content") or "?"}',
                        'model': '', 'serial': '', 'interface': '', 'totalSize': int(p.get('Size') or 0),
                        'sectorSize': 512, 'fs': p.get('Content') or '', 'parentDisk': f'/dev/r{dev}'})
    return out


def fast_drives() -> List[dict]:
    """Liste quasi instantanée (API Win32, sans PowerShell) : volumes + disques physiques (sans nom de modèle)."""
    if os.name != 'nt':
        return enumerate_drives()
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    out: List[dict] = []
    mask = k.GetLogicalDrives()
    for i in range(26):
        if not (mask >> i) & 1:
            continue
        letter = chr(65 + i)
        root = f'{letter}:\\'
        dt = k.GetDriveTypeW(root)
        if dt not in (2, 3):                   # amovible / fixe
            continue
        label = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        ok = k.GetVolumeInformationW(root, label, 261, None, None, None, fs, 261)
        total = ctypes.c_ulonglong(0)
        free = ctypes.c_ulonglong(0)
        avail = ctypes.c_ulonglong(0)
        k.GetDiskFreeSpaceExW(root, ctypes.byref(avail), ctypes.byref(total), ctypes.byref(free))
        out.append({'path': f'\\\\.\\{letter}:', 'kind': 'volume',
                    'label': f'{(label.value if ok else "") or "Volume"} ({letter}:) — {(fs.value if ok else "") or "?"}',
                    'model': '', 'serial': '', 'interface': 'USB' if dt == 2 else '', 'totalSize': total.value,
                    'sectorSize': 512, 'fs': fs.value if ok else '', 'letter': letter, 'freeSize': free.value})
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                              wintypes.DWORD, wintypes.HANDLE]
    k.CreateFileW.restype = wintypes.HANDLE
    k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID,
                                  wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    disks: List[dict] = []
    for n in range(16):
        path = f'\\\\.\\PhysicalDrive{n}'
        h = k.CreateFileW(path, 0, 3, None, 3, 0, None)       # accès « requête » : sans droits administrateur
        if h in (None, -1, 0xFFFFFFFFFFFFFFFF, ctypes.c_void_p(-1).value):
            continue
        buf = ctypes.create_string_buffer(128)
        ret = wintypes.DWORD(0)
        size = 0
        bps = 512
        if k.DeviceIoControl(h, 0x700A0, None, 0, buf, 128, ctypes.byref(ret), None):     # GET_DRIVE_GEOMETRY_EX
            import struct
            bps = struct.unpack_from('<I', buf.raw, 20)[0] or 512
            size = struct.unpack_from('<Q', buf.raw, 24)[0]
        k.CloseHandle(h)
        disks.append({'path': path, 'kind': 'disk', 'label': f'Disque {n}', 'model': '', 'serial': '', 'interface': '',
                      'totalSize': size, 'sectorSize': bps, 'fs': '', 'partitions': []})
    return disks + out


def enumerate_drives() -> List[dict]:
    try:
        if os.name == 'nt':
            return _windows_drives()
        if os.uname().sysname == 'Darwin':
            return _mac_drives()
        return _linux_drives()
    except Exception as e:
        from .common import log
        log(f"énumération des disques impossible : {e}")
        return []


def list_shadow_copies() -> List[dict]:
    if os.name != 'nt':
        return []
    try:
        raw = _ps(_PS_VSS).strip()
        data = json.loads(raw) if raw else []
    except Exception:
        return []
    out = []
    for s in _as_list(data):
        dev = s.get('device') or ''
        if not dev:
            continue
        path = dev.rstrip('\\')
        if path.startswith('\\\\?\\GLOBALROOT'):
            pass
        elif path.startswith('\\Device'):
            path = '\\\\?\\GLOBALROOT' + path
        out.append({'path': path, 'kind': 'shadow', 'label': f'Cliché {s.get("letter") or ""} du {str(s.get("created", ""))[:16].replace("T", " ")}',
                    'created': s.get('created'), 'letter': s.get('letter') or '', 'id': s.get('id'),
                    'totalSize': 0, 'sectorSize': 512, 'fs': 'NTFS', 'model': 'Shadow Copy', 'serial': '', 'interface': 'VSS'})
    return out


_PS_SMART = r"""
$ErrorActionPreference = 'SilentlyContinue'
$out = @(Get-PhysicalDisk | ForEach-Object {
  $c = $null; try { $c = $_ | Get-StorageReliabilityCounter -ErrorAction Stop } catch {}
  [pscustomobject]@{ id = [int]$_.DeviceId; name = $_.FriendlyName; media = "$($_.MediaType)"; bus = "$($_.BusType)";
    health = "$($_.HealthStatus)"; op = "$($_.OperationalStatus)"; size = $_.Size;
    temp = $c.Temperature; tempMax = $c.TemperatureMax; wear = $c.Wear; hours = $c.PowerOnHours;
    readErr = $c.ReadErrorsTotal; writeErr = $c.WriteErrorsTotal; uncorrected = $c.ReadErrorsUncorrected }
})
ConvertTo-Json -InputObject $out -Compress
"""


def smart_report() -> List[dict]:
    """État de santé des disques (S.M.A.R.T. / compteurs de fiabilité) avec un diagnostic et un conseil."""
    items: List[dict] = []
    try:
        if os.name == 'nt':
            raw = _ps(_PS_SMART, timeout=60).strip()
            items = _as_list(json.loads(raw)) if raw else []
        else:
            for d in enumerate_drives():
                if d.get('kind') != 'disk':
                    continue
                try:
                    j = json.loads(subprocess.check_output(['smartctl', '-j', '-a', d['path']], text=True, timeout=30))
                except Exception:
                    continue
                at = {a['name']: a for a in j.get('ata_smart_attributes', {}).get('table', [])}
                items.append({'id': d['path'], 'name': j.get('model_name', d['label']), 'media': '', 'bus': d.get('interface', ''),
                              'health': 'Healthy' if j.get('smart_status', {}).get('passed', True) else 'Unhealthy',
                              'temp': (j.get('temperature') or {}).get('current'), 'hours': (j.get('power_on_time') or {}).get('hours'),
                              'readErr': (at.get('Raw_Read_Error_Rate') or {}).get('raw', {}).get('value'),
                              'reallocated': (at.get('Reallocated_Sector_Ct') or {}).get('raw', {}).get('value')})
    except Exception:
        return []
    out = []
    for it in items:
        reasons, level = [], 'ok'
        if str(it.get('health', 'Healthy')).lower() not in ('healthy', 'ok', ''):
            reasons.append(f"État signalé par le disque : {it.get('health')}")
            level = 'critical'
        if it.get('op') and str(it['op']).lower() not in ('ok', ''):
            reasons.append(f"Statut opérationnel : {it['op']}")
            level = 'critical'
        w = it.get('wear')
        if isinstance(w, (int, float)) and w >= 80:
            reasons.append(f'Usure SSD : {int(w)} %')
            level = 'critical' if w >= 95 else ('warning' if level == 'ok' else level)
        for key, label, lim in (('readErr', 'Erreurs de lecture', 0), ('uncorrected', 'Erreurs de lecture non corrigées', 0),
                                ('reallocated', 'Secteurs réalloués', 0)):
            v = it.get(key)
            if isinstance(v, (int, float)) and v > lim:
                reasons.append(f'{label} : {int(v)}')
                level = 'critical' if key == 'uncorrected' or v > 50 else ('warning' if level == 'ok' else level)
        t = it.get('temp')
        if isinstance(t, (int, float)) and t >= 65:
            reasons.append(f'Température élevée : {int(t)} °C')
            level = 'warning' if level == 'ok' else level
        advice = {'ok': 'Aucun signe de défaillance détecté.',
                  'warning': 'Disque à surveiller : clonez-le (image) avant toute récupération.',
                  'critical': 'Disque en danger : ne l\'utilisez plus. Créez d\'abord une image (Clonage de disque), '
                              'puis récupérez depuis l\'image.'}[level]
        path = f"\\\\.\\PhysicalDrive{it['id']}" if os.name == 'nt' and isinstance(it.get('id'), int) else it.get('id')
        out.append({**it, 'path': path, 'level': level, 'reasons': reasons, 'advice': advice,
                    'hasCounters': any(it.get(k) is not None for k in ('temp', 'wear', 'hours', 'readErr'))})
    return out

"""Validation du moteur sur de VRAIS volumes Windows (NTFS, FAT32, exFAT) créés dans des disques virtuels (VHD).

Nécessite les droits administrateur (diskpart, accès disque brut). Ne touche QUE des VHD jetables créés dans un
dossier temporaire : chaque disque est vérifié (« File Backed Virtual ») avant toute écriture.

Scénarios, pour chaque système de fichiers :
  A. fichiers supprimés (et mis à la Corbeille pour NTFS) -> analyse rapide du disque physique -> récupération
  B. formatage rapide du volume -> analyse approfondie -> récupération
  C. (NTFS) suppression de la partition -> analyse approfondie -> récupération
Chaque fichier supprimé est comparé octet par octet (SHA-256) à la vérité terrain.

Usage (terminal administrateur) :  python tests/tools/validate_on_real_volumes.py [dossier_de_travail]
Le rapport est écrit dans <dossier_de_travail>/report.json et le journal dans log.txt.
"""
import ctypes
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
ENGINE = os.path.join(ROOT, 'app', 'main', 'ipc', 'scan_backend.py')
WORK = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), 'lazarus-real-validation')
os.makedirs(WORK, exist_ok=True)
LOG = open(os.path.join(WORK, 'log.txt'), 'a', encoding='utf-8', buffering=1)


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.write(s + '\n')
    print(s, flush=True)


def ps(cmd, check=True):
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', cmd], capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if check and r.returncode != 0:
        raise RuntimeError(f'PowerShell: {cmd}\n{r.stdout}\n{r.stderr}')
    return r.stdout.strip()


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ------------------------------------------------------------------ disques virtuels
class Vhd:
    def __init__(self, name, size_mb, ext='vhd', vtype='fixed'):
        self.vtype = vtype
        self.path = os.path.join(WORK, f'{name}.{ext}')
        self.size_mb = size_mb
        self.number = None
        self.letter = None

    def create_attach(self):
        if os.path.exists(self.path):
            self.detach()
            os.remove(self.path)
        script = os.path.join(WORK, 'dp.txt')
        open(script, 'w').write(f'create vdisk file="{self.path}" maximum={self.size_mb} type={self.vtype}\n'
                                f'select vdisk file="{self.path}"\nattach vdisk\n')
        subprocess.run(['diskpart', '/s', script], capture_output=True, check=True)
        time.sleep(2)
        self.number = int(ps(f'(Get-DiskImage -ImagePath "{self.path}" | Get-Disk).Number'))
        bus = ps(f'(Get-Disk -Number {self.number}).BusType')
        loc = ps(f'(Get-Disk -Number {self.number}).Location')
        if 'Virtual' not in bus or self.path.lower() not in loc.lower():
            raise RuntimeError(f'Sécurité : le disque {self.number} n\'est pas le VHD de test ({bus} / {loc})')
        ps(f'Initialize-Disk -Number {self.number} -PartitionStyle GPT')

    def format(self, fs, label='LZTEST'):
        part = ps(f'$p = New-Partition -DiskNumber {self.number} -UseMaximumSize -AssignDriveLetter; '
                  f'Format-Volume -Partition $p -FileSystem {fs} -NewFileSystemLabel {label} -Confirm:$false | Out-Null; '
                  f'$p.DriveLetter')
        self.letter = part.strip()[-1]
        time.sleep(1)
        return self.letter

    def quick_format(self, fs, label='LZTEST2'):
        ps(f'Format-Volume -DriveLetter {self.letter} -FileSystem {fs} -NewFileSystemLabel {label} -Confirm:$false | Out-Null')
        time.sleep(1)

    def flush(self):
        ps(f'Write-VolumeCache -DriveLetter {self.letter}', check=False)

    def drop_partition(self):
        ps(f'Remove-Partition -DiskNumber {self.number} -PartitionNumber 1 -Confirm:$false')
        time.sleep(1)

    @property
    def device(self):
        return f'\\\\.\\PhysicalDrive{self.number}'

    def detach(self):
        script = os.path.join(WORK, 'dp2.txt')
        open(script, 'w').write(f'select vdisk file="{self.path}"\ndetach vdisk\n')
        subprocess.run(['diskpart', '/s', script], capture_output=True)


# ------------------------------------------------------------------ jeu de fichiers
def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_files(seed, count=60):
    """Fichiers déterministes : certains compressibles (texte), d'autres aléatoires, quelques formats structurés."""
    rnd = random.Random(seed)
    files = []
    import io
    import sqlite3
    import struct
    import zipfile
    import zlib

    def png(w=64, h=64):
        raw = b''.join(b'\x00' + bytes(rnd.randrange(256) for _ in range(w * 3)) for _ in range(h))

        def ch(t, d):
            return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF)
        return (b'\x89PNG\r\n\x1a\n' + ch(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
                ch(b'IDAT', zlib.compress(raw)) + ch(b'IEND', b''))

    def zipf():
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('a.txt', 'Lazarus ' * rnd.randrange(100, 3000))
            z.writestr('b.bin', bytes(rnd.randrange(256) for _ in range(rnd.randrange(500, 20000))))
        return b.getvalue()

    for i in range(count):
        kind = i % 6
        folder = ['Documents', 'Images', 'Projets\\Alpha', 'Projets\\Beta', 'Archives', 'Divers\\Sous dossier'][i % 6]
        if kind == 0:
            name, data = f'rapport_{i}.txt', (f'Rapport numero {i}. ' * rnd.randrange(50, 4000)).encode()
        elif kind == 1:
            name, data = f'image_{i}.png', png()
        elif kind == 2:
            name, data = f'donnees_{i}.bin', bytes(rnd.randrange(256) for _ in range(rnd.randrange(2000, 300000)))
        elif kind == 3:
            name, data = f'archive_{i}.zip', zipf()
        elif kind == 4:
            name, data = f'note_{i}.txt', f'Petite note {i}'.encode()          # fichiers minuscules (résidents NTFS)
        else:
            name, data = f'gros_{i}.bin', bytes(rnd.randrange(256) for _ in range(rnd.randrange(1_000_000, 3_000_000)))
        files.append({'rel': folder + '\\' + name, 'name': name, 'data': data})
    return files


def recycle(path):
    """Envoie à la Corbeille (SHFileOperationW + FOF_ALLOWUNDO) pour produire de vrais $I/$R."""
    from ctypes import wintypes

    class SHFILEOPSTRUCT(ctypes.Structure):
        _fields_ = [('hwnd', wintypes.HWND), ('wFunc', wintypes.UINT), ('pFrom', wintypes.LPCWSTR),
                    ('pTo', wintypes.LPCWSTR), ('fFlags', ctypes.c_ushort), ('fAnyOperationsAborted', wintypes.BOOL),
                    ('hNameMappings', ctypes.c_void_p), ('lpszProgressTitle', wintypes.LPCWSTR)]
    op = SHFILEOPSTRUCT(None, 3, path + '\0\0', None, 0x40 | 0x10 | 0x4 | 0x400, False, None, None)
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0


def populate(vhd, fs, files):
    drive = vhd.letter + ':\\'
    for f in files:
        full = os.path.join(drive, f['rel'])
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'wb') as fh:
            fh.write(f['data'])
            fh.flush()
            os.fsync(fh.fileno())
    if fs == 'NTFS':
        # un fichier compressé NTFS (LZNT1) : le moteur doit le décompresser
        comp = [f for f in files if f['name'].startswith('rapport_')][:3]
        for f in comp:
            subprocess.run(['compact', '/c', os.path.join(drive, f['rel'])], capture_output=True)
            f['compressed'] = True
    vhd.flush()


def delete_some(vhd, fs, files):
    drive = vhd.letter + ':\\'
    rnd = random.Random(99)
    victims = [f for i, f in enumerate(files) if i % 2 == 0]
    for f in victims:
        full = os.path.join(drive, f['rel'])
        f['deleted'] = True
        if fs == 'NTFS' and rnd.random() < 0.3:
            f['recycled'] = recycle(full)
            if f['recycled']:
                continue
        os.remove(full)
    vhd.flush()
    time.sleep(1)


# ------------------------------------------------------------------ moteur
def run_engine(cmd, req):
    rf = os.path.join(WORK, f'req_{cmd}.json')
    json.dump(req, open(rf, 'w'))
    t = time.time()
    r = subprocess.run([sys.executable, ENGINE, cmd, '--request-file', rf], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', input='')
    result = None
    for line in r.stdout.splitlines():
        if line.startswith('{') and '"event"' not in line[:12]:
            try:
                result = json.loads(line)
            except ValueError:
                pass
    return r, result, time.time() - t


def evaluate(scenario, device, files, deep, carve, existing=False):
    sess = os.path.join(WORK, f'{scenario}.jsonl')
    if os.path.exists(sess):
        os.remove(sess)
    r, _, dt = run_engine('scan', {'device': device, 'deepScan': deep, 'carveText': carve, 'enableCarving': carve,
                                   'includeExisting': existing, 'sessionPath': sess})
    log(f'[{scenario}] scan {dt:.1f}s rc={r.returncode}')
    if r.returncode != 0:
        log(r.stdout[-600:], r.stderr[-600:])
    records = []
    if os.path.exists(sess):
        for line in open(sess, encoding='utf-8'):
            try:
                records.append(json.loads(line))
            except ValueError:
                pass
    log(f'[{scenario}] {len(records)} éléments ; moteurs : ' + ', '.join(sorted({x["source"] for x in records})))
    want = [f for f in files if f.get('deleted') or existing]
    sizes = {}
    for rec in records:
        sizes.setdefault(rec['size'], []).append(rec)
    ids = []
    for f in want:
        for rec in sizes.get(len(f['data']), []):
            ids.append(rec['id'])
    ids = sorted(set(ids))[:5000]
    dest = os.path.join(WORK, f'out_{scenario}')
    shutil.rmtree(dest, ignore_errors=True)
    exact = named = 0
    recovered = {}
    if ids:
        r2, res, dt2 = run_engine('recover', {'sessionPath': sess, 'ids': ids, 'destination': dest, 'structure': 'flat',
                                              'verify': False, 'allowSameDisk': True})
        log(f'[{scenario}] recover {dt2:.1f}s')
        for item in (res or {}).get('results', []):
            if item.get('success'):
                recovered.setdefault(item['sha256'], []).append(item)
    missing = []
    for f in want:
        h = sha(f['data'])
        if h in recovered:
            exact += 1
            nm = f['name'].lower()
            if any(x['name'].lower().lstrip('_') == nm.lstrip('_') or x['name'].lower()[1:] == nm[1:] for x in recovered[h]):
                named += 1
        else:
            missing.append(f['rel'])
    out = {'scenario': scenario, 'wanted': len(want), 'exact': exact, 'with_original_name': named,
           'scan_seconds': round(dt, 1), 'elements': len(records), 'missing_examples': missing[:8]}
    log(f'[{scenario}] RÉSULTAT : {exact}/{len(want)} fichiers identiques octet par octet, {named} avec leur nom d\'origine')
    return out


def run_fs(fs, size_mb, report):
    log(f'\n===== {fs} =====')
    vhd = Vhd(fs.lower(), size_mb)
    try:
        vhd.create_attach()
        vhd.format(fs)
        files = make_files(7 if fs == 'NTFS' else 8, 60)
        populate(vhd, fs, files)
        delete_some(vhd, fs, files)
        report.append(evaluate(f'{fs}-A-supprimes', vhd.device, files, deep=False, carve=False))
        report.append(evaluate(f'{fs}-A2-carving', vhd.device, files, deep=False, carve=True))
        # B : formatage rapide
        vhd.quick_format(fs)
        report.append(evaluate(f'{fs}-B-apres-formatage', vhd.device, [dict(f, deleted=True) for f in files], deep=True, carve=True))
        if fs == 'NTFS':
            vhd.drop_partition()
            report.append(evaluate(f'{fs}-C-partition-supprimee', vhd.device, [dict(f, deleted=True) for f in files], deep=True,
                                   carve=True))
    except Exception as e:
        log(f'ERREUR {fs} : {e!r}')
        report.append({'scenario': fs, 'error': repr(e)})
    finally:
        vhd.detach()


def run_containers(report):
    """VHD dynamique et VHDX : le moteur lit le FICHIER (sans attacher le disque) et retrouve les fichiers supprimés."""
    for ext, vtype in (('vhd', 'expandable'), ('vhdx', 'expandable')):
        name = f'ntfs_dyn_{ext}'
        log(f'\n===== conteneur {ext.upper()} dynamique =====')
        vhd = Vhd(name, 300, ext=ext, vtype=vtype)
        try:
            vhd.create_attach()
            vhd.format('NTFS')
            files = make_files(11, 40)
            populate(vhd, 'NTFS', files)
            delete_some(vhd, 'NTFS', files)
            vhd.detach()
            time.sleep(2)
            report.append(evaluate(f'conteneur-{ext}', vhd.path, files, deep=False, carve=False))
        except Exception as e:
            log(f'ERREUR conteneur {ext} : {e!r}')
            report.append({'scenario': f'conteneur-{ext}', 'error': repr(e)})
        finally:
            vhd.detach()


def run_bitlocker(report):
    """Volume réellement chiffré par Windows (XTS-AES 128) : déverrouillage par clé de récupération puis récupération."""
    log('\n===== BitLocker =====')
    vhd = Vhd('bitlocker', 300)
    try:
        vhd.create_attach()
        vhd.format('NTFS', 'LZBL')
        files = make_files(13, 40)
        populate(vhd, 'NTFS', files)
        delete_some(vhd, 'NTFS', files)
        ps(f"Enable-BitLocker -MountPoint '{vhd.letter}:' -EncryptionMethod XtsAes128 -RecoveryPasswordProtector "
           f"-SkipHardwareTest -WarningAction SilentlyContinue | Out-Null")
        for _ in range(120):
            st = ps(f"(Get-BitLockerVolume -MountPoint '{vhd.letter}:').VolumeStatus")
            if st.strip() == 'FullyEncrypted':
                break
            time.sleep(2)
        key = ps(f"((Get-BitLockerVolume -MountPoint '{vhd.letter}:').KeyProtector | Where-Object KeyProtectorType -eq 'RecoveryPassword' "
                 f"| Select-Object -First 1).RecoveryPassword")
        log('BitLocker état :', st.strip(), '| clé de récupération obtenue :', bool(key))
        ps(f"Lock-BitLocker -MountPoint '{vhd.letter}:' -ForceDismount", check=False)
        vhd.detach()
        time.sleep(2)
        # le disque est détaché : on lit le fichier VHD ; la partition BitLocker est repérée par le moteur
        sys.path.insert(0, os.path.join(ROOT, 'app', 'main', 'ipc'))
        from engine import partitions
        from engine.devio import open_reader
        rd = open_reader(vhd.path)
        lay = partitions.detect_layout(rd)
        rd.close()
        log('partitions :', json.dumps([{k: p[k] for k in ('start', 'size', 'fs')} for p in lay]))
        bl = [p for p in lay if p['fs'] == 'bitlocker'][0]
        spec = 'bitlocker:' + json.dumps({'inner': vhd.path, 'start': bl['start'], 'size': bl['size'], 'recoveryPassword': key.strip()})
        # mauvaise clé : doit être refusée proprement
        bad = 'bitlocker:' + json.dumps({'inner': vhd.path, 'start': bl['start'], 'size': bl['size'],
                                         'recoveryPassword': '000000-000000-000000-000000-000000-000000-000000-000000'})
        rb, _, _ = run_engine('scan', {'device': bad, 'sessionPath': os.path.join(WORK, 'bad.jsonl')})
        log('mauvaise clé ->', (rb.stdout.strip().splitlines() or [''])[-1][:200])
        report.append(evaluate('bitlocker-supprimes', spec, files, deep=False, carve=False))
        report.append(evaluate('bitlocker-existants', spec, files, deep=False, carve=False, existing=True))
    except Exception as e:
        import traceback
        log(f'ERREUR BitLocker : {e!r}\n{traceback.format_exc()}')
        report.append({'scenario': 'bitlocker', 'error': repr(e)})
    finally:
        vhd.detach()


def main():
    if not is_admin():
        print('Ce script doit être lancé en administrateur.')
        sys.exit(2)
    report = []
    # 0. auto-test du moteur NTFS sur le vrai C: (lecture seule)
    out = subprocess.run([sys.executable, ENGINE, 'selftest', '--volume', 'C:', '--count', '40'], capture_output=True,
                         text=True, encoding='utf-8', errors='replace')
    try:
        st = json.loads([ln for ln in out.stdout.splitlines() if ln.startswith('{')][-1])
    except Exception:
        st = {'error': out.stdout[-300:] + out.stderr[-300:]}
    log('SELFTEST C: ->', json.dumps(st))
    report.append({'scenario': 'selftest-C', **st})
    only = os.environ.get('LZ_ONLY', '') or (sys.argv[2] if len(sys.argv) > 2 else '') or (sys.argv[2] if len(sys.argv) > 2 else '')
    if not only or 'bitlocker' in only:
        run_bitlocker(report)
    if not only or 'containers' in only:
        run_containers(report)
    if not only or 'fs' in only:
        for fs, size in (('NTFS', 400), ('FAT32', 300), ('exFAT', 300)):
            run_fs(fs, size, report)
    json.dump(report, open(os.path.join(WORK, 'report.json'), 'w'), indent=2)
    log('\nTERMINÉ — rapport :', os.path.join(WORK, 'report.json'))


if __name__ == '__main__':
    main()

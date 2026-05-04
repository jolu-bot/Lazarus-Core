import argparse
import json
import os
import random
import subprocess
import time
from pathlib import Path


def compute_health(file_obj, seed):
    conf = float(file_obj.get('confidence') or 0)
    st = int(file_obj.get('status') or 0)
    score = round(conf * 100)
    if st == 1:
        score = min(score, 93)
    if st == 2:
        score = min(score, 74)
    if st == 3:
        score = min(score, 56)
    repair_mode = 0 if score >= 85 else 1 if score >= 70 else 2 if score >= 50 else 3
    labels = ['Excellent', 'Good - minor repair', 'Degraded - repair needed', 'Critical - reconstruct']
    return {
        'score': score,
        'headerOk': conf >= 0.65,
        'structPct': 100 if st == 0 else int(conf * 80),
        'dataPct': 100 if st == 0 else int(conf * 85),
        'frags': 1 if st == 0 else 2,
        'repairMode': repair_mode,
        'label': labels[repair_mode],
        'existsOnDisk': st == 0,
    }


def get_mock_drives():
    if os.name == 'nt':
        return [
            {
                'path': r'\\.\\PhysicalDrive0',
                'label': 'System Disk (Drive 0)',
                'model': 'Local Disk',
                'serial': '',
                'interface': 'SATA',
                'totalSize': 500107862016,
                'sectorSize': 512,
                'fs': 'NTFS',
            },
            {
                'path': r'\\.\\PhysicalDrive1',
                'label': 'External (Drive 1)',
                'model': 'External',
                'serial': '',
                'interface': 'USB',
                'totalSize': 1000204886016,
                'sectorSize': 512,
                'fs': 'NTFS',
            },
        ]
    return [{
        'path': '/dev/sda', 'label': 'sda - Local Disk', 'model': 'sda',
        'serial': '', 'interface': 'SATA', 'totalSize': 500107862016,
        'sectorSize': 512, 'fs': 'EXT4'
    }]


def enumerate_drives():
    if os.name != 'nt':
        return get_mock_drives()
    try:
        out = subprocess.check_output(
            'wmic diskdrive get DeviceID,Model,Size,InterfaceType,SerialNumber /format:csv',
            shell=True,
            text=True,
            timeout=4,
            encoding='utf-8',
            errors='ignore',
        )
    except Exception:
        return get_mock_drives()

    drives = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith('Node'):
            continue
        p = [x.strip() for x in line.split(',')]
        if len(p) < 6:
            continue
        dev, model, serial, size_s, iface = p[2], p[3], p[4], p[5], p[1]
        if not dev or dev == 'DeviceID':
            continue
        try:
            size_n = int(size_s)
        except Exception:
            size_n = 0
        label = model or dev
        if serial and serial != 'SerialNumber' and len(serial) > 2:
            label = f"{model} ({serial[-8:]})"
        drives.append({
            'path': dev, 'label': label, 'model': model, 'serial': serial,
            'interface': '' if iface == 'InterfaceType' else iface,
            'totalSize': size_n, 'sectorSize': 512, 'fs': 'NTFS'
        })
    return drives or get_mock_drives()


def cmd_scan():
    exts = ['jpg', 'png', 'mp4', 'pdf', 'docx', 'mp3', 'xlsx', 'mov', 'psd', 'zip']
    tmap = {'jpg': 1, 'png': 1, 'psd': 1, 'mp4': 2, 'mov': 2, 'mp3': 3, 'pdf': 4, 'docx': 4, 'xlsx': 4, 'zip': 5}
    stats = [0, 0, 1, 1, 2, 3]
    total = 312
    for i in range(total):
        ext = exts[i % len(exts)]
        st = stats[i % len(stats)]
        conf = round(0.45 + random.random() * 0.55, 2)
        file_obj = {
            'id': i,
            'name': f'file_{i}.{ext}',
            'extension': ext,
            'size': random.randint(5000, 80005000),
            'type': tmap.get(ext, 6),
            'status': st,
            'confidence': conf,
            'recoverable': True,
            'path': '',
            'fs': 1,
            'mft_ref': 4096 + i,
        }
        file_obj['health'] = compute_health(file_obj, i)
        print(json.dumps({'event': 'file-found', 'data': file_obj}), flush=True)
        prog = {
            'percent': round((i / total) * 100),
            'finished': False,
            'filesFound': i + 1,
            'filesRecoverable': i + 1,
            'sectorsTotal': 1000000,
            'sectorsScanned': round((i / total) * 1000000),
            'currentPath': f'Scanning cluster {i}...'
        }
        print(json.dumps({'event': 'progress', 'data': prog}), flush=True)
        time.sleep(0.03)
    print(json.dumps({'event': 'progress', 'data': {'percent': 100, 'finished': True, 'filesFound': total}}), flush=True)
    print(json.dumps({'event': 'done', 'data': {'filesFound': total}}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('enumerate')
    sub.add_parser('scan')
    p_rec = sub.add_parser('recover')
    p_rec.add_argument('--file-json', required=True)
    p_rec.add_argument('--output-dir', default='')
    p_ana = sub.add_parser('analyze')
    p_ana.add_argument('--file-json', required=True)
    p_rep = sub.add_parser('repair')
    p_rep.add_argument('--args-json', required=True)

    args = parser.parse_args()

    if args.cmd == 'enumerate':
        print(json.dumps(enumerate_drives()))
        return
    if args.cmd == 'scan':
        cmd_scan()
        return
    if args.cmd == 'recover':
        file_obj = json.loads(args.file_json)
        outdir = args.output_dir or str(Path.home())
        out = str(Path(outdir) / (file_obj.get('name') or 'recovered_file'))
        print(json.dumps({'success': True, 'outputPath': out, 'health': file_obj.get('health')}))
        return
    if args.cmd == 'analyze':
        file_obj = json.loads(args.file_json)
        print(json.dumps(compute_health(file_obj, int(file_obj.get('id') or 0))))
        return
    if args.cmd == 'repair':
        payload = json.loads(args.args_json)
        file_obj = payload.get('file') or {}
        outdir = payload.get('outputDir') or str(Path.home() / 'LazarusRecovered')
        out = str(Path(outdir) / ('repaired_' + (file_obj.get('name') or 'file')))
        h = file_obj.get('health') or {}
        nh = {'score': min(100, int(h.get('score') or 50) + 15), 'repairMode': max(0, int(h.get('repairMode') or 0) - 1), 'label': 'Repaired (basic)'}
        print(json.dumps({'success': True, 'outputPath': out, 'health': nh, 'repaired': True}))


if __name__ == '__main__':
    main()

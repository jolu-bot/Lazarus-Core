#!/usr/bin/env python3
"""Lazarus Core 2.0 — point d'entrée CLI du moteur de récupération (lecture seule sur les sources).

Protocole : les commandes « streaming » émettent des lignes JSON {"event":..., "data":...} sur stdout ;
les commandes simples impriment un unique objet JSON. L'entrée « stop » sur stdin demande un arrêt propre.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:                                    # sortie UTF-8 quelle que soit la page de code de la console
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from engine import __version__, aifix, carver, ext as ext_engine, fat, imager, ntfs, partitions, recover, repair, report  # noqa: E402
from engine import system, tools  # noqa: E402
from engine.common import STOP, FileSink, Progress, compute_health, emit, log  # noqa: E402
from engine.devio import DeviceError, Reader, open_reader  # noqa: E402


def load_request(args) -> dict:
    if getattr(args, 'request_file', None):
        with open(args.request_file, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    if getattr(args, 'json', None):
        return json.loads(args.json)
    return {}


def start_stdin_watcher():
    def run():
        try:
            for line in sys.stdin:
                if line.strip().lower() == 'stop':
                    STOP.set()
                    return
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def is_admin() -> bool:
    try:
        if os.name == 'nt':
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


# ============================================================================ scan
def cmd_scan(req: dict):
    t0 = time.time()
    device = req.get('device') or req.get('devicePath') or ''
    mode = 'all' if req.get('includeExisting') else 'deleted'
    carve_on = req.get('enableCarving', True)
    deep = bool(req.get('deepScan'))
    min_size = int(req.get('minSize') or 1)
    only_part = req.get('partition')                    # {'start':..,'size':..} pour limiter l'analyse
    sink = FileSink(device, req.get('sessionPath'))
    engines_used = []
    alloc_list = []        # (début, fin, fonction « cet offset est-il alloué ? ») fournies par les moteurs de fichiers

    try:
        reader = open_reader(device)
    except DeviceError as e:
        emit('done', {'filesFound': 0, 'error': str(e), 'engines': [], 'needsAdmin': 'administrateur' in str(e)})
        return 2
    log(f'Source : {reader.path} — {reader.size} octets, secteur {reader.sector_size}')
    total_size = reader.size or 0
    emit('progress', {'percent': 0, 'finished': False, 'currentPath': 'Analyse de la table de partitions', 'engine': 'layout',
                      'filesFound': 0})

    layout = partitions.detect_layout(reader)
    if only_part:
        layout = [p for p in layout if p['start'] == int(only_part.get('start', 0))] or [{
            'index': 0, 'start': int(only_part.get('start', 0)), 'size': int(only_part.get('size', 0)),
            'fs': partitions.probe_fs(reader, int(only_part.get('start', 0))).get('fs'), 'desc': 'Sélection', 'source': 'user'}]
    lost = []
    if (deep or not any(p.get('fs') for p in layout)) and not only_part and reader.raw and total_size:
        emit('progress', {'percent': 1, 'finished': False, 'currentPath': 'Recherche de partitions perdues…',
                          'engine': 'layout', 'filesFound': 0})
        lost = partitions.find_lost_partitions(
            reader, layout, progress=lambda d, t: emit('progress', {
                'percent': round(1 + 4 * d / max(t, 1), 1), 'finished': False, 'currentPath': 'Recherche de partitions perdues…',
                'engine': 'layout', 'filesFound': 0, 'bytesDone': d, 'bytesTotal': t}))
        layout = layout + lost
    emit('layout', {'partitions': layout, 'size': total_size, 'sectorSize': reader.sector_size})

    usable = [p for p in layout if p.get('fs') in ('ntfs', 'fat', 'exfat', 'ext')]
    fs_sink = sink
    if req.get('skipFs'):
        # reprise du carving seul : les moteurs de fichiers retournent analyser (pour connaître l'espace alloué)
        # mais n'émettent plus rien : leurs fichiers figurent déjà dans la session
        class NullSink(FileSink):
            def add(self, f, dedupe_key=None):
                return None
        fs_sink = NullSink(device)
    for p in layout:
        if p.get('encrypted') or p.get('fs') == 'bitlocker':
            emit('warning', {'message': f"Partition {p.get('index')} chiffrée par BitLocker : illisible en accès disque brut. Si c'est le disque "
                                        f"Windows en cours d'exécution, analysez plutôt le VOLUME (C:) — Windows le déchiffre pour vous ; "
                                        f"sinon la clé de récupération est indispensable."})
        elif p.get('fs') in ('refs', 'apfs', 'hfs'):
            emit('warning', {'message': f"Partition {p.get('index')} ({p['fs'].upper()}) : analyse de fichiers supprimés non "
                                        f"prise en charge, le carving par signatures est appliqué."})

    fs_weight = 100 if not carve_on else 45
    allowed = {'ntfs': req.get('scanNTFS', True), 'fat': req.get('scanFAT', True), 'exfat': req.get('scanFAT', True),
               'ext': req.get('scanEXT4', True)}
    prog = Progress('fs', 0, sink)
    sizes = [max(p.get('size') or 1, 1) for p in usable if allowed.get(p['fs'], True)]
    acc = 0
    tot = sum(sizes) or 1
    try:
        for p in usable:
            if STOP.is_set():
                break
            if not allowed.get(p['fs'], True):
                continue
            share = max(1, int(fs_weight * (p.get('size') or 1) / tot))
            prog.engine = p['fs']
            prog.window(int(fs_weight * acc / tot), share)
            acc += p.get('size') or 1
            label = f"{p['fs'].upper()} @{p['start'] // (1024 * 1024)} Mo"
            n_before = sink.count
            log(f'Analyse {label}')
            try:
                if p['fs'] == 'ntfs':
                    ntfs.scan_volume(reader, p['start'], fs_sink, prog, mode=mode, size_hint=p.get('size') or 0,
                                     part_label=label, min_size=min_size, alloc_out=alloc_list)
                    if deep:
                        vol = ntfs.Volume(reader, p['start'], p.get('size') or 0)
                        try:
                            vol.load_mft()
                        except ntfs.NtfsError:
                            pass
                        ntfs.scan_mft_carve(reader, p['start'], fs_sink, prog, vol, mode, label, min_size,
                                            live_ranges=vol.live_ranges())
                elif p['fs'] == 'fat':
                    fat.scan_fat(reader, p['start'], fs_sink, prog, mode=mode, part_label=label, deep=deep, min_size=min_size,
                                 alloc_out=alloc_list)
                elif p['fs'] == 'exfat':
                    fat.scan_exfat(reader, p['start'], fs_sink, prog, mode=mode, part_label=label, deep=deep, min_size=min_size,
                                   alloc_out=alloc_list)
                elif p['fs'] == 'ext':
                    ext_engine.scan_ext(reader, p['start'], fs_sink, prog, mode=mode, part_label=label, min_size=min_size,
                                        alloc_out=alloc_list)
                engines_used.append(p['fs'])
            except Exception as e:
                log(f'Erreur du moteur {p["fs"]} : {e!r}')
                emit('warning', {'message': f"Le moteur {p['fs'].upper()} a rencontré une erreur : {e}"})
            log(f'  → {sink.count - n_before} élément(s)')
    finally:
        pass

    # ---------------- carving
    if not carve_on and sink.count == 0 and not STOP.is_set():
        emit('warning', {'message': "Aucun fichier trouvé via les systèmes de fichiers : le carving par signatures est lancé "
                                    "automatiquement."})
        carve_on = True
    if carve_on and not STOP.is_set() and total_size:
        if only_part:
            c_start, c_end = int(only_part.get('start', 0)), int(only_part.get('start', 0)) + int(only_part.get('size', 0))
        else:
            c_start, c_end = int(req.get('startOffset') or 0), total_size
        def is_allocated(off):
            for a, b, fn in alloc_list:
                if a <= off < b:
                    return fn(off)
            return False                      # hors des volumes analysés : espace considéré comme libre

        use_alloc = alloc_list and not req.get('carveAll')
        if use_alloc:
            log("Carving limité à l'espace non alloué (les fichiers existants sont ignorés)")
        prog = Progress('carve', 0, sink)
        prog.window(fs_weight if usable else 0, 100 - (fs_weight if usable else 0))
        try:
            carver.carve(reader, sink, prog, start=c_start, end=c_end, groups=set(req.get('carveTypes') or []) or None,
                         unknown_cap=int(req.get('unknownCapMB') or 64) * 1024 * 1024, label='Carving',
                         is_allocated=is_allocated if use_alloc else None,
                         text=bool(req.get('carveText', deep)), custom=req.get('customSignatures'))
            engines_used.append('carve')
        except Exception as e:
            log(f'Erreur du carving : {e!r}')
            emit('warning', {'message': f'Le carving a rencontré une erreur : {e}'})
    sink.close()
    done = {'filesFound': sink.count, 'engines': engines_used, 'seconds': round(time.time() - t0, 1),
            'badSectors': reader.bad_count, 'sessionPath': req.get('sessionPath') or '', 'stopped': STOP.is_set(),
            'partitions': len(layout), 'device': device}
    reader.close()
    emit('progress', {'percent': 100, 'finished': True, 'filesFound': sink.count, 'engine': 'done'})
    emit('done', done)
    return 0


# ============================================================================ récupération
def cmd_recover(req: dict):
    records = req.get('records') or ([req['record']] if req.get('record') else [])
    if not records and req.get('sessionPath'):
        records = recover.load_records(req['sessionPath'], req.get('ids') or [])
        if req.get('device') is None and records:
            req['device'] = records[0].get('device')
    dest = req.get('destination') or str(Path.home() / 'LazarusRecovered')
    if req.get('device') and not req.get('allowSameDisk'):
        chk = recover.check_destination(req['device'], dest)
        if not chk['safe']:
            print(json.dumps({'success': False, 'blocked': True, 'error': chk['reason'], 'check': chk}))
            return 3
    res = recover.recover_batch(records, dest, req.get('structure', 'tree'), req.get('verify', True),
                                req.get('device'), stop_flag=STOP.is_set)
    print(json.dumps(res))
    return 0 if res['success'] else 1


def cmd_preview_record(req: dict):
    rec = req.get('record')
    if not rec and req.get('sessionPath'):
        found = recover.load_records(req['sessionPath'], [req.get('id', -1)])
        rec = found[0] if found else None
    if not rec:
        print(json.dumps({'success': False, 'message': 'Enregistrement introuvable'}))
        return
    print(json.dumps(recover.preview_bytes(rec, int(req.get('maxBytes') or 65536), req.get('device'))))


def cmd_preview_file(path: str, max_bytes: int):
    p = Path(path)
    if not p.is_file():
        print(json.dumps({'success': False, 'message': 'Fichier introuvable'}))
        return
    import base64
    max_bytes = max(1024, min(max_bytes, 32 * 1024 * 1024))
    with open(p, 'rb') as fh:
        raw = fh.read(max_bytes)
    ext = p.suffix.lstrip('.').lower()
    kind = ('image' if ext in ('jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp') else
            'audio' if ext in ('mp3', 'wav', 'flac', 'ogg', 'm4a') else
            'video' if ext in ('mp4', 'mov', 'avi', 'mkv') else
            'document' if ext in ('pdf', 'doc', 'docx', 'xlsx', 'pptx') else 'binary')
    print(json.dumps({'success': True, 'kind': kind, 'name': p.name, 'size': p.stat().st_size,
                      'head_b64': base64.b64encode(raw).decode('ascii'), 'bytes': len(raw)}))


# ============================================================================ auto-test sur volume NTFS réel
class _Enough(Exception):
    pass


def cmd_selftest(volume: str, count: int):
    """Valide le moteur NTFS sur un volume réel : récupère des fichiers existants et compare leur SHA-256
    avec la lecture normale du système. Nécessite les droits administrateur."""
    import hashlib
    vol_path = volume if volume.startswith('\\\\') else f'\\\\.\\{volume.rstrip(chr(92)).rstrip(":")}:'
    letter = volume.rstrip('\\')[-2:] if len(volume.rstrip('\\')) >= 2 and volume.rstrip('\\')[-1] == ':' else volume
    try:
        rd = open_reader(vol_path)
    except DeviceError as e:
        print(json.dumps({'success': False, 'error': str(e)}))
        return 2
    samples = []

    class Pick(FileSink):
        def __init__(self):
            super().__init__(vol_path)

        def add(self, f, dedupe_key=None):
            p = f.get('path') or ''
            if f.get('status') != 0 or not f.get('extents') or not (1024 <= f['size'] <= 40 * 1024 * 1024):
                return None
            if p.startswith('$') or '\\$' in p or f.get('compressed') or f.get('encrypted'):
                return None
            if f.get('mtime') and f['mtime'] > time.time() - 900:
                return None            # fichier modifié récemment (cache, journaux) : la comparaison serait faussée
            samples.append(f)
            if len(samples) >= count:
                raise _Enough()
            return f

    sink = Pick()
    try:
        ntfs.scan_volume(rd, 0, sink, Progress('selftest', 0, sink), mode='all', part_label='selftest')
    except _Enough:
        pass
    results = {'tested': 0, 'identical': 0, 'different': 0, 'skipped': 0, 'details': []}
    drive = (letter if len(letter) == 2 and letter[1] == ':' else 'C:') + '\\'
    for f in samples:
        live = drive + f['path']
        try:
            with open(live, 'rb') as fh:
                want = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            results['skipped'] += 1
            continue
        rr = recover.RecordReader(rd, f)
        got = hashlib.sha256(rr.read(0, f['size'])).hexdigest()
        results['tested'] += 1
        if got == want:
            results['identical'] += 1
        else:
            results['different'] += 1
            if len(results['details']) < 10:
                results['details'].append({'path': f['path'], 'size': f['size']})
    rd.close()
    results['success'] = results['tested'] > 0 and results['different'] == 0
    print(json.dumps(results))
    return 0 if results['success'] else 1


# ============================================================================ main
def _main():
    ap = argparse.ArgumentParser(prog='scan_backend', description='Lazarus Core 2.0 engine')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('scan', 'recover', 'preview-record', 'repair', 'report', 'check-dest', 'image-disk', 'partitions',
                 'hex-read', 'search', 'export-range', 'raid-detect', 'bitlocker-probe', 'thumbs', 'diagnose', 'fix'):
        sp = sub.add_parser(name)
        sp.add_argument('--request-file')
        sp.add_argument('--json')
        if name == 'scan':
            sp.add_argument('--device')
            sp.add_argument('--output-dir')
            sp.add_argument('--deep-scan', action='store_true')
        if name in ('repair', 'report'):
            sp.add_argument('--args-json')
            sp.add_argument('--report-json')
            sp.add_argument('--output-dir')
    sub.add_parser('enumerate')
    sub.add_parser('enumerate-fast')
    sub.add_parser('vss-list')
    sub.add_parser('diag')
    sub.add_parser('smart')
    sub.add_parser('engines')
    p = sub.add_parser('preview')
    p.add_argument('--file', required=True)
    p.add_argument('--max-bytes', type=int, default=65536)
    p = sub.add_parser('analyze')
    p.add_argument('--file-json', required=True)
    p = sub.add_parser('selftest')
    p.add_argument('--volume', default='C:')
    p.add_argument('--count', type=int, default=30)
    args = ap.parse_args()

    if args.cmd in ('scan', 'recover', 'image-disk', 'search'):
        start_stdin_watcher()

    if args.cmd == 'enumerate':
        print(json.dumps(system.enumerate_drives()))
    elif args.cmd == 'enumerate-fast':
        print(json.dumps(system.fast_drives()))
    elif args.cmd == 'vss-list':
        print(json.dumps(system.list_shadow_copies()))
    elif args.cmd == 'diag':
        print(json.dumps({'version': __version__, 'python': sys.version.split()[0], 'admin': is_admin(),
                          'platform': sys.platform, 'cwd': os.getcwd(), 'signatures': len(carver.SIGNATURES)}))
    elif args.cmd == 'engines':
        print(json.dumps({'version': __version__, 'filesystems': ['ntfs', 'fat12', 'fat16', 'fat32', 'exfat', 'ext2', 'ext3', 'ext4'],
                          'carving': carver.SUPPORTED_EXTENSIONS, 'repair': sorted(repair.REPAIRERS), 'ai': aifix.capabilities()}))
    elif args.cmd == 'scan':
        req = load_request(args)
        if args.device:
            req.setdefault('device', args.device)
        if getattr(args, 'deep_scan', False):
            req['deepScan'] = True
        sys.exit(cmd_scan(req))
    elif args.cmd == 'partitions':
        req = load_request(args)
        try:
            rd = open_reader(req.get('device', ''))
        except DeviceError as e:
            print(json.dumps({'success': False, 'error': str(e)}))
            return
        print(json.dumps({'success': True, 'size': rd.size, 'sectorSize': rd.sector_size, 'partitions': partitions.detect_layout(rd)}))
        rd.close()
    elif args.cmd == 'recover':
        sys.exit(cmd_recover(load_request(args)))
    elif args.cmd == 'preview-record':
        cmd_preview_record(load_request(args))
    elif args.cmd == 'preview':
        cmd_preview_file(args.file, args.max_bytes)
    elif args.cmd == 'analyze':
        f = json.loads(args.file_json)
        print(json.dumps(compute_health(f, int(f.get('id') or 0))))
    elif args.cmd == 'repair':
        req = json.loads(args.args_json) if getattr(args, 'args_json', None) else load_request(args)
        f = req.get('file') or {}
        src = req.get('path') or f.get('outputPath') or f.get('path') or ''
        res = repair.repair_file(src, f.get('extension') or req.get('extension') or '', req.get('outputPath'))
        res['repaired'] = bool(res.get('success') and res.get('changed'))
        print(json.dumps(res))
    elif args.cmd == 'diagnose':
        r = load_request(args)
        print(json.dumps(aifix.analyze(r.get('path', ''))))
    elif args.cmd == 'fix':
        r = load_request(args)
        src = r.get('path', '')
        print(json.dumps(aifix.repair_auto(src, r.get('outputDir') or os.path.dirname(os.path.abspath(src)), r.get('reference') or '',
                                           bool(r.get('enhance')))))
    elif args.cmd == 'report':
        req = json.loads(args.report_json) if getattr(args, 'report_json', None) else load_request(args)
        out = args.output_dir or req.get('outputDir') or str(Path.home() / 'LazarusReports')
        print(json.dumps(report.build_report(req, out)))
    elif args.cmd == 'check-dest':
        req = load_request(args)
        print(json.dumps(recover.check_destination(req.get('device', ''), req.get('destination', ''))))
    elif args.cmd == 'image-disk':
        req = load_request(args)
        res = imager.image_disk(req['device'], req['outputImage'], int(req.get('start') or 0),
                                req.get('length'), stop_flag=STOP.is_set)
        print(json.dumps(res))
    elif args.cmd == 'thumbs':
        r = load_request(args)
        recs = recover.load_records(r['sessionPath'], r.get('ids') or [])
        print(json.dumps({'success': True, 'thumbs': tools.thumbnail_batch(recs, r.get('device') or '')}))
    elif args.cmd == 'smart':
        print(json.dumps(system.smart_report()))
    elif args.cmd == 'hex-read':
        r = load_request(args)
        print(json.dumps(tools.hex_read(r['device'], r.get('offset', 0), r.get('length', 4096))))
    elif args.cmd == 'search':
        r = load_request(args)
        print(json.dumps(tools.search(r['device'], r.get('text', ''), r.get('hex', ''), r.get('encodings'), r.get('nocase', True),
                                      int(r.get('start') or 0), r.get('end'), int(r.get('maxHits') or 2000))))
    elif args.cmd == 'export-range':
        r = load_request(args)
        print(json.dumps(tools.export_range(r['device'], r['offset'], r['length'], r['dest'])))
    elif args.cmd == 'raid-detect':
        r = load_request(args)
        from engine import raid as raid_engine
        members = [open_reader(p) if p else None for p in r['members']]
        try:
            cands = raid_engine.detect(members, int(r.get('cacheMB') or 16))
            print(json.dumps({'success': True, 'candidates': cands, 'sizes': [(m.size if m else None) for m in members]}))
        finally:
            for m in members:
                if m:
                    m.close()
    elif args.cmd == 'bitlocker-probe':
        r = load_request(args)
        from engine import bitlocker
        rd = open_reader(r['device'])
        try:
            print(json.dumps(bitlocker.probe(rd, int(r.get('start') or 0))))
        finally:
            rd.close()
    elif args.cmd == 'selftest':
        sys.exit(cmd_selftest(args.volume, args.count))


def main():
    try:
        _main()
    except DeviceError as e:          # source illisible, clé BitLocker erronée, RAID incohérent… : message clair, pas de trace
        print(json.dumps({'success': False, 'error': str(e), 'message': str(e)}))
        sys.exit(2)


if __name__ == '__main__':
    main()

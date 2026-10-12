"""Outil de validation : vérifie les validateurs du carver sur des FICHIERS RÉELS de cette machine.

Usage : python tests/tools/validate_carver_on_real_files.py [dossier ...]
Les fichiers trouvés sont placés dans une image temporaire (séparés par du bruit aléatoire), le carver est lancé
et l'offset/la taille de chaque fichier retrouvé sont comparés. Rien n'est écrit hors du fichier temporaire.
"""
import os, sys, random, tempfile, collections, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'app', 'main', 'ipc')); sys.path.insert(0, os.path.join(ROOT, 'tests', 'engine'))
from engine import carver, common
from engine.devio import Reader
from test_ntfs import Collector

WANT = {'jpg': 60, 'png': 80, 'gif': 30, 'bmp': 20, 'pdf': 30, 'zip': 25, 'docx': 15, 'xlsx': 10, 'mp4': 15, 'mp3': 20,
        'wav': 20, 'exe': 40, 'dll': 60, 'sqlite': 15, 'ico': 0, 'gz': 20, 'ogg': 10, 'tif': 10, '7z': 5, 'doc': 8, 'xls': 8,
        'webp': 10, 'avi': 5, 'mkv': 5, 'cab': 10}
EXT_ALIAS = {'jpeg': 'jpg', 'db': 'sqlite', 'sqlite3': 'sqlite', 'tiff': 'tif'}
roots = sys.argv[1:] or ([r'C:\Windows', r'C:\Program Files', r'C:\Program Files (x86)'] if os.name == 'nt' else ['/usr', '/opt'])
found = collections.defaultdict(list)
t0 = time.time()
for r in roots:
    for dp, dn, fn in os.walk(r):
        if time.time() - t0 > 150:
            break
        for f in fn:
            e = f.rsplit('.', 1)[-1].lower() if '.' in f else ''
            e = EXT_ALIAS.get(e, e)
            if e in WANT and len(found[e]) < WANT[e]:
                p = os.path.join(dp, f)
                try:
                    sz = os.path.getsize(p)
                    if 200 <= sz <= 40 * 1024 * 1024:
                        found[e].append(p)
                except OSError:
                    pass
print({k: len(v) for k, v in found.items()}, f'scan {time.time()-t0:.0f}s')

rnd = random.Random(1)
img = tempfile.NamedTemporaryFile(delete=False, suffix='.img')
exp = []   # (offset, size, ext, path)
pos = 0
ss = 512
for ext, paths in found.items():
    for p in paths:
        try:
            data = open(p, 'rb').read()
        except OSError:
            continue
        gap = rnd.randrange(1, 12) * ss
        img.write(rnd.randbytes(gap)); pos += gap
        exp.append((pos, len(data), ext, p))
        img.write(data); pos += len(data)
        pad = (-pos) % ss
        img.write(rnd.randbytes(pad)); pos += pad
img.close()
print('image', pos // (1024 * 1024), 'Mo,', len(exp), 'fichiers')
r = Reader(img.name)
sink = Collector(); sink.starts = set()
carver.carve(r, sink, common.Progress('c', 0, sink))
by_off = {}
for f in sink.files:
    by_off.setdefault(f['extents'][0][0], f)
stats = collections.defaultdict(lambda: [0, 0, 0, 0])   # total, exact, wrongsize, missed
bad = []
for off, size, ext, p in exp:
    s = stats[ext]; s[0] += 1
    f = by_off.get(off)
    if f is None:
        s[3] += 1; bad.append(('MANQUE', ext, size, p))
    elif f['size'] == size and f['size_known']:
        s[1] += 1
    elif f['size'] == size:
        s[1] += 1
    else:
        s[2] += 1; bad.append(('TAILLE', ext, size, f['size'], f['extension'], f.get('size_known'), p))
tot = [0, 0, 0, 0]
for ext, s in sorted(stats.items()):
    print(f'{ext:7s} total={s[0]:3d} exact={s[1]:3d} taille_diff={s[2]:3d} manques={s[3]:3d}')
    for i in range(4): tot[i] += s[i]
print('TOTAL', tot)
extra = [f for off, f in by_off.items() if off not in {e[0] for e in exp}]
print('faux positifs:', len(extra), [(f['extension'], f['size']) for f in extra[:10]])
for b in bad[:40]:
    print(b)
r.close(); os.unlink(img.name)

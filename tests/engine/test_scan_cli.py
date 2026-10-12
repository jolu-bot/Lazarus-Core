"""Test de bout en bout du CLI : analyse (NTFS + carving limité à l'espace non alloué) puis récupération."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
IPC = os.path.abspath(os.path.join(HERE, '..', '..', 'app', 'main', 'ipc'))
sys.path.insert(0, IPC)

import ntfs_image  # noqa: E402
from test_carver import make_png  # noqa: E402


def run(cmd, req):
    d = tempfile.mkdtemp()
    rf = os.path.join(d, 'req.json')
    json.dump(req, open(rf, 'w'))
    out = subprocess.run([sys.executable, '-I', os.path.join(IPC, 'scan_backend.py'), cmd, '--request-file', rf],
                         capture_output=True, text=True, input='', encoding='utf-8')
    events, result = [], None
    for line in out.stdout.splitlines():
        if not line.startswith(('{', '[')):
            continue
        o = json.loads(line)
        if isinstance(o, dict) and 'event' in o:
            events.append(o)
        else:
            result = o
    return out, events, result


class ScanCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        img, cls.truth = ntfs_image.build_image()
        cls.png = make_png()
        cs = ntfs_image.CS
        # PNG dans un cluster LIBRE (200) et un autre dans un cluster ALLOUÉ (clusters 50-53 : big.bin réalloué)
        img[200 * cs:200 * cs + len(cls.png)] = cls.png
        img[51 * cs:51 * cs + len(cls.png)] = cls.png
        fd, cls.path = tempfile.mkstemp(suffix='.img')
        os.write(fd, bytes(img))
        os.close(fd)
        cls.cs = cs

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def carved(self, events):
        return [e['data'] for e in events if e['event'] == 'file-found' and e['data']['source'] == 'carve']

    def test_carving_only_unallocated_space(self):
        out, events, _ = run('scan', {'device': self.path, 'enableCarving': True})
        self.assertEqual(out.returncode, 0, out.stderr)
        offs = [c['extents'][0][0] for c in self.carved(events)]
        self.assertIn(200 * self.cs, offs)
        self.assertNotIn(51 * self.cs, offs)       # espace alloué ignoré

    def test_carving_everything_when_requested(self):
        _, events, _ = run('scan', {'device': self.path, 'enableCarving': True, 'carveAll': True})
        offs = [c['extents'][0][0] for c in self.carved(events)]
        self.assertIn(200 * self.cs, offs)
        self.assertIn(51 * self.cs, offs)

    def test_carved_file_recovery_via_session(self):
        d = tempfile.mkdtemp()
        sess = os.path.join(d, 's.jsonl')
        _, events, _ = run('scan', {'device': self.path, 'enableCarving': True, 'sessionPath': sess})
        rec = [c for c in self.carved(events) if c['extents'][0][0] == 200 * self.cs][0]
        out_dir = os.path.join(d, 'out')
        o, ev, res = run('recover', {'sessionPath': sess, 'ids': [rec['id']], 'destination': out_dir})
        self.assertTrue(res['success'], o.stderr)
        r = res['results'][0]
        self.assertEqual(open(r['outputPath'], 'rb').read(), self.png)
        self.assertEqual(r['integrity'], 'ok')

    def test_resume_keeps_ids_unique(self):
        d = tempfile.mkdtemp()
        sess = os.path.join(d, 's.jsonl')
        _, ev1, _ = run('scan', {'device': self.path, 'enableCarving': True, 'sessionPath': sess})
        n1 = len([e for e in ev1 if e['event'] == 'file-found'])
        # reprise : les moteurs de fichiers retournent analyser (espace alloué) sans rien ré-émettre, le carving continue
        _, ev2, _ = run('scan', {'device': self.path, 'enableCarving': True, 'skipFs': True, 'startOffset': 0,
                                 'sessionPath': sess})
        ids = [json.loads(line)['id'] for line in open(sess, encoding='utf-8')]
        self.assertEqual(len(ids), len(set(ids)))                       # identifiants jamais réutilisés
        self.assertGreater(max(ids), n1 - 1)
        fs_events = [e for e in ev2 if e['event'] == 'file-found' and e['data']['source'] != 'carve']
        self.assertEqual(fs_events, [])                                 # aucun doublon issu des moteurs de fichiers

    def test_stop_via_stdin(self):
        d = tempfile.mkdtemp()
        rf = os.path.join(d, 'r.json')
        json.dump({'device': self.path, 'enableCarving': True, 'carveAll': True}, open(rf, 'w'))
        p = subprocess.Popen([sys.executable, '-I', os.path.join(IPC, 'scan_backend.py'), 'scan', '--request-file', rf],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, _ = p.communicate('stop\n', timeout=60)
        self.assertEqual(p.returncode, 0)
        last = [json.loads(line) for line in out.splitlines() if line.startswith('{')][-1]
        self.assertEqual(last['event'], 'done')


if __name__ == '__main__':
    unittest.main()

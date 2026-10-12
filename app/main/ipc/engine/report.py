"""Rapport de récupération (JSON + HTML) avec empreintes — contenu échappé (aucune injection HTML)."""
from __future__ import annotations

import datetime
import html
import json
import os
from typing import Dict, List

STYLE = """
body{font-family:Segoe UI,Arial,sans-serif;background:#0d1117;color:#c9d1d9;margin:0;padding:28px;line-height:1.45}
h1{color:#58a6ff;border-bottom:1px solid #30363d;padding-bottom:8px}h2{color:#8b949e;font-size:14px;margin-top:24px;text-transform:uppercase}
table{border-collapse:collapse;width:100%;font-size:12px;margin-top:8px}
th{background:#161b22;color:#8b949e;text-align:left;padding:6px 10px;border:1px solid #30363d}
td{padding:5px 10px;border:1px solid #30363d;vertical-align:top;word-break:break-all}
tr:hover td{background:#161b22}.ok{color:#3fb950}.warn{color:#d29922}.bad{color:#f85149}.info{color:#58a6ff}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px;margin:16px 0}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px}
.v{font-size:22px;font-weight:700;color:#58a6ff}.l{font-size:11px;color:#8b949e;margin-top:4px}
code{background:#161b22;padding:1px 5px;border-radius:4px}
"""


def fmt_size(n: int) -> str:
    n = int(n or 0)
    for unit, div in (('Go', 1 << 30), ('Mo', 1 << 20), ('Ko', 1 << 10)):
        if n >= div:
            return f'{n / div:.2f} {unit}' if unit == 'Go' else f'{n / div:.1f} {unit}'
    return f'{n} o'


def build_report(report_obj: dict, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    files: List[dict] = report_obj.get('files') or []
    device = str(report_obj.get('device') or 'inconnu')
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime('%Y%m%d_%H%M%S')
    by_ext: Dict[str, int] = {}
    by_src: Dict[str, int] = {}
    scores: List[int] = []
    total = 0
    rows = []
    for f in files:
        ext = (f.get('extension') or '?').lower()
        by_ext[ext] = by_ext.get(ext, 0) + 1
        src = f.get('source') or 'inconnu'
        by_src[src] = by_src.get(src, 0) + 1
        h = f.get('health') or {}
        sc = int(h.get('score') if isinstance(h, dict) and h.get('score') is not None else round((f.get('confidence') or 0) * 100))
        scores.append(sc)
        size = int(f.get('size') or 0)
        total += size
        rows.append({
            'id': f.get('id'), 'nom': f.get('name') or '', 'chemin': f.get('path') or '', 'extension': ext,
            'taille': size, 'sante': sc, 'source': src, 'statut': f.get('status'),
            'recupere_vers': f.get('outputPath') or '', 'md5': (f.get('hashes') or {}).get('md5') or f.get('md5') or '',
            'sha256': (f.get('hashes') or {}).get('sha256') or f.get('sha256') or '',
            'integrite': f.get('integrity') or '',
        })
    avg = round(sum(scores) / len(scores)) if scores else 0
    summary = {'fichiers': len(files), 'octets_total': total, 'sante_moyenne': avg,
               'excellents': sum(1 for s in scores if s >= 85), 'recuperables': sum(1 for s in scores if s >= 50),
               'par_extension': by_ext, 'par_moteur': by_src}
    doc = {'outil': 'Lazarus Core 2.0', 'genere_le': now.isoformat().replace('+00:00', 'Z'),
           'source': device, 'debut_analyse': report_obj.get('scanStarted', ''), 'fin_analyse': report_obj.get('scanEnded', ''),
           'resume': summary, 'fichiers': rows}
    jpath = os.path.join(out_dir, f'lazarus_rapport_{stamp}.json')
    with open(jpath, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)

    e = html.escape

    def cls(s):
        return 'ok' if s >= 85 else 'warn' if s >= 50 else 'bad'
    trs = ''.join(
        f'<tr><td>{e(str(r["id"]))}</td><td>{e(r["nom"])}</td><td>{e(r["chemin"])}</td><td>{e(r["extension"])}</td>'
        f'<td>{fmt_size(r["taille"])}</td><td class="{cls(r["sante"])}">{r["sante"]} %</td><td>{e(r["source"])}</td>'
        f'<td>{e(r["integrite"])}</td><td><code>{e(r["sha256"][:16])}</code></td></tr>' for r in rows)
    top = ''.join(f'<tr><td>.{e(k)}</td><td>{v}</td></tr>' for k, v in sorted(by_ext.items(), key=lambda x: -x[1])[:12])
    srcs = ''.join(f'<tr><td>{e(k)}</td><td>{v}</td></tr>' for k, v in sorted(by_src.items(), key=lambda x: -x[1]))
    page = f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><title>Lazarus Core — Rapport de récupération</title>
<style>{STYLE}</style></head><body>
<h1>Lazarus Core — Rapport de récupération</h1>
<p>Généré le {e(now.strftime('%Y-%m-%d %H:%M:%S'))} UTC &nbsp;|&nbsp; Source : <code>{e(device)}</code></p>
<div class="grid">
<div class="card"><div class="v">{len(files)}</div><div class="l">Fichiers</div></div>
<div class="card"><div class="v">{fmt_size(total)}</div><div class="l">Volume total</div></div>
<div class="card"><div class="v">{avg} %</div><div class="l">Santé moyenne</div></div>
<div class="card"><div class="v">{summary['excellents']}</div><div class="l">Excellents (≥ 85 %)</div></div>
<div class="card"><div class="v">{summary['recuperables']}</div><div class="l">Récupérables (≥ 50 %)</div></div></div>
<h2>Extensions principales</h2><table><tr><th>Extension</th><th>Nombre</th></tr>{top}</table>
<h2>Moteurs</h2><table><tr><th>Moteur</th><th>Nombre</th></tr>{srcs}</table>
<h2>Détail des fichiers</h2>
<table><tr><th>#</th><th>Nom</th><th>Chemin</th><th>Ext.</th><th>Taille</th><th>Santé</th><th>Moteur</th><th>Intégrité</th><th>SHA-256</th></tr>{trs}</table>
<p style="margin-top:30px;color:#8b949e;font-size:11px">Les empreintes complètes figurent dans le fichier JSON associé.</p>
</body></html>"""
    hpath = os.path.join(out_dir, f'lazarus_rapport_{stamp}.html')
    with open(hpath, 'w', encoding='utf-8') as fh:
        fh.write(page)
    return {'success': True, 'jsonPath': jpath, 'htmlPath': hpath, 'totalFiles': len(files), 'totalBytes': total}

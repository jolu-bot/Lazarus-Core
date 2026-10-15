"""Reconstruction de zones d'image manquantes (OpenCV, sans modèle externe).

Cas dominant — le bas d'une photo tronquée : les couleurs de la dernière ligne valide sont prolongées puis ramenées
progressivement vers la couleur moyenne des colonnes voisines (l'incertitude augmente avec la distance), et le grain de la
zone valide est réfléchi par-dessus pour éviter l'aspect « lissé ». Aucun objet n'est dupliqué. Tout autre masque passe par
un inpainting TELEA + Navier-Stokes.
Le résultat est une estimation plausible, jamais une restitution exacte : l'interface le signale.
"""
from __future__ import annotations


def reconstruct(base, mask):
    """``base`` : image BGR uint8 ; ``mask`` : uint8, 255 = pixels à reconstruire. Retourne l'image complétée."""
    import numpy as np

    h, w = mask.shape
    rows = np.where(mask.any(axis=1))[0]
    if rows.size == 0:
        return base
    top = int(rows.min())
    if top >= 8 and mask[top:].all() and not mask[:top].any():
        return _bottom_band(base, top)
    return _generic(base, mask)


def _bottom_band(img, top: int):
    import cv2
    import numpy as np

    h, w = img.shape[:2]
    band = h - top
    src = img.astype(np.float32)
    idx = np.arange(band)
    j = idx % (2 * top)
    refl = np.where(j < top, top - 1 - j, j - top)                    # réflexion répétée si la bande dépasse la zone valide
    mirror = src[refl]

    tau = max(24.0, 0.12 * h)
    t = (1.0 - np.exp(-(idx + 0.5) / tau)).astype(np.float32)[:, None, None]

    # basses fréquences : prolongation de la frontière (sans dupliquer les objets), puis retour vers la couleur moyenne des colonnes
    k3 = min(3, top)
    edge = src[top - k3:top].mean(axis=0, keepdims=True)
    edge = cv2.GaussianBlur(np.repeat(edge, 3, axis=0), (0, 0), 3.0)[:1]
    k = max(4, min(top, int(0.2 * h)))
    colmean = src[top - k:top].mean(axis=0, keepdims=True)
    colmean = cv2.GaussianBlur(np.repeat(colmean, 3, axis=0), (0, 0), max(4.0, w * 0.05))[:1]
    lowfreq = (1.0 - t) * np.repeat(edge, band, axis=0) + t * np.repeat(colmean, band, axis=0)

    # hautes fréquences : grain et texture de la zone valide voisine, réfléchis (ne contient plus la structure de l'image)
    detail = mirror - cv2.GaussianBlur(mirror, (0, 0), 2.5)
    out = lowfreq + detail * 0.5

    res = src.copy()
    res[top:] = out
    return np.clip(res, 0, 255).astype(np.uint8)


def _generic(base, mask):
    import cv2
    import numpy as np

    h, w = mask.shape
    scale = min(1.0, 640.0 / max(h, w))
    sm = cv2.resize(base, (max(8, int(w * scale)), max(8, int(h * scale))), interpolation=cv2.INTER_AREA) if scale < 1 else base.copy()
    mk = cv2.resize(mask, (sm.shape[1], sm.shape[0]), interpolation=cv2.INTER_NEAREST) if scale < 1 else mask
    mk = cv2.dilate(mk, np.ones((3, 3), np.uint8))
    rad = max(3, int(min(sm.shape[:2]) * 0.03))
    low = cv2.addWeighted(cv2.inpaint(sm, mk, rad, cv2.INPAINT_TELEA), 0.5, cv2.inpaint(sm, mk, rad, cv2.INPAINT_NS), 0.5, 0)
    if scale < 1:
        low = cv2.resize(low, (w, h), interpolation=cv2.INTER_CUBIC)
    out = base.copy()
    out[mask > 0] = low[mask > 0]
    return out

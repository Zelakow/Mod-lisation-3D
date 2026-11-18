"""Post-traitement photographique d'un rendu Cycles (PNG 16 bits) → JPEG.

Courbe de contraste douce, saturation, halo des hautes lumières (bloom), légère aberration
chromatique, vignettage et grain argentique — ce qu'apporte un vrai appareil photo.
Usage : python post.py entree.png sortie.jpg [--interieur]
"""
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

src, dst = sys.argv[1], sys.argv[2]
interior = "--interieur" in sys.argv
im = np.asarray(Image.open(src)).astype(np.float32)
im = im / (65535.0 if im.max() > 255 else 255.0)
im = im[..., :3]
h, w, _ = im.shape

# 1. halo des hautes lumières
lum = im @ np.array([0.2126, 0.7152, 0.0722], np.float32)
hi = np.clip((lum - 0.72) / 0.28, 0, 1)[..., None] * im
glow = np.stack([ndimage.gaussian_filter(hi[..., c], sigma=w * 0.012) for c in range(3)], -1)
glow2 = np.stack([ndimage.gaussian_filter(hi[..., c], sigma=w * 0.045) for c in range(3)], -1)
im = im + glow * (0.22 if interior else 0.14) + glow2 * 0.08

# 2. courbe en S douce + saturation
def scurve(x, k=0.12):
    # assombrit légèrement les ombres, éclaircit les lumières, extrémités inchangées
    return np.clip(x + k * (x - 0.5) * (1 - np.abs(2 * x - 1)) * 2, 0, 1)
im = np.clip(im, 0, 1)
im = scurve(im, 0.10)
lum = (im @ np.array([0.2126, 0.7152, 0.0722], np.float32))[..., None]
im = np.clip(lum + (im - lum) * 1.07, 0, 1)

# 3. aberration chromatique très légère (bords)
yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
cx, cy = (w - 1) / 2, (h - 1) / 2
for c, s in ((0, 1.0007), (2, 0.9993)):
    im[..., c] = ndimage.map_coordinates(im[..., c], [cy + (yy - cy) / s, cx + (xx - cx) / s], order=1, mode="nearest")

# 4. vignettage
r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2) / np.sqrt(2)
im *= (1 - 0.28 * r ** 2.3)[..., None]

# 5. grain
rng = np.random.default_rng(1)
g = ndimage.gaussian_filter(rng.normal(0, 1, (h, w)).astype(np.float32), 0.6)
im = np.clip(im + g[..., None] * 0.010, 0, 1)

Image.fromarray((im * 255 + 0.5).astype(np.uint8)).save(dst, quality=93, subsampling=0)
print("post-traité →", dst)

"""Goccio's foam skin (img/goccio-foam.webp and img/goccio-foam-little.webp), after the reference picture:
dense creamy microfoam and bigger bubbles wrapping all round the ball, wet glossy glints, a little light glowing through
(subsurface), darker crema mottling, two simple glossy black oval eyes sunk into the foam. Soft studio light from the upper
left; the top is lighter, the bottom darker.
python3 scripts/goccio_foam.py SIZE OUT.webp [lit]
Without "lit" it draws the skin the page turns with the ball: lit from the front only, so it looks right at any angle; the
page lays the studio light (top lighter, bottom darker, from the upper left) over it as a fixed layer. With "lit" it bakes
that light in, for the little Goccio in the top bar."""
import sys, math
import numpy as np
from scipy.spatial import cKDTree
from PIL import Image

N = int(sys.argv[1]) if len(sys.argv) > 1 else 384
ROT = 0.0
OUT = sys.argv[2] if len(sys.argv) > 2 else 'img/goccio-foam.webp'
LIT = len(sys.argv) > 3 and sys.argv[3] == 'lit'
SS = 2; M = N * SS
rng = np.random.default_rng(11)

def nrm(a): a = np.array(a, float); return a / np.linalg.norm(a)
def sphere_pts(n):
    v = rng.normal(size=(n, 3)); return v / np.linalg.norm(v, axis=1, keepdims=True)
def smooth(a, b, x): t = np.clip((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t)

yy, xx = np.mgrid[0:M, 0:M]
PAD = 1.0
u = (xx + .5) / M * 2 * PAD - PAD; w = (yy + .5) / M * 2 * PAD - PAD
rr = u * u + w * w; inside = rr < 1
z = np.sqrt(np.clip(1 - rr, 0, 1))
cr, sr = math.cos(ROT), math.sin(ROT)
Pb = np.stack([cr * u + sr * w, -sr * u + cr * w, z], -1)[inside]   # the ball's own frame: foam turns with a roll
P2 = np.stack([u, w], -1)[inside]
npx = len(Pb)

def tier(n, lo, hi):
    v = sphere_pts(n); r = np.exp(rng.uniform(math.log(lo), math.log(hi), n)); tree = cKDTree(v)
    d, idx = tree.query(Pb, k=7)
    rad = r[idx]; lsq = (d / rad) ** 2
    hh = np.sqrt(np.clip(1 - lsq, 0, None)) * rad
    j = hh.argmax(1); ar = np.arange(npx); hit = hh[ar, j] > 0; l2 = np.where(hit, lsq[ar, j], 1.0); ci = idx[ar, j]
    cv = v[ci]; cx = cr * cv[:, 0] - sr * cv[:, 1]; cy = sr * cv[:, 0] + cr * cv[:, 1]
    ox, oy = P2[:, 0] - cx, P2[:, 1] - cy; ol = np.hypot(ox, oy) + 1e-12; sl = np.sqrt(np.clip(l2, 0, 1))
    return hit, ox / ol * sl, oy / ol * sl, l2, rad[ar, j]

L = nrm([-0.38, -0.78, 0.5]) if LIT else np.array([0, 0, 1.0]); V = np.array([0, 0, 1.0]); Hh = nrm(L + V)
Ns = np.stack([u, w, z], -1)[inside]

# the ball's light: soft from the upper left, the top clearly lighter, the bottom clearly darker
lam = np.clip((Ns * L).sum(-1), 0, 1)
vert = 1 - (P2[:, 1] + 1) / 2                     # 1 at the top, 0 at the bottom
key = 0.22 + 0.58 * lam ** 0.85 + 0.5 * vert ** 1.2
rim = 0.6 + 0.4 * Ns[:, 2] ** 0.55

# crema mottling: a few slow waves over the ball's surface, darker caramel patches
mot = np.zeros(npx)
for _ in range(9):
    kv = rng.normal(size=3); kv = kv / np.linalg.norm(kv) * rng.uniform(3.5, 9)
    mot += np.sin(Pb @ kv + rng.uniform(0, 6.3)) / 9
mot = smooth(-0.05, 0.35, mot)

cream = np.array([0.64, 0.41, 0.21]); caramel = np.array([0.43, 0.24, 0.10]); deep = np.array([0.25, 0.12, 0.04])
base = cream[None] * (1 - 0.55 * mot[:, None]) + caramel[None] * (0.55 * mot[:, None])
grain = 1 + 0.05 * (rng.random(npx) - .5)

def dome(lx, ly, l2, tilt=0.75):
    bz = np.sqrt(np.clip(1 - l2, 0, 1))
    nb = np.stack([lx, ly, bz], -1) * tilt + Ns * (1 - tilt); nb /= np.linalg.norm(nb, axis=-1, keepdims=True) + 1e-9
    return np.clip((nb * L).sum(-1), 0, 1), np.clip((nb * Hh).sum(-1), 0, 1)

def side(lx, ly):
    return (lx * L[0] + ly * L[1]) / math.hypot(L[0], L[1]) if LIT else lx * 0   # >0 on the side towards the light

# layer 1: the microfoam, a dense skin of tiny bubbles over the cream
hit, lx, ly, l2, _ = tier(700000, .0019, .0044)
dl, sp = dome(lx, ly, l2, .6)
ring = smooth(.72, .95, np.sqrt(l2)) * hit
col = base * (grain * (1 - 0.22 * ring * (0.5 + 0.5 * np.clip(-side(lx, ly), 0, 1)))
              * np.where(hit, 0.9 + 0.16 * dl, 0.8))[:, None]
col = col + ((sp ** 90) * 0.28 * hit)[:, None]

# layers 2 and 3: medium and big bubbles, clear films you half see through
for n, lo, hi, see, gloss, edge in [(27000, .005, .011, .30, .7, .28), (2100, .011, .027, .55, 1.0, .38)]:
    hit, lx, ly, l2, rb = tier(n, lo, hi)
    dl, sp = dome(lx, ly, l2, .85)
    cen = np.clip(1 - l2, 0, 1)
    trans = see * cen ** 0.5 * hit                         # how much of the foam below shows through
    film = (base * 0.78 + deep[None] * 0.22) * (0.82 + 0.3 * dl)[:, None]
    s0 = side(lx, ly)
    rr0 = smooth(.80, .955, np.sqrt(l2)) * (1 - smooth(.965, 1.0, np.sqrt(l2)))
    outline = 1 - edge * rr0 * (0.55 + 0.45 * np.clip(-s0, 0, 1)) + 0.25 * rr0 * np.clip(s0, 0, 1)
    under = col * (1 - 0.12 * cen)[:, None]                 # the foam under the film, a touch darker
    new = (under * trans[:, None] + film * (1 - trans)[:, None]) * outline[:, None]
    # wet glints: a sharp one and a soft sheen on the lit side, and a little light caught on the far rim
    glint = (sp ** 160) * 1.25 * gloss + (sp ** 24) * 0.12 * gloss + 0.10 * rr0 * np.clip(-s0, 0, 1) * gloss
    new = new + glint[:, None] * np.array([1, .98, .93])[None]
    col = np.where(hit[:, None], new, col)

# light through the foam: shadows stay warm, not grey; the whole ball takes the studio light
lit = key * rim
warm = np.array([0.85, 0.42, 0.16])
col = (col * lit[:, None] + (warm[None] * 0.10 * (1 - lit)[:, None] * Ns[:, 2:3] ** 0.5) * (col.mean(1, keepdims=True) + .2)) if LIT else col * 1.04

img = np.zeros((M, M, 3)); img[inside] = col

# two simple black oval eyes, a little glossy, sunk into the foam; they turn with a roll
for ex in ():
    ey, ax, ay = 0.0, 0.072, 0.1
    cx, cy = ex * cr - ey * sr, ex * sr + ey * cr
    dx, dy = u - cx, w - cy
    rx, ry = dx * cr + dy * sr, -dx * sr + dy * cr      # into the eye's own axes
    dd = np.sqrt((rx / ax) ** 2 + (ry / ay) ** 2)
    sock = smooth(1.55, 1.0, dd) * (dd >= 1) * inside
    img *= (1 - 0.55 * sock ** 1.5)[..., None]
    e = dd < 1
    ez = np.sqrt(np.clip(1 - dd ** 2, 0, 1))
    en = np.stack([rx / ax * 0.6, ry / ay * 0.6, ez], -1); en /= np.linalg.norm(en, axis=-1, keepdims=True) + 1e-9
    es = np.clip((en * Hh).sum(-1), 0, 1)
    bead = 0.012 + 0.03 * np.clip((en * L).sum(-1), 0, 1) + 0.9 * es ** 90 + 0.06 * es ** 10
    img = np.where(e[..., None], bead[..., None] * np.array([1, 1, 1.0]), img)

img = np.clip(img, 0, 1) ** (1 / 1.1)
a = inside.astype(float)
out = np.dstack([img * a[..., None], a])
im8 = np.asarray(Image.fromarray((out * 255).round().astype(np.uint8), 'RGBA').resize((N, N), Image.LANCZOS)).copy()
# the corners outside the ball take the colour of its edge, straight out from the middle, and the picture is opaque:
# the page clips it to the body, whose outline is not quite a circle, so no sliver of anything else shows at the rim
yy2, xx2 = np.mgrid[0:N, 0:N]; cx2 = (N - 1) / 2; dx2, dy2 = xx2 - cx2, yy2 - cx2; rr2 = np.hypot(dx2, dy2) + 1e-9
edge_r = N / 2 * 0.975; out_px = rr2 > edge_r
sx = np.clip(np.round(cx2 + dx2 / rr2 * edge_r), 0, N - 1).astype(int); sy = np.clip(np.round(cx2 + dy2 / rr2 * edge_r), 0, N - 1).astype(int)
im8[out_px] = im8[sy[out_px], sx[out_px]]; im8[..., 3] = 255
Image.fromarray(im8, 'RGBA').convert('RGB').save(OUT, quality=82, method=6)

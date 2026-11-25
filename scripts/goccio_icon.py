"""Goccio's icons and profile picture: the foam ball, lit by the studio light, with his satin eyes set into the foam, on black.

    SS=1 python3 scripts/goccio_foam.py 2048 /tmp/ball.png lit round
    python3 scripts/goccio_icon.py /tmp/ball.png

writes icons/ (home-screen icon, favicons, app icons) and og/goccio-profile.png (1080 px, for Instagram).
The ball is as big as each place allows: edge to edge where the corners are cut round (iPhone, Instagram's circle),
inside the safe circle for the maskable icon."""
import sys, os
import numpy as np
from PIL import Image

BALL = sys.argv[1] if len(sys.argv) > 1 else '/tmp/ball.png'
ball = Image.open(BALL).convert('RGBA')
B = np.asarray(ball).astype(float) / 255.0
N = B.shape[0]

# the eyes, in the ball's own measure (centre 0, radius 1, y down), as on the site: centres ±0.335, a hair above the middle,
# 0.194 wide and 0.229 tall
yy, xx = np.mgrid[0:N, 0:N]
u = (xx + .5) / N * 2 - 1; w = (yy + .5) / N * 2 - 1
L = np.array([-0.38, -0.78]); L = L / np.linalg.norm(L)
rgb = B[..., :3].copy(); a = B[..., 3]
stops = [(0, 0x2a), (.38, 0x18), (.78, 0x0b), (1, 0x04)]


def ramp(t):
    t = np.clip(t, 0, 1); out = np.zeros_like(t)
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        m = (t >= t0) & (t <= t1); out[m] = (c0 + (c1 - c0) * (t[m] - t0) / (t1 - t0)) / 255
    return out


for ex in (-0.335, 0.335):
    ey, rx, ry = -0.065, 0.194, 0.229
    dx, dy = (u - ex) / rx, (w - ey) / ry; dd = np.hypot(dx, dy)
    # the foam sinks round the eye: shadowed on the side towards the light, a little light on the far wall
    tow = (dx * L[0] + dy * L[1]) / np.maximum(dd, 1e-4)
    cav = np.clip((1.42 - dd) / 0.42, 0, 1); cav = cav * cav * (3 - 2 * cav) * (dd >= 1)
    rgb *= (1 - cav * cav * (0.22 + 0.2 * np.clip(tow, 0, None)))[..., None]
    rgb += np.array([.95, .8, .6]) * (0.06 * cav * np.clip(-tow, 0, None))[..., None]
    # the eye: a satin-black pebble, lighter on the upper left
    bx, by = (dx + 1) / 2, (dy + 1) / 2
    t = np.hypot(bx - 0.3, by - 0.22) / 0.95
    g = ramp(t)
    edge = np.clip((1 - dd) * N * rx / 2, 0, 1)   # a soft, one-pixel edge
    rgb = rgb * (1 - edge[..., None]) + g[..., None] * edge[..., None]

out = np.dstack([np.clip(rgb, 0, 1), a])
face = Image.fromarray((out * 255).round().astype(np.uint8), 'RGBA')


def on_black(size, fill):
    """The ball, `fill` of the square wide, centred on black."""
    bg = Image.new('RGBA', (size, size), (0, 0, 0, 255)); d = max(1, round(size * fill))
    f = face.resize((d, d), Image.LANCZOS); bg.alpha_composite(f, ((size - d) // 2, (size - d) // 2)); return bg.convert('RGB')


root = os.path.join(os.path.dirname(__file__), '..')
ic = os.path.join(root, 'icons'); og = os.path.join(root, 'og')
# iPhone and the app icons round the corners themselves: the ball runs almost to the edges
on_black(180, 0.94).save(os.path.join(ic, 'apple-touch-icon.png'), optimize=True)
on_black(192, 0.94).save(os.path.join(ic, 'icon-192.png'), optimize=True)
on_black(512, 0.94).save(os.path.join(ic, 'icon-512.png'), optimize=True)
on_black(1024, 0.94).save(os.path.join(ic, 'icon-1024.png'), optimize=True)
on_black(512, 0.8).save(os.path.join(ic, 'icon-512-maskable.png'), optimize=True)   # Android may cut it to a circle of 80%
# tab icons: as big as they can be
on_black(32, 0.98).save(os.path.join(ic, 'favicon-32.png'), optimize=True)
on_black(48, 0.98).save(os.path.join(ic, 'favicon-48.png'), optimize=True)
on_black(48, 0.98).save(os.path.join(ic, 'favicon.ico'), sizes=[(16, 16), (32, 32), (48, 48)])
# Instagram shows a circle: the ball fills it
os.makedirs(og, exist_ok=True)
on_black(1080, 0.985).save(os.path.join(og, 'goccio-profile.png'), optimize=True)
print('icons written')

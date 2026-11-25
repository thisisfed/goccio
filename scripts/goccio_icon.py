"""Goccio's pictures: the home screen icons, favicons and the Instagram profile picture, all from one drawing.

The drawing is Goccio at rest on the site (the glossy drop, dark roast): the same body, colours, shine and eyes as index.html.
Run from the repo root:  python3 scripts/goccio_icon.py
Needs Playwright with Chromium (pip install playwright && playwright install chromium) and Pillow.
"""
import io
import os
from PIL import Image
from playwright.sync_api import sync_playwright

# Goccio at rest, in the site's own units: a ball of radius 15.5 round (0, -15.5)
SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{px}" height="{px}">
<defs><radialGradient id="f" gradientUnits="userSpaceOnUse" cx="1.8" cy="-9.3" r="22.3" fx="2.5" fy="-6.8">
<stop offset="0" stop-color="#7d4524"/><stop offset=".38" stop-color="#4c2311"/><stop offset=".78" stop-color="#261107"/><stop offset="1" stop-color="#120702"/></radialGradient></defs>
{bg}<circle cx="0" cy="-15.5" r="15.5" fill="url(#f)"/>
<ellipse rx="3.4" ry="1.9" fill="#fff" opacity=".5" transform="translate(-6.98 -24.49) rotate(-35)"/>
<ellipse cx="-6" cy="-16.5" rx="2.4" ry="3.4" fill="#000"/><ellipse cx="6" cy="-16.5" rx="2.4" ry="3.4" fill="#000"/>
</svg>"""


def render(page, px, ball, bg=True):
    """a square picture px wide, the ball taking `ball` of its width"""
    half = 15.5 / ball
    vb = f"{-half} {-15.5 - half} {2 * half} {2 * half}"
    rect = f'<rect x="{-half}" y="{-15.5 - half}" width="{2 * half}" height="{2 * half}" fill="#000"/>' if bg else ""
    page.set_viewport_size({"width": px, "height": px})
    page.set_content(f'<html><body style="margin:0;background:transparent">{SVG.format(vb=vb, px=px, bg=rect)}</body></html>')
    return Image.open(io.BytesIO(page.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": px, "height": px}))).convert("RGBA")


def main():
    os.makedirs("icons", exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        big = render(pg, 4096, 0.76)   # about the size other apps draw their mark (Grok's ring and slash): room round him, never touching the corners
        for name, size in [("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512), ("icon-1024.png", 1024)]:
            big.resize((size, size), Image.LANCZOS).convert("RGB").save("icons/" + name, optimize=True)
        render(pg, 4096, 0.8).resize((512, 512), Image.LANCZOS).convert("RGB").save("icons/icon-512-maskable.png", optimize=True)   # Android's safe circle: 80% of the tile
        fav = render(pg, 1024, 0.96, bg=False)   # browser tabs: just the ball, no square
        fav.resize((32, 32), Image.LANCZOS).save("icons/favicon-32.png", optimize=True)
        fav.resize((48, 48), Image.LANCZOS).save("icons/favicon-48.png", optimize=True)
        fav.save("icons/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
        # Instagram, X and YouTube profile picture: they all crop to a circle; the ball fills it edge to edge, no border
        render(pg, 4096, 1.01).resize((2048, 2048), Image.LANCZOS).convert("RGB").save("og/goccio-profile.png", optimize=True)
        b.close()


if __name__ == "__main__":
    main()

"""One page per coffee, for search engines.

Run by the publish workflow on the copy of the site it is about to upload:

    python3 scripts/pages.py /tmp/site

It writes, inside that folder:
  coffee/index.html                       every roaster, A to Z
  coffee/<roaster>/index.html             a roaster's coffees
  coffee/<roaster>/<coffee>/index.html    one coffee: what the roaster says, and a V60 recipe
  sitemap.xml, robots.txt

The recipe numbers are not worked out here. The script opens the site's own index.html in a
headless browser and asks the app's engine (window.bagRecipe) for each coffee, so a page always
shows exactly what a first-time visitor gets in the app.
"""
import html, json, os, re, socket, subprocess, sys, threading, unicodedata
from datetime import date
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan  # noqa: E402  (tidy_note: tasting notes without the sentence around them)

SITE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
HOST = "www.goccio.co.uk"
try:
    HOST = open(os.path.join(SITE, "CNAME")).read().strip() or HOST
except OSError:
    pass
BASE = "https://" + HOST
GRINDER = "Comandante C40"
e = lambda s: html.escape(str(s or ""), quote=True)


def roaster_recipe_line(c, name):
    """The roaster's own recipe in words (the same wording as the app), or "" when its page gives none."""
    rr = c.get("roaster_recipe") or {}
    if not rr:
        return ""
    bits = []
    if rr.get("dose") and rr.get("water"):
        bits.append((f'{rr["dose"]} g in, {rr["water"]} g out' if rr.get("brewer") == "espresso" else f'{rr["dose"]} g coffee to {rr["water"]} g water') + (f' (1:{rr["ratio"]})' if rr.get("ratio") else ""))
    elif rr.get("ratio"):
        bits.append(f'a 1:{rr["ratio"]} ratio')
    if rr.get("temp"):
        bits.append(f'{rr["temp"]} °C')
    if rr.get("grind") or rr.get("grind_um"):
        um = f'about {rr["grind_um"]} µm' if rr.get("grind_um") else ""
        bits.append((rr["grind"].replace("-", "-") + " grind" + (f" ({um})" if um else "")) if rr.get("grind") else um + " grind")
    if rr.get("clicks"):
        bits.append(f'{rr["clicks"]} clicks' + (f' on {rr["grinder"]}' if rr.get("grinder") else ""))
    if rr.get("bloom"):
        bits.append(f'a {rr["bloom"]} g bloom')
    if rr.get("pours"):
        bits.append(f'{rr["pours"][0]} g pours every {rr["pours"][1]} s')
    if rr.get("time"):
        bits.append(f'{rr["time"]} in all')
    return f"{name}: " + ", ".join(bits) + "." if bits else ""


def slug(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"&", " and ", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80].strip("-") or "coffee"


def ddmmyyyy(iso):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{int(m[3])} {['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(m[2]) - 1]} {m[1]}" if m else ""   # 19 Nov 2026, never slashes


def mmss(s):
    s = max(0, round(s or 0))
    return f"{s // 60}:{s % 60:02d}"


def iso_dur(s):
    s = max(0, round(s or 0))
    return f"PT{s // 60}M{s % 60}S" if s % 60 else f"PT{s // 60}M"


def and_list(xs):
    xs = [x for x in xs if x]
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1] if xs else ""


def cap(s):
    return s[:1].upper() + s[1:] if s else s


# ---------- the recipes, from the app itself ----------
ROW_BITS = {}


def recipes(coffees):
    from playwright.sync_api import sync_playwright

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    srv = ThreadingHTTPServer(("127.0.0.1", port), partial(Quiet, directory=SITE))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            try:
                b = p.chromium.launch(channel="chrome")   # GitHub's runners already have Chrome
            except Exception:
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                b = p.chromium.launch()
            # a phone-sized window: on a wide one the site opens itself inside a phone column (an iframe) and this page
            # never finishes loading, which skipped every coffee page from 25/11/2026 on
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.goto(f"http://127.0.0.1:{port}/index.html?wide", wait_until="domcontentloaded")
            pg.wait_for_function("() => typeof window.bagRecipe === 'function'", timeout=60000)
            out = []
            for i in range(0, len(coffees), 500):
                out += pg.evaluate("(xs) => xs.map((x) => { try { return bagRecipe(x); } catch (err) { return null; } })", coffees[i:i + 500])
            for i in range(0, len(coffees), 500):   # each row's taste line and roaster name, written by the main page itself
                for c, bits in zip(coffees[i:i + 500], pg.evaluate("(xs) => xs.map((x) => window.rowBits ? rowBits(x) : null)", coffees[i:i + 500])):
                    ROW_BITS[id(c)] = bits or {}
            b.close()
            return out
    finally:
        srv.shutdown()


# ---------- the look: the site's own, black and white plus the accent, 15/24/39/63 ----------
CSS = """
:root{--bg:#f7f3ed;--ink:#000;--muted:#69625a;--rule:#e1d9ce;--line:#a8a196;--pill:#e7e0d6;--hl:#ff4f00;
--sans:"ALT Riviera","Helvetica Neue",Helvetica,Arial,-apple-system,BlinkMacSystemFont,system-ui,sans-serif}
@font-face{font-family:"ALT Riviera";src:url("/fonts/alt-medium.woff2") format("woff2");font-weight:100 900;font-style:normal;font-display:swap}
@media (prefers-color-scheme:dark){:root{--bg:#000;--ink:#fff;--muted:#8c8c8c;--rule:#262626;--line:#595959;--pill:#222;--hl:#ff5a14}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;overflow-x:clip}
body{margin:0;background:var(--bg);color:var(--ink);font:500 15px/1.35 var(--sans);letter-spacing:-.011em}
a{color:inherit;text-decoration:none}
.top{position:sticky;top:0;z-index:2;display:flex;justify-content:space-between;align-items:center;gap:12px;height:49px;padding:0 12px;background:var(--bg);border-bottom:1px solid var(--line)}
.mark{font-size:15px}
.pill{display:inline-flex;align-items:center;height:32px;padding:0 12px;border-radius:4px;background-color:var(--pill);color:var(--ink);font:500 15px/1 var(--sans);transition:background-color .15s ease}
.pill:hover{background-color:color-mix(in srgb,var(--pill) 80%,var(--ink))}
.page{display:grid;gap:72px;padding:24px 12px 72px}
@media (min-width:760px){.top{padding:0 24px}.page{padding:24px 24px 72px}}
.sec-head{display:flex;justify-content:space-between;gap:12px;border-top:1px solid var(--line);padding-top:8px;font-size:24px;line-height:1.1;letter-spacing:-.025em}
.sec-head .muted{color:var(--muted)}
.crumb{margin:0 0 12px;color:var(--muted)}
.crumb a,.r-read a,footer a{text-decoration:underline;text-decoration-color:color-mix(in srgb,currentColor 40%,transparent);text-underline-offset:2px;transition:text-decoration-color .15s ease}
.crumb a:hover,.r-read a:hover,footer a:hover{text-decoration-color:transparent}
.list .name{transition:color .15s ease}.list a:hover .name{color:var(--muted)}
.specs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}
@media (min-width:760px){.specs{grid-template-columns:repeat(4,minmax(0,1fr))}}
.spec{display:grid;gap:4px;align-content:start;padding:10px 0 18px;border-top:1px solid var(--line);min-width:0}
.spec.wide{grid-column:1/-1}
.spec.brewer+.spec,.spec.brewer+.spec+.spec{border-top:0}   /* no rule under the brewer's name */
@media (min-width:760px){.spec.brewer+.spec+.spec+.spec,.spec.brewer+.spec+.spec+.spec+.spec{border-top:0}}
.page.top-tight{padding-top:15px}   /* base of the name in the top bar to its rule = that rule to the first words */
.top-tight > section:first-child .spec:first-child{border-top:0;padding-top:0}
.spec .k{color:var(--muted);font-weight:600}
.spec b,.spec h1{margin:0;font-size:39px;line-height:1.05;letter-spacing:-.04em;font-weight:500;overflow-wrap:anywhere}
@media (min-width:760px){.spec b,.spec h1{font-size:63px}}
.spec small{font-size:24px;color:var(--muted);letter-spacing:0;margin-left:4px}
.facts{display:grid;gap:4px;margin:6px 0 0}
/* Roasters A to Z: the letter bar sticks under the top bar; one size of type, sliding sideways when it doesn't fit */
.az{position:sticky;top:49px;z-index:1;display:flex;gap:4px;justify-content:space-between;overflow-x:auto;scrollbar-width:none;margin:12px -12px 0;padding:12px;background:var(--bg);border-bottom:1px solid var(--line)}
.az::-webkit-scrollbar{display:none}
.az a,.az span{flex:none;width:32px;height:32px;display:inline-flex;align-items:center;justify-content:center;border-radius:4px;font-size:15px}
.az a{background:var(--pill)}.az span{color:var(--muted);opacity:.5}
.az a:hover{background:color-mix(in srgb,var(--pill) 80%,var(--ink))}
.az a[aria-current]{background:var(--ink);color:var(--bg)}   /* the letter you're reading, as the main page marks the section in view */
@media (min-width:760px){.az{margin:12px -24px 0;padding:12px 24px}}
.list .az-h{font-size:24px;line-height:1.1;color:var(--muted);padding:24px 0 8px;scroll-margin-top:107px}
.list .az-h:first-child{padding-top:12px}
.page > section{min-width:0}   /* a long row inside slides on its own; the page never gets wider than the screen */
.page > .az-sec{margin-top:-72px}   /* right under the intro, not a section's gap away */
.az{margin-top:0!important}
.spec.ro{padding-bottom:0}
.spec .ro-n{display:block}
.spec .ro-shop{justify-self:start;margin-top:8px}
a.ro-n{justify-self:start;text-decoration:underline;text-decoration-color:color-mix(in srgb,currentColor 40%,transparent);text-underline-offset:2px}
.facts div{display:grid;grid-template-columns:120px minmax(0,1fr);gap:12px}
.facts dt{color:var(--muted)}.facts dd{margin:0;overflow-wrap:anywhere}
.notes{margin:12px 0 0}
.r-read{margin:12px 0 0}
.ro-rec{margin:16px 0 0;padding:12px 14px;border-radius:4px;background:var(--pill)} .ro-rec p{margin:0} .ro-rec .k{font-size:13px;opacity:.7;margin-bottom:4px}
.pours{width:100%;border-collapse:collapse;margin:12px 0 0}
.pours th{text-align:left;font-weight:500;color:var(--muted);padding:0 10px 8px 0;border-bottom:1px solid var(--line)}
.pours td{padding:11px 10px 11px 0;border-bottom:1px solid var(--line);vertical-align:top}
.pours td.at{color:var(--muted);white-space:nowrap}.pours td.to{white-space:nowrap}
.pours small{color:var(--muted);margin-left:2px}
.muted,.note{color:var(--muted)}
.note{margin:12px 0 0}
.go{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 0}
.list{list-style:none;margin:0;padding:0}
.list li{padding:12px 0;border-bottom:1px solid var(--line)}
.list .name{display:block;font-size:24px;line-height:1.1;letter-spacing:-.025em}
.list .sub{display:block;margin-top:4px;color:var(--muted)}
footer{margin:0 12px;padding:10px 0 24px;border-top:1px solid var(--line);color:var(--muted)}
@media (min-width:760px){footer{margin:0 24px}}
footer p{margin:0}
.page:has(> section:last-child > .list){padding-bottom:0}   /* a page ending on a list: its last rule is the footer's rule */
.page > section:last-child > .list > li:last-child{border-bottom:0}
/* the main page's look: its Dark / Light (dark unless you pick light), its type drawn the same (thin smoothing, no extra tracking) */
:root[data-theme="light"]{--bg:#f7f3ed;--ink:#000;--muted:#69625a;--rule:#e1d9ce;--line:#a8a196;--pill:#e7e0d6;--hl:#ff4f00}
:root[data-theme="dark"]{--bg:#000;--ink:#fff;--muted:#8c8c8c;--rule:#262626;--line:#595959;--pill:#222;--hl:#ff5a14}
body{-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
*{letter-spacing:0!important}
.spec b,.spec h1,.list .name{letter-spacing:-.01em!important}
.spec .k{font-weight:500!important}
.top .tr{display:flex;gap:5px}
.pill.sq{width:32px;padding:0;justify-content:center;border:0;cursor:pointer;border-radius:50%}
.pill.sq svg{width:17px;height:17px}
/* coffee rows as on the main page: grey who and when, the name at 39 (63 on wide screens), then tags with coloured dots and grey notes */
.list.rows li{padding:12px 0;border-bottom:1px solid var(--line)}
.list.rows a{display:block}
.list.rows .cw{margin:0 0 5px;color:var(--muted);line-height:19px}
.list.rows .cw .ro{color:var(--ink);text-decoration:underline 1px;text-underline-offset:2px;text-decoration-color:color-mix(in srgb,currentColor 40%,transparent)}
.list.rows .name{font-size:39px;line-height:1.05;letter-spacing:-.01em!important}
@media (min-width:1000px){.list.rows .name{font-size:63px}}
.list.rows li{position:relative;isolation:isolate}
.list.rows li::before{content:"";position:absolute;inset:0 -8px;z-index:-1;border-radius:4px;background:var(--ink);opacity:0;transition:opacity .15s ease;pointer-events:none}
@media (hover:hover) and (pointer:fine){.list.rows li:hover::before{opacity:.05}}
.list.rows .tags{display:flex;flex-wrap:wrap;column-gap:20px;row-gap:2px;margin:6px 0 0;color:var(--muted);line-height:19px}
.list.rows .tg{display:inline-flex;align-items:center;min-width:0;overflow-wrap:anywhere}
.list.rows .tg::before{content:"";flex:none;width:12px;height:12px;margin-right:5px;border-radius:50%;background:var(--vc,var(--muted))}
.list.rows .tg.pr::before{border-radius:3px}
.list.rows .tg.vd::before{border-radius:2px;rotate:45deg;scale:.82}
.p-nat{--vc:#af52de}.p-wash{--vc:#30b0c7}.p-honey{--vc:#ff9f0a}.p-exp{--vc:#ff2d55}.p-decaf{--vc:#a0703c}.p-other{--vc:#8a9a1b}.miss{--vc:#8e8e93}
.list.rows .cn{margin:2px 0 0;color:var(--muted);line-height:19px}
.nw-day{font-size:24px;line-height:1.1;margin:28px 0 0;padding-bottom:8px;border-bottom:1px solid var(--line);font-weight:500}
"""


def page(title, desc, path, body, extra_head="", nav=True, tight=False):
    url = BASE + path
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="theme-color" content="#000000"><script>try{{var t=localStorage.getItem("v60.theme");if(t!=="auto")document.documentElement.setAttribute("data-theme",t==="light"?"light":"dark")}}catch(e){{document.documentElement.setAttribute("data-theme","dark")}}</script><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="Goccio">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}"><meta property="og:image" content="{BASE}/og/card-8.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" type="image/png" sizes="32x32" href="/icons/favicon-32.png?v=3"><link rel="apple-touch-icon" href="/apple-touch-icon.png?v=3"><meta name="apple-mobile-web-app-title" content="Goccio">
<style>{CSS}</style>{extra_head}
</head><body>
<header class="top"><a class="mark" href="/">Goccio</a><span class="tr">{'<a class="pill" href="/coffee/">Roasters</a>' if nav else '<a class="pill" href="/">Back to homepage</a>'}<button type="button" class="pill sq" id="themeBtn" aria-label="Appearance"></button></span></header>
<main class="page{' top-tight' if tight else ''}">
{body}
</main>
<footer><p>Coffee details are read every day from each roaster’s own shop. Prices and stock change: check the roaster’s page before you buy.</p>
<p><a href="/">Goccio</a>: a recipe for any coffee, for your brewer and your grinder. A roaster? <a href="/list/">Get your roastery listed</a>. <a href="/privacy/">Privacy</a>. <a class="mail" href="#" data-m="ku.oc.oiccog@nu">Email us</a>.</p></footer>
<script src="/lib/theme.js"></script><script>document.querySelectorAll("a.mail").forEach(function(a){{var go=function(){{a.href="mailto:"+a.dataset.m.split("").reverse().join("");}};a.addEventListener("pointerdown",go);a.addEventListener("focus",go);a.addEventListener("click",function(){{go();}});}});</script>
</body></html>
"""


_OC = None


def origin_colours():
    # the main page's colour for each country, read from its own styles (index.html, or the stylesheet build.py split out)
    global _OC
    if _OC is None:
        _OC, txt = {}, ""
        import glob
        for f in [os.path.join(SITE, "index.html")] + glob.glob(os.path.join(SITE, "assets", "app.*.css")):
            try:
                txt += open(f, encoding="utf-8").read()
            except OSError:
                pass
        # the minified stylesheet drops the quotes where it can: [data-o=Ethiopia], but [data-o="Costa Rica"]
        for sels, col in re.findall(r'((?:\[data-o=(?:"[^"]+"|[\w-]+)\]\s*,?\s*)+)\{\s*--oc:\s*(#[0-9a-fA-F]{3,8})', txt):
            for q, b in re.findall(r'data-o=(?:"([^"]+)"|([\w-]+))', sels):
                _OC.setdefault(q or b, col)
    return _OC


def _bucket(p):
    p = (p or "").lower()
    if re.search(r"decaf", p): return "p-decaf"
    if re.search(r"anaerob|co-?ferment|carbonic|thermal|infus|double|yeast", p): return "p-exp"
    if "natural" in p: return "p-nat"
    if "honey" in p: return "p-honey"
    if "washed" in p: return "p-wash"
    return "p-other"


def _var_colour(v):
    # the same hue the main page gives this variety: its name hashed, h * 31 + each character
    h = 0
    for ch in v.lower().strip():
        o = ord(ch)
        if o > 0xFFFF:
            o = 0xD800 + ((o - 0x10000) >> 10)
        h = (h * 31 + o) & 0xFFFFFFFF
    return f"hsl({h % 360} 62% 50%)"


def _var_name(v):
    t = str(v or "").strip()
    if re.match(r"^74\s?/?\d{2,3}\b", t):
        return "Ethiopian " + re.sub(r"74\s?/(\d)", r"74\1", t)
    if re.match(r"^[\d\s,.]+$", t) or re.match(r"^\s*\d+\s?(?:g|gr|kg|oz|lb)\b", t, re.I):
        return ""
    return t


def _day(c):
    iso = (c.get("published") or c.get("found") or "")[:10]
    d = ddmmyyyy(iso)
    if not d:
        return ""
    return "Added " + (d[:-5] if iso[:4] == date.today().isoformat()[:4] else d)   # this year's dates without the year, as on the main page


def coffee_row(c, cpath, roaster=True, day=True):
    # one coffee as the main page draws it: who and when in grey, the name big, origin, process and variety with their coloured dots, then the notes
    oc = origin_colours()
    os_ = [x for x in str(c.get("origin") or "").split(" / ") if x]
    tags = []
    if os_:
        reg = c.get("region") if len(os_) == 1 and c.get("region") else ""
        tags.append(f'<span class="tg oc" style="--vc:{oc.get(os_[0], "var(--muted)")}">{e(" / ".join(os_))}{", " + e(reg) if reg else ""}</span>')
    p = c.get("process")
    tags.append(f'<span class="tg pr {_bucket(p)}">{e(p)}</span>' if p else '<span class="tg pr miss">Process not listed</span>')
    v = _var_name(c.get("variety"))
    if v:
        tags.append(f'<span class="tg vd" style="--vc:{_var_colour(v)}">{e(" ".join(w[:1].upper() + w[1:] for w in v.split(" ")))}</span>')
    bits = ROW_BITS.get(id(c)) or {}
    taste = re.sub(r"<[^>]+>", "", bits.get("notes") or "").strip()   # the main page's own taste line: the roaster's notes, or what the origin usually tastes of
    if not taste:
        ns = [n for n in (scan.tidy_note(x) for x in (c.get("notes") or []) if isinstance(x, str) and len(x) < 40) if n][:6]
        taste = e(cap(and_list([re.sub(r"\b[A-Z](?=[a-z])", lambda m: m.group(0).lower(), n) for n in ns])))
    who = []
    if roaster:
        city, cc = c.get("roaster_city") or "", c.get("roaster_country") or ""
        cc = "UK" if cc == "GB" else cc
        where = (", " + e(city) if city else "") + (f'{" " if city else ", "}({e(cc)})' if cc else "")   # Hamburg (DE), as on the main page
        who.append(f'<span class="ro">{e(bits.get("ro") or c["roaster"])}</span>{where}')
    if day and _day(c):
        who.append(f'<span class="dy">{_day(c)}</span>')
    return (f'<li class="cr"><a href="{cpath[id(c)]}">' + (f'<p class="cw">{"<br>".join(who)}</p>' if who else "")
            + f'<span class="name">{e(c["name"])}</span><p class="tags">{"".join(tags)}</p>'
            + (f'<p class="cn">{taste}</p>' if taste else "") + "</a></li>")


def coffee_list(cs, cpath, roaster=False, day=True):
    return '<ul class="list rows">' + "".join(coffee_row(c, cpath, roaster, day) for c in cs) + "</ul>"


def write(rel, text):
    full = os.path.join(SITE, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    d = json.load(open(os.path.join(SITE, "data", "releases.json"), encoding="utf-8"))
    updated = (d.get("updated") or date.today().isoformat())[:10]
    shops = {r.get("name"): r for r in d.get("roasters") or [] if isinstance(r, dict)}
    coffees = [r for r in d.get("releases") or [] if r.get("name") and r.get("roaster")]

    # stable addresses: roasters, then coffees within a roaster, ordered by name and shop link
    rslug, used = {}, set()
    for name in sorted({c["roaster"] for c in coffees}, key=lambda n: (slug(n), n)):
        s, k = slug(name), 2
        while s in used:
            s, k = f"{slug(name)}-{k}", k + 1
        used.add(s); rslug[name] = s
    by_roaster = {}
    for c in sorted(coffees, key=lambda c: (c["roaster"], slug(c["name"]), c.get("url") or "")):
        by_roaster.setdefault(c["roaster"], []).append(c)
    cpath = {}
    for name, cs in by_roaster.items():
        seen = set()
        for c in cs:
            s, k = slug(c["name"]), 2
            while s in seen:
                s, k = f"{slug(c['name'])}-{k}", k + 1
            seen.add(s); cpath[id(c)] = f"/coffee/{rslug[name]}/{s}/"

    recs = recipes(coffees)
    rec = {id(c): r for c, r in zip(coffees, recs)}
    urls = [(BASE + "/", updated), (BASE + "/it/", updated), (BASE + "/coffee/", updated), (BASE + "/list/", updated), (BASE + "/privacy/", updated)]

    # ---------- a page per coffee ----------
    for name, cs in by_roaster.items():
        city = next((c.get("roaster_city") for c in cs if c.get("roaster_city")), "") or (shops.get(name) or {}).get("city", "")
        for c in cs:
            r = rec.get(id(c))
            path = cpath[id(c)]
            notes = [re.sub(r"\b[A-Z](?=[a-z])", lambda m: m.group(0).lower(), n) for n in (scan.tidy_note(x) for x in (c.get("notes") or []) if isinstance(x, str) and len(x) < 40) if n][:5]
            process = c.get("process") or (cap(r["processLabel"]) if r and "process" not in r["missing"] else "")
            facts = [("Origin", e(c.get("origin"))), ("Process", e(process)), ("Variety", e(c.get("variety"))),
                     ("Roast", e(cap(r["roastLabel"])) if r and "roast" not in r["missing"] else ""),
                     ("Roasted for", e(cap(c["roast_for"])) if c.get("roast_for") in ("filter", "espresso") else ""),
                     ("Bag", e(" for ".join(x for x in [f'{c["bag_g"]} g' if c.get("bag_g") else "", c.get("price") or ""] if x))),
                     ("On the list since", e(ddmmyyyy(c.get("found") or c.get("published"))))]
            dl = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts if v)
            spec = lambda k, v, cls="": f'<div class="spec{(" " + cls) if cls else ""}"><span class="k">{k}</span>{v}</div>'
            # the coffee: laid out like the app's recipe, Roastery and Coffee as big specs, then the facts
            first = [
                     # like the recipe on the main page: Roastery (name, town) then Coffee, each a small label over big type
                     '<div class="specs">' + f'<div class="spec wide"><span class="k">Roastery</span><b><a href="/coffee/{rslug[name]}/">{e(name)}</a>{", " + e(city) if city else ""}</b></div>'
                     + f'<div class="spec wide"><span class="k">Coffee</span><h1>{e(c["name"])}</h1></div>' + "</div>", f'<dl class="facts">{dl}</dl>']
            if notes:
                first.append(f'<p class="notes">Flavour: {e(and_list(notes))}.</p>')
            body = ["<section>" + "".join(first) + "</section>"]
            brew = "/#brew=" + e(quote(c.get("url") or "", safe=""))
            go = (f'<p class="go"><a class="pill" href="{brew}">Brew it in the app</a>'
                  + (f'<a class="pill" href="{e(c["url"])}" rel="noopener">Buy from {e(name)}</a>' if c.get("url") else "") + "</p>")
            ld = ""
            if r and r.get("water"):
                specs = ('<div class="specs">' + spec("Brewer", "<b>V60</b>", "wide brewer") + spec(GRINDER, f'<b>{r["clicks"]}<small>clicks</small></b>')
                         + spec("Kettle", f'<b>{r["temp"]}<small>°C</small></b>') + spec("Coffee", f'<b>{r["dose"]}<small>g</small></b>')
                         + spec("Water", f'<b>{r["water"]}<small>g</small></b>') + spec("Total time", f'<b>{mmss(r["lo"])} – {mmss(r["hi"])}</b>', "wide") + "</div>")
                rows = "".join(f'<tr><td class="at">{mmss(p["t"])}</td><td class="to">{p["to"]}<small>g</small></td><td>{e(p["note"])}</td></tr>' for p in r["pours"] if p.get("to") is not None)
                miss = r["missing"]
                hint = ""
                if miss:
                    what = "roast or process" if len(miss) == 2 else miss[0]
                    hint = f'<p class="note">The roaster doesn’t state the {what}, so this starts from the middle of the range. Pick it in the app to sharpen the recipe.</p>'
                ro_rec = roaster_recipe_line(c, name)
                body.append("<section>" + '<div class="sec-head"><span>Recipe.</span></div>'
                            + f'<p class="r-read">{e(r["method"])}, 1:{r["ratio"]}</p>' + specs
                            + (f'<div class="ro-rec"><p class="k">The roaster’s recipe</p><p>{e(ro_rec)}</p></div>' if ro_rec else "")
                            + (f'<table class="pours"><thead><tr><th>At</th><th>Target</th><th>How</th></tr></thead><tbody>{rows}</tbody></table>' if rows else "") + hint
                            + '<p class="note">Another grinder or brewer (Chemex, Kalita, AeroPress, French press and more), a timer for every pour, and a journal that adjusts the next cup: all in the app.</p>'
                            + go + "</section>")
                steps = [{"@type": "HowToStep", "text": f'{mmss(p["t"])}: pour to {p["to"]} g. {p["note"]}'.strip()} for p in r["pours"] if p.get("to") is not None]
                ld = json.dumps({"@context": "https://schema.org", "@type": "Recipe", "name": f"V60 recipe for {c['name']} ({name})",
                                 "description": f"A V60 pour over recipe for {c['name']} from {name}.", "image": [BASE + "/og/card-8.png"],
                                 "author": {"@type": "Organization", "name": "Goccio", "url": BASE + "/"},
                                 "recipeCategory": "Drink", "recipeYield": "1 cup", "totalTime": iso_dur(r["hi"]), "keywords": f"V60, pour over, {name}, {c.get('origin') or ''}".strip(", "),
                                 "recipeIngredient": [f'{r["dose"]} g {c["name"]} coffee, ground at {r["clicks"]} clicks on a {GRINDER}', f'{r["water"]} g water at {r["temp"]}°C'],
                                 "recipeInstructions": steps}, ensure_ascii=False).replace("</", "<\\/")
                ld = f'\n<script type="application/ld+json">{ld}</script>'
            else:
                body[0] = body[0][:-len("</section>")] + go + "</section>"
            others = sorted([o for o in cs if o is not c], key=lambda o: (o.get('published') or o.get('found') or '')[:10], reverse=True)[:12]   # newest first, as on the main page
            if others:
                body.append(f'<section><div class="sec-head"><span>More from {e(name)}.</span></div>' + coffee_list(others, cpath) + "</section>")
            bits = [x for x in [(process or "").lower(), c.get("origin")] if x]
            desc = f"A V60 recipe for {c['name']} from {name}{', ' + city if city else ''}" + (f": {' '.join(bits)}" if bits else "") + "."
            if r and r.get("water"):
                desc += f' {r["dose"]} g to {r["water"]} g at {r["temp"]}°C, {r["clicks"]} clicks on a {GRINDER}, about {mmss(r["hi"])} in all.'
            write(path.strip("/") + "/index.html", page(f"{c['name']}, {name}: a V60 recipe", desc, path, "\n".join(x for x in body if x), ld, tight=True))
            urls.append((BASE + path, (c.get("found") or c.get("published") or updated)[:10]))

    # ---------- a page per roaster ----------
    for name, cs in by_roaster.items():
        city = next((c.get("roaster_city") for c in cs if c.get("roaster_city")), "")
        shop = (shops.get(name) or {}).get("shop") or ""
        # like the recipe's Roastery on the main site: the name and its town big, then how many coffees and the shop, as close
        # under it as Roastery is above it. No Roasters link here: the top bar has it
        body = (f'<section><div class="specs">'
                f'<div class="spec wide ro"><h1>{e(name)}{", " + e(city) if city else ""}</h1>'
                f'<span class="ro-n">{len(cs)} coffee{"s" if len(cs) != 1 else ""} on the list</span>'
                + (f'<a class="pill ro-shop" href="{e(shop)}" rel="noopener">Their shop</a>' if shop else "") + "</div></div></section>"
                f'<section><div class="sec-head"><span>Coffees.</span><span class="muted">Each with a V60 recipe</span></div>{coffee_list(sorted(cs, key=lambda c: (c.get('published') or c.get('found') or '')[:10], reverse=True), cpath)}</section>')
        desc = f"{len(cs)} coffee{'s' if len(cs) != 1 else ''} from {name}{', ' + city if city else ''}, each with a V60 recipe: grind, dose, temperature and every pour."
        write(f"coffee/{rslug[name]}/index.html", page(f"{name}: coffees and V60 recipes", desc, f"/coffee/{rslug[name]}/", body, tight=True))
        urls.append((f"{BASE}/coffee/{rslug[name]}/", updated))

    # ---------- every roaster ----------
    names = sorted(by_roaster, key=lambda n: slug(n))
    # a heading where the first letter changes, and a 1 A B … Z bar to jump to one (1 for names that start with a number)
    def letter(n):
        c = (slug(n)[:1] or "#").upper()
        return "1" if c.isdigit() else c if "A" <= c <= "Z" else "1"
    items, last = [], None
    for n in names:
        L = letter(n)
        if L != last:
            items.append(f'<li class="az-h" id="az-{L}">{L}</li>'); last = L
        items.append(f'<li><a href="/coffee/{rslug[n]}/"><span class="name">{e(n)}</span></a><span class="sub">'
                     + e(", ".join(x for x in [next((c.get("roaster_city") for c in by_roaster[n] if c.get("roaster_city")), ""),
                                               f"{len(by_roaster[n])} coffee{'s' if len(by_roaster[n]) != 1 else ''}"] if x)) + "</span></li>")
    items = "".join(items)
    have = {letter(n) for n in names}
    az = '<nav class="az" aria-label="Jump to a letter">' + "".join(
        f'<a href="#az-{L}">{L}</a>' if L in have else f'<span>{L}</span>' for L in ["1"] + [chr(c) for c in range(65, 91)]) + "</nav>"
    body = (f'<section><div class="specs"><div class="spec wide"><h1>Roasters A to Z</h1></div></div>'
            f'<p class="r-read">{len(names)} roasters, {len(coffees):,} coffees, updated {ddmmyyyy(updated)}. Every coffee has a V60 recipe.</p></section>'
            f'<section class="az-sec">{az}<ul class="list">{items}</ul></section>'
            # the letter in view lights up in the bar, and slides into it when the bar is wider than the screen
            '<script>(function(){var bar=document.querySelector(".az");if(!bar)return;var hs=[].slice.call(document.querySelectorAll(".az-h")),cur="",pick=null;'
            'function sync(){var line=bar.getBoundingClientRect().bottom+40,a=hs.length?hs[0].id:"";hs.forEach(function(h){if(h.getBoundingClientRect().top<=line)a=h.id;});'
            'if(pick&&Date.now()-pick.t<1500)a=pick.id;else if(innerHeight+scrollY>=document.documentElement.scrollHeight-2&&hs.length&&!pick)a=hs[hs.length-1].id;'
            'if(pick&&Date.now()-pick.t>=1500&&innerHeight+scrollY>=document.documentElement.scrollHeight-2)a=pick.id;'
            'if(a===cur)return;cur=a;[].forEach.call(bar.querySelectorAll("a"),function(x){var on=x.getAttribute("href")==="#"+a;if(on){x.setAttribute("aria-current","true");'
            'var l=x.offsetLeft-bar.offsetLeft;if(l<bar.scrollLeft+12||l+x.offsetWidth>bar.scrollLeft+bar.clientWidth-12)bar.scrollTo({left:Math.max(0,l-bar.clientWidth/2),behavior:"smooth"});}'
            'else x.removeAttribute("aria-current");});}var raf=0;addEventListener("scroll",function(){if(!raf)raf=requestAnimationFrame(function(){raf=0;sync();});},{passive:true});sync();'
            '[].forEach.call(bar.querySelectorAll("a"),function(x){x.addEventListener("click",function(ev){var t=document.querySelector(x.getAttribute("href"));if(!t)return;ev.preventDefault();pick={id:t.id,t:Date.now()};'
            'addEventListener("wheel",function(){pick=null;},{once:true,passive:true});addEventListener("touchmove",function(){pick=null;},{once:true,passive:true});'
            'var top=document.querySelector(".top"),y=t.getBoundingClientRect().top+scrollY-(top?top.offsetHeight:49)-bar.offsetHeight+1;'
            'window.scrollTo({top:y,behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});history.replaceState(null,"",x.getAttribute("href"));});});})();</script>')   # inside the list's section, so it stays stuck all the way down
    write("coffee/index.html", page("Specialty coffee roasters and V60 recipes for their coffees",
                                    f"{len(coffees):,} specialty coffees from {len(names)} roasters, updated every day, each with a V60 recipe.", "/coffee/", body, nav=False, tight=True))

    # ---------- new this week: a page and a feed of the coffees added in the last seven days, newest day first ----------
    from datetime import date as _d, timedelta as _td
    from email.utils import format_datetime
    from datetime import datetime as _dt, timezone as _tz
    last = max((c.get("found") or "" for c in coffees), default="") or updated
    try:
        since = (_d.fromisoformat(last[:10]) - _td(days=6)).isoformat()
    except ValueError:
        since = ""
    # new means new from the roaster: the shop's own date when it gives one; else the day Goccio first saw it, but not the day a
    # roaster joined the list (that day brings its whole range, not new coffees)
    joined = {(x or {}).get("name"): (x or {}).get("first_seen") for x in (shops.values() if isinstance(shops, dict) else [])}
    def when(c):
        if c.get("published"):
            return c["published"][:10]
        f = (c.get("found") or "")[:10]
        return "" if f and f == (joined.get(c["roaster"]) or "")[:10] else f
    week = sorted([c for c in coffees if when(c) >= since and when(c)], key=lambda c: (when(c), c["roaster"], c["name"]), reverse=True)
    days, blocks = {}, []
    for c in week:
        days.setdefault(when(c), []).append(c)
    for day, cs in days.items():
        blocks.append(f'<h2 class="nw-day">{e(ddmmyyyy(day))}, {len(cs)} coffee{"s" if len(cs) != 1 else ""}</h2>' + coffee_list(cs, cpath, roaster=True, day=False))
    feed_link = f'<link rel="alternate" type="application/rss+xml" title="Goccio: new coffees" href="{BASE}/new/feed.xml">'
    body = (f'<section><div class="specs"><div class="spec wide"><h1>New this week</h1></div></div>'
            f'<p class="r-read">{len(week):,} specialty coffees added in the last seven days, each with a V60 recipe. '
            f'Follow them with the <a href="/new/feed.xml">feed</a> in any reader.</p>{"".join(blocks)}</section>')
    write("new/index.html", page("New specialty coffees this week, with their recipes",
                                 f"{len(week):,} specialty coffees added in the last seven days, from {len({c['roaster'] for c in week})} roasters, each with a V60 recipe.",
                                 "/new/", body, extra_head=feed_link, tight=True))
    urls.append((f"{BASE}/new/", updated))
    def rfc(day):
        try:
            return format_datetime(_dt.fromisoformat(day[:10]).replace(hour=6, tzinfo=_tz.utc))
        except ValueError:
            return ""
    items = "".join(
        f"<item><title>{e(c['name'])}, {e(c['roaster'])}</title><link>{BASE}{cpath[id(c)]}</link><guid isPermaLink=\"true\">{BASE}{cpath[id(c)]}</guid>"
        f"<pubDate>{rfc(when(c))}</pubDate><description>{e(', '.join(x for x in [c.get('origin'), c.get('process'), ', '.join(n for n in (c.get('notes') or []) if isinstance(n, str))] if x))}</description></item>\n"
        for c in week[:150])
    write("new/feed.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>Goccio: new coffees</title>'
          f"<link>{BASE}/new/</link><description>Every new specialty coffee, with its recipe before you buy.</description><language>en-gb</language>\n{items}</channel></rss>\n")
    print(f"new this week: {len(week)} coffees since {since}")

    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"<url><loc>{e(u)}</loc><lastmod>{m}</lastmod></url>\n" for u, m in urls) + "</urlset>\n")
    write("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n")
    bad = sum(1 for r in recs if not r)
    print(f"{len(coffees)} coffee pages, {len(by_roaster)} roaster pages, {len(urls)} addresses in the sitemap, {bad} without a recipe")


if __name__ == "__main__":
    main()

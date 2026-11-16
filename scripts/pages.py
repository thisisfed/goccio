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

SITE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
HOST = "bagtocup.thisisfed.xyz"
try:
    HOST = open(os.path.join(SITE, "CNAME")).read().strip() or HOST
except OSError:
    pass
BASE = "https://" + HOST
GRINDER = "Comandante C40"
e = lambda s: html.escape(str(s or ""), quote=True)


def slug(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"&", " and ", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80].strip("-") or "coffee"


def ddmmyyyy(iso):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{m[3]}/{m[2]}/{m[1]}" if m else ""


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
            pg = b.new_page()
            pg.goto(f"http://127.0.0.1:{port}/index.html")
            pg.wait_for_function("() => typeof window.bagRecipe === 'function'", timeout=60000)
            out = []
            for i in range(0, len(coffees), 500):
                out += pg.evaluate("(xs) => xs.map((x) => { try { return bagRecipe(x); } catch (err) { return null; } })", coffees[i:i + 500])
            b.close()
            return out
    finally:
        srv.shutdown()


# ---------- the look: the site's own, black and white plus the accent, 15/24/39/63 ----------
CSS = """
:root{--bg:#fff;--ink:#000;--muted:#808080;--rule:#e3e3e3;--pill:#e6e6e6;--hl:#ff4f00;
--sans:"Helvetica Neue",Helvetica,Arial,-apple-system,BlinkMacSystemFont,system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#000;--ink:#fff;--muted:#8c8c8c;--rule:#262626;--pill:#222;--hl:#ff5a14}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;overflow-x:clip}
body{margin:0;background:var(--bg);color:var(--ink);font:500 15px/1.35 var(--sans);letter-spacing:-.012em}
a{color:inherit;text-decoration:none}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px;border-bottom:1px solid var(--rule)}
.mark{font-size:15px}
.pill{display:inline-flex;align-items:center;height:32px;padding:0 12px;border-radius:4px;background:var(--pill);transition:background-color .15s}
.pill:hover{background-color:color-mix(in srgb,var(--pill) 80%,var(--ink))}
.btn{display:inline-flex;align-items:center;height:40px;padding:0 16px;border-radius:4px;background:var(--ink);color:var(--bg)}
main{padding:24px 12px 60px}
@media (min-width:760px){.top{padding:12px 24px}main{padding:39px 24px 63px}}
.crumb{margin:0 0 24px;color:var(--muted)}
.crumb a:hover,.list a:hover,.more a:hover,footer a:hover{color:var(--hl)}
h1{margin:0;font-size:39px;line-height:1.1;letter-spacing:-.03em;font-weight:700}
@media (min-width:760px){h1{font-size:63px}}
h2{margin:39px 0 12px;padding-top:12px;border-top:1px solid var(--rule);font-size:24px;line-height:1.2;letter-spacing:-.02em;font-weight:700}
.by{margin:6px 0 0;color:var(--muted)}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 24px;margin:24px 0 0}
dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
.notes{margin:12px 0 0}
.method{margin:0;color:var(--muted)}
.specs{display:flex;flex-wrap:wrap;gap:6px 24px;margin:12px 0 0;font-size:39px;line-height:1.1;letter-spacing:-.03em;font-weight:500}
.specs small{font-size:15px;color:var(--muted);letter-spacing:-.012em;margin-left:4px}
.pours{list-style:none;margin:24px 0 0;padding:0}
.pours li{display:grid;grid-template-columns:48px 64px 1fr;gap:12px;padding:6px 0;border-top:1px solid var(--rule)}
.pours span,.muted{color:var(--muted)}
.go{display:flex;flex-wrap:wrap;gap:8px;margin:24px 0 0}
.list{list-style:none;margin:0;padding:0}
.list li{padding:8px 0;border-top:1px solid var(--rule)}
.list b{font-weight:500}
.more{margin:0;padding-left:18px}
footer{padding:24px 12px;border-top:1px solid var(--rule);color:var(--muted)}
@media (min-width:760px){footer{padding:24px}}
footer p{margin:0 0 6px}
"""


def page(title, desc, path, body, extra_head=""):
    url = BASE + path
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="A Bag to a Cup">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}"><meta property="og:image" content="{BASE}/og/card.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/icons/icon-192.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png?v=2">
<style>{CSS}</style>{extra_head}
</head><body>
<header class="top"><a class="mark" href="/">A Bag to a Cup</a><a class="pill" href="/coffee/">Roasters</a></header>
<main>
{body}
</main>
<footer><p>Coffee details are read every day from each roaster’s own shop. Prices and stock change: check the roaster’s page before you buy.</p>
<p><a href="/">A Bag to a Cup</a>: a recipe for any coffee, for your brewer and your grinder.</p></footer>
</body></html>
"""


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
    urls = [(BASE + "/", updated), (BASE + "/coffee/", updated)]

    # ---------- a page per coffee ----------
    for name, cs in by_roaster.items():
        city = next((c.get("roaster_city") for c in cs if c.get("roaster_city")), "") or (shops.get(name) or {}).get("city", "")
        for c in cs:
            r = rec.get(id(c))
            path = cpath[id(c)]
            notes = [n for n in (c.get("notes") or []) if isinstance(n, str) and n.strip() and len(n) < 40][:5]
            process = c.get("process") or (cap(r["processLabel"]) if r and "process" not in r["missing"] else "")
            facts = [("Origin", e(c.get("origin"))), ("Process", e(process)), ("Variety", e(c.get("variety"))),
                     ("Roast", e(cap(r["roastLabel"])) if r and "roast" not in r["missing"] else ""),
                     ("Roasted for", e(cap(c["roast_for"])) if c.get("roast_for") in ("filter", "espresso") else ""),
                     ("Bag", e(" for ".join(x for x in [f'{c["bag_g"]} g' if c.get("bag_g") else "", c.get("price") or ""] if x))),
                     ("On the list since", e(ddmmyyyy(c.get("found") or c.get("published"))))]
            dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in facts if v)
            body = [f'<p class="crumb"><a href="/coffee/">Roasters</a> / <a href="/coffee/{rslug[name]}/">{e(name)}</a></p>',
                    f"<h1>{e(c['name'])}</h1>", f'<p class="by">{e(name)}{", " + e(city) if city else ""}</p>', f"<dl>{dl}</dl>"]
            if notes:
                body.append(f'<p class="notes">Flavour: {e(and_list(notes))} (the roaster’s notes).</p>')
            brew = "/#brew=" + e(quote(c.get("url") or "", safe=""))
            ld = ""
            if r and r.get("water"):
                specs = (f'<div class="specs"><span>{r["clicks"]}<small>clicks, {GRINDER}</small></span>'
                         f'<span>{r["dose"]} → {r["water"]}<small>g</small></span><span>{r["temp"]}<small>°C</small></span>'
                         f'<span>{mmss(r["lo"])} – {mmss(r["hi"])}<small>total</small></span></div>')
                pours = "".join(f'<li><span>{mmss(p["t"])}</span><b>{p["to"]} g</b><span>{e(p["note"])}</span></li>' for p in r["pours"] if p.get("to") is not None)
                miss = r["missing"]
                hint = ""
                if miss:
                    what = "roast or process" if len(miss) == 2 else miss[0]
                    hint = f'<p class="muted">The roaster doesn’t state the {what}, so this starts from the middle of the range. Pick it in the app to sharpen the recipe.</p>'
                body += ["<h2>A V60 recipe</h2>", f'<p class="method">{e(r["method"])}, {r["dose"]} g of coffee to {r["water"]} g of water (1:{r["ratio"]})</p>', specs,
                         f'<ol class="pours">{pours}</ol>' if pours else "", hint,
                         '<p class="muted">Another grinder or brewer (Chemex, Kalita, AeroPress, French press and more), a timer for every pour, and a journal that adjusts the next cup: all in the app.</p>']
                steps = [{"@type": "HowToStep", "text": f'{mmss(p["t"])}: pour to {p["to"]} g. {p["note"]}'.strip()} for p in r["pours"] if p.get("to") is not None]
                ld = json.dumps({"@context": "https://schema.org", "@type": "Recipe", "name": f"V60 recipe for {c['name']} ({name})",
                                 "description": f"A V60 pour over recipe for {c['name']} from {name}.", "image": [BASE + "/og/card.png"],
                                 "author": {"@type": "Organization", "name": "A Bag to a Cup", "url": BASE + "/"},
                                 "recipeCategory": "Drink", "recipeYield": "1 cup", "totalTime": iso_dur(r["hi"]), "keywords": f"V60, pour over, {name}, {c.get('origin') or ''}".strip(", "),
                                 "recipeIngredient": [f'{r["dose"]} g {c["name"]} coffee, ground at {r["clicks"]} clicks on a {GRINDER}', f'{r["water"]} g water at {r["temp"]}°C'],
                                 "recipeInstructions": steps}, ensure_ascii=False).replace("</", "<\\/")
                ld = f'\n<script type="application/ld+json">{ld}</script>'
            body.append(f'<p class="go"><a class="btn" href="{brew}">Brew it step by step</a>'
                        + (f'<a class="pill" href="{e(c["url"])}" rel="noopener">Buy from {e(name)}</a>' if c.get("url") else "") + "</p>")
            others = [o for o in cs if o is not c][:12]
            if others:
                body.append(f"<h2>More from {e(name)}</h2>")
                body.append('<ul class="list">' + "".join(f'<li><a href="{cpath[id(o)]}"><b>{e(o["name"])}</b></a>' + (f' <span class="muted">{e(o.get("origin"))}</span>' if o.get("origin") else "") + "</li>" for o in others) + "</ul>")
            bits = [x for x in [(process or "").lower(), c.get("origin")] if x]
            desc = f"A V60 recipe for {c['name']} from {name}{', ' + city if city else ''}" + (f": {' '.join(bits)}" if bits else "") + "."
            if r and r.get("water"):
                desc += f' {r["dose"]} g to {r["water"]} g at {r["temp"]}°C, {r["clicks"]} clicks on a {GRINDER}, about {mmss(r["hi"])} in all.'
            write(path.strip("/") + "/index.html", page(f"{c['name']}, {name}: a V60 recipe", desc, path, "\n".join(x for x in body if x), ld))
            urls.append((BASE + path, (c.get("found") or c.get("published") or updated)[:10]))

    # ---------- a page per roaster ----------
    for name, cs in by_roaster.items():
        city = next((c.get("roaster_city") for c in cs if c.get("roaster_city")), "")
        shop = (shops.get(name) or {}).get("shop") or ""
        items = "".join(f'<li><a href="{cpath[id(c)]}"><b>{e(c["name"])}</b></a> <span class="muted">'
                        + e(", ".join(x for x in [c.get("origin"), c.get("process"), c.get("price")] if x)) + "</span></li>" for c in cs)
        body = (f'<p class="crumb"><a href="/coffee/">Roasters</a></p><h1>{e(name)}</h1>'
                f'<p class="by">{e(city) + ", " if city else ""}{len(cs)} coffee{"s" if len(cs) != 1 else ""} on the list'
                + (f', <a href="{e(shop)}" rel="noopener">their shop</a>' if shop else "") + "</p>"
                f"<h2>Coffees, each with a V60 recipe</h2><ul class=\"list\">{items}</ul>")
        desc = f"{len(cs)} coffee{'s' if len(cs) != 1 else ''} from {name}{', ' + city if city else ''}, each with a V60 recipe: grind, dose, temperature and every pour."
        write(f"coffee/{rslug[name]}/index.html", page(f"{name}: coffees and V60 recipes", desc, f"/coffee/{rslug[name]}/", body))
        urls.append((f"{BASE}/coffee/{rslug[name]}/", updated))

    # ---------- every roaster ----------
    names = sorted(by_roaster, key=lambda n: slug(n))
    items = "".join(f'<li><a href="/coffee/{rslug[n]}/"><b>{e(n)}</b></a> <span class="muted">'
                    + e(", ".join(x for x in [next((c.get("roaster_city") for c in by_roaster[n] if c.get("roaster_city")), ""),
                                              f"{len(by_roaster[n])} coffee{'s' if len(by_roaster[n]) != 1 else ''}"] if x)) + "</span></li>" for n in names)
    body = (f"<h1>Roasters</h1><p class=\"by\">{len(names)} roasters, {len(coffees):,} coffees, updated {ddmmyyyy(updated)}. Every coffee has a V60 recipe.</p>"
            f'<h2>A to Z</h2><ul class="list">{items}</ul>')
    write("coffee/index.html", page("Specialty coffee roasters and V60 recipes for their coffees",
                                    f"{len(coffees):,} specialty coffees from {len(names)} roasters, updated every day, each with a V60 recipe.", "/coffee/", body))

    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"<url><loc>{e(u)}</loc><lastmod>{m}</lastmod></url>\n" for u, m in urls) + "</urlset>\n")
    write("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n")
    bad = sum(1 for r in recs if not r)
    print(f"{len(coffees)} coffee pages, {len(by_roaster)} roaster pages, {len(urls)} addresses in the sitemap, {bad} without a recipe")


if __name__ == "__main__":
    main()

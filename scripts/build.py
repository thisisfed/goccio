"""Make the published page light: run by the publish workflow on the copy of the site it is about to upload.

    python3 scripts/build.py /tmp/site

- The page's big style block and big script move into their own files under /assets/, minified (esbuild) and named by
  their content (app.3f9c2a1b.js), so a phone keeps them for a year and only downloads them again when they change.
  The page itself shrinks from about 1 MB to a few tens of KB. The source index.html in the repo stays as it is, readable.
- _headers tells Cloudflare how long each kind of file can be kept.
- data/list.json is the coffee list without the fields the page never reads (where a note came from, when it was checked...).
  data/releases.json stays whole for the coffee pages and the health page. latest.json is trimmed the same way.
"""
import hashlib, json, re, subprocess, sys
from pathlib import Path

site = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
assets = site / "assets"
assets.mkdir(exist_ok=True)
html = (site / "index.html").read_text(encoding="utf-8")


def minify(code, loader):
    r = subprocess.run(["npx", "--yes", "esbuild@0.24.0", f"--loader={loader}", "--minify", "--charset=utf8", "--log-level=error"],
                       input=code.encode("utf-8"), capture_output=True, check=True)
    return r.stdout.decode("utf-8")


def store(code, ext):
    h = hashlib.sha256(code.encode("utf-8")).hexdigest()[:10]
    name = f"app.{h}.{ext}"
    (assets / name).write_text(code, encoding="utf-8")
    return "/assets/" + name


before = len(html.encode("utf-8"))
blocks = list(re.finditer(r"<(style|script)>(.*?)</\1>", html, re.S))
big_css = max((m for m in blocks if m.group(1) == "style"), key=lambda m: len(m.group(2)))
big_js = max((m for m in blocks if m.group(1) == "script"), key=lambda m: len(m.group(2)))
css_url = store(minify(big_css.group(2), "css"), "css")
js_url = store(minify(big_js.group(2), "js"), "js")
# replace from the end so the earlier position stays right
for m, new in sorted([(big_css, f'<link rel="stylesheet" href="{css_url}">'), (big_js, f'<script src="{js_url}"></script>')], key=lambda x: -x[0].start()):
    html = html[:m.start()] + new + html[m.end():]
# the intro's count ("9,653 coffees. From 791 roasters.") is in the page itself, not only counted up by the code: anything that reads the page
# before the code runs (search engines, reviewers, a slow phone) saw "0 coffees. From near and far." (Nov 2026)
try:
    rel = json.loads((site / "data" / "releases.json").read_text(encoding="utf-8")).get("releases", [])
    n_co, n_ro = len(rel), len({r.get("roaster") for r in rel if r.get("roaster")})
    if n_co:
        html = html.replace('<span id="statN">0</span>', f'<span id="statN">{n_co:,}</span>', 1)
        html = html.replace('<span class="stat-s" id="statS">From near and far.</span>', f'<span class="stat-s" id="statS">From {n_ro:,} roasters.</span>', 1)
except Exception as e:
    print("intro count not written:", e)
# the app's code starts downloading with the page, not when the parser reaches the end of it
html = html.replace("</title>", f'</title><link rel="preload" href="{js_url}" as="script">', 1)
(site / "index.html").write_text(html, encoding="utf-8")
print(f"index.html {before // 1024} KB -> {len(html.encode('utf-8')) // 1024} KB; {css_url} {(assets / css_url.split('/')[-1]).stat().st_size // 1024} KB; "
      f"{js_url} {(assets / js_url.split('/')[-1]).stat().st_size // 1024} KB")

# the coffee list without what the page never reads
DROP = {"methods_none", "roast_checked", "roaster_nation", "notes_checked", "roast_from", "variety_from", "notes_from", "process_from",
        "notes_v", "notes_orig", "origin_from", "price_from"}
DROP_ROASTER = {"error", "note", "platform"}
def trim(d):
    d = dict(d)
    d["releases"] = [{k: v for k, v in r.items() if k not in DROP} for r in d.get("releases", [])]
    d["roasters"] = [{k: v for k, v in r.items() if k not in DROP_ROASTER} for r in d.get("roasters", []) if isinstance(r, dict)]
    return d
full = json.loads((site / "data" / "releases.json").read_text(encoding="utf-8"))
(site / "data" / "list.json").write_text(json.dumps(trim(full), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
lt = site / "data" / "latest.json"
if lt.exists():
    lt.write_text(json.dumps(trim(json.loads(lt.read_text(encoding="utf-8"))), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"data/list.json {(site / 'data' / 'list.json').stat().st_size // 1024} KB (releases.json {(site / 'data' / 'releases.json').stat().st_size // 1024} KB)")

# how long each kind of file can be kept (Cloudflare Pages reads _headers)
(site / "_headers").write_text("""/assets/*
  Cache-Control: public, max-age=31536000, immutable
/fonts/*
  Cache-Control: public, max-age=2592000
/img/*
  Cache-Control: public, max-age=2592000
/icons/*
  Cache-Control: public, max-age=2592000
/og/*
  Cache-Control: public, max-age=604800
/lib/*
  Cache-Control: public, max-age=86400
""")
print("_headers written")

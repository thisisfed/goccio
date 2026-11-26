"""Safety net 3: a daily look at the live site, as a visitor and as Google see it.

Run by .github/workflows/site-check.yml (every morning after the scan, after every publish, and by hand).
Writes a report (the run's summary page) and exits 1 when something is wrong; the workflow then opens an
issue labelled "site-check" (GitHub emails it), and closes it again once a check passes.

    python3 scripts/site_check.py [https://www.goccio.co.uk]
"""
import json, os, random, re, sys, time, urllib.request
from datetime import date, datetime, timezone

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://www.goccio.co.uk").rstrip("/")
UA = "Goccio-site-check/1.0 (+https://www.goccio.co.uk)"
rows, bad = [], []


def note(ok, what, detail=""):
    rows.append(("✅" if ok else "❌", what, detail))
    if not ok:
        bad.append(f"{what}: {detail}")


def get(path, data=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(BASE + path, data=data, headers={"User-Agent": UA, "content-type": "application/json"} if data else {"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if i == tries - 1:
                return e.code, ""
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                return 0, str(e)
        time.sleep(5)


# 1. what Google reads: robots.txt, the sitemap, and a few coffee pages from it
st, robots = get("/robots.txt")
note(st == 200 and "Sitemap:" in robots, "robots.txt", f"HTTP {st}")
st, smap = get("/sitemap.xml")
locs = re.findall(r"<loc>([^<]+)</loc>", smap) if st == 200 else []
note(st == 200 and smap.lstrip().startswith("<?xml") and len(locs) >= 5000, "Sitemap", f"HTTP {st}, {len(locs)} addresses" + ("" if smap.lstrip().startswith("<?xml") or st != 200 else ", but it is not XML (an HTML page?)"))
coffee = [u for u in locs if u.count("/coffee/") and u.rstrip("/").count("/") >= 5]
for u in random.sample(coffee, min(3, len(coffee))):
    st, page = get(u.replace("https://www.goccio.co.uk", "").replace(BASE, ""))
    note(st == 200 and "Recipe" in page and "application/ld+json" in page, "Coffee page", f"HTTP {st} {u}")

# 2. the data: today's list, recent enough and full
st, raw = get("/data/releases.json")
try:
    d = json.loads(raw)
    n, upd = len(d.get("releases", [])), d.get("updated", "")
    age = (date.today() - date.fromisoformat(upd)).days if upd else 99
    note(n >= 5000 and age <= 2, "Coffee data", f"{n} coffees, updated {upd} ({age} days ago)")
except Exception as e:  # noqa: BLE001
    note(False, "Coffee data", f"HTTP {st}, unreadable: {e}")

# 3. Goccio's brain (the answers live on the server)
st, ans = get("/api/goccio", data=json.dumps({"q": "why is my coffee sour?"}).encode())
note(st == 200 and len(ans) > 20, "Goccio's answers (/api/goccio)", f"HTTP {st}")

# 4. the page itself in a real browser, on a phone and on a computer: no script errors, the list fills in, Goccio is there
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, vw, mobile in (("phone", {"width": 390, "height": 844}, True), ("computer", {"width": 1280, "height": 800}, False)):
            ctx = b.new_context(viewport=vw, is_mobile=mobile, has_touch=mobile, user_agent=None)
            pg = ctx.new_page(); errs = []
            pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)[:160]))
            t0 = time.time()
            pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
            try:
                pg.wait_for_function("document.querySelectorAll('#shelf .item').length >= 5", timeout=30000)
                items = pg.evaluate("document.querySelectorAll('#shelf .item').length")
            except Exception:  # noqa: BLE001
                items = 0
            secs = round(time.time() - t0, 1)
            pg.wait_for_timeout(3000)
            drop = pg.evaluate("!!document.querySelector('#gdrop svg .gd-b') && document.querySelector('#gdrop svg .gd-b').getAttribute('d').length > 10")
            note(items >= 5, f"Home page on a {name}: coffees listed", f"{items} shown after {secs} s")
            note(not errs, f"Home page on a {name}: no script errors", "; ".join(errs[:3]))
            note(drop, f"Home page on a {name}: Goccio drawn", "")
            ctx.close()
        b.close()
except Exception as e:  # noqa: BLE001
    note(False, "Browser check", f"couldn't run: {e}")

when = datetime.now(timezone.utc).strftime("%d %m %Y %H:%M UTC")
out = [f"## Goccio site check, {when}", "", f"**{'All good' if not bad else str(len(bad)) + ' problem' + ('s' if len(bad) > 1 else '')}** on {BASE}", "", "| | Check | Detail |", "|---|---|---|"]
out += [f"| {a} | {b_} | {c} |" for a, b_, c in rows]
report = "\n".join(out) + "\n"
print(report)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(report)
open("site-check.md", "w").write(report)
sys.exit(1 if bad else 0)

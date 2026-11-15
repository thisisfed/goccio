#!/usr/bin/env python3
"""One-off: find UK and Irish specialty roasters and check which shops the scanner can read.

Candidates come from the roasterlist.pages.dev directory (UK) plus a hand list for Ireland. Each candidate's own
website is then read with the same code as the daily scan, and data/discover.json records what came back:
platform, how many single-origin coffees, a few names, or why it failed. Nothing is added to roasters.json here.
"""
import json, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import scan  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "discover.json"
DIR = "https://roasterlist.pages.dev"
SOCIAL = re.compile(r"gstatic|googleapis|jsdelivr|unpkg|cdn|fonts\.|schema\.org|w3\.org|gravatar|wp\.com|instagram|facebook|twitter|x\.com|tiktok|linkedin|youtube|pinterest|google|roasterlist|pages\.dev|wa\.me|maps\.|threads\.net|spotify|apple\.com|trustpilot|cloudflare", re.I)

IRELAND = [  # name, website, city (the directory is UK-only)
    ("Full Circle Roasters", "https://fullcircleroasters.ie", "Dublin"), ("Imbibe", "https://imbibe.ie", "Dublin"),
    ("Cloud Picker", "https://cloudpickercoffee.ie", "Dublin"), ("Upside Coffee", "https://upsidecoffee.com", "Dublin"),
    ("Silverskin", "https://silverskincoffee.ie", "Dublin"), ("Sumo Coffee Roasters", "https://sumocoffeeroasters.com", "Dublin"),
    ("Calendar Coffee", "https://calendarcoffee.ie", "Galway"), ("Bell Lane", "https://belllane.ie", "Mullingar"),
    ("West Cork Coffee", "https://westcorkcoffee.ie", "Innishannon"), ("Golden Bean", "https://thegoldenbean.ie", "Shanagarry"),
    ("Badger & Dodo", "https://badgeranddodo.ie", "Fermoy"), ("Roasted Brown", "https://roastedbrown.com", "Dublin"),
    ("Two Fifty Square", "https://twofiftysquare.ie", "Dublin"), ("Velo Coffee", "https://velocoffee.ie", "Dublin"),
    ("Stonevalley", "https://stonevalleyroasters.com", "Clonakilty"), 
    ("The Old Barracks", "https://theoldbarracks.ie", "Birdhill"), ("Ariosa", "https://ariosacoffee.com", "Meath"),
    ("Mind the Step", "https://mindthestep.ie", "Dublin"), ("Groundstate", "https://groundstate.ie", "Dublin"),
    ("Cool Hand Coffee", "https://coolhandcoffeeroasters.ie", "Dublin"), ("Urbanity", "https://urbanity.ie", "Dublin"),
    ("PS Coffee Roasters", "https://pscoffeeroasters.ie", "Naas"), ("Ponaire", "https://ponaire.ie", "Limerick"),
    ("Cork Coffee Roasters", "https://corkcoffee.ie", "Cork"), ("Baobab", "https://baobabcoffee.ie", "Celbridge"), ("Coffeeangel", "https://coffeeangel.com", "Dublin"),
    ("Anam Coffee", "https://anamcoffee.ie", "Dublin"), 
    ("Red Strand Coffee", "https://redstrandcoffee.ie", "Clonakilty"), ("Bear Market", "https://bearmarket.ie", "Dublin"),
]


def get(url):
    return scan.get_text(url, tries=2, limit=3_000_000)


def directory():
    """Every /roaster/<slug>/ link on the directory's list pages, with the name and place the list shows."""
    pages = ["/uk-coffee-roasters/", "/single-origin-coffee-roasters/", "/buy-coffee-beans-online/", "/light-roast-coffee-uk/",
             "/direct-trade-coffee-roasters/", "/buy-coffee-beans-no-subscription/", "/coffee-roasters-with-subscriptions/",
             "/award-winning-coffee-roasters/", "/decaf-coffee-roasters/", "/coffee-roasters-with-cafes/"]
    try:
        disc = get(DIR + "/discover/")
        pages += sorted(set(re.findall(r'href="(/coffee-roasters-in-[a-z-]+/)"', disc)))
    except Exception as e:  # noqa: BLE001
        print("discover page:", e)
    slugs = {}
    for p in pages:
        for n in range(1, 30):
            url = DIR + p + ("" if n == 1 else f"page/{n}/")
            try:
                html = get(url)
            except Exception:  # noqa: BLE001
                break
            got = set(re.findall(r'href="(?:https://roasterlist\.pages\.dev)?/roaster/([a-z0-9-]+)/?"', html))
            new = got - set(slugs)
            for s in got:
                slugs.setdefault(s, p)
            if n > 1 and not new:
                break
            if not re.search(r'href="[^"]*page/%d/' % (n + 1), html):
                break
    print(len(slugs), "roasters in the directory")
    return sorted(slugs)


def roaster_page(slug):
    try:
        html = get(f"{DIR}/roaster/{slug}/")
    except Exception as e:  # noqa: BLE001
        return {"slug": slug, "error": f"directory page: {e}"}
    name = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    name = scan.strip_html(name.group(1)).strip() if name else slug.replace("-", " ").title()
    loc = re.search(r'"addressLocality"\s*:\s*"([^"]+)"', html) or re.search(r'"addressRegion"\s*:\s*"([^"]+)"', html)
    site = None
    v = re.search(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(?:\s|<[^>]+>)*Visit\b', html, re.I)
    cands = ([v.group(1)] if v else []) + re.findall(r'"(?:url|sameAs)"\s*:\s*"(https?://[^"]+)"', html) + re.findall(r'href="(https?://[^"]+)"', html)
    for u in cands:
        if not SOCIAL.search(urllib.parse.urlparse(u).netloc):
            site = u
            break
    text = scan.strip_html(html)
    return {"slug": slug, "name": name, "place": loc.group(1) if loc else None, "site": site,
            "about": re.sub(r"\s+", " ", text)[:4000]}


def norm(u):
    p = urllib.parse.urlparse(u)
    return f"{p.scheme or 'https'}://{p.netloc}".rstrip("/")


def final_home(shop):
    """Where the shop's home page really lives (theroastingparty.co.uk -> roastingparty.com)."""
    try:
        req = urllib.request.Request(shop, headers={"User-Agent": scan.UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return norm(resp.geturl())
    except Exception:  # noqa: BLE001
        return shop


def test(c):
    c = {**c, "shop": final_home(c["shop"])}
    r = {"name": c["name"], "shop": c["shop"], "city": c.get("place") or "", "region": "UK", "country": c.get("country", "GB")}
    if r["country"] == "IE":
        r["region"] = "Europe"
    t0 = time.time()
    try:
        kind, items, err = scan.scan_roaster(r)
    except Exception as e:  # noqa: BLE001
        kind, items, err = None, [], f"{type(e).__name__}: {e}"
    recs = []
    for it in items or []:
        try:
            rec = scan.classify(it, r)
        except Exception:  # noqa: BLE001
            rec = None
        if rec:
            recs.append(rec)
    drops = {k: v[:4] for k, v in (scan.DROPS.get(r["name"]) or {}).items()}
    keep = ("name", "origin", "process", "variety", "roast", "roast_for", "price", "bag_g", "url")
    return {**c, "platform": kind, "products": len(items or []), "coffees": len(recs), "error": (err or "")[:600],
            "recs": [{k: x.get(k) for k in keep} for x in recs], "drops": drops,
            "sample": [f"{x['name']} | {x.get('origin')} | {x.get('process')} | {x.get('roast')} | {x.get('price')}" for x in recs[:6]],
            "secs": round(time.time() - t0, 1)}


def main():
    have = {norm(r["shop"]) for r in json.loads((ROOT / "data" / "roasters.json").read_text())}
    have |= {norm(r.get("feed") or r["shop"]) for r in json.loads((ROOT / "data" / "roasters.json").read_text())}
    slugs = directory()
    with ThreadPoolExecutor(max_workers=12) as pool:
        pages = list(pool.map(roaster_page, slugs))
    cands = []
    for p in pages:
        if p.get("site"):
            cands.append({"name": p["name"], "shop": norm(p["site"]), "place": p.get("place"), "src": "roasterlist/" + p["slug"],
                          "about": p.get("about", "")[:600]})
    for n, u, city in IRELAND:
        cands.append({"name": n, "shop": norm(u), "place": city, "country": "IE", "src": "hand"})
    seen, todo = set(), []
    for c in cands:
        if c["shop"] in seen:
            continue
        seen.add(c["shop"])
        c["already"] = c["shop"] in have
        todo.append(c)
    print(len(todo), "candidates,", sum(c["already"] for c in todo), "already listed")
    fresh = [c for c in todo if not c["already"]]
    with ThreadPoolExecutor(max_workers=16) as pool:
        res = list(pool.map(test, fresh))
    # shops that asked us to slow down get one more, unhurried try
    for i, x in enumerate(res):
        if "429" in x["error"]:
            time.sleep(20)
            res[i] = test({k: x[k] for k in ("name", "shop", "place", "src", "country", "already") if k in x})
    out = {"directory": len(slugs), "no_site": [p for p in pages if not p.get("site")],
           "already": [c["name"] for c in todo if c["already"]], "tested": sorted(res, key=lambda x: -x["coffees"])}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("ok", sum(1 for x in res if x["coffees"]), "with coffees of", len(res))


if __name__ == "__main__":
    main()

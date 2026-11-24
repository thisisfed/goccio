"""Find new specialty coffee roasters anywhere in the world and add up to 25 a run to data/roasters.json.

Where they come from: OpenStreetMap, the open map anyone can edit (ODbL), which tags roasteries as craft=coffee_roaster
with their website. One query a run to its public Overpass API. Shops already on the list, or that asked to be removed,
are left out, and so is every shop checked in the last 120 days (data/world_seen.json).

How a shop gets in: it is read exactly as the daily scan reads it (Shopify, WooCommerce, Squarespace, a sitemap; robots.txt
and the same gentle pace), and it must sell coffee beans the scanner can read: at least 3 coffees, at least 2 of them
naming their origin (single origins are what specialty roasters sell; a shop of blends called House and Italian isn't).
Up to 100 shops are tried a run; the first 25 that pass are added (Nov 2026: was 10 of 40, to reach 1,500 roasters sooner). None found: nothing changes until the next run.

    python3 scripts/world.py            # one run
    python3 scripts/world.py --dry      # report only, change nothing
"""
import json, os, random, re, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import scan  # noqa: E402
import discover  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SEEN = ROOT / "data" / "world_seen.json"
MAP = ROOT / "data" / "world_map.json"   # the last list the map gave: used when every map server is busy
OVERPASS = "https://overpass-api.de/api/interpreter"
OVERPASS_ALSO = ["https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]   # the same open map, other public servers: tried when the main one is busy
QUERY = '[out:json][timeout:240];nwr["craft"="coffee_roaster"][~"^(website|contact:website|url)$"~"."];out tags;'
MAX_ADD, MAX_TRY, RECHECK_DAYS = int(os.environ.get("WORLD_MAX_ADD") or 25), int(os.environ.get("WORLD_MAX_TRY") or 100), 120   # a run by hand can ask for more (the workflow's inputs)
WORKERS = 8   # shops checked side by side: each is a different site, read at the scan's own gentle pace

EUROPE = set("AD AL AT BA BE BG BY CH CY CZ DE DK EE ES FI FO FR GI GR HR HU IE IS IT LI LT LU LV MC MD ME MK MT NL NO PL PT RO RS SE SI SK SM UA VA XK".split())
NORTH_AMERICA = {"US", "CA", "MX"}
ASIA = set("AE AF AM AZ BD BH BN BT CN GE HK ID IL IN IQ IR JO JP KG KH KR KW KZ LA LB LK MM MN MO MV MY NP OM PH PK PS QA SA SG SY TH TJ TL TM TR TW UZ VN YE".split())
TLD = {"uk": "GB", "gb": "GB"}   # any other two-letter ending is its country (.de, .jp, .ie); .com and the like say nothing


def region(cc):
    return "UK" if cc == "GB" else "Europe" if cc in EUROPE else "North America" if cc in NORTH_AMERICA else "Asia" if cc in ASIA else "World"


def country(tags, shop):
    cc = (tags.get("addr:country") or "").strip().upper()
    if re.fullmatch(r"[A-Z]{2}", cc):
        return cc
    end = discover.host(shop).rsplit(".", 1)[-1]
    return TLD.get(end, end.upper() if len(end) == 2 and end not in ("co", "io", "me", "tv", "ai", "cc") else "")


def candidates():
    """(name, shop, city, country) for every roastery on the map with a website."""
    els, err = None, None
    for url in [OVERPASS] + OVERPASS_ALSO:
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": QUERY}).encode(),
                                     headers={"User-Agent": scan.UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                els = json.loads(r.read()).get("elements", [])
            break
        except Exception as e:  # noqa: BLE001
            err = e
            print(f"map server busy ({url.split('/')[2]}: {type(e).__name__}), trying the next")
    if els is None:
        raise err
    out, seen = [], set()
    for el in els:
        t = el.get("tags") or {}
        site, name = t.get("website") or t.get("contact:website") or t.get("url") or "", (t.get("name") or "").strip()
        if not site or not name or len(name) > 60:
            continue
        if not site.startswith("http"):
            site = "https://" + site
        try:
            u = urllib.parse.urlparse(site)
        except ValueError:
            continue
        h = discover.host(site)
        if not h or "." not in h or h in seen or re.search(r"(facebook|instagram|google|linktr|wixsite|business\.site|tripadvisor|yelp)\.", h):
            continue   # a social page or a listing is not a shop
        seen.add(h)
        shop = f"{u.scheme or 'https'}://{u.netloc}"
        out.append({"name": name, "shop": shop, "city": (t.get("addr:city") or "").strip(), "country": country(t, shop)})
    return out


def check(c):
    """Read the shop as the daily scan would: how many coffees, and how many name their origin."""
    r = {"name": c["name"], "shop": c["shop"], "_old": {}}
    try:
        kind, items, _ = scan.scan_roaster(r)
    except Exception:  # noqa: BLE001
        return None, 0, 0, "unreadable"
    recs = []
    for it in items or []:
        try:
            rec = scan.classify(it, r)
        except Exception:  # noqa: BLE001
            rec = None
        if rec:
            recs.append(rec)
    return kind, len(recs), sum(1 for x in recs if x.get("origin")), scan.specialty_gate(recs, c["name"])


def main():
    dry = "--dry" in sys.argv
    today = date.today()
    roasters = scan.load_roasters()
    have = {discover.host(r["shop"]) for r in roasters} | {discover.host(r.get("feed") or "") for r in roasters} | discover.blocked()
    names = {discover.norm(r["name"]) for r in roasters}
    try:
        seen = json.loads(SEEN.read_text())
    except (OSError, ValueError):
        seen = {}
    fresh = lambda h: h in seen and seen[h] >= (today - timedelta(days=RECHECK_DAYS)).isoformat()
    try:
        cands = candidates()
        MAP.write_text(json.dumps(cands, ensure_ascii=False, indent=0) + "\n")
    except Exception as e:  # noqa: BLE001
        try:
            cands = json.loads(MAP.read_text())
            print(f"map not reachable this time ({type(e).__name__}): using its last list ({len(cands)} roasteries)")
        except (OSError, ValueError):
            print(f"map not reachable this time ({type(e).__name__}) and no saved list: nothing changes until the next run"); return
    new = [c for c in cands if discover.host(c["shop"]) not in have and discover.norm(c["name"]) not in names and not fresh(discover.host(c["shop"]))]
    random.Random(today.isoformat()).shuffle(new)   # a different handful each day, the whole world in turn
    print(f"{len(cands)} roasteries with a website on the map, {len(new)} not on the list and not checked lately")
    added, tried = [], 0
    batch = new[:MAX_TRY]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(check, batch))   # read side by side, then taken in the day's order
    for c, res in zip(batch, results):
        if len(added) >= MAX_ADD:
            break
        tried += 1
        kind, n, origins, gate = res
        seen[discover.host(c["shop"])] = today.isoformat()
        ok = kind and n >= 3 and origins >= 2 and not gate   # specialty only (scan.specialty_gate)
        print(f"  {'ADD ' if ok else 'skip'} {c['name']} ({c['shop']}, {c['country'] or '?'}): {kind or 'unreadable'}, {n} coffees, {origins} with an origin{'; not specialty: ' + gate if kind and gate else ''}")
        if ok:
            r = {"name": c["name"], "shop": c["shop"], "city": c["city"], "country": c["country"], "region": region(c["country"])}
            if c["country"] == "GB":
                r["nation"] = discover.nation(c["city"])
            roasters.append(r); added.append(c["name"])
    print(f"added {len(added)}: {', '.join(added) or 'none this time'}")
    if dry:
        return
    SEEN.write_text(json.dumps(dict(sorted(seen.items())), indent=0) + "\n")
    if added:
        discover.save_roasters(roasters)


if __name__ == "__main__":
    main()

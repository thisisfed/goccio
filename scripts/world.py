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
import json, os, random, re, sys, time, urllib.parse, urllib.request
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
QUERY = '[out:json][timeout:240];nwr["craft"="coffee_roaster"][~"^(website|contact:website|url)$"~"."];out tags;'   # the whole world at once (kept for reference)
# the world in pieces: a small question gets through where the whole world times out; a piece that fails uses its last answer
REGIONS = {"Europe": (34, -25, 72, 45), "North America": (5, -170, 75, -50), "South America": (-57, -90, 13, -30),
           "Africa and the Middle East": (-36, -20, 38, 60), "Asia": (0, 45, 60, 100), "East Asia and Oceania": (-50, 100, 60, 180)}
def region_query(b):
    s, w, n, e = b
    site = '[~"^(website|contact:website|url)$"~"."]'
    return f'[out:json][timeout:180];(nwr["craft"="coffee_roaster"]{site}({s},{w},{n},{e});nwr["shop"="coffee_roasting"]{site}({s},{w},{n},{e}););out tags;'
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


def ask_map(query):
    """One question to the open map: each server in turn, then once more after a pause (busy servers often clear)."""
    err = None
    for rnd in range(2):
        for url in [OVERPASS] + OVERPASS_ALSO:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": query}).encode(),
                                         headers={"User-Agent": scan.UA, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.loads(r.read()).get("elements", [])
            except Exception as e:  # noqa: BLE001
                err = e
                print(f"  map server busy ({url.split('/')[2]}: {type(e).__name__})")
        if rnd == 0:
            time.sleep(20)
    raise err


def candidates():
    """(name, shop, city, country) for every roastery on the map with a website, asked region by region. A region the map
    can't answer today uses its last answer (data/world_map.json); only when every region fails with nothing saved does it raise."""
    try:
        saved = json.loads(MAP.read_text())
    except (OSError, ValueError):
        saved = {}
    if isinstance(saved, list):
        saved = {"all": saved}   # the first saved list was the whole world in one
    out, ok, fresh_, need_all = [], 0, {}, False
    for reg, box in REGIONS.items():
        try:
            got = parse_map(ask_map(region_query(box)))
            fresh_[reg] = got; ok += 1
            print(f"map, {reg}: {len(got)} roasteries with a website")
        except Exception as e:  # noqa: BLE001
            got = saved.get(reg) or []
            if not got:
                need_all = True
            print(f"map, {reg}: not reachable ({type(e).__name__}), using its last answer ({len(got)})")
        out += got
    if not ok and not any(saved.values()):
        raise RuntimeError("no map region reachable and nothing saved")
    if need_all:
        out += saved.get("all") or []   # a region with no answer of its own: the whole-world list saved before regions
    if fresh_:
        keep = {k: v for k, v in saved.items() if k != "all"}
        keep.update(fresh_)
        MAP.write_text(json.dumps(keep, ensure_ascii=False, indent=0) + "\n")
    seen, uniq = set(), []
    for c in out:
        h = discover.host(c["shop"])
        if h not in seen:
            seen.add(h); uniq.append(c)
    return uniq


def from_uk_directory(have, names, limit=150):
    """Second source: the public UK roaster directory (roasterlist.pages.dev), the same list the "Find new roasters" run reads.
    Only roasters not on the list have their directory page read, for their own website; at most `limit` a run."""
    try:
        listed = discover.directory()
    except Exception as e:  # noqa: BLE001
        print(f"UK directory not reachable ({type(e).__name__})"); return []
    todo = [x for x in listed if discover.norm(x["name"]) not in names][:limit]
    with ThreadPoolExecutor(max_workers=4) as pool:
        got = list(pool.map(discover.website, todo))
    out = [{"name": g["name"], "shop": g["shop"], "city": g.get("place") or "", "country": "GB"} for g in got if g.get("shop") and discover.host(g["shop"]) not in have]
    print(f"UK directory: {len(listed)} roasters, {len(todo)} not on the list looked up, {len(out)} with a website")
    return out


WIKIDATA = "https://query.wikidata.org/sparql"
WD_QUERY = """SELECT ?item ?itemLabel ?site ?cc ?cityLabel WHERE {
  SERVICE wikibase:mwapi { bd:serviceParam wikibase:endpoint "www.wikidata.org"; wikibase:api "Search";
    mwapi:srsearch "\\"coffee roaster\\" OR \\"coffee roastery\\" OR \\"coffee roasting company\\" OR \\"specialty coffee\\" OR \\"speciality coffee\\" haswbstatement:P856"; mwapi:srlimit "max".
    ?item wikibase:apiOutputItem mwapi:title. }
  ?item wdt:P856 ?site.
  OPTIONAL { ?item wdt:P17 ?c. ?c wdt:P297 ?cc. }
  OPTIONAL { ?item wdt:P159 ?city. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""


def from_wikidata(have):
    """Third source: Wikidata, the open database behind Wikipedia: items described as a coffee roaster with an official website."""
    try:
        req = urllib.request.Request(WIKIDATA + "?" + urllib.parse.urlencode({"query": WD_QUERY, "format": "json"}),
                                     headers={"User-Agent": scan.UA, "Accept": "application/sparql-results+json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            rows = json.loads(r.read())["results"]["bindings"]
    except Exception as e:  # noqa: BLE001
        print(f"Wikidata not reachable ({type(e).__name__})"); return []
    out, seen = [], set()
    for b in rows:
        site, name = b.get("site", {}).get("value", ""), b.get("itemLabel", {}).get("value", "")
        if not site.startswith("http") or not name or re.fullmatch(r"Q\d+", name):
            continue
        u = urllib.parse.urlparse(site); shop = f"{u.scheme}://{u.netloc}"; h = discover.host(shop)
        if not h or h in seen or h in have:
            continue
        seen.add(h)
        out.append({"name": name, "shop": shop, "city": b.get("cityLabel", {}).get("value", "") if not re.fullmatch(r"Q\d+", b.get("cityLabel", {}).get("value", "")) else "",
                    "country": (b.get("cc", {}).get("value") or "").upper() or country({}, shop)})
    print(f"Wikidata: {len(rows)} items, {len(out)} with a website not on the list")
    return out


def parse_map(els):
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
    except Exception as e:  # noqa: BLE001
        print(f"map not reachable this time ({type(e).__name__}) and nothing saved: the other sources only"); cands = []
    # three sources, so a night the map is down still brings roasters: the map, the UK directory, Wikidata
    cands += from_uk_directory(have, names) + from_wikidata(have)
    seen_h, uniq = set(), []
    for c in cands:   # the same shop from two sources is tried once
        h = discover.host(c["shop"])
        if h not in seen_h:
            seen_h.add(h); uniq.append(c)
    cands = uniq
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

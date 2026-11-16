"""Find UK roasters the list doesn't have yet, and check whether the scanner can read their shops.

Run by hand from the "Find new roasters" workflow. Reads the public UK roaster directory at roasterlist.pages.dev
(name, place, website), leaves out every roaster whose website or name is already in data/roasters.json, then tries
each new shop exactly as the daily scan would (Shopify, WooCommerce, Squarespace, sitemap), with the scan's own
honest user agent. Nothing is added to the list: the result goes to data/candidates.json for a person to review.

    python3 scripts/discover.py            # the whole directory
    python3 scripts/discover.py --urls https://a.example,https://b.example   # just these shops (the listing page's requests)
"""
import json, re, sys, html
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
import scan  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIR = "https://roasterlist.pages.dev"
OUT = ROOT / "data" / "candidates.json"
NATIONS = {"scotland": "Scotland", "wales": "Wales", "northern ireland": "Northern Ireland"}
SCOT = r"edinburgh|glasgow|aberdeen|dundee|inverness|perth|stirling|fife|highland|argyll|orkney|shetland|lothian|ayr|skye|mull|speyside|cairngorm|borders|galashiels|kinross|moray|angus|lanark|dumfries"
WALES = r"cardiff|swansea|newport|wrexham|carmarthen|ceredigion|gwynedd|anglesey|pembroke|powys|conwy|denbigh|monmouth|bridgend|llandeilo|aberystwyth|wales"
NI = r"belfast|derry|antrim|down|armagh|tyrone|fermanagh|lisburn|newry|comber|northern ireland"


def host(u):
    h = urlparse(u if "//" in u else "https://" + u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def norm(n):
    n = re.sub(r"&", " and ", (n or "").lower())
    n = re.sub(r"\b(coffee|roasters?|roastery|roasting|co|company|ltd|limited|the|and|speciality|specialty|uk|espresso|tea)\b", " ", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def nation(place):
    p = (place or "").lower()
    for k, v in NATIONS.items():
        if k in p:
            return v
    if re.search(SCOT, p): return "Scotland"
    if re.search(NI, p): return "Northern Ireland"
    if re.search(WALES, p): return "Wales"
    return "England"


def directory():
    """(name, place, roaster page) for every roaster in the directory's A to Z."""
    page = scan.get_text(f"{DIR}/uk-coffee-roasters/", tries=2, limit=2_000_000)
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="(?:https://roasterlist\.pages\.dev)?(/roaster/[^"#?]+/?)"[^>]*>(.*?)</a>', page, re.S | re.I):
        link, inner = m.group(1), m.group(2)
        name = html.unescape(re.sub(r"<[^>]+>|\s+", " ", inner)).strip()
        if not name or link in seen or len(name) > 60:
            continue
        seen.add(link)
        out.append({"name": name, "page": DIR + link})
    return out


def website(entry):
    """The roaster's own site and place, from its directory page."""
    try:
        t = scan.get_text(entry["page"], tries=1, limit=600_000)
    except Exception as e:  # noqa: BLE001
        entry["error"] = f"directory page: {e}"; return entry
    for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', t, re.S | re.I):
        href, label = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        if "roasterlist" in href or "pages.dev" in href:
            continue
        if re.search(r"visit|website|shop", label, re.I):
            entry["shop"] = href.rstrip("/"); break
    place = re.search(r'<(?:p|span|div)[^>]*class="[^"]*(?:location|place|region|meta)[^"]*"[^>]*>(.*?)</', t, re.S | re.I)
    if place:
        entry["place"] = html.unescape(re.sub(r"<[^>]+>|\s+", " ", place.group(1))).strip()[:60]
    return entry


def probe(c):
    """Read the shop as the daily scan would; count what would make the list."""
    r = {"name": c["name"], "shop": c["shop"], "_old": {}}
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
    c.update({"platform": kind, "coffees": len(recs), "sample": [x["name"] for x in recs[:4]], "error": None if kind else (err or "")[:300]})
    return c


def main():
    roasters = json.loads((ROOT / "data" / "roasters.json").read_text())
    have_hosts = {host(r["shop"]) for r in roasters} | {host(r["feed"]) for r in roasters if r.get("feed")}
    have_names = {norm(r["name"]) for r in roasters}
    args = sys.argv[1:]
    if "--urls" in args:
        cands = [{"name": host(u), "shop": u.rstrip("/"), "page": None} for u in args[args.index("--urls") + 1].split(",") if u.strip()]
    else:
        listed = directory()
        print(f"directory index: {len(listed)} roaster links; first: {listed[:3]}")
        if not listed:
            print(scan.get_text(f"{DIR}/uk-coffee-roasters/", tries=1)[:3000])
        with ThreadPoolExecutor(max_workers=8) as pool:
            cands = list(pool.map(website, listed))
        print("first pages read:", [{k: c.get(k) for k in ("name", "shop", "place", "error")} for c in cands[:3]])
        if cands and not any(c.get("shop") for c in cands[:20]):
            print(scan.get_text(cands[0]["page"], tries=1)[:4000])
    new, known = [], 0
    for c in cands:
        if not c.get("shop"):
            continue
        if host(c["shop"]) in have_hosts or norm(c["name"]) in have_names:
            known += 1; continue
        c["nation"] = nation(c.get("place", ""))
        new.append(c)
    print(f"directory: {len(cands)} roasters, {sum(1 for c in cands if c.get('shop'))} with a website, {known} already on the list, {len(new)} new")
    with ThreadPoolExecutor(max_workers=12) as pool:
        new = list(pool.map(probe, new))
    new.sort(key=lambda c: (-c["coffees"], c["name"].lower()))
    OUT.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n")
    ok = [c for c in new if c["coffees"]]
    print(f"readable with coffees: {len(ok)}; readable, no coffees: {sum(1 for c in new if c['platform'] and not c['coffees'])}; unreadable: {sum(1 for c in new if not c['platform'])}")
    for c in new:
        print(f"{c['name'][:34]:<34} {c['shop'][:44]:<44} {(c['platform'] or 'FAILED'):<12} {c['coffees']:>3}  {'; '.join(c['sample'])[:90]}")


if __name__ == "__main__":
    main()

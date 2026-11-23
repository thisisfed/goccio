"""Find UK roasters the list doesn't have yet, and check whether the scanner can read their shops.

Run by hand from the "Find new roasters" workflow. Reads the public UK roaster directory at roasterlist.pages.dev
(name, place, website), leaves out every roaster whose website or name is already in data/roasters.json, then tries
each new shop exactly as the daily scan would (Shopify, WooCommerce, Squarespace, sitemap), with the scan's own
honest user agent. Nothing is added to the list: the result goes to data/candidates.json for a person to review.

    python3 scripts/discover.py            # the whole directory
    python3 scripts/discover.py --urls https://a.example,https://b.example   # just these shops (the listing page's requests)
"""
import json, os, re, sys, html
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
    """(name, roaster page) for every roaster in the directory: its JSON-LD list if it has one, else every link to a roaster page."""
    page = scan.get_text(f"{DIR}/uk-coffee-roasters/", tries=2, limit=3_000_000)
    out, seen = [], set()
    def add(name, link):
        link = re.sub(r"^https?://[^/]+", "", link)
        if not re.match(r"^/roaster/[^/]+/?$", link) or link in seen:
            return
        name = html.unescape(re.sub(r"<[^>]+>|\s+", " ", name or "")).strip()
        if not name or len(name) > 60:
            return
        seen.add(link); out.append({"name": name, "page": DIR + link.rstrip("/") + "/"})
    for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(blob)
        except Exception:  # noqa: BLE001
            continue
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                u = x.get("url") or (x.get("item") or {}).get("@id") if isinstance(x.get("item"), dict) else x.get("url")
                if isinstance(u, str) and "/roaster/" in u:
                    add(x.get("name") or (x.get("item") or {}).get("name"), u)
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    for m in re.finditer(r'<a[^>]+href="([^"]*/roaster/[^"#?]+)"[^>]*>(.*?)</a>', page, re.S | re.I):
        add(m.group(2), m.group(1))
    for slug in re.findall(r'/roaster/([a-z0-9-]+)/', page):   # every other mention: the name comes from the roaster's own page
        add(slug.replace("-", " ").title(), f"/roaster/{slug}/")
    print(f"index: {page.count('/roaster/')} mentions of a roaster page")
    if not out:
        for m in list(re.finditer(r"/roaster/", page))[:5]:
            print("CONTEXT:", page[max(0, m.start() - 300): m.end() + 200].replace("\n", " "))
    return out


def website(entry):
    """The roaster's name, place and own site, from its directory page (title, structured data, the Visit link)."""
    try:
        t = scan.get_text(entry["page"], tries=1, limit=800_000)
    except Exception as e:  # noqa: BLE001
        entry["error"] = f"directory page: {e}"; return entry
    title = re.search(r"<title>(.*?)</title>", t, re.S)
    if title:   # "Cargo Coffee | County Down Coffee Roaster | Roasterlist"
        bits = [html.unescape(b).strip() for b in title.group(1).split("|")]
        if bits and bits[0]:
            entry["name"] = bits[0]
        if len(bits) > 2:
            entry["place"] = re.sub(r"\s*Coffee Roaster.*$", "", bits[1]).strip()
    for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', t, re.S):
        try:
            data = json.loads(blob)
        except Exception:  # noqa: BLE001
            continue
        stack = [data]
        while stack and not entry.get("shop"):
            x = stack.pop()
            if isinstance(x, dict):
                for k in ("url", "sameAs"):
                    vals = x.get(k) if isinstance(x.get(k), list) else [x.get(k)]
                    for v in vals:
                        if isinstance(v, str) and v.startswith("http") and "roasterlist" not in v and not re.search(r"instagram|facebook|twitter|x\.com|tiktok|linkedin|youtube|google", v):
                            entry["shop"] = v.rstrip("/"); break
                    if entry.get("shop"):
                        break
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    if not entry.get("shop"):
        for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', t, re.S | re.I):
            href, label = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
            if "roasterlist" in href or "pages.dev" in href:
                continue
            if re.search(r"visit|website", label, re.I):
                entry["shop"] = href.rstrip("/"); break
    if entry.get("shop"):
        u = urlparse(entry["shop"]); entry["shop"] = f"{u.scheme}://{u.netloc}"   # the shop's home: the scan finds its products from there
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
    c.update({"platform": kind, "coffees": len(recs), "sample": [x["name"] for x in recs[:4]], "error": None if kind else (err or "")[:300],
              "gate": scan.specialty_gate(recs, c["name"]) if recs else None})   # specialty only: why it is not added, or None
    return c


def gh(method, path, body=None):
    """GitHub's REST API on the private requests repo (REQUESTS_REPO), where the forms file their requests as issues."""
    import urllib.request
    req = urllib.request.Request(f"https://api.github.com/repos/{os.environ.get('REQUESTS_REPO') or os.environ['GITHUB_REPOSITORY']}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "goccio-listings", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"null")


REMOVED = ROOT / "data" / "removed.json"   # shops whose roasters asked to be taken off: never added back by the directory


def removed():
    try:
        return set(json.loads(REMOVED.read_text()))
    except (OSError, ValueError):
        return set()


def blocked():
    """Hosts never added: roasters who asked to be removed, and shops banned for not being specialty (data/banned.json)."""
    return removed() | set(scan.banned())


def save_roasters(roasters):
    (ROOT / "data" / "roasters.json").write_text("[\n" + ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in roasters) + "\n]\n")   # one roaster a line, as the file is kept


def same_owner(email, shop):
    """True when the email is at the shop's own domain (shop.x.co.uk and x.co.uk both match hello@x.co.uk)."""
    d = (email or "").rsplit("@", 1)[-1].lower()
    h = host(shop)
    return bool(d) and (h == d or h.endswith("." + d) or d.endswith("." + h))


def removals():
    """Requests from the "Ask to be removed" form (issues labelled "removal"). When the email is at the shop's own
    domain the shop comes off data/roasters.json and goes on data/removed.json at once; otherwise the issue stays
    open for a person to check, so nobody can take a rival off the site."""
    roasters = scan.load_roasters()
    gone, out = removed(), []
    for iss in gh("GET", "/issues?labels=removal&state=open&per_page=50"):
        m = re.search(r"```json\s*(\{.*?\})\s*```", iss.get("body") or "", re.S)
        if not m:
            continue
        req = json.loads(m.group(1))
        h = host(req["shop"])
        if not same_owner(req.get("email"), req["shop"]):
            gh("POST", f"/issues/{iss['number']}/comments", {"body": f"Not removed yet: {req.get('email')} isn't at {h}. Check it's the roaster, then add {h} to data/removed.json and take it off data/roasters.json."})
            continue
        before = len(roasters)
        roasters = [r for r in roasters if host(r["shop"]) != h and host(r.get("feed") or "") != h]
        gone.add(h); out.append(h)
        gh("POST", f"/issues/{iss['number']}/comments", {"body": f"Removed {h} ({before - len(roasters)} on the list). Its coffees go at the next daily scan. Reply to {req.get('email')} to say so."})
        gh("PATCH", f"/issues/{iss['number']}", {"state": "closed"})
    if out:
        save_roasters(roasters)
        REMOVED.write_text(json.dumps(sorted(gone), indent=1) + "\n")
    print(f"removal requests: {len(out)} removed: {', '.join(out)}")


def listings():
    """Requests from the Get your roastery listed page (issues labelled "listing"): check each shop with the real scanner,
    add the ones with coffees to data/roasters.json, and answer the issue. A request it can't read stays open for a person."""
    roasters = scan.load_roasters()
    have = {host(r["shop"]) for r in roasters}
    added = []
    for iss in gh("GET", "/issues?labels=listing&state=open&per_page=50"):
        m = re.search(r"```json\s*(\{.*?\})\s*```", iss.get("body") or "", re.S)
        if not m:
            continue
        req = json.loads(m.group(1))
        shop = req["shop"].rstrip("/")
        if host(shop) in have:
            gh("POST", f"/issues/{iss['number']}/comments", {"body": "Already on the list."}); gh("PATCH", f"/issues/{iss['number']}", {"state": "closed"}); continue
        if not same_owner(req.get("email"), shop):   # permission counts only from the roastery itself
            if not any("isn't at" in (x.get("body") or "") for x in gh("GET", f"/issues/{iss['number']}/comments")):
                gh("POST", f"/issues/{iss['number']}/comments", {"body": f"Not added yet: {req.get('email')} isn't at {host(shop)}. Check it's the roaster, then add it to data/roasters.json by hand."})
            continue
        c = probe({"name": req["name"], "shop": shop})
        if host(shop) in scan.banned() or (c["coffees"] and c.get("gate")):   # asked to be listed, but not specialty: a person decides
            if not any("specialty" in (x.get("body") or "") for x in gh("GET", f"/issues/{iss['number']}/comments")):
                gh("POST", f"/issues/{iss['number']}/comments", {"body": f"Not added: Goccio lists specialty roasters only, and this shop {c.get('gate') or 'is on data/banned.json'}. If that is wrong, add it to data/roasters.json by hand."})
            continue
        if c["coffees"]:
            ie = host(shop).endswith(".ie")
            r = {"name": req["name"], "shop": shop, "city": req.get("town") or "", "region": "UK", "country": "IE" if ie else "GB"}
            if not ie:
                r["nation"] = nation(req.get("town") or "")
            roasters.append(r); have.add(host(shop)); added.append(r["name"])
            gh("POST", f"/issues/{iss['number']}/comments", {"body": f"Added: the scanner reads {c['coffees']} coffees ({c['platform']}), e.g. {', '.join(c['sample'][:3])}. They appear after the next daily scan.{'' if req.get('town') else ' Add its town to data/roasters.json (city).'} Reply to {req.get('email')} to say so."})
            gh("PATCH", f"/issues/{iss['number']}", {"state": "closed"})
        else:
            gh("POST", f"/issues/{iss['number']}/comments", {"body": f"Not added: the scanner {'reads the shop (' + c['platform'] + ') but finds no coffee beans in it' if c['platform'] else 'cannot read the shop'}. {(c.get('error') or '')[:300]}"})
    if added:
        save_roasters(roasters)
    if added and REMOVED.exists():   # a roaster who asked to come back is no longer on the removed list
        REMOVED.write_text(json.dumps(sorted(removed() - {host(r["shop"]) for r in roasters}), indent=1) + "\n")
    print(f"listing requests: {len(added)} added: {', '.join(added)}")


EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
JUNK = re.compile(r"sentry|wixpress|example\.|domain\.|email\.com|yourname|@2x|\.(?:png|jpe?g|gif|webp|svg)$|shopify|squarespace|godaddy|wordpress|u003e", re.I)


def contacts(shop):
    """Public contact addresses a shop publishes on its home or contact page (for asking permission to list it)."""
    found, pages = [], [shop] + [shop + p for p in ("/contact", "/contact-us", "/pages/contact", "/pages/contact-us", "/about")]
    for u in pages:
        try:
            t = scan.get_text(u, tries=1, limit=800_000)
        except Exception:  # noqa: BLE001
            continue
        for e in EMAIL.findall(html.unescape(t)):
            e = e.strip(".").lower()
            if not JUNK.search(e) and e not in found:
                found.append(e)
        if found:
            break
    return {"shop": shop, "emails": found[:3]}


def main():
    if "--listings" in sys.argv[1:]:
        removals()
        return listings()
    if "--contacts" in sys.argv[1:]:
        shops = [u.strip() for u in sys.argv[sys.argv.index("--contacts") + 1].split(",") if u.strip()]
        with ThreadPoolExecutor(max_workers=12) as pool:
            for c in pool.map(contacts, shops):
                print("CONTACT " + json.dumps(c))
        return
    roasters = scan.load_roasters()
    have_hosts = {host(r["shop"]) for r in roasters} | {host(r["feed"]) for r in roasters if r.get("feed")} | blocked()
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
    for c in new:
        if c["coffees"] and c.get("gate"):
            print(f"NOT SPECIALTY {c['name']} ({c['shop']}): {c['gate']}")
    new = [c for c in new if not (c["coffees"] and c.get("gate"))]
    ok = [c for c in new if c["coffees"]]
    print(f"readable with coffees: {len(ok)}; readable, no coffees: {sum(1 for c in new if c['platform'] and not c['coffees'])}; unreadable: {sum(1 for c in new if not c['platform'])}")
    for c in new:   # the whole record, for whoever reviews the run (artifacts aren't always reachable)
        print("CAND " + json.dumps({k: c.get(k) for k in ("name", "shop", "place", "nation", "platform", "coffees", "sample")}, ensure_ascii=False))
    for c in new:
        print(f"{c['name'][:34]:<34} {c['shop'][:44]:<44} {(c['platform'] or 'FAILED'):<12} {c['coffees']:>3}  {'; '.join(c['sample'])[:90]}")


if __name__ == "__main__":
    main()

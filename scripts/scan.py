#!/usr/bin/env python3
"""Weekly scan of UK roasters' public shop feeds for single-origin filter coffees.

Free and key-less: most UK specialty roasters run on Shopify, which publishes every
product at /products.json. WooCommerce shops expose /wp-json/wc/store/v1/products.
Anything else is skipped and reported in data/releases.json -> roasters[].

Usage: python3 scripts/scan.py            (writes data/releases.json)
       python3 scripts/scan.py --fixture f.json --shop https://x  (offline parse test)
"""
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROASTERS = ROOT / "data" / "roasters.json"
OUT = ROOT / "data" / "releases.json"
UA = "V60BrewCard/1.0 (+https://v60.thisisfed.xyz; weekly filter-coffee list)"
NEW_DAYS = 21
MAX_ITEMS = 150

COUNTRIES = ["Ethiopia", "Kenya", "Colombia", "Panama", "Costa Rica", "Guatemala", "El Salvador",
             "Honduras", "Nicaragua", "Peru", "Bolivia", "Ecuador", "Brazil", "Burundi", "Rwanda",
             "Uganda", "Tanzania", "Yemen", "Indonesia", "Sumatra", "Papua New Guinea", "Mexico",
             "China", "Taiwan", "India", "Myanmar", "Thailand", "Vietnam", "DR Congo", "Congo", "Malawi",
             "Zambia", "Jamaica", "Hawaii", "Dominican Republic", "Timor-Leste", "East Timor", "Laos"]
VARIETIES = ["Gesha", "Geisha", "Sidra", "Pink Bourbon", "Wush Wush", "Eugenioides", "Laurina",
             "Sudan Rume", "SL28", "SL34", "Ruiru 11", "Batian", "Red Bourbon", "Yellow Bourbon",
             "Bourbon", "Typica", "Caturra", "Catuai", "Castillo", "Pacamara", "Maragogype",
             "74110", "74112", "74158", "Heirloom", "Landrace", "Java", "Mokka", "Chiroso",
             "Tabi", "Villa Sarchi", "Parainema", "Marsellesa", "Catimor"]
EXCLUDE = re.compile(r"subscri|gift|voucher|capsule|\bpods?\b|nespresso|coffee bags?|drip bags?|"
                     r"steep|equipment|grinder|\bmug\b|kettle|dripper|filter papers?|papers\b|\bcups?\b(?! of excellence)|"
                     r"sampler|tasting pack|taster|bundle|merch|t-?shirt|hoodie|tote|cap\b|"
                     r"cold brew|concentrate|instant|\btea\b|chocolate bar|chocolate\b|cascara|"
                     r"workshop|course|class|training|advent|box\b|\bkit\b|scale\b|aeropress\b(?! recipe)|"
                     r"\bblend\b|espresso blend|house blend", re.I)
FILTERY = re.compile(r"\bfilter\b|\bomni\b|pour[- ]?over|\bv60\b|chemex|batch brew|filter roast", re.I)
ESPRESSO = re.compile(r"\bespresso\b", re.I)
COFFEE_HINT = re.compile(r"single origin|single-origin|altitude|masl|variet|process|tasting notes|"
                         r"flavour notes|flavor notes|producer|washing station|farm|finca|estate", re.I)
NOTES_RE = re.compile(r"(?:tasting notes|flavour notes|flavor notes|flavour profile|in the cup|"
                      r"tastes like|we taste|notes)\s*[:\-–]\s*([^\n.]{3,120})", re.I)
DARK = re.compile(r"dark roast|medium[- ]dark|french roast|italian roast", re.I)


def strip_html(s):
    s = re.sub(r"<(br|/p|/li|/h\d|/div)[^>]*>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def get_json(url, tries=2):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                ctype = r.headers.get("Content-Type", "")
                body = r.read()
                if "json" not in ctype and not body.lstrip().startswith((b"{", b"[")):
                    raise ValueError("not json")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise
            if i == tries - 1:
                raise
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(2)


def fetch_shopify(shop):
    items = []
    for page in range(1, 5):
        data = get_json(f"{shop}/products.json?limit=250&page={page}")
        prods = data.get("products", [])
        if not prods:
            break
        for p in prods:
            tags = p.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]
            variants = p.get("variants") or []
            prices = [float(v["price"]) for v in variants if v.get("price") not in (None, "")]
            items.append({
                "title": p.get("title", ""),
                "type": p.get("product_type", ""),
                "tags": tags,
                "body": strip_html(p.get("body_html", "")),
                "variants": " / ".join(v.get("title", "") for v in variants),
                "available": any(v.get("available", True) for v in variants) if variants else False,
                "price": min(prices) if prices else None,
                "url": f"{shop}/products/{p.get('handle', '')}",
                "published": (p.get("published_at") or p.get("created_at") or "")[:10],
            })
        if len(prods) < 250:
            break
        time.sleep(1)
    return items


def fetch_woo(shop):
    items = []
    for page in range(1, 4):
        data = get_json(f"{shop}/wp-json/wc/store/v1/products?per_page=100&page={page}")
        if not isinstance(data, list) or not data:
            break
        for p in data:
            pr = p.get("prices") or {}
            minor = int(pr.get("currency_minor_unit", 2) or 2)
            raw = pr.get("price")
            price = int(raw) / (10 ** minor) if raw not in (None, "") else None
            cats = [c.get("name", "") for c in p.get("categories", [])]
            tags = [t.get("name", "") for t in p.get("tags", [])]
            items.append({
                "title": html.unescape(p.get("name", "")),
                "type": " ".join(cats),
                "tags": tags + cats,
                "body": strip_html((p.get("short_description") or "") + "\n" + (p.get("description") or "")),
                "variants": "",
                "available": bool(p.get("is_in_stock", True)),
                "price": price,
                "url": p.get("permalink", ""),
                "published": "",
            })
        if len(data) < 100:
            break
        time.sleep(1)
    return items


def first(pattern_list, text):
    low = text.lower()
    best = None
    for w in pattern_list:
        i = low.find(w.lower())
        if i >= 0 and (best is None or i < best[0]):
            best = (i, w)
    return best[1] if best else None


def find_process(text):
    t = text.lower()
    if "decaf" in t:
        return "Decaf"
    for pat, name in [(r"anaerobic natural", "Anaerobic natural"), (r"anaerobic washed", "Anaerobic washed"),
                      (r"anaerobic honey", "Anaerobic honey"), (r"carbonic maceration", "Carbonic maceration"),
                      (r"co-?ferment", "Co-fermented"), (r"thermal shock", "Thermal shock"),
                      (r"anaerobic", "Anaerobic"), (r"double fermentation|double ferment", "Double fermented"),
                      (r"\bnatural\b|dry[- ]process", "Natural"), (r"\bhoney\b|pulped natural", "Honey"),
                      (r"\bwashed\b|wet[- ]process", "Washed")]:
        if re.search(pat, t):
            return name
    return None


def find_notes(item):
    text = item["body"]
    m = NOTES_RE.search(text)
    raw = m.group(1) if m else None
    if not raw:
        # "Name - Country - Note, Note, Note" style titles
        parts = re.split(r"\s[-–|]\s", item["title"])
        if len(parts) >= 3 and "," in parts[-1]:
            raw = parts[-1]
    if not raw:
        for t in item["tags"]:
            mm = re.match(r"(?:notes?|flavou?r)[:_ ](.+)", t, re.I)
            if mm:
                raw = (raw + ", " if raw else "") + mm.group(1)
    if not raw:
        return []
    bits = re.split(r",|&|\band\b|/|·|\|", raw)
    out = []
    for b in bits:
        b = b.strip(" .;:-–").strip()
        if 2 <= len(b) <= 28 and not re.search(r"\d{3,}|masl|process|altitude", b, re.I) and not first(COUNTRIES, b):
            out.append(b[:1].upper() + b[1:])
    return out[:4]


def clean_name(title, roaster, origin):
    name = re.sub(r"^(filter|espresso|omni)\s*[-–:|/]\s*", "", title, flags=re.I)
    name = re.sub(r"\s*[-–|]\s*(filter|omni)( roast)?\s*$", "", name, flags=re.I)
    parts = re.split(r"\s[-–|]\s", name)
    if len(parts) >= 3 or (len(parts) == 2 and first(COUNTRIES, parts[1])):
        name = parts[0]
    if origin:
        name = re.sub(r"[,\s\-–|]+" + re.escape(origin) + r"\s*$", "", name, flags=re.I)
    name = re.sub(r"\(?\b\d{2,4}\s?g\b\)?", "", name, flags=re.I).strip(" -–|,")
    return name or title


def classify(item, roaster):
    title = item["title"]
    blob = " ".join([title, item["type"], " ".join(item["tags"]), item["variants"]])
    full = blob + "\n" + item["body"]
    if not item["available"]:
        return None
    if EXCLUDE.search(title) or EXCLUDE.search(item["type"]):
        return None
    if DARK.search(full):
        return None
    origin = first(COUNTRIES, title) or first(COUNTRIES, blob) or first(COUNTRIES, item["body"])
    is_coffee = bool(origin) and (bool(COFFEE_HINT.search(full)) or re.search(r"coffee|bean", blob, re.I))
    if not is_coffee:
        return None
    filtery = bool(FILTERY.search(blob)) or bool(re.search(r"roasted for filter|filter roast|omni roast", item["body"], re.I))
    espresso_only = bool(ESPRESSO.search(title + " " + item["type"])) and not filtery
    if espresso_only:
        return None
    if not filtery and ESPRESSO.search(" ".join(item["tags"])) and not FILTERY.search(item["body"]):
        return None
    process = find_process(title + " " + " ".join(item["tags"])) or find_process(item["body"])
    variety = first(VARIETIES, title + " " + " ".join(item["tags"])) or first(VARIETIES, item["body"])
    rec = {
        "roaster": roaster["name"],
        "name": clean_name(title, roaster["name"], origin),
        "origin": origin,
        "process": process,
        "variety": variety,
        "notes": find_notes(item),
        "price": f"£{item['price']:.2f}" if item["price"] else None,
        "url": item["url"],
        "published": item["published"] or None,
        "roast": "filter" if filtery else "omni / unlabelled",
    }
    return {k: v for k, v in rec.items() if v not in (None, "", [])}


def scan_roaster(r):
    shop = r["shop"].rstrip("/")
    errors = []
    for kind, fn in (("shopify", fetch_shopify), ("woocommerce", fetch_woo)):
        try:
            items = fn(shop)
            if items:
                return kind, items, None
        except Exception as e:  # noqa: BLE001
            errors.append(f"{kind}: {type(e).__name__}: {str(e)[:80]}")
    return None, [], "; ".join(errors) or "no products found"


def main():
    today = datetime.now(timezone.utc).date().isoformat()
    args = sys.argv[1:]
    if "--fixture" in args:
        data = json.loads(Path(args[args.index("--fixture") + 1]).read_text())
        shop = args[args.index("--shop") + 1]
        r = {"name": "Fixture Roaster", "shop": shop}
        items = []
        for p in data["products"]:
            variants = p.get("variants") or []
            items.append({"title": p["title"], "type": p.get("product_type", ""), "tags": p.get("tags", []),
                          "body": strip_html(p.get("body_html", "")), "variants": " / ".join(v.get("title", "") for v in variants),
                          "available": any(v.get("available", True) for v in variants),
                          "price": min(float(v["price"]) for v in variants), "url": f"{shop}/products/{p['handle']}",
                          "published": p.get("published_at", "")[:10]})
        for it in items:
            print(json.dumps(classify(it, r), ensure_ascii=False))
        return

    roasters = json.loads(ROASTERS.read_text())
    old = {}
    if OUT.exists():
        try:
            for x in json.loads(OUT.read_text()).get("releases", []):
                old[x["url"]] = x
        except Exception:  # noqa: BLE001
            pass

    found, status = [], []
    scanned_ok = set()
    for r in roasters:
        kind, items, err = scan_roaster(r)
        kept = 0
        if kind:
            scanned_ok.add(r["name"])
            for it in items:
                rec = classify(it, r)
                if rec:
                    rec["found"] = old.get(rec["url"], {}).get("found", today)
                    found.append(rec)
                    kept += 1
        status.append({"name": r["name"], "shop": r["shop"], "platform": kind, "coffees": kept, "error": err})
        print(f"{r['name']:<26} {kind or 'FAILED':<12} {kept:>3} {err or ''}")
        time.sleep(1.5)

    # keep last week's coffees from roasters that failed this time (temporary outages)
    urls = {x["url"] for x in found}
    for u, x in old.items():
        if x["roaster"] not in scanned_ok and u not in urls:
            found.append(x)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=NEW_DAYS)).date().isoformat()
    for x in found:
        x["new"] = (x.get("published") or x.get("found", "")) >= cutoff
    found.sort(key=lambda x: (x.get("published") or x.get("found") or ""), reverse=True)
    found = found[:MAX_ITEMS]

    OUT.write_text(json.dumps({"updated": today, "new_window_days": NEW_DAYS, "roasters": status,
                               "releases": found}, ensure_ascii=False, indent=1) + "\n")
    print(f"\n{len(found)} coffees from {len(scanned_ok)}/{len(roasters)} roasters -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

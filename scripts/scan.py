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
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROASTERS = ROOT / "data" / "roasters.json"
OUT = ROOT / "data" / "releases.json"
UA = "V60BrewCard/1.0 (+https://v60.thisisfed.xyz; weekly filter-coffee list)"
NEW_DAYS = 21
MAX_ITEMS = 1200
PER_ROASTER = 8

COUNTRIES = ["Ethiopia", "Kenya", "Colombia", "Panama", "Costa Rica", "Guatemala", "El Salvador",
             "Honduras", "Nicaragua", "Peru", "Bolivia", "Ecuador", "Brazil", "Burundi", "Rwanda",
             "Uganda", "Tanzania", "Yemen", "Indonesia", "Sumatra", "Papua New Guinea", "Mexico",
             "China", "Taiwan", "India", "Myanmar", "Thailand", "Vietnam", "DR Congo", "Congo", "Malawi",
             "Zambia", "Jamaica", "Hawaii", "Dominican Republic", "Timor-Leste", "East Timor", "Laos"]
# origin names as roasters abroad write them -> English
COUNTRY_ALIASES = {
    "Etiopia": "Ethiopia", "Äthiopien": "Ethiopia", "Éthiopie": "Ethiopia", "Ethiopie": "Ethiopia", "Etiopien": "Ethiopia", "Ethiopië": "Ethiopia",
    "Colombie": "Colombia", "Kolumbien": "Colombia", "Kolumbia": "Colombia", "Colombië": "Colombia",
    "Kenia": "Kenya", "Brasile": "Brazil", "Brasilien": "Brazil", "Brésil": "Brazil", "Brasil": "Brazil", "Brazylia": "Brazil",
    "Perù": "Peru", "Pérou": "Peru", "Perú": "Peru", "Panamá": "Panama", "Ruanda": "Rwanda", "Messico": "Mexico", "Mexiko": "Mexico",
    "Mexique": "Mexico", "México": "Mexico", "Indonesien": "Indonesia", "Indonésie": "Indonesia", "Équateur": "Ecuador",
    "Ouganda": "Uganda", "Tansania": "Tanzania", "Tanzanie": "Tanzania", "Jemen": "Yemen", "Yémen": "Yemen", "Salvador": "El Salvador",
    "Costa Rica": "Costa Rica", "Burundi": "Burundi", "Guatemala": "Guatemala", "Honduras": "Honduras", "Nicaragua": "Nicaragua",
    "Bolivie": "Bolivia", "Bolivien": "Bolivia", "Cina": "China", "Chine": "China", "Inde": "India", "Indien": "India",
}
SYMBOL = {"GBP": "£", "EUR": "€", "USD": "$", "CAD": "CA$", "AUD": "A$", "NZD": "NZ$", "JPY": "¥", "DKK": " kr", "SEK": " kr", "NOK": " kr",
          "PLN": " zł", "CZK": " Kč", "CHF": "CHF "}
COUNTRY_CCY = {"GB": "GBP", "US": "USD", "CA": "CAD", "AU": "AUD", "NZ": "NZD", "JP": "JPY", "DK": "DKK", "SE": "SEK", "NO": "NOK",
               "PL": "PLN", "CZ": "CZK", "CH": "CHF"}

VARIETIES = ["Gesha", "Geisha", "Sidra", "Pink Bourbon", "Wush Wush", "Eugenioides", "Laurina",
             "Sudan Rume", "SL28", "SL34", "Ruiru 11", "Batian", "Red Bourbon", "Yellow Bourbon",
             "Bourbon", "Typica", "Caturra", "Catuai", "Castillo", "Pacamara", "Maragogype",
             "74110", "74112", "74158", "Heirloom", "Landrace", "Java", "Mokka", "Chiroso",
             "Tabi", "Villa Sarchi", "Parainema", "Marsellesa", "Catimor"]
EXCLUDE = re.compile(r"subscri|abonnement|abbonamento|\babo\b|suscripci|prenumeration|geschenk|regalo|cadeau|gutschein|"
                     r"\btasse\b|tazza|latte art|\bpen\b|\btool\b|accessor|machine|maker|moccamaster|ticket|party|event|festival|origami|glass|server|carafe|porcelain|ceramic|brewer|filter holder|gift|voucher|capsule|\bpods?\b|nespresso|coffee bags?|drip bags?|"
                     r"steep|equipment|grinder|\bmug\b|kettle|dripper|filter papers?|papers\b|\bcups?\b(?! of excellence)|"
                     r"sampler|tasting pack|taster|bundle|merch|t-?shirt|hoodie|tote|cap\b|"
                     r"cold brew|concentrate|instant|\btea\b|chocolate bar|chocolate\b|cascara|"
                     r"workshop|course|class|training|advent|box\b|\bkit\b|scale\b|aeropress\b(?! recipe)|"
                     r"\bblend\b|espresso blend|house blend|\bgreen\b|unroasted|\bduo\b|\btrio\b|\bpack\b|\bset\b|selection|collection|wholesale|\b1\s?kg\b|\b2\s?kg\b", re.I)
FILTERY = re.compile(r"\bfilter\b|\bomni\b|pour[- ]?over|\bv60\b|chemex|batch brew|filter roast|\bfiltro\b|\bfiltre\b|"
                     r"filterröst|filterkaffe|handfilter|brew roast", re.I)
ESPRESSO = re.compile(r"\bespresso\b", re.I)
COFFEE_HINT = re.compile(r"single origin|single-origin|altitude|masl|variet|process|tasting notes|"
                         r"flavour notes|flavor notes|producer|washing station|farm|finca|estate", re.I)
NOTES_RE = re.compile(r"(?:tasting notes|flavour notes|flavor notes|flavour profile|in the cup|tastes like|we taste|cup notes|"
                      r"note di degustazione|note aromatiche|note|geschmacksnoten|geschmack|aromen|notes de dégustation|"
                      r"smaksnoter|smagsnoter|smaksnotater|notas de cata|notas|notes)\s*[:\-–]\s*([^\n.]{3,120})", re.I)
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


def get_text(url, tries=2, limit=2_000_000):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"})
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read(limit)
                enc = r.headers.get_content_charset() or "utf-8"
                return raw.decode(enc, "replace")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404, 410) or i == tries - 1:
                raise
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(2)


# ---------- any other shop: sitemap + schema.org Product data ----------
PRODUCTISH = re.compile(r"/(products?|shop|store|negozio|tienda|boutique|butik|produkte?|produits?|prodotti|coffees?|kaffee|caffe|caffè|cafe|café|kaffe|kahvi|kawa|beans|filter|"
                        r"single-origin|catalog|item|p)/", re.I)
SKIP_URL = re.compile(r"/(blog|news|journal|pages?|about|contact|cart|account|collections?|category|categories|tag|"
                      r"wholesale|subscriptions?|gift|equipment|merch)/?$", re.I)


def sitemap_urls(shop):
    """Product-like page URLs with lastmod, newest first. Follows robots.txt and sitemap indexes."""
    cands = []
    try:
        for line in get_text(f"{shop}/robots.txt", tries=1).splitlines():
            if line.lower().startswith("sitemap:"):
                cands.append(line.split(":", 1)[1].strip())
    except Exception:  # noqa: BLE001
        pass
    cands += [f"{shop}/sitemap.xml", f"{shop}/sitemap_index.xml", f"{shop}/product-sitemap.xml", f"{shop}/wp-sitemap.xml"]
    seen, pages, queue = set(), [], []
    for c in cands:
        if c not in seen:
            seen.add(c); queue.append(c)
    fetched = 0
    while queue and fetched < 8:
        sm = queue.pop(0)
        try:
            xml = get_text(sm, tries=1)
            root = ET.fromstring(xml.encode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            continue
        fetched += 1
        tag = root.tag.split("}")[-1]
        ns = {"s": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
        q = (lambda path: root.findall(path, ns)) if ns else (lambda path: root.findall(path.replace("s:", "")))
        if tag == "sitemapindex":
            kids = [e.text.strip() for e in q(".//s:sitemap/s:loc") if e.text]
            kids.sort(key=lambda u: (0 if re.search(r"product|shop|store|item", u, re.I) else 1))
            for k in kids[:6]:
                if k not in seen:
                    seen.add(k); queue.append(k)
        else:
            from_product_map = bool(re.search(r"product", sm, re.I))
            for u in q(".//s:url"):
                loc = u.find("s:loc", ns) if ns else u.find("loc")
                lm = u.find("s:lastmod", ns) if ns else u.find("lastmod")
                if loc is None or not loc.text:
                    continue
                url = loc.text.strip()
                if SKIP_URL.search(url):
                    continue
                if from_product_map or PRODUCTISH.search(url):
                    pages.append((url, (lm.text or "")[:10] if lm is not None and lm.text else ""))
        if len(pages) > 400:
            break
    uniq = {}
    for u, lm in pages:
        uniq.setdefault(u, lm)
    return sorted(uniq.items(), key=lambda x: x[1], reverse=True)


def ld_products(html_text):
    """schema.org Product objects from every JSON-LD block on a page."""
    out = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_text, re.S | re.I):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except Exception:  # noqa: BLE001
                continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                t = d.get("@type")
                types = t if isinstance(t, list) else [t]
                if any(str(x).lower() in ("product", "productgroup") for x in types):
                    out.append(d)
                for v in d.values():
                    if isinstance(v, (list, dict)):
                        stack.append(v)
            elif isinstance(d, list):
                stack.extend(d)
    return out


def ld_to_item(p, url, lastmod):
    offers = p.get("offers") or []
    if isinstance(offers, dict):
        offers = offers.get("offers") if isinstance(offers.get("offers"), list) else [offers]
    variants = p.get("hasVariant") or []
    for v in variants if isinstance(variants, list) else []:
        o = v.get("offers")
        if isinstance(o, dict):
            offers.append(o)
    prices, ccy, avail = [], None, False
    for o in offers:
        if not isinstance(o, dict):
            continue
        pr = o.get("price") or o.get("lowPrice") or (o.get("priceSpecification") or {}).get("price")
        try:
            if pr not in (None, ""):
                prices.append(float(str(pr).replace(",", ".")))
        except ValueError:
            pass
        ccy = ccy or o.get("priceCurrency") or (o.get("priceSpecification") or {}).get("priceCurrency")
        a = str(o.get("availability", "InStock"))
        avail = avail or ("InStock" in a or "PreOrder" in a or "LimitedAvailability" in a)
    if not offers:
        avail = True
    cat = p.get("category") or ""
    if isinstance(cat, list):
        cat = " ".join(map(str, cat))
    brand = p.get("brand")
    desc = p.get("description") or ""
    return {"title": html.unescape(str(p.get("name") or "")).strip(), "type": str(cat), "tags": [],
            "body": strip_html(str(desc)), "variants": "", "available": avail,
            "price": min(prices) if prices else None, "currency": ccy, "url": p.get("url") or url,
            "published": "", "lastmod": lastmod, "brand": brand}


def fetch_generic(shop, max_pages=45):
    items, pages = [], sitemap_urls(shop)
    for url, lm in pages[:max_pages]:
        try:
            page = get_text(url, tries=1)
        except Exception:  # noqa: BLE001
            continue
        for p in ld_products(page)[:1]:
            it = ld_to_item(p, url, lm)
            if it["title"]:
                if len(it["body"]) < 60:   # thin JSON-LD: add the page's meta description
                    m = re.search(r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']+)', page, re.I)
                    if m:
                        it["body"] = (it["body"] + "\n" + html.unescape(m.group(1))).strip()
                items.append(it)
        time.sleep(0.8)
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
    """Earliest whole-word match (so 'China' never matches inside 'Machina', or 'Peru' inside 'Perugia')."""
    best = None
    for w in pattern_list:
        m = re.search(r"(?<![\w])" + re.escape(w) + r"(?![\w])", text or "", re.I)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), w)
    return best[1] if best else None


ORIGIN_LABEL = re.compile(r"(?:origin|country|origine|herkunft|paese|pays|país|ursprung|oprindelse|land)\s*[:\-–]\s*([^\n]{2,60})", re.I)


def count_origin(text):
    """Most-mentioned producing country in a long description (beats a stray mention)."""
    best = (0, None)
    for name, canon in [(c, c) for c in COUNTRIES] + list(COUNTRY_ALIASES.items()):
        n = len(re.findall(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text or "", re.I))
        if n > best[0]:
            best = (n, canon)
    return best[1]


def find_origin(title, blob="", body=""):
    """Title first, then a labelled 'Origin:' line, then tags/categories, then the most-mentioned country."""
    def direct(t):
        o = first(COUNTRIES, t)
        if o:
            return o
        a = first(list(COUNTRY_ALIASES), t)
        return COUNTRY_ALIASES[a] if a else None
    o = direct(title)
    if o:
        return o
    m = ORIGIN_LABEL.search(body or "")
    if m and direct(m.group(1)):
        return direct(m.group(1))
    return direct(blob) or (count_origin(body) if body else None)


def find_process(text):
    t = text.lower()
    if "decaf" in t:
        return "Decaf"
    for pat, name in [(r"anaerobic natural", "Anaerobic natural"), (r"anaerobic washed", "Anaerobic washed"),
                      (r"anaerobic honey", "Anaerobic honey"), (r"carbonic maceration", "Carbonic maceration"),
                      (r"co-?ferment", "Co-fermented"), (r"thermal shock", "Thermal shock"),
                      (r"anaerobic", "Anaerobic"), (r"double fermentation|double ferment", "Double fermented"),
                      (r"anaerob", "Anaerobic"),
                      (r"\bnatural\b|dry[- ]process|\bnaturale\b|\bnaturel\b|\bnatur\b|naturlig|\bnatuurlijk", "Natural"),
                      (r"\bhoney\b|pulped natural|\bmiel\b|\bhonig\b|\bmiele\b", "Honey"),
                      (r"\bwashed\b|wet[- ]process|\blavato\b|gewaschen|\blavé\b|\blavado\b|tvättad|\bvasket\b|gewassen|vaskad", "Washed")]:
        if re.search(pat, t):
            return name
    return None


def find_roast(text):
    """Roast level only when the roaster states it; otherwise None (the site then asks)."""
    t = text.lower()
    for pat, lvl in [(r"(very|ultra|extra)[- ]light", "vlight"), (r"nordic", "vlight"),
                     (r"medium[- ]light|light[- ]medium", "light"),
                     (r"light roast|lightly roasted|roast(?: level)?\s*[:\-]\s*light|tostatura chiara|tostatura leggera|"
                      r"helle röstung|hell geröstet|torréfaction claire|tueste claro|ljusrost|lys brent|lysristet", "light"),
                     (r"medium roast|roast(?: level)?\s*[:\-]\s*medium\b|tostatura media|mittlere röstung|torréfaction moyenne|tueste medio", "medium")]:
        if re.search(pat, t):
            return lvl
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
        if (2 <= len(b) <= 28 and len(b.split()) <= 4 and ":" not in b
                and not re.search(r"\d|masl|process|altitude|score|perfect|sharing|recommend|brew", b, re.I)
                and not first(COUNTRIES, b) and not first(list(COUNTRY_ALIASES), b)):
            out.append(b[:1].upper() + b[1:])
    return out[:4]


def clean_name(title, roaster, origin):
    name = re.sub(r"^(filter|filtro|filtre|espresso|omni)\s*[-–:|/]\s*", "", title, flags=re.I)
    name = re.sub(r"\s*[-–|(]\s*(filter|filtro|filtre|omni)( roast| röst)?\)?\s*$", "", name, flags=re.I)
    parts = re.split(r"\s[-–|]\s", name)
    if len(parts) >= 3 or (len(parts) == 2 and find_origin(parts[1])):
        name = parts[0]
    name = re.sub(r"\s+by\s+" + re.escape(roaster) + r".*$", "", name, flags=re.I)
    if origin:
        name = re.sub(r"[,\s\-–|]+" + re.escape(origin) + r"\s*$", "", name, flags=re.I)
    name = re.sub(r"\(?\b\d{2,4}\s?g\b\)?", "", name, flags=re.I).strip(" -–|,")
    return name or title


def money(v, ccy):
    sym = SYMBOL.get(ccy, ccy + " ")
    amount = f"{v:.0f}" if ccy in ("JPY", "DKK", "SEK", "NOK", "CZK") else f"{v:.2f}"
    return amount + sym if sym.startswith(" ") else sym + amount


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
    origin = find_origin(title, blob, item["body"])
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
        "price": money(item["price"], roaster.get("_ccy", "GBP")) if item["price"] else None,
        "url": item["url"],
        "published": item["published"] or None,
        "roast": "filter" if filtery else "omni / unlabelled",
        "roast_level": find_roast(title + " " + " ".join(item["tags"]) + " " + item["variants"]) or find_roast(item["body"]),
    }
    rec["market"] = roaster.get("region", "UK")
    rec["roaster_country"] = roaster.get("country")
    rec["roaster_city"] = roaster.get("city")
    return {k: v for k, v in rec.items() if v not in (None, "", [])}


def shop_currency(shop, kind, r):
    if r.get("currency"):
        return r["currency"]
    try:
        if kind == "shopify":
            c = get_json(f"{shop}/cart.js", tries=1).get("currency")
            if c:
                return c
        else:
            d = get_json(f"{shop}/wp-json/wc/store/v1/products?per_page=1", tries=1)
            c = d and d[0].get("prices", {}).get("currency_code")
            if c:
                return c
    except Exception:  # noqa: BLE001
        pass
    return COUNTRY_CCY.get(r.get("country", "GB"), "EUR" if r.get("region") == "Europe" else "GBP")


def scan_roaster(r):
    shop = r["shop"].rstrip("/")
    errors = []
    for kind, fn in (("shopify", fetch_shopify), ("woocommerce", fetch_woo), ("sitemap", fetch_generic)):
        try:
            items = fn(shop)
            if items:
                if kind == "sitemap":
                    found = [i["currency"] for i in items if i.get("currency")]
                    r["_ccy"] = r.get("currency") or (max(set(found), key=found.count) if found else shop_currency(shop, kind, r))
                else:
                    r["_ccy"] = shop_currency(shop, kind, r)
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
    old, first_seen = {}, {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text())
            for x in prev.get("releases", []):
                old[x["url"]] = x
            for st in prev.get("roasters", []):
                if st.get("platform"):
                    first_seen[st["name"]] = st.get("first_seen") or prev.get("updated")
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
        if kind and r["name"] not in first_seen:
            first_seen[r["name"]] = today
        status.append({"name": r["name"], "shop": r["shop"], "market": r.get("region", "UK"), "country": r.get("country"),
                       "first_seen": first_seen.get(r["name"]),
                       "currency": r.get("_ccy"), "platform": kind, "coffees": kept, "error": err})
        print(f"{r['name']:<26} {kind or 'FAILED':<12} {kept:>3} {err or ''}")
        time.sleep(1.5)

    # keep last week's coffees from roasters that failed this time (temporary outages)
    urls = {x["url"] for x in found}
    for u, x in old.items():
        if x["roaster"] not in scanned_ok and u not in urls:
            found.append(x)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=NEW_DAYS)).date().isoformat()
    for x in found:
        if x.get("published"):
            x["new"] = x["published"] >= cutoff
        else:   # no listing date: new only if it appeared after we started watching this roaster
            fs = first_seen.get(x["roaster"]) or today
            x["new"] = x.get("found", today) > fs and x.get("found", "") >= cutoff
    found.sort(key=lambda x: (x.get("published") or x.get("found") or ""), reverse=True)
    # one listing per coffee: drop size/variant duplicates and stores that share a catalogue
    seen, per_roaster, deduped = set(), {}, []
    for x in found:
        key_same = (x["roaster"], x["name"].lower())
        key_shared = (x["name"].lower(), x.get("price"), x.get("origin"))
        if key_same in seen or key_shared in seen:
            continue
        if per_roaster.get(x["roaster"], 0) >= PER_ROASTER:
            continue
        seen.update([key_same, key_shared])
        per_roaster[x["roaster"]] = per_roaster.get(x["roaster"], 0) + 1
        deduped.append(x)
    found = deduped[:MAX_ITEMS]

    OUT.write_text(json.dumps({"updated": today, "new_window_days": NEW_DAYS, "roasters": status,
                               "releases": found}, ensure_ascii=False, indent=1) + "\n")
    print(f"\n{len(found)} coffees from {len(scanned_ok)}/{len(roasters)} roasters -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

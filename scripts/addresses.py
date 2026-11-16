"""Find each roaster's address as the roaster publishes it on its own site, for the roaster pages.

Reads the shop's home page and its contact / about / visit pages, and takes, in this order:
  1. a schema.org PostalAddress in the page's JSON-LD (streetAddress, addressLocality, postalCode),
  2. a Google Maps link that spells the address out (maps.google.com/?q=..., google.com/maps/place/...),
  3. for UK and Irish roasters, the lines that end in a postcode or Eircode in the page's text.
Nothing is guessed: no address found means the roaster page keeps showing the city.
Writes data/addresses.json: {roaster name: {"address": ..., "from": url}}.

Run: python3 scripts/addresses.py [name, name...]
"""
import html
import json
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import scan  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "addresses.json"
PAGES = ["", "/pages/contact", "/pages/contact-us", "/contact", "/contact-us", "/pages/visit-us", "/pages/visit", "/visit",
         "/pages/about", "/pages/about-us", "/about", "/about-us", "/pages/find-us", "/find-us", "/pages/roastery", "/roastery"]
UK_PC = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})\b")
EIRCODE = re.compile(r"\b([AC-FHKNPRTV-Y]\d{2}|D6W)\s?([0-9AC-FHKNPRTV-Y]{4})\b")
STREETY = re.compile(r"\d|\b(?:road|rd|street|st|lane|ln|unit|units|way|avenue|ave|industrial|estate|park|yard|place|court|"
                     r"house|mill|works|arches?|arch|close|row|terrace|square|drive|business|centre|center|quay|wharf|farm|"
                     r"building|trading|floor|studio|market|bridge|hill|green|gate|walk|parade|crescent|mews)\b", re.I)
JUNK = re.compile(r"©|copyright|registered|company (?:no|number)|vat\b|all rights|cookie|privacy|newsletter|subscribe|"
                  r"@|https?:|www\.|\bltd\b\.?$|limited|phone|tel\b|call us|email|opening|hours|mon(?:day)?\b|cart|basket|"
                  r"[£€$%]|deliver|shipping|dispatch|order|\bfree\b|\bsale\b|\boff\b|returns?\b|\bgift", re.I)


def ld_address(raw):
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', raw, re.S | re.I):
        try:
            data = json.loads(html.unescape(block.strip()))
        except ValueError:
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                a = d.get("address")
                if isinstance(a, dict) and (a.get("streetAddress") or "").strip():
                    parts = [a.get("streetAddress"), a.get("addressLocality"), a.get("postalCode")]
                    parts = [re.sub(r"\s+", " ", str(p)).strip(" ,") for p in parts if p and str(p).strip()]
                    if len(parts) >= 2:
                        return ", ".join(dict.fromkeys(parts))
                stack.extend(v for v in d.values() if isinstance(v, (dict, list)))
    return None


def maps_address(raw):
    for m in re.finditer(r'(?:maps\.google\.[a-z.]+/(?:maps)?\?[^"\'<>]*?\bq=|google\.[a-z.]+/maps/(?:place|search)/(?:\?api=1&(?:amp;)?query=)?)([^"\'<>&/@]+)', raw, re.I):
        v = urllib.parse.unquote_plus(html.unescape(m.group(1))).strip(" ,")
        if len(v) >= 12 and "," in v and STREETY.search(v) and not re.fullmatch(r"[-\d., ]+", v):
            return re.sub(r"\s+", " ", v)
    return None


def text_address(raw, country):
    """UK / Irish: the lines just before a postcode or Eircode, as long as they read like an address."""
    # the footer is where most shops print their address, so only scripts and styles are dropped (scan._visible drops footers)
    text = scan.strip_html(re.sub(r"<(script|style|noscript|svg|template)(?=[\s>]).*?</\1>", " ", raw, flags=re.I | re.S))
    lines = [re.sub(r"\s+", " ", l).strip(" ,|·•") for l in text.split("\n")]
    lines = [l for l in lines if l]
    rx = EIRCODE if country == "IE" else UK_PC
    for i, line in enumerate(lines):
        m = rx.search(line)
        if not m or len(line) > 120 or JUNK.search(line.replace(m.group(0), "")):
            continue
        before = []
        for prev in reversed(lines[max(0, i - 4):i]):
            if len(prev) > 60 or JUNK.search(prev) or prev.endswith(":"):
                break
            before.insert(0, prev)
        while before and not STREETY.search(before[0]):   # "Visit us", the shop's own name: the address starts at its street
            before.pop(0)
        parts = [p for p in before + [line] if p]
        joined = ", ".join(parts)
        joined = re.sub(r",\s*,", ",", joined)
        if len(joined) > 140 or not STREETY.search(joined.replace(m.group(0), "")):
            continue
        return joined
    return None


def find(r):
    shop = r["shop"].rstrip("/")
    for path in PAGES:
        url = shop + path
        try:
            raw = scan.get_text(url, tries=1, limit=1_500_000)
        except Exception:  # noqa: BLE001
            continue
        got = ld_address(raw) or maps_address(raw) or (text_address(raw, r.get("country", "GB")) if r.get("country", "GB") in ("GB", "IE") else None)
        if got:
            return {"address": got, "from": url}
    return None


def main():
    roasters = json.loads((ROOT / "data" / "roasters.json").read_text())
    want = {n.strip().lower() for n in " ".join(sys.argv[1:]).split(",") if n.strip()}
    if want:
        roasters = [r for r in roasters if r["name"].lower() in want]
    out = json.loads(OUT.read_text()) if OUT.exists() else {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        for r, got in zip(roasters, pool.map(find, roasters)):
            if got:
                out[r["name"]] = got
            print(f"{r['name']:<34} {got['address'] if got else '-'}")
    OUT.write_text(json.dumps(dict(sorted(out.items())), ensure_ascii=False, indent=1) + "\n")
    print(f"\n{sum(1 for r in roasters if r['name'] in out)} of {len(roasters)} roasters with an address")


if __name__ == "__main__":
    main()

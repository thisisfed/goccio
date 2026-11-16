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


LABEL_SEG = re.compile(r"^(?:where to find us|find us|visit us|come (?:and|for)\b.*|our roastery|the roastery|roastery|address|location|"
                       r"duration\b.*|appointment\b.*|\(?appointment only\)?)$", re.I)


def tidy(addr, name):
    """One clean line: no phone numbers, labels ("Visit us", "Roastery:"), the shop's own name or repeats; capitals as
    in a sentence (no words in capitals), postcodes upper case."""
    addr = re.sub(r"\s+", " ", addr).strip(" .,")
    if re.fullmatch(r"-?\d+\.\d+,\s*-?\d+\.\d+", addr):   # map coordinates, not an address
        return ""
    addr = re.sub(r"\((?:a )?trading name[^)]*\)", "", addr, flags=re.I)
    segs, out = [p.strip(" .") for p in re.split(r"\s*[,;]\s*", addr)], []
    for seg in segs:
        seg = re.sub(r"^(?:roastery|location|address|visit us|find us|[A-Za-z]+(?: [A-Za-z]+)?)\s*:\s*", "", seg, flags=re.I).strip()
        short = re.sub(r"\s+(?:coffee|roasters?|roastery|roasting|company|co\.?)\b.*$", "", name, flags=re.I) or name
        seg = re.sub(r"^(?:" + re.escape(name) + "|" + re.escape(short) + r")\s+(?=\d)", "", seg, flags=re.I)
        seg = re.sub(r"^20\d\d\s+(?=\D)", "", seg)   # a copyright year run into the street   # "Ginger Monkey 31 Christleton Rd" -> "31 Christleton Rd"
        seg = re.sub(r"\s*\b(?:ltd|limited)\b\.?", "", seg, flags=re.I).strip()
        if re.search(r"\b(?:\d{1,2}\s?(?:am|pm)|mon|tues?|wed|thur?s?|fri|sat|sun)(?:day)?s?\b|closed|bank holiday|powered by|company reg|"
                     r"view all|visit the|\bNI\d{4,}|\d{7,}|[\U0001F300-\U0001FAFF]|celebrat", seg, re.I) and not UK_PC.search(seg.upper()):
            continue
        if re.fullmatch(r"\d{1,4}[a-z]?", seg) and seg not in ("",):   # "13, Lymington Enterprise Centre": a number on its own joins the next part
            out.append("\0" + seg)
            continue
        if not seg or LABEL_SEG.match(seg) or re.fullmatch(r"[+()\d\s-]{8,}", seg) or re.search(r"\+\d{2}|\b0\d{9,10}\b|\bhrs?\b", seg, re.I):
            continue
        if seg.lower() == name.lower() or (name.lower() in seg.lower() and not STREETY.search(seg.lower().replace(name.lower(), ""))):
            continue
        if seg.lower() in (o.lower() for o in out):
            continue
        if out and out[-1].startswith("\0"):
            out[-1] = out[-1][1:] + " " + seg
            continue
        out.append(seg)
    out = [o[1:] if o.startswith("\0") else o for o in out]   # a number left at the end is a postcode (Oslo 0680)
    if re.fullmatch(r"(?:20\d\d|\d{1,3})", out[0] if out else ""):
        out = out[1:]
    def word(w):
        if UK_PC.fullmatch(w.upper()) or re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]?|\d[A-Z]{2}", w.upper()) and len(w) <= 4:
            return w.upper() if re.search(r"\d", w) else w
        core = w.strip(",.")
        if (core.isupper() and len(core) > 2 and core.isalpha()) or (core.islower() and core.isalpha() and len(core) > 3):
            return w.replace(core, core.capitalize())
        return w
    line = ", ".join(out)
    line = " ".join(word(w) for w in line.split(" "))
    m = UK_PC.search(line.upper())
    if m:   # "g12 8hx" -> "G12 8HX"
        i = line.upper().find(m.group(0))
        line = line[:i] + m.group(0) + line[i + len(m.group(0)):]
    return line


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
                got["address"] = tidy(got["address"], r["name"])
                out[r["name"]] = got
            print(f"{r['name']:<34} {got['address'] if got else '-'}")
    OUT.write_text(json.dumps(dict(sorted(out.items())), ensure_ascii=False, indent=1) + "\n")
    print(f"\n{sum(1 for r in roasters if r['name'] in out)} of {len(roasters)} roasters with an address")


if __name__ == "__main__":
    main()

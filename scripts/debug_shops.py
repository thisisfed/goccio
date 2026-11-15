import sys, re, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import scan
SHOPS = ["https://notescoffee.com", "https://secondcitycoffee.co.uk", "https://www.yellowbourbon.co.uk", "https://thegoldenbean.ie",
         "https://doubletroublecoffee.co.uk", "https://www.westerrossroasters.co.uk", "https://www.northshorecoffeeroasters.co.uk"]
out = []
for s in SHOPS:
    out.append("=" * 20 + " " + s)
    try:
        sm = scan.get_text(s + "/sitemap.xml", tries=1)
        locs = re.findall(r"<loc>([^<]+)</loc>", sm)
        out.append(f"{len(locs)} locs: " + " ".join(locs[:40]))
        prod = [u for u in locs if re.search(r"/p/|/product|/store/|/shop/", u)]
        if prod:
            pg = scan.get_text(prod[0], tries=1)
            out.append("PAGE " + prod[0] + " ld+json=" + str(pg.count("application/ld+json")) + " og:price=" + str("price:amount" in pg))
            out.append(re.sub(r"\s+", " ", scan.strip_html(pg))[:1500])
            for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', pg, re.S):
                out.append("LD " + m.group(1)[:600])
            try:
                j = scan.get_json(prod[0] + "?format=json", tries=1)
                it = j.get("item", {})
                out.append("SQS " + json.dumps({k: it.get(k) for k in ("title", "excerpt", "addedOn", "publishOn", "fullUrl")})[:500])
                out.append("SQSV " + json.dumps((it.get("structuredContent") or {}).get("variants", [])[:2])[:600])
            except Exception as e:  # noqa: BLE001
                out.append(f"SQS err {e}")
    except Exception as e:  # noqa: BLE001
        out.append(f"err {e}")
Path("data/debug.txt").write_text("\n".join(out))

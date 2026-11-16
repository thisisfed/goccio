import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import scan
out = []
R = {r["name"]: r for r in json.loads(Path("data/roasters.json").read_text())}
# Bean Brothers: sitemap and the shop page's JSON
try:
    sm = scan.get_text("https://www.beanbrothers.co.uk/sitemap.xml", tries=1)
    locs = re.findall(r"<loc>([^<]+)</loc>", sm)
    out.append(f"BB sitemap {len(locs)} urls: " + " ".join(locs[:80]))
except Exception as e:
    out.append(f"BB sitemap ERR {e}")
try:
    j = scan.get_json("https://www.beanbrothers.co.uk/coffee-shop?format=json", tries=1)
    out.append("BB keys " + str(list(j.keys())))
    its = scan._sqs_items(j)
    out.append(f"BB items {len(its)}")
    if its:
        out.append("BB item0 keys " + str(list(its[0].keys())))
        out.append("BB item0 " + json.dumps(its[0])[:3000])
except Exception as e:
    out.append(f"BB json ERR {e}")
# Kaffa Roastery: what the shop gives and why each item is dropped
r = R["Kaffa Roastery"]
kind, items, err = scan.scan_roaster(r)
out.append(f"KAFFA kind={kind} n={len(items)} err={err}")
for it in items[:40]:
    rec = scan.classify(it, r)
    why = [k for k in ("not_coffee", "not_beans", "not_one_coffee") if getattr(scan, k)(it)]
    out.append(f"  {it['title']!r} type={it.get('type')!r} avail={it.get('available')} kept={bool(rec)} why={[getattr(scan, k)(it) for k in why]} url={it.get('url')}")
for k, v in scan.DROPS.get("Kaffa Roastery", {}).items():
    out.append(f"  DROP {k}: {v[:10]}")
Path("data/dbg_shops.txt").write_text("\n".join(out))

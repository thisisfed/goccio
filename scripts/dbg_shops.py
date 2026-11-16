import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import scan
out = []
R = {r["name"]: r for r in json.loads(Path("data/roasters.json").read_text())}
for name in ("Kaffa Roastery", "Bean Brothers"):
    r = R[name]
    kind, items, err = scan.scan_roaster(r)
    out.append(f"{name}: kind={kind} items={len(items)} err={err}")
    for it in items:
        rec = scan.classify(it, r)
        if rec:
            out.append(f"  KEPT {rec['name']} | {rec.get('origin')} | {rec.get('process')} | {rec.get('price')} | {rec['url']}")
    for k, v in scan.DROPS.get(name, {}).items():
        out.append(f"  DROP {k}: {v[:12]}")
Path("data/dbg_shops.txt").write_text("\n".join(out))

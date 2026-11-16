import json, random, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import scan
R = json.loads(Path("data/releases.json").read_text())["releases"]
miss = [r for r in R if not r.get("roast")]
random.seed(11)
by = {}
for r in miss:
    by.setdefault(r["roaster"], []).append(r)
pick = [random.choice(v) for k, v in random.sample(sorted(by.items()), 60)]
out = []
for r in pick:
    try:
        raw, text = scan.cached_page(r["url"])
    except Exception as e:  # noqa: BLE001
        out.append(f"## {r['roaster']} | {r['name']} | ERR {e}")
        continue
    hits = []
    for m in re.finditer(r"roast", text, re.I):
        hits.append(text[max(0, m.start() - 60):m.start() + 80].replace("\n", " / "))
    rawh = []
    for m in re.finditer(r"roast[_ -]?(?:level|profile|degree)|\b(?:light|medium|dark)[_-]roast", raw, re.I):
        rawh.append(raw[max(0, m.start() - 80):m.start() + 100].replace("\n", " "))
    out.append(f"## {r['roaster']} | {r['name']} | {r['url']}\nTEXT: " + " || ".join(hits[:8]) + "\nRAW: " + " || ".join(rawh[:4]))
Path("data/debug_roast.txt").write_text("\n".join(out))

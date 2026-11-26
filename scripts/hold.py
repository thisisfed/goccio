"""Publishing: coffees held back for a look (data/held.json, not yet in data/approved.json) are left off the site.
Usage: python3 scripts/hold.py <site folder>   (edits data/releases.json there, never the one in the repo)"""
import json
import sys
from pathlib import Path

site = Path(sys.argv[1])
key = lambda u: (u or "").split("?")[0].split("#")[0].rstrip("/").lower()
load = lambda f: json.loads(f.read_text()) if f.exists() else {}
held, ok = load(site / "data" / "held.json"), load(site / "data" / "approved.json")
hide = {u for u in held if u not in ok} | {key(u) for u in load(site / "data" / "banned_coffees.json")}   # a coffee banned from the email goes at once, not at tomorrow's scan
p = site / "data" / "releases.json"
d = json.loads(p.read_text(encoding="utf-8"))
n0 = len(d["releases"])
d["releases"] = [r for r in d["releases"] if key(r.get("url")) not in hide]
p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"held back from the site: {n0 - len(d['releases'])}")

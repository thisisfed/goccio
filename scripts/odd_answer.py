"""The ticks in an Odd coffees issue: "Show it" puts a held coffee on the site (data/approved.json), "Ban it" takes it off for good
(data/banned_coffees.json). Either way it leaves data/held.json. Usage: python3 scripts/odd_answer.py <issue body file>"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
body = Path(sys.argv[1]).read_text()
load = lambda f: json.loads(f.read_text()) if f.exists() else {}
H, OK, BAN = ROOT / "data" / "held.json", ROOT / "data" / "approved.json", ROOT / "data" / "banned_coffees.json"
held, ok, ban = load(H), load(OK), load(BAN)
shown = banned = 0
for verb, u in re.findall(r"^\s*[-*] \[[xX]\] (Show|Ban) it: (\S+)", body, re.M):
    u = u.strip().lower()
    h = held.pop(u, None)
    if verb == "Show" and u not in ok:
        ok[u] = date.today().isoformat(); shown += 1
    elif verb == "Ban" and u not in ban:
        ban[u] = {"name": (h or {}).get("name"), "roaster": (h or {}).get("roaster"), "on": date.today().isoformat(), "why": "banned from the odd-coffees email"}
        ok.pop(u, None); banned += 1
for f, v in ((H, held), (OK, ok), (BAN, ban)):
    f.write_text(json.dumps(v, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
print(f"shown {shown}, banned {banned}")

"""The roasters in the new list that weren't in the old one, as the scan's --only wants them: names, comma-separated.

  python3 scripts/new_roasters.py /tmp/roasters_before.json data/roasters.json
"""
import json
import sys

old = {r.get("name") for r in json.load(open(sys.argv[1], encoding="utf-8"))}
new = [r["name"] for r in json.load(open(sys.argv[2], encoding="utf-8")) if r.get("name") and r["name"] not in old and "," not in r["name"]]
print(",".join(new))

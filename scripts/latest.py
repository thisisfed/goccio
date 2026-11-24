#!/usr/bin/env python3
"""The newest coffees in a small file, so the list shows before the full one has arrived.

Usage: python3 scripts/latest.py <site folder>   (reads data/releases.json there, writes data/latest.json beside it)

The page lists coffees that are just in, then new ones, then the rest, newest day first in each. This keeps whole days in that
order until there are at least 30 coffees: the first screen is then the same as with the full list. Fewer than 5: no file, and the
page loads the full list as before.
"""
import json, sys
from pathlib import Path

site = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
d = json.loads((site / "data" / "releases.json").read_text(encoding="utf-8"))
rel = [r for r in d.get("releases", []) if r.get("name") and r.get("roaster")]
# the page's own order: just in, then new, then the rest; inside each, newest day first
date = lambda r: (r.get("found") if r.get("just_in") else r.get("published") or r.get("found")) or ""
keep = []
for grp in ([r for r in rel if r.get("just_in")], [r for r in rel if r.get("new") and not r.get("just_in")], [r for r in rel if not r.get("new") and not r.get("just_in")]):
    days = {}
    for r in grp:
        days.setdefault(date(r), []).append(r)
    for day in sorted(days, reverse=True):
        if len(keep) >= 30:
            break
        keep += days[day]
    if len(keep) >= 30:
        break
out = site / "data" / "latest.json"
if len(keep) < 5:
    out.unlink(missing_ok=True)
    print("latest.json: too few new coffees, not written")
else:
    names = {r["roaster"] for r in keep}
    day = max((r.get("found") or "" for r in rel), default="")   # the last scan's day, and how many coffees it added
    out.write_text(json.dumps({"updated": d.get("updated"), "total": len(rel), "roasters_n": len({r["roaster"] for r in rel}),
                               "added_day": day, "added_n": sum(1 for r in rel if r.get("found") == day),
                               "roasters": [x for x in d.get("roasters", []) if x and x.get("name") in names], "releases": keep},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"latest.json: {len(keep)} coffees, {out.stat().st_size // 1024} KB")

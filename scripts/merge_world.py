#!/usr/bin/env python3
"""Put a roaster-finder run's finds back on top of a newer main.

The finder can run for hours. If main moved meanwhile (the nightly run also adds roasters), its commit can't be rebased
cleanly and every find was lost (24 Nov 2026: 27 roasters). This takes the run's own copies of the data files (saved before
committing) and adds what they have that the newer files lack: roasters by shop host, appended in the run's order; the
seen-list and map cache merged key by key, the run's value winning.

Usage: python3 scripts/merge_world.py <folder with the run's roasters.json, world_seen.json, world_map.json>
"""
import json, os, sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def host(u):
    h = urlparse(u if "//" in str(u) else "https://" + str(u)).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def load(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def main():
    ours_dir = sys.argv[1]
    theirs = load(os.path.join(DATA, "roasters.json"), [])
    ours = load(os.path.join(ours_dir, "roasters.json"), [])
    have = {host(r.get("shop", "")) for r in theirs if isinstance(r, dict)}
    names = {str(r.get("name", "")).lower() for r in theirs if isinstance(r, dict)}
    add = [r for r in ours if isinstance(r, dict) and host(r.get("shop", "")) not in have and str(r.get("name", "")).lower() not in names]
    with open(os.path.join(DATA, "roasters.json"), "w", encoding="utf-8") as f:   # one roaster a line, as discover.save_roasters writes it
        f.write("[\n" + ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in theirs + add) + "\n]\n")
    for name in ("world_seen.json", "world_map.json"):
        o = load(os.path.join(ours_dir, name), None)
        if not isinstance(o, dict):
            continue
        t = load(os.path.join(DATA, name), {})
        if not isinstance(t, dict):
            t = {}
        t.update(o)
        with open(os.path.join(DATA, name), "w", encoding="utf-8") as f:   # as world.py writes them
            f.write(json.dumps(dict(sorted(t.items())) if name == "world_seen.json" else t, ensure_ascii=False, indent=0) + "\n")
    print(f"put back {len(add)} roaster(s) on top of the newer list: " + ", ".join(r.get("name", "") for r in add[:20]))


if __name__ == "__main__":
    main()

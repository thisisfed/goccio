"""Why coffees on the list have no process. Reads the product page of every coffee without one (or the first N),
tries the scanner's own readers and a looser phrase reader, and prints what the page says near the word "process".
Nothing is saved. Run from the "Find new roasters" workflow with the diag input."""
import json, re, sys, collections
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import scan  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORD = re.compile(r"washed|natural|honey|anaerob|ferment|pulped|wet[- ]hull|giling|semi[- ]washed|sun[- ]dried|dry[- ]process|carbonic|lavado|lavé|lavato|natur", re.I)


def page(rec):
    try:
        raw, text = scan.cached_page(rec["url"])
    except Exception as e:  # noqa: BLE001
        return rec, None, None, f"{type(e).__name__}"
    return rec, raw, text, None


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    R = json.loads((ROOT / "data" / "releases.json").read_text())["releases"]
    miss = [r for r in R if not r.get("process") and not r.get("blend")][:n]
    print(f"{len(miss)} single-origin coffees without a process")
    with ThreadPoolExecutor(max_workers=16) as pool:
        got = list(pool.map(page, miss))
    stats, by_roaster, snippets = collections.Counter(), collections.Counter(), []
    for rec, raw, text, err in got:
        if err:
            stats["page unreachable"] += 1; continue
        start = max(0, text.lower().find(rec["name"].lower()[:30]))
        cur = scan.labelled(text, "process", start) or scan.labelled(text, "process") or scan.raw_labelled(raw, "process") or scan.from_json(raw, "process") \
            or scan.class_labelled(raw, "process") or scan.suffix_labelled(text, "process", start) or scan.process_from_text(text[start:start + 4000])
        new = scan.process_phrase(text[start:start + 6000], why=True) if not cur else None
        anyw = [m for m in WORD.finditer(text[start:start + 6000])]
        if cur:
            stats["current readers find it"] += 1
        elif new:
            stats["phrase reader finds it"] += 1; snippets.insert(0, ("NEW " + new[0], rec, new[1]))
        elif anyw:
            stats["a process word somewhere, no reader"] += 1; by_roaster[rec["roaster"]] += 1
            m = anyw[0]; t = text[start:start + 6000]
            snippets.append(("WORD", rec, t[max(0, m.start() - 120): m.end() + 120]))
        else:
            stats["no process word on the page"] += 1
    print(dict(stats))
    print("roasters with process words but no reader:", by_roaster.most_common(30))
    for tag, rec, s in snippets[:140]:
        print(f"{tag} | {rec['roaster']} | {rec['name']} | {re.sub(r'\\s+', ' ', s)[:300]}")


if __name__ == "__main__":
    main()

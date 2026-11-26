"""Today's new coffees that look odd, for a person to check: a strange name ("[ ] 2027", a bag size, a gift box, a code)
or tasting notes that aren't tastes ("Typical of the region", "Dynamic", "Where juicy mandarin").

Writes odd-coffees.md (a list with links) and prints how many. The Odd coffees workflow opens it as a GitHub issue each
morning after the scan, so it arrives by email; nothing on the site changes. Usage: python3 scripts/odd_coffees.py [YYYY-MM-DD]
"""
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import flavours  # noqa: E402

day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
rel = json.loads((ROOT / "data" / "releases.json").read_text())["releases"]

# words that are tastes: the flavour dictionary, plus any word used in the notes of 6 or more coffees across the whole list
seen = Counter()
for r in rel:
    seen.update({w for n in r.get("notes") or [] for w in re.findall(r"[a-zà-ÿ]+", n.lower())})
TASTE = {w for w, c in seen.items() if c >= 6} | set(flavours.EN_WORDS) | {w for k in flavours.W for w in k.split()}
# words that describe a coffee, its place or its making, not how it tastes
NOT_TASTE = set("""typical typically classic dynamic balanced complex structured structure profile region regional origin process processed
washed natural anaerobic altitude roast roasted espresso filter notes note hints hint where when which this that our
we you perfect great delicious amazing lovely nice unique specialty quality harvest farm producer variety coffee cup brew
recommended ideal suitable everyday daily house blend""".split())

NAME_BAD = [
    (r"^[^a-zA-ZÀ-ÿ]*$", "no letters"),
    (r"[\[\]{}<>|#*_]", "stray symbols"),
    (r"\b\d+\s?(?:g|kg|gr|grams?|oz|lb)\b", "a bag size"),
    (r"\b(?:gift|box|set|bundle|sample|subscription|pack|capsules?|pods?|drip ?bags?|instant|ground|tea|voucher|card)\b", "not one coffee?"),
    (r"\bcopy of\b|\btest\b|\bdraft\b", "a shop leftover"),
    (r"\b[A-Z]{2,}\d+\b|\b(?!(?:19|20)\d\d\b)\d{4,}\b", "a code"),   # "GN007", "74158"; a year like 2026 is fine
]


def odd_name(r):
    n = (r.get("name") or "").strip()
    why = [w for rx, w in NAME_BAD if re.search(rx, n, re.I if w != "a code" else 0)]
    if len(n) > 64 or len(n.split()) > 9:
        why.append("very long")
    if len(re.sub(r"[^a-zA-ZÀ-ÿ]", "", n)) < 3 and "no letters" not in why:
        why.append("hardly a name")
    return why


def odd_notes(r):
    out = []
    for n in r.get("notes") or []:
        ws = re.findall(r"[a-zà-ÿ]+", n.lower())
        if not ws:
            continue
        if any(w in NOT_TASTE for w in ws):
            out.append(n)
        elif not any(w in TASTE or w.rstrip("s") in TASTE or w[:-2] in TASTE for w in ws):   # plurals: "Pecans", "Cherries"
            out.append(n)
        elif len(ws) > 5 or len(n) > 40:
            out.append(n)
    return out


today = [r for r in rel if r.get("found") == day]
rows = []
for r in today:
    a, b = odd_name(r), odd_notes(r)
    if a or b:
        rows.append((r, a, b))

dd = "/".join(reversed(day.split("-")))
if rows:
    lines = [f"{len(rows)} of today's {len(today)} new coffees look odd. Nothing on the site has changed: tell Claude which to fix, rename or ban.", ""]
    for r, a, b in sorted(rows, key=lambda t: (t[0].get("roaster") or "", t[0].get("name") or "")):
        why = []
        if a:
            why.append("name: " + ", ".join(a))
        if b:
            why.append("notes: " + "; ".join(f"“{x}”" for x in b))
        notes = ", ".join(r.get("notes") or []) or "no notes"
        lines.append(f"- **{r.get('name')}** from {r.get('roaster')} ({notes})  \n  {'; '.join(why)}  \n  {r.get('url')}")
    Path("odd-coffees.md").write_text("\n".join(lines) + "\n")
else:
    Path("odd-coffees.md").write_text(f"Nothing odd among today's {len(today)} new coffees.\n")
print(f"odd coffees {dd}: {len(rows)} of {len(today)}")

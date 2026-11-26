"""Today's new coffees that look odd, for a person to check: a strange name ("[ ] 2027", a bag size, a gift box, a code)
or tasting notes that aren't tastes ("Typical of the region", "Dynamic", "Where juicy mandarin").

They're held back: the scan (python3 scripts/odd_coffees.py --hold, before it commits) puts them in data/held.json, and
publishing leaves held coffees off the site (scripts/hold.py). The Odd coffees workflow then emails them as an issue with two
boxes each: tick "Show it" and the coffee goes on the site (data/approved.json, never held again), tick "Ban it" and it goes
for good (data/banned_coffees.json). The Odd coffees: answer workflow does that the moment a box is ticked.
Usage: python3 scripts/odd_coffees.py [--hold] [YYYY-MM-DD]   (without --hold: writes odd-coffees.md from what's held today)
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

args = [a for a in sys.argv[1:] if not a.startswith("--")]
HOLD = "--hold" in sys.argv
day = args[0] if args else date.today().isoformat()
HELD, OK = ROOT / "data" / "held.json", ROOT / "data" / "approved.json"
load = lambda f: json.loads(f.read_text()) if f.exists() else {}
key = lambda u: (u or "").split("?")[0].split("#")[0].rstrip("/").lower()
rel = json.loads((ROOT / "data" / "releases.json").read_text())["releases"]

# words that are tastes: the flavour dictionary, plus any word used in the notes of 6 or more coffees across the whole list
seen = Counter()
for r in rel:
    seen.update({w for n in r.get("notes") or [] for w in re.findall(r"[a-zà-ÿ]+", n.lower())})
TASTE = {w for w, c in seen.items() if c >= 6} | set(flavours.EN_WORDS) | {w for k in flavours.W for w in k.split()} | {w for k, v in flavours.W.items() for w in v[0].split()}
# real tastes that few coffees mention, so they aren't flagged (from the first lists, 26/11/2026)
TASTE |= set("""roasted starfruit osmanthus panettone satsuma woody rosemary rosewater speculoos zingy limoncello mangosteen tangy hawthorn calamansi longan
stevia granola loquat pastry tiramisu candyfloss maltesers banoffee herbaceous hops effervescent umami chrysanthemum lingonberry sandalwood barquillo
jackfruit ganache frangipane lollipop darjeeling viscous gooseberries gooseberry vermouth cereals flowery mulberry cointreau boysenberry dragonfruit dandelion
daisy botanical biscoff chewy waffle peachy camomile limeade choco allspice cognac snickers savory sapodilla velvet smoke quince lactic gianduja malic
carnation amarula soldum blaeberries refreshers sangria skittles piloncillo plush acai açaí molasse molasses fruitiness nuttiness balanced complex round long smoked oak wood rye puchao love hearts""".split())
# words that describe a coffee, its place or its making, not how it tastes
NOT_TASTE = set("""typical typically classic dynamic structured structure profile region regional origin process processed
washed natural anaerobic altitude roast espresso filter notes note hints hint where when which this that our
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
held, ok = load(HELD), load(OK)
if HOLD:   # the scan: today's odd ones go on hold, unless already shown once by hand
    n = 0
    for r in today:
        a, b = odd_name(r), odd_notes(r)
        u = key(r.get("url"))
        ns = r.get("notes") or []
        bad_name = [w for w in a if w in ("no letters", "a bag size", "not one coffee?", "a shop leftover")]   # a variety code (SL28, 74158) or a '#' is no reason to hide
        if (bad_name or (b and len(b) * 2 >= len(ns))) and u and u not in ok and u not in held:   # an odd name, or notes that are mostly not tastes; one odd note among good ones isn't worth hiding a coffee
            held[u] = {"name": r.get("name"), "roaster": r.get("roaster"), "on": day, "why": "; ".join((["name: " + ", ".join(a)] if a else []) + (["notes: " + "; ".join(b)] if b else []))}
            n += 1
    HELD.write_text(json.dumps(held, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(f"held back today: {n} (on hold in all: {len(held)})")
    sys.exit(0)

by_url = {key(r.get("url")): r for r in rel}
rows = [(u, h, by_url.get(u)) for u, h in held.items() if h.get("on") == day]
dd = "/".join(reversed(day.split("-")))
if rows:
    lines = [f"{len(rows)} of today's {len(today)} new coffees look odd, so they're **held back**: not on the site until you tick **Show it**. "
             "**Ban it** takes one off for good. Unticked, a coffee stays hidden.", ""]
    for u, h, r in sorted(rows, key=lambda t: ((t[1].get("roaster") or ""), (t[1].get("name") or ""))):
        notes = ", ".join((r or {}).get("notes") or []) or "no notes"
        lines.append(f"**{h.get('name')}** from {h.get('roaster')} ({notes})  \n{h.get('why')}")
        lines.append(f"- [ ] Show it: {u}")
        lines.append(f"- [ ] Ban it: {u}")
        lines.append("")
    Path("odd-coffees.md").write_text("\n".join(lines) + "\n")
else:
    Path("odd-coffees.md").write_text(f"Nothing odd among today's {len(today)} new coffees.\n")
print(f"odd coffees {dd}: {len(rows)} of {len(today)}")

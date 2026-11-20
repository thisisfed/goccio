"""Promote a roaster (they paid to be at the top of the coffee list), or stop a promotion.

Run from the "Promote a roaster" workflow on GitHub (Actions > Promote a roaster > Run workflow): type the roaster's
name as it is on the list, how many days, how many of its coffees to pin. Writes data/promoted.json; the site reads it
and pins the roaster's newest coffees at the top, labelled Paid promotion, from the start date until the end date.

    python3 scripts/promote.py "Square Mile" 30 1          # 30 days from today, its newest coffee
    python3 scripts/promote.py "Square Mile" stop          # end it now
"""
import json, sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "data" / "promoted.json"


def main():
    name, days = sys.argv[1].strip(), (sys.argv[2] if len(sys.argv) > 2 else "30").strip().lower()
    coffees = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].strip() else 1
    known = {r["name"].lower(): r["name"] for r in json.loads((ROOT / "data" / "roasters.json").read_text().replace(",\n]", "\n]"))}
    if name.lower() not in known:
        close = [v for k, v in known.items() if name.lower() in k or k in name.lower()][:5]
        sys.exit(f"No roaster called {name!r} on the list." + (f" Did you mean: {', '.join(close)}?" if close else ""))
    name = known[name.lower()]
    try:
        promos = json.loads(FILE.read_text())
    except (OSError, ValueError):
        promos = []
    today = date.today()
    promos = [p for p in promos if p["roaster"] != name and p.get("until", "") >= today.isoformat()]   # ended ones drop out
    if days == "stop":
        print(f"Stopped: {name}")
    else:
        until = today + timedelta(days=max(1, int(days)) - 1)
        promos.append({"roaster": name, "from": today.isoformat(), "until": until.isoformat(), "coffees": max(1, min(3, coffees))})
        print(f"Promoted: {name}, {today:%d/%m/%Y} to {until:%d/%m/%Y}, {max(1, min(3, coffees))} coffee(s) at the top")
    FILE.write_text(json.dumps(promos, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

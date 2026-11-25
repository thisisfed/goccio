"""Goccio's week: counts last week's unanswered questions into the body of their issue, most asked first, and labels it
"ready", so the list can be sent to Claude to teach Goccio the answers. Run on Mondays by .github/workflows/learn.yml.
Needs GH_TOKEN with access to the private requests repo."""
import json, os, re, sys, urllib.request
from collections import OrderedDict

REPO = "thisisfed/goccio-requests"
TOKEN = os.environ.get("GH_TOKEN", "")


def gh(path, method="GET", body=None):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json", "User-Agent": "goccio-learn"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"null")


def norm(q):
    return re.sub(r"[^a-z0-9à-ü ]+", "", q.lower()).strip()


def main():
    if not TOKEN:
        print("no token: nothing to do"); return
    issues = gh("/issues?labels=goccio-learn&state=open&per_page=50")
    for it in issues:
        if any(l["name"] == "ready" for l in it.get("labels", [])):
            continue
        # this week's issue is still filling up: only last week's (and older) are counted
        m = re.search(r"week of (\d+) (\w+) (\d{4})", it["title"])
        if not m:
            continue
        from datetime import datetime, timedelta, timezone
        start = datetime.strptime(" ".join(m.groups()), "%d %b %Y").replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < start + timedelta(days=7):
            continue
        seen = OrderedDict()
        page = 1
        while True:
            cs = gh(f"/issues/{it['number']}/comments?per_page=100&page={page}")
            if not cs:
                break
            for c in cs:
                q = c["body"].split("\n\n<sub>")[0].strip()
                why = "👎" if "👎" in c["body"] else "didn't know"
                k = norm(q)
                if not k:
                    continue
                e = seen.setdefault(k, {"q": q, "n": 0, "down": 0})
                e["n"] += 1; e["down"] += why == "👎"
            page += 1
        rows = sorted(seen.values(), key=lambda e: -e["n"])
        lines = [f"{i + 1}. {e['q']}" + (f" (×{e['n']})" if e["n"] > 1 else "") + (" 👎" if e["down"] else "") for i, e in enumerate(rows)]
        body = (f"**{len(rows)} questions Goccio couldn't answer**, most asked first (👎: someone disliked its answer).\n\n" + "\n".join(lines)
                + "\n\nSend this issue to Claude to teach Goccio the answers.") if rows else "No questions this week."
        gh(f"/issues/{it['number']}", "PATCH", {"body": body})
        gh(f"/issues/{it['number']}/labels", "POST", {"labels": ["ready"]})
        print(f"#{it['number']}: {len(rows)} questions counted")


if __name__ == "__main__":
    sys.exit(main())

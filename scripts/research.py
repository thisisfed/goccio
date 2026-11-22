#!/usr/bin/env python3
"""Weekly research and recipe watch. Free, like the roaster scan: public feeds and registries only, no keys, no accounts.

It looks for three things since the last run and writes a short digest (data/research.md):
  1. New peer-reviewed papers on brewing, extraction, grinding, brew water and coffee tasting (Crossref, by title).
  2. New videos and posts from the people whose recipes the site uses: every YouTube channel behind a video the footer
     cites, plus a few blogs. A new source added to the footer is watched from the next run on.
  3. The recipe pages the footer cites: if the brewing numbers printed on one change (grams, ratios, times, degrees),
     it says which appeared and which went.
It never changes the site: it only reports. State is kept in data/research.json.

  python3 scripts/research.py            run and write the digest
  python3 scripts/research.py --selftest check the filters
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import scan  # noqa: E402  (the scanner's polite fetcher: robots.txt respected, user agent Goccio/1.0)

ROOT = scan.ROOT
STATE = ROOT / "data" / "research.json"
DIGEST = ROOT / "data" / "research.md"
FIRST_LOOK_BACK, MAX_LOOK_BACK, OVERLAP = 30, 60, 2   # days

QUERIES = ["coffee brewing", "coffee extraction yield", "espresso extraction", "pour-over coffee", "cold brew coffee",
           "coffee grinding particle size", "coffee sensory brew temperature", "brewing water coffee taste",
           "roasted coffee storage freshness", "caffeine sleep"]
COFFEE = re.compile(r"\b(coffees?|espresso|cold brew|moka)\b", re.I)
TOPIC = re.compile(r"brew|extract|grind|ground coffee|particle|percolat|immersion|pour|drip|filter coffee|espresso|sensory|flavou?r|aroma|"
                   r"taste|acidity|bitter|sweet|water|temperature|roast|storage|stal|fresh|degas|crema|cupping|consumer", re.I)
SKIP = re.compile(r"spent coffee|coffee (?:husk|pulp|silverskin|waste|by-?products?|leaf|leaves|plants?|farm\w*|berry|rust|cherr\w+|trees?)|"
                  r"biochar|adsorb|biodiesel|biogas|compost|coffee ?shops?|coffeehouse|caf[eé]s?\b|supply chain|prices?\b|market|export|"
                  r"agroforest|genom|cultivar|soil|irrigation|fertili[sz]|pregnan|cancer|mortality|cardiovascular|diabet|cohort|"
                  r"\brats?\b|\bmice\b|mouse|polyphenol intake|nanoparticle|corrosion|concrete|asphalt|wastewater", re.I)
GROUPS = {"ristenpart", "guinard", "batali", "frost", "liang", "yeretzian", "smrke", "hendon", "gagné", "gagne", "cotter", "moroney", "rune"}

BLOGS = [("Scott Rao", "https://www.scottrao.com/blog?format=rss"), ("Coffee ad Astra", "https://coffeeadastra.com/feed/"),
         ("Barista Hustle", "https://www.baristahustle.com/feed/")]
BREWING = re.compile(r"recipe|technique|method|how to|brew|v60|pour|aeropress|french press|moka|espresso|switch|kalita|chemex|origami|"
                     r"clever|orea|grind|water|extract|cold brew|cupping|bloom|ratio|dripper|filter", re.I)
NUMS = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:g|grams?|ml|°\s?[CF]|µm|microns?|clicks?|seconds?|secs?|minutes?|mins?)\b|\b1\s?:\s?\d+(?:\.\d+)?\b|\b\d{1,2}:\d{2}\b", re.I)
NOT_PAGES = re.compile(r"doi\.org|youtube\.com|youtu\.be|docs\.google|digitalcollection|/search|sca\.coffee/?$", re.I)


def day(d):
    return f"{d.day} {d.strftime('%b %Y')}"


def keep_paper(title):
    """A paper is listed when its title is about coffee in the cup: brewing, extraction, grinding, water, tasting, storage.
    Farming, waste, health studies and cafés are left out; caffeine and sleep is the one health topic the site cites."""
    t = title or ""
    if re.search(r"caffeine", t, re.I) and re.search(r"\bsleep", t, re.I):
        return True
    return bool(COFFEE.search(t) and TOPIC.search(t) and not SKIP.search(t))


def fingerprint(text):
    """The brewing numbers printed on a page (grams, millilitres, degrees, ratios, times), as a sorted list: layout and
    wording can change freely, a changed number shows."""
    return sorted({re.sub(r"\s+", "", m.group(0).lower()).replace(",", ".") for m in NUMS.finditer(text or "")})


def footer_links(page):
    """(label, url) for every link in the footer's Sources list."""
    a = page.find('<ol class="refs">')
    b = page.find("</ol>", a)
    out = []
    for li in re.findall(r"(?is)<li>(.*?)</li>", page[a:b] if a >= 0 else ""):
        m = re.search(r'href="([^"]+)"', li)
        if m:
            label = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", li.split("<a ")[0]))).strip(" .")
            out.append((label[:90], html.unescape(m.group(1))))
    return out


def new_papers(since, seen, cited, problems):
    found = {}
    for q in QUERIES:
        url = ("https://api.crossref.org/works?query.bibliographic=" + urllib.parse.quote(q) +
               f"&filter=from-created-date:{since.isoformat()},type:journal-article&rows=100"
               "&select=DOI,title,author,container-title,created")
        try:
            items = (scan.get_json(url, tries=2) or {}).get("message", {}).get("items", [])
        except Exception as e:  # noqa: BLE001
            problems.append(f"Crossref search for '{q}' ({type(e).__name__})")
            continue
        for it in items:
            doi = (it.get("DOI") or "").lower()
            title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", (it.get("title") or [""])[0]))).strip()
            if not doi or doi in seen or doi in cited or doi in found or not keep_paper(title):
                continue
            fam = [a.get("family", "") for a in it.get("author") or [] if a.get("family")]
            parts = (it.get("created") or {}).get("date-parts") or [[]]
            when = dt.date(*(parts[0] + [1, 1])[:3]) if parts[0] else None
            found[doi] = {"doi": doi, "title": title, "authors": fam, "journal": html.unescape((it.get("container-title") or [""])[0]),
                          "date": when.isoformat() if when else "", "group": any(f.lower() in GROUPS for f in fam)}
    return sorted(found.values(), key=lambda p: (not p["group"], p["date"]), reverse=False)


def channel_of(video_id, cache):
    if video_id in cache:
        return cache[video_id]
    raw = scan.get_text(f"https://www.youtube.com/watch?v={video_id}", tries=1)
    m = re.search(r'"channelId":"(UC[\w-]{22})"', raw) or re.search(r'youtube\.com/channel/(UC[\w-]{22})', raw)
    if not m:
        return None
    cache[video_id] = m.group(1)
    return m.group(1)


def feed_entries(raw):
    """(id, title, link, date) from an Atom or RSS feed."""
    out = []
    for e in re.findall(r"(?is)<(?:entry|item)\b.*?</(?:entry|item)>", raw):
        def tag(name):
            m = re.search(rf"(?is)<{name}[^>]*>(.*?)</{name}>", e)
            return html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip() if m else ""
        vid = tag("yt:videoId")
        link = (f"https://www.youtube.com/watch?v={vid}" if vid else tag("link")) or (re.search(r'<link[^>]+href="([^"]+)"', e) or [None, ""])[1]
        when = tag("published") or tag("pubDate") or tag("updated")
        d = None
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", when)
        if m:
            d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        else:
            m = re.search(r"(\d{1,2}) (\w{3}) (\d{4})", when)
            if m:
                try:
                    d = dt.datetime.strptime(" ".join(m.groups()), "%d %b %Y").date()
                except ValueError:
                    d = None
        if link and d:
            out.append((vid or link, re.sub(r"\s+", " ", tag("title")), link, d))
    return out


def new_videos(page, since, state, problems):
    seen, cache = set(state.get("seen_posts", [])), state.setdefault("channels", {})
    feeds, out, other = {}, [], 0
    for vid in sorted(set(re.findall(r"youtube\.com/watch\?v=([\w-]{11})", page))):
        try:
            ch = channel_of(vid, cache)
        except Exception as e:  # noqa: BLE001
            ch = None
            problems.append(f"YouTube video {vid} ({type(e).__name__})")
        if ch:
            feeds[f"https://www.youtube.com/feeds/videos.xml?channel_id={ch}"] = None
        elif not any(vid in p for p in problems):
            problems.append(f"the channel behind YouTube video {vid}")
    for name, url in BLOGS:
        feeds[url] = name
    for url, name in feeds.items():
        try:
            raw = scan.get_text(url, tries=1)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{name or url} ({type(e).__name__})")
            continue
        who = name or (re.search(r"(?is)<author>\s*<name>(.*?)</name>", raw) or re.search(r"(?is)<title>(.*?)</title>", raw) or [None, "YouTube"])[1]
        who = html.unescape(who).strip()
        for key, title, link, d in feed_entries(raw):
            if d < since or key in seen:
                continue
            seen.add(key)
            if BREWING.search(title):
                out.append({"who": who, "title": title, "link": link, "date": d.isoformat()})
            else:
                other += 1
    state["seen_posts"] = sorted(seen)[-3000:]
    return sorted(out, key=lambda v: v["date"], reverse=True), other


def changed_pages(page, state, problems):
    pages, out = state.setdefault("pages", {}), []
    for label, url in footer_links(page):
        if NOT_PAGES.search(url) or urllib.parse.urlparse(url).path in ("", "/"):   # papers, videos and home pages are not recipe pages
            continue
        try:
            nums = fingerprint(scan._visible(scan.get_text(url, tries=1)))
        except Exception as e:  # noqa: BLE001
            problems.append(f"{label or url} ({type(e).__name__})")
            continue
        if not nums:
            problems.append(f"{label or url} (no brewing numbers readable on the page)")
            continue
        old = pages.get(url)
        if old is not None and old != nums:
            out.append({"label": label, "url": url, "new": [n for n in nums if n not in old][:10], "gone": [n for n in old if n not in nums][:10]})
        pages[url] = nums
    return out


def main():
    today = dt.date.today()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    last = dt.date.fromisoformat(state["last_run"]) if state.get("last_run") else None
    since = max(today - dt.timedelta(days=MAX_LOOK_BACK), (last - dt.timedelta(days=OVERLAP)) if last else today - dt.timedelta(days=FIRST_LOOK_BACK))
    page = (ROOT / "index.html").read_text()
    cited = {m.lower().rstrip(".") for m in re.findall(r'doi\.org/(10\.[^"<\s]+)', page)}
    problems = []
    seen_dois = set(state.get("seen_dois", []))
    papers = new_papers(since, seen_dois, cited, problems)
    videos, other = new_videos(page, since, state, problems)
    first_pages = "pages" not in state
    changes = changed_pages(page, state, problems)
    state["seen_dois"] = sorted(seen_dois | {p["doi"] for p in papers})[-3000:]
    state["last_run"] = today.isoformat()

    L = [f"# Research watch, {day(today)}", "",
         f"Since {day(since)}: {len(papers)} new paper{'s' if len(papers) != 1 else ''}, {len(videos)} new video{'s' if len(videos) != 1 else ''} or post{'s' if len(videos) != 1 else ''} "
         f"about brewing, {len(changes)} cited page{'s' if len(changes) != 1 else ''} with changed numbers. Nothing on the site was changed.", ""]
    if papers:
        L += ["## New papers", ""]
        for p in papers:
            who = (p["authors"][0] + (" et al." if len(p["authors"]) > 1 else "")) if p["authors"] else "Unknown authors"
            when = day(dt.date.fromisoformat(p["date"])) if p["date"] else ""
            L.append(f"- {p['title']}. {who}, {p['journal']}{', ' + when if when else ''}. https://doi.org/{p['doi']}"
                     + (" (from a group the site already cites)" if p["group"] else ""))
        L.append("")
    if videos or other:
        L += ["## New videos and posts", ""]
        for v in videos:
            L.append(f"- {v['who']}: {v['title']}, {day(dt.date.fromisoformat(v['date']))}. {v['link']}")
        if other:
            L.append(f"- Plus {other} other new video{'s' if other != 1 else ''} or post{'s' if other != 1 else ''} whose titles are not about brewing.")
        L.append("")
    if changes:
        L += ["## Cited pages whose numbers changed", ""]
        for c in changes:
            L.append(f"- {c['label']}: " + "; ".join(x for x in ["new on the page: " + ", ".join(c["new"]) if c["new"] else "", "gone: " + ", ".join(c["gone"]) if c["gone"] else ""] if x) + f". {c['url']}")
        L.append("")
    elif first_pages:
        L += ["First run: the brewing numbers on every cited recipe page were recorded, so changes show from the next run.", ""]
    if problems:
        L += ["## Could not check", ""] + [f"- {p}" for p in problems[:25]] + [""]
    DIGEST.write_text("\n".join(L))
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True))
    n = len(papers) + len(videos) + len(changes)
    print("\n".join(L))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"found={n}\ntitle=Research watch, {day(today)}\n")


def selftest():
    ok = [
        keep_paper("Impact of water composition on coffee sensory properties: a comprehensive analysis"),
        keep_paper("Uneven extraction in coffee brewing"),
        keep_paper("Dose and timing effects of caffeine on subsequent sleep: a randomized clinical crossover trial"),
        not keep_paper("Biochar from spent coffee grounds for wastewater treatment"),
        not keep_paper("Coffee consumption and cardiovascular mortality in a prospective cohort"),
        not keep_paper("Coffee leaf rust resistance in Arabica cultivars"),
        not keep_paper("Consumer loyalty in coffee shops"),
        fingerprint("Use 20 g of coffee and 300 ml of water at 95 °C, 1:15, done by 3:30.") == ["1:15", "20g", "300ml", "3:30", "95°c"],
        fingerprint("Use 20g coffee, 300 ml water. 95°C. 1 : 15. 3:30!") == fingerprint("use 20 g  coffee; 300ml; 95 °C; 1:15; about 3:30"),
        footer_links('<ol class="refs"><li>Blue Bottle Coffee. <span class="rt">Chemex brew guide</span>. <a href="https://xyz.example/chemex">xyz</a></li></ol>') == [("Blue Bottle Coffee. Chemex brew guide", "https://xyz.example/chemex")],
        feed_entries("<feed><entry><yt:videoId>abcdefghijk</yt:videoId><title>A new V60 recipe</title><published>2026-11-20T10:00:00+00:00</published></entry></feed>")
        == [("abcdefghijk", "A new V60 recipe", "https://www.youtube.com/watch?v=abcdefghijk", dt.date(2026, 11, 20))],
        feed_entries("<rss><item><title><![CDATA[Pulsar notes]]></title><link>https://xyz.example/p</link><pubDate>Fri, 20 Nov 2026 10:00:00 +0000</pubDate></item></rss>")
        == [("https://xyz.example/p", "Pulsar notes", "https://xyz.example/p", dt.date(2026, 11, 20))],
    ]
    print(f"{sum(ok)} of {len(ok)} checks pass")
    sys.exit(0 if all(ok) else 1)


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()

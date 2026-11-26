"""Safety net for publishing: the folder about to go live must hold the whole site.

Run by the publish workflow on the copy it is about to upload:  python3 scripts/check_build.py /tmp/site
Fails (exit code 1) when something essential is missing, so the publish stops and the site stays as it was
(Cloudflare keeps the last good version) instead of going out broken. This is what would have caught the
coffee pages and sitemap going missing for 15 hours on 25/11/2026.
"""
import json, os, re, sys

site = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
problems = []


def need(cond, what):
    if not cond:
        problems.append(what)


def size(p):
    try:
        return os.path.getsize(os.path.join(site, p))
    except OSError:
        return 0


need(size("index.html") > 50_000, "index.html missing or too small")
need(size("it/index.html") > 50_000, "the Italian page (it/index.html) is missing")
need(size("robots.txt") > 0 and "Sitemap:" in open(os.path.join(site, "robots.txt")).read() if size("robots.txt") else False, "robots.txt missing or without its Sitemap line")
smap = open(os.path.join(site, "sitemap.xml"), encoding="utf-8").read() if size("sitemap.xml") else ""
n_urls = smap.count("<url>")
need(smap.startswith("<?xml") and "<urlset" in smap[:300], "sitemap.xml missing or not a sitemap")
try:
    rel = json.load(open(os.path.join(site, "data", "releases.json"), encoding="utf-8"))
    n_coffees = len(rel.get("releases", []))
except Exception as e:  # noqa: BLE001
    n_coffees = 0
    problems.append(f"data/releases.json unreadable: {e}")
need(n_coffees >= 1000, f"only {n_coffees} coffees in the data")
coffee_pages = sum(1 for root, _, files in os.walk(os.path.join(site, "coffee")) if "index.html" in files)
need(coffee_pages >= 0.8 * n_coffees, f"only {coffee_pages} coffee and roaster pages for {n_coffees} coffees")
need(n_urls >= 0.8 * n_coffees, f"the sitemap lists only {n_urls} addresses for {n_coffees} coffees")
for d in ("functions/api", "fonts", "icons", "img", "list", "privacy"):
    need(os.path.isdir(os.path.join(site, d)), f"folder {d}/ missing")

print(f"Build check: {n_coffees} coffees, {coffee_pages} coffee and roaster pages, {n_urls} sitemap addresses")
if problems:
    for p in problems:
        print(f"::error::{p}")
    sys.exit(1)
print("Build check: everything is there")

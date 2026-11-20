# Goccio

**Live at [www.goccio.co.uk](https://www.goccio.co.uk)**.

New specialty coffees from roasters in the UK, Europe and beyond, read every day from their own shops, each with a recipe for
your brewer and your grinder: grind setting, dose, water, temperature and every step, with a brew-along screen, a journal
that learns, My bags and a bag scanner. No accounts, no tracking, no API keys; everything you save stays on your device.

Everything below is done from GitHub: open the **goccio** repo, tap **Actions**, pick the workflow on the left, then
**Run workflow**. In the GitHub phone app: repo, **Actions**, workflow, **Run workflow**.

## Promote a roaster (paid placement)

A roaster paid to be at the top of the coffee list.

1. **Actions → Promote a roaster → Run workflow.**
2. **Roaster:** the name exactly as on the list (e.g. `Square Mile`). A name that isn't on the list stops the run with an error and nothing changes.
3. **Days:** how long, starting today (e.g. `30`). To end a promotion early, run it again with `stop` here.
4. **Coffees:** how many of their newest coffees go at the top, `1` to `3`.
5. Run it. The site updates by itself about two minutes later.

What visitors see: the roaster's newest coffees first, under a **Paid promotion** heading in the accent colour
(*Promozione a pagamento* in Italian). Only coffees that fit what the visitor has picked (region, process, extras, the
after-14:00 decaf rule); never during a search, on a roaster's own view or with For you on. Several promotions take turns
at the top, in a different order each visit. A promotion ends by itself after its last day.

Where it's kept: `data/promoted.json` (roaster, from, until, coffees). You can also edit that file by hand on GitHub.

## Roasters asking to be listed or removed

The **Get your roastery listed** page (`/list/`) asks for the shop's address and an email, nothing else.

- **Where requests arrive:** each one becomes an issue in this repo (**Issues** tab), labelled `listing`, `removal` or
  `question` (from the privacy page). Only you can see them. To get an email for each, tap **Watch → Custom → Issues**.
- **What happens on its own** (every morning at 04:41 UTC, workflow **Listing requests**):
  - a listing whose email is at the shop's own domain and whose shop the scanner can read is added and the issue closed,
    with a note to reply and to add the roaster's town;
  - a removal whose email is at the shop's own domain takes the shop off the list at once (it goes into `data/removed.json`
    and is never added back unless they ask);
  - anything else (a gmail address, a shop the scanner can't read) stays open with a note for you to check by hand.
- The form needs the `LISTING_TOKEN` secret (Settings → Secrets → Actions), already set.

## New roasters, found automatically

- **New roasters worldwide** (every night at 02:17 UTC, or by hand): looks at roasteries on OpenStreetMap
  (`craft=coffee_roaster` with a website) that aren't on the list, reads up to 40 shops the way the daily scan does, and
  adds the first **10** that sell at least 3 coffees with at least 2 naming their origin. None found: nothing changes.
  Shops already checked are skipped for 120 days (`data/world_seen.json`). Script: `scripts/world.py`.
- **Find new roasters** (by hand): reads the public UK roaster directory and writes candidates for review.

The order of roasters in `data/roasters.json` doesn't matter: the coffee list is sorted by date, and coffees from the
same day take turns by roaster. A newly added roaster doesn't flood the top: its coffees are dated by when its shop listed them.

## Adding or removing a roaster by hand

Add a line to `data/roasters.json`:

```json
{"name": "Roaster Name", "shop": "https://their-shop-domain.co.uk", "city": "Town", "country": "GB", "region": "UK"}
```

`region` is one of `UK`, `Europe`, `North America`, `Asia`, `World`. To remove one, delete its line and add its shop's
domain to `data/removed.json`. After the next scan, `data/releases.json → roasters` shows whether each shop could be read.

## The daily scan

- **Daily roaster scan** (`scripts/scan.py`, `.github/workflows/scan.yml`): reads every roaster's public shop once a
  day (Shopify, WooCommerce, Squarespace, sitemaps), following robots.txt, at least 2 seconds between requests to a shop,
  backing off from any shop that says it's busy. It keeps coffee beans in stock and pulls origin, process, variety, roast
  and tasting notes. Scheduled at 05:31, 07:13 and 09:47 UTC (the later ones skip if the day's scan is in; GitHub often
  runs scheduled jobs late). Run it by hand any time.
- **Run for some roasters only:** Run workflow with `only` = roaster names, comma-separated.
- **Look at one page:** Run workflow with `inspect` = `text:URL` (visible words), `raw:URL` (page source) or a bare URL
  (what the scanner reads off it).
- **Tasting-notes audit:** Run workflow with `inspect` = `audit:60` to see, for 60 roasters whose coffees have no notes,
  what their pages say near words like notes or flavour.
- Every scanner mistake ever reported is a test in `scripts/test_scan.py` (`python3 scripts/test_scan.py`).

## Publishing

**Publish to Cloudflare** runs on every change to the main branch, after every daily scan and after a promotion. It copies
the site, the data, the coffee and roaster pages (`scripts/pages.py`), fonts, icons and images to Cloudflare Pages
(free plan). Run it by hand if the site ever looks out of date.

## Domain

DNS at Spaceship (it stays there, so the Spacemail mailbox for un@goccio.co.uk is untouched):

- `www.goccio.co.uk`: `CNAME` to `v60-auq.pages.dev`, added as a custom domain on the Pages project. This is the site.
- `goccio.co.uk`: Spaceship URL redirect to `https://www.goccio.co.uk`. Cloudflare Pages can serve a bare domain only if
  its DNS moves to Cloudflare, so the bare domain forwards instead.
- `bagtocup.thisisfed.xyz` and `v60.thisisfed.xyz`: `CNAME` to `v60-auq.pages.dev`, still custom domains on the Pages
  project. The pages see the old address and forward to the same page on www.goccio.co.uk (the main page packs the
  visitor's saved data into the link, since browser storage belongs to one address). Keep them attached.
- `CNAME` in the repo holds the main address; `scripts/pages.py` builds the sitemap and links from it.

## Contact

The site's **Email us** links go to un@goccio.co.uk. The address is never written in the pages as text (it's put
together only when someone taps the link), so address-harvesting bots don't find it.

## Credits

Made by Federico R. T. Ferrari. Set in ALT Riviera, with thanks to [Alt Type Foundry](https://alt-tf.com/).

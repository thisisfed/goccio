# V60 Brew Card

**Live at [v60.thisisfed.xyz](https://v60.thisisfed.xyz)**

Type the coffee you're brewing and get a dialled-in Hario V60 recipe: Comandante C40 clicks, dose, water, temperature and every pour, with a brew-along timer. The method is matched to the coffee: James Hoffmann's Better 1-Cup and Ultimate V60, Tetsu Kasuya's 4:6 and 10-Pour, or Scott Rao's bloom & spin.

Below the recipe is **New on UK shelves**: filter coffees (single origins and blends) from UK, European and worldwide roasters, refreshed every Monday.

## How it runs (free)

- **Site:** one static `index.html`, served by Cloudflare Pages (free plan) at v60.thisisfed.xyz. No server, no tracking, no API keys.
- **What gets published:** Cloudflare's build copies only `index.html` and `data/releases.json` into `public/`, so the scanner, roaster list and workflow stay private.
- **Recipes:** worked out in the browser from the coffee's process, roast, variety and the cup style you pick.
- **Roaster scan:** `scripts/scan.py` (Python standard library only) reads each roaster's public shop feed: Shopify's `/products.json` or WooCommerce's Store API. It keeps in-stock coffees roasted for filter or omni (blends are labelled; bundles and subscriptions are skipped), pulls origin, process, variety and tasting notes, and writes `data/releases.json`. A coffee counts as **new** if the shop listed it in the last 21 days.
- **Schedule:** `.github/workflows/scan.yml` runs the scan every Monday at 05:31 UTC and commits the new list. Cloudflare Pages redeploys on its own. Run it any time from **Actions → Weekly roaster scan → Run workflow**.

## Adding a roaster

Add a line to `data/roasters.json`:

```json
{"name": "Roaster Name", "shop": "https://their-shop-domain.co.uk", "city": "Town"}
```

After the next scan, `data/releases.json → roasters` shows whether each shop could be read (`platform`), how many coffees it gave, and any error.

## Custom domain

`CNAME` holds `v60.thisisfed.xyz`. DNS: a `CNAME` record for `v60` pointing to `thisisfed.github.io`.

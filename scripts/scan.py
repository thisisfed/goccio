#!/usr/bin/env python3
"""Daily scan of UK roasters' public shop feeds for single-origin filter coffees.

Free and key-less: most UK specialty roasters run on Shopify, which publishes every
product at /products.json. WooCommerce shops expose /wp-json/wc/store/v1/products.
Anything else is skipped and reported in data/releases.json -> roasters[].

Usage: python3 scripts/scan.py            (writes data/releases.json)
       python3 scripts/scan.py --shard 0/4 --part p0.json   (one quarter of the roasters, saved as a part)
       python3 scripts/scan.py --merge parts/               (the parts put together, writes data/releases.json)
       python3 scripts/scan.py --fixture f.json --shop https://x  (offline parse test)
"""
import html
import json
from concurrent.futures import ThreadPoolExecutor
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import flavours  # noqa: E402  (tasting notes in English)
ROASTERS = ROOT / "data" / "roasters.json"


BANNED = ROOT / "data" / "banned.json"   # shops taken off for not being specialty: {host: {"name", "why", "on"}}. Never scanned, never added back


def host_of(shop):
    return urllib.parse.urlparse(shop or "").netloc.lower().removeprefix("www.")


def banned():
    try:
        return json.loads(BANNED.read_text())
    except (OSError, ValueError):
        return {}


# Specialty only. Two things a specialty roaster's shelf never holds:
# flavoured coffee (said in the name: "Amaretto Flavoured Coffee", "Irish Cream", "Pumpkin Spice"; tasting notes are never read for this,
# they say "caramel flavour" of honest coffees), and robusta (the name or the variety says robusta, canephora or conilon).
FLAVOURED = re.compile(r"\bflavou?red\b|\bflavou?r(?:ed)? coffee\b|\baromatisiert|\baromatizzat|\baromatis[ée]e?s?\b|\birish cream\b|\bpumpkin spice\b"
                       r"|\bamaretto\b|\bfrench vanilla\b|\btoffee nut\b|\bcinnamon bun\b", re.I)
ROBUSTA = re.compile(r"\brobustas?\b|\bcanephora\b|\bconilon\b", re.I)
NO_ROBUSTA = re.compile(r"\b(?:no|without|sans|ohne|senza|zero|0 ?%)\s+robusta|100 ?% arabica", re.I)


def flavoured(name):
    m = FLAVOURED.search(name or "")
    return m.group(0) if m else None


def robusta(name, variety=""):
    v = " ".join(variety) if isinstance(variety, list) else (variety or "")
    for t in (name or "", v):
        if ROBUSTA.search(t) and not NO_ROBUSTA.search(t):
            return True
    return False


def rarely_states(recs):
    """A shop with five or more coffees where fewer than 30% state a process and fewer than 15% a variety: the test that took
    25 roasters off on 23 Nov 2026, now run on every roaster at every scan."""
    n = len(recs)
    if n < 5:
        return False
    return sum(1 for x in recs if x.get("process")) / n < 0.3 and sum(1 for x in recs if x.get("variety")) / n < 0.15


WEAK = ROOT / "data" / "weak.json"   # {host: {"since", "days": [each day it was read and failed rarely_states()]}}; banned at WEAK_DAYS days
WEAK_DAYS = 7                        # a week's grace: a shop that changes its theme can stop being readable for a few days


def specialty_gate(recs, name=""):
    """Why a shop found by the directory or the map is not added (None when it passes). A specialty roaster says where each
    coffee is from and how it was made, sells no flavoured coffee and no robusta, and isn't a tea merchant with a coffee shelf."""
    if re.search(r"\bteas?\b|\btee\b|\bth[ée]s?\b", name or "", re.I):
        return "a tea and coffee merchant by its name"
    for x in recs:
        if flavoured(x.get("name")):
            return f"sells flavoured coffee ({x.get('name')})"
        if robusta(x.get("name"), x.get("variety")):
            return f"sells robusta ({x.get('name')})"
    n = len(recs)
    if n < 3:
        return "fewer than 3 coffees"
    share = lambda k: sum(1 for x in recs if x.get(k)) / n
    if share("origin") < 0.6:
        return f"only {share('origin'):.0%} of its coffees name an origin"
    if share("process") < 0.3 and share("variety") < 0.2:
        return f"its coffees rarely say process ({share('process'):.0%}) or variety ({share('variety'):.0%})"
    return None


def load_roasters():
    """data/roasters.json, forgiving the two slips a hand edit on GitHub makes: a comma after the last roaster,
    and a roaster added twice (the first one stays). A broken file would otherwise stop the whole daily scan."""
    text = re.sub(r",\s*([\]}])", r"\1", ROASTERS.read_text())
    seen, out = set(), []
    for r in json.loads(text):
        key = urllib.parse.urlparse(r.get("shop", "")).netloc.lower().removeprefix("www.") or r.get("name")
        if key in seen:
            print(f"roasters.json: {r.get('name')} is listed twice; the first one is kept")
            continue
        seen.add(key); out.append(r)
    gone = banned()
    return [r for r in out if host_of(r.get("shop")) not in gone]
OUT = ROOT / "data" / "releases.json"
REPORT_FILE = ROOT / "data" / "scan_report.json"   # what the last scan couldn't finish (limits hit), for the morning check and the run page
SEEN = ROOT / "data" / "seen.json"   # when each coffee page was first seen, including ones the list leaves out as duplicates
UA = "Goccio/1.0 (+https://www.goccio.co.uk; once-a-day coffee list, follows robots.txt)"
NEW_DAYS = 21
MAX_ITEMS = 12000   # a safety cap only; the list is ~5,000 coffees
PER_ROASTER = 100   # was 8, which hid most of a big roaster's range

COUNTRIES = ["Ethiopia", "Kenya", "Colombia", "Panama", "Costa Rica", "Guatemala", "El Salvador",
             "Honduras", "Nicaragua", "Peru", "Bolivia", "Ecuador", "Brazil", "Burundi", "Rwanda",
             "Uganda", "Tanzania", "Yemen", "Indonesia", "Sumatra", "Papua New Guinea", "Mexico",
             "China", "Taiwan", "India", "Myanmar", "Thailand", "Vietnam", "DR Congo", "Congo", "Malawi",
             "Zambia", "Jamaica", "Hawaii", "Dominican Republic", "Timor-Leste", "East Timor", "Laos"]
# origin names as roasters abroad write them -> English
GROWING_HOME = {"BR": "Brazil", "CO": "Colombia", "PE": "Peru", "EC": "Ecuador", "BO": "Bolivia", "MX": "Mexico"}
COUNTRY_ALIASES = {
    "Etiopia": "Ethiopia", "Äthiopien": "Ethiopia", "Éthiopie": "Ethiopia", "Ethiopie": "Ethiopia", "Etiopien": "Ethiopia", "Ethiopië": "Ethiopia",
    "Colombie": "Colombia", "Kolumbien": "Colombia", "Kolumbia": "Colombia", "Colombië": "Colombia",
    "Kenia": "Kenya", "Brasile": "Brazil", "Brasilien": "Brazil", "Brésil": "Brazil", "Brasil": "Brazil", "Brazylia": "Brazil",
    "Canastra": "Brazil", "Mantiqueira": "Brazil", "Cerrado Mineiro": "Brazil", "Sul de Minas": "Brazil", "Mogiana": "Brazil",
    "Chapada Diamantina": "Brazil", "Caparaó": "Brazil", "Matas de Minas": "Brazil",
    "Perù": "Peru", "Pérou": "Peru", "Perú": "Peru", "Panamá": "Panama", "Ruanda": "Rwanda", "Messico": "Mexico", "Mexiko": "Mexico",
    "Mexique": "Mexico", "México": "Mexico", "Indonesien": "Indonesia", "Indonésie": "Indonesia", "Équateur": "Ecuador",
    "Ouganda": "Uganda", "Tansania": "Tanzania", "Tanzanie": "Tanzania", "Jemen": "Yemen", "Yémen": "Yemen", "Salvador": "El Salvador",
    "Costa Rica": "Costa Rica", "Burundi": "Burundi", "Guatemala": "Guatemala", "Honduras": "Honduras", "Nicaragua": "Nicaragua",
    "Bolivie": "Bolivia", "Bolivien": "Bolivia", "Cina": "China", "Chine": "China", "Inde": "India", "Indien": "India",
    # Spanish, Polish, Czech, Nordic, Italian spellings seen on shop pages
    "Etiopía": "Ethiopia", "Etiópia": "Ethiopia", "Etiopie": "Ethiopia", "Keňa": "Kenya", "Kolumbie": "Colombia",
    "Kostaryka": "Costa Rica", "Kostarika": "Costa Rica", "Gwatemala": "Guatemala", "Salwador": "El Salvador",
    "Nikaragua": "Nicaragua", "Boliwia": "Bolivia", "Bolívie": "Bolivia", "Ekwador": "Ecuador", "Ekvádor": "Ecuador",
    "Meksyk": "Mexico", "Mexiko": "Mexico", "Indonezja": "Indonesia", "Indonésie": "Indonesia", "Brazílie": "Brazil",
    "Brazilië": "Brazil", "Ruandzie": "Rwanda", "Rwandy": "Rwanda", "Tanzánie": "Tanzania", "Tanzania": "Tanzania",
    "Perù": "Peru", "Honduras": "Honduras", "Jemen": "Yemen", "Kongo": "DR Congo", "Kenija": "Kenya", "Ugandzie": "Uganda",
}

# well-known growing regions that belong to one country only, for pages that name the region but never the country
# (Square Mile's Don Cayito: "from Don Cayito in Dota, Tarrazú"). Names shared with other places (Antigua, Java, Kivu) stay out
# only a last resort: a country named anywhere on the page wins (a Guji variety grown in Nicaragua stays Nicaragua)
REGION_COUNTRY = {
    "Tarrazú": "Costa Rica", "Tarrazu": "Costa Rica", "West Valley": "Costa Rica", "Valle Occidental": "Costa Rica", "Tres Ríos": "Costa Rica", "Brunca": "Costa Rica",
    "Huila": "Colombia", "Nariño": "Colombia", "Narino": "Colombia", "Tolima": "Colombia", "Quindío": "Colombia", "Quindio": "Colombia",
    "Risaralda": "Colombia", "Antioquia": "Colombia",
    "Yirgacheffe": "Ethiopia", "Yirgachefe": "Ethiopia", "Sidama": "Ethiopia", "Sidamo": "Ethiopia", "Guji": "Ethiopia", "Gedeo": "Ethiopia",
    "Bench Maji": "Ethiopia", "West Arsi": "Ethiopia", "Jimma": "Ethiopia", "Harrar": "Ethiopia",
    "Nyeri": "Kenya", "Kirinyaga": "Kenya", "Kiambu": "Kenya", "Murang'a": "Kenya", "Muranga": "Kenya",
    "Huehuetenango": "Guatemala", "Acatenango": "Guatemala", "Atitlán": "Guatemala", "Atitlan": "Guatemala", "Fraijanes": "Guatemala",
    "Boquete": "Panama", "Chiriquí": "Panama", "Chiriqui": "Panama",
    "Cajamarca": "Peru", "Marcala": "Honduras", "Ocotepeque": "Honduras", "Comayagua": "Honduras",
    "Jinotega": "Nicaragua", "Matagalpa": "Nicaragua", "Nueva Segovia": "Nicaragua", "Chiapas": "Mexico", "Oaxaca": "Mexico", "Veracruz": "Mexico",
    "Chalatenango": "El Salvador", "Apaneca": "El Salvador", "Yunnan": "China", "Sumatra": "Indonesia", "Aceh": "Indonesia", "Sulawesi": "Indonesia",
    "Toraja": "Indonesia", "Kayanza": "Burundi", "Ngozi": "Burundi", "Nyamasheke": "Rwanda", "Gakenke": "Rwanda", "Bugisu": "Uganda",
    "Mount Elgon": "Uganda", "Rwenzori": "Uganda", "Kilimanjaro": "Tanzania", "Mbeya": "Tanzania", "Chikmagalur": "India", "Karnataka": "India",
}
SYMBOL = {"GBP": "£", "EUR": "€", "USD": "$", "CAD": "CA$", "AUD": "A$", "NZD": "NZ$", "JPY": "¥", "DKK": " kr", "SEK": " kr", "NOK": " kr",
          "PLN": " zł", "CZK": " Kč", "CHF": "CHF ", "BRL": "R$", "COP": "COL$", "PEN": "S/", "ARS": "AR$", "CLP": "CLP$", "MXN": "MX$"}
COUNTRY_CCY = {"GB": "GBP", "US": "USD", "CA": "CAD", "AU": "AUD", "NZ": "NZD", "JP": "JPY", "DK": "DKK", "SE": "SEK", "NO": "NOK",
               "PL": "PLN", "CZ": "CZK", "CH": "CHF", "CN": "CNY", "HK": "HKD", "TW": "TWD", "KR": "KRW", "SG": "SGD", "MY": "MYR",
               "TH": "THB", "PH": "PHP", "ID": "IDR", "BR": "BRL", "CO": "COP", "PE": "PEN", "AR": "ARS", "CL": "CLP", "EC": "USD",
               "MX": "MXN", "UY": "UYU"}

VARIETIES = ["Gesha", "Geisha", "Sidra", "Pink Bourbon", "Wush Wush", "Eugenioides", "Laurina",
             "Sudan Rume", "SL28", "SL34", "Ruiru 11", "Batian", "Red Bourbon", "Yellow Bourbon",
             "Bourbon", "Typica", "Caturra", "Catuai", "Castillo", "Pacamara", "Maragogype",
             "74110", "74112", "74158", "Heirloom", "Landrace", "Java", "Mokka", "Chiroso",
             "Tabi", "Villa Sarchi", "Parainema", "Marsellesa", "Catimor"]
EXCLUDE = re.compile(r"subscri|abonnement|abbonamento|\babo\b|suscripci|assinatura|\bcurso\b|introdu[cç][aã]o aos|sach[eê]s?\b|c[aá]psulas?|filtro de papel|coador|prenumeration|geschenk|regalo|cadeau|gutschein|"
                     r"\btasse\b|tazza|dip ?style|in-store|xpods?|xbloom|セット|飲み比べ|ドリップバッグ|latte art|\bpen\b|\btool\b|accessor|machine|maker|moccamaster|ticket|party|event|festival|origami|glass|server|carafe|porcelain|ceramic|brewer|filter holder|gift|voucher|capsule|\bpods?\b|nespresso|(?<!\dg )(?<!\d g )coffee bags?|drip bags?|brew bags?|immersion bags?|caf[ée] de poche|"
                     r"h[aå]ndbrygg|presskanne|julepakke|pakken\b|med pegasus|\bswitch\s[–-]|\bnewby\b|steep|equipment|grinder|\bmug\b|kettle|dripper|filter papers?|papers\b|\bcups?\b(?! of excellence)|"
                     r"sampler|tasting pack|taster|bundle|merch|t-?shirt|hoodie|tote|cap\b|"
                     r"cold brew|concentrate|instant|\btea\b|chocolate bar|chocolate\b|kaffeehonig|\bhonig\b|\bchocolat\b|tablettes?\b|tampers?\b|stirring stick|\bwdt\b|dosing (?:ring|cup|funnel)|cascara|"
                     r"workshop|course|\bclass(?:es)?\b|masterclass|training|advent|box\b|\bkit\b|scale\b|aeropress\b(?! recipe)|"
                     r"green (?:beans?|coffee)|råkaffe|rohkaffee|unroasted|\bduo\b|\btrio\b|\bpack\b|\bset\b|selection|collection|wholesale|caf[ée]s?[ -]only|trade[ -]only|\bhoreca\b|food ?service|"
                     r"\b\d+(?:[.,]\d+)?\s?kg\b|\btin\b|longjing|sencha|oolong|rooibos|darjeeling|\bassam\b|earl grey|bai hao|jasmine (?:green|tea|pearl)|"
                     r"sticker|socks?\b|bandana|poster|\binsert\b|screw|basket|portafilter|gasket|spout|tablets?\b|cleaner|\bpin\b|scoop|\bjar\b|"
                     r"\bcake\b|bread\b|sandwich|tumbler|calendar|kalender|shipping\b|postcard|\bpaper\b|filtry|\bfilters\b|\bcards?\b|\bhoney (?:jar|mini)|"
                     r"\b\d{1,2} days of\b|\bavent\b|adventn|julkalender|d[áa]rkov|bal[íi][čc]ek|\bzestaw\b|brelok|abonament|palle med|\bpallets?\b|"
                     r"mousseur|frother|coffee sacks?|jute sack|hessian|\b\d+\s?(?:ks|szt|stk)\b|choklad|\b[čc]aj\b|yunnan green|- greens\b|"
                     r"introduction to coffee|^\d\s?x\s|babygrow|\+ protein|"
                     r"coffee blossom honey|demerara|muscovado|\bjaggery\b|surprise|super jolly|cometeer|\bkony\b|\bphilos\b|we choose|filter cone|\bcone\b|\boffice\b|\bgreen\s*$|\bsample\b|cupping|atelier|d[ée]gustation", re.I)
FILTERY = re.compile(r"\bfilter\b|\bomni\b|pour[- ]?over|\bv60\b|chemex|batch brew|filter roast|\bfiltro\b|\bfiltre\b|"
                     r"filterröst|filterkaffe|handfilter|brew roast", re.I)
ESPRESSO = re.compile(r"\bespresso\b", re.I)
COFFEE_HINT = re.compile(r"single origin|single-origin|altitude|masl|variet|process|tasting notes|"
                         r"flavour notes|flavor notes|producer|washing station|farm|finca|estate|"
                         r"proces\b|vari[eë]teit|hoogte|smaak|producent|boerderij|koffiebonen|"
                         r"fazenda|s[ií]tio|gr[aã]os?\b|torra\b|torrado|tostad[oa]|tueste|grano|variedade?s?|processo|proceso|colheita|cosecha", re.I)
NOTES_RE = re.compile(r"(?:tasting notes|flavour notes|flavor notes|flavour profile|in the cup|tastes like|we taste|cup notes|"
                      r"note di degustazione|note aromatiche|note|geschmacksnoten|geschmack|aromen|notes de dégustation|"
                      r"smaksnoter|smagsnoter|smaksnotater|notas de cata|notas|notes)\s*[:\-–]\s*([^\n.]{3,120})", re.I)
# notes said in a sentence: "Expect notes of pineapple, red apple and hazelnut in a layered, sweet cup"
NOTES_SENT = re.compile(r"(?:notes? of|flavou?rs? of|tastes? of|hints? of|aromas? of|we(?:'re| are)? (?:getting|tasting)|expect(?:ing)?(?! notes)|tasting like)\s+"
                        r"((?:[A-Za-z][\w'’\-]*(?:\s(?!and\b)[A-Za-z][\w'’\-]*){0,2})(?:\s*(?:,|&|\band\b)\s*[A-Za-z][\w'’\-]*(?:\s(?!and\b)[A-Za-z][\w'’\-]*){0,2}){1,5})", re.I)
# a label on a line of its own with the notes on the next ("Tasting notes\nStrawberry, blueberry, nectarine"; Standout)
NOTES_LINE = re.compile(r"(?:tasting notes|flavou?r notes|flavou?r composition|flavou?r descriptions?|cup profile|flavou?r profile|cup(?:ping)? notes|in the cup|smaksnoter|smagsnoter|smaksnotater|geschmacksnoten|"
                        r"notas de cata|note di degustazione|notes de d[ée]gustation)[ \t]*(?:\n|\s{2,})\s*([^\n.]{3,120})", re.I)
# a table row read as one line, label and notes split by a single space ("Tasting notes Citrus, Lemon Peel, White Florals"; Dak).
# The line must be the label and a list and nothing else, so a sentence ("tasting notes of ...", "tasting notes are ...") is never taken.
# Also a bare label ("Notes", "Flavor", "Aroma", "Tastes like") and other languages ("Note de degustare", "NOTES DE DÉGUSTATIONS"),
# with the list split by commas, spaced dashes or bullets ("Fraise - Myrtille - Mûre - Figue"; Tanat, Mabó, Dropshot, Coffea Circulor)
NOTES_CELL = re.compile(r"^[ \t\xa0]*(?:tasting notes|tastes?(?![ \t]+like)|flavou?r notes|flavou?r composition|flavou?r descriptions?|cup profile|flavou?r profile|notes? de d[ée]gustations?|d[ée]gustation|note de degustare|note di degustazione|notas de cata|"
                        r"sensory profile|cup(?:ping)? notes|tastes like|smaksnoter|smagsnoter|smaksnotater|geschmacksnoten|flavou?rs?|aromas?|noten|notes)[ \t\xa0]*:?[ \t\xa0]+"
                        r"(?!(?:of|are|is|include|from|with|that|we|you|and|the|a|an)\b)(?![^\n]*\b(?:coffee|roasters?|roastery|caf[ée])\b)"
                        r"([^\n.:]{3,120}?(?:,|&|\band\b|\s[-–•·]\s|\s?//\s?|\s\|\s)[^\n.:]{2,160}?)[ \t\xa0]*\.?[ \t\xa0]*$", re.I | re.M)
# the same label alone on its line and the list alone on the next ("Notes\nGem de fragi, Mar rosu, Stafide"; Dropshot, Mabó, Inverness)
NOTES_NEXT = re.compile(r"^[ \t\xa0]*(?:tasting notes|tastes?(?![ \t]+like)|flavou?r notes|flavou?r composition|flavou?r descriptions?|cup profile|flavou?r profile|notes? de d[ée]gustations?|d[ée]gustation|note de degustare|note di degustazione|notas de cata|"
                        r"sensory profile|cup(?:ping)? notes|tastes like|smaksnoter|smagsnoter|smaksnotater|geschmacksnoten|flavou?rs?|aromas?|noten|notes)[ \t\xa0]*:?[ \t\xa0]*\n[ \t\xa0]*"
                        r"(?!(?:of|are|is|include|from|with|that|we|you|and|the|a|an)\b)(?![^\n]*\b(?:coffee|roasters?|roastery|caf[ée])\b)"
                        r"([^\n.:]{3,120}?(?:,|&|\band\b|\s[-–•·]\s|\s?//\s?|\s\|\s)[^\n.:]{2,160}?)[ \t\xa0]*$", re.I | re.M)
NOTES_CHECK = 10   # pages read for notes with these rules (10: elbgold's "Noten:" line, Nov 2026); a coffee checked under older rules gets one more read
# A fix for one shop's page layout re-reads only that shop: raise its number here (above NOTES_CHECK), not NOTES_CHECK,
# which re-reads every coffee without notes everywhere (thousands of pages). Raise NOTES_CHECK only for a change to the
# rules every shop goes through
NOTES_RECHECK = {"Climpson & Sons": 10, "Sydrip": 10, "Fève": 10, "Passage": 10, "The Source": 10}   # e.g. {"Monmouth": 10}
notes_ver = lambda shop: max(NOTES_CHECK, NOTES_RECHECK.get(shop, 0))
NOTES_V = 2       # page notes read under these list rules; a short list (two or fewer) read under older ones is read once more


def dot_notes(text):
    """A line of flavours on its own, split by middle dots or bars: 'Strawberry · Blueberry · Nectarine · Passion Fruit · Lavender'
    (Standout). Every part a word or three, no numbers, origin, process or variety, so the line above it
    ('Gibirinna 74110 & Serto 74112 · Anoxic Natural · Ethiopia') is not taken."""
    for line in (text or "").splitlines():
        parts = [x.strip() for x in re.split(r"\s*[·•|]\s*|\s+/\s+", line.strip()) if x.strip()]   # or slashes: 'Apple Crumble / Almond / Brown Sugar' (Square Mile)
        if len(parts) < 3 or len(parts) > 8:
            continue
        if all(re.fullmatch(r"[^\W\d_][^\W\d_'’\- ]*(?:\s[^\W\d_][^\W\d_'’\-]*){0,2}", x) and not find_process(x) and not find_origin(x)
               and not any(v.lower() == x.lower() for v in VARIETIES)
               and not re.search(r"\b(?:filter|espresso|omni|whole ?beans?|ground|roast|light|medium|dark|decaf|organic|fair ?trade|new|limited|"
                                 r"single origin|blend|subscription|gift|home|shop|cart|menu|about|contact|wholesale|coffees?|beans?|products?|collections?|all|equipment|merch)\b", x, re.I) for x in parts):
            return ", ".join(parts)
    return stop_notes(text)


def stop_notes(text):
    """A line of flavours on its own, each closed by a full stop: 'Biela broskyňa. Marhuľa. Šľahačka. Čokoláda.' (Sydrip).
    Three to eight parts of a word or three, and at least half of them flavours we know, so 'Free. Fast. Fresh.' is not taken."""
    import flavours
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.endswith(".") or line.count(".") < 3:
            continue
        parts = [x.strip() for x in line.split(".") if x.strip()]
        if not 3 <= len(parts) <= 8 or not all(re.fullmatch(r"[^\W\d_][^\W\d_'’\- ]*(?:\s[^\W\d_][^\W\d_'’\-]*){0,2}", x) for x in parts):
            continue
        known = sum(1 for x in parts if x.lower() in flavours.PHRASES or all(w in flavours.W for w in x.lower().split()))
        if known * 2 >= len(parts) and not any(find_process(x) or find_origin(x) for x in parts):
            return ", ".join(parts)
    return None


NOTES_TAIL = re.compile(r"\s(?:in|with|for|that|which|on|to|from|giving|making|alongside|plus|throughout|backed|balanced|layered|all|as|when|while)\b.*$", re.I)


def notes_from_text(text):
    """Notes in a sentence ("notes of A, B and C"), the list cut where the sentence moves on ("... in a sweet cup")."""
    for m in NOTES_SENT.finditer(text or ""):
        raw = m.group(1)
        parts = [NOTES_TAIL.sub("", p).strip() for p in re.split(r",|&|\band\b", raw)]
        parts = [p for p in parts if p]
        story = [bool(re.match(r"(?:the|a|an|its|this|their|our|your|his|her|every|each|all|some|more|great|good|nice)\b", p, re.I)) for p in parts]
        if story and story[0]:
            continue   # "hints of the terroir and the farm's history" is a story, not tasting notes
        if True in story:   # "notes of chocolate cherries, strawberry cake, crisp apple and a rich, candy-like sweetness": the list ends where the story starts
            parts = parts[:story.index(True)]
        if len(parts) >= 2:
            return ", ".join(parts)
    return None


DARK = re.compile(r"dark roast|medium[- ]dark|french roast|italian roast", re.I)
# Roast level, in the site's five steps. Read only from a labelled line ("Roast: Light", "Röstgrad: hell"),
# a tag, or an "X roast" phrase in the coffee's own description; never from anywhere on a page.
ROAST_WORDS = [
    ("vlight", r"very[- ]light|ultra[- ]?light|extra[- ]light|super[- ]light|lightest|nordic|bardzo jasn|zeer licht|sehr hell|tr[eè]s clair|molto chiar|muy clar"),
    # medium-light is the light end of medium, not a light roast (Bella Barista's "Roast level: Medium-Light")
    ("medium", r"medium[- ]light|light[- ]medium|light[- ]to[- ]medium|medium[- ]to[- ]light"),
    ("mdark", r"medium[- ]dark|full[- ]city|mittel[- ]?dunkel|moyen[- ]fonc|medio[- ]scur|[sś]rednio[- ]ciemn|halvm[øö]rk"),
    ("dark", r"\bdark|ciemn|donker|dunkel|fonc[ée]|\bscur[ao]|oscur[ao]|m[øö]rk"),
    ("light", r"\blight|\blys\b|\bljus|vaalea|\bhell\b|\bclair|chiar[ao]|jasn|\bclaro|\blicht\b"),
    ("medium", r"\bmedium|\bmittel|\bmoyen|\bmedi[oa]\b|[sś]redni|middels|mellan"),
]
ROAST_LINE = re.compile(r"\b(?:roast(?:ing)?(?: level| degree| profile| colou?r| style)?|röstgrad|röstung|rostning(?:sgrad)?|brenning(?:sgrad)?|"
                        r"risteys(?:aste)?|tostado|tueste|nivel de tueste|torr[ée]faction|tostatura|grado di tostatura|"
                        r"stopie[ńn] palenia|palenie|brandingsgraad|branding)\s*(?::|\n)", re.I)
ROAST_PHRASE = re.compile(r"\b(very[- ]light|ultra[- ]?light|extra[- ]light|nordic(?:[- ]style)?|medium[- ]light|light[- ]medium|light|medium[- ]dark|medium|dark)"
                          r"(?:ly)?[- ]roast(?:ed|s)?\b|\broasted (?:very |ultra[- ]?|extra[- ])?(light|medium|dark)(?:ly|er)?\b|\b(lightly) roasted\b", re.I)


def roast_word(v):
    for key, pat in ROAST_WORDS:
        if re.search(pat, v or "", re.I):
            return key
    return None


def roast_labelled(text):
    """'Roast level: Light' / 'Röstgrad\nhell' -> 'light'."""
    for m in ROAST_LINE.finditer(text or ""):
        # the value line, or the one after a short note ("Roast level\nBased on the Agtron scale\nLight roast")
        lines = [l.strip(" :-–\xa0\t") for l in text[m.end():m.end() + 120].split("\n") if l.strip(" :-–\xa0\t")][:2]
        for line in lines:
            if 0 < len(line) <= 30:
                got = roast_word(line)
                if got:
                    return got
                break
    return None


ROAST_JSON = [re.compile(r'"name"\s*:\s*"(?:roast(?:ing)?(?: level| degree| profile)?|r[öo]stgrad)"\s*,\s*"value"\s*:\s*"([^"]{2,30})"', re.I),
              re.compile(r'"roast[_ -]?(?:level|degree|profile)?"\s*:\s*"([^"]{2,30})"', re.I),
              re.compile(r'"key"\s*:\s*"roast[^"]{0,20}"[^{}]{0,300}?"value"\s*:\s*"([^"]{2,30})"', re.I)]
ROAST_SCALE = re.compile(r'roast(?:ing)?(?: level| degree)?\W{0,4}([1-5])\s?(?:/|of|out of)\s?5\b', re.I)


def roast_from_raw(raw):
    """Roast written in the page's data (schema.org PropertyValue "Roast Level": "Medium", a Shopify metafield
    "roast_level": "Light") or a five-step scale ("Roast level 2/5")."""
    for rx in ROAST_JSON:
        for m in rx.finditer(raw or ""):
            got = roast_word(html.unescape(m.group(1)))
            if got:
                return got
    m = ROAST_SCALE.search(raw or "")
    if m:
        return ["vlight", "light", "medium", "mdark", "dark"][int(m.group(1)) - 1]
    return None


def roast_from_agtron(text):
    """A measured roast colour on the page ("Ground: 119AG", "Agtron 82"): ground readings, Agtron gourmet scale.
    Higher is lighter. Nordic-light filter roasts read 95 and up ground; espresso roasts sit in the 50s and 60s."""
    m = re.search(r"ground\W{0,4}(\d{2,3})\s?(?:AG|agtron)\b", text, re.I) or re.search(r"\bagtron\W{0,12}(\d{2,3})\b", text, re.I)
    if not m:
        return None
    v = int(m.group(1))
    return "vlight" if v >= 95 else "light" if v >= 80 else "medium" if v >= 65 else "mdark" if v >= 50 else "dark"


def find_roast(*texts):
    """Roast level from a labelled line, then an 'X roast' phrase. Two different phrases (a shop offering
    'light or dark roast') give nothing rather than a guess."""
    for t in texts:
        got = roast_labelled(t)
        if got:
            return got
    found = set()
    for t in texts:
        for m in ROAST_PHRASE.finditer(t or ""):
            got = roast_word(next(g for g in m.groups() if g).replace("lightly", "light"))
            if got:
                found.add(got)
    return found.pop() if len(found) == 1 else None
ROAST_LABEL = re.compile(r"(?:roast(?: level| degree)?|tostado|tueste|röstgrad|torréfaction|tostatura)\s*[:\-–]\s*(medium[- ]dark|dark)\b", re.I)
# sold like a bag of beans: a bag weight, a grind/bean option, a process or variety, or a coffee product type.
# Gates the product-page origin look-up, so paper filters and gift cards never get a country from a
# "you may also like" strip.
BAG = re.compile(r"\b(?:100|125|150|200|227|250|300|340|350|454|500)\s?g\b|\b(?:8|10|12|16)\s?oz\b|whole ?beans?|wholebean|hele bønner|"
                 r"en grains?|en grano|grano entero|ganze bohnen?|ziarnist|zrnk|\bmolido\b|ground for|"
                 r"\b(?:washed|natural|honey|anaerobic|lavado|natural|lavé|gewaschen|geisha|gesha|bourbon|caturra|typica|sl28|pacamara)\b|"
                 r"^(?:coffee|café|cafe|kaffe|kaffee|caffè|kawa|káva|filter coffee|single origin)|\b(?:filter|espresso|omni)\s*$", re.I)
# looks like a bag of coffee even when the feed names no country or tasting details
BEANISH = re.compile(r"\b\d{3,4}\s?g\b|whole ?beans?|wholebean|hele bønner|en grains?|grano|ganze bohnen?|ziarn|zrnk|"
                     r"\bfilter\b|\bespresso\b|\bomni\b|coffee|\bcaf[eé]\b|kaffe|kaffee|caff[eè]|\bkawa\b|k[aá]va|kahvi|"
                     r"washed|natural|honey|anaerob|lavado|lavé|gewaschen|geisha|gesha|koffie|bonen|gewassen|natuurlijk", re.I)

# --- "is this a bag of beans?" gate -------------------------------------------------------
# Roasters also sell drinks made from coffee (liqueurs, cans, concentrates). Their pages name an
# origin and a producer, so the origin + "coffee" test alone lets them through. That is how
# "Midnight Oil Decaf Coffee Liqueur 700ml" (Climpson & Sons) got listed. These checks run first.
# Never add "bourbon" here: Bourbon (Pink, Yellow, Red...) is a coffee variety.
# Drinks and food: checked on title and product type only. Tags and body hold tasting notes
# ("rum", "whisky", "wine" are common notes), so they are not searched for these words.
DRINK_WORDS = re.compile(r"liqueur|liquor|likör|licor|liquore|spirits?\b|vodka|\bgin\b|\brum\b|whisk(?:e)?y|brandy|"
                         r"martini|cocktail|\bcha[iï]\b|negroni|\bbeer\b|\bstout\b|\bporter\b|\bwine\b|\bsake\b|kombucha|tonic|sparkling|"
                         r"\brtd\b|ready[- ]to[- ]drink|canned|\bcans?\b|bottled|\bbottles?\b|nitro\b|syrup|sauce|\bpowder\b|"
                         r"ice cream|gelato|cookies?|biscuits?|brownies?|granola|candle|soap\b|\bscrub\b|\bbeverages?\b|\bdrinks?\b|"
                         r"atlas of coffee|\bbooks?\b|\bdiary\b|\bmagazine\b|\bmatcha\b|\bchai\b", re.I)
# a fermentation or barrel step named in a coffee's title is not a drink: strip it before checking
NOT_A_DRINK = re.compile(r"(?:rum|whisk(?:e)?y|bourbon|wine|sake|gin|beer|tequila|mezcal|cognac|brandy|port|sherry)"
                         r"[- ]?(?:barrel|cask|yeast|ferment\w*|infus\w*)(?:[- ]?aged)?", re.I)
# whole-tag matches only (a tag like "alcohol" or "18+" is a category, a tag like "rum" is a note)
DRINK_TAGS = re.compile(r"^(?:alcohol(?:ic)?|spirits?|liqueurs?|drinks?|beverages?|rtd|ready to drink|cans?|"
                        r"18\+|over 18|age[- ]restricted|cocktails?|merchandise|food)$", re.I)
# age gates and alcohol strength anywhere on the page
ALCOHOL_PAGE = re.compile(r"\b\d+(?:[.,]\d+)?\s?%\s?(?:abv|vol|alc)\b|\babv\b|alc\.?\s?/?\s?vol|drink ?aware|drink responsibly|"
                          r"over (?:the age of )?18|aged? 18 or over|must be 18|18\+ only", re.I)
# beans are sold by weight; liquids by volume
WEIGHT = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:g|gr|grams?|kg|kilos?|oz|lbs?)\b", re.I)
VOLUME = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:ml|cl|l|ltr|litres?|liters?|fl ?oz)\b", re.I)


# --- blends and bundles -----------------------------------------------------------------
# Blends are kept (a blend brews fine on a V60) and labelled, so the shelf can say so.
# Bundles, subscriptions, samplers and "roaster's choice" are dropped: they are not one coffee.
# A coffee is labelled a blend when:
#  1. its title, product type or URL slug says blend, house/seasonal/signature roast, half-caff;
#  2. its title or slug joins two producing countries ("Uganda and Brazil", "Brazil & Peru");
#     two countries side by side are not enough: "La Indonesia, Colombia" is a farm, "San Roque
#     Kenya" a variety. A "field blend" is several varieties from one farm. Slugs are read
#     without the query string;
#  3. its page gives a composition: two or more countries with percentages ("60% Brazil, 40% ...");
#  4. its page calls it a blend and the title names no country, unless the page names exactly one
#     country. "A blend of harvests, lots, varieties or producers" describes one origin.
NOT_ONE_COFFEE = re.compile(r"\ball[- ]?\d\b|\b\d\s?x\s?\d{2,3}\s?g\b|roaster'?s[- ]choice|mystery|rotating|subscp?ri|abonnement|"
                            r"taste card|tasting (?:set|box|pack)|sampler|probierset|proefpakket|proefset|discovery (?:set|box|pack)|\bbundle\b|gift (?:set|box)|"
                            # prepaid plans: "Jones Prepaid Weekly 12 months", "Coffee of the Month (6 month Prepaid)",
                            # "Uphill Espresso - 6 months", "Seasonal Special Coffee Plan" ("Plan Vivo" is a coffee)
                            r"pre-?paid|(?<!aged )(?<!rested )\b\d{1,2}\s?months?\b|\bof the month\b|\bcoffee plan\b|"
                            r"\b(?:weekly|fortnightly|monthly|quarterly)\b|assinatura|por m[eê]s|al mes\b", re.I)
BLEND_TITLE = re.compile(r"(?<!field )\bblends?\b|low[- ]caff?\b|house[- ](?:roast|coffee|blend|espresso)|signature[- ](?:roast|blend|coffee)|"
                         r"seasonal[- ](?:filter|espresso|blend|roast)|half[- ]caff|miscela|m[ée]lange|mezcla|mischung", re.I)
# "a blend of harvests / lots / varieties / producers" is still one origin, and so is a "field blend"
_ONE_ORIGIN = r"(?!\s+(?:of\s+)?(?:\w+\s+){0,2}(?:harvests?|lots?|varieties|cultivars|producers|smallholders|farmers|cherr(?:y|ies)|\w+[- ]processed|days?))"
BLEND_BODY = re.compile(r"(?<!field )\b(?:this|our|a|the) blend\b" + _ONE_ORIGIN + r"|(?<!field )\bblend of\b" + _ONE_ORIGIN +
                        r"|\bblended\b|\bcomponents?\b|"
                        r"\bblend(?:s|ing)? (?:together|two|three)\b|\bmix of (?:two|three)\b", re.I)
SINGLE_BODY = re.compile(r"single[- ](?:origin|estate|farm|lot|producer|variety)", re.I)
PCT_ORIGIN = re.compile(r"\b\d{1,3}\s?%\s*(?:of\s+)?([A-Z][a-z]+(?: [A-Z][a-z]+)?)")


_CNAMES = sorted([c for c in COUNTRIES] + list(COUNTRY_ALIASES), key=len, reverse=True)
_CANON = {**{c.lower(): c for c in COUNTRIES}, **{a.lower(): v for a, v in COUNTRY_ALIASES.items()}}
_CALT = "|".join(re.escape(n) for n in _CNAMES)
JOINED = re.compile(r"(?<![\w])(" + _CALT + r")(?![\w])\s*(?:and|&|\+|/|with)\s*(?<![\w])(" + _CALT + r")(?![\w])", re.I)


def joined_countries(text):
    for a, b in JOINED.findall(text or ""):
        ca, cb = _CANON.get(a.lower(), a), _CANON.get(b.lower(), b)
        if ca != cb:
            return f"{ca} and {cb}"
    return None


def countries_in(text):
    found = set()
    for name, canon in [(c, c) for c in COUNTRIES] + list(COUNTRY_ALIASES.items()):
        if re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text or "", re.I):
            found.add(canon)
    return found


def _slug(item):
    return re.sub(r"[-_/]+", " ", (item.get("url") or "").split("?")[0].split("#")[0].rstrip("/").rsplit("/", 1)[-1])


def not_one_coffee(item):
    """Why an item is a bundle / subscription / sampler rather than one coffee, or None."""
    m = NOT_ONE_COFFEE.search(f"{item['title']} {item.get('type') or ''} {_slug(item)}")
    return f"title says '{m.group(0)}'" if m else None


def blend_reason(item):
    """Why a coffee looks like a blend, or None."""
    title, ptype, slug = item["title"], item.get("type") or "", _slug(item)
    m = BLEND_TITLE.search(f"{title} {ptype} {slug}")
    if m:
        return f"title says '{m.group(0)}'"
    j = joined_countries(title) or joined_countries(slug)
    if j:
        return "title names " + j
    body = item.get("body") or ""
    pct = {canon for g in PCT_ORIGIN.findall(body) for canon in countries_in(g)}
    if len(pct) >= 2:
        return "composition " + " / ".join(sorted(pct))
    m = BLEND_BODY.search(body)
    if m and not countries_in(f"{title} {slug}"):
        n = len(countries_in(body))
        if n != 1 and not (SINGLE_BODY.search(body) and n <= 1):
            return f"page says '{m.group(0)}'"
    return None


def blend_origins(item):
    """The producing countries a blend names, in the order they appear."""
    text = f"{item['title']} {_slug(item)}\n{item.get('body') or ''}"
    hits = []
    for name in _CNAMES:
        for m in re.finditer(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text, re.I):
            hits.append((m.start(), _CANON.get(name.lower(), name)))
    out = []
    for _, c in sorted(hits):
        if c not in out:
            out.append(c)
    return out[:4]


def not_beans(item):
    """Why an item is not a bag of coffee beans, or None if it may be one."""
    title, ptype = item["title"], item.get("type") or ""
    head = NOT_A_DRINK.sub(" ", f"{title} {ptype}")
    m = DRINK_WORDS.search(head)
    if m:
        return f"drink/food word '{m.group(0)}'"
    tag = next((t for t in item.get("tags") or [] if DRINK_TAGS.match(str(t).strip())), None)
    if tag:
        return f"tag '{tag}'"
    sold_as = f"{title} {item.get('variants') or ''}"
    if VOLUME.search(sold_as) and not WEIGHT.search(item.get("variants") or ""):
        return f"sold by volume '{VOLUME.search(sold_as).group(0)}'"
    m = ALCOHOL_PAGE.search(f"{title}\n{item.get('body') or ''}")
    if m:
        return f"alcohol page '{m.group(0)}'"
    return None


REJECTED = []   # non-coffee items caught by not_beans(), written to the scan log for review

# ---------- coffee only: a product has to look like a bag of coffee, and nothing on it may look like something else ----------
# Chocolate first: bean-to-bar makers share coffee's words (single origin, Honduras, tasting notes, producer), and coffee
# tasting notes say "milk chocolate" all the time, so only bar-specific wording counts.
# (in the title only, and only unmistakable wording: coffees are called "Cherry Truffle", "Pecan Praline", "Choc Nuts",
# and their notes, which some shops put in the title or product type, say cacao and cocoa)
CHOC_HEAD = re.compile(r"\b\d{2,3}\s?%\s?(?:dark|milk|white|cacao|cocoa|salted|with)\b|bean[- ]to[- ]bar|chocolate bar|hot chocolate|"
                       r"drinking chocolate|\bflakes\b", re.I)
# a cacao product by name, unless the title also says it's a coffee ("Alpha Blend - pomegranate, cacao nibs & caramel")
CACAO_ITEM = re.compile(r"^\W*(?:pure |organic |ceremonial |raw |nibbed\W+)?(?:cacao|cocoa)\b", re.I)
# (only a chocolate maker's words: coffee notes say "cocoa beans" and "milk chocolate bar" too)
CHOC_BODY = re.compile(r"bean[- ]to[- ]bar|cocoa (?:solids|mass|liquor)|cacao (?:content|percentage|solids)|"
                       r"\b\d{2,3}\s?%\s?(?:cocoa|cacao)\b|chocolate ?maker|\bconched\b", re.I)
CHOC_URL = re.compile(r"bean-to-bar|chocolate-bar|hot-chocolate|drinking-chocolate|-\d{2,3}-(?:milk|dark|white)\b", re.I)
# whole categories that are never a bag of beans, as a shop files them (product type or a whole tag)
# the product type only: whole categories a shop files as never a bag of beans
NOT_COFFEE_TYPE = re.compile(r"^(?:chocolates?|cacao|cocoa|confectionery|sweets|snacks?|food|pantry|teas?|herbal|infusions?|"
                             r"equipment|brew(?:ing)? (?:gear|equipment)|accessor(?:y|ies)|gear|kit|merch(?:andise)?|apparel|clothing|"
                             r"homeware|ceramics?|cups?|mugs?|books?|gift cards?|vouchers?|courses?|classes|"
                             r"workshops?|events?|tickets?|grinders?|machines?|spare parts?|cleaning|syrups?|capsules?|pods?|"
                             r"drip ?bags?|instant|cold brew|concentrates?|rtd)$", re.I)
NOT_COFFEE_TITLE = re.compile(r"\bhario\b|decanter|\bcaddy\b|chamomile|dragon pearls|\bsachets?\b|drip[- ]?bags?|\b\d+\s?pcs?\b|"
                              r"\b(?:[2-9]|\d{2,})\s?x\s?\d+(?:[.,]\d+)?\s?(?:kg|g)\b|\bwholesale\b|\bcatering\b", re.I)
# and a bag of coffee says so somewhere: coffee words, brewing words, the farm's processing, coffee varieties, or a coffee bag size
COFFEE_WORDS = re.compile(r"coffee|espresso|\bfilter\b|\bbrew|roast(?:ed|ery|er|ing)?\b|whole ?beans?|wholebean|\bground\b|\bgrind|"
                          r"aeropress|\bv60\b|cafeti[eè]re|french press|\bmoka\b|chemex|\bmasl\b|m\.?a\.?s\.?l|metres above|meters above|"
                          r"washing station|wet mill|dry mill|\bcherr(?:y|ies)\b|parchment|\bsca\b|cup(?:ping)? score|varietal|cultivar|"
                          r"\bsl ?28\b|\bsl ?34\b|bourbon|caturra|typica|gesha|geisha|catua[ií]|castillo|pacamara|heirloom|landrace|"
                          r"\b74\d{3}\b|ruiru|batian|maragogyp|kaffee?|koffie|caf[eé]\b|caff[eè]|\bkawa\b|k[aá]va|kahvi|"
                          r"anaerobic|carbonic|honey process|natural process|washed process|fully washed|semi[- ]washed|wet[- ]hulled|"
                          r"decaf|swiss water|mountain water|sugar ?cane process|\bea\b process", re.I)
COFFEE_BAG = re.compile(r"\b(?:200|225|227|250|300|340|350|454|500|750|1000)\s?g\b|\b(?:1|2)\s?kg\b|\b(?:8|10|12|16)\s?oz\b", re.I)


def not_coffee(item):
    """Why a product isn't coffee at all (chocolate, tea, gear, bulk trade packs), or None."""
    title, ptype = item.get("title") or "", item.get("type") or ""
    tags = [str(t).strip() for t in item.get("tags") or []]
    url = (item.get("url") or "").lower()
    body = item.get("body") or ""
    if NOT_COFFEE_TYPE.match(ptype.strip()):
        return f"product type '{ptype}'"
    # a tea shelf at a tea and coffee merchant: the category says tea and nothing in it or the title says coffee (Smith's "Peppermint")
    if re.search(r"\b(?:teas?|tisanes?|herbal|infusions?)\b", ptype, re.I) and not re.search(r"coffee|espresso|caf[eé]|kaffee|decaf", ptype + " " + title, re.I):
        return f"product type '{ptype[:40]}'"
    if re.search(r"^\s*green\b.{0,60}\b(?:coffee|beans)\b|\bunroasted\b|\bgreen (?:coffee )?beans\b|\braw (?:coffee|beans)\b"
                 r"|^\s*green\s+(?:robusta|arabica|\w+(?:ian|ean|ese|can)\b)|\bcaf[ée]s? verts?\b|\bvert grain\b", title, re.I):   # "Green Brazilian Santos", "Café vert grain"
        return "green, unroasted coffee"
    # (tags aren't used: shops tag coffees "gift", "subscription", "chocolate" or "coffee bags" as filters)
    m = CHOC_HEAD.search(title) or CHOC_URL.search(url.rsplit("/", 1)[-1]) \
        or (None if re.search(r"coffee|espresso|blend|roast|filter", title, re.I) else CACAO_ITEM.search(title))
    if m:
        return f"chocolate '{m.group(0)}'"
    m = CHOC_BODY.search(body)
    if m and not re.search(r"\bcoffee\b|espresso|\bbrew", f"{title} {ptype}", re.I):
        return f"chocolate page '{m.group(0)}'"
    m = NOT_COFFEE_TITLE.search(title)
    if m:
        return f"not a bag of beans '{m.group(0)}'"
    sold = f"{title} {ptype} {' '.join(tags)} {item.get('variants') or ''} {url}"
    # a shop that describes the product at length and never says anything coffee-like isn't selling coffee
    # (a bare feed with no description is left to the page check further on)
    if len(body) > 120 and not (COFFEE_WORDS.search(sold) or COFFEE_WORDS.search(body) or COFFEE_BAG.search(sold) or COFFEE_HINT.search(body)):
        return "no coffee words anywhere"
    return None


def strip_html(s):
    s = re.sub(r"<(br|/p|/li|/h\d|/div)[^>]*>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


# ---------- manners: every request the scanner makes goes through polite() first ----------
# robots.txt is read once per shop and obeyed (Disallow and Crawl-delay, for our name and for *); the same shop is asked
# at most once every HOST_GAP seconds (or its Crawl-delay, if longer); the whole scan at most once every ALL_GAP seconds;
# and a shop that answers 429 (too many requests) or 503 is left alone for the rest of the run
HOST_GAP, ALL_GAP = 2.0, 0.34
UA_TOKEN = "Goccio"
_pace = threading.Lock()
_host_next, _all_next, _robots, _resting = {}, [0.0], {}, set()


class Refused(urllib.error.HTTPError):
    def __init__(self, url, why):
        super().__init__(url, 403, why, None, None)


def _wait_turn(host, gap):
    with _pace:
        now = time.monotonic()
        t = max(now, _host_next.get(host, 0.0), _all_next[0])
        _host_next[host] = t + gap
        _all_next[0] = t + ALL_GAP
    if t > now:
        time.sleep(t - now)


def _robots_for(scheme, host):
    """The shop's robots.txt, parsed once per run; None when it has none (everything allowed)."""
    key = f"{scheme}://{host}"
    if key in _robots:
        return _robots[key]
    rp = None
    try:
        _wait_turn(host, HOST_GAP)
        req = urllib.request.Request(key + "/robots.txt", headers={"User-Agent": UA, "Accept": "text/plain"})
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read(500_000).decode(r.headers.get_content_charset() or "utf-8", "replace")
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(text.splitlines())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):   # a shop that won't even show its robots.txt: treat it as "don't"
            rp = urllib.robotparser.RobotFileParser(); rp.parse(["User-agent: *", "Disallow: /"])
    except Exception:  # noqa: BLE001   no robots.txt reachable: nothing is disallowed
        rp = None
    _robots[key] = rp
    return rp


def polite(url):
    """Wait for this shop's turn, after checking its robots.txt allows the page. Raises Refused when it doesn't."""
    u = urllib.parse.urlsplit(url)
    host = u.netloc.lower()
    if host in _resting:
        raise Refused(url, "this shop asked us to slow down: left alone until tomorrow")
    rp = None if u.path == "/robots.txt" else _robots_for(u.scheme or "https", host)
    if rp is not None and not (rp.can_fetch(UA_TOKEN, url) and rp.can_fetch("*", url)):
        raise Refused(url, "disallowed by robots.txt")
    delay = rp.crawl_delay(UA_TOKEN) or rp.crawl_delay("*") if rp is not None else None
    _wait_turn(host, max(HOST_GAP, float(delay or 0)))


def _rest(url, e):
    if isinstance(e, urllib.error.HTTPError) and e.code in (429, 503) and not isinstance(e, Refused):
        _resting.add(urllib.parse.urlsplit(url).netloc.lower())
        print(f"  {urllib.parse.urlsplit(url).netloc}: answered {e.code}, no more requests to it this run")


def get_json(url, tries=2):
    for i in range(tries):
        try:
            url = urllib.parse.quote(url, safe=":/?&=%#+,;@!$'()*~")   # accented paths (Dayglow) broke the request
            polite(url)
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                ctype = r.headers.get("Content-Type", "")
                body = r.read()
                if "json" not in ctype and not body.lstrip().startswith((b"{", b"[")):
                    raise ValueError("not json")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            _rest(url, e)
            if e.code in (401, 403, 404, 429, 503):
                raise
            if i == tries - 1:
                raise
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(2)


def fetch_shopify(shop, extra=""):
    base = f"{shop}/products.json"
    try:
        get_json(f"{base}?limit=1{extra}")
    except Exception:  # noqa: BLE001
        base = f"{shop}/collections/all/products.json"   # some shops switch off the root list only
    items = _fetch_shopify(shop, base, extra)
    try:
        shelves = shopify_shelves(shop)
    except Exception:  # noqa: BLE001
        shelves = {}
    for it in items:
        it["shelf"] = shelves.get(it["url"].rsplit("/", 1)[-1])
    return items


# --- filter or espresso, in the roaster's own words -------------------------------------------
# Almost every shop sells every bean ground "for filter", so a grind option says nothing about the roast.
# The most reliable signal is where the roaster puts the coffee: its filter / pour-over / omni shelf or
# its espresso shelf (Shopify collections). Text is the fallback when a shop has no such shelves.
FILTER_SHELF = re.compile(r"filter|pour[- ]?over|\bv60\b|\bomni|filtro|filtre|filterkaffe|filterröst|brew(?!ing equipment)|batch", re.I)
ESPRESSO_SHELF = re.compile(r"espresso", re.I)
NOT_COFFEE_SHELF = re.compile(r"equipment|machine|grinder|kit|merch|gift|subscri|wholesale|capsule|pod|accessor|paper", re.I)
ESPRESSO_TEXT = re.compile(r"espresso[- ]roast|roasted (?:specifically |primarily |especially )?for espresso|classic espresso|house espresso|"
                           r"(?:best|ideal|perfect|recommended|great|suited|designed) (?:brew(?:ing)? methods?:?\s*)?(?:for|as|:)\s*(?:an? )?espresso|"
                           r"brew methods?:\s*espresso|crowd[- ]pleasing espresso|(?:id[ée]al|recommand[ée]|parfait|conseill[ée]|pens[ée])e?s? (?:pour|en) (?:l['’])?espresso|(?:our|this) (?:signature |seasonal |house )?espresso\b", re.I)
FILTER_TEXT = re.compile(r"roasted (?:specifically |primarily |especially )?for filter|filter[- ]roast|omni[- ]?roast|\bomni\b|"
                         r"(?:best|ideal|perfect|recommended|great|suited|designed) (?:brew(?:ing)? methods?:?\s*)?(?:for|as|:)\s*(?:pour[- ]?over|filter|v60)|"
                         r"brew methods?:\s*(?:filter|pour)|(?:id[ée]al|recommand[ée]|parfait|conseill[ée]|pens[ée])e?s? (?:pour|en) (?:le |la |les )?(?:filtre|m[ée]thodes? douces|v60|chemex)|m[ée]thodes? douces", re.I)


def shopify_shelves(shop):
    """product handle -> 'filter' | 'espresso' | 'both', from the shop's own coffee collections."""
    cols = get_json(f"{shop}/collections.json?limit=250", tries=1).get("collections", [])
    picks = []
    for c in cols:
        name = f"{c.get('title', '')} {c.get('handle', '')}"
        if NOT_COFFEE_SHELF.search(name) or not c.get("products_count", 1):
            continue
        f, e = bool(FILTER_SHELF.search(name)), bool(ESPRESSO_SHELF.search(name))
        if f != e:   # a shelf that is clearly one or the other ("Filter & Espresso" tells us nothing)
            picks.append((c["handle"], "filter" if f else "espresso"))
    out = {}
    for handle, kind in picks[:10]:
        for page in range(1, 4):
            prods = get_json(f"{shop}/collections/{handle}/products.json?limit=250&page={page}", tries=1).get("products", [])
            for p in prods:
                h = p.get("handle", "")
                out[h] = kind if out.get(h) in (None, kind) else "both"
            if len(prods) < 250:
                break
        time.sleep(.3)
    return out


def roast_for(item):
    """'espresso' when the roaster presents the coffee as an espresso roast, 'filter' when as filter/omni, else None."""
    shelf = item.get("shelf")
    if shelf in ("filter", "both"):
        return "filter"
    if shelf == "espresso":
        return "espresso"
    head = f"{item['title']} {item.get('type', '')} {' '.join(item.get('tags') or [])}"
    body = item.get("body") or ""
    f = FILTER_TEXT.search(body) or re.search(r"\bfilter\b|\bomni\b|pour[- ]?over", f"{item.get('type', '')} {' '.join(item.get('tags') or [])}", re.I) \
        or re.search(r"\bfilt(?:er|re|ro)\b", item["title"], re.I)
    e = ESPRESSO_TEXT.search(body) or re.search(r"\bespresso\b", head, re.I)
    if e and not f:
        return "espresso"
    if f and not e:
        return "filter"
    return None


def _fetch_shopify(shop, base, extra=""):
    items = []
    for page in range(1, 5):
        data = get_json(f"{base}?limit=250&page={page}{extra}")
        prods = data.get("products", [])
        if not prods:
            break
        for p in prods:
            tags = p.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]
            variants = p.get("variants") or []
            prices = [float(v["price"]) for v in variants if v.get("price") not in (None, "")]
            items.append({
                "title": p.get("title", ""),
                "type": p.get("product_type", ""),
                "tags": tags,
                "body": strip_html(p.get("body_html", "")),
                "variants": " / ".join(v.get("title", "") for v in variants),
                "available": any(v.get("available", True) for v in variants) if variants else False,
                "price": min(prices) if prices else None,
                "url": f"{shop}/products/{p.get('handle', '')}",
                "published": (p.get("published_at") or p.get("created_at") or "")[:10],
            })
        if len(prods) < 250:
            break
        time.sleep(1)
    return items


def get_text(url, tries=2, limit=2_000_000):
    for i in range(tries):
        try:
            url = urllib.parse.quote(url, safe=":/?&=%#+,;@!$'()*~")   # accented paths (Dayglow) broke the request
            polite(url)
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"})
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read(limit)
                enc = r.headers.get_content_charset() or "utf-8"
                return raw.decode(enc, "replace")
        except urllib.error.HTTPError as e:
            _rest(url, e)
            if e.code in (401, 403, 404, 410, 429, 503) or i == tries - 1:
                raise
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(2)


# ---------- any other shop: sitemap + schema.org Product data ----------
PRODUCTISH = re.compile(r"/(products?|shop|store|negozio|tienda|boutique|butik|produkte?|produits?|prodotti|coffees?|kaffee|caffe|caffè|cafe|café|kaffe|kahvi|kawa|beans|filter|"
                        r"single-origin|catalog|item|p)/", re.I)
# Squarespace "/shop-coffee/<slug>" (Curve) and PrestaShop "/123-some-coffee.html" (Gardelli)
SHOP_SECTION = re.compile(r"/shop-[\w-]+/[^/]+/?$|/\d+-[\w-]+\.html$", re.I)
SKIP_URL = re.compile(r"/(blog|news|journal|pages?|about|contact|cart|account|collections?|category|categories|tag|"
                      r"wholesale|subscriptions?|gift|equipment|merch)/?$", re.I)


def sitemap_urls(shop):
    """Product-like page URLs with lastmod, newest first. Follows robots.txt and sitemap indexes."""
    cands = []
    try:
        for line in get_text(f"{shop}/robots.txt", tries=1).splitlines():
            if line.lower().startswith("sitemap:"):
                cands.append(line.split(":", 1)[1].strip())
    except Exception:  # noqa: BLE001
        pass
    cands += [f"{shop}/sitemap.xml", f"{shop}/sitemap_index.xml", f"{shop}/product-sitemap.xml", f"{shop}/wp-sitemap.xml",
              f"{shop}/xmlsitemap.php",                                   # BigCommerce (Extract)
              f"{shop}/1_index_sitemap.xml", f"{shop}/1_en_0_sitemap.xml", f"{shop}/1_it_0_sitemap.xml"]   # PrestaShop (Gardelli)
    seen, pages, queue = set(), [], []
    for c in cands:
        if c not in seen:
            seen.add(c); queue.append(c)
    fetched = 0
    while queue and fetched < 8:
        sm = queue.pop(0)
        try:
            xml = get_text(sm, tries=1)
            root = ET.fromstring(xml.encode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            continue
        fetched += 1
        tag = root.tag.split("}")[-1]
        ns = {"s": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
        q = (lambda path: root.findall(path, ns)) if ns else (lambda path: root.findall(path.replace("s:", "")))
        if tag == "sitemapindex":
            kids = [e.text.strip() for e in q(".//s:sitemap/s:loc") if e.text]
            kids.sort(key=lambda u: (0 if re.search(r"product|shop|store|item", u, re.I) else 1))
            for k in kids[:6]:
                if k not in seen:
                    seen.add(k); queue.append(k)
        else:
            from_product_map = bool(re.search(r"product", sm, re.I))
            for u in q(".//s:url"):
                loc = u.find("s:loc", ns) if ns else u.find("loc")
                lm = u.find("s:lastmod", ns) if ns else u.find("lastmod")
                if loc is None or not loc.text:
                    continue
                url = loc.text.strip()
                if SKIP_URL.search(url):
                    continue
                if from_product_map or PRODUCTISH.search(url) or SHOP_SECTION.search(url):
                    pages.append((url, (lm.text or "")[:10] if lm is not None and lm.text else ""))
        if len(pages) > 400:
            break
    uniq = {}
    for u, lm in pages:
        uniq.setdefault(u, lm)
    return sorted(uniq.items(), key=lambda x: x[1], reverse=True)


def ld_products(html_text):
    """schema.org Product objects from every JSON-LD block on a page."""
    out = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_text, re.S | re.I):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except Exception:  # noqa: BLE001
                continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                t = d.get("@type")
                types = t if isinstance(t, list) else [t]
                if any(str(x).lower() in ("product", "productgroup") for x in types):
                    out.append(d)
                for v in d.values():
                    if isinstance(v, (list, dict)):
                        stack.append(v)
            elif isinstance(d, list):
                stack.extend(d)
    return out


def range_title(name, url):
    """Doubleshot names its coffees "Farm • Bule Hora": the range, then the coffee. Cut at the bullet, that left "Farm" three
    times over. When every word after the bullet is in the product's own link (…/ethiopia-bule-hora), that part is the coffee;
    a name followed by tasting notes ("Kenya • blackcurrant") is left alone."""
    m = re.match(r"\s*([^•·]{2,40}?)\s*[•·]\s*([^•·|]{3,60}?)\s*$", name or "")
    if not m:
        return name
    fold = lambda t: unicodedata.normalize("NFD", t.lower()).encode("ascii", "ignore").decode()   # noqa: E731
    slug = re.sub(r"[^a-z0-9]+", " ", fold(urllib.parse.unquote((url or "").rstrip("/").split("/")[-1])))
    words = [w for w in re.split(r"[^a-z0-9]+", fold(m.group(2))) if len(w) >= 3]
    return m.group(2).strip() if words and all(w in slug.split() for w in words) else name


def own_url(stated, page_url):
    """The link a page's product data gives for itself, unless that is just the shop's front page (Doubleshot's data says
    "https://www.doubleshot.cz" on every product): then the page being read is the product's link."""
    if isinstance(stated, str) and urllib.parse.urlparse(stated).path.strip("/"):
        return stated
    return page_url or (stated if isinstance(stated, str) else "")


def ld_to_item(p, url, lastmod):
    offers = p.get("offers") or []
    if isinstance(offers, dict):
        offers = offers.get("offers") if isinstance(offers.get("offers"), list) else [offers]
    offers = [o for o in offers if isinstance(o, dict)] if isinstance(offers, list) else []
    variants = p.get("hasVariant") or []
    for v in variants if isinstance(variants, list) else []:
        o = v.get("offers") if isinstance(v, dict) else None
        if isinstance(o, list):
            offers.extend(x for x in o if isinstance(x, dict))
        if isinstance(o, dict):
            offers.append(o)
    prices, ccy, avail = [], None, False
    for o in offers:
        if not isinstance(o, dict):
            continue
        spec = o.get("priceSpecification") or {}
        if isinstance(spec, list):
            spec = next((x for x in spec if isinstance(x, dict)), {})
        pr = o.get("price") or o.get("lowPrice") or spec.get("price")
        try:
            if pr not in (None, ""):
                prices.append(float(str(pr).replace(",", ".")))
        except ValueError:
            pass
        ccy = ccy or o.get("priceCurrency") or spec.get("priceCurrency")
        a = str(o.get("availability", "InStock"))
        avail = avail or ("InStock" in a or "PreOrder" in a or "LimitedAvailability" in a)
    if not offers:
        avail = True
    cat = p.get("category") or ""
    if isinstance(cat, list):
        cat = " ".join(map(str, cat))
    brand = p.get("brand")
    desc = p.get("description") or ""
    return {"title": html.unescape(str(p.get("name") or "")).strip(), "type": str(cat), "tags": [],
            "body": strip_html(str(desc)), "variants": "", "available": avail,
            "price": min(prices) if prices else None, "currency": ccy, "url": own_url(p.get("url"), url),
            "published": "", "lastmod": lastmod, "brand": brand}


def next_products(page):
    """Headless shops (Next.js / Nuxt): product data sits in an embedded JSON blob, often Shopify Storefront shaped."""
    blobs = []
    for m in re.finditer(r'<script[^>]+id=["\'](?:__NEXT_DATA__|__NUXT_DATA__)["\'][^>]*>(.*?)</script>', page, re.S | re.I):
        blobs.append(m.group(1))
    for m in re.finditer(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', page, re.S):   # Next.js app router stream
        try:
            blobs.append(json.loads('"' + m.group(1) + '"'))
        except Exception:  # noqa: BLE001
            pass
    found = []
    for b in blobs:
        for chunk in [b]:
            try:
                data = json.loads(chunk)
            except Exception:  # noqa: BLE001
                # app-router chunks look like "1a:{...}"; try every JSON object start
                data = None
                for mm in re.finditer(r'\{"', chunk):
                    try:
                        data, _ = json.JSONDecoder().raw_decode(chunk[mm.start():]); break
                    except Exception:  # noqa: BLE001
                        data = None
                if data is None:
                    continue
            stack = [data]
            while stack:
                d = stack.pop()
                if isinstance(d, dict):
                    if d.get("title") and ("descriptionHtml" in d or "description" in d) and ("priceRange" in d or "variants" in d or "handle" in d):
                        found.append(d)
                    stack.extend(v for v in d.values() if isinstance(v, (dict, list)))
                elif isinstance(d, list):
                    stack.extend(d)
    out = []
    for d in found[:1]:
        pr = ((d.get("priceRange") or {}).get("minVariantPrice") or {})
        price, ccy = pr.get("amount"), pr.get("currencyCode")
        if price is None:
            vs = d.get("variants")
            vs = vs.get("edges") or vs.get("nodes") if isinstance(vs, dict) else vs
            for v in vs or []:
                v = v.get("node", v) if isinstance(v, dict) else {}
                p2 = v.get("price")
                if isinstance(p2, dict):
                    price, ccy = p2.get("amount"), p2.get("currencyCode") or ccy
                elif p2 is not None:
                    price = p2
                if price is not None:
                    break
        tags = d.get("tags") or []
        out.append({"@type": "Product", "name": d.get("title"), "description": d.get("descriptionHtml") or d.get("description") or "",
                    "category": " ".join([str(d.get("productType") or "")] + [t for t in tags if isinstance(t, str)]),
                    "offers": {"price": price, "priceCurrency": ccy, "availability": "InStock" if d.get("availableForSale", True) else "OutOfStock"}})
    return out


SEO_TITLE = re.compile(r"\||\bbuy\b|\bonline\b|\bshop\b", re.I)


def heading_if_seo(name, page):
    """Some shops (Nude) give every product the site's SEO title as its name; the page heading has the real one."""
    if not SEO_TITLE.search(name or ""):
        return name
    h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", page, re.I | re.S)
    h1 = html.unescape(re.sub(r"<[^>]+>|\s+", " ", h1.group(1))).strip() if h1 else ""
    return h1 if h1 and len(h1) < 90 and not SEO_TITLE.search(h1) else name


def og_product(page):
    """Fallback for shops that only publish OpenGraph product tags (common on Squarespace and custom sites)."""
    meta = {}
    for m in re.finditer(r'<meta[^>]+(?:property|name)=["\']([^"\']+)["\'][^>]*content=["\']([^"\']*)["\']', page, re.I):
        meta.setdefault(m.group(1).lower(), html.unescape(m.group(2)))
    for m in re.finditer(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']([^"\']+)["\']', page, re.I):
        meta.setdefault(m.group(2).lower(), html.unescape(m.group(1)))
    is_product = meta.get("og:type", "").lower().startswith("product") or "product:price:amount" in meta or "og:price:amount" in meta
    if not is_product or not meta.get("og:title"):
        return []
    meta["og:title"] = heading_if_seo(meta["og:title"], page)
    price = meta.get("product:price:amount") or meta.get("og:price:amount")
    ccy = meta.get("product:price:currency") or meta.get("og:price:currency")
    avail = meta.get("product:availability") or meta.get("og:availability") or "instock"
    return [{"@type": "Product", "name": meta["og:title"], "description": meta.get("og:description") or meta.get("description", ""),
             "offers": {"price": price, "priceCurrency": ccy, "availability": "InStock" if re.search(r"in ?stock|available|preorder", avail, re.I) else "OutOfStock"}}]


def microdata_product(page):
    """schema.org microdata (itemprop="name" / "price" / "availability"), for shops with no JSON-LD: Module's
    WordPress pages sell through Shopify (ShopWP) and only carry these. A bare code name (Module's "M24") gets the
    producer from the page's spec table, so the shelf says which coffee it is."""
    def prop(k):
        m = re.search(r'<meta[^>]+itemprop=["\']' + k + r'["\'][^>]*content=["\']([^"\']*)', page, re.I)
        return html.unescape(m.group(1)).strip() if m else ""
    name = prop("name")
    if not name or not prop("price"):
        return []
    specs = re.findall(r"<p>\s*([^<]{2,40}?)\s*</p>\s*<p[^>]*class=[\"'][^\"']*specs-detail[^\"']*[\"'][^>]*>(.*?)</p>", page, re.S | re.I)
    specs = [(k.strip(), re.sub(r"\s+", " ", strip_html(v)).strip(" ,")) for k, v in specs]
    if len(name) <= 4:
        who = next((v for k, v in specs if re.match(r"producer|farm|estate", k, re.I)), "")
        if who:
            name = f"{name} {who.split('/')[0].strip()}"
    body = prop("description") + "\n" + "\n".join(f"{k}: {v}" for k, v in specs)
    return [{"@type": "Product", "name": name, "description": body,
             "offers": {"price": prop("price"), "priceCurrency": prop("priceCurrency"), "availability": prop("availability") or "InStock"}}]


SPEC_LABELS = r"Country|Origin|Region|Varietals?|Variet(?:y|ies)|Process(?:ing)?|Altitude|Producers?|Farm|Tasting notes|Notes"


def own_heading(page):
    """(match, text) of the coffee's own <h1>: not a cart or menu button ("Close"), and the one the page title repeats when
    there are several (Conscious: three h1s, "Close", the coffee, "Overview", under the title "Shop | Arcangel")."""
    hs = [(m, strip_html(m.group(1)).strip()) for m in re.finditer(r"(?is)<h1[^>]*>(.*?)</h1>", page)]
    hs = [(m, t) for m, t in hs if t and not UI_WORD.match(t)]
    dt = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    dt = strip_html(dt.group(1)).lower() if dt else ""
    return next(((m, t) for m, t in hs if t.lower() in dt), hs[0] if hs else (None, ""))


def price_after(tail):
    """The first real price printed after a heading: never a zero (an empty cart's "$0.00") and never a delivery line."""
    text = re.sub(r"\s+", " ", strip_html(re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", tail)))[:1500]
    for m in re.finditer(r"([£€$])\s?(\d{1,4}(?:[.,]\d{2})?)", text):
        if float(m.group(2).replace(",", ".")) > 0 and not re.search(r"(?:over|above|orders?|shipping|delivery|spend)\W{0,3}$", text[max(0, m.start() - 24):m.start()], re.I):
            return m
    return None


def spec_grid_product(page):
    """Next.js shops that render the product as plain HTML with a spec grid and no product data (Newground):
    <h1>Name</h1>, "One Time Purchase £11.00", then label/value pairs like Country / Colombia, Process / Washed."""
    h1, name = own_heading(page)
    specs = re.findall(r">\s*(" + SPEC_LABELS + r")\s*</div>\s*<div[^>]*>([^<]{1,120})</div>", page, re.I)
    if not h1 or not specs:
        return []
    # the price printed after the coffee's heading; failing that, the first priced element on the page that isn't a zero
    price = price_after(page[h1.end():]) or next((m for m in re.finditer(r"(?:buyingOptPrice|[Pp]rice)[^>]*>\s*([£€$])\s?(\d+(?:[.,]\d{2})?)", page)
                                                  if float(m.group(2).replace(",", ".")) > 0), None)
    cur = {"£": "GBP", "€": "EUR", "$": "USD"}.get(price.group(1)) if price else ""
    body = "\n".join(f"{k}: {html.unescape(v).strip()}" for k, v in specs)
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', page, re.I)
    if m:
        body += "\n" + html.unescape(m.group(1))
    sold = re.search(r">\s*(?:sold out|out of stock)\s*<", page, re.I) and not re.search(r"add to (?:bag|basket|cart)", page, re.I)
    return [{"@type": "Product", "name": name, "description": body,
             "offers": {"price": price.group(2).replace(",", ".") if price else "", "priceCurrency": cur, "availability": "OutOfStock" if sold else "InStock"}}]


def shopify_product_js(url, lastmod, extra=""):
    """Shopify serves every product as JSON at <product url>.js, even when /products.json is off."""
    try:
        p = get_json(url.split("?")[0].rstrip("/") + ".js" + (f"?{extra}" if extra else ""), tries=1)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(p, dict) or not p.get("title"):
        return None
    variants = p.get("variants") or []
    prices = [v["price"] / 100 for v in variants if isinstance(v.get("price"), (int, float))]
    tags = p.get("tags") or []
    return {"title": p.get("title", ""), "type": p.get("type", ""), "tags": tags if isinstance(tags, list) else [tags],
            "body": strip_html(p.get("description", "")), "variants": " / ".join(v.get("title", "") for v in variants),
            "available": bool(p.get("available", True)), "price": min(prices) if prices else (p.get("price", 0) / 100 or None),
            "currency": None, "url": url.split("?")[0], "published": (p.get("published_at") or "")[:10], "lastmod": lastmod, "via": "js"}


DIAG = {}


def listing_urls(shop, lists):
    """Product links read off a shop's own category pages, for shops with no sitemap (Gardelli, on PrestaShop):
    roasters.json names the pages in "list". A product link sits one level under the shop and starts with its id."""
    host = re.escape(shop.split("//", 1)[-1])
    out = []
    for u in lists or []:
        try:
            page = get_text(u, tries=1)
        except Exception:  # noqa: BLE001
            continue
        for m in re.finditer(r'href=["\'](https?://' + host + r'/[a-z0-9-]+/\d+-[a-z][a-z0-9-]+)(?:\.html)?["\'#?]', page, re.I):
            if m.group(1) not in out:
                out.append(m.group(1))
        time.sleep(0.8)
    return [(u, "") for u in out]


LISTED_SPECS = re.compile(r"\b(Variet(?:y|al|ies)|Cultivar|Process(?:ing)?|Terroir|Region|Altitude|Producer|Farm)\b\s*:?\s*([^\n]{2,70})", re.I)


def fetch_generic(shop, max_pages=45, extra="", lists=None):
    items, pages = [], sitemap_urls(shop)
    listed = not pages and bool(lists)
    if listed:
        pages = listing_urls(shop, lists)
    DIAG[shop] = {"sitemap_urls": len(pages), "pages_ok": 0, "pages_blocked": 0, "sample": pages[0][0] if pages else None}
    for url, lm in pages[:max_pages]:
        if "/products/" in url:
            it = shopify_product_js(url, lm, extra)
            if it:
                items.append(it); time.sleep(0.6); continue
        try:
            page = get_text(url + (("&" if "?" in url else "?") + extra if extra else ""), tries=1)
            DIAG[shop]["pages_ok"] += 1
        except Exception:  # noqa: BLE001
            DIAG[shop]["pages_blocked"] += 1
            continue
        prods = ld_products(page)[:1] or next_products(page) or og_product(page) or microdata_product(page) or spec_grid_product(page) or plain_product(page, url)
        for p in prods:
            it = ld_to_item(p, url, lm)
            it["title"] = range_title(heading_if_seo(it["title"], page), url)
            if it["title"]:
                if len(it["body"]) < 60:   # thin JSON-LD: add the page's meta description
                    m = re.search(r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']+)', page, re.I)
                    if m:
                        it["body"] = (it["body"] + "\n" + html.unescape(m.group(1))).strip()
                if listed:   # OpenGraph tags carry no origin details: add the page's own spec lines (Process: …, Variety: …)
                    seen_l = set()
                    for lm2 in LISTED_SPECS.finditer(strip_html(page)):
                        if lm2.group(1).lower() not in seen_l:
                            seen_l.add(lm2.group(1).lower()); it["body"] += f"\n{lm2.group(1)}: {lm2.group(2).strip()}"
                items.append(it)
        time.sleep(0.8)
    return items


PRICE_DIAG = {}


PLAIN_URL = re.compile(r"/(?:product|products|store/p\d+|shop|item)/[^/]+", re.I)
CART_WORDS = re.compile(r"add[\s-]*to[\s-]*(?:cart|basket|bag)|buy now", re.I)


def plain_product(page, url):
    """A product page with no structured data at all (Webflow, Weebly, hand-built shops): the page's own heading,
    the first price shown and the visible text. Only for product-looking URLs on pages with an add-to-cart button."""
    if not PLAIN_URL.search(url) or not CART_WORDS.search(page):
        return []
    body = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", page)
    body = re.sub(r"(?is)<(header|nav|footer)[^>]*>.*?</\1>", " ", body)
    # the coffee's own heading: not a cart or menu button ("Close"), and the one the page title repeats when there are several
    # (Conscious: three h1s, "Close", the coffee, "Overview", under the title "Shop | Arcangel")
    h1, title = own_heading(body)
    if not title:
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', page, re.I)
        title = html.unescape(m.group(1)).strip() if m else ""
    if not title:
        return []
    text = re.sub(r"\s+", " ", strip_html(body))
    # what follows the heading itself, not the first place its words appear (the page title, then the cart and its "$0.00")
    after = re.sub(r"\s+", " ", strip_html(body[h1.end():])) if h1 else (text[text.find(title) + len(title):] if title in text else text)
    pm = next((x for x in re.finditer(r"([£€$])\s?(\d{1,4}(?:[.,]\d{2})?)", after) if float(x.group(2).replace(",", ".")) > 0), None)
    ccy = {"£": "GBP", "€": "EUR", "$": "USD"}.get(pm.group(1)) if pm else None
    i = after.find(title) if title in after else 0
    return [{"name": title, "description": after[:3500], "url": url,
             "offers": [{"price": pm.group(2).replace(",", "."), "priceCurrency": ccy}] if pm else []}]


def _sqs_items(j):
    if isinstance(j.get("item"), dict):
        return [j["item"]]
    return [x for x in (j.get("items") or []) if isinstance(x, dict)]


def fetch_squarespace(shop):
    """Squarespace answers any page with ?format=json: a product page gives its item, a shop page all of them."""
    home = get_text(shop, tries=1, limit=600_000)
    if "squarespace" not in home.lower():
        raise ValueError("not squarespace")
    urls = []
    try:
        sm = get_text(f"{shop}/sitemap.xml", tries=1)
        urls = re.findall(r"<loc>([^<]+)</loc>", sm)
    except Exception:  # noqa: BLE001
        pass
    # shop pages first: one "?format=json" of a shop page lists all its products (Bean Brothers' /coffee-shop sat past
    # the 60th address, behind blog tags), and their product pages are then not needed
    roots = list(dict.fromkeys(m.group(1) for u in urls for m in [re.match(r"(.+)/p/[^/]+/?$", u)] if m))
    shopish = [u for u in urls if u not in roots and re.search(r"shop|store|coffee|beans|kaffe|caf", u, re.I) and "/p/" not in u]
    urls = roots + shopish + [u for u in urls if u not in roots and u not in shopish and not any(u.startswith(r + "/p/") for r in roots)]
    seen, items, tried = set(), [], 0
    for u in urls:
        if tried >= 60 or SKIP_URL.search(u) or re.search(r"/(blog|news|journal|event|events|testimonials?)/", u, re.I):
            continue
        tried += 1
        try:
            j = get_json(u.split("?")[0] + "?format=json", tries=1)
        except Exception:  # noqa: BLE001
            continue
        for it in _sqs_items(j):
            sc = it.get("structuredContent") or {}
            variants = sc.get("variants") if isinstance(sc, dict) else None
            if not variants or it.get("id") in seen:
                continue
            seen.add(it.get("id"))
            prices = []
            for v in variants:
                pm = v.get("salePriceMoney") if v.get("onSale") else v.get("priceMoney")
                try:
                    prices.append(float((pm or {}).get("value")) if pm else float(v.get("price")) / 100)
                except (TypeError, ValueError):
                    pass
            avail = any(v.get("unlimited") or (v.get("qtyInStock") or 0) > 0 for v in variants)
            full = it.get("fullUrl") or ""
            pub = it.get("publishOn") or it.get("addedOn")
            items.append({"title": html.unescape(it.get("title") or ""), "type": " ".join(it.get("categories") or []),
                          "tags": it.get("tags") or [], "body": strip_html((it.get("excerpt") or "") + " " + (it.get("body") or "")),
                          "variants": " / ".join(" ".join(map(str, (v.get("attributes") or {}).values())) for v in variants),
                          "available": avail, "price": min(prices) if prices else None,
                          "currency": ((variants[0].get("priceMoney") or {}).get("currency")),
                          "url": shop + full if full.startswith("/") else full or u,
                          "published": datetime.fromtimestamp(pub / 1000, timezone.utc).date().isoformat() if pub else ""})
        time.sleep(0.4)
    return items


def woo_variation_price(shop, variations):
    """Shops that sell by weight (Monmouth) only price each size: read the sizes, prefer the 250 g bag."""
    best = None
    for v in variations[:6]:
        try:
            d = get_json(f"{shop}/wp-json/wc/store/v1/products/{v.get('id')}", tries=1)
        except Exception:  # noqa: BLE001
            continue
        pr = d.get("prices") or {}
        raw = pr.get("price")
        if raw in (None, "", "0"):
            continue
        val = int(raw) / (10 ** int(pr["currency_minor_unit"] if pr.get("currency_minor_unit") not in (None, "") else 2))
        if val < 1:
            continue
        label = " ".join(str(a.get("value", "")) for a in (v.get("attributes") or [])) + " " + d.get("name", "")
        if re.search(r"\b250\s?g", label, re.I):
            return val
        best = val if best is None else min(best, val)
        time.sleep(.3)
    return best


def fetch_woo(shop):
    items = []
    for page in range(1, 4):
        data = get_json(f"{shop}/wp-json/wc/store/v1/products?per_page=100&page={page}")
        if not isinstance(data, list) or not data:
            break
        for p in data:
            pr = p.get("prices") or {}
            minor = int(pr["currency_minor_unit"] if pr.get("currency_minor_unit") not in (None, "") else 2)
            raw = pr.get("price")
            if raw in (None, "", "0"):   # variable products (sizes) put the price in a range
                raw = (pr.get("price_range") or {}).get("min_amount") or raw
            price = int(raw) / (10 ** minor) if raw not in (None, "", "0") else None
            if price is not None and price < 1:   # a per-gram or sample price, not a bag
                price = None
            if price is None and p.get("variations"):
                price = woo_variation_price(shop, p["variations"])
            prefix = ""
            if price is None:   # last resort: the price line the shop itself shows ("From £3.90" at Monmouth, sold by weight)
                m = re.search(r"([\d]+(?:[.,]\d{1,2})?)</span>", (p.get("price_html") or "").replace("&nbsp;", " "))
                if m:
                    try:
                        price = float(m.group(1).replace(",", "."))
                        prefix = "From " if re.search(r"\bfrom\b", p.get("price_html") or "", re.I) else ""
                    except ValueError:
                        price = None
            if price is None and shop not in PRICE_DIAG and "subscri" not in (p.get("type") or "") and not EXCLUDE.search(p.get("name", "")):
                PRICE_DIAG[shop] = (f"{p.get('name')}: prices={json.dumps(pr)[:260]} type={p.get('type')} variations={json.dumps(p.get('variations'))[:300]} "
                                    f"price_html={(p.get('price_html') or '')[:200]!r}")
            cats = [c.get("name", "") for c in p.get("categories", [])]
            tags = [t.get("name", "") for t in p.get("tags", [])]
            items.append({
                "title": html.unescape(p.get("name", "")),
                "type": " ".join(cats),
                "tags": tags + cats,
                "body": strip_html((p.get("short_description") or "") + "\n" + (p.get("description") or "")),
                # the sizes on sale: the listed price is the cheapest, so it belongs to the smallest bag (Smith's "from £3.20" is 125 g)
                "variants": " / ".join(str(t.get("name", "")) for a in (p.get("attributes") or []) if isinstance(a, dict) for t in (a.get("terms") or []) if isinstance(t, dict)),
                "available": bool(p.get("is_in_stock", True)),
                "price": price,
                "price_prefix": prefix,
                "url": p.get("permalink", ""),
                "published": "",
            })
        if len(data) < 100:
            break
        time.sleep(1)
    return items


def first(pattern_list, text):
    """Earliest whole-word match (so 'China' never matches inside 'Machina', or 'Peru' inside 'Perugia')."""
    best = None
    for w in pattern_list:
        m = re.search(r"(?<![\w])" + re.escape(w) + r"(?![\w])", text or "", re.I)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), w)
    return best[1] if best else None


ORIGIN_LABEL = re.compile(r"(?:origin|country|origine|herkunft|paese|pays|país|ursprung|oprindelse|land)\s*[:\-–]\s*([^\n]{2,60})", re.I)


def count_origin(text):
    """Most-mentioned producing country in a long description (beats a stray mention)."""
    best = (0, None)
    for name, canon in [(c, c) for c in COUNTRIES] + list(COUNTRY_ALIASES.items()):
        n = len(re.findall(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text or "", re.I))
        if n > best[0]:
            best = (n, canon)
    return best[1]


def find_origin(title, blob="", body=""):
    """Title first, then a labelled 'Origin:' line, then tags/categories, then the most-mentioned country."""
    def direct(t):
        o = first(COUNTRIES, t)
        if o:
            return o
        a = first(list(COUNTRY_ALIASES), t)
        return COUNTRY_ALIASES[a] if a else None
    o = direct(title)
    if o:
        return o
    m = ORIGIN_LABEL.search(body or "")
    if m and direct(m.group(1)):
        return direct(m.group(1))
    o = direct(blob) or (count_origin(body) if body else None)
    if o:
        return o
    r = first(list(REGION_COUNTRY), " ".join([title, blob or "", body or ""]))
    return REGION_COUNTRY[r] if r else None


def find_process(text):
    t = text.lower()
    if re.search(r"d[eé]caf|entkoffeiniert|bezkofein", t):
        return "Decaf"
    for pat, name in [(r"anaerobic natural", "Anaerobic natural"), (r"anaerobic washed", "Anaerobic washed"),
                      (r"anaerobic honey", "Anaerobic honey"), (r"carbonic maceration", "Carbonic maceration"),
                      (r"co-?ferment", "Co-fermented"), (r"thermal shock|\bthermic\b", "Thermal shock"),
                      (r"mac[ée]ration carbonique|carbonic", "Carbonic maceration"),
                      (r"yeast|inoculat|\bkoji\b|mosto|\bhefe\b", "Yeast fermented"),
                      (r"anaerobic", "Anaerobic"), (r"double fermentation|double ferment", "Double fermented"),
                      (r"anaerob", "Anaerobic"),
                      (r"\baerobic\b", "Aerobic fermentation"), (r"\bcultur(?:ed|ing)\b", "Yeast fermented"),
                      (r"wet[- ]hull|giling basah", "Wet-hulled"),
                      (r"monsoon(?:ed|ing)", "Monsooned"), (r"semi[- ]washed", "Semi-washed"),
                      (r"\bnatural\b|\bnaturally (?:processed|dried)\b|\bnaturalna\b|\bnature\b(?= mac[ée]ration| process)|dry[- ]process|\bnaturale\b|\bnaturel\b|\bnatur\b|naturlig|\bnatuurlijk|t[øo]rrforedl", "Natural"),
                      (r"\bhoney\b|pulped natural|\bmiel\b|\bhonig\b|\bmiele\b|\bmiodowa\b", "Honey"),
                      (r"\bwashed\b|\b(?:extended|double|fully)[- ]wash(?:ed)?\b|wet[- ]process|\blavato\b|gewaschen|\blavé\b|\blavado\b|tvättad|\bvasket\b|v[åa]tforedl|gewassen|vaskad|\bmyta\b|\bmyt[aey]\b", "Washed")]:
        if re.search(pat, t):
            return name
    return None


# Free text names tasting notes as often as processes ("honey sweetness", "a natural sweetness",
# "honeyed", "notes of honey"), so a description only counts when a sentence is about processing.
PROC_CUE = re.compile(r"process|processed|processing|ferment|dried|drying|depulp|de-pulp|pulped|washing station|"
                      r"verarbeit|aufbereit|procesad|proceso|lavado|lavé|trait|lavorazion|beneficio|mucilage|cherry|cherries|"
                      r"\bwashed\b|anaerob|carbonic|maceration|sun[- ]dried|raised beds|patio|factory|station|yeast", re.I)
NOTE_CUE = re.compile(r"notes?\b|tastes?\b|tasting|flavou?rs?\b|in the cup|cup profile|aroma|hints? of|reminiscent|sweetness|"
                      r"acidity|mouthfeel|finish\b|we (?:get|taste|love)|expect", re.I)


def process_from_text(body):
    """Process from a description: a labelled 'Process:' line first, then a sentence about processing."""
    if not body:
        return None
    got = labelled(body, "process")
    if got:
        return got
    for sent in re.split(r"(?<=[.!?])\s+|\n+", body):
        if PROC_CUE.search(sent) and not NOTE_CUE.search(sent):
            got = find_process(sent)
            if got:
                return got
    return None


# "processed using Giling Basah", "it went through a washed process", "Process - Natural", "honey processing": the process
# word sits right next to "process"/"processed"/"method", so the sentence can talk about flavour too and still be read.
PROC_AFTER = re.compile(r"\bprocess(?:ed|ing)?\b\s*(?:[:\-–|]|\bis\b|\bwas\b|\busing\b|\bby\b|\bwith\b|\bas\b|\bvia\b|\bthrough\b)?\s*(?:(?:the|a|an|their|its|traditional|classic)\s+)?([A-Za-z][\w\-]*(?:\s[\w\-]+){0,2})", re.I)
PROC_BEFORE = re.compile(r"\b([A-Za-z][\w\-]*(?:\s[A-Za-z][\w\-]*)?)\s+(?:process(?:ed|ing)?|method|processing method)\b", re.I)
# words that only ever describe processing, so they count wherever they stand ("a fully washed coffee", "naturally
# processed and slow-dried"); plain "washed" only when it qualifies the coffee ("washed Arabica", "a washed lot")
PROC_STRONG = re.compile(r"\b(fully[- ]washed|double[- ]washed|semi[- ]washed|wet[- ]hulled|giling basah|pulped natural|naturally (?:processed|dried)|"
                         r"sun[- ]dried (?:natural|cherr(?:y|ies))|anaerobic(?:ally)?|carbonic maceration|washed (?:coffee|lot|arabica|beans?|microlot|process))\b", re.I)
NOT_PROC = re.compile(r"brew|filter|espresso|roast|grind|order|payment|cookie|data|checkout|shipping|delivery|decaffeinat|cafeti", re.I)


# a sentence that hedges or compares ("usually natural", "if you enjoy a washed Kenya", "between a washed and a natural")
# says nothing sure about this coffee, so it is skipped; so is one naming two processes ("80% natural and 20% honey")
PROC_HEDGE = re.compile(r"\b(?:usually|often|typically|generally|commonly|traditionally|tend|tends|expect|if you|compared|unlike|than|between|such as|like most|most of|many)\b", re.I)
PAGE_END = re.compile(r"related products|you may also like|you might also like|recently viewed|customers (?:also|who)|frequently bought|more (?:coffees|from)|other products|similar products|súvisiace produkty|související produkty|podobné produkty|mohlo by sa vám páčiť|mohlo by se vám líbit|reviews?\b", re.I)


def process_phrase(text, why=False):
    """A process named right next to the word 'process' (or 'method'), or in words that can only mean a process,
    in a sentence that is sure about this one coffee."""
    text = re.sub(r"(?<=[a-z])(?=[A-Z]{2})", " ", text or "")   # "Fully WashedELEVATION": labels glued together
    for sent in re.split(r"(?<=[.!?])\s+|\n+|\s\|\s(?=[A-Z]{3,})", text):
        found = set()
        for rx in (PROC_AFTER, PROC_BEFORE, PROC_STRONG):
            for m in rx.finditer(sent):
                bit = m.group(1)
                if NOT_PROC.search(bit) or NOT_PROC.search(sent[max(0, m.start() - 30):m.end() + 10]):
                    continue
                got = find_process(bit)
                if got and got != "Decaf":
                    found.add(got)
        plain = {w.lower() for w in re.findall(r"\b(natural|washed|honey)\b", sent, re.I)}   # "80% natural and 20% honey"
        if len(found) == 1 and len(plain) <= 1 and not PROC_HEDGE.search(sent):
            got = found.pop()
            return (got, sent[:200]) if why else got
    return None


def name_at(text, name):
    """Where the product's own words start: its name, but not the copy in the page title (the first line of the text,
    "Pic n Mix | Colombia ... – Apricity Coffee"), which is followed by the whole menu and never the description."""
    low, key = text.lower(), name.lower()[:30]
    i = low.find(key)
    if i < 0:
        return 0
    head = text.find("\n", len(text) - len(text.lstrip()))
    if 0 <= i < head:
        j = low.find(key, head)
        if j >= 0:
            return j
    return i


def page_notes(text, name, meta=""):
    """The shop's notes on the product page: tried from each place the name appears (title, heading, breadcrumb,
    description) so a long menu after the first one doesn't hide them, then the page's description tag."""
    low, key = text.lower(), name.lower()[:30]
    starts = [name_at(text, name)]
    i = low.find(key)
    while i >= 0 and len(starts) < 8:
        if i not in starts:
            starts.append(i)
        i = low.find(key, i + 1)
    for st in starts:
        ns = find_notes({"body": description_window(text, st), "title": name, "tags": []})
        if ns:
            return ns
    # a labelled notes line further down, past an upsell that looks like the end of the product ("Since you are buying
    # this, you might also want…" then "Flavour profile:"; Climpson): only the strict label-and-list rules, so a related
    # product's sentence is never taken
    for st in starts:
        w = text[st:st + 8000]
        for rx in (NOTES_CELL, NOTES_NEXT):
            m = rx.search(w)
            if m:
                ns = find_notes({"body": w[m.start():m.end() + 1], "title": name, "tags": []})
                if ns:
                    return ns
    return find_notes({"body": meta, "title": name, "tags": []}) if meta else []


# notes the page labels only in its markup: a block whose class says tasting notes (Monmouth: <div class="product-details__tasting-notes">
# <ul><li>Guava jam</li>…), so the visible text has the list but no "Tasting notes" word in front of it
NOTES_CLASS = re.compile(r'<(div|ul|ol|section|p|dl)\b[^>]*class=["\'][^"\']*\b(?:[\w-]*?(?:tasting|flavou?r|taste|cup)[-_]?notes?|notes[-_](?:tasting|flavou?r))\b[^"\']*["\'][^>]*>', re.I)
# what a list like that also holds that isn't a flavour: "Lively acidity", "Medium body", "Medium roast", "Long finish"
NOTE_DESCRIPTOR = re.compile(r"\b(?:acidity|body|bodied|roast(?:ed)?|finish|mouthfeel|aftertaste|texture|clean cup|balance[d]?)\b", re.I)


def class_notes(raw, name=""):
    """The tasting notes in a block the page marks with a class (see NOTES_CLASS): the first such block after the coffee's
    name in the markup, its list items (or its lines), descriptors of acidity, body or roast left out."""
    key = html.unescape(name or "").lower()[:30]
    low = html.unescape(raw).lower() if key else ""
    at = low.find(key) if key else -1
    blocks = list(NOTES_CLASS.finditer(raw))
    if not blocks:
        return []
    b = next((m for m in blocks if at < 0 or m.start() >= at - 200), blocks[0])
    tag = b.group(1).lower()
    end = re.search(r"</%s>" % tag, raw[b.end():b.end() + 4000], re.I)
    inner = raw[b.end():b.end() + (end.start() if end else 1500)]
    if tag == "div" and re.search(r"<ul|<ol", inner, re.I):   # the list inside the div: take up to its own end
        e2 = re.search(r"</(?:ul|ol)>", raw[b.end():b.end() + 4000], re.I)
        inner = raw[b.end():b.end() + (e2.end() if e2 else 1500)]
    items = re.findall(r"<li\b[^>]*>(.*?)</li>", inner, re.S | re.I) or re.split(r"<br\s*/?>|\n|,|\s[|/·•]\s", inner)
    out = []
    for it in items:
        t = html.unescape(re.sub(r"<[^>]+>", " ", it))
        t = re.sub(r"\s+", " ", t).strip(" .;:-–—")
        if not t or NOTE_DESCRIPTOR.search(t):
            continue
        n = tidy_note(t)
        if n and n not in out:
            out.append(n)
    return out[:8]


def class_roast(raw):
    """'Medium roast' in the same marked block: the roast level the shop states."""
    b = NOTES_CLASS.search(raw)
    if not b:
        return None
    m = re.search(r"\b(very light|light|medium[- ]dark|medium|dark)[- ]roast", re.sub(r"<[^>]+>", " ", raw[b.end():b.end() + 1500]), re.I)
    return {"very light": "vlight", "light": "light", "medium": "medium", "medium-dark": "mdark", "medium dark": "mdark", "dark": "dark"}.get(m.group(1).lower()) if m else None


def description_window(text, start, size=2500):
    """The product's own words on its page: from its name on, up to the related products or reviews."""
    t = text[start:start + size]
    m = PAGE_END.search(t, 200)
    return t[:m.start()] if m else t


# words that mean a tasting note has run on into the sentence around it ("rounded out by", "followed by the", "lead into")
NOTE_STOP = re.compile(r"(?<![\w-])(?:by|into|onto|the|our|we|you|it|its|it[’']s|is|are|was|were|be|this|that|then|at|of|without|yet|even|simply|due|"
                       r"followed|complement(?:ed|s)?|compliment(?:ed|s)?|soften(?:ed|s)?|lift(?:ed|s)?|round(?:ed|s)?|rounding|organi[sz]ed|"
                       r"characteri[sz]ed|open(?:s|ing)?|before|after|lead(?:s|ing)?|carr(?:y|ies)|unfold(?:s|ing)?|greet(?:s)?|make(?:s)?|give(?:s|n)?|"
                       r"bring(?:s|ing)?|develop(?:s|ing)?|evolv(?:e|es|ing)|leav(?:e|es|ing)|turn(?:s|ing)?)(?![\w-])", re.I)
NOTE_LEAD = re.compile(r"^(?:with\s+)?(?:(?:a|an|some|strong|subtle|delicate|juicy|rich|bright|soft|gentle|lovely|distinct|clear|beautiful|sweet|lingering|pronounced|big|bold|little|slight)\s+)*"
                       r"(?:notes?|hints?|flavou?rs?|tones?|touch(?:es)?|aromas?|accents?|undertones?|twist|splash|dash|whisper|suggestion|layers?|lots|loads|plenty|bursts?|waves?|"
                       r"reminiscent|full|courtesy|zest)\s+of(?:\s+|$)", re.I)
# words that are never a flavour on their own: what's left of a sentence, not a note
NOTE_NOT = re.compile(r"^(?:courtesy|half|now|let|whilst|while|these|those|full|well|gradient|story|compact|orthodox|layers|lots|loads|reminiscent|so|also|"
                      r"here|there|both|each|every|very|much|more|most|less|in the cup|cup|body|round|quality|flavou?r|flavou?rs)$", re.I)


# page markup read as a note: an image's address or srcset ("https://…-1024x717.png 1024w"), a tag ("<svg", "<img"), an attribute ("Class=\"…", "Alt=\"Chocolate")
NOTE_JUNK = re.compile(r"[<>]|=\s*[\"'“”]|https?:|//|\.(?:png|jpe?g|gif|svg|webp|avif)\b|\b\d{2,4}w\b|\bsizes=|\bsrcset\b", re.I)


# a brew guide's headings read as notes ("Ratios, dose, bloom"; The Source): how to brew it, not how it tastes
NOTE_BREW = re.compile(r"^(?:ratios?|brew(?:ing)? ratios?|dos(?:e|es|age)|bloom(?:ing)?|brew(?:ing)? (?:time|guide|method|recipe|temp(?:erature)?)|grind(?: size)?|water(?: temp(?:erature)?)?|"
                       r"temp(?:erature)?|yield|recipe|pours?|time|timings?|method|agitation|filter papers?|"
                       # the brewers a German shop says a coffee suits, and where it ships from: not flavours
                       r"siebtr[äa]ger(?:maschine)?|vollautomat|herdkocher|herdkanne|handfilter|filter(?:kaffee)?maschine|french ?press|pour[- ]?over|aero ?press|kaffeekapseln|kapseln|lungo|"
                       r"direkt vom ursprung|deutschland|germany)$", re.I)


# what a blend is made of, as the shop spells it out: "50% Bookkisa Natural / 50% El Higuerón" (Square Mile's Sweetshop). The same
# words are printed on the bag, often with no roaster's name beside them, so the bag scan can tell whose blend it is
BLEND_PART = re.compile(r"(\d{1,3})\s?%\s+([^\W\d_][^\n/|+%,;:()\d]{2,40}?)\s*(?=/|\||\+|,|;|&|\band\b|\n|$|\d{1,3}\s?%)", re.I)


def blend_parts(text):
    """The parts of a blend when the page gives them with their shares, and the shares add up to the whole: else nothing."""
    for line in re.split(r"[\n.]", text or ""):
        ps = [(int(a), b.strip(" -–")) for a, b in BLEND_PART.findall(line)]
        if len(ps) >= 2 and 95 <= sum(a for a, _ in ps) <= 100 and all(re.search(r"[^\W\d_]{3}", b) and len(b.split()) <= 5 for _, b in ps):
            return [b for _, b in ps]
    return []


# a shop's badge on a product card, read as a note when the next coffee's card follows the label ("New"; Dak's The Alchemist)
NOTE_BADGE = re.compile(r"^(?:new|new in|new arrival|just landed|sold out|out of stock|sale|on sale|best ?seller|limited(?: edition)?|pre-?order|back in stock)$", re.I)


# a piece of a sentence about the coffee, not a flavour: "Perfekt für alle", "die ihren Kaffee vollmundig", "aromatisch lieben" (Röststätte)
NOTE_SENT = re.compile(r"(?:^(?:group|profile)_|vc_column|\bicon\b|^order$|^journal$|^droplets$|^producers$|^farm$|^harvest|additional information|flavou?r series|bryggkaffe|^(?:corp|aciditate|correcta acidez)|koffeinfri|dekaffinert|\bund zeigt|gute fülle|^(?:notes?|noted|finishing|coffee|fun|long|too|old|really|along|combined|coupled|paired|unique|expressive|so expressive|such|mittel|voller|intensives)$|^la que)|\b(?:instagram|facebook|blog|twitter|tiktok|newsletter|jetzt|erleben|convinced|apparent|imagine|create|für|ihren?|ihre|lieben|liebt|perfekt|unsere?[rsn]?|dieser?|dieses|wird|werden|sind|kaffee|viel|wenig|klassisch|blend|perfect for|for those|who loves?|if you like)\b", re.I)


def junk_note(n):
    if NOTE_SENT.search(n or ""):
        return True
    t = (n or "").strip(" .,;:!")
    return bool(NOTE_JUNK.search(n or "")) or bool(NOTE_BREW.match(t)) or bool(NOTE_BADGE.match(t))


def tidy_note(n):
    """One tasting note, without the sentence it was cut from: 'Juicy notes of nectarine' -> 'Nectarine', 'A hint of caramel' -> 'Caramel',
    'Butterscotch followed by' -> 'Butterscotch', 'A caramel finish' -> 'Caramel finish', 'Rounded out by' and 'Hints of' -> '' (dropped)."""
    n = re.sub(r"[\xa0\u2009\u202f\s]+", " ", re.sub(r"[\u200b-\u200d\ufeff]", "", n or "")).strip()   # no-break spaces: "Blood\xa0orange"
    n = re.sub(r"^[^\w\s(\"'“<]+\s*", "", n)   # an emoji in front: "🍫Chocolate" -> "Chocolate"
    n = re.sub(r"^(?:imagine|tasting notes?|notes?|taste|with)\s*:?\s+", "", n, flags=re.I)
    n = re.sub(r"^notes_", "", n, flags=re.I)   # a shop's tag: "Notes_Caramel" -> "Caramel" (York Coffee Emporium)   # "Imagine lollipop!", "Tasting Notes: Plum"
    n = re.sub(r"\s*[(\[][^)\]]*$", "", n)   # an aside the list cut open: "Tropical fruits (pineapple" -> "Tropical fruits"
    n = re.sub(r"\s*!+$", "", n)   # "Lemon cake!" -> "Lemon cake"
    if junk_note(n):
        return ""
    n = n.split("\n")[0].strip(" .;:-–[](){}*•|\"'“”")   # stray brackets and stars too: "Vanilla[" -> "Vanilla"
    if n.isupper() and len(n) > 3:
        n = n.lower()   # shouted notes ("CHERRY YOGURT") read as "Cherry yogurt"
    n = NOTE_LEAD.sub("", n).strip()
    n = re.sub(r"^(?:a|an|the)\s+", "", n, flags=re.I)
    n = re.sub(r"\s+(?:in|im|mit|und|and|with|of|von|de|et)$", "", n, flags=re.I)   # a list cut mid-phrase: "Marzipan in" -> "Marzipan"
    m = NOTE_STOP.search(n)
    if m:
        n = n[:m.start()].strip(" ,.;:-–")
        # what's left before the run-on is a verb or an adverb, not a flavour: "Complemented by", "Beautifully complemented by"
        if len(n.split()) == 1 and re.search(r"(?:ed|ly|ing)$", n, re.I):
            return ""
    if not re.search(r"[^\W\d_]{3,}", n) or len(n.split()) > 4 or NOTE_NOT.match(n):
        return ""
    return n[:1].upper() + n[1:]


NOT_A_NOTE = re.compile(r"\b(?:beans?|whole|ground|grind|espresso|filter|omni|cafeti[eè]re|aeropress|v60|washed|natural|anaerobic|light|medium|dark|small|large|regular|mild|strong|size|decaf\w*|"
                        r"bourbon|gei?sha|caturra|catuai|typica|sl\s?\d+|heirloom|arabica|robusta|organic|fairtrade|blend|single|origin|roast\w*|"
                        r"the|our|this|with|from|for|your|you|is|are|we|new|free|delivery|bag|kg|subscription|gift|limited|edition)\b", re.I)


def first_line_notes(text):
    """A description that opens with nothing but a short list ("Florals, Mandarin, Raspberry", Long & Short) is the tasting
    notes, with no label to say so: two to five commas-apart phrases of one to three words, none of them a grind, a process,
    a variety or ordinary sentence words."""
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    bits = [b.strip(" .") for b in line.split(",")]
    if not (2 <= len(bits) <= 5) or len(line) > 70 or re.search(r"\d|[:;!?]", line):
        return None
    if any(not b or len(b.split()) > 3 or NOT_A_NOTE.search(b) or first(COUNTRIES, b) for b in bits):
        return None
    # with no label, at least half of it must be words a cup is described with: a heading ("Tradition, Handwerk &
    # Temperaturkontrolle", elbgold) is a list of nouns too
    def known(b):
        b = b.strip().lower()
        return bool(FLAVOUR_WORD.search(b)) or b in flavours.W or b in flavours.EN_WORDS or any(w in flavours.W or w in flavours.EN_WORDS for w in b.split()) \
            or flavours.to_english(b).lower() != b
    parts = [p for p in re.split(r",|&", line) if p.strip()]
    if sum(known(p) for p in parts) * 2 < len(parts):
        return None
    return line


# Japanese shops write the cup as a sentence, not a list: 「焼きりんごやレーズンを思わせる、熟度の高い果実感。…キャラメルのような甘さ」
# ("reminiscent of baked apple and raisin … a caramel-like sweetness"). Only the flavours named before を思わせる / のような / の風味 are
# taken, and only words in this list: nothing is guessed from the rest of the sentence.
JA_FLAVOURS = {
    "焼きりんご": "baked apple", "青りんご": "green apple", "りんご": "apple", "リンゴ": "apple", "アップル": "apple", "林檎": "apple",
    "レーズン": "raisin", "ドライフルーツ": "dried fruit", "プルーン": "prune", "デーツ": "date", "いちじく": "fig", "イチジク": "fig",
    "キャラメル": "caramel", "トフィー": "toffee", "黒糖": "brown sugar", "ブラウンシュガー": "brown sugar", "きび砂糖": "cane sugar", "和三盆": "wasanbon sugar",
    "はちみつ": "honey", "ハチミツ": "honey", "蜂蜜": "honey", "メープルシロップ": "maple syrup", "メープル": "maple", "バニラ": "vanilla",
    "ミルクチョコレート": "milk chocolate", "ダークチョコレート": "dark chocolate", "チョコレート": "chocolate", "カカオ": "cacao", "ココア": "cocoa",
    "ヘーゼルナッツ": "hazelnut", "アーモンド": "almond", "くるみ": "walnut", "クルミ": "walnut", "ピーナッツ": "peanut", "ナッツ": "nuts",
    "ブラッドオレンジ": "blood orange", "オレンジ": "orange", "みかん": "mandarin", "ミカン": "mandarin", "グレープフルーツ": "grapefruit", "レモン": "lemon",
    "ライム": "lime", "ゆず": "yuzu", "柚子": "yuzu", "柑橘": "citrus", "シトラス": "citrus", "ベルガモット": "bergamot",
    "ストロベリー": "strawberry", "いちご": "strawberry", "イチゴ": "strawberry", "苺": "strawberry", "ブルーベリー": "blueberry", "ラズベリー": "raspberry",
    "クランベリー": "cranberry", "ブラックベリー": "blackberry", "カシス": "blackcurrant", "ベリー": "berries",
    "アメリカンチェリー": "cherry", "さくらんぼ": "cherry", "チェリー": "cherry", "プラム": "plum", "すもも": "plum", "梅": "ume plum",
    "白桃": "white peach", "黄桃": "yellow peach", "ピーチ": "peach", "桃": "peach", "ネクタリン": "nectarine", "アプリコット": "apricot", "杏": "apricot",
    "マスカット": "muscat grape", "巨峰": "kyoho grape", "ぶどう": "grape", "ブドウ": "grape", "葡萄": "grape", "グレープ": "grape",
    "洋梨": "pear", "洋ナシ": "pear", "梨": "pear", "メロン": "melon", "ライチ": "lychee",
    "トロピカルフルーツ": "tropical fruit", "マンゴー": "mango", "パイナップル": "pineapple", "パッションフルーツ": "passion fruit", "グァバ": "guava",
    "グアバ": "guava", "パパイヤ": "papaya", "ココナッツ": "coconut", "バナナ": "banana",
    "赤ワイン": "red wine", "白ワイン": "white wine", "ワイン": "wine", "ラム酒": "rum", "ウイスキー": "whisky", "ブランデー": "brandy",
    "ジャスミン": "jasmine", "フローラル": "floral", "花": "flowers", "ラベンダー": "lavender", "ローズ": "rose", "バラ": "rose",
    "アールグレイ": "earl grey", "紅茶": "black tea", "緑茶": "green tea", "ほうじ茶": "roasted green tea", "ハーブ": "herbs",
    "シナモン": "cinnamon", "スパイス": "spice", "バター": "butter", "クリーム": "cream", "ヨーグルト": "yoghurt", "ミルク": "milk",
}
_JA_KEYS = sorted(JA_FLAVOURS, key=len, reverse=True)
JA_CUE = re.compile(r"([^。、！？\n]{1,40}?)(?:を思わせる|を感じさせる|を連想させる|のような|の(?:風味|フレーバー|香り|ニュアンス|甘さ|酸味|甘み|余韻))")


def ja_notes(text):
    """Flavours a Japanese description names in a sentence, in English, in the order written (see JA_FLAVOURS), or None."""
    if not re.search(r"[\u3040-\u30ff]", text or ""):
        return None
    out = []
    for m in JA_CUE.finditer(text):
        for part in re.split(r"[や・と&＆/／]|および|そして", m.group(1)):
            part = part.strip()
            k = next((k for k in _JA_KEYS if part.endswith(k)), None)   # the flavour is the last word before the cue: 熟した桃 -> 桃
            if k and JA_FLAVOURS[k] not in out:
                out.append(JA_FLAVOURS[k])
    return ", ".join(out) if out else None


# a labelled sentence: one quality, then the flavours ("Taste notes: Buttery with creamy notes of chocolate Santas and ripe juicy plum"; Morgon)
NOTES_WITH = re.compile(r"^[ \t\xa0]*(?:taste|tasting|flavou?r) notes[ \t\xa0]*:[ \t\xa0]*([A-Za-z][\w'’ -]{2,30}?)[ \t]+with[ \t]+(?:[\w-]+[ \t]+){0,2}notes of[ \t]+([^\n.:]{3,120}?)[ \t\xa0.]*$", re.I | re.M)


def find_notes(item):
    text = item["body"]
    # a bracketed heading with the list under it: "【Taste Note】" then "Almond, Red apple, Orange, Plum, Clean" (Passage)
    text = re.sub(r"[【\[]\s*(?:taste|tasting|flavou?r|cup)\s+notes?\s*[】\]][ \t\xa0]*\n\s*", "Tasting notes: ", text, flags=re.I)
    cands = [m.group(1) for m in (rx.search(text) for rx in (NOTES_CELL, NOTES_NEXT, NOTES_RE, NOTES_LINE)) if m]   # a line that is only the label and its list is the surest
    w = NOTES_WITH.search(text)
    if w:   # "Buttery with creamy notes of A and B" inside a labelled line reads best as the with-list; elsewhere (a recipe step) it comes last
        wl = "%s, %s" % (w.group(1), re.sub(r"\s+and\s+", ", ", w.group(2)))
        if any(w.group(1) in c for c in cands) or not cands:
            cands.insert(0, wl)
        else:
            cands.append(wl)
    if len(cands) > 1 and not item.get("_one"):   # the first that gives a list wins; a labelled line that gives nothing doesn't hide the next one
        for c in cands:
            got = find_notes({**item, "body": "Tasting notes: " + c.strip() + "\n", "_one": True})
            if got:
                return got
    raw = cands[0] if cands else None
    if not raw:
        raw = dot_notes(text)
    if not raw:
        raw = notes_from_text(text)
    if not raw:
        raw = first_line_notes(text)
    if not raw:
        raw = ja_notes(text)
    if not raw:
        # "Name - Country - Note, Note, Note" style titles
        parts = re.split(r"\s[-–|]\s", item["title"])
        if len(parts) >= 3 and "," in parts[-1]:
            raw = parts[-1]
    if not raw:
        for t in item["tags"]:
            mm = re.match(r"(?:notes?|flavou?r)[:_ ](.+)", t, re.I)
            if mm:
                raw = (raw + ", " if raw else "") + mm.group(1)
    if not raw:
        return []
    # notes for each brew: "Strawberry, Holunder (Filter); Kirsche, Peach, Blütenhonig (Espresso)" (Hoppenworth & Ploch). Goccio is filter, so the filter list
    mf = re.search(r"^(.*?)\(\s*filter\s*\)", raw, re.I | re.S)
    if mf and mf.group(1).strip(" ,;"):
        raw = mf.group(1)
    raw = re.sub(r"\(\s*(?:filter|espresso|omni)\b\s*\)?", " ", raw, flags=re.I).replace("\xa0", " ")
    raw = re.split(r"\s(?:[A-Z][\w]+(?:\s[a-z]+)?):\s", raw)[0]   # "Lychee • Peach • Candied Cherry Roast: Omni — …": the list ends at the next label
    if re.search(r" [-–] ", raw) and "," in raw:   # a dash list ends at a comma: "Fraise - Myrtille - Figue Direction le Panama, à la…" (Tanat)
        raw = raw.split(",")[0]
        ds = [x.strip() for x in re.split(r" [-–] ", raw)]
        if len(ds) >= 3 and all(len(x.split()) == 1 for x in ds[:-1]) and len(ds[-1].split()) > 2:
            ds[-1] = ds[-1].split()[0]   # single-word notes, then the sentence runs on: keep the note
        raw = " - ".join(ds)
    # and the word for "and" in the shop's language, once the line is already a comma list: "Té verde, manzanilla, fruta de la pasión y kiwi amarillo" (Harmony)
    bits = re.split(r",|&|\band\b|/|·|•|\|| [-–] " + (r"|\s(?:y|e|et|und|och|og|ja|i)\s" if "," in raw else ""), raw)
    out = []
    for b in bits:
        b = b.strip(" .;:-–").strip()
        if (2 <= len(b) <= 28 and len(b.split()) <= 4 and ":" not in b
                and not re.search(r"\d|masl|process|altitude|score|perfect|sharing|recommend|brew", b, re.I)
                and not first(COUNTRIES, b) and not first(list(COUNTRY_ALIASES), b)):
            b = tidy_note(b)
            if b and b.lower() not in (o.lower() for o in out):
                out.append(b)
    return out[:8]   # every note the shop lists, up to eight (Fève lists six)


BEANS_PREFIX = re.compile(r"^\s*(?:kaffeb[øo]nner|kaffeb[öo]nor|kaffeebohnen|koffiebonen|coffee beans|caf[ée] en grains?|caff[èe] in grani)\s+(?=\S)", re.I)
FROM_TAIL = re.compile(r"\s+(?:fra|från|from|aus|von|uit)(?:\s+(\S+))?\s*$", re.I)


NAME_SMALL = {"de", "del", "da", "do", "di", "of", "the", "and", "y", "e", "et", "en", "van", "von"}


def cap_name(name):
    """A name the shop writes all in small letters reads as a name: 'la planta natural sidra' -> 'La Planta Natural Sidra',
    'thermal shock orange gesha C-13' -> 'Thermal Shock Orange Gesha C-13'. Names with capitals of their own are left alone."""
    if not name or not name[0].isalpha() or not name[0].islower():
        return name
    ws = name.split(" ")
    if any(w[:1].isupper() and w[1:].islower() for w in ws):   # some words are capitalised: the shop chose the others
        return name[:1].upper() + name[1:]
    return " ".join(w if (i and w in NAME_SMALL) or not w.islower() else w[:1].upper() + w[1:] for i, w in enumerate(ws))


def clean_name(title, roaster, origin):
    return cap_name(clean_name_raw(title, roaster, origin))


def clean_name_raw(title, roaster, origin):
    """The coffee's own name. The shop's wording round it goes: "Kaffebønner Klassisk Julekaffe fra Guatemala" (Kaffa: "coffee
    beans … from Guatemala") is "Klassisk Julekaffe"; "Kaffebønner Etiopia Danche" is "Danche"."""
    t = html.unescape(title)
    name = _clean_name(BEANS_PREFIX.sub("", t), roaster, origin)
    if not BEANS_PREFIX.match(t):
        return name   # only a shop that words its titles this way gets the rest
    m = FROM_TAIL.search(name)   # "… fra" left hanging once the origin went, or "… fra Etiopia" in the shop's own language
    if m and (not m.group(1) or (origin and find_origin(m.group(1)) == origin)) and name[:m.start()].strip():
        name = name[:m.start()].strip()
    first, _, rest = name.partition(" ")   # the origin in front: "Etiopia Danche", "Brasil Fazenda IP", "Kenya Kagere"
    if rest and origin and find_origin(first) == origin and not find_origin(rest):
        name = rest.strip()
    return name


def _clean_name(title, roaster, origin):
    title = re.sub(r"<br\s*/?>", " ", html.unescape(title), flags=re.I)
    title = re.sub(r"<[^>]+>", "", title)
    title = re.sub(r"^\s*\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}\s*[~〜～]\s*", "", title)   # Philocoffea: "11/16 10:00~" release stamp
    title = re.sub(r"\s*/\s*$", "", title)   # Fuglen Tokyo: "Arbegona /"
    title = re.sub(r"\s*\{(?:filter|espresso|blend|omni)\}\s*$", "", title, flags=re.I)   # People Possession: "Abu [Catuai 3125]{Filter}"
    title = re.sub(r"\s*\(\s*\d+\s?(?:g|gr|kg)\b[^)]*\)\s*$", "", title, flags=re.I)   # Pergamino: "Lomaverde (500g coffee bag)"
    m = re.match(r"^\s*\d{3}\s+(\S.*)$", title)   # Philocoffea: "467 Ethiopia Bombe Washed", a lot number in front of the origin
    if m and (find_origin(m.group(1)[:25]) or re.match(r"[A-Z]", m.group(1))):
        title = m.group(1)
    title = re.sub(r"\s{2,}", " ", title).strip()
    title = re.sub(r"\s*[•·]\s*$", "", title)
    # a shop tag on the front: "【NEW】Panama Lost Origin", "[NEW] …", "NEWPanama …" -> "Panama Lost Origin"
    title = re.sub(r"^\s*[【\[(（]\s*(?:NEW|New|SOLD OUT|LIMITED|新作|新入荷|限定)\s*[】\])）]\s*", "", title)
    title = re.sub(r"^\s*(?:NEW|SOLD OUT|LIMITED)\s*[!:|\-–]?\s*(?=[A-Z])", "", title)
    if "•" in title and title.split("•")[0].strip():
        title = title.split("•")[0].strip()
    # "Curve Coffee Roasters - FEATURE FILTER | El Silencio" -> drop the shop's own brand prefix first,
    # otherwise every Curve coffee is named "Curve Coffee Roasters" and de-duplicates down to one
    name = re.sub(r"^" + re.escape(roaster) + r"[\w\s&']*?\s[-–|:]\s*", "", title, flags=re.I)
    name = re.sub(r"^[^-–|]*\b(?:coffee )?roast(?:ers?|ery)\s[-–|:]\s*", "", name, flags=re.I)
    name = re.sub(r"^(?:feature|house|community|guest)\s+(?:filter|espresso)\s*[|:–-]\s*", "", name, flags=re.I)
    name = re.sub(r"^(filter|filtro|filtre|espresso|omni)\s*[-–:|/]\s*", "", name, flags=re.I)
    name = re.sub(r"^\s*(?:\d{2,4}(?:/\d{2,4})?\s+)?new (?:season|crop)\b\s*[-–—:|]?\s*", "", name, flags=re.I)   # Big Sur: "26/27 New Season - …"
    name = re.sub(r"\s*[-–|(]\s*(filter|filtro|filtre|omni)( roast| röst)?\)?\s*$", "", name, flags=re.I)
    parts = re.split(r"\s[-–|]\s", name)
    if len(parts) >= 3:
        # "LIMITED | EL SALVADOR | La Siberia | Java | Natural" -> "La Siberia" (origin, variety and process show as tags)
        def plain(p):
            q = p.strip()
            return not (GENERIC_SEG.match(q) or is_brand(q, roaster) or (find_origin(q) and len(q) <= len(find_origin(q)) + 1)
                        or find_process(q) and len(q) < 30 and not re.search(r"\b(?:finca|farm|estate|hacienda|fazenda)\b", q, re.I)
                        or any(q.lower() == v.lower() for v in VARIETIES))
        name = next((p for p in parts if plain(p)), parts[0])
        if len(re.sub(r"[^A-Za-z]", "", name)) < 4:     # "COLOMBIA | EA | Castillo | Decaf" -> "Colombia EA"
            o = next((p for p in parts if find_origin(p)), "")
            name = f"{o} {name}".strip()
    elif len(parts) == 2 and re.fullmatch(r"\s*[A-Za-z]+ & [A-Za-z]+\s*", parts[0]) and find_origin(parts[1]):
        name = parts[1].strip()     # Kaffa Roastery: "Fruity & Floral - Nicaragua Santa Isabel", the shop's flavour style first
    elif len(parts) == 2 and find_origin(parts[1]):
        name = parts[0]
    elif len(parts) == 2 and find_origin(parts[0]) and len(parts[0]) <= len(find_origin(parts[0])) + 2:
        name = parts[1]     # "Colombie - Penas Blancas" -> "Penas Blancas" (the origin is a tag)
    elif len(parts) == 2 and " | " in name:
        # "Impact Espresso | Well Grounded" -> "Impact Espresso"; "Kenya | Gichathaini" -> "Gichathaini"
        a, b = parts
        name = b if find_origin(a) and len(a) <= len(find_origin(a)) + 1 else a
    # "Colombia / Divino Nino" -> "Divino Nino" (the country is already a tag)
    m = re.match(r"^\s*([^/]{3,30}?)\s+/\s+(\S.*)$", name)
    if m and find_origin(m.group(1)) and len(m.group(1)) <= len(find_origin(m.group(1))) + 1 and not find_origin(m.group(2).split()[0]):
        name = m.group(2)
    name = re.sub(r"\s+by\s+" + re.escape(roaster) + r".*$", "", name, flags=re.I)
    if origin:
        name = re.sub(r"[,\s\-–|]+" + re.escape(origin) + r"\s*$", "", name, flags=re.I)
    name = re.sub(r"\(?\b\d{2,4}\s?g\b\)?", "", name, flags=re.I).strip(" -–|,")
    # what taking the origin or the bag size off can leave hanging: "Amecafe Blend from (Brazil)", "… factory (500g) bags"
    for _ in range(2):
        name = re.sub(r"\s+(?:from|of|in|with|by|for|and|&|bags?|packs?|pouch(?:es)?)\s*$", "", name, flags=re.I).strip(" -–|,")
    # "Kamwangi AA, Fully Washed, Batian, SL-28" -> "Kamwangi AA": stop at the first comma part that's only process or variety
    segs = [p.strip() for p in name.split(",")]
    if len(segs) >= 2:
        keep = [segs[0]]
        for p in segs[1:]:
            if details_only(p) or (find_process(p) and len(p) < 30) or any(p.lower() == v.lower() for v in VARIETIES):
                break
            keep.append(p)
        name = ", ".join(keep)
    name = tidy_name(name, roaster)
    name = close_brackets(name)
    return name or title


def close_brackets(name):
    """A bracket the shop never closed: 'Nestor Lasso - (72hr Advanced Washed' -> 'Nestor Lasso' (process, variety, origin or a date
    after it go), 'Uganda (Bukonzo Dream' -> 'Uganda Bukonzo Dream' (a name after it stays, without the bracket)."""
    for o, c in (("(", ")"), ("[", "]")):
        if name.count(o) > name.count(c):
            i = name.rfind(o)
            head, tail = name[:i].rstrip(" -–|,:"), name[i + 1:].strip()
            detail = (find_process(tail) or find_origin(tail) or any(v.lower() in tail.lower() for v in VARIETIES)
                      or re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d|\b\d+\s*(?:hr|h|hours?)\b|\bjarc\b|\b74\d{3}\b", tail, re.I))
            name = head if detail and len(head) >= 3 else f"{head} {tail}".strip()
    return re.sub(r"\s{2,}", " ", name).strip(" -–|,:")


# title segments that are labels or shop/SEO text, not the coffee's name
GENERIC_SEG = re.compile(r"^(?:\d{2}(?:/\d{2})?\s+new season|new season|new crop|release\s*#?\d+|\d+(?:[.,]\d+)?\s?(?:g|gr|kg)|farm|fun|classic|daily|exclusive|rare|special|limited(?: release| edition)?|new|new release|feature(?:d)?|guest|seasonal|single origin|nanolotes?|varietal|blend|"
                         r"filter|omni|coffee|whole ?beans?|shop|store|"
                         r"(?:buy\b.*|.*\bonline\b.*|.*\bspecialty coffee beans?\b.*))$", re.I)
BRAND_FILLER = re.compile(r"\b(?:the|coffee|co|company|roasters?|roastery|roasting|ltd|&|and|espresso)\b|[^\w\s]", re.I)


def is_brand(seg, roaster):
    """True when a title segment is just the shop's own name ("Nude Coffee Roasters", "doubleshot")."""
    rest = re.sub(re.escape(roaster), " ", seg, flags=re.I)
    return rest != seg and not BRAND_FILLER.sub(" ", rest).strip()


UI_WORD = re.compile(r"^\W*(?:close|menu|cart|basket|search|back|home|shop|view|quick view|add to (?:cart|basket)|sold out|"
                     r"choose an option|select options?|read more)\W*$", re.I)
SALE_FORM = re.compile(r"\(?\b(?:whole ?beans?|beans?|wholebean|ground(?: coffee)?|coffee beans?|\d+(?:[.,]\d+)?\s?(?:g|gr|kg|oz|lbs?))\b\)?", re.I)


def same_name(name):
    """A coffee's name without how it's sold: "Kiambu AB - Whole Bean 250g" and "Kiambu AB (Ground)" are one coffee."""
    return re.sub(r"\W+", "", SALE_FORM.sub(" ", name or "").lower()) or (name or "").lower()


def tidy_name(name, roaster):
    """'Buy Specialty Coffee Beans Online UK | Nude Coffee Roasters' -> '' (caller falls back);
    'Farm • Sagastume Geisha | doubleshot' -> 'Sagastume Geisha'; 'Limited Release | Franken Grind Blend' -> 'Franken Grind Blend';
    'EAST BLEND' -> 'East Blend'."""
    name = re.sub(r"\s*[\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]+\s*", " ", name).strip()   # Big Sur: the Chinese name after the English one
    name = re.sub(r"\s{2,}", " ", re.sub(r"\s*/\s*$", "", name)).strip()   # Fuglen Tokyo: "Arbegona / アルベゴナ" leaves a slash
    name = re.sub(r"^\W*\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}\W*", "", name)   # Philocoffea: "11/16 10:00~" release stamp
    name = re.sub(r"^\W*\d{3}\s+(?=[A-Z])", "", name)   # and its lot number: "459 China Yunnan …"
    name = re.sub(r"^\s*(?:\d{2,4}(?:/\d{2,4})?\s+)?new (?:season|crop)\b\s*[-–—:|]?\s*", "", name, flags=re.I)   # "25/26 New Season Ethiopia …"
    # a tag in square brackets at the end: a variety or lot number goes (Mellow: "… [Syrina]"); anything else is part of
    # the name and keeps its words without the brackets (People Possession: "Industrial Supply Series [RED]" -> "… Red")
    def _tail(m):
        t = m.group(1).strip()
        if any(v.lower() in t.lower() for v in VARIETIES if len(v) > 3) or re.search(r"\d", t):
            return ""
        return " " + (t.title() if t.isupper() else t)
    name = re.sub(r"\s*\[([^\]]{2,40})\]\s*$", _tail, name)
    # a blend named, then what's in it: "Broadway Blend: El Salvador & Guatemala" -> "Broadway Blend" (the origins show as tags)
    name = re.sub(r"^(.{2,40}?\bblend)\s*[:–—]\s+.+$", r"\1", name, flags=re.I)
    if re.search(r"\s[•·]\s", name):
        # "Honduras Finca El Puente • Geisha • Anaerobic Natural" -> "Honduras Finca El Puente, Geisha" (process shows as a tag)
        bits = [b.strip() for b in re.split(r"\s[•·]\s", name) if b.strip()]
        bits = [b for b in bits if not GENERIC_SEG.match(b) and not is_brand(b, roaster)]
        while len(bits) > 1 and find_process(bits[-1]) and len(bits[-1]) < 30:
            bits.pop()
        name = ", ".join(b[:1].upper() + b[1:] if b.islower() else b for b in bits)
    first, _, rest = name.partition(", ")
    caps = re.sub(r"[^A-Za-z]", "", first)
    if rest and len(caps) >= 4 and caps.isupper() and not find_origin(first):
        # "EFFLORESCE, Washed Thermal Shock, Sidra" -> "Effloresce" (process, variety and origin show as tags)
        name = first
    parts = [p.strip() for p in re.split(r"\s[|–—]\s|\s-\s", name) if p.strip()]
    keep = [p for p in parts if not is_brand(p, roaster) and not GENERIC_SEG.match(p)]
    if len(parts) > 1:
        name = " ".join(keep[:1]) if len(keep) != len(parts) else name
        # "Gem Forest Coffee - Double Ferment Washed [Syrina]", "Black Moon Chiroso — Natural": the tail is tags
        if len(keep) == 2 and details_only(keep[1]):
            name = keep[0]
        # "Fruity & Floral - Nicaragua Santa Isabel" (Kaffa Roastery): the shop's flavour style first, the coffee after
        if len(keep) == 2 and re.fullmatch(r"[A-Za-z]+ & [A-Za-z]+", keep[0]):
            name = keep[1]
    elif not keep:
        name = ""
    if ", " in name:
        # "Colombia, Amigos de Buesaco, Nariño, natural" -> "Amigos de Buesaco, Nariño"; "Don Benjie, SL28 Natural" -> "Don Benjie"
        bits = [b.strip() for b in name.split(", ") if b.strip()]
        if len(bits) > 1 and find_origin(bits[0]) and len(bits[0]) <= len(find_origin(bits[0])) + 1:
            bits = bits[1:]
        while len(bits) > 1 and details_only(bits[-1]) and not details_only(bits[0]):
            bits.pop()
        name = ", ".join(bits)
    head, sep, tail = name.rpartition(": ")
    if sep and head and details_only(tail):   # "Finca Sunderland: Washed" -> "Finca Sunderland"
        name = head
    name = re.sub(r"^\s*\[[^\]]{3,40}\]\s*", "", name)   # "[Kawa bezkofeinowa] Kolumbia El Vergel Decaf": a shop category in brackets
    # "El Diviso Ombligon ! DÉCAFÉINÉ !! Filtre & Espresso" -> "El Diviso Ombligon Décaféiné"
    name = re.sub(r"\s*\b(?:filt(?:er|re|ro)\s*(?:&|and|et|/|\+)\s*espresso|espresso\s*(?:&|and|et|/|\+)\s*filt(?:er|re|ro))\s*$", "", name, flags=re.I)
    name = re.sub(r"\s*!+\s*", " ", name).strip()
    # "Alo Bore [Washed]" -> "Alo Bore": a bracketed process at the end is already a tag
    name = re.sub(r"\s*[\[(]([^\])]{3,30})[\])]\s*$", lambda m: "" if find_process(m.group(1)) or details_only(m.group(1)) else m.group(0), name)
    return calm_caps(name).strip(" -–—|,")


DETAIL_WORDS = re.compile(r"\b(?:washed|natural|honey|anaerobic|aerobic|double|triple|ferment(?:ed|ation)?|co-?ferment(?:ed)?|culturing|cultured|"
                          r"carbonic|maceration|thermal|shock|decaf|semi|pulped|wet|hulled|dry|process(?:ed)?|\d+\s?h(?:rs?|ours?)?|yeast|lactic|"
                          r"experimental|black|white|red|yellow|orange|pink|20\d\d)\b", re.I)


def details_only(seg):
    """True when a name part is nothing but process and variety words ('SL28 Natural', 'Double Ferment Washed', 'Syrina')."""
    rest = DETAIL_WORDS.sub(" ", seg)
    for v in sorted(VARIETIES, key=len, reverse=True):
        rest = re.sub(r"\b" + re.escape(v) + r"\b", " ", rest, flags=re.I)
    rest = re.sub(r"\b(?:sl\s?\d+|ruiru\s?\d+|batian|typica|bourbon|caturra|catuai|castillo|heirloom|landrace|74\d{3})\b|[^\w]+|\s+", " ", rest, flags=re.I).strip()
    return bool(seg.strip()) and not rest


GRADE = {"EA", "AA", "AB", "AAA", "PB", "SL", "EP", "SHB", "SHG", "FW", "HB", "DR", "PNG", "UK", "USA"}


def calm_caps(name):
    """Shouted titles in sentence-friendly caps: 'GATOMBOYA AA' -> 'Gatomboya AA', 'EL SALVADOR Tempisque' -> 'El Salvador Tempisque',
    'A DROP OF SCIENCE' -> 'A Drop of Science'. Grades and codes (AA, SL28, 3FE) stay as they are."""
    words = name.split()
    letters = re.sub(r"[^A-Za-z]", "", name)
    shouting = len(letters) >= 4 and letters.isupper()
    if not shouting:
        # mixed case: capital runs are usually brands or acronyms (SNSC, CGLE), so only countries and DECAF are calmed
        def calm(m):
            run = m.group(0)
            if re.fullmatch(r"D[EÉ]CAF[EÉ]?(?:IN[EÉ])?", run) or (find_origin(run) and len(run) <= len(find_origin(run)) + 1):
                return " ".join(w.capitalize() for w in run.split())
            return " ".join(w.capitalize() if len(w) >= 4 and len(re.findall(r"[AEIOUYÀ-Ý]", w)) >= 2 else w for w in run.split())
        return re.sub(r"\b[A-ZÀ-Ý]{2,}(?:\s+[A-ZÀ-Ý]{2,})*\b", calm, name)
    out = []
    for i, w in enumerate(words):
        core = re.sub(r"[^A-Za-z]", "", w)
        if not core.isupper() or re.search(r"\d", w) or core in GRADE or (not shouting and len(core) < 4):
            out.append(w)
        elif i and core.lower() in ("of", "and", "the", "with", "a"):
            out.append(w.lower())
        else:
            out.append(w[:1] + w[1:].lower())
    return " ".join(out)



BAG_W = re.compile(r"(\d+(?:[.,]\d+)?)\s?(kg|kilos?|g|gr|gms?|grams?|oz|lbs?)\b", re.I)   # "250gms" (Proud Mary) too


def bag_grams(item):
    """The bag size in grams: the smallest bag in the sizes on sale (the listed price is the cheapest, so the smallest bag),
    else from the title, else a size the description ties to the bag. None when the listing never says."""
    def sizes(text):
        out = []
        for n, u in BAG_W.findall(text or ""):
            v = float(n.replace(",", ".")); u = u.lower()
            g = v * 1000 if u.startswith("k") else v * 28.35 if u == "oz" else v * 453.6 if u.startswith("lb") else v
            if 50 <= g <= 2000:
                out.append(int(round(g)))
        return out
    for text in (item.get("variants"), item.get("title")):
        got = sizes(text)
        if got:
            return min(got)
    m = re.search(r"(?:bag|pack|net|size|weight)[^.]{0,30}?\b(\d+(?:[.,]\d+)?\s?(?:kg|g|grams?|oz))\b|\b(\d+(?:[.,]\d+)?\s?(?:kg|g|grams?|oz))\s(?:bag|pack|net)", item.get("body") or "", re.I)
    if m:
        got = sizes(m.group(1) or m.group(2))
        return min(got) if got else None
    return None

def price_ccy(item, roaster):
    """The currency to print a price in: the one set by hand for the roaster, else the one the coffee's own page states, else the
    shop's. Father's pages give some coffees in koruna and some in euros: every price was labelled with the shop's euros, so a
    449 Kč bag read "€449.77"."""
    own = item.get("currency")
    return roaster.get("currency") or (own if isinstance(own, str) and re.fullmatch(r"[A-Z]{3}", own) else None) or roaster.get("_ccy", "GBP")


def money(v, ccy):
    sym = SYMBOL.get(ccy, ccy + " ")
    amount = f"{v:,.0f}" if ccy in ("COP", "CLP", "ARS") else f"{v:.0f}" if ccy in ("JPY", "DKK", "SEK", "NOK", "CZK") else f"{v:.2f}"
    return amount + sym if sym.startswith(" ") else sym + amount


PAGES = {}   # url -> (raw html, visible text), shared by the origin and the process/variety look-ups
ORIGIN_PAGE_FETCHES = 60


def cached_page(url):
    if url not in PAGES:
        PAGES[url] = page_text(url)
        time.sleep(0.4)
    return PAGES[url]


def origin_from_page(item, roaster):
    """Country for a coffee whose feed doesn't name one: a labelled Origin/Country on its page, else the
    country named most in the text right after its title (menus and footers are stripped first)."""
    prev = (roaster.get("_old") or {}).get(item.get("url"), {})
    if prev.get("origin_from") == "page" and prev.get("origin"):
        item["_origin_from"] = "page"
        return prev["origin"]
    n = roaster.setdefault("_origin_pages", 0)
    if n >= ORIGIN_PAGE_FETCHES or not item.get("url"):
        return None
    roaster["_origin_pages"] = n + 1
    try:
        raw, text = cached_page(item["url"])
    except Exception:  # noqa: BLE001
        return None
    start = text.lower().find(item["title"].lower()[:30])
    window = text[max(start, 0):max(start, 0) + 2500]
    o = None
    for m in ORIGIN_LABEL.finditer(window):
        o = find_origin(m.group(1))
        if o:
            break
    o = o or find_origin(window[:200])
    if not o and COFFEE_HINT.search(window):   # a bare count needs the page to read like a coffee page
        o = count_origin(window)
    if o:
        item["_origin_from"] = "page"
        item["body"] = (item.get("body") or "") + "\n" + window   # lets process, variety and notes use the page too
    return o


DROPS = {}   # roaster -> reason -> [titles], printed at the end of a scan so silent drops can be reviewed


def _drop(roaster, reason, title):
    DROPS.setdefault(roaster["name"], {}).setdefault(reason, []).append(title)
    return None


def classify(item, roaster):
    title = item["title"]
    blob = " ".join([title, item["type"], " ".join(item["tags"]), item["variants"]])
    full = blob + "\n" + item["body"]
    if not item["available"]:
        return _drop(roaster, "sold out", title)
    # a product type that is just the shop's name for bagged coffee ("Coffee Bags", Kaffa Roastery) is not a steeping bag
    ptype = "" if re.fullmatch(r"\s*(?:coffee|kahvi|kaffe)\s*bags?\s*", item["type"] or "", re.I) else item["type"]
    m = EXCLUDE.search(title) or EXCLUDE.search(ptype)
    if m:
        return _drop(roaster, f"not coffee ({m.group(0)})", title)
    why = not_coffee(item) or not_beans(item) or not_one_coffee(item)
    if why:
        REJECTED.append(f"{roaster['name']}: {title} ({why})")
        return _drop(roaster, why.split(":")[0], title)
    # dark roasts stay (the recipe handles them); read the level from the title/tags or a labelled roast line,
    # not from anywhere on the page: Hasbean prints the whole light-to-dark scale on every coffee
    # tags naming two roast levels are the shop's filter menu, not this coffee: they say nothing about its roast
    menu_tags = len({roast_word(t.split(":", 1)[-1]) for t in item["tags"] if re.search(r"roast", t, re.I)} - {None}) > 1
    dark_src = " ".join([title, item["type"], item["variants"]]) if menu_tags else blob
    m = DARK.search(dark_src) or ROAST_LABEL.search(item["body"])
    roast_level = None
    if m:
        lvl = (m.group(1) if m.re is ROAST_LABEL else m.group(0)).lower()
        roast_level = "medium-dark" if "medium" in lvl else "dark"
    tags_txt = "\n".join(f"Roast: {t.split(':', 1)[-1].replace('roast', '')}" if re.search(r"roast", t, re.I) else "" for t in item["tags"])
    if menu_tags:
        tags_txt = ""
    # the coffee's own "Roast: Medium" line first: a shop's tags can say otherwise (Danelaw tagged Polaris, a
    # medium roast espresso, as light)
    roast = roast_labelled(item["body"]) or find_roast(tags_txt, f"{title}\n{item['type']}", item["body"])
    origin = find_origin(title, blob, item["body"])
    if not origin and (BAG.search(f"{title} {item['type']} {' '.join(item['tags'])} {item['variants']}")
                       or re.search(r"/coff?ees?/[^/?#]+/?$", item.get("url") or "", re.I)):
        # the shop's feed doesn't say where it's from (Nomad, Dak, Blossom...): read the product page
        origin = origin_from_page(item, roaster)
    if not origin and roaster.get("country") in GROWING_HOME and COFFEE_HINT.search(full) \
            and re.search(r"\b\d{2,4}\s?g\b|gr[aã]os|grano|mo[ií]do|molido|whole bean|ground", f"{title} {item['variants']}", re.I):
        # a roaster in a growing country names the farm, not the country: Pergamino's "Lomaverde" is Colombian
        origin = GROWING_HOME[roaster["country"]]
    blend = blend_reason(item)
    if blend:
        parts = blend_origins(item)
        origin = " / ".join(parts) if len(parts) >= 2 else (origin or (parts[0] if parts else None))
    is_coffee = bool(origin) and (bool(COFFEE_HINT.search(full)) or bool(BEANISH.search(blob)))
    if not is_coffee:
        return _drop(roaster, "no origin found" if not origin else "no coffee details", title)
    filtery = bool(FILTERY.search(blob)) or bool(re.search(r"roasted for filter|filter roast|omni roast", item["body"], re.I))
    # espresso-only coffees stay in (the site brews espresso and moka too); they're marked as espresso roasts
    espresso_only = (bool(ESPRESSO.search(title + " " + item["type"])) and not filtery) \
        or (not filtery and bool(ESPRESSO.search(" ".join(item["tags"]))) and not FILTERY.search(item["body"]))
    process = find_process(title + " " + " ".join(item["tags"])) or process_from_text(item["body"]) or process_phrase(item["body"])
    variety = first(VARIETIES, title + " " + " ".join(item["tags"])) or first(VARIETIES, item["body"])
    rec = {
        "roaster": roaster["name"],
        "name": clean_name(title, roaster["name"], origin),
        "origin": origin,
        "process": process,
        "variety": variety,
        "notes": find_notes(item),
        "price": (item.get("price_prefix") or "") + money(item["price"], price_ccy(item, roaster)) if item["price"] else None,
        "url": item["url"],
        "bag_g": bag_grams(item),
        "published": item["published"] or None,
        "roast": "filter" if filtery else "omni / unlabelled",
        "roast_for": "espresso" if espresso_only else roast_for(item),
        "blend": True if blend else None,
        "roast_level": roast_level,
        "roast": roast or ("mdark" if roast_level == "medium-dark" else "dark" if roast_level else None),
        "roast_from": "feed" if (roast or roast_level) else None,
        "origin_from": item.get("_origin_from"),
    }
    rec["market"] = roaster.get("region", "UK")
    rec["roaster_country"] = roaster.get("country")
    rec["roaster_city"] = roaster.get("city")
    if roaster.get("nation"):
        rec["roaster_nation"] = roaster["nation"]
    return {k: v for k, v in rec.items() if v not in (None, "", [])}


# ---------- product page details ----------
# Many shops keep process and variety in theme fields (Shopify metafields) that never reach the
# product JSON: Climpson shows "Process: Natural" on the page but not in body_html. When the JSON
# gives no process or variety, read the product page and take the labelled value.
PAGE_LABEL = {
    "process": re.compile(r"\b(?:process(?:ing)?(?: method)?|processo|proceso|prozess|aufbereitung|proc[ée]d[ée]|bearbetning|prosess|proces|zpracov[aá]n[ií]|obr[oó]bka|verwerking(?: na oogst)?|verwerkingsmethode)\s*(?::|\n)", re.I),
    "variety": re.compile(r"\b(?:variet(?:y|ies|al|als)|cultivars?|variedad(?:es)?|variet[àa]|sorte[n]?|vari[ée]t[ée]s?|vari[eë]teit(?:\(?en\)?)?|odmian[ay]?)\s*(?::|\n)", re.I),
}
# what each run had to leave for another day, by shop: pages not read (the time budget or the shop's daily cap), roasters not reached
REPORT = {"page_time": {}, "page_cap": {}, "price_time": {}, "price_cap": {}, "not_reached": []}
REPORT_LOCK = threading.Lock()


def report_skip(kind, shop):
    with REPORT_LOCK:
        REPORT[kind][shop] = REPORT[kind].get(shop, 0) + 1


PAGE_FETCHES_PER_ROASTER = 60   # product pages read per shop per day, on top of its product list (the rest wait for tomorrow)
# product pages are read only for the first 100 minutes of a run, so a day with a lot to re-read (new rules) still ends
# well inside the workflow's 150-minute limit and saves what it found; the rest is read the next day
SCAN_T0 = time.monotonic()
PAGE_MINUTES = 200
STOP_MINUTES = 240   # roasters not reached by then keep yesterday's coffees, so the run always saves inside the 270-minute limit (GitHub allows 360)
# a coffee's page is read for its roast once per version of the roast reader: when the reader learns a new
# way shops write it, every coffee still without a roast gets one more look, and never again after that
ROAST_CHECK = 3


JSON_PROCESS = [re.compile(r'"(?:process(?:ing)?(?:_method|Method)?)"\s*:\s*"([^"]{2,60})"', re.I),
                re.compile(r'Process::\s*([^"\\]{2,60})'),
                re.compile(r'"key"\s*:\s*"process[^"]*"[^{}]{0,300}?"value"\s*:\s*"([^"]{2,60})"', re.I)]
JSON_VARIETY = [re.compile(r'"(?:variet(?:y|ies|al)|cultivars?)"\s*:\s*"([^"]{2,80})"', re.I),
                re.compile(r'Variety::\s*([^"\\]{2,80})'),
                re.compile(r'"key"\s*:\s*"variet[^"]*"[^{}]{0,300}?"value"\s*:\s*"([^"]{2,80})"', re.I)]


def page_text(url):
    raw = get_text(url, tries=2, limit=1_500_000)
    return raw, _visible(raw)


def raw_labelled(raw, k):
    """A label that is a whole HTML text node (<h4>Process:</h4><p>Natural</p>), read straight from the HTML.
    Works even when the page wraps its product block in something _visible() strips."""
    words = PAGE_LABEL[k].pattern.split(r"\s*(?::|\n)")[0]
    for m in re.finditer(r">\s*" + words + r"\s*:?\s*<", raw, re.I):
        after = strip_html(raw[m.end() - 1:m.end() + 1500])
        got = labelled(("Process" if k == "process" else "Variety") + ":\n" + after, k)
        if got:
            return got
    return None


RAW_NOTES_LABEL = re.compile(r">\s*(tasting notes|flavou?r notes|flavou?r profile|cup notes|tastes like|notes)\s*:?\s*<", re.I)


def raw_notes(raw, name):
    """Notes under a label that is a whole HTML text node (<h4>Flavour profile:</h4><p>Liquorice, Pear, Blackberry</p>), read
    straight from the HTML: for pages whose product block _visible() strips (Climpson), like raw_labelled() does for process."""
    for m in RAW_NOTES_LABEL.finditer(raw):
        after = strip_html(raw[m.end() - 1:m.end() + 600]).strip()
        first = next((ln.strip() for ln in after.split("\n") if ln.strip()), "")
        if not first or len(first) > 120 or first.endswith(":"):
            continue
        ns = find_notes({"body": m.group(1) + ":\n" + first + "\n", "title": name, "tags": []})
        if ns:
            return ns
    return []


# Tasting notes read as the variety (Caffeine Project "Caramel, Toasts, Vanilla", Tigermoth "Blackberry, tangerine, dark brown
# sugar"): a variety field with flavour words and no coffee variety in it is notes, not a variety.
FLAVOUR_WORD = re.compile(r"\b(?:chocolate|cocoa|cacao|caramel|vanilla|toasts?|toasted|berry|berries|blackberry|strawberry|raspberry|blueberry|"
                          r"cherry|cherries|citrus|lemon|lime|orange|tangerine|grapefruit|floral|flowery|nuts?|nutty|hazelnut|almond|sugar|"
                          r"honeycomb|apple|plum|peach|apricot|toffee|fudge|jam|fruit|fruity|tea|jasmine|bergamot|grape|wine|molasses|spices?|"
                          r"cinnamon|biscuit|malt|butter|cream|syrup|raisin|fig|melon|mango|tropical|currant|blackcurrant|earthy)\b", re.I)


def variety_is_flavour(v):
    """True when a 'variety' is really a list of tasting notes (no coffee variety named in it)."""
    if not v or not FLAVOUR_WORD.search(v):
        return False
    return not first(VARIETIES, v) and not re.search(r"\b(?:sl ?\d+|ruiru|batian|catua[ií]|caturr|castillo|pacas|pacamara|bourbon|typica|gesha|geisha|"
                                                     r"heirloom|landrace|74\d{3}|sidra|java|mokka|catimor|parainema|marsellesa|villa|mundo|obata|"
                                                     r"icatu|arara|chiroso|tabi|wush|laurina|eugenioides|kent|jackson|mibirizi|tekisic|caturron|papayo)\b", v, re.I)


def flavour_variety(x):
    """Move tasting notes read as the variety into the notes (when the notes hold none) and clear the variety."""
    v = x.get("variety")
    if not variety_is_flavour(v):
        return x
    ns = [n for n in x.get("notes") or [] if FLAVOUR_WORD.search(n)]
    if not ns:
        ns = [tidy_note(p) for p in re.split(r"\s*[,|/]\s*", v)]
        x["notes"] = [n for n in ns if n][:5] or x.get("notes")
    x["variety"] = None
    return x


def tidy_variety(v):
    """A variety written in a theme block or a value-first line: no "variety" word, no process, natural capitals."""
    v = re.sub(r"\b(?:variet(?:y|ies|al|als)|cultivars?)\b", " ", v, flags=re.I)
    for part in re.split(r"\s+[-–|/]\s+|\s*\|\s*", v):
        part = part.strip(" -–/|,:.\xa0")
        if not part or find_process(part) or re.search(r"process", part, re.I):
            continue
        got = labelled(f"Variety:\n{part}\n", "variety")
        if got:
            return " ".join(w.capitalize() if w.isalpha() and (w.isupper() or w.islower()) and len(w) > 2 else w for w in got.split())
    return None


def class_labelled(raw, k):
    """A short block the shop's theme names after the field: <p class="product__process">washed process</p>,
    <span class="coffeeTitle_varietyProcess">CHIROSO - WASHED</span>; or the process in a product's class list
    (WooCommerce: "process_traditional-washed", "pa_process-natural")."""
    want = r"process" if k == "process" else r"variet|cultivar"
    for m in re.finditer(r'<([a-z][a-z0-9-]*)\b[^>]*?\b(?:class|id)\s*=\s*["\'][^"\']*?(?:' + want + r')[^"\']*["\'][^>]*>', raw, re.I):
        end = raw.find("</" + m.group(1), m.end())
        if end < 0 or end - m.end() > 600:
            continue
        inner = strip_html(raw[m.end():end]).strip()
        if not inner or len(inner) > 80:
            continue
        got = find_process(inner) if k == "process" else tidy_variety(inner)
        if got:
            return got
    if k == "process":
        m = re.search(r'class\s*=\s*["\'][^"\']*\b(?:pa_)?process[_-]([a-z][a-z-]{2,40})', raw, re.I)
        if m:
            return find_process(m.group(1).replace("-", " "))
    return None


def suffix_labelled(text, k, start=0):
    """A line that is the value followed by the field's name: "washed process", "typica variety"."""
    rx = re.compile(r"(?im)^[ \t]*([^\n:]{2,40}?)\s+process(?:ed)?[ \t]*$") if k == "process" else \
        re.compile(r"(?im)^[ \t]*([^\n:]{2,50}?)\s+(?:variet(?:y|ies|al)|cultivars?)[ \t]*$")
    for t in ((text[start:start + 6000], text) if start else (text,)):
        for m in rx.finditer(t):
            got = find_process(m.group(1)) if k == "process" else tidy_variety(m.group(1))
            if got:
                return got
    return None


def from_json(raw, k):
    for rx in (JSON_PROCESS if k == "process" else JSON_VARIETY):
        for m in rx.finditer(raw):
            v = html.unescape(m.group(1)).strip()
            got = find_process(v) if k == "process" else labelled(f"Variety:\n{v}\n", "variety")
            if got:
                return got
    return None


def _visible(raw):
    # (?=[\s>]) so a custom element like <header-drawer> is not read as <header> (that ate Climpson's whole product block)
    raw = re.sub(r"<(script|style|noscript|svg|template)(?=[\s>]).*?</\1>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<(header|nav|footer)(?=[\s>]).*?</\1>", " ", raw, flags=re.I | re.S)
    return strip_html(raw)


GLUED_LABEL = {"process": re.compile(r"(?<=[a-z])Process\s*:"), "variety": re.compile(r"(?<=[a-z])Variety\s*:")}


def labelled(text, key, start=0):
    """The value written after a "Process:" / "Variety:" label, or None."""
    for m in [*PAGE_LABEL[key].finditer(text, start), *GLUED_LABEL[key].finditer(text, start)]:
        window = text[m.end():m.end() + 90]
        if key == "process":
            got = find_process(window)
            if got:
                return got
        else:
            line = next((l.strip(" :-\xa0\t") for l in window.split("\n") if l.strip(" :-\xa0\t")), "")
            # labels run on one line ("Variety: Castillo Process: Washed", "GeishaProcess: Washed"): stop at the next one
            line = re.split(r"(?:\s+|(?<=[a-z]))(?=[A-Z][a-z]+(?:\s[A-Za-z]+){0,3}\s*:)", line)[0].strip(" :-\xa0\t")
            if line and not PAGE_LABEL["process"].match(line + ":") and len(line) <= 60 and \
                    (first(VARIETIES, line) or re.search(r"[A-Z][a-z]+|\d{3,}", line)):
                junk = re.search(r"\b(?:process|altitude|elevation|masl|harvest|origin|region|notes?|producer|farm)\b|\b(?:19|20)\d\d\b", line, re.I)
                vague = re.fullmatch(r"(?:various|mixed|mix(?:ed)? variet(?:y|ies)|multiple|n/?a|unknown|(?:100\s?%\s?)?arabi[ck]a|m[ée]lange|blend de vari[ée]t[ée]s|mix de vari[ée]t[ée]s)", line, re.I) or \
                    re.match(r"mieszanka|mix of|blend of", line, re.I)
                place_only = countries_in(line) and not first(VARIETIES, line)
                if not (junk or vague or place_only):
                    return line
    return None


PRICE_META = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og|product):price:(amount|currency)["\'][^>]+content=["\']([^"\']+)', re.I)
PRICE_FETCHES_PER_ROASTER = 40


SHOWN_PRICE = re.compile(r"([£€])\s?(\d{1,3}(?:[.,]\d{2})?)(?![\d.,]*\s?(?:off|%))")


def shown_price(raw, name):
    """The price printed on the page just after the coffee's name ("Danse … £ 14.00"), for shops whose page data gives none or a
    zero (Conscious: its data says $0.00 while the page shows pounds). Only pounds or euros, only within a few lines of the name,
    never a 'free delivery over £25' line."""
    text = _visible(raw)
    i = name_at(text, name) if name else -1
    if i < 0 or (i == 0 and not text.lower().startswith(name.lower()[:30])):
        return None, None
    for ln in text[i:i + 700].split("\n")[:14]:
        if re.search(r"\b(?:over|above|under|from|save|delivery|shipping|orders?|spend|subscri)\b", ln, re.I):
            continue
        m = SHOWN_PRICE.search(ln)
        if m and float(m.group(2).replace(",", ".")) > 0:
            return float(m.group(2).replace(",", ".")), {"£": "GBP", "€": "EUR"}[m.group(1)]
    return None, None


def page_price(raw, name=""):
    """(amount, currency) from a product page: schema.org offers first, then og/product price meta tags, then the price
    printed by the coffee's name."""
    for p in ld_products(raw):
        it = ld_to_item(p, "", "")
        if it.get("price"):
            return it["price"], it.get("currency")
    # WooCommerce variable products keep their variation prices in a data attribute on the add-to-cart form
    # (RAF: the Store API returns price 0 and no variations); prefer the 250 g bag, else the cheapest
    sym = re.search(r'woocommerce-Price-currencySymbol">\s*([^<\s]+)', raw)
    cur = {"&euro;": "EUR", "€": "EUR", "&pound;": "GBP", "£": "GBP", "&#36;": "USD", "$": "USD"}.get(sym.group(1) if sym else "")
    m = re.search(r'data-product_variations="([^"]+)"', raw)
    if m and cur:
        try:
            vs = [v for v in json.loads(html.unescape(m.group(1))) if isinstance(v, dict) and v.get("display_price")]
        except ValueError:
            vs = []
        if vs:
            pick = next((v for v in vs if re.search(r"\b250\s?g", json.dumps(v.get("attributes", {})), re.I)), None)
            return float((pick or min(vs, key=lambda v: float(v["display_price"])))["display_price"]), cur
    m = re.search(r'<p class="price">(.*?)</p>', raw, re.S)
    if m and cur:
        a = re.search(r'(\d+(?:[.,]\d{2})?)', re.sub(r"<[^>]+>|&nbsp;", " ", m.group(1)))
        if a:
            return float(a.group(1).replace(",", ".")), cur
    meta = {k.lower(): v for k, v in PRICE_META.findall(raw)}
    try:
        if meta.get("amount"):
            return float(meta["amount"].replace(",", ".")), meta.get("currency")
    except ValueError:
        pass
    return shown_price(raw, name) if name else (None, None)


def add_page_prices(recs, roaster, old):
    """Last resort for "Price on site": read the price from the product page, asking for the shop's home market.
    A price is only shown when the page states it in the shop's own currency, so a geo-converted figure never
    gets through. Last week's page price for the same URL is reused when nothing changed."""
    home, fetched, filled = home_currency(roaster), 0, 0
    loc = f"country={roaster.get('country') or 'GB'}&currency={home}"
    for rec in recs:
        if rec.get("price"):
            continue
        prev = old.get(rec["url"], {})
        if prev.get("price") and prev.get("price_from") == "page":
            rec["price"], rec["price_from"] = prev["price"], "page"
            continue
        if fetched >= PRICE_FETCHES_PER_ROASTER or time.monotonic() - SCAN_T0 > PAGE_MINUTES * 60:
            left = sum(1 for x in recs[recs.index(rec):] if not x.get("price"))
            for _ in range(left):
                report_skip("price_cap" if fetched >= PRICE_FETCHES_PER_ROASTER else "price_time", roaster["name"])
            break
        fetched += 1
        try:
            raw = get_text(rec["url"] + ("&" if "?" in rec["url"] else "?") + loc, tries=1)
        except Exception:  # noqa: BLE001
            continue
        amount, ccy = page_price(raw, rec.get("name") or "")
        if amount and 1 <= amount <= 1000 and (ccy or "").upper() == home:
            rec["price"], rec["price_from"] = money(amount, home), "page"
            filled += 1
        time.sleep(.4)
    if fetched:
        print(f"  prices from pages for {roaster['name']}: {filled} of {fetched}")


BREW_METHODS = [("filter", r"filter|filtr|pour[- ]?over|v60|chemex|kalita|origami|drip(?:per)?|przelew|aeropress|batch ?brew|handfilter|filtre|filtro"),
                ("espresso", r"espresso|ekspres(?: kolbowy| ciśnieniowy)?"),
                ("moka", r"kawiarka|moka(?: ?pot)?|mokapot|bialetti|cafetera"),
                ("french press", r"french ?press|cafeti[eè]re|frenchpress"),
                ("machine", r"automaat|bonenautomaat|volautomaat|lungo|bean[- ]to[- ]cup|ekspres automatyczny|vollautomat|automatic"),
                ("cold brew", r"cold ?brew")]
METHOD_ATTR = re.compile(r'\b(?:alt|title|aria-label)=["\'](?:(?:geschikt voor|suitable for|ideal for|perfect for|recommended for|great for|polecane do|empfohlen f[üu]r)\s+)?([^"\'<>]{3,30})["\']', re.I)


METHOD_FILE = re.compile(r'(?:src=["\']|url\([\'"]?)[^"\')]*/(?:icons?|brew\w*|method\w*|zetwijze)/[^"\')/]*?'
                         r'(espresso|moka|bialetti|kawiarka|french-?press|cafetiere|v60|chemex|kalita|filter|aeropress|drip|pour-?over|lungo|automa\w*)[^"\')/]*\.(?:svg|png|webp)', re.I)
METHOD_LIST = re.compile(r"(?:brew(?:ing)? methods?|recommended (?:brew(?:ing)? )?(?:for|methods?)|suitable for|best for|metody parzenia|"
                         r"zetwijze|bereidingswijze|zubereitung(?:sarten)?|m[ée]thodes? (?:d'extraction|de pr[ée]paration))\s*:?\s*([^\n]{3,140})", re.I)


def method_names(v):
    v = v.strip().lower()
    return {name for name, pat in BREW_METHODS if re.fullmatch(pat, v, re.I)}


def brew_methods(raw, text=""):
    """Brew methods a product page names for the coffee, or an empty set: icons ("Geschikt voor espresso",
    <img alt="Kawiarka">, .../brewing/moka.svg) or a labelled list ("Brewing methods: Espresso, Moka").
    Only values that are nothing but a method name count, so menus, photos and prose don't."""
    found = set()
    for m in METHOD_ATTR.finditer(raw):
        found |= method_names(m.group(1))
    for m in METHOD_FILE.finditer(raw):
        found |= method_names(m.group(1).replace("-", " "))
    if len(found) < 2 and text:
        for m in METHOD_LIST.finditer(text):
            got = set()
            for part in re.split(r",|/|\band\b|\boraz\b|\ben\b|\bund\b|\bet\b|&|\+|·|\|", m.group(1)):
                got |= method_names(part)
            if len(got) >= 2:
                found |= got
                break
    return found


def add_page_details(recs, roaster, old):
    """Fill missing process / variety from the product page (or last week's answer for the same URL)."""
    fetched, filled, errs = 0, 0, []
    today = datetime.now(timezone.utc).date().isoformat()
    # pages left unread on an earlier day go first, oldest wait first, so no coffee stays at the back of the queue
    order = sorted(recs, key=lambda r_: old.get(r_["url"], {}).get("page_wait") or "9999")
    for rec in order:
        prev = old.get(rec["url"], {})
        if prev.get("methods") and not rec.get("roast_for"):
            rec["methods"] = prev["methods"]
            rec["roast_for"] = "filter" if "filter" in prev["methods"] else "espresso"
        if prev.get("methods_none"):
            rec["methods_none"] = True
        if not rec.get("roast") and prev.get("roast") and prev.get("roast_from") == "page" and prev.get("roast_checked") == ROAST_CHECK:
            rec["roast"], rec["roast_from"] = prev["roast"], "page"
        if prev.get("roast_checked") == ROAST_CHECK:
            rec["roast_checked"] = ROAST_CHECK
        want_roast = not rec.get("roast") and not rec.get("roast_checked") and rec.get("roast_for") != "espresso"
        # page notes are kept. A list of two or fewer read under older rules may have been cut short ("Té verde, manzanilla,
        # fruta de la pasión y kiwi amarillo" kept only the first two), so its page is read once more; the old list stays if that finds nothing
        short_old = prev.get("notes_from") == "page" and len(prev.get("notes") or []) <= 2 and (prev.get("notes_v") or 0) < NOTES_V
        if prev.get("notes") and any(junk_note(n) for n in prev["notes"]):   # markup kept as notes by older rules (Dak's image addresses): forgotten, and the page is read again
            prev = {**prev, "notes": None, "notes_from": None, "notes_checked": 0}
        if not rec.get("notes") and prev.get("notes") and prev.get("notes_from") == "page":
            rec["notes"], rec["notes_from"] = prev["notes"], "page"
            if prev.get("notes_v"):
                rec["notes_v"] = prev["notes_v"]
        if (prev.get("notes_checked") or 0) >= notes_ver(roaster["name"]):
            rec["notes_checked"] = notes_ver(roaster["name"])
        need = [k for k in ("process", "variety", "notes") if not rec.get(k) and not (k == "notes" and rec.get("notes_checked"))]
        if short_old and rec.get("notes_from") == "page" and "notes" not in need:
            need.append("notes")
        # a shop whose page layout fooled the notes rules (Sydrip: the related coffees' notes taken for this one's) is read
        # once more under the fixed rules, and what the page says now replaces the old list
        redo = roaster["name"] in NOTES_RECHECK and prev.get("notes_from") == "page" and (prev.get("notes_checked") or 0) < NOTES_RECHECK[roaster["name"]]
        if redo and "notes" not in need:
            need.append("notes")
        # every coffee the shop doesn't label filter or espresso gets its page read once for the brewers it names
        want_methods = not rec.get("roast_for") and not rec.get("methods") and not rec.get("methods_none")
        # a blend's page is read once for what it is made of (kept from then on)
        if prev.get("parts"):
            rec["parts"] = prev["parts"]
        if prev.get("parts_checked"):
            rec["parts_checked"] = prev["parts_checked"]
        want_parts = bool(rec.get("blend")) and not rec.get("parts") and not rec.get("parts_checked")
        if not need and not want_methods and not want_roast and not want_parts:
            continue
        for k in [k for k in need if k != "notes"]:
            ok = prev.get(k) and (labelled(f"Variety:\n{prev[k]}\n", "variety") if k == "variety" else find_process(prev[k]))
            if ok and prev.get(k + "_from") == "page":
                rec[k], rec[k + "_from"] = prev[k].strip(" \xa0"), "page"
        need = [k for k in need if not rec.get(k) or (k == "notes" and short_old)]
        if not need and not want_methods and not want_roast and not want_parts:
            continue
        if fetched >= PAGE_FETCHES_PER_ROASTER or time.monotonic() - SCAN_T0 > PAGE_MINUTES * 60:
            report_skip("page_cap" if fetched >= PAGE_FETCHES_PER_ROASTER else "page_time", roaster["name"])
            rec["page_wait"] = prev.get("page_wait") or today   # waiting since: read first next time
            continue
        fetched += 1
        try:
            raw, text = cached_page(rec["url"])
        except Exception as e:  # noqa: BLE001
            errs.append(f"{type(e).__name__}: {str(e)[:60]}")
            time.sleep(1)
            continue
        if want_parts:
            ps = blend_parts(text)
            if ps:
                rec["parts"] = ps
            else:
                rec["parts_checked"] = 1
        ms = brew_methods(raw, text)
        if len(ms) >= 2:
            # the shop shows which brewers a coffee is for: no filter method means it isn't a V60 coffee
            rec["methods"] = sorted(ms)
            rec["roast_for"] = "filter" if "filter" in ms else "espresso"
        else:
            rec["methods_none"] = True
        start = name_at(text, rec["name"])
        rec["roast_checked"] = ROAST_CHECK
        if not rec.get("roast"):
            r_ = roast_labelled(text[start:start + 6000]) or roast_from_raw(raw) or roast_from_agtron(text) or class_roast(raw)
            if r_:
                rec["roast"], rec["roast_from"] = r_, "page"
                if r_ in ("mdark", "dark") and not rec.get("roast_level"):
                    rec["roast_level"] = "medium-dark" if r_ == "mdark" else "dark"
        got = False
        if "notes" in need:   # the shop's own tasting notes: a labelled line, a sentence, or the page's description tag
            meta = re.search(r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']+)', raw, re.I)
            ns = class_notes(raw, rec["name"]) or page_notes(text, rec["name"], html.unescape(meta.group(1)) if meta else "") or raw_notes(raw, rec["name"])
            ns = [n for n in (ns or []) if not junk_note(n)]   # whatever rule found them, markup is never a note
            if ns:
                rec["notes"], rec["notes_from"], rec["notes_v"] = ns, "page", NOTES_V
                if redo:
                    rec["notes_checked"] = notes_ver(roaster["name"])
                got = True
            elif redo:   # the page read again names none of its own: the list it had was another coffee's
                rec.pop("notes", None); rec.pop("notes_from", None); rec.pop("notes_v", None)
                rec["notes_checked"] = notes_ver(roaster["name"])
            elif rec.get("notes"):
                rec["notes_v"] = NOTES_V   # the short list read again and nothing better: keep it, don't read it again
            else:
                rec["notes_checked"] = notes_ver(roaster["name"])   # read once and the page names none: don't fetch it again just for notes (until the rules change)
            need = [k for k in need if k != "notes"]
        for k in need:
            v = labelled(text, k, start) or (labelled(text, k) if start else None) or raw_labelled(raw, k) or from_json(raw, k) \
                or class_labelled(raw, k) or suffix_labelled(text, k, start)
            if v and k == "variety" and re.match(r"\s*\d+\s?(?:g|gr|kg|oz|lb)\b", v, re.I):
                v = None   # a bag size read as the variety ("250g", Notes' Black Label)
            if not v and k == "process" and not rec.get("blend"):   # a sentence about processing in the description
                v = process_from_text(text[start:start + 4000]) or process_phrase(description_window(text, start))
            if v:
                rec[k], rec[k + "_from"] = v, "page"
                got = True
        if not got and "process" in need and not errs:
            hits = [m.start() for m in re.finditer(r"process", raw, re.I)][:6]
            errs.append("no label; raw HTML around 'process': " + " || ".join(repr(raw[max(0, i - 80):i + 120]) for i in hits))
        filled += got
        time.sleep(0.4)
    if fetched:
        print(f"  page details for {roaster['name']}: {fetched} pages read, {filled} filled" + (f" ({len(errs)} issues, first: {errs[0]})" if errs else ""))
    return fetched


def name_from_url(name, url):
    """A name with no readable letters ("/ [ ]", what was left of a Japanese title, or the Japanese itself) is replaced by the
    words of the product's own link. Names that are numbers ("60/40", "11") are left alone."""
    if re.search(r"[A-Za-zÀ-ÿ]", name or "") or re.fullmatch(r"[\d\s/.,:#&+-]+", name or ""):
        return name
    slug = re.sub(r"[-_]+", " ", urllib.parse.unquote(url.rstrip("/").split("/")[-1].split("?")[0]))
    slug = re.sub(r"\s+", " ", re.sub(r"\b(?:copy|\d{4})\b", " ", slug)).strip()
    return slug.title() if re.search(r"[A-Za-z]{3}", slug) else name


def home_currency(r):
    # a roaster with no country set has no home market to ask for: keep the currency its shop gave (Fandango, in Sweden with
    # no country on file, was asked for pounds and its kronor came back labelled "£270.00")
    return r.get("currency") or COUNTRY_CCY.get(r.get("country")) or r.get("_ccy") or ("EUR" if r.get("region") == "Europe" else "GBP")


def shop_currency(shop, kind, r, extra=""):
    if r.get("currency"):
        return r["currency"]
    try:
        if kind == "shopify":
            c = get_json(f"{shop}/cart.js?{extra.lstrip('&')}", tries=1).get("currency")
            if c:
                return c
        else:
            d = get_json(f"{shop}/wp-json/wc/store/v1/products?per_page=1", tries=1)
            c = d and d[0].get("prices", {}).get("currency_code")
            if c:
                return c
    except Exception:  # noqa: BLE001
        pass
    return COUNTRY_CCY.get(r.get("country", "GB"), "EUR" if r.get("region") == "Europe" else "GBP")


def scan_roaster(r):
    shop = r["shop"].rstrip("/")
    errors = []
    feed = (r.get("feed") or "").rstrip("/")   # a headless Shopify store's own myshopify.com address
    for kind, fn in (("shopify", fetch_shopify), ("woocommerce", fetch_woo), ("squarespace", fetch_squarespace), ("sitemap", fetch_generic)):
        try:
            if feed and kind != "shopify":
                continue
            items = fn(feed) if feed else fn(shop, max_pages=r.get("pages") or 45, lists=r.get("list")) if kind == "sitemap" and (r.get("pages") or r.get("list")) else fn(shop)
            for i in items if feed else []:   # links still go to the shop people actually use
                i["url"] = shop + i["url"][len(feed):]
            if items:
                if kind == "sitemap":
                    home = home_currency(r)
                    is_shopify = any(i.get("via") == "js" for i in items)

                    def seen_in(its, extra=""):
                        if r.get("currency"):   # set by hand in roasters.json: the shop's own data can be wrong (Conscious says USD, sells in pounds)
                            return r["currency"]
                        if is_shopify:   # product .js carries no currency: ask the shop's cart, as for Shopify feeds
                            return shop_currency(shop, "shopify", r, extra)
                        found = [i["currency"] for i in its if i.get("currency")]
                        return max(set(found), key=found.count) if found else home
                    seen = seen_in(items)
                    if seen != home:
                        # the scanner runs abroad, so the shop showed foreign prices (Friedhats came back in USD):
                        # ask again for the shop's home market before giving up on prices
                        extra = f"country={r.get('country') or 'GB'}&currency={home}"
                        try:
                            again = fetch_generic(shop, extra=extra)
                            if again and seen_in(again, extra) == home:
                                items, seen = again, home
                        except Exception:  # noqa: BLE001
                            pass
                    r["_ccy"] = seen
                    if seen != home:   # still another currency: kept, in the currency the shop gave (the site shows it in pounds)
                        r["_note"] = f"prices in {seen}, not {home}"
                else:
                    r["_ccy"] = shop_currency(shop, kind, r)
                    home = home_currency(r)
                    if kind == "shopify" and r["_ccy"] != home:
                        # Shopify Markets priced the scanner as abroad (Girls Who Grind came back in SHP, +2%).
                        # Ask for the home market; if the shop won't, hide prices rather than show wrong ones.
                        extra = f"&country={r.get('country') or 'GB'}&currency={home}"
                        try:
                            if shop_currency(shop, kind, r, extra) == home:
                                items, r["_ccy"] = fetch_shopify(shop, extra), home
                        except Exception:  # noqa: BLE001
                            pass
                        if r["_ccy"] != home:   # kept in the currency the shop gave: the site converts every price to pounds
                            r["_note"] = f"prices in {r['_ccy']}, not {home}"
                return kind, items, None
        except Exception as e:  # noqa: BLE001
            errors.append(f"{kind}: {type(e).__name__}: {str(e)[:80]}")
            continue
        d = DIAG.get(shop) if kind == "sitemap" else None
        errors.append(f"{kind}: no product data" + (f" ({d['sitemap_urls']} product URLs in sitemap, {d['pages_ok']} pages read, {d['pages_blocked']} blocked; e.g. {d['sample']})" if d else ""))
    return None, [], "; ".join(errors + [probe_site(shop)]) or "no products found"


def probe_site(shop):
    """One line about a shop we couldn't read: what platform the home page says it runs, and what the sitemap answers."""
    bits = []
    try:
        home = get_text(shop, tries=1, limit=400_000)
        gen = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', home, re.I)
        plat = next((p for p in ("Shopify", "Squarespace", "Wix", "WooCommerce", "Magento", "PrestaShop", "BigCommerce", "Webflow", "Shopware", "Ecwid", "Lightspeed")
                     if p.lower() in home.lower()), None)
        links = sorted(set(re.findall(r'href=["\'](/[^"\'#?]*(?:product|shop|coffee|kaffe|caf)[^"\'#?]*)', home, re.I)))[:6]
        bits.append(f"home ok ({len(home)} B, generator={gen.group(1) if gen else '-'}, looks like {plat or '?'}, links {links})")
    except Exception as e:  # noqa: BLE001
        bits.append(f"home {type(e).__name__}: {str(e)[:60]}")
    for path in ("/sitemap.xml", "/robots.txt"):
        try:
            t = get_text(shop + path, tries=1, limit=200_000)
            bits.append(f"{path} ok {len(t)} B: {t[:120]!r}")
        except Exception as e:  # noqa: BLE001
            bits.append(f"{path} {type(e).__name__}: {str(e)[:40]}")
    return "probe: " + " | ".join(bits)


INSPECT_WORDS = r"obr[óo]bk|odmian|metod|zaparz|przelew|kawiark|ekspres|proces|verwerk|vari[eë]t|bereid|zetmethode|espresso|filter|drip|v60|chemex|aeropress|moka|french|cold ?brew|process|variet|brew"


def notes_audit(n):
    """For coffees whose page was read and gave no notes: one per roaster (the roasters missing most first), read the page
    and print what the reader sees near words like 'notes', 'flavour', 'taste' or 'cup', so a missed layout shows up
    without opening every coffee by hand. Run from the workflow as inspect 'audit:N'; nothing is saved."""
    rel = json.load(open(OUT))
    rel = rel.get("releases", rel) if isinstance(rel, dict) else rel
    by = {}
    for r in rel:
        by.setdefault(r["roaster"], []).append(r)
    rank = sorted(by, key=lambda k: -sum(not r.get("notes") for r in by[k]) / len(by[k]) * min(len(by[k]), 20))
    done = 0
    for k in rank:
        miss = [r for r in by[k] if not r.get("notes") and r.get("url") and r.get("notes_checked")]
        if not miss or done >= n:
            continue
        r = miss[0]; done += 1
        try:
            raw, text = cached_page(r["url"])
        except Exception as e:  # noqa: BLE001
            print(f"\nAUDIT {k}: {r['url']}  {type(e).__name__}"); continue
        meta = re.search(r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']+)', raw, re.I)
        got = class_notes(raw, r["name"]) or page_notes(text, r["name"], html.unescape(meta.group(1)) if meta else "") or raw_notes(raw, r["name"])
        print(f"\nAUDIT {k} ({sum(not x.get('notes') for x in by[k])}/{len(by[k])} without notes): {r['name']}  {r['url']}  -> {got}")
        st, shown = name_at(text, r["name"]), 0
        for m in re.finditer(r"[^\n]*\b(?:notes?|flavou?rs?|taste[sd]?|tasting|cup|profile|aroma|we get|expect)\b[^\n]*(?:\n[^\n]{0,160})?", text[st:st + 6000], re.I):
            if shown < 6:
                shown += 1; print("   |", re.sub(r"\s+", " ", m.group(0))[:240])


def inspect(urls):
    """Print what a product page says about process, variety and brew methods (labels, icons), so new page layouts
    can be supported without guessing. Run from the workflow with the 'inspect' input; nothing is saved."""
    for url in urls:
        if url.startswith("audit:"):
            notes_audit(int(url[6:] or 40)); continue
        dump = url.startswith("raw:")   # raw:<url> prints the page source itself, for writing a reader for a custom shop
        words = url.startswith("text:")   # text:<url> prints only the page's visible words (a long policy page, say)
        url = url[4:] if dump else url[5:] if words else url
        try:
            raw = get_text(url, tries=1)
        except Exception as e:  # noqa: BLE001
            print(f"INSPECT {url}: {e}"); continue
        if words:
            text = strip_html(re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<noscript\b.*?</noscript>", " ", raw, flags=re.S | re.I))
            print(f"\nTEXT {url}  ({len(text)} characters)")
            for i in range(0, min(len(text), 60000), 1000):
                print("  |", text[i:i + 1000])
            continue
        if dump:
            print(f"\nRAW {url}  ({len(raw)} bytes)")
            for line in re.sub(r"<style\b.*?</style>", "", raw, flags=re.S | re.I)[:120000].splitlines():
                line = line.strip()
                for i in range(0, len(line), 1000):   # long lines (inline JSON) in pieces, nothing cut off
                    print("  |", line[i:i + 1000])
            continue
        body = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", raw, flags=re.S | re.I)
        print(f"\nINSPECT {url}  ({len(raw)} bytes)")
        h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", body, re.S | re.I)
        print("  h1:", re.sub(r"<[^>]+>|\s+", " ", h1.group(1)).strip() if h1 else None)
        for p in ld_products(raw)[:1]:
            print("  json-ld:", json.dumps({k: p.get(k) for k in ("name", "category", "additionalProperty", "description")}, ensure_ascii=False)[:900])
        seen = set()
        for m in re.finditer(r"<(?:img|svg|i|span|use|li|div|a)\b[^>]*(?:alt|title|aria-label|class|data-[\w-]+|href)=[\"'][^\"']*(?:" + INSPECT_WORDS + r")[^\"']*[\"'][^>]*>", body, re.I):
            tag = re.sub(r"\s+", " ", m.group(0))[:220]
            if tag not in seen and len(seen) < 25:
                seen.add(tag); print("  tag:", tag)
        text = strip_html(body)
        for m in list(re.finditer(r"\b(?:[A-Z]{1,2}-?)?\d{4,5}\s+[A-ZÄÖÜ][\wäöüßé.-]+(?:\s[A-ZÄÖÜ][\wäöüß.-]+)?", text))[:4]:   # a postcode and town (legal notice / footer)
            print("  address:", re.sub(r"\s+", " ", text[max(0, m.start() - 60): m.end() + 20]))
        hits = 0
        for m in re.finditer(INSPECT_WORDS, text, re.I):
            snip = re.sub(r"\s+", " ", text[max(0, m.start() - 80): m.end() + 140])
            if snip in seen or hits >= 30:
                continue
            seen.add(snip); hits += 1; print("  text:", snip)


def write_report(today, only, found, ok, total):
    """What this run left for another day, in data/scan_report.json and on the run's page (GitHub step summary)."""
    mins = round((time.monotonic() - SCAN_T0) / 60)
    pages = {}
    for k in ("page_time", "page_cap"):
        for shop, n in REPORT[k].items():
            pages[shop] = pages.get(shop, 0) + n
    waiting = sorted(pages.items(), key=lambda kv: -kv[1])
    rep_ = {"date": today, "scope": "full" if not only else "only: " + ", ".join(sorted(only)), "minutes": mins,
            "limits": {"page_time_hit": bool(REPORT["page_time"]), "shop_cap_hit": bool(REPORT["page_cap"]),
                       "run_time_hit": bool(REPORT["not_reached"]), "page_minutes": PAGE_MINUTES, "stop_minutes": STOP_MINUTES,
                       "pages_per_shop": PAGE_FETCHES_PER_ROASTER},
            "pages_waiting": sum(pages.values()), "pages_waiting_by_shop": dict(waiting),
            "prices_waiting": sum(REPORT["price_time"].values()) + sum(REPORT["price_cap"].values()),
            "roasters_not_reached": sorted(REPORT["not_reached"]), "roasters_ok": ok, "roasters": total,
            "coffees": len(found), "with_notes": sum(1 for x in found if x.get("notes"))}
    if only and REPORT_FILE.exists():   # a rescan of a few shops: keep the full scan's report, add this one under it
        try:
            full = json.loads(REPORT_FILE.read_text())
            full["last_rescan"] = rep_
            rep_ = full
        except Exception:  # noqa: BLE001
            pass
    REPORT_FILE.write_text(json.dumps(rep_, ensure_ascii=False, indent=1) + "\n")
    r0 = rep_.get("last_rescan") if only else rep_
    hit = [w for w, k in (("page time (" + str(PAGE_MINUTES) + " min)", "page_time_hit"), ("pages per shop (" + str(PAGE_FETCHES_PER_ROASTER) + ")", "shop_cap_hit"),
                          ("run time (" + str(STOP_MINUTES) + " min)", "run_time_hit")) if r0["limits"][k]]
    lines = [f"## Scan {today} ({r0['scope']}), {r0['minutes']} min",
             f"**Limits hit:** {', '.join(hit) if hit else 'none, everything was read'}",
             f"**Pages left for tomorrow:** {r0['pages_waiting']}" + (" (" + ", ".join(f"{k} {v}" for k, v in list(r0['pages_waiting_by_shop'].items())[:12]) + ")" if r0['pages_waiting'] else ""),
             f"**Prices left for tomorrow:** {r0['prices_waiting']}",
             f"**Roasters not reached** (kept yesterday's coffees): {', '.join(r0['roasters_not_reached']) or 'none'}",
             f"**Coffees:** {r0['coffees']}, {r0['with_notes']} with tasting notes"]
    print("\n" + "\n".join(lines))
    import os
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("\n".join(lines) + "\n")


def main():
    today = datetime.now(timezone.utc).date().isoformat()
    args = sys.argv[1:]
    if "--inspect" in args:
        inspect([u.strip() for u in args[args.index("--inspect") + 1].split(",") if u.strip()])
        return
    if "--fixture" in args:
        data = json.loads(Path(args[args.index("--fixture") + 1]).read_text())
        shop = args[args.index("--shop") + 1]
        r = {"name": "Fixture Roaster", "shop": shop}
        items = []
        for p in data["products"]:
            variants = p.get("variants") or []
            items.append({"title": p["title"], "type": p.get("product_type", ""), "tags": p.get("tags", []),
                          "body": strip_html(p.get("body_html", "")), "variants": " / ".join(v.get("title", "") for v in variants),
                          "available": any(v.get("available", True) for v in variants),
                          "price": min(float(v["price"]) for v in variants), "url": f"{shop}/products/{p['handle']}",
                          "published": p.get("published_at", "")[:10]})
        for it in items:
            print(json.dumps(classify(it, r), ensure_ascii=False))
        for line in REJECTED:
            print("skipped:", line)
        return

    roasters = load_roasters()
    only = None
    if "--only" in args:   # rescan just these roasters (comma-separated names), keep everyone else as is
        only = {n.strip().lower() for n in args[args.index("--only") + 1].split(",") if n.strip()}
        roasters = [r for r in roasters if r["name"].lower() in only]
    old, first_seen = {}, {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text())
            for x in prev.get("releases", []):
                old[x["url"]] = x
            for st in prev.get("roasters", []):
                if st.get("first_seen") or st.get("platform"):   # a roaster whose shop was down for one scan keeps its date
                    first_seen[st["name"]] = st.get("first_seen") or prev.get("updated")
        except Exception:  # noqa: BLE001
            pass

    # The published list drops duplicates (a coffee sold under two pages, two sizes), so it can't be the only memory of when
    # a page was first seen: the dropped page came back as "new today" at every scan and took the listing's date with it.
    seen_at = {}
    if SEEN.exists():
        try:
            seen_at = json.loads(SEEN.read_text())
        except Exception:  # noqa: BLE001
            seen_at = {}
    for u, x in old.items():
        if x.get("found") and x["found"] < seen_at.get(u, "9"):
            seen_at[u] = x["found"]

    found, status = [], []
    prev_status = []
    if only and OUT.exists():
        try:
            prev = json.loads(OUT.read_text())
            prev_status = [st for st in prev.get("roasters", []) if st["name"].lower() not in only]
            found = [x for x in prev.get("releases", []) if x["roaster"].lower() not in only]
        except Exception:  # noqa: BLE001
            pass
    # shops with the most pages left waiting last time start first, so the time budget doesn't fall on them again
    try:
        last = json.loads(REPORT_FILE.read_text()) if REPORT_FILE.exists() else {}
        waiting = {k: v for k, v in (last.get("pages_waiting_by_shop") or {}).items()}
        behind = set(last.get("roasters_not_reached") or [])   # not reached last time: first in line today, so a longer list never leaves the same shops out twice
        roasters.sort(key=lambda r_: (r_["name"] not in behind, -waiting.get(r_["name"], 0)))
    except Exception:  # noqa: BLE001
        pass
    scanned_ok = set()
    def run(r):
        """Fetch and classify one roaster (runs in a thread pool: page look-ups made one-by-one were too slow)."""
        r["_old"] = old
        if time.monotonic() - SCAN_T0 > STOP_MINUTES * 60:
            with REPORT_LOCK:
                REPORT["not_reached"].append(r["name"])
            return None, "out of time today: yesterday's coffees kept", []
        kind, items, err = scan_roaster(r)
        recs = []
        if kind:
            for it in items:
                rec = classify(it, r)
                if rec and rec["url"].rstrip("/").split("//")[-1].replace("www.", "") == r["shop"].rstrip("/").split("//")[-1].replace("www.", ""):
                    rec = None   # a "coffee" whose link is the shop's front page (Doubleshot: "Farm", "Fun") can't be opened or checked
                if rec:
                    rec["name"] = name_from_url(rec["name"], rec["url"])
                    rec["found"] = seen_at.get(rec["url"]) or old.get(rec["url"], {}).get("found", today)
                    recs.append(rec)
            add_page_details(recs, r, old)
            add_page_prices(recs, r, old)   # for every shop: it once sat under the roast line below and ran for two roasters only
        if r.get("roast"):   # a roaster that roasts every filter coffee the same way says so once in roasters.json
            for rec in recs:
                if not rec.get("roast") and rec.get("roast_for") != "espresso":
                    rec["roast"], rec["roast_from"] = r["roast"], "roaster"
        return kind, err, recs

    # A split scan: four machines each read a quarter of the roasters at once (--shard k/4 --part file), and one more puts the
    # quarters together (--merge folder) and writes the list. Each quarter is every fourth roaster of the same ordered list, so the
    # shops left behind last time are spread over all four. A quarter that never arrives counts as not reached: yesterday's coffees stay
    global SCAN_T0
    if "--shard" in args:
        k, n = (int(x) for x in args[args.index("--shard") + 1].split("/"))
        mine = [r for j, r in enumerate(roasters) if j % n == k]
        with ThreadPoolExecutor(max_workers=16) as pool:
            res = list(pool.map(run, mine))
        part = {"minutes": round((time.monotonic() - SCAN_T0) / 60), "report": REPORT, "drops": DROPS, "rejected": REJECTED, "price_diag": PRICE_DIAG,
                "roasters": {r["name"]: {"kind": kind, "err": err, "recs": recs, "note": r.get("_note"), "ccy": r.get("_ccy")}
                             for r, (kind, err, recs) in zip(mine, res)}}
        out = Path(args[args.index("--part") + 1]); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(part, ensure_ascii=False, default=lambda o: sorted(o) if isinstance(o, (set, frozenset)) else str(o)))
        for r, (kind, err, recs) in zip(mine, res):
            print(f"{r['name']:<26} {kind or 'FAILED':<12} {len(recs):>3} {err or ''}")
        print(f"\nPart {k + 1} of {n}: {len(mine)} roasters, {sum(len(x[2]) for x in res)} coffees, {part['minutes']} min -> {out}")
        return
    if "--merge" in args:
        got, mins = {}, 0
        for f in sorted(Path(args[args.index("--merge") + 1]).rglob("*.json")):
            try:
                p = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            got.update(p.get("roasters") or {}); mins = max(mins, p.get("minutes") or 0)
            for key in ("page_time", "page_cap", "price_time", "price_cap"):
                REPORT[key].update((p.get("report") or {}).get(key) or {})
            REPORT["not_reached"].extend((p.get("report") or {}).get("not_reached") or [])
            DROPS.update(p.get("drops") or {}); REJECTED.extend(p.get("rejected") or []); PRICE_DIAG.update(p.get("price_diag") or {})
        SCAN_T0 = time.monotonic() - mins * 60   # the report gives the longest quarter's time
        results = []
        for r in roasters:
            g = got.get(r["name"])
            if g is None:
                REPORT["not_reached"].append(r["name"])
                results.append((None, "its part of today's scan didn't finish: yesterday's coffees kept", []))
            else:
                r["_note"], r["_ccy"] = g.get("note"), g.get("ccy")
                results.append((g.get("kind"), g.get("err"), g.get("recs") or []))
        print(f"Put together {len(got)} of {len(roasters)} roasters from the parts, longest part {mins} min")
    else:
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(run, roasters))
    for r, (kind, err, recs) in zip(roasters, results):
        kept = len(recs)
        if kind:
            scanned_ok.add(r["name"])
            found.extend(recs)
        if kind and r["name"] not in first_seen:
            first_seen[r["name"]] = today
        status.append({"name": r["name"], "shop": r["shop"], "market": r.get("region", "UK"), "country": r.get("country"),
                       "first_seen": first_seen.get(r["name"]), "note": r.get("_note"),
                       "currency": r.get("_ccy"), "platform": kind, "coffees": kept, "error": err})
        print(f"{r['name']:<26} {kind or 'FAILED':<12} {kept:>3} {err or ''}")

    status = prev_status + status
    # keep last week's coffees from roasters that failed this time (temporary outages),
    # but never from a roaster that has left data/roasters.json (one that asked to be removed goes at once)
    urls = {x["url"] for x in found}
    listed = {r["name"] for r in load_roasters()}
    for u, x in old.items():
        if x["roaster"] not in scanned_ok and u not in urls and x["roaster"] in listed:
            found.append(x)

    # safety net: re-check everything that will be published, including entries carried over from
    # earlier scans (they were classified under older rules and only keep name + url)
    def still_beans(x):
        probe = {"title": x.get("name", ""), "type": "", "tags": [], "variants": "", "body": "", "url": x.get("url", "")}
        why = not_beans(probe) or not_one_coffee(probe) or (f"not coffee ({EXCLUDE.search(probe['title']).group(0)})" if EXCLUDE.search(probe["title"]) else None)
        if why:
            REJECTED.append(f"{x.get('roaster')}: {x.get('name')} ({why}, dropped from list)")
        return not why
    found = [x for x in found if still_beans(x)]
    # specialty only: a shop with a flavoured coffee on its shelf is banned (all its coffees go, and it is never scanned or
    # added again); a robusta is dropped wherever it turns up
    gone, shop_of = banned(), {r["name"]: r.get("shop") for r in load_roasters()}
    for x in found:
        f = flavoured(x.get("name"))
        h = host_of(shop_of.get(x["roaster"]))
        if f and h and h not in gone:
            gone[h] = {"name": x["roaster"], "why": f"flavoured coffee: {x.get('name')}", "on": datetime.now(timezone.utc).date().isoformat()}
            print(f"BANNED {x['roaster']} ({h}): flavoured coffee '{x.get('name')}'")
    # every roaster read today: one that rarely states process or variety goes on watch, and is banned once it has failed for
    # WEAK_DAYS days running (never on one bad read)
    try:
        weak = json.loads(WEAK.read_text())
    except (OSError, ValueError):
        weak = {}
    day = datetime.now(timezone.utc).date()
    for name in sorted(scanned_ok):
        h = host_of(shop_of.get(name))
        if not h or h in gone:
            continue
        if rarely_states([x for x in found if x["roaster"] == name]):
            w = weak.get(h) if isinstance(weak.get(h), dict) else {"since": day.isoformat(), "days": [], }
            if day.isoformat() not in w["days"]:
                w["days"].append(day.isoformat())   # one count a day, however many scans run
            weak[h] = w
            if len(w["days"]) >= WEAK_DAYS:   # read and found wanting on seven separate days, with no good read in between
                gone[h] = {"name": name, "why": f"its coffees rarely state a process or a variety (since {w['since']})", "on": day.isoformat()}
                weak.pop(h, None)
                print(f"BANNED {name} ({h}): rarely states process or variety since {w['since']}")
            else:
                print(f"ON WATCH {name} ({h}): rarely states process or variety, day {len(w['days'])} of {WEAK_DAYS}")
        else:
            weak.pop(h, None)
    WEAK.write_text(json.dumps(weak, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    if gone != banned():
        BANNED.write_text(json.dumps(gone, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    out_names = {v["name"] for v in gone.values()}
    kept = []
    for x in found:
        if x["roaster"] in out_names:
            continue
        if robusta(x.get("name"), x.get("variety")):
            REJECTED.append(f"{x.get('roaster')}: {x.get('name')} (robusta, dropped from list)"); continue
        kept.append(x)
    found = kept
    for x in found:   # entries carried over from older scans get today's name clean-up too
        x["name"] = tidy_name(x["name"], x["roaster"]) or x["name"]
        flavour_variety(x)   # tasting notes read as the variety go back to being notes
        if UI_WORD.match(x["name"]):   # a theme's button read as the title (Conscious Speciality: every coffee "Close")
            slug = re.sub(r"[-_]+", " ", x["url"].split("?")[0].rstrip("/").rsplit("/", 1)[-1]).strip()
            x["name"] = " ".join(w.capitalize() if w.islower() else w for w in slug.split()) or x["name"]

    # remember every page seen, and give duplicates of one coffee (same roaster, name, process, variety) the earliest date
    # any of them was seen: whichever page ends up listed, the coffee has been around since then
    same = lambda x: (x["roaster"], x["name"].lower(), (x.get("process") or "").lower(), (x.get("variety") or "").lower(), x.get("roast_for") == "espresso")
    earliest = {}
    for x in found:
        if x.get("found"):   # looked up again here, by the address the record ends up with (some change while being read)
            x["found"] = seen_at[x["url"]] = min(x["found"], seen_at.get(x["url"], x["found"]))
            earliest[same(x)] = min(x["found"], earliest.get(same(x), x["found"]))
    for x in found:
        if x.get("found"):
            x["found"] = earliest[same(x)]
            seen_at[x["url"]] = x["found"]
    old_cut = (datetime.now(timezone.utc) - timedelta(days=400)).date().isoformat()
    SEEN.write_text(json.dumps({u: d for u, d in sorted(seen_at.items()) if d >= old_cut}, ensure_ascii=False, indent=0) + "\n")

    cutoff = (datetime.now(timezone.utc) - timedelta(days=NEW_DAYS)).date().isoformat()
    for x in found:
        if x.get("published"):
            x["new"] = x["published"] >= cutoff
        else:   # no listing date: new only if it appeared after we started watching this roaster
            fs = first_seen.get(x["roaster"]) or today
            x["new"] = x.get("found", today) > fs and x.get("found", "") >= cutoff
    week = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    for x in found:
        fs = first_seen.get(x["roaster"]) or today
        x["just_in"] = x.get("found") == today and fs < today and (not x.get("published") or x["published"] >= week)
    found.sort(key=lambda x: (x.get("published") or x.get("found") or ""), reverse=True)
    # one listing per coffee: drop size/variant duplicates and stores that share a catalogue. A roaster that lists
    # one coffee twice (beans and ground, 250 g and 1 kg) keeps the newest listing, with anything it lacks filled
    # in from the other
    seen, per_roaster, deduped, kept = set(), {}, [], {}
    for x in found:
        # a roaster's filter and espresso versions of one coffee are two coffees
        key_same = (x["roaster"], same_name(x["name"]), (x.get("process") or "").lower(), (x.get("variety") or "").lower(), x.get("roast_for") == "espresso")
        key_shared = (x["name"].lower(), x.get("price"), x.get("origin"))
        if key_same in seen or key_shared in seen:
            first = kept.get(key_same)
            if first is not None:
                for k in ("origin", "process", "variety", "roast", "roast_from", "price", "price_from", "methods", "roast_for", "notes"):
                    if x.get(k) and not first.get(k):
                        first[k] = x[k]
            continue
        if per_roaster.get(x["roaster"], 0) >= PER_ROASTER:
            continue
        seen.update([key_same, key_shared])
        kept[key_same] = x
        per_roaster[x["roaster"]] = per_roaster.get(x["roaster"], 0) + 1
        deduped.append(x)
    found = deduped[:MAX_ITEMS]
    # tasting notes in English (the Italian page translates the English); the roaster's own words kept beside them
    for x in found:
        if x.get("notes"):
            en = flavours.english_notes(x["notes"])
            if en and en != x["notes"]:
                x.setdefault("notes_orig", x["notes"])
                x["notes"] = en

    # no price, no listing: a coffee you can't see the price of is almost always sold out, or not sold on its page
    all_found = found
    unpriced = [x for x in found if not x.get("price")]
    if unpriced:
        found = [x for x in found if x.get("price")]
        by = {}
        for x in unpriced:
            by[x["roaster"]] = by.get(x["roaster"], 0) + 1
        print(f"\nNot listed, no price: {len(unpriced)} (" + ", ".join(f"{n} {c}" for n, c in sorted(by.items(), key=lambda t: -t[1])[:8]) + ")")
    OUT.write_text(json.dumps({"updated": today, "new_window_days": NEW_DAYS, "roasters": status,
                               "releases": found}, ensure_ascii=False, indent=1) + "\n")
    print(f"\n{len(found)} coffees from {len(scanned_ok)}/{len(roasters)} roasters -> {OUT.relative_to(ROOT)}")
    write_report(today, only, found, len(scanned_ok), len(roasters))
    miss = {}
    for x in all_found:
        miss.setdefault(x["roaster"], [0, 0])[0 if x.get("price") else 1] += 1
    bad = sorted(((n, a, b) for n, (a, b) in miss.items() if b and b >= a), key=lambda t: -t[2])
    print("\nRoasters with most coffees on 'Price on site': " + (", ".join(f"{n} {b}/{a + b}" for n, a, b in bad) or "none"))
    for shop_url, d in PRICE_DIAG.items():
        print(f"  no price sample {shop_url}: {d}")
    print("\nWhy products were not listed, per roaster (review this when a shop looks thin):")
    for name in sorted(DROPS):
        reasons = DROPS[name]
        print(f"  {name}: " + ", ".join(f"{k} {len(v)}" for k, v in sorted(reasons.items(), key=lambda kv: -len(kv[1]))))
        for k, v in reasons.items():
            if k != "sold out":
                print(f"      {k}: " + " | ".join(v[:6]))
    # watch list: coffees still without a process, by roaster, so a new page layout shows up in the log
    miss = {}
    for x in found:
        if not x.get("process") and not x.get("blend"):
            miss.setdefault(x["roaster"], []).append(x["name"])
    if miss:
        print(f"\nNo process found ({sum(len(v) for v in miss.values())} single origins), most first:")
        for name, xs in sorted(miss.items(), key=lambda kv: -len(kv[1]))[:25]:
            print(f"  {name}: {len(xs)} ({' | '.join(xs[:4])})")
    if REJECTED:
        print(f"\nNot coffee beans, skipped ({len(REJECTED)}):")
        for line in REJECTED:
            print("  " + line)


if __name__ == "__main__":
    main()

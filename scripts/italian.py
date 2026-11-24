"""The Italian site at goccio.co.uk/it: the same page, its own address, so Google can find it in Italian.

Run by the publish workflow on the copy of the site it is about to upload:

    python3 scripts/italian.py /tmp/site

The page itself turns Italian at /it (index.html, LANG). This writes it/index.html with what has to be Italian before any
script runs: the language, the title, the description, the link previews, and the address Google should keep for it.
"""
import sys
from pathlib import Path

site = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
s = (site / "index.html").read_text(encoding="utf-8")
BASE = "https://www.goccio.co.uk"
TITLE_EN = "Goccio: every new coffee, with its recipe before you buy"
TITLE_IT = "Goccio: ogni nuovo caffè, con la sua ricetta prima di comprarlo"
DESC_IT = ("Ogni nuovo caffè specialty da oltre 700 torrefazioni, controllato ogni giorno, con la ricetta per il tuo metodo e il tuo "
           "macinino: macinatura, rapporto, temperatura e ogni passaggio.")
rep = [('<html lang="en"', '<html lang="it"'), (f"<title>{TITLE_EN}</title>", f"<title>{TITLE_IT}</title>"),
       (f'content="{TITLE_EN}"', f'content="{TITLE_IT}"'),
       ('<meta property="og:url" content="https://www.goccio.co.uk/"><link rel="canonical" href="https://www.goccio.co.uk/">',
        f'<meta property="og:url" content="{BASE}/it/"><link rel="canonical" href="{BASE}/it/">'),
       ('<meta property="og:locale" content="en_GB">', '<meta property="og:locale" content="it_IT">')]
for a, b in rep:
    s = s.replace(a, b)
import re
s = re.sub(r'(<meta (?:name|property)="(?:description|og:description|twitter:description)" content=")[^"]*(")', lambda m: m.group(1) + DESC_IT + m.group(2), s)
(site / "it").mkdir(exist_ok=True)
(site / "it" / "index.html").write_text(s, encoding="utf-8")
print("it/index.html written:", s.count('lang="it"'), "lang, title", TITLE_IT in s)

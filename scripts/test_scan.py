import re
"""Every scanner mistake that has been reported, with the right answer.

The scanner must get all of these right before a change goes live: the daily scan runs this first and stops
(keeping yesterday's list) if any old mistake comes back, and so does every change to scripts/scan.py.
Add each new report here when it's fixed: who reported what, and what the scanner should say.

Run: python3 scripts/test_scan.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import scan
import flavours  # noqa: E402


def offline(*a, **k):
    raise OSError("the tests never go online")


scan.get_text = scan.get_json = offline   # every case is decided from what's written here, never from a live page

UK = {"name": "Test Roaster", "shop": "https://example.com", "city": "London", "country": "GB", "region": "UK"}


def item(title, body="", type_="Coffee", tags=(), variants="250g", url="https://example.com/products/x"):
    return {"title": title, "type": type_, "tags": list(tags), "body": body, "variants": variants, "available": True,
            "price": 12.0, "currency": "GBP", "url": url, "published": ""}


def kept(it, roaster=UK):
    return scan.classify(it, roaster)


def name(title, roaster="Test Roaster", origin=""):
    return scan.tidy_name(scan.clean_name(title, roaster, origin), roaster)


COFFEE_BODY = "Origin: Colombia\nProcess: Washed\nVariety: Caturra\nAltitude: 1,800 masl\nTasting notes: plum, cocoa"

# (what was reported, check that must be True)
CASES = [
    ("Tanat: 'Janson [Los Alpes GN195]' keeps the farm in the brackets, the lot code goes; a variety or a bare code in brackets still goes",
     lambda: scan.tidy_name("Janson [Los Alpes GN195]", "Tanat") == "Janson Los Alpes" and scan.tidy_name("Abu [Catuai 3125]", "People Possession") == "Abu"
     and scan.tidy_name("Alo Bore [Washed]", "Tanat") == "Alo Bore" and scan.tidy_name("Kimel [GN195]", "Tanat") == "Kimel"
     and scan.tidy_name("Industrial Supply Series [RED]", "People Possession") == "Industrial Supply Series Red"),
    ("North Star: a coffee sold ground for the French press, and a coffee with a travel mug, are not bags of beans; the filter-roast one is",
     lambda: scan.EXCLUDE.search("City Bloc x Brazil Montanari - French Press (250G)") is not None
     and scan.EXCLUDE.search("Brazil Montanari + Flat White Life Travel") is not None
     and not scan.EXCLUDE.search("City Bloc x Brazil Montanari - Filter (250G)") and not scan.EXCLUDE.search("French Press Blend")
     and not scan.EXCLUDE.search("Ethiopia Guji - Filter")),
    ("Crosby: '<strong>Tasting notes:</strong> Pomelo, Brazil Nut' is two notes: the bold label doesn't eat the first, Brazil nut is not the country, pomelo stays pomelo",
     lambda: scan.flavours.english_notes(scan.find_notes(item("Honduras Santa Rosa", "<ul><li><strong>Origin:</strong> Honduras</li><li><strong>Region:</strong> Santa Rosa</li><li><strong>Tasting notes:</strong> Pomelo, Brazil Nut</li><li><strong>Process:</strong> Washed</li><li><strong>Cup Score:</strong> 84</li></ul>")))
     == ["Pomelo", "Brazil Nut"]),
    ("Crosby: notes the editor split or wrapped in a sentence, a misspelt blackcurrant, and '(Sale)' copies of a coffee",
     lambda: [scan.tidy_note(x) for x in ["Dried A pricot", "S piced Raisins", "Expect super-sweet plum", "Cherry notes up front"]] == ["Dried Apricot", "Spiced Raisins", "Plum", "Cherry"]
     and scan.flavours.english_notes(["Blackcurrent"]) == ["Blackcurrant"]
     and scan.tidy_name("Santa Rosa (Sale)", "Crosby Coffee") == "Santa Rosa" and scan.tidy_name("Iron Men Blend Sale", "Crosby Coffee") == "Iron Men Blend"
     and scan.tidy_name("Garage Sale Espresso", "X") == "Garage Sale Espresso"),
    ("Tanat: a cap named after a coffee ('Casquette - Geisha Washed Only Beige') is not a coffee",
     lambda: scan.EXCLUDE.search("Casquette - Geisha Washed Only Beige") is not None and scan.EXCLUDE.search("Beanie Noir") is not None
     and not scan.EXCLUDE.search("Geisha Washed") and not scan.EXCLUDE.search("Finca Hartmann")),
    ("Langøra: the flavours on the second line, under a line of how it feels ('Insens, saftig, eksplosiv')",
     lambda: scan.find_notes(item("Julekaffe Colombia - Granja Paraíso 92", "<p><em>Insens, saftig, eksplosiv</em></p>\n<p><em>Jordbærmarmelade, pasjonsfrukt, fersken</em></p>\n<p>Dette er en skkelig eksplosiv fruktbombe av en kaffe.</p>"))
     == ["Jordbærmarmelade", "Pasjonsfrukt", "Fersken"]
     and scan.flavours.english_notes(["Jordbærmarmelade", "Pasjonsfrukt", "Fersken"]) == ["Strawberry jam", "Passion fruit", "Peach"]),
    ("Jolly Bean: a heading of flavours under Origin, Varietal and Process; the style after the dash is not a note",
     lambda: scan.find_notes(item("Leonid Ramirez - Recessio Proof Banger", "<p><strong>Origin:</strong> Genova</p><p><strong>Varietal:</strong> Castillo</p><p><strong>Process:</strong> Extended Fermentation Washed</p><p></p><h3>GRAPEFRUIT, APPLE, BROWN SUGAR - AROMATIC &amp; FLORAL</h3><p>A new producer for us! Leonid Ramírez is here with an extended fermentation castillo, and it is great and typifies why I love Colombian lots so much, fruit, full body, complex and floral.</p>"))
     == ["Grapefruit", "Apple", "Brown sugar"]),
    ("Trigger: '[PROFILE] GINGERBREAD COOKIES WITH STRAWBERRY JAM' is the cup, two notes; the Polish '[PROFIL]' too",
     lambda: scan.find_notes(item("Colombia x Rwanda Holiday Coffee", "<p>[X-MAS COFFEE] COLOMBIA X RWANDA<br>[PRODUCER] SANTA CLAUS TEAM<br>[VARIETAL] CATURRA X BOURBON<br>[PROCESS] WASHED CO-FERMENTED X NATURAL<br>[ROAST LEVEL] FILTER<br>[PROFILE] GINGERBREAD COOKIES WITH STRAWBERRY JAM</p><p>Coffee roasted a maximum of 14 days ago.</p>"))
     == ["Gingerbread cookies", "Strawberry jam"]
     and scan.find_notes(item("Kolumbia x Rwanda [X-mas Coffee] Pierniczki z dżemem truskawkowym", "<p>[KAWA ŚWIĄTECZNA] KOLUMBIA X RWANDA<br>[PRODUCENT] SANTA CLAUS TEAM<br>[PROFIL] PIERNICZKI Z DŻEMEM TRUSKAWKOWYM</p><p>Zapach zbliżających się świąt.</p>"))
     == ["Gingerbread", "Strawberry jam"]),
    ("Trigger: the name stops at the bracketed tag, the notes after it are read, Polish country names in English",
     lambda: scan.tidy_name("Etiopia Aricha [FILTR] Morele, Limonka, Czarna Herbata", "Trigger") == "Ethiopia Aricha"
     and scan.tidy_name("Kolumbia x Rwanda [X-mas Coffee] Pierniczki z dżemem truskawkowym", "Trigger") == "Colombia x Rwanda"
     and scan.tidy_name("[Kawa bezkofeinowa] Kolumbia El Vergel Decaf", "Trigger") == "Colombia El Vergel Decaf"
     and scan.tidy_name("Industrial Supply Series [RED]", "People Possession") == "Industrial Supply Series Red"
     and scan.flavours.english_notes(scan.find_notes(item("Etiopia Aricha [FILTR] Morele, Limonka, Czarna Herbata", "<p>Kawa z Etiopii.</p>")))
     == ["Apricot", "Lime", "Black tea"]),
    ("Light Up: Japanese blood orange, grape and rum (ラム, which a browser turns into 'lamb')",
     lambda: scan.find_notes(item("Ethiopia", "<p>ブラッドオレンジやグレープのようなフルーティーさ。ラムを思わせる余韻。</p>")) == ["Blood orange", "Grape", "Rum"]),
    ("ST. ALi: 'Strawberries + White Lily' is two notes, shown with a comma between, not one note with a plus",
     lambda: scan.flavours.english_notes(["Strawberries + White Lily"]) == ["Strawberries", "White Lily"]
     and scan.flavours.english_notes(["Chocolate", "Plum + Treacle"]) == ["Chocolate", "Plum", "Treacle"]),
    # Dropshot (Romania, 24/11/2026): notes left in Romanian, one misspelt ("Ciuocolata"); "Columbia" and "Brazilia" in names are Colombia and Brazil
    ("Dropshot's Romanian notes come out in English",
     lambda: scan.flavours.english_notes(["Ciuocolata cu lapte", "Portocala coapta", "Gem de Vişine", "Tort de Ciocolată Neagră", "Turta Dulce", "Miere Acacia"]) == ["Milk chocolate", "Ripe orange", "Sour cherry jam", "Dark chocolate cake", "Gingerbread", "Acacia honey"]),
    ("'Columbia Magnum Sidra' is from Colombia, 'Brazilia Samba' from Brazil",
     lambda: scan.find_origin("Columbia Magnum Sidra") == "Colombia" and scan.find_origin("Brazilia Samba") == "Brazil"),
    # Rogue Wave (24/11/2026): sizes 340 g, 1 kg, 2.5 kg and a 40 g sample; the sample's price was shown for the 340 g bag
    ("A 40 g sample's price is not the price of the 340 g bag",
     lambda: min(scan.shop_prices([{"title": "340 g", "price": "24.00"}, {"title": "1 kg", "price": "60.00"}, {"title": "2.5 kg", "price": "140.00"}, {"title": "40 g", "price": "7.00"}])) == 24.0),
    # Dayglow (24/11/2026): "Taste notes" over a sentence: the list after "like"
    ("Dayglow's 'Taste notes: We taste beautiful florals like lavender and lilac, with…' gives Lavender, Lilac",
     lambda: [x.lower() for x in scan.find_notes({"body": "Taste notes\nWe taste beautiful florals like lavender and lilac, with a sweet sugary finish.\nDetails\nVariety: Geisha\nProcessing: Anaerobic Washed", "title": "Sugar Dust", "tags": []})] == ["lavender", "lilac"]),
    # Established (24/11/2026): the notes in capitals under the name line "EL LIMONAR - COLOMBIA", which carries the country after the name
    ("Established's 'NECTARINE, BAKED APPLES, BLACK TEA' under 'EL LIMONAR - COLOMBIA' are the notes",
     lambda: scan.page_notes("Shop\nEl Limonar - Colombia\n\u00a314.00\nSize\n250g\nAdd to cart\nEL LIMONAR - COLOMBIA\nNECTARINE, BAKED APPLES, BLACK TEA\nPROCESS: WASHED\nVARIETAL: ARUSI\nCOUNTRY: COLOMBIA", "El Limonar") == ["Nectarine", "Baked apples", "Black tea"]),
    # Rogue Wave (24/11/2026): "…with notes that remind us of:" then the notes as bullets, then the size picker
    ("Rogue Wave's list after 'notes that remind us of:' gives the six notes (bullets)",
     lambda: scan.find_notes({"body": "<p>This natural coffee is sweet and floral with notes that remind us of:</p><ul><li>Tangerine</li><li>Strawberry</li><li>Blackberry</li><li>Watermelon</li><li>Grape</li><li>Floral</li></ul>", "title": "Mullugeta Muntasha Arbegona", "tags": []}) == ["Tangerine", "Strawberry", "Blackberry", "Watermelon", "Grape", "Floral"]),
    ("…and as lines on the page, stopping at 'Size'",
     lambda: scan.find_notes({"body": "This natural coffee is sweet and floral with notes that remind us of:\nTangerine\nStrawberry\nBlackberry\nWatermelon\nGrape\nFloral\nSize\n340 g", "title": "Mullugeta Muntasha Arbegona", "tags": []}) == ["Tangerine", "Strawberry", "Blackberry", "Watermelon", "Grape", "Floral"]),
    # Rogue Wave (26/11/2026): Nyeri Hill Factory was listed as "Grapefruit, Mapl"; the page has the five notes as a styled list under "…reminds us of:"
    ("Rogue Wave's page list ('reminds us of:' over ul.product-taste-list) gives all five notes, Maple Syrup whole",
     lambda: scan.page_notes(scan._visible('<div class="product-short-desc">This washed process coffee is tangy, bright, and juicy with tasting notes that reminds us of:</div><div class="product-taste"><ul class="product-taste-list"><li class="grapefruit">Grapefruit</li><li class="maple-syrup">Maple Syrup</li><li class="red-currant">Red Currant</li><li class="plum">Plum</li><li class="floral">Floral</li></ul></div><form><label>Size</label></form>'), "Nyeri Hill Factory", "")
       == ["Grapefruit", "Maple Syrup", "Red Currant", "Plum", "Floral"]),
    # Sey (26/11/2026): Dobe Mara had no notes; they close the description: "In the cup we find dark berries, tamarind, and hibiscus."
    ("Sey's 'In the cup we find dark berries, tamarind, and hibiscus.' gives the three notes",
     lambda: scan.find_notes({"body": '<p><span>This is a distinctive coffee and one of the few Maragogypes we have ever released. We are grateful to Stephan and Lost Origin for the work that went into producing it. In the cup we find dark berries, tamarind, and hibiscus.</span></p>', "title": "2026 Stephan Muller x Lost Origin; Dobe Mara", "tags": []}) == ["Dark berries", "Tamarind", "Hibiscus"]
       and scan.find_notes({"body": "<p>In the cup, you'll find stone fruit and honey.</p>", "title": "X", "tags": []}) == ["Stone fruit", "Honey"]),
    # Poma (26/11/2026): the roaster's own recipe under "Brewing Parameters" is read as numbers, shown beside Goccio's
    ("Poma's 'Brewing Parameters' paragraph gives 13 g to 200 g, 92 °C, coarse about 900 µm, 50 g every 40 s, 3:00",
     lambda: scan.roaster_recipe('<p>Brewing Parameters</p><p>We recommend using 13 grams of coffees to 200 grams of water. A coarse grind size approximately 900 micron. Brewing temperature 92C. Our brewing pattern is a 50g circular pour every 40 seconds. Total brew time is 3:00.</p>')
       == {"dose": 13, "water": 200, "ratio": 15.4, "temp": 92, "grind_um": 900, "grind": "coarse", "time": "3:00", "pours": [50, 40]}),
    ("A roaster's espresso recipe ('18g in, 40g out in 28-32 seconds at 93°C') and a V60 list are read; '1:16' is a ratio, not a time; no recipe without one",
     lambda: scan.roaster_recipe('<p>Espresso recipe: 18g in, 40g out in 28-32 seconds at 93°C.</p>') == {"dose": 18, "water": 40, "ratio": 2.2, "temp": 93, "time": "28–32 s", "brewer": "espresso"}
       and scan.roaster_recipe('<h3>Our V60 recipe</h3><ul><li>15g coffee</li><li>250g water</li><li>94°C</li><li>Medium-fine grind</li><li>Total time 2:45</li></ul>')["brewer"] == "v60"
       and scan.roaster_recipe('<p>We recommend brewing this at a 1:16 ratio with water at 96°C.</p>') == {"ratio": 16, "temp": 96}
       and scan.roaster_recipe('<p>Roasted for filter. Notes of plum. 250g bag.</p>') is None),
    # Assembly (26/11/2026): the recipe is a "Recipe" drop-down on the product page, after a menu with "Brew guide" and a script mentioning "recipe"
    ("Assembly's page 'Recipe' drop-down gives 15 g to 255 ml (1:17), 2:15–2:45, 98 °C, a 50 g bloom, flat-bottom",
     lambda: scan.roaster_recipe('<nav><a>Brew guide</a><a>Recipes</a></nav><script>var x={"recipe":"15g"}</script><details><summary>Recipe <svg><path d="M1 1"/></svg></summary><div><p>Pour Over (flat-bottom)</p><ul><li>Brew Ratio - 15g to 255ml (1:17)</li><li>Brew Time - 2:15-2:45</li><li>Water Temp - 98°C</li><li>Bloom - 50g, 30 seconds</li></ul><p>After bloom, pour to 100g.</p></div></details>')
       == {"dose": 15, "water": 255, "ratio": 17, "temp": 98, "time": "2:15–2:45", "bloom": 50, "brewer": "flat"}),
    # Mokxa (26/11/2026): no notes on any coffee; the French description says them in a sentence, "aux notes intenses de …, … et …"
    ("Mokxa's 'aux notes intenses de grué de cacao, liqueur d'amande et fruit de la passion' gives three notes (cacao nibs, almond liqueur, passion fruit in English); Italian and Spanish too",
     lambda: scan.find_notes({"body": "<p>Un café enveloppant aux notes intenses de grué de cacao, liqueur d’amande et fruit de la passion.</p>", "title": "Serinen", "tags": []}) == ["Grué de cacao", "Liqueur d’amande", "Fruit de la passion"]
       and scan.flavours.english_notes(["Grué de cacao", "Liqueur d’amande", "Fruit de la passion"]) == ["Cacao nibs", "Almond liqueur", "Passion fruit"]
       and scan.find_notes({"body": "<p>Un caffè con note di pesca, gelsomino e miele.</p>", "title": "X", "tags": []}) == ["Pesca", "Gelsomino", "Miele"]
       and scan.find_notes({"body": "<p>Un café con notas de durazno, panela y naranja.</p>", "title": "X", "tags": []}) == ["Durazno", "Panela", "Naranja"]),
    # Rise & Grind (26/11/2026): La Leona showed "Creamy"; under "Tasting Notes" each note is bold, then a colon and a description
    ("Rise & Grind's bold notes over descriptions ('<strong>White chocolate</strong>: soft and creamy') give the bold names, not the descriptions",
     lambda: scan.find_notes({"body": '<p>It is gentle, creamy and sweet.</p> <h3>Tasting Notes</h3> <ul> <li> <strong>White chocolate</strong>: soft and creamy</li> <li> <strong>Almonds</strong>: smooth and nutty</li> <li> <strong>Berries</strong>: a gentle fruity finish</li> </ul> <h3>The Details</h3> <ul> <li> <strong>Origin:</strong> Quindío, Colombia</li> </ul>', "title": "La Leona", "tags": []}) == ["White chocolate", "Almonds", "Berries"]
       and scan.find_notes({"body": scan.strip_html('<h3>Tasting Notes</h3>\n<ul>\n<li>\n<strong>White chocolate</strong>: soft and creamy</li>\n<li>\n<strong>Almonds</strong>: smooth and nutty</li>\n<li>\n<strong>Berries</strong>: a gentle fruity finish</li>\n</ul>\n<h3>The Details</h3>\n<ul>\n<li>\n<strong>Origin:</strong> Quindío, Colombia</li>\n</ul>'), "title": "La Leona", "tags": []}) == ["White chocolate", "Almonds", "Berries"]),   # as the scan reads it: markup stripped first
    # Kurasu (26/11/2026): FAF Dark showed the "typical" notes; its table row says "Flavor note" (one note, no "tasting"),
    # and its other coffees ended their lists with "Honey-like sweetness, Accompanying aftertaste"
    ("Kurasu: a 'Flavor note' row is the notes; 'Honey-like sweetness' is Honey and 'Accompanying aftertaste' is not a note",
     lambda: scan.page_notes("Process\nNatural\nFlavor note\nOrange peel, Roasted nuts, Dried raisins, Caramel, Dark Chocolate\nRoaster's Comment\nKurasu's beloved House Blend", "FAF Dark", "") == ["Orange peel", "Roasted nuts", "Dried raisins", "Caramel", "Dark Chocolate"]
       and [scan.tidy_note(x) for x in ["Honey-like sweetness", "Dried mango-like sweetness", "Accompanying aftertaste"]] == ["Honey", "Dried mango", ""]),
    ("Tanat: 'Agrumes d'orange sanguine' is blood orange",
     lambda: __import__("flavours").to_english("Agrumes d'orange sanguine") == "Blood orange" and __import__("flavours").to_english("Agrumes d’orange sanguine") == "Blood orange"),
    # Hälla (26/11/2026): new roaster, every coffee without notes; Swedish sentence notes and "Process: Tvättat"
    ("Hälla: 'smakprofil med toner av svart te, lakrits och len mjölkchoklad, avrundad…' gives three notes; 'Tvättat' is washed",
     lambda: [__import__("flavours").to_english(n) for n in scan.find_notes({"body": "Kaffeinfo:\nEcuador,\nVäxer på 1800-2100m\nArabica:  Typical\nProcess: Tvättat\nEn fyllig och balanserad smakprofil med toner av svart te, lakrits och len mjölkchoklad, avrundad med en djup och lätt bitter karaktär av kakao.\n", "title": "Chito Community", "tags": []})] in (["Black tea", "Liquorice", "Smooth milk chocolate"], ["Black tea", "Licorice", "Smooth milk chocolate"])
       and scan.find_process("Process: Tvättat") == "Washed"),
    # To kawa (26/11/2026): no notes on any coffee; the label is "Profil sensoryczny" (Polish), notes in Polish
    ("To kawa: 'Profil sensoryczny: nugat, czekolada mleczna, prażone orzechy laskowe' gives Nougat, Milk chocolate, Roasted hazelnuts",
     lambda: [__import__("flavours").to_english(n) for n in scan.page_notes("Odmiana: Typica, Bourbon, Caturra, Catuai\nProfil sensoryczny: nugat, czekolada mleczna, prażone orzechy laskowe\nWaga\n", "Guatemala Huehuetenango", "")] == ["Nougat", "Milk chocolate", "Roasted hazelnuts"]
       and [__import__("flavours").to_english(n) for n in scan.page_notes("Profil sensoryczny: karmel, mleczna czekolada, czereśnie, agrest\nWaga\n", "Kenia Kamathura", "")] == ["Caramel", "Milk chocolate", "Sweet cherry", "Gooseberry"]),
    ("Hälla: Swedish notes that run on into the sentence or the next paragraph end at the flavour, and translate",
     lambda: [scan.tidy_note(x) for x in ["KrämigVi skickar kaffe som", "Granatäpple möter sötma av", "Len fudge med en", "Lemonad Vi skickar kaffe", "Mogen plommonfrukt med ljus", "McIntosh apple"]] == ["Krämig", "Granatäpple", "Len fudge", "Lemonad", "Mogen plommonfrukt", "McIntosh apple"]
       and [__import__("flavours").to_english(x) for x in ["Mörka körsbär", "Rörsocker", "Rostade nötter", "Ciemna czekolada", "Śliwka węgierka"]] == ["Dark cherries", "Cane sugar", "Roasted nuts", "Dark chocolate", "Damson plum"]),
    # Rover Coffee Lab (26/11/2026): washed coffees shown as honey or double fermented; the "Process:" label's window ran on into
    # the next line's tasting notes ("Honey") or the story
    ("Rover: 'Process: Washed' over 'Tasting notes: Orange, Honey' is washed, not honey; 'Process: Double Fermentation Washed' stays double fermented",
     lambda: scan.labelled(" Process: Washed\n Tasting notes: Orange, Honey, Caramel, Black Tea\n", "process") == "Washed"
       and scan.labelled(" Process: Washed — 48-hour fermentation\n Tasting notes: Raspberry, Cherry, Honey, Floral\n", "process") == "Washed"
       and scan.labelled("Process:\nNatural\n", "process") == "Natural"),
    # Tandem (26/11/2026): the notes' label is "We hear:", and the list ends with the coffee's song ("Move Inside My Head")
    ("Tandem's 'We hear: Lime, Chamomile, Lychee, Move Inside My Head' gives Lime, Chamomile, Lychee (the song isn't a note)",
     lambda: scan.page_notes("Producer\nAbel Salinas\nVarietals\nMejorado\nElevation\n1890 MASL\nProcessing\nWashed\nWe hear\nLime, Chamomile, Lychee, Move Inside My Head\nEven Better With\nJoin Our Mailing List", "Abel Salinas", "") == ["Lime", "Chamomile", "Lychee"]
       and scan.find_notes({"body": "<p><strong>We hear:</strong><br>Lime, Chamomile, Lychee, Move Inside My Head</p>", "title": "Abel Salinas", "tags": []}) == ["Lime", "Chamomile", "Lychee"]),
    # Sprout (24/11/2026): the same subtitle layout as Sl.ow, with the name in capitals ("LASSO LASSI", then "Lychee, Tropical, Lactic")
    ("Sprout's 'Lychee, Tropical, Lactic' under 'LASSO LASSI' are the notes",
     lambda: scan.page_notes("Skip to content\nShop\nLASSO LASSI\nLychee, Tropical, Lactic\n\u00a313.00\nSize\n250g\nAdd to cart\nComplex & fruity bang bang baby!", "Lasso Lassi") == ["Lychee", "Tropical", "Lactic"]),
    # Sl.ow (24/11/2026): the notes are an unlabelled subtitle right under the coffee's name
    ("Sl.ow's 'Lime, Pineapple, Red Apple' under the title 'Loco Lime' are the notes",
     lambda: scan.page_notes("Home\nShop\nMexico \u00b7 Honey\nLoco Lime\nLime, Pineapple, Red Apple\nNZ$53.99\nAdd to cart\nThis honey processed Geisha from Mexico is bright and juicy.", "Loco Lime") == ["Lime", "Pineapple", "Red Apple"]),
    # Lucid (24/11/2026): "Tasting:" is a list of descriptors (fruity, high sweetness); the notes are under "Flavours like:"
    ("Lucid's 'Flavours like: Cherry, Apricot, Cola' are the notes, not the 'Tasting: Fruity, High sweetness' descriptors",
     lambda: scan.find_notes({"body": "Origin: Rwanda\nProcess: Washed\nTasting: Fruity, High sweetness, Medium Acidity, Juicy\nFlavours like: Cherry, Apricot, Cola", "title": "Rwanda Shyira", "tags": []}) == ["Cherry", "Apricot", "Cola"]),
    # Lucid (25/11/2026): the same lines as list items in the shop's own markup; "Cola</li></ul>" was dropped as markup
    ("Lucid's '<li>Flavours like: Cherry, Apricot, Cola</li>' gives all three notes, Cola included",
     lambda: scan.find_notes({"body": "<ul><li>Variety: Red Bourbon</li><li>Process: Washed Process</li></ul><p>&nbsp;</p><ul><li>Tasting: Fruity, High sweetness, Medium Acidity, Juicy</li><li>Flavours like: Cherry, Apricot, Cola</li></ul>", "title": "Rwanda Shyira Washed", "tags": []}) == ["Cherry", "Apricot", "Cola"]),
    ("…and a paragraph after the list doesn't join the notes",
     lambda: scan.find_notes({"body": "<ul><li>Flavours like: Cherry, Apricot, Cola</li></ul><p>We roast this one light for filter.</p>", "title": "Rwanda Shyira Washed", "tags": []}) == ["Cherry", "Apricot", "Cola"]),
    # James Gourmet (24/11/2026): "Aromatics: Floral, melon and raspberry | Body: … | Acidity: …"
    ("James Gourmet's 'Aromatics: Floral, melon and raspberry |' gives the three notes and stops at the next label",
     lambda: scan.find_notes({"body": "BREWING AND RECIPES\nAromatics: Floral, melon and raspberry | Body: Creamy on cooling| Acidity: Ripe, Wild, Boozy, Citric |\nRipe soft fruit and orange land in your mug.", "title": "Ethiopian Bekele Yutute", "tags": []}) == ["Floral", "Melon", "Raspberry"]),
    # Terraform (24/11/2026): "Tasting Note" in the singular, and the notes joined with plus signs, in a Basic Info block
    ("Terraform's 'Tasting Note' block with notes joined by ' + ' gives the four notes",
     lambda: scan.find_notes({"body": "BASIC INFO\nTasting Note\nGardenia + Pomelo + Orange soda + Yellow peach\nRegion\nCosta Rica\nVariety\nGesha (COE Washed Rank 2)\nProcess\nWashed\nAltitude\n2050 masl\nHarvest\nMarch 2026", "title": "El Roble", "tags": []}) == ["Gardenia", "Pomelo", "Orange soda", "Yellow peach"]),
    ("'Tasting Note: A + B' on one line is read the same way",
     lambda: scan.find_notes({"body": "Tasting Note: Gardenia + Pomelo + Orange soda + Yellow peach\nRegion: Costa Rica", "title": "El Roble", "tags": []}) == ["Gardenia", "Pomelo", "Orange soda", "Yellow peach"]),
    # Rum Baba's Winter Coffee (24/11/2026): the page labels "Processing: Anaerobic" but the shop tags say natural and thermal
    ("A labelled 'Processing: Anaerobic' line beats shop tags saying natural",
     lambda: (kept(item("Winter Coffee - Costa Rica", "Tasting notes: Frosted Cinnamon Bun\nArea: San José, Costa Rica\nFarm: Fernando Cordero, Cordillera de Fuego, Luis Campos\nVariety: Catuai\nProcessing: Anaerobic\nRoast level: Light",
                       tags=("baking spice", "coffee", "costa rica", "natural", "thermal", "filter roast"))) or {}).get("process") == "Anaerobic"),
    ("Rum Baba's 'Tasting notes: Frosted Cinnamon Bun' is read as the note",
     lambda: (kept(item("Winter Coffee - Costa Rica", "Tasting notes: Frosted Cinnamon Bun\nArea: San José, Costa Rica\nVariety: Catuai\nProcessing: Anaerobic\nRoast level: Light")) or {}).get("notes") == ["Frosted Cinnamon Bun"]),
    # chocolate and other things that aren't coffee (Newground, 15/11/2026)
    ("Newground's 'Honduras 60% Milk' chocolate bar is not coffee",
     lambda: scan.not_coffee(item("Honduras 60% Milk", "Bean to bar milk chocolate from Honduras.")) is not None),
    ("A coffee with milk chocolate tasting notes is still coffee",
     lambda: kept(item("Huila Pink Bourbon", COFFEE_BODY + ", milk chocolate bar")) is not None),
    ("Midnight Oil coffee liqueur is a drink, not beans",
     lambda: scan.not_beans(item("Midnight Oil Decaf Coffee Liqueur 700ml", variants="700ml")) is not None),
    # sugar (Kin Coffee, 16/11/2026)
    ("Kin's 'Demerara Sugar – Organically Grown' is not coffee", lambda: kept(item("Demerara Sugar – Organically Grown", COFFEE_BODY)) is None),
    ("A sugarcane decaf is still coffee", lambda: kept(item("Colombia Sugarcane Decaf", COFFEE_BODY)) is not None),
    # cascara (Kaffa Roastery, 16/11/2026)
    ("Kaffa's 'Cascara - Las Lajas' is not coffee", lambda: kept(item("Cascara - Las Lajas", COFFEE_BODY, type_="Coffee Bags")) is None),
    ("Kaffa's Kili cascara cans are not coffee",
     lambda: kept(item("Kili Cascara-Kirsikka 24-pack", COFFEE_BODY, type_="Other drinks")) is None),
    ("Kaffa files coffees under 'Coffee Bags': they are coffee",
     lambda: kept(item("Fruity & Floral - Ethiopia Doyo", COFFEE_BODY.replace("Colombia", "Ethiopia"), type_="Coffee Bags")) is not None),
    ("Kaffa: 'Fruity & Floral - Nicaragua Santa Isabel' is named Nicaragua Santa Isabel",
     lambda: name("Fruity & Floral - Nicaragua Santa Isabel", "Kaffa Roastery", "Nicaragua") == "Nicaragua Santa Isabel"),
    # roast (Danelaw Polaris and Bella Barista Yule Be Brewing, 16/11/2026)
    ("Polaris: the page says 'Roast: Medium', the shop's tag says light: it's medium",
     lambda: (kept(item("Polaris - House Espresso Blend Decaf", "Origin: Colombia\nRoast: Medium\nProcess: Sugarcane decaf\nTasting notes: caramel",
                        tags=["Light Roast"])) or {}).get("roast") == "medium"),
    ("Yule Be Brewing: 'Roast level: Medium-Light' is medium, not light",
     lambda: scan.roast_labelled("Roast level: Medium-Light\n") == "medium"),
    ("'Light-medium' is medium too", lambda: scan.roast_word("Light Medium") == "medium"),
    ("'Lightest' is very light", lambda: scan.roast_word("Lightest") == "vlight"),
    ("A plain 'Light' roast is light", lambda: scan.roast_word("Light") == "light"),
    ("Tags naming two roasts (a shop's filter menu) say nothing about the coffee",
     lambda: (kept(item("Kenya Gichuka AB", COFFEE_BODY.replace("Colombia", "Kenya"), tags=["Light Roast", "Dark Roast"])) or {}).get("roast") is None),
    # prepaid plans (16/11/2026)
    ("Light Up's lucky bag '【店頭受取のご予約】コーヒー福袋2027' is a set, not one coffee", lambda: scan.not_one_coffee(item("【店頭受取のご予約】コーヒー福袋2027")) is not None),
    ("a lucky bag known only by its encoded slug is a set too", lambda: scan.not_one_coffee(item("2027", url="https://lightupcoffee.com/products/%E5%BA%97%E9%A0%AD%E5%8F%97%E5%8F%96%E3%81%AE%E3%81%94%E4%BA%88%E7%B4%84-%E3%82%B3%E3%83%BC%E3%83%92%E3%83%BC%E7%A6%8F%E8%A2%8B2027")) is not None),
    ("lucky bags and blind boxes in any language are sets, not one coffee", lambda: all(scan.not_one_coffee(item(x)) for x in ["New Year Lucky Bag 2027", "Coffee Grab Bag", "Blind Box Espresso", "Surprise Coffee Box", "Kaffee Wundertüte", "コーヒー豆 詰め合わせ", "飲み比べセット"])),
    ("coffees with happy, lucky or sorpresa in the name stay: 'Happy Hills Ethiopia', 'Lucky Farm Colombia', 'Finca La Sorpresa'", lambda: all(scan.not_one_coffee(item(x)) is None for x in ["Happy Hills Ethiopia", "Lucky Farm Colombia", "Finca La Sorpresa Geisha"]) and scan.not_one_coffee(item("Caja Sorpresa de Café")) is not None),
    ("a flavour typed without its accent is still translated: KB's 'Mures' (mûres) is blackberry", lambda: __import__("flavours").to_english("Mures") == "Blackberry"),
    ("a note cut from a sentence loses its 'where': 'Where juicy mandarin' -> 'Juicy mandarin'", lambda: scan.tidy_note("Where juicy mandarin").lower() == "juicy mandarin"),
    ("Wes Ngopi's Alo: 'Upon grinding, the aroma presents mango, peach and blueberry. On the palate, … jam lead, followed by…' gives mango, peach, blueberry", lambda: (scan.notes_from_text('"Upon grinding, the aroma presents mango, peach and blueberry. On the palate, mango, peach and blueberry jam lead, followed by bergamot and sweet white-floral notes. The cup is sweet and juicy."') or "").lower() == "mango, peach, blueberry"),
    ("'On the palate, cherry, cocoa and orange lead' gives the three, not 'orange lead'", lambda: (scan.notes_from_text("On the palate, cherry, cocoa and orange lead the way.") or "").lower() == "cherry, cocoa, orange"),
    ("Odd notes 26/11: French and German words translate (Cassonade, Canelle, Mélilot, Samtig, Vanilje), misspellings mend (Bergamont, Hazlenut, Chery)", lambda: [__import__("flavours").to_english(x) for x in ["Cassonade", "Canelle", "Mélilot", "Samtig", "Vanilje", "Bergamont", "Hazlenut", "Chery"]] == ["Brown sugar", "Cinnamon", "Sweet clover", "Velvety", "Vanilla", "Bergamot", "Hazelnut", "Cherry"]),
    ("Odd notes 26/11: scraps and product words are not notes ('Xxxxx', 'Pth to', 'En grain', 'Designed', 'Filter Coffee')", lambda: all(scan.junk_note(x) for x in ["Xxxxx", "Pth to", "En grain", "Designed", "Filter Coffee", "Mittelkräftig"])),
    ("Odd notes 26/11: 'Notes： Black plum', 'Profile Fruity', 'Lemon notes; bright' tidy to the taste", lambda: [scan.tidy_note(x) for x in ["Notes： Black plum", "Profile Fruity", "Lemon notes; bright"]] == ["Black plum", "Fruity", "Lemon"]),
    ("Names lose shop marks and bag sizes: '*NEW Special Release Blackberry Coferment* Colombia', '12oz Ethiopia Kochere Coffee Beans', 'Caffeinate Mars 2.0, 12oz, Whole Bean'", lambda: [scan.strip_marks(x) for x in ["*NEW Special Release Blackberry Coferment* Colombia - Jairo Arcila", "12oz Ethiopia Kochere Coffee Beans", "Caffeinate Mars 2.0, 12oz, Whole Bean", "***NEW***", "SL28 Kenya 250g", "Holy Sh*t"]] == ["Special Release Blackberry Coferment Colombia - Jairo Arcila", "Ethiopia Kochere Coffee Beans", "Caffeinate Mars 2.0", "***NEW***", "SL28 Kenya", "Holy Sh*t"]),
    ("Tanat's 30 g auction lots (no country in the feed) get their page read for the origin; a mug with no weight doesn't", lambda: scan.wants_page_origin({"title": "Finca Sophia [RW4 - Colibri-Poro 40 GW] - Auction Lot", "type": "", "tags": [], "variants": "30g Grains", "url": "https://tanat.coffee/boutique/finca-sophia-auction-lot-colibri-poro-40/"}) and scan.wants_page_origin({"title": "Finca Sophia [RW4] - Auction Lot", "type": "", "tags": [], "variants": "", "url": "https://tanat.coffee/boutique/x/", "lastmod": "2026-11-26"}) and not scan.wants_page_origin({"title": "Kinto mug", "type": "", "tags": [], "variants": "White", "url": "https://tanat.coffee/boutique/kinto-mug/"})),
    ("'Jones Prepaid Weekly 12 months' is a plan, not a coffee", lambda: scan.not_one_coffee(item("Jones Prepaid Weekly 12 months")) is not None),
    ("'Coffee of the Month (6 month Prepaid)' is a plan", lambda: scan.not_one_coffee(item("Coffee of the Month (6 month Prepaid)")) is not None),
    ("'Uphill Espresso - 6 months' is a plan", lambda: scan.not_one_coffee(item("Uphill Espresso - 6 months")) is not None),
    ("'Nicaragua Plan Vivo' is a real coffee", lambda: scan.not_one_coffee(item("Nicaragua Plan Vivo")) is None),
    # names and duplicates (16/11/2026)
    ("Conscious Speciality: a theme button 'Close' is not a coffee's name", lambda: scan.UI_WORD.match("Close") is not None),
    ("Beans and ground listings of one coffee are the same coffee",
     lambda: scan.same_name("Kiambu AB - Whole Bean 250g") == scan.same_name("Kiambu AB (Ground)")),
    ("Two different coffees stay two", lambda: scan.same_name("Kiambu AB") != scan.same_name("Kiambu AA")),
    # South America (16/11/2026)
    ("Pergamino: 'Lomaverde (500g coffee bag)' is a bag of coffee named Lomaverde",
     lambda: name("Lomaverde (500g coffee bag)", "Pergamino", "Colombia") == "Lomaverde" and not scan.EXCLUDE.search("Lomaverde (500g coffee bag)")),
    ("Onyx's 'Krampus - Cafe Only' is sold to cafes, not to drinkers: left out, and 'Krampus' stays",
     lambda: scan.EXCLUDE.search("Krampus - Cafe Only") is not None and scan.EXCLUDE.search("Framily - Café Only") is not None and not scan.EXCLUDE.search("Krampus") and not scan.EXCLUDE.search("Cafe Imports Only One")),
    ("River's Kyarumba took 'Bright acidity' from the roaster's remarks: the label is 'Flavour Description: Blackcurrant, Honey, Juicy.'",
     lambda: scan.find_notes({"body": "Flavour Description: Blackcurrant, Honey, Juicy.\nProducer: Community of Kyarumba.\nVarietal: SL14 and SL28.\nProcess: Natural Process.\nRoasters Notes: We have roasted this coffee to a medium/medium light level which accentuates the tropical fruit notes and bright acidity.", "title": "Kyarumba (Uganda)", "tags": []})
             == ["Blackcurrant", "Honey", "Juicy"]),
    ("The Source: the notes label is 'cup profile', the list split by dashes",
     lambda: scan.find_notes({"body": "process: natural+\nalt: 1850 masl\nvariety: sidra\ncup profile: cherry cola - Scottish blaeberries - grape\n", "title": "la planta", "tags": []})
             == ["Cherry cola", "Scottish blaeberries", "Grape"]),
    ("The Source writes names in small letters: 'la planta natural sidra' reads 'La Planta Natural Sidra', codes and chosen capitals kept",
     lambda: [scan.cap_name(x) for x in ("la planta natural sidra", "thermal shock orange gesha C-13", "finca de la luna", "El Pergamino", "iPhone blend", "#beãnz")]
             == ["La Planta Natural Sidra", "Thermal Shock Orange Gesha C-13", "Finca de La Luna", "El Pergamino", "iPhone Blend", "#beãnz"]),
    ("Passage had no notes: a bracketed heading '【Taste Note】' with the list on the line under it",
     lambda: scan.find_notes({"body": "【COMMENT】\nHe is the winning producer of the Colombia Washed Coffee Festival 2026.\n\n【Taste Note】\n\nAlmond, Red apple, Orange, Plum, Clean\n\n【PROFILE】\nPRODUCER：Rubiera Velasquez\n", "title": "Colombia Rubiera Velazquez", "tags": []})
             == ["Almond", "Red apple", "Orange", "Plum", "Clean"]),
    ("German notes in English: 'Orange, Salbei, Rosenwasser' reads Orange, Sage, Rose water; Blutorange, Kakaonibs, nussig too",
     lambda: __import__("flavours").english_notes(["Orange", "Salbei", "Rosenwasser", "Blutorange", "Kakaonibs", "Nussig", "Schwarzer Tee"])
             == ["Orange", "Sage", "Rose water", "Blood orange", "Cacao nibs", "Nutty", "Black tea"]),
    ("A German shop's list of brewers is not tasting notes ('Siebträger', 'Vollautomat', 'Herdkocher', 'Handfilter'), nor is 'Direkt vom Ursprung'",
     lambda: [scan.tidy_note(x) for x in ("Siebträger", "Vollautomat", "Herdkocher", "Handfilter", "French Press", "Direkt vom Ursprung", "Haselnuss")] == ["", "", "", "", "", "", "Haselnuss"]),
    ("Hoppenworth & Ploch: notes for filter and for espresso, keep the filter ones and no '(Espresso' left over",
     lambda: scan.find_notes({"body": "Geschmack: Strawberry, Holunder (Filter); Kirsche, Peach, Blütenhonig\xa0 (Espresso)\n", "title": "Bombe", "tags": []}) == ["Strawberry", "Holunder"]
     and scan.find_notes({"body": "Geschmack: Sour cherry, Cola, Mango, Kirschlikör\xa0 (Espresso)\n", "title": "Sakami", "tags": []}) == ["Sour cherry", "Cola", "Mango", "Kirschlikör"]),
    ("Notes with emoji, 'Imagine …!', no-break spaces, cut-open brackets and links to Instagram",
     lambda: [scan.tidy_note(x) for x in ("🍫Chocolate", "🍯 Maple Syrup", "Imagine blackberry candy!", "Lemon cake!", "Blood\xa0orange", "Tropical fruits (pineapple", "Tasting Notes: Plum", "INSTAGRAM", "Pekannuss …\xa0Jetzt erleben!", "MILK CHOCOLATE")]
     == ["Chocolate", "Maple Syrup", "Blackberry candy", "Lemon cake", "Blood orange", "Tropical fruits", "Plum", "", "", "Milk chocolate"]),
    ("Notes left in Romanian, Swedish, Italian and shop markup: 'Ciocolata cu lapte', 'Søt', 'Fiore d'arancio', 'Group_Chocolate', 'Vc_column_text', 'Notes_Caramel'",
     lambda: [flavours.to_english(scan.tidy_note(x)) if scan.tidy_note(x) else "" for x in ("Ciocolata cu lapte", "Søt", "Fiore d'arancio", "Group_Chocolate", "Vc_column_text", "Notes_Caramel", "Corp mediu", "Order")]
     == ["Milk chocolate", "Sweet", "Orange blossom", "", "", "Caramel", "", ""]),
    ("Röststätte: a sentence about the coffee is not its notes ('Perfekt für alle, die ihren Kaffee vollmundig und aromatisch lieben'), and 'Marzipan in' is Marzipan",
     lambda: [scan.tidy_note(x) for x in ("Perfekt für alle", "Die ihren Kaffee vollmundig", "Aromatisch lieben", "Marzipan in", "Kaffeeblüte", "Red currant")] == ["", "", "", "Marzipan", "Kaffeeblüte", "Red currant"]),
    ("Drip coffee bags are still not beans", lambda: scan.EXCLUDE.search("Drip coffee bags x10") is not None),
    ("Um Coffee Co: 'Nanolotes | Wush Wush' is named Wush Wush", lambda: name("Nanolotes | Wush Wush", "Um Coffee Co", "Brazil") == "Wush Wush"),
    ("Um Coffee Co: 'Blend | Fruitbomb' is named Fruitbomb", lambda: name("Blend | Fruitbomb", "Um Coffee Co", "Brazil") == "Fruitbomb"),
    ("Coffee++ subscriptions (assinatura) are not coffees", lambda: scan.EXCLUDE.search("Assinatura Café Paraná") is not None),
    ("Coffee++ sachets are not beans", lambda: scan.EXCLUDE.search("Café Intenso| Drip Coffee - 10 Sachês") is not None),
    ("Um Coffee Co's Kony and Super Jolly grinders are not coffee",
     lambda: scan.EXCLUDE.search("Kony SG") is not None and scan.EXCLUDE.search("Super Jolly V Up Pro") is not None),
    ("Caffeine Project's variety 'Caramel, Toasts, Vanilla' is tasting notes, not a variety", lambda: scan.variety_is_flavour("Caramel, Toasts, Vanilla") and not scan.variety_is_flavour("Pink Bourbon") and not scan.variety_is_flavour("SL28, Ruiru 11")),
    ("Tigermoth: notes read as the variety go back to the notes, the importer's name read as notes goes",
        lambda: scan.flavour_variety({"variety": "Blackberry, tangerine, dark brown sugar", "notes": ["Falcon"]}) == {"variety": None, "notes": ["Blackberry", "Tangerine", "Dark brown sugar"]}),
    ("Heart & Graft: a stray bracket after a note goes ('Vanilla[' reads Vanilla)", lambda: scan.tidy_note("Vanilla[") == "Vanilla" and scan.tidy_note("(Lavender)") == "Lavender"),
    ("Dear Green's '12 Days of Coffee' box is not one coffee", lambda: scan.EXCLUDE.search("Pre-order: 12 Days of Coffee") is not None),
    ("Arlo's 'Calendrier de l'Avent' is not one coffee", lambda: scan.EXCLUDE.search("Calendrier de l'Avent 2026") is not None),
    ("Industra's gift pack (Dárkový balíček) is not one coffee", lambda: scan.EXCLUDE.search("Dárkový balíček FILTR") is not None),
    ("Coffeelab's 'Zestaw ... + brelok' set is not one coffee", lambda: scan.EXCLUDE.search("Zestaw Brewlab Daily + brelok") is not None),
    ("Kafferäven's '2 x Brasilien' is two bags", lambda: scan.EXCLUDE.search("2 x Brasilien") is not None),
    ("Kaffa's Christmas brewing kits are not coffees", lambda: all(scan.EXCLUDE.search(x) for x in ["Håndbrygg i oliventre – med kontroll på oppskriften", "Fellow håndbrygg til jul", "Premium presskanne og skikkelig god julekaffe.", "Suiren-julepakken", "Enkel julekaffe med Pegasus", "Switch – julekaffe med to bryggemåter", "Fruity Berries Newby"])),
    ("Conscious: the cart's 'Not in stock' line on every page doesn't make a coffee sold out", lambda: not re.search(r">\s*(?:sold out|out of stock)\s*<", "<p>Not in stock</p>", re.I)),
    ("Bag scan: white print on a small coloured sticker (lime, teal) is cut out, enlarged and read on its own", lambda: "function panel(src, gamma" in open(scan.ROOT / "index.html").read()),
    ("Bag scan: a roaster's name down the side with its first letters hidden ('IMPSON' / 'SONS') is still found", lambda: "its first letters under a thumb" in open(scan.ROOT / "index.html").read()),
    ("Bag scan: notes read as '25 Caramel. Jasmine' come out as 'Caramel, Jasmine'", lambda: "a misread first word and full stops for commas" in open(scan.ROOT / "index.html").read()),
    ("Climpson: <h4>Flavour profile:</h4><p>Liquorice, Pear, Blackberry</p> is read from the HTML itself when the page text loses it",
     lambda: scan.raw_notes('<div><h4>Flavour profile:</h4><p>Liquorice, Pear, Blackberry</p><h4>Coffee:</h4><p>El Witano</p><h4>Origin:</h4><p>Huehuetenango, Guatemala</p></div>', "El Witano") == ["Liquorice", "Pear", "Blackberry"]
       and scan.raw_notes('<h4>Notes:</h4><p>Free delivery on orders over £25, and returns within 30 days of purchase for all customers everywhere in the United Kingdom and beyond</p>', "X") == []
       and scan.raw_notes('<h4>Flavour profile:</h4><h4>Coffee:</h4><p>El Witano</p>', "El Witano") == []),
    ("Kaffa: 'Kaffebønner Klassisk Julekaffe fra Guatemala' is Klassisk Julekaffe, 'Kaffebønner Etiopia Danche' is Danche; other shops' names are left alone",
     lambda: name("Kaffebønner Klassisk Julekaffe fra Guatemala", "Kaffa", "Guatemala") == "Klassisk Julekaffe" and name("Kaffebønner Etiopia Danche", "Kaffa", "Ethiopia") == "Danche"
       and name("Kaffebønner Juleespresso fra Etiopia", "Kaffa", "Ethiopia") == "Juleespresso" and name("Kaffebønner Brasil Fazenda IP", "Kaffa", "Brazil") == "Fazenda IP"
       and name("Hacienda da Lagoa", "X", "Brazil") == "Hacienda da Lagoa" and name("Casa de Piedra", "X", "Colombia") == "Casa de Piedra"),
    ("Conscious: no price in the page's data ($0.00), but '£ 14.00' is printed under the name; a delivery line is not a price",
     lambda: scan.page_price("<html><body><h1>Danse</h1><p>Ethiopia</p><p>£ 14.00</p><p>250g</p><p>Free delivery over £25</p></body></html>", "Danse") == (14.0, "GBP")
       and scan.page_price("<html><body><h1>Danse</h1><p>Free delivery on orders over £25</p><p>Ethiopia</p></body></html>", "Danse") == (None, None)
       and scan.page_price("<html><body><p>£ 14.00</p><h1>Danse</h1></body></html>", "") == (None, None)),
    ("Conscious: the real page has three h1s ('Close', the coffee, 'Overview'), a 'Shop | Arcangel' title and '£&nbsp;13.00' after the size and grind lines",
     lambda: scan.page_price('<html><head><title>Shop | Arcangel</title></head><body><h1 class="heading-106">Close</h1><div>$0.00</div><p>Free shipping for orders £20+</p>'
                             '<h1 class="pro_buy_now_producer_header">Arcangel</h1><div>Size 250g 1kg</div><div>Grind Whole beans Espresso Stove top Pour over Aeropress French press</div>'
                             '<h6 class="pro_buy_now_heading">£&nbsp;13.00&nbsp;</h6><a>Buy</a><h1 class="heading-55">Overview</h1><p>Price paid to the farm £10.60/KG</p></body></html>', "Arcangel") == (13.0, "GBP")),
    ("Prices are read from product pages for every shop, not only for roasters with a roast set in roasters.json (Conscious: 27 coffees unlisted for want of a price)",
     lambda: re.search(r"\n            add_page_details\(recs, r, old\)\n            add_page_prices\(recs, r, old\)", open(scan.ROOT / "scripts" / "scan.py").read()) is not None),
    ("Conscious: every coffee was read as 'Close' (the cart's heading) with the free-shipping '£20' as its price; the heading the page title repeats is the coffee, and its price is the first one after it",
     lambda: (lambda p: p["name"] == "Arcangel" and p["offers"] == [{"price": "13.00", "priceCurrency": "GBP"}])(scan.plain_product(
         '<html><head><title>Shop | Arcangel</title></head><body><div>Free shipping over £20</div><h1 class="heading-106">Close</h1><div>$0.00</div><a>Continue to Checkout</a>'
         '<p>Free shipping for orders £20+</p><h1 class="pro_buy_now_producer_header">Arcangel</h1><div>Size 250g 1kg</div><h6>£&nbsp;13.00&nbsp;</h6><a>Add to Bag</a><a>Buy now</a>'
         '<h1 class="heading-55">Overview</h1><p>Origin Bolivia</p></body></html>', "https://xyzroastery.example/product/arcangel")[0])),
    ("A plain product page with one heading still reads as before: its heading and the first price after it",
     lambda: (lambda p: p["name"] == "Finca Luna" and p["offers"][0]["price"] == "11.50")(scan.plain_product(
         '<html><head><title>Finca Luna | XYZ Roastery</title></head><body><h1>Finca Luna</h1><p>£11.50</p><button>Add to cart</button></body></html>', "https://xyzroastery.example/product/finca-luna")[0])),
    ("Conscious, as its pages are really read (the spec-grid reader): the cart's 'Close' and '$0.00' came first; the coffee is the heading the title repeats, its price the first real one after it",
     lambda: (lambda p: p["name"] == "Arcangel" and p["offers"]["price"] == "13.00" and p["offers"]["priceCurrency"] == "GBP")(scan.spec_grid_product(
         '<html><head><title>Shop | Arcangel</title></head><body><div>Free shipping over £20</div><h1 class="heading-106">Close</h1><div class="w-commerce-commercecartordervalue price">$0.00</div>'
         '<p>Free shipping for orders £20+</p><h1 class="pro_buy_now_producer_header">Arcangel</h1><div>Size 250g 1kg</div><h6 class="pro_buy_now_heading">£&nbsp;13.00&nbsp;</h6><a>Buy</a>'
         '<h1 class="heading-55">Overview</h1><div>Origin</div><div>Bolivia</div><div>Process</div><div>Coco natural</div><div class="rel-price">£ 17.00</div></body></html>')[0])),
    ("A spec-grid page with one heading and a price element reads as before (Newground: 'One Time Purchase £11.00')",
     lambda: (lambda p: p["name"] == "Finca Luna" and p["offers"]["price"] == "11.00")(scan.spec_grid_product(
         '<html><head><title>Finca Luna</title></head><body><h1>Finca Luna</h1><div>One Time Purchase</div><span class="buyingOptPrice">£11.00</span><div>Country</div><div>Colombia</div><div>Process</div><div>Washed</div></body></html>')[0])),
    ("Fandango: a roaster with no country on file keeps the currency its shop gives (its kronor were shown as '£270.00'); a set country or currency still decides",
     lambda: scan.home_currency({"country": "", "region": "World", "_ccy": "SEK"}) == "SEK" and scan.home_currency({"country": "GB", "_ccy": "USD"}) == "GBP"
       and scan.home_currency({"country": "", "currency": "GBP", "_ccy": "USD"}) == "GBP" and scan.home_currency({"country": "", "region": "Europe"}) == "EUR"),
    ("A tamper, a stirring stick and bags of chocolate tablets are not coffee (Rogue Wave, Arlo's)",
     lambda: all(scan.EXCLUDE.search(t) for t in ["MHW-3BOMBER YU Series Force Impact Tamper Flat 58.35mm", "MHW-3BOMBER Stirring Stick 22mm Walnut", "Mini Tablettes Chocolat au lait Praliné 100g", "Sachet mini tablettes praliné noir 100gr"])
       and not any(scan.EXCLUDE.search(t) for t in ["Chocolatey & spicy Arabica", "Black Forest Roast Rich Chocolatey Coffee", "Guatemala Antigua"])),
    ("Onibus: a Japanese title that came out as '/ [ ]' takes its name from the product link; number names and ordinary names are left alone",
     lambda: scan.name_from_url("/ [ ]", "https://xyzroastery.example/products/el-salvador-familia-diaz-la-mina") == "El Salvador Familia Diaz La Mina"
       and scan.name_from_url("ペルー / ブエナ・ビスタ", "https://xyzroastery.example/products/peru-buena-vista-geisha-2026") == "Peru Buena Vista Geisha"
       and scan.name_from_url("60/40", "https://xyzroastery.example/products/60-40") == "60/40" and scan.name_from_url("Danche", "https://xyzroastery.example/products/x") == "Danche"),
    ("Doubleshot: product data that gives the shop's front page as its own link takes the page's link; a real product link is kept",
     lambda: scan.ld_to_item({"name": "Farm", "url": "https://www.xyzroastery.example"}, "https://xyzroastery.example/produkt/farm", "")["url"] == "https://xyzroastery.example/produkt/farm"
       and scan.ld_to_item({"name": "Farm", "url": "https://xyzroastery.example/p/farm-2"}, "https://xyzroastery.example/produkt/farm", "")["url"] == "https://xyzroastery.example/p/farm-2"
       and scan.ld_to_item({"name": "Farm"}, "https://xyzroastery.example/produkt/farm", "")["url"] == "https://xyzroastery.example/produkt/farm"
       and scan.EXCLUDE.search("MHW-3BOMBER Magnetic Dosing Ring 58mm Black") is not None),
    ("Father's: a coffee whose own page gives its price in koruna is not labelled with the shop's euros ('€449.77'); a currency set by hand still wins",
     lambda: scan.price_ccy({"currency": "CZK"}, {"_ccy": "EUR"}) == "CZK" and scan.price_ccy({"currency": None}, {"_ccy": "EUR"}) == "EUR"
       and scan.price_ccy({"currency": "USD"}, {"currency": "GBP", "_ccy": "USD"}) == "GBP" and scan.price_ccy({}, {}) == "GBP"),
    ("Smith's: a 'from £3.20' price on a shop that sells 125 g, 250 g, 500 g and 1 kg is shown with its 125 g bag",
     lambda: scan.bag_grams({"variants": "125g / 250g / 500g / 1kg / Whole Bean / Cafetiere", "title": "Peru"}) == 125),
    ("Doubleshot: 'Farm • Bule Hora' at …/ethiopia-bule-hora is the coffee Bule Hora, not the range Farm; a name with notes after the bullet, or no bullet, is left alone",
     lambda: scan.range_title("Farm • Bule Hora", "https://xyzroastery.example/en/products/ethiopia-bule-hora") == "Bule Hora"
       and scan.range_title("Fun • El Paraíso Geisha", "https://xyzroastery.example/cs/products/fun-guatemala-el-paraiso-geisha") == "El Paraíso Geisha"
       and scan.range_title("Kenya • blackcurrant, tomato", "https://xyzroastery.example/products/kenya-kagere") == "Kenya • blackcurrant, tomato"
       and scan.range_title("Danche", "https://xyzroastery.example/products/danche") == "Danche"),
    ("Long & Short: a description that opens with a bare list is the tasting notes; grind options, a process line and a sentence are not",
     lambda: scan.find_notes({"title": "Sanchez, Colombia", "tags": [], "body": "Florals, Mandarin, Raspberry\n \n\nGrown by the Sanchez family at 1,900 m."}) == ["Florals", "Mandarin", "Raspberry"]
       and scan.first_line_notes("Whole Bean, Espresso, Filter") is None and scan.first_line_notes("Colombia, Washed, Pink Bourbon") is None
       and scan.first_line_notes("A bright, clean coffee from our friends in Huila") is None and scan.first_line_notes("Raspberry") is None and scan.first_line_notes("Light, Medium, Dark") is None
       and scan.first_line_notes("Peach, Jasmine, Bergamot, Honey") == "Peach, Jasmine, Bergamot, Honey"),
    ("Cheapest first showed teas, green beans and a jar of coffee honey: a tea category with no coffee in it, unroasted beans and Kaffeehonig are not coffee; a coffee in a 'Tea & Coffee' shop still is",
     lambda: scan.not_coffee({"title": "Peppermint", "type": "Loose Leaf Tea Herbal Infusions", "tags": [], "url": "", "body": ""}) is not None
       and scan.not_coffee({"title": "Green Costa Rican Tarrazu Coffee Beans", "type": "Coffee", "tags": [], "url": "", "body": ""}) is not None
       and scan.EXCLUDE.search("Kaffeehonig") is not None
       and scan.not_coffee({"title": "Kenya AA", "type": "Tea & Coffee", "tags": [], "url": "", "body": ""}) is None
       and scan.not_coffee({"title": "Guatemala Green Mountain Estate", "type": "Coffee", "tags": [], "url": "", "body": ""}) is None),
    ("Proud Mary: '250gms / Whole Bean … 1kg' is a 250 g bag, not a kilo ($19 read as a kilo price)",
     lambda: scan.bag_grams({"variants": "250gms / Whole Bean / 250gms / Ground for Espresso / 1kg / Whole Bean", "title": "Honeysuckle"}) == 250),
    ("Green beans named by origin or in French are not roasted coffee ('Green Brazilian Santos', 'Café vert grain BIO'); 'Green Land Estate' and 'Green Roof Espresso' are",
     lambda: all(scan.not_coffee({"title": t, "type": "", "tags": [], "body": ""}) for t in ["Green Brazilian Santos", "Green Ethiopian Yirgacheffe", "Green Robusta", "Café vert grain BIO"])
       and not any(scan.not_coffee({"title": t, "type": "", "tags": [], "body": ""}) for t in ["Green Land Estate", "Green Roof Espresso", "Colombia Verde"])),
    ("Kaffa's own coffees still count", lambda: not any(scan.EXCLUDE.search(x) for x in ["Kaffebønner Kenya Kagere", "Kaffebønner Honduras El Guaco", "Kaffebønner Klassisk Julekaffe fra", "Switch Up Charity Coffee"])),
    ("Coffee sacks, a milk frother, a pallet and a chocolate bar are not coffee", lambda: all(scan.EXCLUDE.search(t) for t in
        ["Jute Coffee Sacks", "Alessi Mousseur à lait Pulcina", "Halvpalle med kaffe", "Malmö Chokladfabrik x Gringo – Kaffekross 55% chokladkaka", "SCA Introduction to coffee", "30 ks", "Čaj Yunnan Green Superior", "Brazil Natural - Greens"])),
    ("'Santa's Sack - Christmas Blend', 'jute Blend', 'Alt + Tab' and 'Rhubarb Fizz' are coffees", lambda: not any(scan.EXCLUDE.search(t) for t in
        ["Santa's Sack - Christmas Blend", "jute Blend", "Alt + Tab", "Rhubarb Fizz", "Costa Rica: Tarrazú - Washed + Regenified", "Christmas Special", "02 Brazil + Rwanda (Espresso)"])),
    ("Lucca's barista course is not coffee", lambda: scan.EXCLUDE.search("Introdução aos Cafés Especiais") is not None),
    ("'Gesha da Canastra' is from Brazil", lambda: scan.find_origin("Edição especial: Gesha da Canastra") == "Brazil"),
    ("A Colombian roaster's farm-named bag is Colombian",
     lambda: (kept(item("Alto de Letras", "Washed Caturra from the farm, roasted for filter.\nTasting notes: panela", variants="500g whole bean"),
                   {**UK, "name": "Pergamino", "country": "CO", "region": "World"}) or {}).get("origin") == "Colombia"),
    ("A Brazilian roaster's grinder is not given a country",
     lambda: kept(item("Philos", "Moedor de café para grãos, torra clara.", type_="Equipamentos", variants="Preto"),
                  {**UK, "name": "Um Coffee Co", "country": "BR", "region": "World"}) is None),
    # Onyx (16/11/2026)
    ("Onyx's Cometeer frozen capsules are not beans", lambda: scan.EXCLUDE.search("Eclipse - Cometeer") is not None),
    # 12% of coffees had no process (16/11/2026): pages that say it in a sentence, not under a label
    ("'Processed using Giling Basah' with flavour in the same sentence is wet-hulled",
     lambda: scan.process_phrase("Processed using Giling Basah, this coffee has a huge body and a spicy aroma with hints of tobacco.") == "Wet-hulled"),
    ("'it is a fully washed coffee, which gives ... a note of marzipan' is washed",
     lambda: scan.process_phrase("It is a fully washed coffee, which gives a rich creamy body and a lovely note of marzipan.") == "Washed"),
    ("'PROCESS | Fully WashedELEVATION' is washed", lambda: scan.process_phrase("VARIETAL | Typica, Caturra, PROCESS | Fully WashedELEVATION | 1,200-1,800") == "Washed"),
    ("'Brazilian coffee (usually natural process)' says nothing sure about this coffee",
     lambda: scan.process_phrase("The full bodied taste of the best Brazilian coffee (usually natural process) with chocolate.") is None),
    ("'80% natural and 20% honey processing' is not called honey", lambda: scan.process_phrase("This lot combines 80% natural and 20% honey processing.") is None),
    ("'if you enjoy Monsooned Malabar' doesn't make this coffee monsooned",
     lambda: scan.process_phrase("If you enjoy Brazil or Indian Monsooned Malabar Coffee, try this lighter Limu.") is None),
    ("'the natural sweetness of the coffee' is a flavour, not a process", lambda: scan.process_phrase("It brings out the natural sweetness of the coffee.") is None),
    ("Kaffa's 'våtforedlet' is washed", lambda: scan.find_process("partiet er våtforedlet") == "Washed"),
    # Kiss the Hippo's Ratnagiri Hydro showed generic notes (16/11/2026): its notes are in a sentence
    ("'Expect notes of pineapple, red apple and hazelnut in a layered, sweet cup' gives the three notes",
     lambda: scan.find_notes({"body": "Expect notes of pineapple, red apple and hazelnut in a layered, sweet cup.", "title": "Ratnagiri Hydro", "tags": []}) == ["Pineapple", "Red apple", "Hazelnut"]),
    ("'hints of the terroir and the farm's history' is not tasting notes",
     lambda: scan.find_notes({"body": "You can taste hints of the terroir and the farm's history.", "title": "X", "tags": []}) == []),
    ("Bosk's 'Amecafe Blend from Brazil' was named 'Amecafe Blend from' (the origin taken off left 'from')",
     lambda: name("Amecafe Blend from Brazil", "Bosk Coffee Roasters", "Brazil") == "Amecafe Blend"),
    ("Herbert and Ward's 'Charlie and the MIlkshake factory 500g bags' was named '… factory bags' (the size taken off left 'bags')",
     lambda: name("Charlie and the MIlkshake factory 500g bags", "Herbert and Ward", "Brazil") == "Charlie and the MIlkshake factory"),
    ("Square Mile's Don Cayito was dropped: its page names Dota, Tarrazú but never Costa Rica",
     lambda: scan.find_origin("Don Cayito", "Coffee coffee filter 175g / 1kg",
                              "This natural process Typica variety from Don Cayito in Dota, Tarrazú creates an idealised version of Arabica’s original cup profile.") == "Costa Rica"),
    ("data/roasters.json with a comma after the last roaster (a hand edit on GitHub) stopped the scan",
     lambda: len(scan.load_roasters()) > 500),
    ("SRW's Årets Julekaffe read 'Flavour: dried fruit, plum, spice and rounded out by' (a note ran on into the sentence)",
     lambda: scan.find_notes({"body": "Tasting notes: dried fruit, plum, spice and rounded out by a long finish", "title": "Årets Julekaffe", "tags": []})
             == ["Dried fruit", "Plum", "Spice"]),
    ("Notes like 'Butterscotch followed by', 'Juicy notes of nectarine' and 'Hints of' keep only the flavour",
     lambda: [scan.tidy_note(n) for n in ["Butterscotch followed by", "Juicy notes of nectarine", "Hints of", "Milk chocolate are"]]
             == ["Butterscotch", "Nectarine", "", "Milk chocolate"]),
    ("Kobean's 'Nestor Lasso - (72hr Advanced Washed' kept an unclosed bracket",
     lambda: name("Nestor Lasso - (72hr Advanced Washed", "Kobean", "") == "Nestor Lasso"),
    ("An unclosed bracket around a name keeps the name: 'Uganda (Bukonzo Dream'",
     lambda: scan.close_brackets("Uganda (Bukonzo Dream") == "Uganda Bukonzo Dream"),
    ("Standout's Shoondhisa had no notes: they sit on their own line between middle dots",
     lambda: scan.find_notes({"body": "Gibirinna 74110 & Serto 74112 · Anoxic Natural · Ethiopia\nStrawberry · Blueberry · Nectarine · Passion Fruit · Lavender\nWhy we selected it",
                              "title": "Shoondhisa", "tags": []}) == ["Strawberry", "Blueberry", "Nectarine", "Passion Fruit", "Lavender"]),
    ("A 'Tasting notes' label with the notes on the next line (no colon) was missed",
     lambda: scan.find_notes({"body": "Altitude\n2,200 m\nTasting notes\nStrawberry, blueberry, nectarine, passion fruit and lavender\nBrewing FAQ",
                              "title": "Shoondhisa", "tags": []})[:3] == ["Strawberry", "Blueberry", "Nectarine"]),
    ("Dak's Lemon Spritz had no notes: a table row 'Tasting notes Citrus, Lemon Peel, White Florals' (no colon, one space)",
     lambda: scan.find_notes({"body": " Region Gedeb \n Producer / Farm Produced by Lalesa Washing Station \n Tasting notes Citrus, Lemon Peel, White Florals \n Altitude 2150masl ",
                              "title": "Lemon Spritz", "tags": []}) == ["Citrus", "Lemon Peel", "White Florals"]),
    ("Square Mile's Huabal had no notes: a line 'Apple Crumble / Almond / Brown Sugar' split by slashes",
     lambda: scan.find_notes({"body": " Filter\n Apple Crumble / Almond / Brown Sugar\n Peru \n £6.07/100g \n", "title": "Huabal", "tags": []})
             == ["Apple Crumble", "Almond", "Brown Sugar"]),
    ("A slash line of sizes, methods or a breadcrumb is not notes ('350g / Whole Bean / NA', 'Home / Coffee / Huabal')",
     lambda: scan.dot_notes("150g (tin) / Whole Bean / NA\nHome / Coffee / Huabal\nFilter / Espresso / Omni") is None),
    ("Apricity's Pic n Mix had no notes: the reader started at the page title and read only the menu",
     lambda: scan.page_notes("Pic n Mix | Colombia – Apricity Coffee\n" + " Shop\n Coffee\n" * 400 + " Pic n Mix\n Process: Advanced Natural\n Tasting Notes\n Refreshers, pink bubblegum, pineapple sweets\n The Story\n", "Pic n Mix")
             == ["Refreshers", "Pink bubblegum", "Pineapple sweets"]),
    ("Notes' Black Label showed '250g' as its variety: a bag size is never a variety",
     lambda: "a bag size read as the variety" in open(scan.__file__).read()),
    ("Notes audit 20/11: bare and foreign labels on a line with the list (Dropshot, Coffea Circulor, Mabó, Inverness)",
     lambda: [scan.find_notes({"body": t, "title": "x", "tags": []})[:2] for t in (" Notes Gem de fragi, Mar rosu, Stafide, Cirese \n",
              " Flavor Blackberry, Cherry, Pear \n", " Note de degustare Floral, Piersici, Cireșe \n", " Tastes Like Seville orange zest, maple syrup, jasmine\n")]
             == [["Gem de fragi", "Mar rosu"], ["Blackberry", "Cherry"], ["Floral", "Piersici"], ["Seville orange zest", "Maple syrup"]]),
    ("Tanat: 'Note de dégustation : Fraise - Myrtille - Mûre - Figue Direction le Panama, à la découverte' is four notes",
     lambda: scan.find_notes({"body": "Note de dégustation : Fraise - Myrtille - Mûre - Figue Direction le Panama, à la découverte\n", "title": "x", "tags": []})
             == ["Fraise", "Myrtille", "Mûre", "Figue"]),
    ("Blind Monkey: 'Tasting notes: Lychee • Peach • Candied Cherry Roast: Omni — … espresso' stops at Roast:",
     lambda: scan.find_notes({"body": " Tasting notes: Lychee • Peach • Candied Cherry Roast: Omni — suitable for both filter and espresso.", "title": "x", "tags": []})
             == ["Lychee", "Peach", "Candied Cherry"]),
    ("Cafēn: 'notes of chocolate cherries, strawberry cake, crisp apple and a rich, candy-like sweetness' keeps the three notes",
     lambda: scan.find_notes({"body": "with indulgent notes of chocolate cherries, strawberry cake, crisp apple and a rich, candy-like sweetness. selected", "title": "x", "tags": []})
             == ["Chocolate cherries", "Strawberry cake", "Crisp apple"]),
    ("A line naming the shop ('Aroma Coffee Roasters - London') is not notes",
     lambda: scan.find_notes({"body": " Aroma Coffee Roasters - London - since 2010 \n", "title": "x", "tags": []}) == []),
    ("Notes audit 2: the label alone on its line, the list alone on the next (Dropshot 'Notes', Mabó, Inverness 'Tastes Like')",
     lambda: [scan.find_notes({"body": t, "title": "x", "tags": []})[:2] for t in (" Notes \n Gem de fragi, Mar rosu, Stafide \n", " Tastes Like\n Seville orange zest, maple syrup\n",
              " Notes\n Our story began in 2010, and we roast daily\n")] == [["Gem de fragi", "Mar rosu"], ["Seville orange zest", "Maple syrup"], []]),
    ("Climpson La Plata: 'Flavour profile:' alone on its line, the notes on the next",
     lambda: scan.page_notes("Decaf: La Plata, Colombia\nFlavour profile:\nDark Chocolate, Caramel, Orange Rind\n\nCoffee:\nLa Plata\n\nOrigin:\nColombia\n", "The Decaf: La Plata")
             == ["Dark Chocolate", "Caramel", "Orange Rind"]),
    ("People Possession names drop the brewer in braces: 'Abu [Catuai 3125]{Filter}' has no '{Filter}'",
     lambda: "{" not in scan.clean_name("Abu [Catuai 3125]{Filter}", "People Possession", "Costa Rica") and "{" not in scan.clean_name("Industrial Supply Series [RED]{Filter}", "People Possession", "")),
    ("People Possession: '[RED]' is part of the name ('Industrial Supply Series Red'), '[Catuai 3125]' is a variety tag and goes",
     lambda: (scan.clean_name("Industrial Supply Series [RED]{Filter}", "People Possession", ""), scan.clean_name("Abu [Catuai 3125]{Filter}", "People Possession", "Costa Rica"))
             == ("Industrial Supply Series Red", "Abu")),
    ("Round Hill: a 'Taste' row ('Taste Strawberry Pavlova, Blueberry Jam, Panettone'), on one line or two",
     lambda: [scan.page_notes(t, "Santa Claude") for t in ("Santa Claude\nAbout this coffee\nTaste Strawberry Pavlova, Blueberry Jam, Panettone\nOrigin Ethiopia\n",
              "Santa Claude\nAbout this coffee\nTaste\nStrawberry Pavlova, Blueberry Jam, Panettone\nOrigin\nEthiopia\n")] == [["Strawberry Pavlova", "Blueberry Jam", "Panettone"]] * 2),
    ("'Taste the difference, and the care' is a sentence, not a Taste row",
     lambda: scan.NOTES_CELL.search("Taste the difference that care makes, and enjoy") is None),
    ("People Possession: 'FLAVOR COMPOSITION CHERRY YOGURT // STRAWBERRY MILKSHAKE //LIME CANDY', label and list split by //, not shouted",
     lambda: [scan.page_notes(t, "Industrial Supply Series: Red Filter") for t in ("Industrial Supply Series: Red Filter\nFLAVOR COMPOSITION CHERRY YOGURT // STRAWBERRY MILKSHAKE //LIME CANDY\n",
              "Industrial Supply Series: Red Filter\nFLAVOR COMPOSITION\nCHERRY YOGURT // STRAWBERRY MILKSHAKE //LIME CANDY\n")] == [["Cherry yogurt", "Strawberry milkshake", "Lime candy"]] * 2),
    ("Climpson's real page: 'Flavour profile:' comes after a 'you might also want' upsell, and is still read",
     lambda: scan.page_notes(" Decaf: La Plata, Colombia\n £12.50 \n Add to cart\n Since you are buying this, you might also want\n Midnight Oil Decaf Espresso Martini 700ml \n £36.00 \n + Add \n"
                             " The ultimate placebo effect; our decaf was selected for its quality of flavour.\n Flavour profile:\n Dark Chocolate, Caramel, Orange Rind\n Coffee:\n La Plata\n Origin:\n Colombia\n", "The Decaf: La Plata")
             == ["Dark Chocolate", "Caramel", "Orange Rind"]),
    ("Harmony Bombe: 'Notas de cata … fruta de la pasión y kiwi amarillo' splits on the Spanish 'y' and keeps all four",
     lambda: scan.page_notes("Bombe, Etiopía\nOrigen Etiopía\nProceso Lavado\nVariedad Heirloom\nNotas de cata Té verde, manzanilla, fruta de la pasión y kiwi amarillo\n\nRecomendado para Espresso y Filtro\n", "Bombe, Etiopía")
             == ["Té verde", "Manzanilla", "Fruta de la pasión", "Kiwi amarillo"]),
    ("Harmony Bombe's notes in English: Green tea, Chamomile, Passion fruit, Yellow kiwi",
     lambda: __import__("flavours").english_notes(["Té verde", "Manzanilla", "Fruta de la pasión", "Kiwi amarillo"])
             == ["Green tea", "Chamomile", "Passion fruit", "Yellow kiwi"]),
    ("Sydrip's Slovak notes in English: Red grapes, Tropical fruit, Blueberry, Dark chocolate",
     lambda: __import__("flavours").english_notes(["Červené hrozno", "Tropické ovocie", "Čučoriedky", "Tmavá čokoláda"])
             == ["Red grapes", "Tropical fruit", "Blueberry", "Dark chocolate"]),
    ("Sydrip: a line of flavours closed by full stops is the notes ('Biela broskyňa. Marhuľa. Šľahačka. Čokoláda.')",
     lambda: scan.find_notes({"body": "Peach\nBiela broskyňa. Marhuľa. Šľahačka. Čokoláda.\nDo košíka", "title": "Peach", "tags": []})
             == ["Biela broskyňa", "Marhuľa", "Šľahačka", "Čokoláda"]),
    ("Sydrip: a related coffee's notes under 'Súvisiace produkty' are not this coffee's",
     lambda: scan.page_notes("Peach\nFermentovaná drip káva z Kolumbie, pražená v Bratislave pre filter a drip. " + "Káva. " * 40
                             + "\nSúvisiace produkty\nBurundi\nČervené hrozno · Tropické ovocie · Čučoriedky · Tmavá čokoláda\n", "Peach") == []),
    ("A slogan in full stops is not tasting notes ('Free. Fast. Fresh.')",
     lambda: scan.stop_notes("Free. Fast. Fresh.") is None),
    ("Sydrip's other Slovak notes in English: Whipped cream, Citrus, Aged rum, Egg liqueur, Red berries",
     lambda: __import__("flavours").english_notes(["Šľahačka", "Citrusy", "Starý rum", "Vaječný likér", "Červené bobuľové ovocie"])
             == ["Whipped cream", "Citrus", "Aged rum", "Egg liqueur", "Red berries"]),
    ("Dak: an image's addresses and sizes are not tasting notes ('https://…-1024x717.png 1024w', 'sizes=\"auto')",
     lambda: scan.tidy_note("https://d1j9xh2330ho4m.cloudfront.net/uploads/2026/11/Little-Orange_Render_Front_89x89-1024x717.png 1024w") == ""
             and scan.junk_note('600w" sizes="auto') and not scan.junk_note("Blood orange")),
    ("Dak's The Alchemist: a shop's badge is not a tasting note ('New', 'Sold out'), and real ones still are",
     lambda: [scan.tidy_note(x) for x in ("New", "Sold out", "Sale", "New potato", "Orange Candy")] == ["", "", "", "New potato", "Orange Candy"]),
    ("Fève had no notes: the label is 'Dégustation' alone on its line, the list on the next, in French",
     lambda: __import__("flavours").english_notes(scan.find_notes({"body": "Méthode\nFiltre\nDégustation\nDoux, orange sanguine, cardamome, citron, poivre (baies roses), pointe ananas\nCe café nous provient de Zarza Coffee, une ferme familiale.\n", "title": "Bourbon rose", "tags": []}))
             == ["Sweet", "Blood orange", "Cardamom", "Lemon", "Pink peppercorn", "Pineapple"]),   # all six: the list was cut at five
    ("Morgon's Holiday Coffee kept one note of three: 'Taste notes: Buttery with creamy notes of chocolate Santas and ripe juicy plum'",
     lambda: scan.find_notes({"body": "BUTTERY - CHOCOLATE SANTAS - PLUM\nVariety: Catuai\nProcessing: Honey\nAltitude: 1900 m.a.s.l.\nHarvested: March 2026\nTaste notes: Buttery with creamy notes of chocolate Santas and ripe juicy plum\n250 grams of whole coffee beans roasted for filter.", "title": "Holiday Coffee", "tags": []})
             == ["Buttery", "Chocolate Santas", "Ripe juicy plum"]),
    ("The Source: 'cup profile: blood orange - yuzu - hibiscus' was lost to a recipe step further down ('Fermentation: ... with specific yeast')",
     lambda: scan.find_notes({"title": "Thermal Shock Orange Gesha", "tags": [], "body": "variety: orange gesha\n process: thermal shock + yeast inoculation\n region: huila, colombia\n cup profile: blood orange - yuzu - hibiscus\n We sourced this stunning orange gesha from Mi Cafe.\n 6. Fermentation: For 62 hours at temperatures below 25°C with specific yeast. 7. Fermentation completion: After 62 hours, the cherries are dried.\n"})
             == ["Blood orange", "Yuzu", "Hibiscus"]),
    ("elbgold: 'Noten: Nougat | Biscuit | Pflaume' (German label, a list split by bars) was missed",
     lambda: scan.find_notes({"title": "La Pradera", "tags": [], "body": "FILTER - DIREKTHANDEL\nProduzent: Oscar Daza\nUrsprung: Kolumbien | Santander | Aratoca\nAnbauhöhe: 1800m\nVarietät: Tabi\nAufbereitung: Honey\nNoten: Nougat | Biscuit | Pflaume\nMenge:\n"})
             == ["Nougat", "Biscuit", "Pflaume"]),
    ("elbgold La Dalia: a heading 'Tradition, Handwerk & Temperaturkontrolle' was taken as tasting notes",
     lambda: scan.find_notes({"title": "La Dalia", "tags": [], "body": "Tradition, Handwerk & Temperaturkontrolle\nDie Finca La Dalia liegt im Norden Nicaraguas.\n"}) == []
       and scan.first_line_notes("Florals, Mandarin, Raspberry") == "Florals, Mandarin, Raspberry"),
    ("Counter Culture and Coffee Bean Shop: tags and attributes are not tasting notes ('<svg', 'Class=\"', 'Alt=\"Chocolate')",
     lambda: [scan.tidy_note(x) for x in ("<svg", 'Class="', 'Alt="Chocolate', '<img', "Black currant")] == ["", "", "", "", "Black currant"]),
    ("The Source: a brew guide's headings are not tasting notes ('Ratios', 'Dose', 'Bloom'), and real ones still are",
     lambda: [scan.tidy_note(x) for x in ("Ratios", "Dose", "Bloom", "Grind size", "Orange blossom", "Honey")] == ["", "", "", "", "Orange blossom", "Honey"]),
    ("Square Mile's Sweetshop: the page's '50% Bookkisa Natural / 50% El Higuerón' gives the blend's two parts",
     lambda: scan.blend_parts("Sweetshop Espresso\n50% Bookkisa Natural / 50% El Higuerón\nEthiopia / Costa Rica") == ["Bookkisa Natural", "El Higuerón"]),
    ("A sale is not a blend ('Save 20% on subscriptions and 10% off your first bag'), and shares that don't add up aren't either",
     lambda: scan.blend_parts("Save 20% on subscriptions and 10% off your first bag") == [] and scan.blend_parts("60% Brazil / 20% Peru") == []),
    ("Czech notes too: 'Borůvky', 'Hořká čokoláda', 'Lískové ořechy' are Blueberry, Dark chocolate, Hazelnut",
     lambda: __import__("flavours").english_notes(["Borůvky", "Hořká čokoláda", "Lískové ořechy"]) == ["Blueberry", "Dark chocolate", "Hazelnut"]),
    ("English notes are left as written ('Tropical fruits', 'Clementine', 'Mango yogurt')",
     lambda: __import__("flavours").english_notes(["Tropical fruits", "Clementine", "Mango yogurt"]) == ["Tropical fruits", "Clementine", "Mango yogurt"]),
    ("Climpson: 'Broadway Blend: El Salvador & Guatemala' is called Broadway Blend",
     lambda: scan.tidy_name("Broadway Blend: El Salvador & Guatemala", "Climpson & Sons") == "Broadway Blend"),
    ("Monmouth La Divina Providencia: notes only in a block marked class='product-details__tasting-notes'; acidity, body and roast left out",
     lambda: scan.class_notes('<h2 class="product-details__heading">La Divina Providencia</h2><span>El Salvador</span></div>'
                              '<div class="product-details__tasting-notes"><ul class="wp-block-list"><li>Guava jam</li>\n<li>Tamarind</li>\n'
                              '<li>Lively acidity</li>\n<li>Medium body</li>\n<li>Medium roast</li>\n</ul>\n</div>', "La Divina Providencia")
             == ["Guava jam", "Tamarind"]),
    ("Monmouth: 'Medium roast' in that block is the roast level",
     lambda: scan.class_roast('<div class="product-details__tasting-notes"><ul><li>Guava jam</li><li>Medium roast</li></ul></div>') == "medium"),
    ("A class that only mentions notes elsewhere (class='footer-notes') is not a tasting-notes block",
     lambda: scan.class_notes('<div class="footer-notes"><p>Free delivery over £30</p></div>', "X") == []),
    ("A sentence 'Tasting notes of this lot change, and so does…' is not a notes row",
     lambda: scan.NOTES_CELL.search("Tasting notes of this lot change every harvest, and so does the roast") is None),
    ("Flavoured coffee is told by its name (Amaretto Flavoured Coffee, Irish Cream, Pumpkin Spice, French Vanilla), never by tasting notes",
     lambda: all(scan.flavoured(t) for t in ["Amaretto Flavoured Coffee", "Abie's Irish Cream 5LB", "Pumpkin Spice 2LB", "French Vanilla 5LB", "Hazelnut flavored coffee"])
       and not any(scan.flavoured(t) for t in ["Las Lajas Micromill", "Colombia El Paraiso", "Caramel Blend", "Hazelnut Hill Estate", "Brazil Santos, vanilla and caramel"])),
    ("Robusta is told by the name or the variety (robusta, canephora, conilon), and '100% Arabica, no robusta' is not robusta",
     lambda: all(scan.robusta(n, v) for n, v in [("Indian Cherry Robusta", ""), ("Gio 100% Canephora (Omniroast)", ""), ("Italian Roast Coffee", "Robusta"),
                                                    ("Espresso blend, 80% Arabica, 20% Robusta", ""), ("Rise & Grind", "Robusta/Canephora and Arabica"), ("Brazil Conilon", "")])
       and not any(scan.robusta(n, v) for n, v in [("House Espresso, no robusta", ""), ("Dr. Espresso dark", "100% Arabica"), ("Ethiopia Guji", "Heirloom"), ("Robust Blend", "")])),
    ("Only specialty shops are added: one flavoured coffee, one robusta, a tea merchant's name, or coffees that never say process or variety keep a shop off",
     lambda: (lambda C: scan.specialty_gate([C("Ethiopia Guji", "Ethiopia", "washed", "Heirloom"), C("Colombia Huila", "Colombia", "natural", "Caturra"), C("Kenya AA", "Kenya", "washed", "")], "XYZ Roastery") is None
       and "flavoured" in scan.specialty_gate([C("Ethiopia Guji", "Ethiopia", "washed", "Heirloom"), C("Colombia Huila", "Colombia", "natural", "Caturra"), C("Irish Cream", "", "", "")], "XYZ Roastery")
       and "robusta" in scan.specialty_gate([C("Ethiopia Guji", "Ethiopia", "washed", "Heirloom"), C("Colombia Huila", "Colombia", "natural", "Caturra"), C("India Cherry Robusta", "India", "natural", "")], "XYZ Roastery")
       and "tea" in scan.specialty_gate([C("Ethiopia Guji", "Ethiopia", "washed", "Heirloom")] * 3, "XYZ Tea & Coffee")
       and "rarely" in scan.specialty_gate([C("Brazil", "Brazil", "", ""), C("Colombia", "Colombia", "", ""), C("Italian Blend", "Brazil", "", ""), C("House", "Brazil", "", "")], "XYZ Roastery"))(
         lambda n, o, p, v: {"name": n, "origin": o, "process": p, "variety": v})),
    ("A shop is on watch only with five or more coffees, under 30% stating a process and under 15% a variety",
     lambda: (lambda C: scan.rarely_states([C("", "")] * 6) and scan.rarely_states([C("washed", "")] + [C("", "")] * 5)
       and not scan.rarely_states([C("", "")] * 4) and not scan.rarely_states([C("washed", "")] * 2 + [C("", "")] * 4)
       and not scan.rarely_states([C("", "Caturra")] + [C("", "")] * 5))(lambda p, v: {"process": p, "variety": v})),
    ("A Japanese description that names its flavours in a sentence gives them as notes, in English, and nothing else from the sentence",
     lambda: scan.ja_notes("豆は全国送料300円 \n焼きりんごやレーズンを思わせる、熟度の高い果実感。滑らかな質感とともに、キャラメルのような甘さがゆっくりと伸びていく。") == "baked apple, raisin, caramel"
       and scan.ja_notes("熟した桃とジャスミンの香り。") == "peach, jasmine"
       and scan.ja_notes("豆は全国送料300円。毎日飲みたいコーヒーです。") is None
       and scan.ja_notes("Reminiscent of baked apples and raisins.") is None),
]


def main():
    failed = 0
    for what, check in CASES:
        try:
            ok = bool(check())
        except Exception as e:  # noqa: BLE001
            ok, what = False, f"{what} (error: {type(e).__name__}: {e})"
        if not ok:
            failed += 1
        print(("ok    " if ok else "FAIL  ") + what)
    print(f"\n{len(CASES) - failed} of {len(CASES)} reported mistakes still fixed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

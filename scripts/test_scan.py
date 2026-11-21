"""Every scanner mistake that has been reported, with the right answer.

The scanner must get all of these right before a change goes live: the daily scan runs this first and stops
(keeping yesterday's list) if any old mistake comes back, and so does every change to scripts/scan.py.
Add each new report here when it's fixed: who reported what, and what the scanner should say.

Run: python3 scripts/test_scan.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import scan  # noqa: E402


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
    ("Drip coffee bags are still not beans", lambda: scan.EXCLUDE.search("Drip coffee bags x10") is not None),
    ("Um Coffee Co: 'Nanolotes | Wush Wush' is named Wush Wush", lambda: name("Nanolotes | Wush Wush", "Um Coffee Co", "Brazil") == "Wush Wush"),
    ("Um Coffee Co: 'Blend | Fruitbomb' is named Fruitbomb", lambda: name("Blend | Fruitbomb", "Um Coffee Co", "Brazil") == "Fruitbomb"),
    ("Coffee++ subscriptions (assinatura) are not coffees", lambda: scan.EXCLUDE.search("Assinatura Café Paraná") is not None),
    ("Coffee++ sachets are not beans", lambda: scan.EXCLUDE.search("Café Intenso| Drip Coffee - 10 Sachês") is not None),
    ("Um Coffee Co's Kony and Super Jolly grinders are not coffee",
     lambda: scan.EXCLUDE.search("Kony SG") is not None and scan.EXCLUDE.search("Super Jolly V Up Pro") is not None),
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
    ("English notes are left as written ('Tropical fruits', 'Clementine', 'Mango yogurt')",
     lambda: __import__("flavours").english_notes(["Tropical fruits", "Clementine", "Mango yogurt"]) == ["Tropical fruits", "Clementine", "Mango yogurt"]),
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

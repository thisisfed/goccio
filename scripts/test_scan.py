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

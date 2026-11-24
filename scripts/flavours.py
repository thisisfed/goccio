"""Tasting notes in English. Roasters write them in their own language ("Té verde, manzanilla, fruta de la pasión y
kiwi amarillo"); the site shows them in English (and the Italian page translates the English). Only notes made
entirely of words in this list are translated, so an English note, or a word we don't know, is left as the roaster
wrote it. Adjectives go in front of the noun, the English way: "kiwi amarillo" -> "Yellow kiwi", "rote Beeren" ->
"Red berries". Linked by de/di/du/von ("mermelada de fresa"), the second part comes first: "Strawberry jam"."""
import re

# whole notes that don't translate word by word
PHRASES = {
    "fruta de la pasión": "passion fruit", "fruta de la pasion": "passion fruit", "maracuyá": "passion fruit", "maracuya": "passion fruit",
    "fruit de la passion": "passion fruit", "frutto della passione": "passion fruit", "maracujá": "passion fruit", "passionsfrucht": "passion fruit",
    "flor de azahar": "orange blossom", "azahar": "orange blossom", "fleur d'oranger": "orange blossom", "fiori d'arancio": "orange blossom",
    "zagara": "orange blossom", "orangenblüte": "orange blossom", "flor de naranjo": "orange blossom",
    "frutos rojos": "red berries", "frutas rojas": "red berries", "fruits rouges": "red berries", "frutti rossi": "red berries",
    "frutos vermelhos": "red berries", "rote beeren": "red berries", "rote früchte": "red berries", "rood fruit": "red berries",
    "frutos del bosque": "forest fruits", "frutti di bosco": "forest fruits", "fruits des bois": "forest fruits", "waldfrüchte": "forest fruits",
    "chocolate negro": "dark chocolate", "chocolate amargo": "dark chocolate", "chocolat noir": "dark chocolate", "cioccolato fondente": "dark chocolate",
    "zartbitterschokolade": "dark chocolate", "dunkle schokolade": "dark chocolate", "pure chocolade": "dark chocolate", "chocolate meio amargo": "dark chocolate",
    # Slovak and Czech (Sydrip, Bratislava: "Červené hrozno, tropické ovocie, čučoriedky a tmavá čokoláda")
    "červené hrozno": "red grapes", "červené hrozny": "red grapes", "biele hrozno": "white grapes", "bílé hrozny": "white grapes",
    "tropické ovocie": "tropical fruit", "tropické ovoce": "tropical fruit", "tmavá čokoláda": "dark chocolate", "horká čokoláda": "dark chocolate",
    "hořká čokoláda": "dark chocolate", "mliečna čokoláda": "milk chocolate", "mléčná čokoláda": "milk chocolate", "biela čokoláda": "white chocolate",
    "bílá čokoláda": "white chocolate", "šľahačka": "whipped cream", "šlehačka": "whipped cream", "starý rum": "aged rum", "vaječný likér": "egg liqueur",
    "červené bobuľové ovocie": "red berries", "citrusy": "citrus", "lesné ovocie": "forest fruits", "lesní ovoce": "forest fruits", "červené ovocie": "red berries",
    "červené ovoce": "red berries", "kôstkové ovocie": "stone fruit", "peckové ovoce": "stone fruit", "sušené ovocie": "dried fruit",
    "sušené ovoce": "dried fruit", "hnedý cukor": "brown sugar", "hnědý cukr": "brown sugar", "trstinový cukor": "cane sugar", "třtinový cukr": "cane sugar",
    "čierny čaj": "black tea", "černý čaj": "black tea", "zelený čaj": "green tea", "čierne ríbezle": "blackcurrant", "černý rybíz": "blackcurrant",
    "červené ríbezle": "redcurrant", "červený rybíz": "redcurrant", "lieskový orech": "hazelnut", "lieskové orechy": "hazelnut",
    "lískový ořech": "hazelnut", "lískové ořechy": "hazelnut", "vlašský orech": "walnut", "vlašský ořech": "walnut", "javorový sirup": "maple syrup",
    "chocolate con leche": "milk chocolate", "chocolat au lait": "milk chocolate", "cioccolato al latte": "milk chocolate", "milchschokolade": "milk chocolate",
    "chocolate ao leite": "milk chocolate", "melkchocolade": "milk chocolate",
    "azúcar moreno": "brown sugar", "azucar moreno": "brown sugar", "sucre roux": "brown sugar", "zucchero di canna": "cane sugar",
    "brauner zucker": "brown sugar", "rohrzucker": "cane sugar", "açúcar mascavo": "brown sugar", "panela": "panela", "rapadura": "rapadura",
    "frutos secos": "nuts", "fruits secs": "dried fruit", "frutta secca": "nuts", "frutas secas": "dried fruit", "trockenfrüchte": "dried fruit",
    "fruta de hueso": "stone fruit", "frutta a nocciolo": "stone fruit", "fruits à noyau": "stone fruit", "steinobst": "stone fruit",
    "fruta tropical": "tropical fruit", "frutta tropicale": "tropical fruit", "fruits tropicaux": "tropical fruit", "tropische früchte": "tropical fruit",
    "té negro": "black tea", "te negro": "black tea", "thé noir": "black tea", "tè nero": "black tea", "schwarztee": "black tea", "chá preto": "black tea",
    "té verde": "green tea", "te verde": "green tea", "thé vert": "green tea", "tè verde": "green tea", "grüntee": "green tea", "grüner tee": "green tea", "chá verde": "green tea",
    "té blanco": "white tea", "thé blanc": "white tea", "tè bianco": "white tea", "weißer tee": "white tea",
    "piel de naranja": "orange peel", "cáscara de naranja": "orange peel", "zeste d'orange": "orange zest", "scorza d'arancia": "orange peel",
    "orangenschale": "orange peel", "zitronenschale": "lemon peel",
    "pan de especias": "gingerbread", "pain d'épices": "gingerbread", "lebkuchen": "gingerbread",
    "caña de azúcar": "sugar cane", "cana de açúcar": "sugar cane", "canna da zucchero": "sugar cane",
    "uva pasa": "raisin", "uvas pasas": "raisins", "pasas": "raisins", "rosinen": "raisins", "uvetta": "raisins", "uva passa": "raisin",
    "flores blancas": "white flowers", "fleurs blanches": "white flowers", "fiori bianchi": "white flowers", "weiße blüten": "white flowers", "flores brancas": "white flowers",
    "blütenhonig": "blossom honey", "flor de saúco": "elderflower", "flor de sauco": "elderflower", "fleur de sureau": "elderflower",
    "fiori di sambuco": "elderflower", "creme caramel": "crème caramel", "crème caramel": "crème caramel", "crème brûlée": "crème brûlée", "fragi": "wild strawberry", "stafide": "raisins", "mar rosu": "red apple", "măr roșu": "red apple",
    "mantequilla": "butter", "beurre": "butter", "burro": "butter", "manteiga": "butter",
    "piña madura": "ripe pineapple", "pina madura": "ripe pineapple",
}

# word: (English, "a" for an adjective, "n" for a noun)
W = {}
def _add(words, en, kind="n"):
    for w in words.split("|"):
        W[w] = (en, kind)

# Slovak and Czech
_add("čučoriedky|čučoriedka|borůvky|borůvka", "blueberry"); _add("jahoda|jahody", "strawberry"); _add("malina|maliny", "raspberry")
_add("černice|ostružiny|ostružina", "blackberry"); _add("čerešňa|čerešne|třešeň|třešně|višňa|višne|višeň|višně", "cherry")
_add("slivka|slivky|švestka|švestky", "plum"); _add("broskyňa|broskyne|broskev|broskve", "peach"); _add("marhuľa|marhule|meruňka|meruňky", "apricot")
_add("jablko|jablká|jablka", "apple"); _add("hruška|hrušky", "pear"); _add("hrozno|hrozny", "grape"); _add("citrón|citróny|citrony", "lemon")
_add("pomaranč|pomaranče|pomeranč|pomeranče", "orange"); _add("mandarínka|mandarinka|mandarínky|mandarinky", "mandarin"); _add("limetka|limetky", "lime")
_add("čokoláda|čokolády", "chocolate"); _add("orechy|ořechy|oriešky|oříšky", "nuts"); _add("mandle|mandľa", "almond"); _add("vanilka", "vanilla")
_add("škorica|skořice", "cinnamon"); _add("jazmín|jasmín", "jasmine"); _add("ananás", "pineapple"); _add("banán", "banana")
_add("hrozienka|rozinky", "raisin"); _add("datle", "date"); _add("figy|fíky", "fig"); _add("melón|meloun", "melon"); _add("ríbezle|rybíz", "currant")
_add("brusnice|brusinky", "cranberry"); _add("maslo|máslo", "butter"); _add("smotana|smetana", "cream"); _add("cukor|cukr", "sugar")
_add("marcipán", "marzipan"); _add("nugát", "nougat"); _add("ovocie|ovoce", "fruit"); _add("čaj", "tea"); _add("víno", "wine"); _add("kvety|květy", "flowers")
_add("tmavá|tmavý|tmavé", "dark", "a"); _add("červené|červená|červený", "red", "a"); _add("čierne|čierna|čierny|černé|černá|černý", "black", "a")
_add("biele|biela|biely|bílé|bílá|bílý", "white", "a"); _add("zelené|zelená|zelený", "green", "a"); _add("žlté|žltá|žltý|žluté|žlutá|žlutý", "yellow", "a")
_add("sladké|sladká|sladký", "sweet", "a"); _add("zrelé|zrelá|zrelý|zralé|zralá|zralý", "ripe", "a"); _add("sušené|sušená|sušený", "dried", "a")
_add("tropické|tropická|tropický", "tropical", "a"); _add("kvetinové|kvetinová|kvetinový|květinové|květinová|květinový", "floral", "a")

# German, as roasters in Germany, Austria and Switzerland write them
_add("salbei", "sage"); _add("rosenwasser", "rose water"); _add("kakaonibs|kakao nibs", "cacao nibs"); _add("pekannuss|pekannüsse", "pecan"); _add("blutorange|blutorangen", "blood orange")
_add("waldbeeren|waldbeere", "forest berries"); _add("vollmilchschokolade", "milk chocolate"); _add("schoggi", "chocolate"); _add("weingummi", "wine gum"); _add("gebrannte mandeln", "candied almonds")
_add("geröstete nüsse", "roasted nuts"); _add("nuss|nüsse", "nut"); _add("maracuja", "passion fruit"); _add("süßer apfel|süsser apfel", "sweet apple"); _add("bratapfel", "baked apple")
_add("muscovado zucker|muscovadozucker", "muscovado sugar"); _add("zitronengras", "lemongrass"); _add("karamellisierter pfirsich", "caramelised peach"); _add("kaffeeblüte", "coffee blossom")
_add("spekulatius", "speculoos"); _add("hauch von zimt", "cinnamon"); _add("ceylon tee|ceylontee", "Ceylon tea"); _add("schwarzer tee|schwarztee", "black tea"); _add("kirschlikör", "cherry liqueur"); _add("süß|süss|süßer|süsser", "sweet"); _add("schokoladig|schokoladiger", "chocolatey")
_add("stachelbeere|stachelbeeren", "gooseberry"); _add("litschi", "lychee"); _add("rosine|rosinen", "raisin"); _add("rosmarin", "rosemary"); _add("pflaumenmus", "plum jam"); _add("glühwein", "mulled wine")
_add("hagebutte", "rosehip"); _add("mirabelle|mirabellen", "mirabelle plum"); _add("florale noten", "floral"); _add("blütenhonig", "blossom honey"); _add("holunder", "elderberry")
_add("nussig", "nutty", "a"); _add("schokoladig", "chocolatey", "a"); _add("fruchtig", "fruity", "a"); _add("beerig", "berry-like", "a"); _add("süss|süß|süßlich|süsslich", "sweet", "a"); _add("weich|sanft|geschmeidig", "soft", "a")
_add("kräftig|intensiv", "bold", "a"); _add("spritzig", "sparkling", "a"); _add("vollmundig", "full-bodied", "a"); _add("ausgewogen", "balanced", "a"); _add("aromatisch", "aromatic", "a"); _add("malzig", "malty", "a")
_add("erdig", "earthy", "a"); _add("rauchig", "smoky", "a"); _add("rund", "round", "a"); _add("klar", "clean", "a")

# French, as Fève writes them
_add("orange sanguine|oranges sanguines", "blood orange"); _add("poivre (baies roses)|poivre (baies roses|baies roses|baie rose", "pink peppercorn")
_add("pointe ananas|pointe d'ananas|pointe d’ananas", "pineapple"); _add("fruits jaunes", "yellow fruit"); _add("fruité", "fruity"); _add("sucré", "sweet")
_add("épices|epices", "spices")

# fruit
_add("fresa|fresas|fraise|fraises|fragola|fragole|morango|morangos|erdbeere|erdbeeren|aardbei|aardbeien|căpșuni|capsuni|jordgubbe|jordbær", "strawberry")
_add("frambuesa|frambuesas|framboise|framboises|lampone|lamponi|framboesa|himbeere|himbeeren|framboos|frambozen|zmeură|hallon|hindbær", "raspberry")
_add("arándano|arandano|arándanos|myrtille|myrtilles|mirtillo|mirtilli|mirtilo|heidelbeere|blaubeere|blaubeeren|bosbes|blåbär|blåbær|afine", "blueberry")
_add("mora|moras|mûre|mûres|mora di rovo|amora|brombeere|brombeeren|braam|björnbär|brombær", "blackberry")
_add("cereza|cerezas|cerise|cerises|ciliegia|ciliegie|cereja|kirsche|kirschen|kers|kersen|cireșe|körsbär|kirsebær", "cherry")
_add("guinda|guindas|griotte|amarena|sauerkirsche", "sour cherry")
_add("ciruela|ciruelas|prugna|prugne|ameixa|pflaume|pflaumen|pruim|pruimen|prună|plommon|blomme", "plum")
_add("melocotón|melocoton|durazno|pêche|pêches|pesca|pesche|pêssego|pfirsich|pfirsiche|perzik|piersică|persika|fersken", "peach")
_add("albaricoque|albaricoques|abricot|abricots|albicocca|albicocche|damasco|aprikose|aprikosen|abrikoos|caisă|aprikos|abrikos", "apricot")
_add("nectarina|nectarine|nettarina|nektarine", "nectarine")
_add("manzana|manzanas|pomme|pommes|mela|mele|maçã|apfel|äpfel|appel|mår|äpple|æble|măr", "apple")
_add("pera|peras|poire|poires|pere|birne|birnen|peer|peren|päron|pære", "pear")
_add("uva|uvas|grappolo|traube|trauben|druif|druiven|strugure|druva|drue", "grape")
_add("naranja|naranjas|orange|oranges|arancia|arance|laranja|orangen|sinaasappel|portocală|apelsin|appelsin", "orange")
_add("mandarina|mandarinas|mandarine|mandarino|tangerina|clementina|clémentine|clementine", "mandarin")
_add("limón|limon|limones|citron|limone|limoni|limão|zitrone|zitronen|citroen|lămâie|citron", "lemon")
_add("lima|limas|lime|citron vert|limette|limetten|limoen", "lime")
_add("pomelo|pamplemousse|pompelmo|toranja|grapefruit|grapefruits|pampelmuse", "grapefruit")
_add("bergamota|bergamote|bergamotto|bergamotte", "bergamot")
_add("piña|pina|ananas|abacaxi", "pineapple")
_add("mango|mangos|mangue|manga|mangue", "mango")
_add("papaya|papaye|mamão|papaia", "papaya")
_add("plátano|platano|banana|banane|bananen", "banana")
_add("coco|noix de coco|cocco|kokos|kokosnuss", "coconut")
_add("lichi|litchi|lychee|lici", "lychee")
_add("guayaba|goyave|guava|goiaba", "guava")
_add("higo|higos|figue|figues|fico|fichi|figo|feige|feigen|vijg|vijgen|smochină|fikon|figen", "fig")
_add("dátil|datil|dátiles|datte|dattes|dattero|datteri|tâmara|dattel|datteln|dadel|dadels", "date")
_add("grosella|grosellas|groseille|ribes|groselha|johannisbeere|johannisbeeren|bes|bessen|coacăze|vinbär|ribs", "currant")
_add("grosella negra|cassis|ribes nero|schwarze johannisbeere|zwarte bes", "blackcurrant")
_add("granada|grenade|melograno|romã|granatapfel|granaatappel|rodie|granatäpple", "pomegranate")
_add("sandía|sandia|pastèque|anguria|melancia|wassermelone|watermeloen|pepene", "watermelon")
_add("melón|melon|melone|melão|meloen", "melon")
_add("membrillo|coing|mela cotogna|marmelo|quitte|kweepeer|gutui", "quince")
_add("ruibarbo|rhubarbe|rabarbaro|rhabarber|rabarber|rabarbar", "rhubarb")
_add("kiwi|kiwis", "kiwi")
_add("arándano rojo|cranberry|airelle|mirtillo rosso|cramberry|preiselbeere|veenbes", "cranberry")
_add("saúco|sauco|sureau|sambuco|sabugueiro|holunder|holunderblüte|vlierbes|soc|fläder|hyld", "elderflower")
_add("cítricos|citricos|cítrico|citrico|agrumes|agrumi|cítricos|zitrus|zitrusfrüchte|citrus|citrice", "citrus")
_add("fruta|frutas|fruit|fruits|frutta|frutto|frutti|frucht|früchte|obst|fruct|frukt", "fruit")
_add("baya|bayas|baies|bacche|bagas|beeren|beere|bessen|fructe de pădure|bär", "berries")
# sweet, nutty, spice
_add("miel|miele|mel|honig|honing|miere|honung|honning", "honey")
_add("caramelo|caramel|caramella|caramello|karamell|karamel|caramel", "caramel")
_add("azúcar|azucar|sucre|zucchero|açúcar|zucker|suiker|zahăr|socker|sukker", "sugar")
_add("melaza|mélasse|melassa|melaço|melasse|melasse|melasă", "molasses")
_add("chocolate|chocolat|cioccolato|schokolade|chocolade|ciocolată|choklad|chokolade", "chocolate")
_add("cacao|cacau|kakao|cacaco|cacao", "cocoa")
_add("vainilla|vanille|vaniglia|baunilha|vanilla", "vanilla")
_add("canela|cannelle|cannella|zimt|kaneel|scorțișoară|kanel", "cinnamon")
_add("clavo|clou de girofle|chiodi di garofano|cravo|nelke|nelken|kruidnagel", "clove")
_add("cardamomo|cardamome|kardamom|kardemom", "cardamom")
_add("jengibre|gingembre|zenzero|gengibre|ingwer|gember|ghimbir|ingefära|ingefær", "ginger")
_add("nuez moscada|muscade|noce moscata|muskat|muskatnuss|nootmuskaat", "nutmeg")
_add("pimienta|poivre|pepe|pimenta|pfeffer|peper", "pepper")
_add("almendra|almendras|amande|amandes|mandorla|mandorle|amêndoa|mandel|mandeln|amandel|amandelen|migdale|mandlar", "almond")
_add("avellana|avellanas|noisette|noisettes|nocciola|nocciole|avelã|haselnuss|haselnüsse|hazelnoot|alune|hasselnöt|hasselnød", "hazelnut")
_add("nuez|nueces|noix|noce|noci|noz|nozes|walnuss|walnüsse|walnoot|nucă|valnöt", "walnut")
_add("cacahuete|cacahuate|maní|cacahuète|arachide|amendoim|erdnuss|pinda|alune de pământ", "peanut")
_add("pistacho|pistache|pistacchio|pistazie|pistazien", "pistachio")
_add("pecana|pécan|pecan|noce pecan", "pecan")
_add("macadamia|macadâmia", "macadamia")
_add("galleta|biscuit|biscotto|biscoito|keks|kekse|koekje|biscuiți|kex", "biscuit")
_add("mazapán|mazapan|massepain|marzapane|marzipan|marsepein", "marzipan")
_add("turrón|turron|nougat|torrone", "nougat")
_add("regaliz|réglisse|liquirizia|alcaçuz|lakritz|lakritze|drop|lakrits", "liquorice")
_add("mermelada|confiture|marmellata|confettura|geleia|marmelade|konfitüre|jam|gem|dulceață|sylt|marmelad", "jam")
_add("tarta|tarte|torta|kuchen|taart|tort|kaka", "cake")
_add("pan|pain|pane|pão|brot|brood|pâine|bröd|brød", "bread")
_add("tofe|toffee|toffe|caramella mou", "toffee")
_add("panela|rapadura", "panela")
_add("crema|crème|creme|sahne|room|smântână|grädde|fløde", "cream")
_add("yogur|yaourt|yogurt|iogurte|joghurt|yoghurt|iaurt", "yoghurt")
_add("vino|vin|vinho|wein|wijn|vin", "wine")
_add("ron|rhum|rum", "rum")
_add("whisky|whiskey", "whisky")
# flowers, herbs, tea
_add("flores|fleurs|fiori|blüten|blume|blumen|bloemen|flori|blommor|blomster", "flowers")
_add("flor|fleur|fiore|blüte|bloem|floare|blomma|blomst", "blossom")
_add("floral|florales|floraux|floreale|floreali|blumig|bloemig|florale", "floral", "a")
_add("jazmín|jazmin|jasmin|gelsomino|jasmim|jasmijn|iasomie", "jasmine")
_add("rosa|rosas|rose|roses|rosen|roos|rozen|trandafir|ros", "rose")
_add("lavanda|lavande|lavendel|levănțică", "lavender")
_add("hibisco|hibiscus|ibisco|hibiskus", "hibiscus")
_add("manzanilla|camomille|camomilla|camomila|kamille|kamillen|mușețel|kamomill", "chamomile")
_add("té|te|thé|tè|chá|tee|thee|ceai|tea|te", "tea")
_add("hierba|hierbas|herbe|herbes|erba|erbe|erva|kräuter|kruiden|ierburi|örter|urter", "herbs")
_add("menta|menthe|minze|munt|mentă|mynta|mynte", "mint")
_add("albahaca|basilic|basilico|manjericão|basilikum|basilicum", "basil")
_add("tomillo|thym|timo|tomilho|thymian|tijm", "thyme")
_add("melisa|mélisse|melissa|zitronenmelisse|citroenmelisse", "lemon balm")
_add("hierbaluisa|verveine|verbena|zitronenverbene|lemon verbena", "lemon verbena")
_add("tabaco|tabac|tabacco|tabak", "tobacco")
_add("cedro|cèdre|zeder|ceder", "cedar")
# words that describe
_add("verde|vert|verte|grün|grüne|grüner|groen|verde|grön|grøn", "green", "a")
_add("amarillo|amarilla|jaune|giallo|gialla|amarelo|amarela|gelb|gelbe|gelber|geel|galben|gul", "yellow", "a")
_add("rojo|roja|rojos|rojas|rouge|rouges|rosso|rossa|rossi|rosse|vermelho|vermelha|rot|rote|roter|rood|rode|roșu|röd|röda|rød", "red", "a")
_add("negro|negra|negros|noir|noire|noirs|nero|nera|neri|preto|preta|schwarz|schwarze|zwart|zwarte|negru|svart|sort", "black", "a")
_add("blanco|blanca|blancos|blancas|blanc|blanche|bianco|bianca|branco|branca|weiß|weiße|weißer|wit|witte|alb|vit|hvid", "white", "a")
_add("morado|morada|roxo|lila|paars|mov", "purple", "a")
_add("violeta|violette|violetta|violetas|veilchen|viooltje", "violet")
_add("dulce|dulces|doux|douce|dolce|doce|süß|süße|zoet|zoete|dulce|söt|sød", "sweet", "a")
_add("maduro|madura|maduros|maduras|mûr|mûrs|maturo|matura|maturi|reif|reife|rijp|rijpe|copt|mogen|moden", "ripe", "a")
_add("seco|seca|secos|secas|sec|sèche|secco|secca|secchi|getrocknet|getrocknete|gedroogd|gedroogde|uscat|torkad|tørret", "dried", "a")
_add("tostado|tostada|tostados|grillé|grillée|tostato|tostata|torrado|torrada|geröstet|geröstete|geroosterd|prăjit|rostad|ristet", "toasted", "a")
_add("confitado|confitada|confit|confite|candito|candita|cristalizado|kandiert|kandierte|gekonfijt|confiat", "candied", "a")
_add("cocido|cocida|cuit|cuite|cotto|cotta|cozido|gekocht|gekochte|gekookt|fiert", "cooked", "a")
_add("jugoso|jugosa|juteux|juteuse|succoso|succosa|suculento|suculenta|saftig|saftige|sappig|sappige|suculent|saftig", "juicy", "a")
_add("fresco|fresca|frais|fraîche|frische|frisch|vers|verse|proaspăt|färsk|frisk", "fresh", "a")
_add("tropical|tropicales|tropicaux|tropicale|tropicali|tropisch|tropische", "tropical", "a")
_add("cremoso|cremosa|crémeux|crémeuse|cremoso|cremig|cremige|romig|cremos|krämig|cremet", "creamy", "a")
_add("ácido|acido|acida|acide|acidulo|säuerlich|zuur|acru", "tart", "a")
_add("brillante|brillant|brillante|brilhante|hell|helder|strălucitor", "bright", "a")
_add("oscuro|oscura|foncé|foncée|scuro|scura|escuro|escura|dunkel|dunkle|dunkler|donker|donkere|închis|mörk|mørk", "dark", "a")
_add("especiado|especiada|épicé|épicée|speziato|speziata|condimentado|würzig|würzige|kruidig|condimentat|kryddig", "spiced", "a")
_add("pequeño|pequeña|petit|petite|piccolo|piccola|pequeno|klein|kleine|mic", "small", "a")
_add("cítrico|citrico|agrumé|agrumato|zitrisch|citrusachtig", "citrus", "a")
_add("pasa|pasas", "raisins")
_add("piel|cáscara|cascara|zeste|écorce|scorza|buccia|casca|schale|schil|coajă|skal", "peel")
_add("jarabe|sirope|sirop|sciroppo|xarope|sirup|siroop|sirop|sirap", "syrup")
_add("arce|érable|acero|bordo|ahorn|esdoorn|arțar|lönn", "maple")
_add("caña|canne|canna|cana|rohr|riet", "cane")
_add("té|tea", "tea")

LINKS = {"de", "del", "la", "el", "los", "las", "di", "della", "dello", "dei", "delle", "du", "des", "d", "à", "au", "aux", "al",
         "da", "do", "dos", "das", "von", "vom", "der", "die", "het", "van"}


def _german_compound(w):
    """'Blütenhonig' -> 'blossom honey', 'Zitronenschale' -> 'lemon peel': two known words joined, the last one the thing."""
    for i in range(3, len(w) - 2):
        a, b = w[:i], w[i:]
        for aa in (a, a[:-1] if a.endswith(("n", "s")) else None, a[:-2] if a.endswith("en") else None):
            if aa and aa in W and b in W and W[b][1] == "n":
                return f"{W[aa][0]} {W[b][0]}"
    return None


# words that are English as well: a note made only of these (and words we don't know) is already English, left alone
EN_WORDS = set("fruit fruits orange oranges rose roses tropical citrus yogurt clementine whiskey verbena cassis mango banana papaya kiwi "
               "lime melon caramel chocolate vanilla tea cream jam nougat marzipan pecan macadamia lychee guava raisins raisin prunes prune "
               "violet cranberry bergamot nectarine grapefruit rum floral coco honey almond date dates fig figs cherry lemon peach plum pear "
               "apple grape mandarin tangerine apricot strawberry raspberry blueberry blackberry currant pineapple coconut cocoa cacao toffee "
               "biscuit cake bread wine syrup maple cane sugar molasses cinnamon clove cardamom ginger nutmeg pepper hazelnut walnut peanut "
               "pistachio liquorice jasmine lavender hibiscus chamomile herbs mint basil thyme tobacco cedar butter panela berries".split())


def to_english(note):
    """One tasting note in English if every word of it is known, else as the roaster wrote it."""
    raw = (note or "").strip()
    low = re.sub(r"\s+", " ", raw.lower()).strip(" .")
    if not low:
        return raw
    if low in PHRASES:
        en = PHRASES[low]
    elif low in W:
        if low in EN_WORDS:
            return raw
        en = W[low][0]
    else:
        words = [w for w in re.split(r"[\s’']+", low) if w]
        if not any((w in W and w not in EN_WORDS) or (w not in W and _german_compound(w)) for w in words):
            return raw   # nothing foreign in it: already English
        # "mermelada de fresa": the part after the link describes the part before -> "strawberry jam"
        cut = next((i for i, w in enumerate(words) if w in LINKS and 0 < i < len(words) - 1), None)
        groups = [words[cut + 1:], words[:cut]] if cut is not None else [words]
        out = []
        for g in groups:
            g = [w for w in g if w not in LINKS]
            adj, noun = [], []
            for w in g:
                if w in W:
                    (adj if W[w][1] == "a" else noun).append(W[w][0])
                else:
                    c = _german_compound(w)
                    if not c:
                        return raw   # a word we don't know: leave the note as it was
                    noun.append(c)
            out += adj + noun
        en = " ".join(out)
        if en == low:
            return raw
    if en.lower() == low:
        return raw
    return en[:1].upper() + en[1:]


def english_notes(notes):
    """The list in English, without duplicates the translation creates ('Fresa', 'Fraise' -> 'Strawberry')."""
    out = []
    for n in notes or []:
        if not isinstance(n, str):
            continue
        e = to_english(n)
        if e and e.lower() not in (o.lower() for o in out):
            out.append(e)
    return out

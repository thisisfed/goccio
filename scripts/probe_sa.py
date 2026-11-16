import json, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).parent))
import scan
C = [("Pergamino", "https://pergamino.co", "Medellín", "CO"), ("Pergamino US", "https://us.pergamino.co", "Medellín", "CO"),
     ("Amor Perfecto", "https://amorperfectocafe.net", "Bogotá", "CO"), ("Azahar", "https://azaharcoffee.com", "Bogotá", "CO"),
     ("Café San Alberto", "https://cafesanalberto.com", "Buenavista", "CO"), ("Libertario", "https://libertariocoffee.com", "Bogotá", "CO"),
     ("Tropicalia", "https://tropicaliacoffee.com", "Bogotá", "CO"), ("Varietale", "https://varietale.com", "Bogotá", "CO"),
     ("Coffee Lab", "https://coffeelab.com.br", "São Paulo", "BR"), ("Um Coffee Co", "https://umcoffeeco.com.br", "São Paulo", "BR"),
     ("Sofá Café", "https://sofacafe.com.br", "São Paulo", "BR"), ("Coffee++", "https://coffeemais.com", "Poços de Caldas", "BR"),
     ("Tocaya", "https://tocaya.com.br", "São Paulo", "BR"), ("Wolff Café", "https://wolffcafe.com.br", "São Paulo", "BR"),
     ("Lucca Cafés Especiais", "https://luccacafesespeciais.com.br", "Curitiba", "BR"), ("Orfeu", "https://cafeorfeu.com.br", "São Paulo", "BR"),
     ("Origen Tostadores", "https://origentostadores.com", "Lima", "PE"), ("Tostaduría Bisetti", "https://cafebisetti.com", "Lima", "PE"),
     ("Puku Puku", "https://pukupuku.pe", "Lima", "PE"), ("Neira Café Lab", "https://neiracafelab.com", "Lima", "PE"),
     ("LAB Tostadores", "https://labtostadores.com", "Buenos Aires", "AR"), ("Cuervo Café", "https://cuervocafe.com", "Buenos Aires", "AR"),
     ("Full City Coffee House", "https://fullcitycoffeehouse.com", "Buenos Aires", "AR"), ("Café Altura", "https://cafealtura.cl", "Santiago", "CL"),
     ("Wonderful Café", "https://wonderfulcafe.cl", "Santiago", "CL"), ("Café Galletti", "https://cafegalletti.com", "Quito", "EC")]
def probe(c):
    name, shop, city, cc = c
    r = {"name": name, "shop": shop, "city": city, "country": cc, "region": "World"}
    try:
        kind, items, err = scan.scan_roaster(r)
    except Exception as e:  # noqa: BLE001
        return f"{name:<24} {shop:<38} ERROR {type(e).__name__}: {str(e)[:80]}"
    kept = [scan.classify(it, r) for it in items] if kind else []
    kept = [k for k in kept if k]
    return f"{name:<24} {shop:<38} {kind or 'FAILED':<11} items={len(items):<4} kept={len(kept):<4} {err or ''} | " + " ; ".join(f"{k['name']} ({k.get('origin')}, {k.get('process')}, {k.get('price')})" for k in kept[:4])
with ThreadPoolExecutor(8) as pool:
    out = list(pool.map(probe, C))
Path("data/probe_sa.txt").write_text("\n".join(out))

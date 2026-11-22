#!/usr/bin/env python3
"""Every recipe Goccio can make, checked for errors.

Runs the page's own engine for every brewer, dose, method, cup, serve, process and roast (about 57,000 recipes) and checks
the numbers; then puts about 16,000 of them on screen and checks the words. Needs: pip install playwright, and Chromium.
Usage: python3 -m http.server 8765 &   then   python3 scripts/audit_recipes.py
Exit code 1 if anything is wrong.
"""
import collections, json, math, re, sys
from playwright.sync_api import sync_playwright

URL = "http://localhost:8765/?scantest"
GRID = """
const P=['washed','natural','honey','anaerobic','cofer','decaf','unsure'], R=['vlight','light','medium','mdark','dark','unsure'], G=['light','balanced','syrupy','tea'], S=['hot','iced'];
const M=['best','hoffmann','fourSix','ten','rao','onyx','cafec','winton','hedrick'], A=['standard','inverted','wendelboe'];
const each=(B,fn)=>{ for (const br in B) for (const dose of B[br]) for (const pr of P) for (const ro of R) for (const goal of G) for (const serve of S) {
  const ms = br==='v60'||br==='neo' ? M : br==='aero' ? A : [null];
  for (const m of ms) { if (m==='ten'&&dose>=25) continue;
    fn({text:'Test coffee',brewer:br,goal,serve,dose,doses:{},method:br==='aero'?'best':(m||'best'),aeroWay:br==='aero'?m:'standard',roast:ro,process:pr,bag:null},[br,dose,pr,ro,goal,serve,m]); } } };
"""
NUMBERS = "()=>{" + GRID + """
const B={cupping:[8.25,11],v60:[12,15,18,20,25,30],neo:[12,15,18,20,25,30],kalita:[12,15,18,20,25,30],april:[12,15,18,20,25],orea:[12,15,17,20,25],melitta:[12,15,18,20,25,30],chemex:[20,30,40,50],origami:[12,15,18,20,25,30],switch:[15,20,30],clever:[15,18,20,25],aero:[11,13,15],press:[15,30,60],cold:[50,100],espresso:[14,16,18,20],mocca:[30,45,60,75],moka:[7,16,30]};
const res=[], errs=[];
each(B,(st,key)=>{ try { const r=__v60.engine(st); res.push({in:key,m:r.m,kind:r.kind,goal:r.goal,dose:r.dose,water:r.water,ratio:r.ratio,clicks:r.clicks,temp:r.temp,lo:r.lo,hi:r.hi,yieldG:r.yieldG,iced:!!r.iced,total:r.total,ice:r.ice,tds:r.tds,ey:r.ey,
  pours:(r.pours||[]).map(p=>({t:p.t,x:p.x,to:p.to,act:p.act||null,dur:p.dur}))}); } catch(e){ errs.push([key,String(e)]); } });
return {res,errs}; }"""
ON_SCREEN = {"cupping":[11],"v60":[15,30],"neo":[15],"kalita":[15,30],"april":[12],"orea":[17],"melitta":[15],"chemex":[30],"origami":[15],"switch":[20],"clever":[15],"aero":[11,15],"press":[30],"cold":[100],"espresso":[18],"mocca":[60],"moka":[16]}
WORDS = "(B)=>{" + GRID + """
const T=(id)=>{const e=document.getElementById(id); return e?[...e.querySelectorAll('li,span,p,td,div')].filter(x=>!x.children.length||x.tagName==='LI').map(x=>x.textContent.trim()).filter(Boolean).join(' | ')||e.textContent:''};
const res=[], errs=[];
each(B,(st,key)=>{ try { const r=__set(st); res.push({in:key,m:r.m,temp:r.temp,text:['why','expect','tech','dial','specs','pours','clkBody','zrMath'].map(T).join(' || '),dial:T('dial'),specs:document.getElementById('specs').textContent}); } catch(e){ errs.push([key,String(e)]); } });
return {res,errs}; }"""

bad = collections.defaultdict(list)
def F(kind, r, msg=""):
    bad[kind].append((r["in"], msg))

def numbers(d):
    idx = {tuple(r["in"]): r for r in d}
    order = ["vlight", "light", "medium", "mdark", "dark"]
    caps, rcaps = {"anaerobic": 93, "cofer": 92, "decaf": 92}, {"dark": 87, "mdark": 90}
    for r in d:
        br, dose, pr, ro, goal, serve, m = r["in"]
        for k in ("dose", "water", "ratio", "clicks", "lo", "hi"):
            v = r.get(k)
            if v is None or (isinstance(v, float) and math.isnan(v)): F("missing " + k, r)
        if r["dose"] != dose: F("dose changed", r, r["dose"])
        if r["temp"] is not None and not 80 <= r["temp"] <= 100: F("kettle outside 80-100", r, r["temp"])
        if r["lo"] > r["hi"]: F("earliest finish after latest", r, (r["lo"], r["hi"]))
        P = [p for p in r["pours"] if not p["act"]]
        if r["kind"] == "pour":
            if not P: F("no pours", r); continue
            if r["lo"] % 5 or r["hi"] % 5: F("time not a whole 5 s", r, (r["lo"], r["hi"]))
            if r["hi"] - r["lo"] < 10: F("time window under 10 s", r, (r["lo"], r["hi"]))
            last = r["pours"][-1]
            if last["t"] + (last["dur"] or 10) + 10 > r["lo"]: F("finishes before the last pour can drain", r, (last["t"], last["dur"], r["lo"]))
        if P:
            xs = [p["x"] for p in P]; ts = [p["t"] for p in r["pours"]]
            if xs != sorted(set(xs)): F("pour weights not rising", r, xs)
            if abs(xs[-1] - r["water"]) > 0.01: F("last pour is not the total", r, (xs[-1], r["water"]))
            if any(p["to"] != p["x"] for p in P): F("scale reading differs from the target", r)
            if ts != sorted(set(ts)): F("pour times not rising", r, ts)
            for a, b in zip(r["pours"], r["pours"][1:]):
                if a["dur"] and a["t"] + a["dur"] > b["t"]: F("a pour runs into the next", r, (a["t"], a["dur"], b["t"]))
            adds = [xs[0]] + [b - a for a, b in zip(xs, xs[1:])]
            if r["kind"] == "pour" and min(adds) < 10: F("a pour under 10 g", r, adds)
        if r["iced"] and abs(r["water"] + r["ice"] - r["total"]) > 0.01: F("hot water plus ice is not the total", r)
        w = r["total"] if r["iced"] else r["water"]
        if r["kind"] in ("pour", "imm") and br != "cupping":
            if abs(w - dose * r["ratio"]) > 2.6: F("water is not dose x ratio", r, (w, dose, r["ratio"]))
            if not 12 <= r["ratio"] <= 20: F("ratio outside 1:12-1:20", r, r["ratio"])
            if not r["iced"] and r["yieldG"] is not None and not w - 2.6 * dose <= r["yieldG"] <= w - 1.5 * dose: F("cup yield off", r, (r["yieldG"], w, dose))
        if r["kind"] == "shot":
            if abs(r["water"] - dose * r["ratio"]) > 1: F("shot: out is not in x ratio", r)
            if not 1.3 <= r["ratio"] <= 3.2: F("shot ratio outside 1:1.3-1:3.2", r, r["ratio"])
            if not 20 <= r["lo"] < r["hi"] <= 40: F("shot time outside 20-40 s", r, (r["lo"], r["hi"]))
            if not 86 <= r["temp"] <= 96: F("shot temperature outside 86-96", r, r["temp"])
        if r["tds"] and r["kind"] != "shot" and not 0.9 <= r["tds"][0] <= r["tds"][1] <= 2.0: F("strength outside 0.9-2.0%", r, r["tds"])
        if br in ("v60", "neo") and r["temp"] is not None and r["goal"] != "tea":
            if pr in caps and r["temp"] > caps[pr]: F("hotter than the process allows", r, r["temp"])
            if ro in rcaps and r["temp"] > rcaps[ro]: F("hotter than the roast allows", r, r["temp"])
        if ro in order[:-1]:
            n = idx.get((br, dose, pr, order[order.index(ro) + 1], goal, serve, m))
            if n and n["m"] == r["m"] and n["goal"] == r["goal"]:
                if r["temp"] is not None and n["temp"] is not None and n["temp"] > r["temp"]: F("a darker roast gets hotter water", r, (r["temp"], n["temp"]))
                if n["clicks"] < r["clicks"]: F("a darker roast gets a finer grind", r, (r["clicks"], n["clicks"]))
        if goal == "light" and r["kind"] in ("pour", "imm") and br != "cupping":
            b_, s_ = idx.get((br, dose, pr, ro, "balanced", serve, m)), idx.get((br, dose, pr, ro, "syrupy", serve, m))
            if b_ and s_ and b_["m"] == r["m"] == s_["m"] and not r["ratio"] >= b_["ratio"] >= s_["ratio"]: F("Light, Balanced, Rich not in order of strength", r, (r["ratio"], b_["ratio"], s_["ratio"]))

def words(d):
    for r in d:
        t = r["text"]
        for w in ("undefined", "NaN", "null", "[object", "Infinity"):
            if w in t: F("text shows " + w, r, t[max(0, t.index(w) - 60):t.index(w) + 30])
        m = re.search(r"\.\.(?!\.)|  ,| ,|,,|\s\.(?!\d)", t)
        if m: F("stray punctuation", r, t[max(0, m.start() - 40):m.end() + 20])
        for m in re.finditer(r"(\d+)°C \((\d+) at most\)", t):
            if int(m.group(1)) > int(m.group(2)): F("temperature above the limit it states", r, m.group(0))
        if r["temp"] and str(r["temp"]) not in r["specs"]: F("kettle on screen differs from the recipe", r)
        if r["in"][3] != "unsure" and "Roast not sure" in t: F("says the roast is unknown when it is set", r)
        if re.search(r"\b1 (clicks|pours|notches)\b|\ba (extra|[aeiou]\w+) (grind|coarse)", t): F("grammar", r, re.search(r".{0,30}(\b1 (clicks|pours|notches)\b|\ba (extra|[aeiou]\w+) (grind|coarse)).{0,20}", t).group(0))
        if re.search(r"\b0 clicks? (finer|coarser)|about 0 µm", t): F("a change of nothing", r)
        if r["in"][0] != "moka" and re.search(r"flame|off the heat|tamped", r["dial"]): F("moka pot tips on another brewer", r)
        if r["in"][0] not in ("aero", "press", "espresso") and re.search(r"\bplunger\b|\bpress gently\b", r["dial"], re.I): F("press tips on another brewer", r)

with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); crashes = []
    pg.on("pageerror", lambda e: crashes.append(str(e)))
    pg.goto(URL); pg.wait_for_timeout(1500)
    a = pg.evaluate(NUMBERS); w = {"res": [], "errs": []}
    for br, doses in ON_SCREEN.items():   # a brewer at a time: all the text at once is too much for one page
        for dose in doses:
            part = pg.evaluate(WORDS, {br: [dose]}); w["res"] += part["res"]; w["errs"] += part["errs"]
    b.close()
numbers(a["res"]); words(w["res"])
for key, e in a["errs"] + w["errs"]: bad["recipe crashed"].append((key, e))
for e in crashes: bad["page error"].append(("", e))
print(f"{len(a['res'])} recipes checked by the numbers, {len(w['res'])} on screen")
for k, v in sorted(bad.items(), key=lambda kv: -len(kv[1])):
    print(f"{len(v):6d}  {k}")
    for inp, msg in v[:4]: print("         ", inp, msg)
print("no errors" if not bad else f"{sum(len(v) for v in bad.values())} problems")
sys.exit(1 if bad else 0)

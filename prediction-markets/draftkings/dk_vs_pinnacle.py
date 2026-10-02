"""Snapshot comparison (results_dk_vs_pinnacle.json): DraftKings sportsbook main lines (moneyline/spread/total) with Pinnacle's, matched by team names and start time."""
import os, json, re, glob, collections, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
def amer_to_p(a):
    a=float(a); return 100/(a+100) if a>0 else -a/(-a+100)
def norm(s):
    s=s.lower(); s=re.sub(r"[^a-z ]","",s); return s.split()[-1] if s.split() else s
# Pinnacle: matchups + straight prices
pm = {}
for f in glob.glob(os.path.join(HERE, "data", "pinnacle", "matchups_*.json")):
    for m in json.load(open(f)):
        if m.get("parentId") or m.get("type")!="matchup" and m.get("type") is not None: pass
        parts = m.get("participants") or []
        if len(parts)!=2 or m.get("parent"): continue
        home=[p for p in parts if p.get("alignment")=="home"]; away=[p for p in parts if p.get("alignment")=="away"]
        if not home or not away: continue
        pm[m["id"]] = dict(league=m["league"]["name"], sport=m["league"]["sport"]["name"], home=home[0]["name"], away=away[0]["name"], start=m["startTime"], prices={})
for f in glob.glob(os.path.join(HERE, "data", "pinnacle", "straight_*.json")):
    for r in json.load(open(f)):
        if r["matchupId"] not in pm or r.get("period")!=0 or r.get("isAlternate"): continue
        if r["type"]=="moneyline":
            d={p["designation"]:p["price"] for p in r["prices"] if "designation" in p}
            if "home" in d and "away" in d: pm[r["matchupId"]]["prices"]["ml"]=d
        elif r["type"]=="spread":
            d={p["designation"]:(p["points"],p["price"]) for p in r["prices"] if "designation" in p}
            if "home" in d: pm[r["matchupId"]]["prices"]["spread"]=d
        elif r["type"]=="total":
            d={p["designation"]:(p["points"],p["price"]) for p in r["prices"] if "designation" in p}
            if "over" in d: pm[r["matchupId"]]["prices"]["total"]=d
print("pinnacle matchups with ML:", sum(1 for v in pm.values() if "ml" in v["prices"]))
# DK
rows=[]
for f in glob.glob(os.path.join(HERE, "data", "dk", "league_*.json")):
    d=json.load(open(f)); lg=d["leagues"][0]["name"]
    ev={e["id"]:e for e in d["events"]}
    mk={m["id"]:m for m in d["markets"]}
    sel=collections.defaultdict(list)
    for s_ in d["selections"]: sel[s_["marketId"]].append(s_)
    for mid,m in mk.items():
        e=ev.get(m["eventId"]); 
        if not e or e.get("status")!="NOT_STARTED": continue
        parts={p["venueRole"]:p["name"] for p in e["participants"] if p.get("venueRole")}
        if "Home" not in parts or "Away" not in parts: continue
        name=m["name"]; ss=sel[mid]
        if name=="Moneyline" and len(ss)==2:
            d2={s_["outcomeType"]:s_["trueOdds"] for s_ in ss}
            if "Home" in d2 and "Away" in d2: rows.append(dict(league=lg, home=parts["Home"], away=parts["Away"], start=e["startEventDate"], type="ml", dk=d2))
        elif name=="Spread" and len(ss)==2 and all(s_.get("main") for s_ in ss):
            d2={s_["outcomeType"]:(s_["points"],s_["trueOdds"]) for s_ in ss}
            if "Home" in d2 and "Away" in d2: rows.append(dict(league=lg, home=parts["Home"], away=parts["Away"], start=e["startEventDate"], type="spread", dk=d2))
        elif name=="Total" and len(ss)==2 and all(s_.get("main") for s_ in ss):
            d2={s_["label"].split()[0]:(s_["points"],s_["trueOdds"]) for s_ in ss}
            if "Over" in d2 and "Under" in d2: rows.append(dict(league=lg, home=parts["Home"], away=parts["Away"], start=e["startEventDate"], type="total", dk=d2))
print("dk main-line rows:", len(rows), collections.Counter(r["type"] for r in rows))
# match by (home last word, away last word, same calendar day)
def key(home,away,start): return (norm(home), norm(away), start[:10])
pidx={key(v["home"],v["away"],v["start"]):v for v in pm.values()}
out=[]
for r in rows:
    v=pidx.get(key(r["home"],r["away"],r["start"]))
    if not v: continue
    if r["type"]=="ml" and "ml" in v["prices"]:
        ph,pa=amer_to_p(v["prices"]["ml"]["home"]),amer_to_p(v["prices"]["ml"]["away"]); pin_h=ph/(ph+pa); pin_hold=ph+pa-1
        dh,da=1/r["dk"]["Home"],1/r["dk"]["Away"]; dk_h=dh/(dh+da); dk_hold=dh+da-1
        out.append(dict(league=r["league"], type="ml", home=r["home"], away=r["away"], pin_h=pin_h, dk_h=dk_h, pin_hold=pin_hold, dk_hold=dk_hold, dk_raw_h=dh, dk_raw_a=da, pin_raw_h=ph, pin_raw_a=pa))
    elif r["type"]=="spread" and "spread" in v["prices"]:
        (pts_h,ph),(pts_a,pa)=v["prices"]["spread"]["home"],v["prices"]["spread"]["away"]
        (dpts_h,dh),(dpts_a,da)=r["dk"]["Home"],r["dk"]["Away"]
        out.append(dict(league=r["league"], type="spread", home=r["home"], away=r["away"], pin_line=pts_h, dk_line=dpts_h, pin_hold=amer_to_p(ph)+amer_to_p(pa)-1, dk_hold=1/dh+1/da-1, same_line=pts_h==dpts_h, pin_h=amer_to_p(ph)/(amer_to_p(ph)+amer_to_p(pa)), dk_h=(1/dh)/(1/dh+1/da)))
    elif r["type"]=="total" and "total" in v["prices"]:
        (pts_o,po),(pts_u,pu)=v["prices"]["total"]["over"],v["prices"]["total"]["under"]
        (dpts_o,do),(dpts_u,du)=r["dk"]["Over"],r["dk"]["Under"]
        out.append(dict(league=r["league"], type="total", home=r["home"], away=r["away"], pin_line=pts_o, dk_line=dpts_o, pin_hold=amer_to_p(po)+amer_to_p(pu)-1, dk_hold=1/do+1/du-1, same_line=pts_o==dpts_o, pin_h=amer_to_p(po)/(amer_to_p(po)+amer_to_p(pu)), dk_h=(1/do)/(1/do+1/du)))
json.dump(out, open(os.path.join(HERE, "results_dk_vs_pinnacle.json"), "w"), indent=1)
import statistics as S
for t in ["ml","spread","total"]:
    sub=[o for o in out if o["type"]==t]
    if not sub: continue
    print(f"\n{t}: {len(sub)} matched; DK hold {S.mean(o['dk_hold'] for o in sub)*100:.2f}% vs Pinnacle {S.mean(o['pin_hold'] for o in sub)*100:.2f}%")
    bylg=collections.defaultdict(list)
    for o in sub: bylg[o["league"]].append(o)
    for lg,os_ in sorted(bylg.items(), key=lambda x:-len(x[1])):
        print(f"  {lg:28s} n={len(os_):3d} DK hold {S.mean(o['dk_hold'] for o in os_)*100:5.2f}%  Pin hold {S.mean(o['pin_hold'] for o in os_)*100:5.2f}%  mean|DKprob-Pinprob| {S.mean(abs(o['dk_h']-o['pin_h']) for o in os_)*100:.2f}pp" + (f"  same line {sum(o['same_line'] for o in os_)}/{len(os_)}" if t!="ml" else ""))
if any(o["type"]=="ml" for o in out):
    print("\nML: DK devigged prob minus Pinnacle devigged prob, by Pinnacle favourite strength (home-side and away-side pooled as 'favourite' and 'dog')")
    bins=[(0,0.2),(0.2,0.35),(0.35,0.5),(0.5,0.65),(0.65,0.8),(0.8,1.01)]
    for lo,hi in bins:
        vals=[]; raw=[]
        for o in out:
            if o["type"]!="ml": continue
            for side in ("h","a"):
                p = o["pin_h"] if side=="h" else 1-o["pin_h"]; d = o["dk_h"] if side=="h" else 1-o["dk_h"]
                dr = o["dk_raw_h"] if side=="h" else o["dk_raw_a"]
                if lo<=p<hi: vals.append(d-p); raw.append(dr-p)
        if vals: print(f"  Pinnacle p in [{lo:.2f},{hi:.2f}): n={len(vals):3d}  DK devig − Pin = {S.mean(vals)*100:+.2f}pp   DK raw price − Pin fair = {S.mean(raw)*100:+.2f}pp (what a DK bettor pays above fair)")

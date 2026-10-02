"""Open DKeX NFL moneyline contracts (last trade, this week's games with open interest >= 1000) against DraftKings sportsbook
raw and devigged prices and Pinnacle's devigged price for the same team. Team codes in symbols are learned from settled contracts.
Run dk_vs_pinnacle.py first. Results in results_dkex_vs_books.json."""
import os, json, re, collections, statistics as S, duckdb

HERE = os.path.dirname(os.path.abspath(__file__))


def norm(s): return re.sub(r"[^a-z]", "", s.lower().split()[-1])


def main():
    con = duckdb.connect(os.path.join(HERE, "data", "dkex", "dkex.duckdb"), read_only=True)
    code2name = {}
    for code, name, n in con.execute("SELECT split_part(symbol,'-',5), name, count(*) FROM contracts WHERE league='NFL' AND mtype='WIN' AND settle IS NOT NULL GROUP BY 1,2 ORDER BY 3 DESC").fetchall():
        code2name.setdefault(code, name)
    rows = con.execute("""WITH d AS (SELECT symbol, oi FROM daily WHERE bdate=(SELECT max(bdate) FROM daily) AND status='Open' AND symbol LIKE 'NFL-WIN-FG-%'),
      lt AS (SELECT symbol, arg_max(price, ts) AS last_price, max(ts) AS last_ts FROM trades WHERE symbol LIKE 'NFL-WIN-FG-%' AND bdate >= (SELECT max(bdate) FROM daily) - 3 GROUP BY 1)
      SELECT d.symbol, split_part(d.symbol,'-',4), split_part(d.symbol,'-',5), d.oi, lt.last_price, lt.last_ts FROM d LEFT JOIN lt USING(symbol)""").fetchall()
    ev = collections.defaultdict(list)
    for sym, event, code, oi, lp, lts in rows: ev[event].append((code2name.get(code, code), oi, lp, lts))
    idx = {}
    for o in json.load(open(os.path.join(HERE, "results_dk_vs_pinnacle.json"))):
        if o["type"] == "ml" and o["league"] == "NFL": idx[norm(o["home"])] = o; idx[norm(o["away"])] = o
    out = []
    for event, teams in ev.items():
        if len(teams) != 2 or not all(t[2] for t in teams): continue
        for name, oi, lp, lts in teams:
            o = idx.get(norm(name))
            if not o: continue
            h = norm(o["home"]) == norm(name)
            out.append(dict(event=event, team=name, oi=oi, dkex_last=lp, pair_sum=sum(t[2] for t in teams), dk_raw=o["dk_raw_h"] if h else o["dk_raw_a"], dk_devig=o["dk_h"] if h else 1 - o["dk_h"], pinnacle=o["pin_h"] if h else 1 - o["pin_h"], last_ts=str(lts)))
    live = [o for o in out if o["oi"] >= 1000]
    print(f"{len(out)} matched contracts, {len(live)} with OI >= 1000 (this week's games)")
    for o in sorted(live, key=lambda o: o["pinnacle"]): print(f"  {o['team']:16s} OI {o['oi']:7d}  DKeX {o['dkex_last']:.2f} (pair {o['pair_sum']:.2f})  DK raw {o['dk_raw']:.3f}  DK devig {o['dk_devig']:.3f}  Pinnacle {o['pinnacle']:.3f}")
    R = {"rows": out}
    if live:
        R["summary"] = dict(n=len(live), dkex_minus_pinnacle=S.mean(o['dkex_last'] - o['pinnacle'] for o in live), dkex_minus_dk_raw=S.mean(o['dkex_last'] - o['dk_raw'] for o in live), dk_raw_minus_pinnacle=S.mean(o['dk_raw'] - o['pinnacle'] for o in live), mean_pair_sum=S.mean(o['pair_sum'] for o in live))
        print(f"\nn={len(live)}: DKeX last − Pinnacle {R['summary']['dkex_minus_pinnacle']*100:+.2f}pp; DKeX − DK sportsbook raw {R['summary']['dkex_minus_dk_raw']*100:+.2f}pp; DK raw − Pinnacle {R['summary']['dk_raw_minus_pinnacle']*100:+.2f}pp; mean DKeX pair sum {R['summary']['mean_pair_sum']:.3f}")
        R["by_bucket"] = []
        for lo, hi in [(0, 0.35), (0.35, 0.65), (0.65, 1.01)]:
            v = [o for o in live if lo <= o['pinnacle'] < hi]
            if v:
                R["by_bucket"].append(dict(lo=lo, hi=hi, n=len(v), dkex_minus_pinnacle=S.mean(o['dkex_last'] - o['pinnacle'] for o in v), dk_raw_minus_pinnacle=S.mean(o['dk_raw'] - o['pinnacle'] for o in v)))
                print(f"  Pinnacle p in [{lo},{hi}): n={len(v)} DKeX − Pinnacle {S.mean(o['dkex_last'] - o['pinnacle'] for o in v)*100:+.2f}pp; DK raw − Pinnacle {S.mean(o['dk_raw'] - o['pinnacle'] for o in v)*100:+.2f}pp")
    json.dump(R, open(os.path.join(HERE, "results_dkex_vs_books.json"), "w"), indent=1)


if __name__ == "__main__":
    main()

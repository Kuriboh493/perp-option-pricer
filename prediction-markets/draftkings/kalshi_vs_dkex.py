"""Same season, same games: Kalshi NFL game-winner contracts (hourly candlesticks, volume-weighted at the hour's mean price)
against DKeX NFL moneyline singles (every trade), scored from the YES buyer's side by price bucket and hours before the end.
Run fetch_kalshi_nfl.py first. Results in results_kalshi_vs_dkex.json."""
import os, json, datetime as dt, collections, duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
BUCKETS = [(0, 0.05, '00-05'), (0.05, 0.10, '05-10'), (0.10, 0.20, '10-20'), (0.20, 0.35, '20-35'), (0.35, 0.50, '35-50'), (0.50, 0.65, '50-65'), (0.65, 0.80, '65-80'), (0.80, 0.90, '80-90'), (0.90, 0.95, '90-95'), (0.95, 1.01, '95-99')]


def bucket(p):
    return next(n for lo, hi, n in BUCKETS if lo <= p < hi)


def hb(h):
    return 'a <1h' if h < 1 else 'b 1-3h' if h < 3 else 'c 3-6h' if h < 6 else 'd 6-24h' if h < 24 else 'e 1-7d' if h < 168 else 'f >7d'


def main():
    d = json.load(open(os.path.join(HERE, "data", "kalshi", "nfl_candles.json")))
    agg = collections.defaultdict(lambda: [0, 0, 0]); aggh = collections.defaultdict(lambda: [0, 0, 0]); n = 0
    for tk, v in d.items():
        m = v["market"]; res = m.get("result")
        if res not in ("yes", "no"): continue
        settle = 1.0 if res == "yes" else 0.0
        close = dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")).timestamp()
        for c in v["candles"]:
            vol = float(c.get("volume_fp") or 0)
            p = float((c.get("price") or {}).get("mean_dollars") or 0)
            if vol <= 0 or not (0 < p < 1): continue
            n += 1; h = (close - c["end_period_ts"]) / 3600.0
            a = agg[bucket(p)]; a[0] += vol; a[1] += p * vol; a[2] += settle * vol
            b = aggh[hb(h)]; b[0] += vol; b[1] += p * vol; b[2] += settle * vol
    print("kalshi NFL candle-hours with volume:", n, "contracts:", round(sum(a[0] for a in agg.values())), "markets:", sum(1 for v in d.values() if v['market'].get('result') in ('yes', 'no')))
    con = duckdb.connect(os.path.join(HERE, "data", "dkex", "dkex.duckdb"), read_only=True)
    bk = " ".join(f"WHEN price<{hi} THEN '{name}'" for lo, hi, name in BUCKETS)
    dk = con.execute(f"""SELECT CASE {bk} END AS b, sum(qty), sum(price*qty), sum(settle*qty) FROM trades t JOIN contracts c USING(symbol)
      WHERE c.league='NFL' AND c.mtype='WIN' AND c.period='FG' AND c.settle IS NOT NULL AND t.bdate>=20260801 GROUP BY 1 ORDER BY 1""").fetchall()
    dkh = con.execute("""WITH t2 AS (SELECT t.price, t.qty, c.settle, date_diff('second', t.ts, c.settle_ts)/3600.0 AS h FROM trades t JOIN contracts c USING(symbol)
      WHERE c.league='NFL' AND c.mtype='WIN' AND c.period='FG' AND c.settle IS NOT NULL AND t.bdate>=20260801)
      SELECT CASE WHEN h<1 THEN 'a <1h' WHEN h<3 THEN 'b 1-3h' WHEN h<6 THEN 'c 3-6h' WHEN h<24 THEN 'd 6-24h' WHEN h<168 THEN 'e 1-7d' ELSE 'f >7d' END, sum(qty), sum(price*qty), sum(settle*qty) FROM t2 WHERE h>=0 GROUP BY 1 ORDER BY 1""").fetchall()
    R = {}
    print("\n## NFL moneylines, YES-buyer return by price bucket: Kalshi (candles, before the 7% taker fee) vs DKeX (trades)")
    hdr = ["bucket", "kalshi_contracts", "kalshi_price", "kalshi_hit", "kalshi_yes_return_pct", "kalshi_after_taker_fee_pct", "dkex_contracts", "dkex_price", "dkex_hit", "dkex_yes_return_pct"]
    print(" | ".join(hdr)); tab = [hdr]
    for b, (kv, kp, ks) in sorted(agg.items()):
        dkrow = next((r for r in dk if r[0] == b), None)
        kprice = kp / kv; fee = 0.07 * kprice * (1 - kprice)
        line = [b, int(kv), round(kprice, 3), round(ks / kv, 3), round(100 * (ks - kp) / kp, 1), round(100 * (ks - kp - fee * kv) / kp, 1)]
        if dkrow: line += [int(dkrow[1]), round(dkrow[2] / dkrow[1], 3), round(dkrow[3] / dkrow[1], 3), round(100 * (dkrow[3] - dkrow[2]) / dkrow[2], 1)]
        print(" | ".join(str(x) for x in line)); tab.append(line)
    R["by price"] = tab
    print("\n## NFL moneylines, YES-buyer return by hours before close (Kalshi) / settlement (DKeX)")
    hdr = ["hours", "kalshi_contracts", "kalshi_yes_return_pct", "dkex_contracts", "dkex_yes_return_pct"]; print(" | ".join(hdr)); tab = [hdr]
    for b, (kv, kp, ks) in sorted(aggh.items()):
        dkrow = next((r for r in dkh if r[0] == b), None)
        line = [b, int(kv), round(100 * (ks - kp) / kp, 1)] + ([int(dkrow[1]), round(100 * (dkrow[3] - dkrow[2]) / dkrow[2], 1)] if dkrow else [])
        print(" | ".join(str(x) for x in line)); tab.append(line)
    R["by hours"] = tab
    kp, ks, kv = sum(a[1] for a in agg.values()), sum(a[2] for a in agg.values()), sum(a[0] for a in agg.values())
    dp, ds, dv = sum(r[2] for r in dk), sum(r[3] for r in dk), sum(r[1] for r in dk)
    R["overall"] = {"kalshi_yes_return_pct": 100 * (ks - kp) / kp, "kalshi_contracts": kv, "dkex_yes_return_pct": 100 * (ds - dp) / dp, "dkex_contracts": dv}
    print(f"\nKalshi NFL overall yes-return {100*(ks-kp)/kp:.2f}% on {kv:,.0f} contracts; DKeX NFL moneyline overall {100*(ds-dp)/dp:.2f}% on {dv:,} contracts")
    json.dump(R, open(os.path.join(HERE, "results_kalshi_vs_dkex.json"), "w"), indent=1)


if __name__ == "__main__":
    main()

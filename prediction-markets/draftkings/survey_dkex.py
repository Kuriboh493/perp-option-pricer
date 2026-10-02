"""Survey of DKeX (DraftKings Predictions) trades, June 11 - Oct 1 2026, scored from the YES buyer's side at the traded price.
The public time & sales has no aggressor flag, so for single contracts this measures contract-level mispricing at each price;
for combos the YES buyer is effectively always the taker (the other side is DraftKings' in-house desk or an external maker).
Time to event uses the settlement timestamp: every contract 'settles early' relative to a placeholder maturity date,
minutes after the event ends, so 'hours to settlement' is hours to the end of the game (a game lasts about three hours).
Results go to results_survey.json."""
import os, json, math, datetime as dt, statistics as S, duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "dkex", "dkex.duckdb")
BUCKET = """CASE WHEN price<0.05 THEN '00-05' WHEN price<0.10 THEN '05-10' WHEN price<0.20 THEN '10-20' WHEN price<0.35 THEN '20-35' WHEN price<0.50 THEN '35-50'
 WHEN price<0.65 THEN '50-65' WHEN price<0.80 THEN '65-80' WHEN price<0.90 THEN '80-90' WHEN price<0.95 THEN '90-95' ELSE '95-99' END"""
TTM = """CASE WHEN h<1 THEN 'a <1h' WHEN h<3 THEN 'b 1-3h' WHEN h<6 THEN 'c 3-6h' WHEN h<24 THEN 'd 6-24h' WHEN h<168 THEN 'e 1-7d' ELSE 'f >7d' END"""
R = {}


def main():
    con = duckdb.connect(DB, read_only=True)
    con.execute("PRAGMA threads=8")

    def show(title, sql):
        rows = con.execute(sql).fetchall(); hdr = [d[0] for d in con.execute(sql).description]
        R[title] = [hdr] + [list(r) for r in rows]
        print(f"\n## {title}"); print(" | ".join(hdr))
        for r in rows: print(" | ".join(f"{v:.4g}" if isinstance(v, float) else str(v) for v in r))

    con.execute("""CREATE TEMP VIEW t AS
SELECT tr.bdate, tr.symbol, tr.ts, tr.price, tr.qty, c.settle, c.name, c.league, c.mtype, c.period, c.legs, c.settle_ts,
       tr.symbol LIKE 'COMBO-%' AS combo, (c.settle - tr.price) * tr.qty AS yes_pnl, tr.price * tr.qty AS yes_stake, (1 - tr.price) * tr.qty AS no_stake,
       date_diff('second', tr.ts, c.settle_ts) / 3600.0 AS h
FROM trades tr LEFT JOIN contracts c USING (symbol)""")
    show("Overview", """SELECT combo, count(*) AS trades, sum(qty) AS contracts, round(sum(yes_stake)/1e6,2) AS yes_notional_musd, count(settle) AS settled_trades,
  round(sum(yes_pnl)/1e6,3) AS yes_pnl_musd, round(100*sum(yes_pnl)/sum(CASE WHEN settle IS NOT NULL THEN yes_stake END),2) AS yes_return_pct FROM t GROUP BY combo ORDER BY combo""")
    show("By month", """SELECT bdate//100 AS month, combo, count(*) AS trades, sum(qty) AS contracts, round(sum(yes_stake)/1e6,2) AS yes_notional_musd,
  round(100*sum(yes_pnl)/sum(CASE WHEN settle IS NOT NULL THEN yes_stake END),2) AS yes_return_pct, round(100.0*count(settle)/count(*),1) AS pct_settled FROM t GROUP BY 1,2 ORDER BY 1,2""")
    show("By league (settled)", """SELECT league, count(*) AS trades, sum(qty) AS contracts, round(sum(yes_stake)/1e6,2) AS yes_notional_musd,
  round(100*sum(yes_pnl)/sum(yes_stake),2) AS yes_return_pct, round(-100*sum(yes_pnl)/sum(qty),2) AS yes_seller_cents_per_contract
  FROM t WHERE settle IS NOT NULL GROUP BY 1 ORDER BY contracts DESC LIMIT 20""")
    show("Singles by market type (settled)", """SELECT mtype, count(*) AS trades, sum(qty) AS contracts, round(sum(yes_stake)/1e6,2) AS yes_notional_musd,
  round(sum(price*qty)/sum(qty),3) AS price_qty_wtd, round(sum(settle*qty)/sum(qty),3) AS hit_rate_qty_wtd,
  round(100*sum(yes_pnl)/sum(yes_stake),2) AS yes_return_pct, round(-100*sum(yes_pnl)/sum(no_stake),2) AS no_return_pct
  FROM t WHERE settle IS NOT NULL AND NOT combo GROUP BY 1 ORDER BY contracts DESC LIMIT 25""")
    for what, where in [("Singles", "NOT combo"), ("Combos", "combo")]:
        show(f"{what} by price bucket (settled, qty-weighted)", f"""SELECT {BUCKET} AS bucket, count(*) AS trades, sum(qty) AS contracts, round(sum(yes_stake)/1e6,2) AS yes_notional_musd,
  round(sum(price*qty)/sum(qty),4) AS price, round(sum(settle*qty)/sum(qty),4) AS hit_rate, round(100*sum(yes_pnl)/sum(yes_stake),2) AS yes_return_pct,
  round(-100*sum(yes_pnl)/sum(no_stake),2) AS no_return_pct, round(-100*sum(yes_pnl)/sum(qty),2) AS yes_seller_cents
  FROM t WHERE settle IS NOT NULL AND {where} GROUP BY 1 ORDER BY 1""")
    show("Combos by leg count (settled)", """SELECT legs, count(*) AS trades, sum(qty) AS contracts, round(sum(yes_stake)/1e6,2) AS yes_notional_musd,
  round(sum(price*qty)/sum(qty),4) AS price, round(sum(settle*qty)/sum(qty),4) AS hit_rate, round(100*sum(yes_pnl)/sum(yes_stake),2) AS yes_return_pct,
  round(-100*sum(yes_pnl)/sum(qty),2) AS yes_seller_cents FROM t WHERE settle IS NOT NULL AND combo GROUP BY 1 ORDER BY 1""")
    show("Combos by month x leg count", """SELECT bdate//100 AS month, legs, sum(qty) AS contracts, round(sum(yes_stake)/1e6,2) AS yes_notional_musd,
  round(100*sum(yes_pnl)/sum(yes_stake),2) AS yes_return_pct FROM t WHERE settle IS NOT NULL AND combo GROUP BY 1,2 ORDER BY 1,2""")

    def bybucket(where, title):
        show(title, f"""SELECT {TTM} AS hours_to_settlement, sum(qty) AS contracts, round(sum(yes_stake)/1e6,2) AS yes_notional_musd,
  round(100*sum(CASE WHEN price<0.05 THEN yes_pnl END)/sum(CASE WHEN price<0.05 THEN yes_stake END),1) AS r_00_05,
  round(100*sum(CASE WHEN price>=0.05 AND price<0.10 THEN yes_pnl END)/sum(CASE WHEN price>=0.05 AND price<0.10 THEN yes_stake END),1) AS r_05_10,
  round(100*sum(CASE WHEN price>=0.10 AND price<0.20 THEN yes_pnl END)/sum(CASE WHEN price>=0.10 AND price<0.20 THEN yes_stake END),1) AS r_10_20,
  round(100*sum(CASE WHEN price>=0.20 AND price<0.35 THEN yes_pnl END)/sum(CASE WHEN price>=0.20 AND price<0.35 THEN yes_stake END),1) AS r_20_35,
  round(100*sum(CASE WHEN price>=0.35 AND price<0.65 THEN yes_pnl END)/sum(CASE WHEN price>=0.35 AND price<0.65 THEN yes_stake END),1) AS r_35_65,
  round(100*sum(CASE WHEN price>=0.65 AND price<0.90 THEN yes_pnl END)/sum(CASE WHEN price>=0.65 AND price<0.90 THEN yes_stake END),1) AS r_65_90,
  round(100*sum(CASE WHEN price>=0.90 THEN yes_pnl END)/sum(CASE WHEN price>=0.90 THEN yes_stake END),1) AS r_90_99,
  round(100*sum(yes_pnl)/sum(yes_stake),1) AS r_all, round(-100*sum(yes_pnl)/sum(qty),2) AS seller_cents
  FROM t WHERE settle IS NOT NULL AND settle_ts IS NOT NULL AND h >= 0 AND {where} GROUP BY 1 ORDER BY 1""")
    bybucket("NOT combo", "Singles: hours to settlement x price bucket (yes return %)")
    bybucket("NOT combo AND league='NFL'", "NFL singles: hours to settlement x price bucket")
    bybucket("NOT combo AND league='MLB'", "MLB singles: hours to settlement x price bucket")
    bybucket("NOT combo AND league='CFB'", "CFB singles: hours to settlement x price bucket")
    bybucket("NOT combo AND mtype='WIN'", "Moneyline (WIN) singles: hours to settlement x price bucket")
    bybucket("NOT combo AND mtype IN ('MOVY','TPTS','TRUNS','TGLS','TMPTS')", "Spread/total singles: hours to settlement x price bucket")
    bybucket("NOT combo AND mtype NOT IN ('WIN','MOVY','TPTS','TRUNS','TGLS','TMPTS','DWIN')", "Player-prop singles: hours to settlement x price bucket")
    bybucket("combo", "Combos: hours to settlement x price bucket")
    show("Combos: legs x hours to settlement (yes return %)", """SELECT legs,
  round(100*sum(CASE WHEN h<3 THEN yes_pnl END)/sum(CASE WHEN h<3 THEN yes_stake END),1) AS r_lt3h,
  round(100*sum(CASE WHEN h>=3 AND h<24 THEN yes_pnl END)/sum(CASE WHEN h>=3 AND h<24 THEN yes_stake END),1) AS r_3_24h,
  round(100*sum(CASE WHEN h>=24 THEN yes_pnl END)/sum(CASE WHEN h>=24 THEN yes_stake END),1) AS r_gt24h,
  round(sum(CASE WHEN h<3 THEN yes_stake END)/1e6,2) AS stake_lt3h, round(sum(CASE WHEN h>=3 AND h<24 THEN yes_stake END)/1e6,2) AS stake_3_24h, round(sum(CASE WHEN h>=24 THEN yes_stake END)/1e6,2) AS stake_gt24h
  FROM t WHERE settle IS NOT NULL AND combo AND h >= 0 GROUP BY 1 ORDER BY 1""")
    show("Combos: all-Yes vs contains No legs", """SELECT name LIKE '%No - %' AS has_no_leg, legs, sum(qty) AS contracts, round(sum(yes_stake)/1e6,2) AS stake_musd,
  round(sum(price*qty)/sum(qty),4) AS price, round(sum(settle*qty)/sum(qty),4) AS hit, round(100*sum(yes_pnl)/sum(yes_stake),1) AS r FROM t WHERE settle IS NOT NULL AND combo GROUP BY 1,2 ORDER BY 2,1""")
    show("Combos: leg composition (yes return %)", """SELECT
  CASE WHEN name NOT LIKE '%TD Scorer%' AND name NOT LIKE '%Yards%' AND name NOT LIKE '%Receptions%' AND name NOT LIKE '%Touchdowns%' AND name NOT LIKE '%Hits%' AND name NOT LIKE '%Strikeouts%' AND name NOT LIKE '%Points Made%' AND name NOT LIKE '%Rebounds%' AND name NOT LIKE '%Assists%' AND name NOT LIKE '%Three%' AND name NOT LIKE '%Home Run%' AND name NOT LIKE '%RBI%' AND name NOT LIKE '%2+ TDs%' THEN 'game markets only (ML/spread/total)'
       WHEN name LIKE '%TD Scorer%' OR name LIKE '%2+ TDs%' THEN 'includes TD scorer leg' ELSE 'includes other player prop leg' END AS mix,
  legs, sum(qty) AS contracts, round(sum(yes_stake)/1e6,2) AS stake_musd, round(sum(price*qty)/sum(qty),4) AS price, round(sum(settle*qty)/sum(qty),4) AS hit, round(100*sum(yes_pnl)/sum(yes_stake),1) AS r
  FROM t WHERE settle IS NOT NULL AND combo GROUP BY 1,2 ORDER BY 1,2""")
    # weekly maker P&L series for candidate pools
    for name, where in [("combos", "combo"), ("combos 2-3 legs", "combo AND legs<=3"), ("combos 6+ legs", "combo AND legs>=6"),
                        ("singles <10c", "NOT combo AND price<0.10"), ("singles <10c, >24h before settlement", "NOT combo AND price<0.10 AND h>=24"),
                        ("singles <10c, <3h before settlement", "NOT combo AND price<0.10 AND h<3 AND h>=0"), ("singles 10-20c", "NOT combo AND price>=0.10 AND price<0.20"),
                        ("singles 20-50c", "NOT combo AND price>=0.20 AND price<0.50"), ("singles 50-80c", "NOT combo AND price>=0.50 AND price<0.80"),
                        ("singles >=80c", "NOT combo AND price>=0.80"), ("singles, 3-24h before settlement", "NOT combo AND h>=3 AND h<24"),
                        ("singles, <1h before settlement (in-play)", "NOT combo AND h<1 AND h>=0"),
                        ("NFL singles", "NOT combo AND league='NFL'"), ("MLB singles", "NOT combo AND league='MLB'"), ("CFB singles", "NOT combo AND league='CFB'")]:
        rows = con.execute(f"SELECT bdate, -sum(yes_pnl), sum(yes_stake), sum(qty) FROM t WHERE settle IS NOT NULL AND {where} GROUP BY 1 ORDER BY 1").fetchall()
        wk = {}
        for b, pnl, stake, qty in rows:
            d = dt.date(b // 10000, b // 100 % 100, b % 100); k = d.isocalendar()[:2]
            w = wk.setdefault(k, [0, 0, 0]); w[0] += pnl; w[1] += stake; w[2] += qty
        ws = [v[0] for v in wk.values()]
        if len(ws) < 3: continue
        tstat = S.mean(ws) / (S.stdev(ws) / math.sqrt(len(ws)))
        R[f"weekly {name}"] = {"weeks": {f"{k[0]}-W{k[1]:02d}": v for k, v in wk.items()}, "total": sum(ws), "stake": sum(v[1] for v in wk.values()), "contracts": sum(v[2] for v in wk.values()),
                               "weeks_positive": sum(w > 0 for w in ws), "t": tstat, "worst": min(ws), "best": max(ws)}
        print(f"\n## Weekly maker P&L, {name}: {len(ws)} weeks, total ${sum(ws)/1e3:,.0f}k on ${sum(v[1] for v in wk.values())/1e3:,.0f}k yes-stake ({sum(v[2] for v in wk.values())/1e6:.1f}M contracts); "
              f"weeks positive {sum(w > 0 for w in ws)}/{len(ws)}; weekly t = {tstat:.2f}; worst week ${min(ws)/1e3:,.0f}k; best ${max(ws)/1e3:,.0f}k; maker ¢/contract {100*sum(ws)/sum(v[2] for v in wk.values()):.2f}")
    json.dump(R, open(os.path.join(HERE, "results_survey.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()

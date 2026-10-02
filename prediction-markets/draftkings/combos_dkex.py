"""Decompose DKeX combo prices (results_combos.json) for NFL/CFB combos made only of 'Yes' moneyline legs.
Each leg is mapped, per trade, to the team's next WIN contract to settle after the trade; the leg price is the last single
trade at or before the combo trade. Independent games => the product of fair leg prices is the fair combo price."""
import os, duckdb, json
HERE = os.path.dirname(os.path.abspath(__file__))
con = duckdb.connect(os.path.join(HERE, "data", "dkex", "dkex.duckdb"), read_only=True); con.execute("PRAGMA threads=8")
con.execute("""CREATE TEMP TABLE c AS
SELECT symbol, name, settle, settle_ts, legs
FROM contracts WHERE symbol LIKE 'COMBO-%' AND settle IS NOT NULL AND name IS NOT NULL
  AND regexp_full_match(name, '(Yes - [^/]+ - Moneyline)( / Yes - [^/]+ - Moneyline)*')""")
con.execute("""CREATE TEMP TABLE w AS SELECT symbol, name AS team, league, settle, settle_ts
FROM contracts WHERE mtype='WIN' AND period='FG' AND league IN ('NFL','CFB') AND settle IS NOT NULL""")
con.execute("""CREATE TEMP TABLE legs AS
SELECT c.symbol AS combo, c.legs, c.settle AS combo_settle, u.i, regexp_extract(u.leg, 'Yes - (.+) - Moneyline', 1) AS team
FROM c, LATERAL (SELECT unnest(string_split(c.name, ' / ')) AS leg, generate_subscripts(string_split(c.name, ' / '), 1) AS i) u""")
con.execute("""CREATE TEMP TABLE ct AS SELECT t.symbol AS combo, t.ts, t.price, t.qty, c.legs, c.settle AS combo_settle FROM trades t JOIN c ON c.symbol = t.symbol""")
# per trade and leg: the team's next WIN contract to settle after the trade (its next game)
con.execute("""CREATE TEMP TABLE lm AS
SELECT ct.combo, ct.ts, l.i, l.team, w.symbol AS leg_symbol, w.settle AS leg_settle, w.settle_ts AS leg_settle_ts
FROM ct JOIN legs l ON l.combo = ct.combo JOIN w ON w.team = l.team AND w.settle_ts > ct.ts AND w.settle_ts < ct.ts + INTERVAL 10 DAY
QUALIFY row_number() OVER (PARTITION BY ct.combo, ct.ts, l.i ORDER BY w.settle_ts) = 1""")
con.execute("""CREATE TEMP TABLE lt AS SELECT symbol AS leg_symbol, ts, price FROM trades WHERE symbol IN (SELECT DISTINCT leg_symbol FROM lm)""")
con.execute("""CREATE TEMP TABLE joined AS
SELECT lm.combo, lm.ts, lm.i, lm.leg_symbol, lm.leg_settle, lt.price AS leg_price, lt.ts AS leg_ts
FROM lm ASOF JOIN lt ON lt.leg_symbol = lm.leg_symbol AND lt.ts <= lm.ts""")
con.execute("""CREATE TEMP TABLE per AS
SELECT ct.combo, ct.ts, ct.price, ct.qty, ct.legs, ct.combo_settle, count(j.i) AS n, exp(sum(ln(j.leg_price))) AS fair,
       max(date_diff('second', j.leg_ts, ct.ts))/3600.0 AS max_stale_h, count(DISTINCT j.leg_symbol) AS distinct_legs
FROM ct JOIN joined j ON j.combo = ct.combo AND j.ts = ct.ts GROUP BY 1,2,3,4,5,6 HAVING count(j.i) = ct.legs AND count(DISTINCT j.leg_symbol) = ct.legs""")
print("all-ML yes-only combo trades:", con.execute("select count(*), sum(qty) from ct").fetchall(), "fully priced:", con.execute("select count(*), sum(qty) from per").fetchall())
def show(title, sql):
    rows=con.execute(sql).fetchall(); hdr=[d[0] for d in con.execute(sql).description]
    print(f"\n## {title}"); print(" | ".join(hdr))
    for r in rows: print(" | ".join(f"{v:.4g}" if isinstance(v,float) else str(v) for v in r))
    return [hdr]+[list(r) for r in rows]
R={}
R["by legs"]=show("All-moneyline NFL/CFB combos: combo price vs product of contemporaneous leg prices (qty-weighted, legs traded within 6h)", """
SELECT legs, count(*) AS trades, sum(qty) AS contracts, round(sum(price*qty)/sum(qty),4) AS combo_price, round(sum(fair*qty)/sum(qty),4) AS product_of_legs,
  round(sum(price*qty)/sum(fair*qty),3) AS markup_ratio, round(100*(pow(sum(price*qty)/sum(fair*qty), 1.0/legs)-1),2) AS per_leg_markup_pct,
  round(100*(sum(price*qty)-sum(fair*qty))/sum(price*qty),1) AS markup_pct_of_price,
  round(sum(combo_settle*qty)/sum(qty),4) AS realized_hit, round(100*(sum(combo_settle*qty)-sum(price*qty))/sum(price*qty),1) AS realized_return_pct,
  round(100*(sum(combo_settle*qty)-sum(fair*qty))/sum(fair*qty),1) AS legs_only_return_pct
FROM per WHERE max_stale_h < 6 GROUP BY 1 ORDER BY 1""")
R["by price"]=show("Same, by combo price bucket", """
SELECT CASE WHEN price<0.05 THEN '00-05' WHEN price<0.10 THEN '05-10' WHEN price<0.20 THEN '10-20' WHEN price<0.35 THEN '20-35' WHEN price<0.50 THEN '35-50' ELSE '50+' END AS bucket,
  count(*) AS trades, sum(qty) AS contracts, round(sum(price*qty)/sum(qty),4) AS combo_price, round(sum(fair*qty)/sum(qty),4) AS product_of_legs, round(sum(price*qty)/sum(fair*qty),3) AS markup_ratio,
  round(sum(combo_settle*qty)/sum(qty),4) AS realized_hit, round(100*(sum(combo_settle*qty)-sum(price*qty))/sum(price*qty),1) AS realized_return_pct
FROM per WHERE max_stale_h < 6 GROUP BY 1 ORDER BY 1""")
R["by legs x fav"]=show("Markup by legs and whether the legs are mostly favourites (product of legs >= 0.5^legs)", """
SELECT legs, fair >= pow(0.5, legs) AS mostly_favourites, count(*) AS trades, sum(qty) AS contracts, round(sum(price*qty)/sum(fair*qty),3) AS markup_ratio, round(sum(fair*qty)/sum(qty),4) AS product_of_legs, round(sum(combo_settle*qty)/sum(qty),4) AS realized_hit
FROM per WHERE max_stale_h < 6 GROUP BY 1,2 ORDER BY 1,2""")
R["distribution"]=show("Distribution of per-trade markup ratio (price / product of legs)", """
SELECT legs, round(quantile_cont(price/fair, 0.1),3) AS p10, round(quantile_cont(price/fair, 0.25),3) AS p25, round(quantile_cont(price/fair, 0.5),3) AS p50, round(quantile_cont(price/fair, 0.75),3) AS p75, round(quantile_cont(price/fair, 0.9),3) AS p90,
  round(100.0*sum(CASE WHEN price < fair THEN 1 ELSE 0 END)/count(*),1) AS pct_trades_below_product
FROM per WHERE max_stale_h < 6 GROUP BY 1 ORDER BY 1""")
R["by week"]=show("Markup and realized return by ISO week (all legs)", """
SELECT yearweek(ts) AS week, count(*) AS trades, sum(qty) AS contracts, round(sum(price*qty)/sum(fair*qty),3) AS markup_ratio, round(100*(sum(combo_settle*qty)-sum(price*qty))/sum(price*qty),1) AS realized_return_pct, round(100*(sum(combo_settle*qty)-sum(fair*qty))/sum(fair*qty),1) AS legs_only_return_pct
FROM per WHERE max_stale_h < 6 GROUP BY 1 ORDER BY 1""")
json.dump(R, open(os.path.join(HERE, "results_combos.json"), "w"), indent=1, default=str)

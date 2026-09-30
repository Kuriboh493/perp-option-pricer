"""Summarise the paper-trading recorder: universe, capacity (longshot buying per day), fill rates and time to fill,
adverse selection after fills, and realised P&L on resolved positions."""
import json, os, sqlite3, datetime as dt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect(os.path.join(HERE, "data", "recorder.db"))
q = lambda s, *a: con.execute(s, a).fetchall()
now = int(dt.datetime.now(dt.timezone.utc).timestamp())
first = q("SELECT MIN(ts) FROM snapshots")[0][0] or now
t0, t1 = q("SELECT MIN(ts), MAX(ts) FROM trades")[0]
hours = max(((t1 or now) - (t0 or now)) / 3600, 1.0)          # rates use the span of observed trades, floored at one hour
out = dict(running_hours=round((now - first) / 3600, 1), trade_span_hours=round(hours, 1))
out["universe_latest"] = {f"{p}/{c}": n for p, c, n in q("SELECT platform, category, COUNT(*) FROM universe WHERE ts=(SELECT MAX(ts) FROM universe) GROUP BY 1,2")}
cap = q("SELECT platform, SUM(size*price), SUM(size), COUNT(*) FROM trades WHERE taker_buys_longshot=1 AND price<=0.20 GROUP BY 1")
out["longshot_buying_observed"] = {p: dict(dollars_per_day=round(d / hours * 24), contracts_per_day=round(c / hours * 24), trades=n) for p, d, c, n in cap}
out["markets_with_longshot_buys"] = {p: n for p, n in q("SELECT platform, COUNT(DISTINCT market) FROM trades WHERE taker_buys_longshot=1 AND price<=0.20 GROUP BY 1")}
depth = q("SELECT platform, AVG(ask_size), AVG(ask_depth_to_20c), AVG(best_ask-best_bid) FROM snapshots WHERE ts=(SELECT MAX(ts) FROM snapshots) GROUP BY 1")
out["book_latest"] = {p: dict(avg_ask_size_at_touch=round(a), avg_ask_depth_to_20c=round(d), avg_spread_cents=round(100 * s, 1)) for p, a, d, s in depth}
fills = {}
for p, k, placed, filled, ttf in q("SELECT platform, kind, COUNT(*), SUM(status='filled'), AVG(CASE WHEN status='filled' THEN filled_ts-placed_ts END) FROM orders GROUP BY 1,2"):
    fills[f"{p}/{k}"] = dict(placed=placed, filled=filled, fill_rate=round(filled / placed, 3) if placed else None, avg_hours_to_fill=round(ttf / 3600, 1) if ttf else None)
out["paper_orders"] = fills
partial = q("SELECT platform, COUNT(*), AVG(size-remaining) FROM orders WHERE status='live' AND remaining<size GROUP BY 1")
out["partially_filled_live_orders"] = {p: dict(n=n, avg_filled=round(f, 1)) for p, n, f in partial}
adv = []
for pid, plat, mkt, price, ts in q("SELECT id, platform, market, price, opened_ts FROM positions"):
    later = q("SELECT (best_bid+best_ask)/2 FROM snapshots WHERE platform=? AND market=? AND ts>=? ORDER BY ts LIMIT 1", plat, mkt, ts + 3600)
    if later:
        adv.append(later[0][0] - price)
out["adverse_selection_mid_move_1h_after_fill_cents"] = dict(n=len(adv), mean=round(100 * float(np.mean(adv)), 2) if adv else None, share_up=round(float(np.mean([a > 0 for a in adv])), 2) if adv else None)
pos = q("SELECT platform, COUNT(*), SUM(size*price), SUM(CASE WHEN result IS NOT NULL THEN 1 ELSE 0 END), SUM(pnl), SUM(CASE WHEN result=side THEN 1 ELSE 0 END) FROM positions GROUP BY 1")
out["positions"] = {p: dict(opened=n, premium_collected_usd=round(prem or 0), resolved=r or 0, realised_pnl_usd=round(pnl or 0), longshots_that_hit=h or 0) for p, n, prem, r, pnl, h in pos}
out["top_markets_by_longshot_buying"] = [dict(platform=p, market=m, dollars=round(d), trades=n) for p, m, d, n in q("SELECT platform, market, SUM(size*price), COUNT(*) FROM trades WHERE taker_buys_longshot=1 AND price<=0.20 GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10")]
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(HERE, "results_recorder.json"), "w"), indent=1)

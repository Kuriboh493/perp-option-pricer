"""Summarise the paper-trading recorder: universe, capacity (longshot buying per day), fill rates and time to fill,
adverse selection after fills, realised P&L on resolved positions, and the BTC daily favourites strategy."""
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
# ---- strategy 2: BTC daily favourites (backtest, 2026 out of sample: 2.7c/contract taker, 4.65c join, ~76% join fill rate)
has_strategy = any(r[1] == "strategy" for r in q("PRAGMA table_info(orders)"))
if has_strategy:
    ev = q("SELECT COUNT(*), SUM(markets) FROM btc_events")[0]
    j = q("SELECT COUNT(*), SUM(status='filled'), SUM(status='expired'), SUM(status='live') FROM orders WHERE strategy='btc_fav'")[0]
    btc = dict(events_traded=ev[0] or 0, strikes_signalled=ev[1] or 0,
               join_orders=dict(placed=j[0] or 0, filled=j[1] or 0, expired=j[2] or 0, live=j[3] or 0,
                                fill_rate=round((j[1] or 0) / ((j[1] or 0) + (j[2] or 0)), 3) if (j[1] or 0) + (j[2] or 0) else None))
    for kind in ("taker", "join"):
        r = q("SELECT COUNT(*), SUM(result IS NOT NULL), SUM(pnl), SUM(CASE WHEN result IS NOT NULL THEN size END), SUM(result=side), AVG(price) FROM positions WHERE strategy='btc_fav' AND kind=?", kind)[0]
        btc[kind] = dict(positions=r[0] or 0, resolved=r[1] or 0, realised_pnl_usd=round(r[2] or 0, 2),
                         cents_per_contract=round(100 * (r[2] or 0) / r[3], 2) if r[3] else None,
                         win_rate=round((r[4] or 0) / r[1], 3) if r[1] else None, avg_price=round(r[5], 3) if r[5] else None)
    daily = q("SELECT date(opened_ts, 'unixepoch'), kind, SUM(pnl) FROM positions WHERE strategy='btc_fav' AND result IS NOT NULL GROUP BY 1, 2 ORDER BY 1")
    btc["daily_pnl_usd"] = [dict(day=d, kind=k, pnl=round(v, 2)) for d, k, v in daily]
    btc["backtest_reference"] = dict(taker_cents=2.7, join_cents=4.65, win_rate=0.97)
    out["btc_favourites"] = btc
    out["positions"] = {p: dict(opened=n, premium_collected_usd=round(prem or 0), resolved=r or 0, realised_pnl_usd=round(pnl or 0), longshots_that_hit=h or 0)
                        for p, n, prem, r, pnl, h in q("SELECT platform, COUNT(*), SUM(size*price), SUM(CASE WHEN result IS NOT NULL THEN 1 ELSE 0 END), SUM(pnl), SUM(CASE WHEN result=side THEN 1 ELSE 0 END) FROM positions WHERE strategy='longshot' GROUP BY 1")}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(HERE, "results_recorder.json"), "w"), indent=1)

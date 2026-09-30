"""Stress test of the favourite-longshot rule executed with resting orders (Burgi, Deng & Whelan: makers earn more than takers).
Rule: h hours before Kalshi's 5pm ET BTC close, on any contract with mid beyond (1-x)/x, rest an order on the favourite side at the
current best quote ('join') or one cent inside it ('improve'); a fill needs a trade printed at or through that price in the next hour.
Rule picked on 2025; everything below is Jan-Sep 2026. No maker fee (KXBTCD is a plain 'quadratic' fee series)."""
import collections, json, os
import numpy as np
import kalshi_v2 as V
import kalshi_edge as K

HERE = os.path.dirname(os.path.abspath(__file__))


def fav_pnl(r, x, mode):
    if r["mid"] >= 1 - x:
        return V.pnl(r, 1.0, 0.0, mode, 0.0)
    if r["mid"] <= x:
        return V.pnl(r, 0.0, 0.0, mode, 0.0)
    return None


def summary(rows, h, x, mode):
    pairs = [(r["day"], v) for r in rows if r["h"] == h and (v := fav_pnl(r, x, mode)) is not None]
    s = K.daily_stats(pairs)
    by = collections.defaultdict(float)
    for d, v in pairs:
        by[d] += 100 * v
    daily = np.array([by[d] for d in sorted(by)])
    if len(daily):
        cum = np.cumsum(daily)
        s.update(worst_day_usd=float(daily.min()), max_drawdown_usd=float((np.maximum.accumulate(np.maximum(cum, 0)) - cum).max()))
    return s


if __name__ == "__main__":
    rows = V.load_rows()
    for r in rows:
        r["mid"] = (r["bid"] + r["ask"]) / 2
    test = [r for r in rows if r["day"] >= V.TEST_FROM]
    res = dict(base=dict(join=summary(test, 4, 0.2, "join"), improve=summary(test, 4, 0.2, "improve"), taker=summary(test, 4, 0.2, "taker")))
    res["neighbouring_settings_join"] = {f"{h}h x={x}": {k: v for k, v in summary(test, h, x, "join").items()} for h in V.HOURS for x in (0.05, 0.10, 0.20, 0.30)}
    months = collections.defaultdict(list)
    for r in test:
        if r["h"] == 4 and (v := fav_pnl(r, 0.2, "join")) is not None:
            months[r["day"].strftime("%Y-%m")].append(v)
    res["by_month_join_cents"] = {k: round(100 * float(np.mean(v)), 2) for k, v in sorted(months.items())}
    # adverse selection: among quotes the rule would rest on, compare outcomes of those that fill with those that do not
    filled, unfilled = [], []
    for r in test:
        if r["h"] != 4 or r["nx"] is None or not (r["mid"] >= 0.8 or r["mid"] <= 0.2):
            continue
        yes_side = r["mid"] >= 0.8
        won = r["y"] == 1 if yes_side else r["y"] == 0
        price = r["bid"] if yes_side else 1 - r["ask"]
        (filled if fav_pnl(r, 0.2, "join") is not None else unfilled).append((won, price))
    res["adverse_selection"] = dict(
        filled=dict(n=len(filled), win_rate=float(np.mean([w for w, _ in filled])), avg_price=float(np.mean([p for _, p in filled]))),
        unfilled=dict(n=len(unfilled), win_rate=float(np.mean([w for w, _ in unfilled])), avg_price=float(np.mean([p for _, p in unfilled]))))
    # only when the de-biased market probability agrees (exploratory; the filter was chosen after seeing the test data)
    iso = V.isotonic(np.array([r["mid"] for r in rows if r["day"] < V.TEST_FROM]), np.array([r["y"] for r in rows if r["day"] < V.TEST_FROM]))
    agree = [(r["day"], v) for r in test if r["h"] == 4 and (v := fav_pnl(r, 0.2, "join")) is not None
             and ((r["mid"] >= 0.8 and iso(r["mid"]) >= r["bid"]) or (r["mid"] <= 0.2 and iso(r["mid"]) <= r["ask"]))]
    res["exploratory_only_when_debiased_agrees"] = K.daily_stats(agree)
    print(json.dumps(res, indent=1, default=float))
    json.dump(res, open(os.path.join(HERE, "results_favorite_maker.json"), "w"), indent=1, default=float)

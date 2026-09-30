"""Stress test of the rule that survived: 4 hours before Kalshi's 5pm ET BTC close, buy the favourite on any
contract whose mid is at or beyond 80/20 (YES at the ask when mid >= 0.80, NO at the bid when mid <= 0.20).
The rule was picked on Mar-Dec 2025 (as the best model-free baseline in kalshi_edge.py); everything here is Jan-Sep 2026."""
import collections, json, os
import numpy as np
import kalshi_edge as K

HERE = os.path.dirname(os.path.abspath(__file__))
H, X = 4, 0.20


def pnl(r, x, side="both", agree=None):
    """P&L per contract after the taker fee, or None if the rule does not trade this quote."""
    m = (r["bid"] + r["ask"]) / 2
    if m >= 1 - x and side in ("both", "yes") and (agree is None or r[agree] >= r["ask"]):
        return r["y"] - r["ask"] - K.fee(r["ask"])
    if m <= x and side in ("both", "no") and (agree is None or r[agree] <= r["bid"]):
        return (1 - r["y"]) - (1 - r["bid"]) - K.fee(r["bid"])
    return None


def summary(rows, h, x, side="both", agree=None):
    pairs = [(r["day"], v) for r in rows if r["h"] == h and (v := pnl(r, x, side, agree)) is not None]
    s = K.daily_stats(pairs)
    by = collections.defaultdict(float)
    for d, v in pairs:
        by[d] += 100 * v
    daily = np.array([by[d] for d in sorted(by)])
    if len(daily):
        cum = np.cumsum(daily)
        s.update(worst_day_usd=float(daily.min()), max_drawdown_usd=float((np.maximum.accumulate(np.maximum(cum, 0)) - cum).max()))
    months = collections.defaultdict(list)
    for d, v in pairs:
        months[d.strftime("%Y-%m")].append(v)
    s["by_month_cents_per_contract"] = {k: round(100 * float(np.mean(v)), 2) for k, v in sorted(months.items())}
    return s


if __name__ == "__main__":
    rows = K.load_rows()
    train = [r for r in rows if r["day"] < K.TEST_FROM]
    test = [r for r in rows if r["day"] >= K.TEST_FROM]
    res = dict(
        rule=f"{H}h before close, favourite side when mid is beyond {1 - X:.2f}/{X:.2f}, 100 contracts per trade, taker fees",
        train=summary(train, H, X), test=summary(test, H, X),
        test_yes_side_only=summary(test, H, X, "yes"), test_no_side_only=summary(test, H, X, "no"),
        test_neighbouring_settings={f"{h}h x={x}": {k: v for k, v in summary(test, h, x).items() if k != "by_month_cents_per_contract"}
                                    for h in K.HOURS for x in (0.05, 0.10, 0.20, 0.30)},
        exploratory_only_when_model_agrees={m: {k: v for k, v in summary(test, H, X, agree=m).items() if k != "by_month_cents_per_contract"}
                                            for m in ("emp", "bates")},
    )
    print(json.dumps(res, indent=1, default=float))
    json.dump(res, open(os.path.join(HERE, "results_favorite.json"), "w"), indent=1, default=float)

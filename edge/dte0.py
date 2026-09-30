"""0DTE test: each day at 03:00 UTC, compare the market's 5-hour at-the-money straddle on Deribit with the model's value
using the seasonal volatility forecast, and trade the straddle unhedged into the 08:00 UTC expiry.
Rules are chosen on Mar-Dec 2025 and judged on Jan-Sep 2026. Costs come from the trades themselves."""
import json, os, sys, datetime as dt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backtest"))
from model import black, bates
from data import load_hourly, ms, HOUR
from volfc import forecast_vol

TEST_FROM = dt.date(2026, 1, 1)
NOTIONAL = 100_000
# Pricer's model with the shape fitted to Deribit in the backtest (calib.py medians); the level comes from the forecast.
SHAPE = dict(kv=20.0, sv=3.43, rho=-0.29, lam=5.9, muJ=-0.03, dJ=0.07)
JUMP_VAR = SHAPE["lam"] * (SHAPE["muJ"] ** 2 + SHAPE["dJ"] ** 2)
_, index, _ = load_hourly()


def day_row(d):
    path = os.path.join(HERE, "data", "deribit_0dte", f"{d}.json")
    t0, t1 = ms(d, 3), ms(d, 8)
    if not os.path.exists(path) or t0 not in index or t1 not in index:
        return None
    exp_code = d.strftime("%-d%b%y").upper()
    rows = [r for r in json.load(open(path)) if r[1].split("-")[1] == exp_code and r[3] and r[7]]
    if not rows:
        return None
    K = np.array([float(r[1].split("-")[2]) for r in rows]); idx = np.array([r[4] for r in rows])
    iv = np.array([r[3] for r in rows]) / 100; px = np.array([r[2] for r in rows]); mark = np.array([r[7] for r in rows])
    near = np.abs(np.log(K / idx)) < 0.01
    if near.sum() < 3:
        return None
    S0 = index[t0]
    strikes = np.unique(K)
    Kc = float(strikes[np.argmin(np.abs(strikes - S0))])
    iv_mkt = float(np.median(iv[near]))
    half_spread = float(np.median(np.abs(px[near] - mark[near]) / mark[near]))   # share of option price paid vs mark
    T = 5 / 8760
    legs = black([S0, S0], Kc, iv_mkt ** 2 * T, [1, -1])
    premium = float(legs.sum())
    fees = float(sum(min(0.0003 * S0, 0.125 * l) for l in legs))
    sig = forecast_vol(t0, 5)
    if sig is None:
        return None
    m = dict(SHAPE, v0=max(sig ** 2 - JUMP_VAR, 0.01), th=max(sig ** 2 - JUMP_VAR, 0.01))
    model_value = float(bates([S0, S0], Kc, [1, -1], T, T, m).sum())
    payoff = abs(index[t1] - Kc)
    q = NOTIONAL / S0
    realized = float(np.sqrt(np.sum(np.diff(np.log([index[t0 + k * HOUR] for k in range(6)])) ** 2) * 8760 / 5))
    return dict(date=str(d), S0=S0, K=Kc, iv_mkt=iv_mkt, forecast_vol=sig, realized_vol=realized, half_spread=half_spread,
                premium=q * premium, model_value=q * model_value, payoff=q * payoff,
                cost=q * (half_spread * premium + fees), edge=premium / model_value - 1)


def stats(pnl):
    pnl = np.asarray(pnl, float)
    if len(pnl) < 5:
        return dict(n=len(pnl))
    cum = np.cumsum(pnl)
    return dict(n=len(pnl), mean=float(pnl.mean()), t=float(pnl.mean() / pnl.std(ddof=1) * np.sqrt(len(pnl))),
                win=float(100 * (pnl > 0).mean()), total=float(cum[-1]), max_dd=float((np.maximum.accumulate(np.maximum(cum, 0)) - cum).max()),
                sharpe=float(pnl.mean() / pnl.std(ddof=1) * np.sqrt(365)))


def run(rows, rule, th):
    """P&L per day of a rule: 'short' sells when the market is at least th above model value, 'both' also buys when th below."""
    out = []
    for r in rows:
        short = r["premium"] - r["payoff"] - r["cost"]
        long_ = r["payoff"] - r["premium"] - r["cost"]
        if r["edge"] > th:
            out.append(short)
        elif rule == "both" and r["edge"] < -th:
            out.append(long_)
    return out


if __name__ == "__main__":
    rows, d = [], dt.date(2025, 3, 1)
    while d <= dt.date(2026, 9, 29):
        r = day_row(d)
        if r:
            rows.append(r)
        d += dt.timedelta(days=1)
    train = [r for r in rows if dt.date.fromisoformat(r["date"]) < TEST_FROM]
    test = [r for r in rows if dt.date.fromisoformat(r["date"]) >= TEST_FROM]
    a = lambda rs, k: np.array([r[k] for r in rs])
    res = dict(days=len(rows), train_days=len(train), test_days=len(test))
    for name, rs in (("train", train), ("test", test)):
        res[f"{name}_vols"] = dict(market_iv=float(a(rs, "iv_mkt").mean()), forecast=float(a(rs, "forecast_vol").mean()),
                                   realized=float(a(rs, "realized_vol").mean()), realized_rms=float(np.sqrt((a(rs, "realized_vol") ** 2).mean())))
        res[f"{name}_costs"] = dict(avg_premium=float(a(rs, "premium").mean()), avg_cost=float(a(rs, "cost").mean()),
                                    cost_share_of_premium=float(a(rs, "cost").mean() / a(rs, "premium").mean()), median_half_spread=float(np.median(a(rs, "half_spread"))))
        res[f"{name}_always_short_gross"] = stats(a(rs, "premium") - a(rs, "payoff"))
        res[f"{name}_always_short_net"] = stats(a(rs, "premium") - a(rs, "payoff") - a(rs, "cost"))
        res[f"{name}_always_long_net"] = stats(a(rs, "payoff") - a(rs, "premium") - a(rs, "cost"))
    grid = [(rule, th) for rule in ("short", "both") for th in (-1.0, 0.0, 0.1, 0.2, 0.3, 0.5)]
    scored = []
    for rule, th in grid:
        s = stats(run(train, rule, th))
        scored.append((s.get("t", -99) if s.get("n", 0) >= 30 else -99, rule, th, s))
    scored.sort(key=lambda x: -x[0])
    res["train_grid"] = [dict(rule=r, threshold=th, **s) for _, r, th, s in scored]
    _, rule, th, _ = scored[0]
    res["chosen_rule"] = dict(rule=rule, threshold=th)
    res["test_chosen_rule"] = stats(run(test, rule, th))
    res["test_all_rules"] = [dict(rule=r, threshold=t, **stats(run(test, r, t))) for r, t in grid]
    # Exploratory, not part of the pre-set rule selection: sell only, filled at mark (no spread paid), exchange fees still charged.
    at_mark = lambda rs, th: stats([r["premium"] - r["payoff"] - (r["cost"] - r["half_spread"] * r["premium"]) for r in rs if r["edge"] > th])
    res["exploratory_short_filled_at_mark"] = {f"{name} edge>{th}": at_mark(rs, th) for name, rs in (("train", train), ("test", test))
                                               for th in (-1.0, 0.0, 0.1, 0.2, 0.3, 0.5)}
    print(json.dumps(res, indent=1, default=float))
    json.dump(dict(summary=res, days=rows), open(os.path.join(HERE, "results_0dte.json"), "w"), indent=1, default=float)

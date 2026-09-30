"""Test 1: each Friday, value the one-week at-the-money straddle with the model using only past price data,
trade it against the market price, and delta-hedge with the perp (funding included) until expiry.
The hedge is checked hourly and rebalanced when the model delta has moved by more than HEDGE_BAND."""
import json, os, datetime as dt
import numpy as np
from model import bates, black, cf_grid, implied_vol, BTC_PRESET
from data import load_hourly, snapshot, ms, HOUR, DATA

R = 0.045                      # flat USD rate used for the perp forward
OPT_SPREAD = 0.01              # half-spread paid on the straddle, as a share of premium
OPT_FEE = 0.0003               # Deribit option fee per leg, share of underlying
PERP_FEE = 0.0005              # perp taker fee on every hedge trade
HEDGE_BAND = 0.10              # rebalance when delta is this far from the position held
NOTIONAL = 100_000             # every week trades a straddle on this much BTC, in USD
JUMP_VAR = BTC_PRESET["lam"] * (BTC_PRESET["muJ"] ** 2 + BTC_PRESET["dJ"] ** 2)

perp, index, fund = load_hourly()


def realized_vol(t, hours):
    px = [index.get(t - i * HOUR) for i in range(hours + 1)]
    if any(p is None for p in px):
        return None
    r = np.diff(np.log(px[::-1]))
    return float(np.sqrt(np.mean(r * r) * 8760))


def straddle(P, K, T, m, grid=None):
    f = P * np.exp(R * T)
    return float(np.exp(-R * T) * bates([f, f], K, [1, -1], T, T, m, grid).sum())


def run_week(d, variant):
    snap = snapshot(d)
    exp_date = d + dt.timedelta(days=7)
    t0, t1 = ms(d, 9), ms(exp_date, 8)
    if snap is None:
        return None
    ex = [e for e in snap["expiries"] if e["expiry"] == t1]
    hours = list(range(t0, t1 + 1, HOUR))
    if not ex or any(h not in perp or h not in index or h not in fund for h in hours):
        return None
    ex = ex[0]
    F_mkt = ex["F"] * index[t0] / snap["index"]
    near = np.abs(np.log(ex["K"] / F_mkt)) < 0.02
    if near.sum() == 0:
        return None
    K = float(ex["K"][np.argmin(np.abs(ex["K"] - F_mkt))])
    iv_mkt = float(np.median(ex["iv"][near]))
    T0 = (t1 - t0) / (365 * 24 * HOUR)
    premium = float(black([F_mkt, F_mkt], K, iv_mkt ** 2 * T0, [1, -1]).sum())

    rv_short, rv_long = realized_vol(t0, 14 * 24), realized_vol(t0, 180 * 24)
    if rv_short is None or rv_long is None:
        return None
    sub = JUMP_VAR if variant == "matched" else 0.0   # 'matched' removes the jump variance so total variance equals realized
    m = dict(BTC_PRESET, v0=max(rv_short ** 2 - sub, 0.01), th=max(rv_long ** 2 - sub, 0.01))
    P0 = perp[t0]
    model_px = straddle(P0, K, T0, m)
    f0 = P0 * np.exp(R * T0)
    side = 1 if K >= f0 else -1                     # Black vol that matches the model at this strike
    iv_model = float(implied_vol(bates(f0, K, side, T0, T0, m), f0, K, T0, side))

    hedge = funding = turnover = 0.0
    prev = 0.0
    for a, b in zip(hours[:-1], hours[1:]):
        T = (t1 - a) / (365 * 24 * HOUR)
        g = cf_grid(T, T, m)
        delta = (straddle(perp[a] * 1.005, K, T, m, g) - straddle(perp[a] * 0.995, K, T, m, g)) / (perp[a] * 0.01)
        if abs(delta - prev) > HEDGE_BAND or a == t0:
            turnover += abs(delta - prev) * perp[a]; prev = delta
        hedge += -prev * (perp[b] - perp[a])            # long straddle holds -delta perps
        funding += prev * fund[b] * perp[a]             # a short perp receives funding when the rate is positive
    turnover += abs(prev) * perp[t1]
    payoff = abs(index[t1] - K)                     # index at 08:00 UTC stands in for the 30-minute delivery average
    gross_long = payoff - premium + hedge + funding
    cost = OPT_SPREAD * premium + 2 * OPT_FEE * index[t0] + PERP_FEE * turnover
    rv_next = float(np.sqrt(np.mean(np.diff(np.log([index[h] for h in hours])) ** 2) * 8760))
    q = NOTIONAL / index[t0]                        # BTC traded this week
    return dict(date=str(d), K=K, index=index[t0], premium=q * premium, iv_mkt=iv_mkt, iv_model=iv_model, rv_next=rv_next,
                rv_short=rv_short, gross_long=q * gross_long, cost=q * cost, funding=q * funding, hedge=q * hedge, payoff=q * payoff)


def stats(pnl, prem):
    pnl = np.array(pnl)
    if len(pnl) < 2:
        return dict(n=len(pnl))
    cum = np.cumsum(pnl)
    return dict(n=len(pnl), mean_usd=pnl.mean(), mean_pct_premium=100 * pnl.mean() / np.mean(prem), win=100 * (pnl > 0).mean(),
                t=pnl.mean() / pnl.std(ddof=1) * np.sqrt(len(pnl)), sharpe=pnl.mean() / pnl.std(ddof=1) * np.sqrt(52),
                total_usd=cum[-1], max_drawdown_usd=float((np.maximum.accumulate(np.maximum(cum, 0)) - cum).max()))


if __name__ == "__main__":
    out = {}
    for variant in ("matched", "preset"):
        rows, d = [], dt.date(2023, 1, 6)
        while d <= dt.date(2026, 9, 18):
            r = run_week(d, variant)
            if r:
                rows.append(r)
            d += dt.timedelta(days=7)
        prem = [r["premium"] for r in rows]
        sig = [1 if r["iv_model"] > r["iv_mkt"] else -1 for r in rows]
        res = dict(
            always_long_gross=stats([r["gross_long"] for r in rows], prem),
            always_short_gross=stats([-r["gross_long"] for r in rows], prem),
            always_long=stats([r["gross_long"] - r["cost"] for r in rows], prem),
            always_short=stats([-r["gross_long"] - r["cost"] for r in rows], prem),
            model_signal_gross=stats([s * r["gross_long"] for s, r in zip(sig, rows)], prem),
            model_signal_net=stats([s * r["gross_long"] - r["cost"] for s, r in zip(sig, rows)], prem),
        )
        for y in (2023, 2024, 2025, 2026):
            sel = [(s, r) for s, r in zip(sig, rows) if r["date"].startswith(str(y))]
            res[f"model_signal_net_{y}"] = stats([s * r["gross_long"] - r["cost"] for s, r in sel], [r["premium"] for _, r in sel])
        a = lambda k: np.array([r[k] for r in rows])
        fc = {}
        for name, x in (("market_iv", a("iv_mkt")), ("model_iv", a("iv_model")), ("trailing_14d_realized", a("rv_short"))):
            e = x - a("rv_next")
            fc[name] = dict(bias_pts=100 * e.mean(), rmse_pts=100 * np.sqrt((e * e).mean()), corr=float(np.corrcoef(x, a("rv_next"))[0, 1]))
        res["forecast_of_next_week_realized_vol"] = fc
        res["weeks_long"], res["weeks_short"] = sig.count(1), sig.count(-1)
        res["avg_cost_usd"], res["avg_premium_usd"] = float(np.mean(a("cost"))), float(np.mean(prem))
        res["avg_funding_usd_long_straddle"] = float(np.mean(a("funding")))
        out[variant] = dict(summary=res, weeks=rows)
        print("\n==", variant, "==")
        for k, v in res.items():
            print(k, json.dumps(v, default=float) if isinstance(v, dict) else v)
    json.dump(out, open(os.path.join(DATA, "..", "results_weekly.json"), "w"), default=float, indent=1)

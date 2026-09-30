"""Prediction-market test: Kalshi 'Bitcoin above $K at 5pm ET' contracts versus model probabilities.
Buys YES at the ask when the model probability beats it by a threshold, or NO at the bid when the model is below it.
Rules (probability model, hours before close, threshold) are picked on Mar-Dec 2025 and judged on Jan-Sep 2026.
P&L is per contract after Kalshi's taker fee; t-stats are computed on daily totals because strikes on one day are correlated."""
import glob, json, math, os, sys, datetime as dt
import numpy as np
from scipy.special import ndtr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backtest"))
from model import bates, cf_grid
from data import load_hourly
from volfc import forecast_var, standardized_returns

TEST_FROM = dt.date(2026, 1, 1)
HOURS = (1, 2, 3, 4, 6)
WIDTH = 0.03
SHAPE = dict(kv=20.0, sv=3.43, rho=-0.29, lam=5.9, muJ=-0.03, dJ=0.07)   # Deribit-fitted shape from the backtest
JUMP_VAR = SHAPE["lam"] * (SHAPE["muJ"] ** 2 + SHAPE["dJ"] ** 2)
_, index, _ = load_hourly()
Z = {h: standardized_returns(h) for h in HOURS}


def fee(p, contracts=100):
    """Kalshi taker fee per contract: 7% of p(1-p), rounded up to the cent per order."""
    return math.ceil(round(0.07 * contracts * p * (1 - p) * 100, 6)) / 100 / contracts


def probabilities(S, K, var, h):
    """P(BTC above K at the close) three ways, for arrays of strikes."""
    sd = math.sqrt(var)
    x = np.log(K / S)
    p_norm = 1 - ndtr(x / sd + sd / 2)
    z = Z[h]
    p_emp = 1 - np.searchsorted(z, x / sd) / len(z)
    T = h / 8760
    v = max(var * 8760 / h - JUMP_VAR, 0.01)
    m = dict(SHAPE, v0=v, th=v)
    g = cf_grid(T, T, m)
    eps = 1e-4
    p_bates = (bates(S, K * (1 - eps), 1, T, T, m, g) - bates(S, K * (1 + eps), 1, T, T, m, g)) / (2 * K * eps)
    return dict(norm=p_norm, emp=p_emp, bates=np.clip(p_bates, 0, 1))


def load_rows():
    rows = []
    for path in sorted(glob.glob(os.path.join(HERE, "data", "kalshi", "*.json"))):
        ms_ = json.load(open(path))
        if not ms_:
            continue
        close = ms_[0]["close"]
        day = dt.datetime.fromtimestamp(close, dt.timezone.utc).date()
        for h in HOURS:
            t = close - h * 3600
            S = index.get(t * 1000)
            var = forecast_var(t * 1000, h)
            if S is None or var is None:
                continue
            quotes = []
            for m in ms_:
                c = {row[0]: row for row in m["candles"]}.get(t)
                if not c or c[1] is None or c[2] is None or not (0.01 <= c[1] < c[2] <= 0.99):
                    continue
                if abs(math.log(m["strike"] / S)) > WIDTH:
                    continue
                quotes.append((m["strike"], c[1], c[2], c[3] or 0.0, 1 if m["result"] == "yes" else 0))
            if not quotes:
                continue
            K = np.array([q[0] for q in quotes])
            P = probabilities(S, K, var, h)
            for j, (k, bid, ask, vol, y) in enumerate(quotes):
                rows.append(dict(day=day, h=h, K=k, S=S, bid=bid, ask=ask, vol=vol, y=y,
                                 norm=float(P["norm"][j]), emp=float(P["emp"][j]), bates=float(P["bates"][j])))
    return rows


def trade_pnl(r, p, th):
    if p - r["ask"] >= th:
        return r["y"] - r["ask"] - fee(r["ask"])
    if r["bid"] - p >= th:
        return (1 - r["y"]) - (1 - r["bid"]) - fee(r["bid"])
    return None


def daily_stats(pairs):
    """pairs: list of (day, pnl per contract). Stats on daily totals of 100-contract trades."""
    if not pairs:
        return dict(trades=0)
    by = {}
    for d, x in pairs:
        by[d] = by.get(d, 0.0) + 100 * x
    v = np.array(list(by.values()))
    per = np.array([x for _, x in pairs])
    out = dict(trades=len(pairs), days=len(v), cents_per_contract=float(100 * per.mean()), win=float(100 * (per > 0).mean()),
               total_usd=float(v.sum()))
    if len(v) > 5 and v.std(ddof=1) > 0:
        out["t"] = float(v.mean() / v.std(ddof=1) * np.sqrt(len(v)))
    return out


def score(rows, key):
    y = np.array([r["y"] for r in rows]); p = np.clip(np.array([r[key] if key != "mid" else (r["bid"] + r["ask"]) / 2 for r in rows]), 0.001, 0.999)
    return dict(brier=float(np.mean((p - y) ** 2)), logloss=float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))))


if __name__ == "__main__":
    rows = load_rows()
    train = [r for r in rows if r["day"] < TEST_FROM]
    test = [r for r in rows if r["day"] >= TEST_FROM]
    res = dict(quotes=len(rows), train_quotes=len(train), test_quotes=len(test),
               days=len({r["day"] for r in rows}), median_hourly_volume=float(np.median([r["vol"] for r in rows])),
               median_spread_cents=float(100 * np.median([r["ask"] - r["bid"] for r in rows])))
    for name, rs in (("train", train), ("test", test)):
        res[f"{name}_accuracy"] = {k: score(rs, k) for k in ("mid", "norm", "emp", "bates")}
    # calibration of the market itself (favourite-longshot check), all data
    bins = [0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 0.95, 1.0]
    cal = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        sel = [r for r in rows if lo <= (r["bid"] + r["ask"]) / 2 < hi]
        if sel:
            cal.append(dict(mid_range=f"{lo:.2f}-{hi:.2f}", n=len(sel), avg_mid=float(np.mean([(r["bid"] + r["ask"]) / 2 for r in sel])),
                            yes_rate=float(np.mean([r["y"] for r in sel])), avg_model_emp=float(np.mean([r["emp"] for r in sel]))))
    res["market_calibration"] = cal
    grid, scored = [], []
    for key in ("norm", "emp", "bates"):
        for h in HOURS:
            for th in (0.02, 0.04, 0.06, 0.08, 0.10, 0.15):
                s = daily_stats([(r["day"], x) for r in train if r["h"] == h and (x := trade_pnl(r, r[key], th)) is not None])
                grid.append((key, h, th))
                scored.append((s.get("t", -99) if s.get("days", 0) >= 40 else -99, key, h, th, s))
    # baseline without any model: sell longshots / buy favourites at mid below x or above 1 - x
    for h in HOURS:
        for x_ in (0.05, 0.10, 0.20):
            f = lambda r: (r["y"] - r["ask"] - fee(r["ask"])) if (r["bid"] + r["ask"]) / 2 >= 1 - x_ else \
                ((1 - r["y"]) - (1 - r["bid"]) - fee(r["bid"])) if (r["bid"] + r["ask"]) / 2 <= x_ else None
            s = daily_stats([(r["day"], v) for r in train if r["h"] == h and (v := f(r)) is not None])
            scored.append((s.get("t", -99) if s.get("days", 0) >= 40 else -99, "longshot_baseline", h, x_, s))
    scored.sort(key=lambda z: -z[0])
    res["train_top10"] = [dict(model=k, hours=h, threshold=th, **s) for _, k, h, th, s in scored[:10]]
    best_model = next(z for z in scored if z[1] != "longshot_baseline")
    best_base = next(z for z in scored if z[1] == "longshot_baseline")
    out = {}
    for _, k, h, th, _s in (best_model, best_base):
        if k == "longshot_baseline":
            f = lambda r: (r["y"] - r["ask"] - fee(r["ask"])) if (r["bid"] + r["ask"]) / 2 >= 1 - th else \
                ((1 - r["y"]) - (1 - r["bid"]) - fee(r["bid"])) if (r["bid"] + r["ask"]) / 2 <= th else None
            out[f"{k} h={h} x={th}"] = daily_stats([(r["day"], v) for r in test if r["h"] == h and (v := f(r)) is not None])
        else:
            out[f"{k} h={h} threshold={th}"] = daily_stats([(r["day"], x) for r in test if r["h"] == h and (x := trade_pnl(r, r[k], th)) is not None])
    res["test_chosen"] = out
    res["test_same_rule_every_model"] = {f"{k} h={best_model[2]} th={best_model[3]}": daily_stats(
        [(r["day"], x) for r in test if r["h"] == best_model[2] and (x := trade_pnl(r, r[k], best_model[3])) is not None]) for k in ("norm", "emp", "bates")}
    print(json.dumps(res, indent=1, default=str))
    json.dump(res, open(os.path.join(HERE, "results_kalshi.json"), "w"), indent=1, default=str)

"""Kalshi retry, informed by Burgi, Deng & Whelan (2026): makers earn more than takers and crypto contracts carry
the strongest favourite-longshot bias. Adds (a) resting limit orders simulated from next-hour candle lows/highs,
(b) a de-biased market probability (isotonic fit on 2025), (c) a DVOL-based probability, (d) a logistic blend.
Rules are chosen on Mar-Dec 2025 and judged on Jan-Sep 2026. Needs data/kalshi2 (fetch_kalshi2.py) and data/dvol.json."""
import glob, json, math, os, sys, datetime as dt
import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr, expit, logit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "perps", "backtest")); sys.path.insert(0, os.path.join(HERE, "..", "..", "common"))
import kalshi_edge as K
from volfc import forecast_var, SEAS, bucket, R2, TS, POS
from data import load_hourly, ms, HOUR

TEST_FROM = dt.date(2026, 1, 1)
HOURS = (1, 2, 3, 4, 6)
WIDTH = 0.03
MAKER_FEE = 0.0175          # Kalshi maker rate on series flagged quadratic_with_maker_fees; KXBTCD is plain quadratic, so 0 applies
_, index, _ = load_hourly()
DVOL = dict(json.load(open(os.path.join(HERE, "data", "dvol.json"))))


def fee(p, rate, contracts=100):
    return math.ceil(round(rate * contracts * p * (1 - p) * 100, 6)) / 100 / contracts


def dvol_at(t_ms):
    return DVOL.get(t_ms) or DVOL.get(t_ms - HOUR) or DVOL.get(t_ms - 2 * HOUR)


def fit_dvol_multiplier():
    """Realized / DVOL-implied hourly variance over the training months (variance risk premium correction)."""
    num = den = 0.0
    for t in range(ms(dt.date(2025, 3, 1)), ms(dt.date(2026, 1, 1)), HOUR):
        i, v = POS.get(t), dvol_at(t)
        if i is None or v is None or not np.isfinite(R2[i + 1] if i + 1 < len(R2) else np.nan):
            continue
        num += R2[i + 1]; den += (v / 100) ** 2 / 8760 * SEAS[bucket(t + HOUR)]
    return num / den


M_DVOL = fit_dvol_multiplier()


def dvol_var(t_ms, h):
    v = dvol_at(t_ms)
    if v is None:
        return None
    return M_DVOL * (v / 100) ** 2 / 8760 * sum(SEAS[bucket(t_ms + (k + 1) * HOUR)] for k in range(h))


def load_rows():
    rows = []
    for path in sorted(glob.glob(os.path.join(HERE, "data", "kalshi2", "*.json"))):
        ms_ = json.load(open(path))
        if not ms_:
            continue
        close = ms_[0]["close"]
        day = dt.datetime.fromtimestamp(close, dt.timezone.utc).date()
        for h in HOURS:
            t = close - h * 3600
            S, var, vard = index.get(t * 1000), forecast_var(t * 1000, h), dvol_var(t * 1000, h)
            if S is None or var is None or vard is None:
                continue
            quotes = []
            for m in ms_:
                by = {row[0]: row for row in m["candles"]}
                c, nx = by.get(t), by.get(t + 3600)
                if not c or c[1] is None or c[2] is None or not (0.01 <= c[1] < c[2] <= 0.99) or abs(math.log(m["strike"] / S)) > WIDTH:
                    continue
                quotes.append((m["strike"], c, nx, 1 if m["result"] == "yes" else 0))
            if not quotes:
                continue
            Ks = np.array([q[0] for q in quotes])
            P = K.probabilities(S, Ks, var, h)
            Pd = K.probabilities(S, Ks, vard, h)
            for j, (k, c, nx, y) in enumerate(quotes):
                rows.append(dict(day=day, h=h, K=k, S=S, bid=c[1], ask=c[2], vol=c[3] or 0.0, y=y, nx=nx,
                                 emp=float(P["emp"][j]), bates=float(P["bates"][j]), dvol=float(Pd["emp"][j]), dvol_norm=float(Pd["norm"][j])))
    return rows


def isotonic(x, y):
    """Pool-adjacent-violators fit of y on x; returns a step function via interpolation."""
    o = np.argsort(x); x, y = x[o], y[o]
    lvl, wts, xs = list(y.astype(float)), [1.0] * len(y), list(x)
    i = 0
    vals, w, xb = [], [], []
    for v, xx in zip(lvl, xs):
        vals.append(v); w.append(1.0); xb.append(xx)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v2 = (vals[-2] * w[-2] + vals[-1] * w[-1]) / (w[-2] + w[-1])
            vals[-2:] = [v2]; w[-2:] = [w[-2] + w[-1]]; xb[-2:] = [xb[-1]]
    xb, vals = np.array(xb), np.array(vals)
    return lambda q: np.interp(q, xb, vals)


def fit_blend(rows, keys):
    X = np.column_stack([np.ones(len(rows))] + [logit(np.clip([r[k] if k != "mid" else (r["bid"] + r["ask"]) / 2 for r in rows], 1e-3, 1 - 1e-3)) for k in keys])
    y = np.array([r["y"] for r in rows], float)
    nll = lambda b: -np.sum(y * np.log(expit(X @ b) + 1e-12) + (1 - y) * np.log(1 - expit(X @ b) + 1e-12)) + 0.01 * b[1:] @ b[1:]
    b = minimize(nll, np.zeros(X.shape[1]), method="L-BFGS-B").x
    return b, lambda rs: expit(np.column_stack([np.ones(len(rs))] + [logit(np.clip([r[k] if k != "mid" else (r["bid"] + r["ask"]) / 2 for r in rs], 1e-3, 1 - 1e-3)) for k in keys]) @ b)


def pnl(r, p, th, mode, maker_rate):
    """P&L per contract, or None if no trade / no fill. mode: taker | join | improve."""
    b, a, y, nx = r["bid"], r["ask"], r["y"], r["nx"]
    if mode == "taker":
        if p - a >= th:
            return y - a - fee(a, 0.07)
        if b - p >= th:
            return (1 - y) - (1 - b) - fee(b, 0.07)
        return None
    if nx is None:
        return None
    trL, trH = nx[8], nx[9]                                 # a fill needs a trade printed at or through the resting price
    if mode == "join":
        if p - b >= th:                                     # rest a YES bid at the current best bid
            return (y - b - fee(b, maker_rate)) if (trL is not None and trL <= b) else None
        if a - p >= th:                                     # rest a YES offer at the current best ask
            return ((1 - y) - (1 - a) - fee(a, maker_rate)) if (trH is not None and trH >= a) else None
        return None
    bi, ai = b + 0.01, a - 0.01                              # improve by one cent (only if the spread allows)
    if bi < a and p - bi >= th:
        return (y - bi - fee(bi, maker_rate)) if (trL is not None and trL <= bi) else None
    if ai > b and ai - p >= th:
        return ((1 - y) - (1 - ai) - fee(ai, maker_rate)) if (trH is not None and trH >= ai) else None
    return None


def grid_search(rows, models, modes, maker_rate, min_days=40):
    out = []
    for key in models:
        for h in HOURS:
            for mode in modes:
                for th in (0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15):
                    sub = [r for r in rows if r["h"] == h]
                    s = K.daily_stats([(r["day"], x) for r in sub if (x := pnl(r, r[key], th, mode, maker_rate)) is not None])
                    s.update(model=key, hours=h, mode=mode, threshold=th)
                    s["score"] = s.get("t", -99) if s.get("days", 0) >= min_days else -99
                    out.append(s)
    return sorted(out, key=lambda s: -s["score"])


def score(rows, key):
    y = np.array([r["y"] for r in rows]); p = np.clip(np.array([r[key] for r in rows]), 1e-3, 1 - 1e-3)
    return dict(brier=float(np.mean((p - y) ** 2)), logloss=float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))))


if __name__ == "__main__":
    rows = load_rows()
    for r in rows:
        r["mid"] = (r["bid"] + r["ask"]) / 2
    train = [r for r in rows if r["day"] < TEST_FROM]
    test = [r for r in rows if r["day"] >= TEST_FROM]
    iso = isotonic(np.array([r["mid"] for r in train]), np.array([r["y"] for r in train]))
    for r in rows:
        r["debiased"] = float(iso(r["mid"]))
    b_all, pred_all = fit_blend(train, ["mid", "emp", "dvol"])
    b_nomkt, pred_nomkt = fit_blend(train, ["emp", "dvol"])
    for rs in (train, test):
        for r, p1, p2 in zip(rs, pred_all(rs), pred_nomkt(rs)):
            r["blend"], r["blend_nomkt"] = float(p1), float(p2)
    models = ["mid", "emp", "bates", "dvol", "dvol_norm", "debiased", "blend", "blend_nomkt"]
    res = dict(quotes=len(rows), train_quotes=len(train), test_quotes=len(test), days=len({r["day"] for r in rows}),
               dvol_variance_multiplier=float(M_DVOL), blend_weights=dict(zip(["const", "logit_mid", "logit_emp", "logit_dvol"], b_all.round(3).tolist())),
               train_accuracy={k: score(train, k) for k in models}, test_accuracy={k: score(test, k) for k in models})
    trade_models = [k for k in models if k != "mid"]
    for name, rate in (("maker_fee_0", 0.0), ("maker_fee_0.0175", MAKER_FEE)):
        g = grid_search(train, trade_models, ["taker", "join", "improve"], rate)
        res[f"{name}_train_top"] = g[:8]
        chosen = g[0]
        sub = [r for r in test if r["h"] == chosen["hours"]]
        res[f"{name}_test_chosen"] = dict(rule={k: chosen[k] for k in ("model", "hours", "mode", "threshold")}, train_t=chosen["score"],
                                         test=K.daily_stats([(r["day"], x) for r in sub if (x := pnl(r, r[chosen["model"]], chosen["threshold"], chosen["mode"], rate)) is not None]))
        # best rule per execution mode, judged on test
        per_mode = {}
        for mode in ("taker", "join", "improve"):
            c = next(s for s in g if s["mode"] == mode)
            sub = [r for r in test if r["h"] == c["hours"]]
            per_mode[mode] = dict(rule={k: c[k] for k in ("model", "hours", "mode", "threshold")}, train_t=c["score"],
                                  test=K.daily_stats([(r["day"], x) for r in sub if (x := pnl(r, r[c["model"]], c["threshold"], c["mode"], rate)) is not None]))
        res[f"{name}_test_best_per_mode"] = per_mode
        # favourite-longshot rule as a maker: rest at the quote on the favourite side when mid beyond 80/20, 4h before close
        fav = []
        for r in test:
            if r["h"] != 4 or r["nx"] is None:
                continue
            x = pnl(r, 1.0, 0.0, "join", rate) if r["mid"] >= 0.8 else pnl(r, 0.0, 0.0, "join", rate) if r["mid"] <= 0.2 else None
            if x is not None:
                fav.append((r["day"], x))
        res[f"{name}_test_favourite_rule_as_maker"] = K.daily_stats(fav)
    fav_t = []
    for r in test:
        if r["h"] == 4:
            x = pnl(r, 1.0, 0.0, "taker", 0) if r["mid"] >= 0.8 else pnl(r, 0.0, 0.0, "taker", 0) if r["mid"] <= 0.2 else None
            if x is not None:
                fav_t.append((r["day"], x))
    res["test_favourite_rule_as_taker"] = K.daily_stats(fav_t)
    fills = [r for r in rows if r["nx"] is not None]
    res["fill_rates"] = dict(join_bid=float(np.mean([r["nx"][8] is not None and r["nx"][8] <= r["bid"] for r in fills])),
                             join_ask=float(np.mean([r["nx"][9] is not None and r["nx"][9] >= r["ask"] for r in fills])),
                             improve_bid=float(np.mean([r["nx"][8] is not None and r["nx"][8] <= r["bid"] + 0.01 for r in fills])))
    print(json.dumps(res, indent=1, default=str))
    json.dump(res, open(os.path.join(HERE, "results_kalshi_v2.json"), "w"), indent=1, default=str)

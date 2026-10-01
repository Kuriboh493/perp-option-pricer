"""Is the Kalshi BTC favourites edge mispricing, or compensation for tail risk?

For every trade the favourites rule makes (4h before the 5pm ET close, strike within 3% of spot, mid beyond 80/20), price the
same contract off the Deribit options market at the same moment: fit the smile of the first Deribit expiry after the Kalshi
close from option trades in the preceding hour, rescale it to the Kalshi window with the hour-of-week variance clock, and take
the risk-neutral probability of finishing on the favourite's side. That probability already contains whatever the options
market charges for tail risk. Each trade's profit then splits into
    (outcome - P_options)   what the options market also earns from the same tail   -> tail-risk compensation
    (P_options - price)     how much cheaper Kalshi is than the options market      -> mispricing
"""
import glob, json, math, os, sys, datetime as dt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "perps", "backtest")); sys.path.insert(0, os.path.join(HERE, "..", "..", "common"))
from model import black
from data import implied_forward, load_hourly, HOUR
from volfc import SEAS, bucket

YEAR_S = 365 * 86400
_, INDEX, _ = load_hourly()


def kalshi_trades():
    """Rule trades with exact decision time, both execution variants (join only when the backtest's fill condition held)."""
    out = []
    for f in sorted(glob.glob(os.path.join(HERE, "data", "kalshi2", "*.json"))):
        ms_ = json.load(open(f))
        if not ms_:
            continue
        close = ms_[0]["close"]; t = close - 4 * 3600
        S = INDEX.get(t * 1000)
        if S is None:
            continue
        for m in ms_:
            by = {c[0]: c for c in m["candles"]}
            c, nx = by.get(t), by.get(t + 3600)
            if not c or c[1] is None or c[2] is None or not (0.01 <= c[1] < c[2] <= 0.99) or abs(math.log(m["strike"] / S)) > 0.03:
                continue
            b, a = c[1], c[2]; mid = (b + a) / 2
            if mid >= 0.8:
                side, taker, join = "yes", a, b
                joined = nx is not None and nx[8] is not None and nx[8] <= b
            elif mid <= 0.2:
                side, taker, join = "no", 1 - b, 1 - a
                joined = nx is not None and nx[9] is not None and nx[9] >= a
            else:
                continue
            y = 1 if (m["result"] == "yes") == (side == "yes") else 0
            out.append(dict(t=t, close=close, day=dt.datetime.fromtimestamp(close, dt.timezone.utc).date(), K=m["strike"], S=S, side=side,
                            taker=taker, join=join if joined else None, y=y))
    return out


def deribit_smile(t, close):
    """Smile of the first Deribit expiry after the Kalshi close, from trades in [t - 1h, t + 15m]."""
    d = dt.datetime.fromtimestamp(t, dt.timezone.utc).date()
    path = os.path.join(HERE, "data", "deribit_afternoon", f"{d}.json")
    if not os.path.exists(path):
        return None
    rows = [r for r in json.load(open(path)) if r[3] and t - 3600 <= r[0] / 1000 <= t + 900]
    if len(rows) < 10:
        return None
    parts = [r[1].split("-") for r in rows]
    exp = np.array([dt.datetime.strptime(p[1], "%d%b%y").replace(hour=8, tzinfo=dt.timezone.utc).timestamp() for p in parts])
    future = exp[exp > close]
    if len(future) == 0:
        return None
    e = future.min()
    sel = exp == e
    K = np.array([float(p[2]) for p in parts])[sel]; cp = np.array([1.0 if p[3] == "C" else -1.0 for p in parts])[sel]
    iv = np.array([r[3] for r in rows])[sel] / 100; px = np.array([r[2] for r in rows])[sel]; idx = np.array([r[4] for r in rows])[sel]
    ts = np.array([r[0] / 1000 for r in rows])[sel]
    T = (e - ts) / YEAR_S
    atm = (np.abs(np.log(K / idx)) < 0.02) & (px >= 0.0005)
    if atm.sum() < 3:
        return None
    ratio = float(np.median(implied_forward(px[atm], iv[atm], K[atm], T[atm], cp[atm], idx[atm]) / idx[atm]))
    strikes = np.unique(K)
    vols = np.array([np.median(iv[K == k]) for k in strikes])
    return dict(expiry=e, T=(e - t) / YEAR_S, ratio=ratio, K=strikes, iv=vols)


def window_fraction(t, close, expiry):
    """Share of the variance between t and the Deribit expiry that falls between t and the Kalshi close (variance clock)."""
    hrs = lambda a, b: sum(SEAS[bucket(int(a * 1000) + (k + 1) * HOUR)] for k in range(int(round((b - a) / 3600))))
    return hrs(t, close) / hrs(t, expiry)


def options_probability(tr, sm, seasonal=True):
    """Risk-neutral P(finish on the favourite's side) for the Kalshi window, from the Deribit smile in standardised moneyness."""
    F = tr["S"] * sm["ratio"]
    z = np.log(sm["K"] / F)
    s0 = float(np.interp(0.0, z, sm["iv"])) if z.min() < 0 < z.max() else float(sm["iv"][np.argmin(np.abs(z))])
    zs = z / (s0 * math.sqrt(sm["T"]))
    keep = np.abs(zs) <= 3
    if keep.sum() < 5:
        return None
    coef = np.polyfit(zs[keep], sm["iv"][keep], 2)                      # iv as a quadratic in standardised moneyness
    w = window_fraction(tr["t"], tr["close"], sm["expiry"]) if seasonal else (tr["close"] - tr["t"]) / (sm["expiry"] - tr["t"])
    V4 = s0 * s0 * sm["T"] * w                                           # ATM total variance over the Kalshi window
    F4 = tr["S"]                                                         # four hours of drift is negligible

    def call(k):
        zk = math.log(k / F4) / math.sqrt(V4)
        ivk = max(np.polyval(coef, max(-3.0, min(3.0, zk))), 0.05)
        return float(black(F4, k, (ivk / s0) ** 2 * V4, 1))
    h = 0.001 * tr["K"]
    above = (call(tr["K"] - h) - call(tr["K"] + h)) / (2 * h)
    above = min(max(above, 0.0), 1.0)
    return above if tr["side"] == "yes" else 1 - above


def summarise(rows, price_key, fee):
    rows = [r for r in rows if r[price_key] is not None]
    if len(rows) < 20:
        return dict(n=len(rows))
    def day_t(vals):
        by = {}
        for r, v in zip(rows, vals):
            by[r["day"]] = by.get(r["day"], 0.0) + v
        a = np.array(list(by.values()))
        return float(a.mean() / a.std(ddof=1) * math.sqrt(len(a))) if len(a) > 5 and a.std() > 0 else None
    y = np.array([r["y"] for r in rows], float); P = np.array([r["pq"] for r in rows]); p = np.array([r[price_key] for r in rows])
    f = np.array([fee(x) for x in p])
    total, tail, misp = y - p - f, y - P, P - p - f
    return dict(n=len(rows), days=len({r["day"] for r in rows}), avg_price_c=round(100 * p.mean(), 2), avg_options_prob_c=round(100 * P.mean(), 2),
                realised_win_rate_c=round(100 * y.mean(), 2),
                total_c=round(100 * total.mean(), 2), total_t=day_t(total),
                tail_compensation_c=round(100 * tail.mean(), 2), tail_t=day_t(tail),
                mispricing_vs_options_c=round(100 * misp.mean(), 2), mispricing_t=day_t(misp),
                share_of_trades_kalshi_cheaper=round(float(np.mean(P > p)), 3))


if __name__ == "__main__":
    tfee = lambda p: math.ceil(round(0.07 * 100 * p * (1 - p) * 100, 6)) / 100 / 100
    trades = kalshi_trades(); print(len(trades), "rule trades", flush=True)
    smiles, priced = {}, []
    for tr in trades:
        key = tr["t"]
        if key not in smiles:
            smiles[key] = deribit_smile(tr["t"], tr["close"])
        sm = smiles[key]
        if not sm:
            continue
        pq, pf = options_probability(tr, sm, True), options_probability(tr, sm, False)
        if pq is None:
            continue
        priced.append(dict(tr, pq=pq, pq_flat=pf))
    print(len(priced), "priced against Deribit on", len({r["day"] for r in priced}), "days", flush=True)
    res = {}
    split = dt.date(2026, 1, 1)
    for period, rs in (("2025", [r for r in priced if r["day"] < split]), ("2026", [r for r in priced if r["day"] >= split]), ("all", priced)):
        res[period] = dict(taker=summarise(rs, "taker", tfee), join=summarise(rs, "join", lambda p: 0.0))
        flat = [dict(r, pq=r["pq_flat"]) for r in rs]
        res[period]["taker_flat_time_robustness"] = summarise(flat, "taker", tfee)
        for side in ("yes", "no"):
            res[period][f"taker_{side}_side"] = summarise([r for r in rs if r["side"] == side], "taker", tfee)
    # calibration: realised win rate by options-probability bucket (is the options market itself fair on these tails?)
    bins = [0.80, 0.90, 0.95, 0.98, 1.001]
    res["options_calibration"] = [dict(options_prob=f"{lo:.2f}-{hi:.2f}", n=len(s), avg_options_prob=round(float(np.mean([r['pq'] for r in s])), 4),
                                       realised=round(float(np.mean([r['y'] for r in s])), 4), avg_kalshi_taker=round(float(np.mean([r['taker'] for r in s])), 4))
                                  for lo, hi in zip(bins[:-1], bins[1:]) if (s := [r for r in priced if lo <= r["pq"] < hi])]
    print(json.dumps(res, indent=1, default=str))
    json.dump(res, open(os.path.join(HERE, "results_tail_test.json"), "w"), indent=1, default=str)

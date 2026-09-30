"""Polymarket Bitcoin 'Up or Down' windows (15m, hourly, daily): market price vs a model probability at fixed lead times,
calibration by price, and favourite-longshot / model rules. Prices are last trades of the Up token; fee is Polymarket's crypto
taker fee 0.07*p*(1-p) (makers pay nothing). Rules are chosen on the first part of each sample and judged on the rest."""
import glob, json, math, os, datetime as dt
import numpy as np
from volfc2 import VolModel

HERE = os.path.dirname(os.path.abspath(__file__))
LEADS = {"15m": [600, 300, 180, 120, 60], "1h": [1800, 900, 300, 120, 60], "1d": [21600, 7200, 3600, 900, 300]}
SPLIT = {"15m": dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc), "1h": dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc), "1d": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)}
VOL = VolModel("BTC")
_b1 = json.load(open(os.path.join(HERE, "data", "btc_1m.json")))
OPEN = {r[0]: r[1] for r in _b1}; CLOSE = {r[0]: r[2] for r in _b1}


def fee(p):
    return math.ceil(round(0.07 * 100 * p * (1 - p) * 100, 6)) / 100 / 100


def spot_at(t):
    """Close of the last full minute before t (no look-ahead)."""
    m = (t // 60) * 60 - 60
    for k in range(5):
        if m - 60 * k in CLOSE:
            return CLOSE[m - 60 * k]
    return None


def load(kind):
    rows = []
    for f in sorted(glob.glob(os.path.join(HERE, "data", "polymarket", kind, "*.json"))):
        d = json.load(open(f))
        if not d or not d.get("history") or not d.get("outcome_prices"):
            continue
        op = json.loads(d["outcome_prices"]); outs = [o.lower() for o in d["outcomes"]]
        if "up" not in outs or op[outs.index("up")] not in ("1", "0"):
            continue
        y = 1 if op[outs.index("up")] == "1" else 0
        S, E = d["start"], d["end"]
        ref = OPEN.get((S // 60) * 60)
        if ref is None:
            continue
        hist = d["history"]
        ts = np.array([h[0] for h in hist]); ps = np.array([h[1] for h in hist])
        for L in LEADS[kind]:
            tau = E - L
            j = np.searchsorted(ts, tau, side="right") - 1
            if j < 0 or tau - ts[j] > max(L / 2, 90):
                continue
            p_mkt = float(ps[j]); spot = spot_at(tau)
            k = j + 1                                                  # next printed trade after the decision time: the fill proxy
            p_fill = float(ps[k]) if k < len(ts) and ts[k] - tau <= 20 else None
            if spot is None or not (0.005 <= p_mkt <= 0.995):
                continue
            var = VOL.var_minutes(tau * 1000, L / 60)
            if not var:
                continue
            p_emp = float(VOL.prob_above(spot, ref, var, True)); p_norm = float(VOL.prob_above(spot, ref, var, False))
            rows.append(dict(kind=kind, day=dt.datetime.fromtimestamp(E, dt.timezone.utc), L=L, p=p_mkt, p_fill=p_fill, y=y, emp=p_emp, norm=p_norm,
                             vol=float(d.get("volume") or 0), dist=math.log(spot / ref)))
    return rows


def brier(rows, key):
    return float(np.mean([(r[key] - r["y"]) ** 2 for r in rows])) if rows else float("nan")


def calib(rows):
    bins = [0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 0.95, 1.01]
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        s = [r for r in rows if lo <= r["p"] < hi]
        if len(s) >= 20:
            ret = np.mean([r["y"] - r["p"] - fee(r["p"]) for r in s])
            out.append(dict(price=f"{lo:.2f}-{hi:.2f}", n=len(s), avg_price=round(float(np.mean([r["p"] for r in s])), 3),
                            up_rate=round(float(np.mean([r["y"] for r in s])), 3), buy_up_return_after_fee=round(100 * float(ret), 2)))
    return out


def stats(pnl):
    pnl = np.asarray(pnl, float)
    if len(pnl) < 10:
        return dict(n=len(pnl))
    return dict(n=len(pnl), cents=float(100 * pnl.mean()), t=float(pnl.mean() / pnl.std(ddof=1) * np.sqrt(len(pnl))), win=float(100 * (pnl > 0).mean()), total_usd_100=float(100 * pnl.sum()))


def fav(r, x, taker=True):
    f = fee(r["p"]) if taker else 0.0
    if r["p"] >= 1 - x:
        return r["y"] - r["p"] - f
    if r["p"] <= x:
        return (1 - r["y"]) - (1 - r["p"]) - f
    return None


def model_rule(r, key, th, taker=True, latency=False):
    """Decide on the last price; with latency=True the fill is the next printed trade within 20 s (else no trade)."""
    px = r["p_fill"] if latency else r["p"]
    if px is None:
        return None
    f = fee(px) if taker else 0.0
    if r[key] - r["p"] >= th:
        return r["y"] - px - f
    if r["p"] - r[key] >= th:
        return (1 - r["y"]) - (1 - px) - f
    return None


if __name__ == "__main__":
    res = {}
    for kind in ("15m", "1h", "1d"):
        rows = load(kind)
        if not rows:
            continue
        tr = [r for r in rows if r["day"] < SPLIT[kind]]; te = [r for r in rows if r["day"] >= SPLIT[kind]]
        k = dict(windows=len({r["day"] for r in rows}), rows=len(rows), train_rows=len(tr), test_rows=len(te),
                 brier_by_lead={L: dict(market=brier([r for r in rows if r["L"] == L], "p"), emp=brier([r for r in rows if r["L"] == L], "emp"), norm=brier([r for r in rows if r["L"] == L], "norm")) for L in LEADS[kind]},
                 calibration_all=calib(rows))
        grid = []
        for L in LEADS[kind]:
            for x in (0.05, 0.1, 0.2, 0.3):
                s = stats([v for r in tr if r["L"] == L and (v := fav(r, x)) is not None]); grid.append(("fav", L, x, s))
            for key in ("emp", "norm"):
                for th in (0.05, 0.1, 0.15, 0.2):
                    s = stats([v for r in tr if r["L"] == L and (v := model_rule(r, key, th)) is not None]); grid.append((key, L, th, s))
        grid = [g for g in grid if g[3].get("n", 0) >= 30]
        grid.sort(key=lambda g: -g[3].get("t", -99))
        k["train_top"] = [dict(rule=g[0], lead_s=g[1], param=g[2], **g[3]) for g in grid[:6]]
        for name, g in (("best_favourite", next((g for g in grid if g[0] == "fav"), None)), ("best_model", next((g for g in grid if g[0] != "fav"), None))):
            if g:
                fn = (lambda r: fav(r, g[2])) if g[0] == "fav" else (lambda r: model_rule(r, g[0], g[2]))
                k[f"test_{name}"] = dict(rule=g[0], lead_s=g[1], param=g[2], train=g[3], test=stats([v for r in te if r["L"] == g[1] and (v := fn(r)) is not None]),
                                         test_no_fee=stats([v for r in te if r["L"] == g[1] and (v := (fav(r, g[2], False) if g[0] == "fav" else model_rule(r, g[0], g[2], False))) is not None]))
                if g[0] != "fav":
                    k[f"test_{name}"]["train_latency_fill"] = stats([v for r in tr if r["L"] == g[1] and (v := model_rule(r, g[0], g[2], True, True)) is not None])
                    k[f"test_{name}"]["test_latency_fill"] = stats([v for r in te if r["L"] == g[1] and (v := model_rule(r, g[0], g[2], True, True)) is not None])
        res[kind] = k
    print(json.dumps(res, indent=1, default=str))
    json.dump(res, open(os.path.join(HERE, "results_polymarket.json"), "w"), indent=1, default=str)

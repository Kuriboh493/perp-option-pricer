"""Kalshi's newer price-threshold series (hourly ETH/SOL/XRP/BTC, hourly S&P 500, 15-minute BTC), Aug-Sep 2026:
quotes at fixed lead times before close vs a model probability; calibration; favourite and model rules as taker and maker.
All these series are plain 'quadratic' fee series, so makers pay nothing. Rules chosen on August, judged on September."""
import bisect, glob, json, math, os, datetime as dt
import numpy as np
from volfc2 import VolModel

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET = {"KXETHD": "ETH", "KXSOLD": "SOL", "KXXRPD": "XRP", "KXBTC": "BTC", "KXINXU": "SPX", "KXBTC15M": "BTC"}
LEADS = {"KXBTC15M": [12, 8, 5, 2, 1]}
DEFAULT_LEADS = [50, 30, 15, 5, 2]
SPLIT = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
WIDTH = 0.02


def fee(p):
    return math.ceil(round(0.07 * 100 * p * (1 - p) * 100, 6)) / 100 / 100


class Spot:
    def __init__(self, asset):
        if asset == "SPX":
            rows = json.load(open(os.path.join(HERE, "data", "spx_5m.json"))); self.step = 300
        elif asset == "BTC":
            rows = json.load(open(os.path.join(HERE, "data", "btc_1m.json"))); self.step = 60
        else:
            rows = json.load(open(os.path.join(HERE, "data", f"{asset.lower()}_1m.json"))); self.step = 60
        self.close = {r[0]: r[2] for r in rows}

    def at(self, t):
        m = (t // self.step) * self.step - self.step
        for k in range(6):
            if m - self.step * k in self.close:
                return self.close[m - self.step * k]
        return None


def p_yes(vol, spot, m, var):
    """Model probability that the market resolves YES given its strike type."""
    if m["strike_type"] == "greater":
        return vol.prob_above(spot, m["strike"], var)
    if m["strike_type"] == "less":
        return 1 - vol.prob_above(spot, m["cap"], var)
    if m["strike_type"] == "between":
        return vol.prob_above(spot, m["strike"], var) - vol.prob_above(spot, m["cap"], var)
    return None


def load(series):
    asset = ASSET[series]; vol = VolModel(asset, always_open=(asset != "SPX")); spot = Spot(asset)
    rows = []
    for f in sorted(glob.glob(os.path.join(HERE, "data", "kalshi_recent", series, "*.json"))):
        ms_ = json.load(open(f))
        if not ms_:
            continue
        close = ms_[0]["close"]
        hourly = ms_[0].get("resolution", 1) == 60          # thin events only carry hour candles: one lead, trade prices
        for L in ([60] if hourly else LEADS.get(series, DEFAULT_LEADS)):
            tau = close - 60 * L
            S = spot.at(tau)
            var = vol.var_minutes(tau * 1000, L)
            if S is None or not var:
                continue
            for m in ms_:
                lvl = m["strike"] if m["strike"] is not None else m["cap"]
                if lvl is None or abs(math.log(lvl / S)) > WIDTH:
                    continue
                cs = m["candles"]; ts = [c[0] for c in cs]
                j = bisect.bisect_right(ts, tau) - 1                 # last candle at or before the lead time (candles are sparse)
                if j < 0 or tau - ts[j] > (3600 if hourly else 600):
                    continue
                c = cs[j]
                if hourly:                                    # no standing quotes: use the hour's last trade as both bid and ask
                    if c[10] is None or not (0.01 <= c[10] <= 0.99) or not (c[3] or 0) > 0:
                        continue
                    c = [c[0], c[10], c[10], c[3]] + [None] * 7
                elif c[1] is None or c[2] is None or not (0.01 <= c[1] < c[2] <= 0.99):
                    continue
                pm = p_yes(vol, S, m, var)
                if pm is None:
                    continue
                nxt = [] if hourly else [x for x in cs[j + 1:] if x[0] <= min(close, tau + 300)]
                trL = min([x[8] for x in nxt if x[8] is not None], default=None); trH = max([x[9] for x in nxt if x[9] is not None], default=None)
                rows.append(dict(series=series, day=dt.datetime.fromtimestamp(close, dt.timezone.utc), L=L, bid=c[1], ask=c[2], mid=(c[1] + c[2]) / 2,
                                 y=1 if m["result"] == "yes" else 0, emp=float(pm), trL=trL, trH=trH, vol=c[3] or 0.0, hourly=hourly))
    return rows


def pnl(r, p, th, mode):
    b, a, y = r["bid"], r["ask"], r["y"]
    if mode == "taker":
        if p - a >= th:
            return y - a - fee(a)
        if b - p >= th:
            return (1 - y) - (1 - b) - fee(b)
        return None
    if p - b >= th:
        return (y - b) if (r["trL"] is not None and r["trL"] <= b) else None
    if a - p >= th:
        return ((1 - y) - (1 - a)) if (r["trH"] is not None and r["trH"] >= a) else None
    return None


def fav_p(r, x):
    return 1.0 if r["mid"] >= 1 - x else 0.0 if r["mid"] <= x else None


def stats(pairs):
    if len(pairs) < 10:
        return dict(n=len(pairs))
    by = {}
    for d, v in pairs:
        by[d] = by.get(d, 0.0) + 100 * v
    v = np.array(list(by.values())); per = np.array([x for _, x in pairs])
    return dict(n=len(pairs), events=len(v), cents=float(100 * per.mean()), t=float(v.mean() / v.std(ddof=1) * np.sqrt(len(v))) if len(v) > 5 and v.std() > 0 else None,
                win=float(100 * (per > 0).mean()), total_usd_100=float(v.sum()))


def calib(rows):
    bins = [0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 0.95, 1.01]
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        s = [r for r in rows if lo <= r["mid"] < hi]
        if len(s) >= 20:
            out.append(dict(mid=f"{lo:.2f}-{hi:.2f}", n=len(s), avg_mid=round(float(np.mean([r["mid"] for r in s])), 3), yes_rate=round(float(np.mean([r["y"] for r in s])), 3),
                            buy_yes_at_ask_after_fee=round(100 * float(np.mean([r["y"] - r["ask"] - fee(r["ask"]) for r in s])), 2)))
    return out


if __name__ == "__main__":
    res = {}
    for series in ASSET:
        allrows = load(series)
        for sub in ("daily", "hourly"):
            rows = [r for r in allrows if r["hourly"] == (sub == "hourly")]
            if not rows:
                continue
            name = series + ("" if sub == "daily" else "_hourly_events")
            tr = [r for r in rows if r["day"] < SPLIT]; te = [r for r in rows if r["day"] >= SPLIT]
            leads = [60] if sub == "hourly" else LEADS.get(series, DEFAULT_LEADS)
            k = dict(events=len({r["day"] for r in rows}), quotes=len(rows), train=len(tr), test=len(te),
                     median_spread_cents=float(100 * np.median([r["ask"] - r["bid"] for r in rows])), median_minute_volume=float(np.median([r["vol"] for r in rows])),
                     brier_by_lead={L: dict(market=float(np.mean([(r["mid"] - r["y"]) ** 2 for r in rows if r["L"] == L])), model=float(np.mean([(r["emp"] - r["y"]) ** 2 for r in rows if r["L"] == L]))) for L in leads if any(r["L"] == L for r in rows)},
                     calibration_all=calib(rows))
            grid = []
            for L in leads:
                for mode in ("taker", "join"):
                    for x in (0.05, 0.1, 0.2, 0.3):
                        s = stats([(r["day"], v) for r in tr if r["L"] == L and (fp := fav_p(r, x)) is not None and (v := pnl(r, fp, 0.0, mode)) is not None]); grid.append(("fav", L, mode, x, s))
                    for th in (0.04, 0.08, 0.12, 0.2):
                        s = stats([(r["day"], v) for r in tr if r["L"] == L and (v := pnl(r, r["emp"], th, mode)) is not None]); grid.append(("model", L, mode, th, s))
            grid = [g for g in grid if g[4].get("n", 0) >= 30 and g[4].get("t") is not None]
            grid.sort(key=lambda g: -g[4]["t"])
            k["train_top"] = [dict(rule=g[0], lead_min=g[1], mode=g[2], param=g[3], **g[4]) for g in grid[:6]]
            for rule in ("fav", "model"):
                for mode in ("taker", "join"):
                    g = next((g for g in grid if g[0] == rule and g[2] == mode), None)
                    if g:
                        fn = (lambda r, g=g, mode=mode: pnl(r, fav_p(r, g[3]), 0.0, mode) if fav_p(r, g[3]) is not None else None) if rule == "fav" else (lambda r, g=g, mode=mode: pnl(r, r["emp"], g[3], mode))
                        k[f"test_{rule}_{mode}"] = dict(lead_min=g[1], param=g[3], train=g[4], test=stats([(r["day"], v) for r in te if r["L"] == g[1] and (v := fn(r)) is not None]))
            res[name] = k
    print(json.dumps(res, indent=1, default=str))
    json.dump(res, open(os.path.join(HERE, "results_kalshi_recent.json"), "w"), indent=1, default=str)

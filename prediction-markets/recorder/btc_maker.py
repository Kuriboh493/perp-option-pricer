"""Shared logic for the Kalshi BTC maker strategy: as-of lookups (no lookahead), the Deribit-implied fair value of a Kalshi
"Bitcoin above $K at 5pm ET" contract at any timestamp, and the resting-bid fill replay used by the recorder.

Fair value follows ../kalshi-btc/tail_test.py: the smile of the first Deribit expiry after the Kalshi close, expressed in
standardised moneyness, rescaled to the remaining Kalshi window with the hour-of-week variance clock, and turned into the
risk-neutral probability of finishing above the strike. Every input is taken as of the measurement time."""
import bisect, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "perps", "backtest"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "common"))
from model import black  # noqa: E402

HOUR_S = 3600
try:                                                       # hour-of-week variance seasonality fitted on 2022-2025 data
    from volfc import SEAS as _SEAS
    SEAS = [float(x) for x in _SEAS]
except Exception:                                          # data file missing: fall back to flat time
    SEAS = [1.0] * 48


def bucket(hour_start_s):
    """Seasonal bucket for the clock hour starting at hour_start_s (UTC): hour of day, +24 on Saturday/Sunday."""
    import datetime as dt
    d = dt.datetime.fromtimestamp(hour_start_s, dt.timezone.utc)
    return d.hour + (24 if d.weekday() >= 5 else 0)


def variance_clock(a, b, seas=None):
    """Seasonal variance units between timestamps a < b (seconds), with partial hours weighted by overlap."""
    seas = seas or SEAS
    if b <= a:
        return 0.0
    total, t = 0.0, float(a)
    while t < b:
        h0 = math.floor(t / HOUR_S) * HOUR_S
        end = min(b, h0 + HOUR_S)
        total += (end - t) / HOUR_S * seas[bucket(h0)]
        t = end
    return total


# ---------- as-of lookups ----------
class Series:
    """Time series with as-of lookup. strict=True returns the last point strictly before t (for 'immediately before a fill')."""

    def __init__(self, ts, values):
        order = sorted(range(len(ts)), key=lambda i: ts[i])
        self.ts = [float(ts[i]) for i in order]
        self.v = [values[i] for i in order]

    def asof(self, t, max_age=None, strict=False):
        i = (bisect.bisect_left(self.ts, t) if strict else bisect.bisect_right(self.ts, t)) - 1
        if i < 0:
            return None
        if max_age is not None and t - self.ts[i] > max_age:
            return None
        return self.v[i]

    def asof_ts(self, t, strict=False):
        i = (bisect.bisect_left(self.ts, t) if strict else bisect.bisect_right(self.ts, t)) - 1
        return self.ts[i] if i >= 0 else None


# ---------- Deribit smile and fair value ----------
def fit_smile(strikes, ivs, forward, expiry_s, ts_s, index_price=None):
    """Quadratic smile in standardised moneyness z = ln(K/F)/(s0*sqrt(T)), from Deribit mark IVs (in vol units, e.g. 0.48)."""
    K = np.asarray(strikes, float); iv = np.asarray(ivs, float)
    ok = np.isfinite(K) & np.isfinite(iv) & (iv > 0.01)
    K, iv = K[ok], iv[ok]
    if len(K) < 5 or forward is None or forward <= 0:
        return None
    T = (expiry_s - ts_s) / (365 * 86400)
    if T <= 0:
        return None
    order = np.argsort(K); K, iv = K[order], iv[order]
    z = np.log(K / forward)
    s0 = float(np.interp(0.0, z, iv)) if z.min() < 0 < z.max() else float(iv[np.argmin(np.abs(z))])
    zs = z / (s0 * math.sqrt(T))
    keep = np.abs(zs) <= 3
    if keep.sum() < 5:
        return None
    coef = np.polyfit(zs[keep], iv[keep], 2)
    return dict(s0=s0, coef=[float(c) for c in coef], expiry=float(expiry_s), ts=float(ts_s), forward=float(forward),
                index=float(index_price) if index_price else None)


def prob_above(smile, spot, strike, t_s, close_s, seas=None):
    """Risk-neutral P(BTC > strike at the Kalshi close), as of t_s. Uses only the smile, spot and clock at t_s."""
    if smile is None or spot is None or spot <= 0:
        return None
    if t_s >= close_s:
        return 1.0 if spot > strike else 0.0
    T_D = (smile["expiry"] - t_s) / (365 * 86400)
    if T_D <= 0:
        return None
    w = variance_clock(t_s, close_s, seas) / max(variance_clock(t_s, smile["expiry"], seas), 1e-12)
    V = smile["s0"] ** 2 * T_D * w                                    # ATM total variance over the remaining Kalshi window
    if V <= 1e-12:
        return 1.0 if spot > strike else 0.0
    F = float(spot)                                                   # a few hours of drift is negligible

    def call(k):
        zk = math.log(k / F) / math.sqrt(V)
        ivk = max(float(np.polyval(smile["coef"], max(-3.0, min(3.0, zk)))), 0.05)
        return float(black(F, k, (ivk / smile["s0"]) ** 2 * V, 1))
    h = 0.001 * strike
    p = (call(strike - h) - call(strike + h)) / (2 * h)
    return min(max(p, 0.0), 1.0)


def side_value(p_above, side):
    """Value of one contract on our side: YES pays if above, NO pays if not."""
    if p_above is None:
        return None
    return p_above if side == "yes" else 1.0 - p_above


def side_quote(yes_bid, yes_ask, side):
    """(bid, ask, mid) of our side of the book from the YES quote."""
    if yes_bid is None or yes_ask is None:
        return None, None, None
    if side == "yes":
        return yes_bid, yes_ask, (yes_bid + yes_ask) / 2
    return 1 - yes_ask, 1 - yes_bid, 1 - (yes_bid + yes_ask) / 2


# ---------- fill replay ----------
def favourite_sell_trades(trades, side, price, placed, life_s):
    """Trades that hit a resting bid on `side` at `price`: the taker bought the other side, at a side-price <= our bid.
    trades: iterable of dicts with ts (float seconds), taker_side, yes_price, no_price, count, trade_id."""
    out = []
    for t in trades:
        if t["ts"] < placed or t["ts"] > placed + life_s:
            continue
        if t["taker_side"] == side:
            continue
        px = t["yes_price"] if side == "yes" else t["no_price"]
        if px <= price + 1e-9:
            out.append(dict(ts=t["ts"], qty=float(t["count"]), px=px, trade_id=t.get("trade_id"), trade_size=float(t["count"])))
    return sorted(out, key=lambda x: x["ts"])


def replay_fills(hits, price, queue, size, through=False):
    """Queue model: each qualifying trade first consumes the displayed size that was ahead of us, then fills us.
    through=False is the recorder's rule (unchanged). through=True also fills us fully the first time a trade prints
    strictly below our price, since price-time priority means our level was cleared.
    Returns (fill portions [{ts, qty, trade_id, trade_size}], remaining, queue_left)."""
    q, rem, portions = float(queue), float(size), []
    for h in hits:
        if rem <= 1e-9:
            break
        if through and h["px"] < price - 1e-9:
            portions.append(dict(ts=h["ts"], qty=rem, trade_id=h["trade_id"], trade_size=h["trade_size"])); rem = 0.0; q = 0.0
            break
        qty = h["qty"]
        take = min(qty, q); q -= take; qty -= take
        if qty > 0:
            f = min(qty, rem); rem -= f
            portions.append(dict(ts=h["ts"], qty=f, trade_id=h["trade_id"], trade_size=h["trade_size"]))
    return portions, rem, q


def cluster_mean_ci(values, clusters, z=1.96):
    """Mean with a cluster-robust (by day) 95% interval."""
    v = np.asarray(values, float); c = np.asarray(clusters)
    ok = np.isfinite(v)
    v, c = v[ok], c[ok]
    if len(v) == 0:
        return None, None, None, 0
    m = float(v.mean())
    groups = {}
    for x, g in zip(v - m, c):
        groups[g] = groups.get(g, 0.0) + x
    G = len(groups)
    if G < 2:
        return m, None, None, len(v)
    se = math.sqrt(sum(s * s for s in groups.values()) * G / (G - 1)) / len(v)
    return m, m - z * se, m + z * se, len(v)

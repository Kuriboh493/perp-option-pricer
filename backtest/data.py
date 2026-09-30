"""Loaders that turn the cached Deribit files into arrays the tests use."""
import json, os, datetime as dt
import numpy as np
from model import black

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UTC = dt.timezone.utc
YEAR_MS = 365 * 24 * 3600 * 1000.0
HOUR = 3600 * 1000


def ms(d, hour=0, minute=0):
    return int(dt.datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC).timestamp() * 1000)


def load_hourly():
    """Dicts keyed by hour timestamp: perp price, spot index, and funding paid by longs over the hour ending then."""
    rows = json.load(open(os.path.join(DATA, "hourly.json")))
    perp = {r[0] + HOUR: r[1] for r in rows}      # chart bars are stamped at their open; use the close
    index = {r[0]: r[2] for r in rows}
    fund = {r[0]: r[3] for r in rows}
    return perp, index, fund


def load_delivery():
    raw = json.load(open(os.path.join(DATA, "delivery.json")))
    return {dt.datetime.strptime(k, "%Y-%m-%d").date(): v for k, v in raw.items()}


def implied_forward(price_btc, iv, K, T, cp, idx):
    """Forward that Deribit used to turn a BTC-quoted trade price into its reported implied vol."""
    lo, hi = idx * 0.8, idx * 1.25
    for _ in range(40):
        mid = (lo + hi) / 2
        up = cp * (black(mid, K, iv * iv * T, cp) / mid - price_btc) < 0   # call value/F rises with F, put falls
        lo, hi = np.where(up, mid, lo), np.where(up, hi, mid)
    return (lo + hi) / 2


def snapshot(d):
    """One implied-vol surface from trades 08:05-10:05 UTC on day d: list of expiries with forward, T, strikes, vols."""
    path = os.path.join(DATA, "trades", f"{d}.json")
    if not os.path.exists(path):
        return None
    rows = [r for r in json.load(open(path)) if r[3]]
    if len(rows) < 20:
        return None
    ts = np.array([r[0] for r in rows], float)
    price = np.array([r[2] for r in rows]); iv = np.array([r[3] for r in rows]) / 100; idx = np.array([r[4] for r in rows])
    parts = [r[1].split("-") for r in rows]
    exp = np.array([ms(dt.datetime.strptime(p[1], "%d%b%y").date(), 8) for p in parts], float)
    K = np.array([float(p[2]) for p in parts]); cp = np.array([1.0 if p[3] == "C" else -1.0 for p in parts])
    T = (exp - ts) / YEAR_MS
    ok = (T > 0) & (iv > 0.05) & (iv < 4)
    ts, price, iv, idx, exp, K, cp, T = (a[ok] for a in (ts, price, iv, idx, exp, K, cp, T))
    ratio = implied_forward(price, iv, K, T, cp, idx) / idx
    t_ref, idx_ref, out = ms(d, 9, 5), float(np.median(idx)), []
    for e in np.unique(exp):
        sel = exp == e
        atm = sel & (np.abs(np.log(K / idx)) < 0.05) & (price >= 0.002)
        if atm.sum() < 3:
            continue
        F, Te = idx_ref * float(np.median(ratio[atm])), (e - t_ref) / YEAR_MS
        ks = np.unique(K[sel])
        vols = np.array([np.median(iv[sel & (K == k)]) for k in ks])
        out.append(dict(expiry=int(e), F=F, T=Te, K=ks, iv=vols))
    return dict(date=d, index=idx_ref, expiries=out)

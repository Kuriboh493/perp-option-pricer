"""Test 3: check two structural assumptions against data.
(a) Perp fair value: the model says funding settles near the carry rate and the perp trades within a basis point of spot.
(b) Market hours: the model says a closed hour carries a fixed fraction of an open hour's variance (default 12%)."""
import json, os, urllib.request, datetime as dt
import numpy as np
from data import load_hourly, DATA

perp, index, fund = load_hourly()
ts = sorted(t for t in fund if t in perp and t >= 1672531200000)
f = np.array([fund[t] for t in ts]); basis = np.array([perp[t] / index[t] - 1 for t in ts])
res = dict(funding=dict(hours=len(ts), mean_annualised_pct=float(100 * f.mean() * 8760), median_annualised_pct=float(100 * np.median(f) * 8760),
                        share_of_hours_negative_pct=float(100 * (f < 0).mean()), p5_p95_annualised_pct=[float(100 * 8760 * np.percentile(f, q)) for q in (5, 95)],
                        mean_basis_bp=float(1e4 * basis.mean()), basis_std_bp=float(1e4 * basis.std()),
                        by_year={y: float(100 * 8760 * np.mean([fund[t] for t in ts if dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).year == y])) for y in (2023, 2024, 2025, 2026)}))


def yahoo(sym, interval, rng):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={interval}&range={rng}&includePrePost=false"
    r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    return np.array(r["timestamp"]), np.array(q["open"], float), np.array(q["close"], float)


clock = {}
for sym in ("SPY", "QQQ", "NVDA", "AAPL", "TSLA"):
    try:
        t, o, c = yahoo(sym, "1d", "10y")
    except Exception as e:
        clock[sym] = f"download failed: {e}"; continue
    ok = np.isfinite(o) & np.isfinite(c); t, o, c = t[ok], o[ok], c[ok]
    intraday = np.log(c / o) ** 2
    gap = np.log(o[1:] / c[:-1]) ** 2
    days = np.round((t[1:] - t[:-1]) / 86400)
    open_var = intraday.mean() / 6.5
    night, wknd = days == 1, days == 3
    clock[sym] = dict(days=len(t), weeknight_closed_hour_pct_of_open_hour=float(100 * gap[night].mean() / 17.5 / open_var),
                      weekend_closed_hour_pct_of_open_hour=float(100 * gap[wknd].mean() / 65.5 / open_var),
                      all_closed_hours_pct=float(100 * gap.sum() / (days * 24 - 6.5).sum() / open_var),
                      share_of_total_variance_while_closed_pct=float(100 * gap.sum() / (gap.sum() + intraday.sum())))
try:
    t, o, c = yahoo("GC=F", "1h", "730d")
    ok = np.isfinite(o) & np.isfinite(c); t, o, c = t[ok], o[ok], c[ok]
    r2 = np.log(c[1:] / c[:-1]) ** 2; gap_h = (t[1:] - t[:-1]) / 3600
    inside, wk = gap_h <= 1.01, gap_h > 40
    open_var = r2[inside].mean()
    clock["gold_futures"] = dict(hourly_bars=len(t), weekend_closed_hour_pct_of_open_hour=float(100 * r2[wk].sum() / (gap_h[wk] - 1).sum() / open_var), weekends=int(wk.sum()))
except Exception as e:
    clock["gold_futures"] = f"download failed: {e}"
res["market_hours"] = clock
print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(DATA, "..", "results_checks.json"), "w"), indent=1)

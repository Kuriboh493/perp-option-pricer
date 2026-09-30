"""Short-horizon BTC volatility forecast: hour-of-day x weekday/weekend seasonality times a HAR level.
Fitted only on hourly Deribit index data from 2022-01-01 to 2025-02-28, before either test period starts."""
import os, sys, datetime as dt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backtest"))
from data import load_hourly, ms, HOUR

FIT_FROM, FIT_TO = ms(dt.date(2022, 1, 1)), ms(dt.date(2025, 3, 1))
_, index, _ = load_hourly()
TS = np.array(sorted(index), dtype=np.int64)
PX = np.array([index[t] for t in TS])
R2 = np.r_[np.nan, np.diff(np.log(PX)) ** 2]          # R2[i] = squared return over the hour ending at TS[i]
POS = {int(t): i for i, t in enumerate(TS)}


def bucket(t_ms):
    """Hour of day (0-23) plus 24 on Saturday/Sunday UTC, for the hour ending at t_ms."""
    d = dt.datetime.fromtimestamp((t_ms - HOUR) / 1000, dt.timezone.utc)
    return d.hour + (24 if d.weekday() >= 5 else 0)


BUCKET = np.array([bucket(int(t)) for t in TS])
fit = (TS >= FIT_FROM) & (TS < FIT_TO) & np.isfinite(R2)
SEAS = np.array([np.mean(R2[fit & (BUCKET == b)]) for b in range(48)]) / np.mean(R2[fit])
DES = R2 / SEAS[BUCKET]                                 # deseasonalised squared returns
CS = np.r_[0, np.nancumsum(np.nan_to_num(DES))]


def _mean_des(i, n):
    return (CS[i + 1] - CS[i + 1 - n]) / n              # mean over the n hours ending at TS[i]


def _features(i):
    return np.array([1.0, _mean_des(i, 24), _mean_des(i, 168), _mean_des(i, 720)])


def _fit_har(H=6):
    X, y = [], []
    for i in np.where(fit)[0][::3]:
        if i < 721 or i + H >= len(TS):
            continue
        X.append(_features(i)); y.append(np.mean(DES[i + 1:i + H + 1]))
    return np.linalg.lstsq(np.array(X), np.array(y), rcond=None)[0]


BETA = _fit_har()

# Rolling bias correction: realised / forecast variance over the previous 90 days of 1-hour forecasts (past data only).
_LEVEL = np.array([float(_features(i) @ BETA) if i >= 720 else np.nan for i in range(len(TS))])
_F1 = np.r_[np.nan, _LEVEL[:-1] * SEAS[BUCKET[1:]]]      # forecast made an hour earlier for the hour ending at TS[i]
_ok = np.isfinite(_F1) & np.isfinite(R2)
_CR, _CF = np.r_[0, np.cumsum(np.where(_ok, R2, 0))], np.r_[0, np.cumsum(np.where(_ok, _F1, 0))]
WINDOW = 90 * 24


def bias(i):
    lo = max(0, i + 1 - WINDOW)
    f = _CF[i + 1] - _CF[lo]
    return (_CR[i + 1] - _CR[lo]) / f if f > 0 else 1.0


def forecast_var(t_ms, hours, adjust=True):
    """Forecast variance of the log return from t_ms to t_ms + hours (not annualised). None if data is missing."""
    i = POS.get(int(t_ms))
    if i is None or i < 721 + WINDOW:
        return None
    level = max(float(_features(i) @ BETA), 0.1 * _mean_des(i, 720)) * (bias(i) if adjust else 1.0)
    return level * sum(SEAS[bucket(int(t_ms) + (k + 1) * HOUR)] for k in range(int(hours)))


def forecast_vol(t_ms, hours):
    v = forecast_var(t_ms, hours)
    return None if v is None else float(np.sqrt(v * 8760 / hours))


def standardized_returns(hours):
    """Realised hours-ahead returns divided by their forecast sd, over the fitting period (for empirical tails)."""
    z = []
    for i in np.where(fit)[0][::hours]:
        if i < 721 or i + hours >= len(TS):
            continue
        v = forecast_var(int(TS[i]), hours, adjust=False)
        if v is None:
            continue
        z.append(np.log(PX[i + hours] / PX[i]) / np.sqrt(v))
    return np.sort(np.array(z))


if __name__ == "__main__":
    print("HAR weights (const, 1d, 7d, 30d):", BETA.round(3))
    print("seasonal factor by UTC hour, weekday:", SEAS[:24].round(2))
    print("seasonal factor by UTC hour, weekend:", SEAS[24:].round(2))
    # out-of-sample check from 2025-03 on: forecast vs naive trailing 24h vol, 6h horizon
    e_f, e_n = [], []
    for i in range(POS[ms(dt.date(2025, 3, 1))], len(TS) - 7, 6):
        real = np.sum(R2[i + 1:i + 7])
        f = forecast_var(int(TS[i]), 6); n = np.mean(R2[i - 23:i + 1]) * 6
        e_f.append((np.log(f) - np.log(real + 1e-12))); e_n.append((np.log(n) - np.log(real + 1e-12)))
    for name, e in (("forecast", np.array(e_f)), ("trailing 24h", np.array(e_n))):
        print(f"{name}: mean log error {e.mean():.3f}, sd {e.std():.3f}")
    z = standardized_returns(6)
    print("standardised 6h returns: sd", z.std().round(3), "kurtosis", (np.mean(z ** 4) / z.var() ** 2).round(2), "n", len(z))

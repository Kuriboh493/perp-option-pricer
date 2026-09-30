"""Asset-generic short-horizon volatility forecast: hour-of-day x weekday/weekend seasonality times a HAR level, fitted on
hourly data before FIT_TO. Sub-hour horizons scale the current hour's seasonal variance by minutes/60."""
import json, os, datetime as dt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HOUR = 3600 * 1000


class VolModel:
    def __init__(self, asset, fit_to=dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc), always_open=True):
        rows = json.load(open(os.path.join(HERE, "data", f"spot_{asset}.json")))
        self.ts = np.array([r[0] for r in rows], dtype=np.int64); self.px = np.array([r[1] for r in rows], float)
        self.pos = {int(t): i for i, t in enumerate(self.ts)}
        self.r2 = np.r_[np.nan, np.diff(np.log(self.px)) ** 2]
        self.always_open = always_open
        self.bucket = np.array([self._bucket(int(t)) for t in self.ts])
        fit = (self.ts < int(fit_to.timestamp() * 1000)) & np.isfinite(self.r2)
        nb = 48 if always_open else 24
        self.seas = np.array([np.mean(self.r2[fit & (self.bucket == b)]) if (fit & (self.bucket == b)).any() else np.nan for b in range(nb)])
        self.seas = np.where(np.isfinite(self.seas), self.seas, np.nanmean(self.seas)) / np.nanmean(self.r2[fit])
        des = self.r2 / self.seas[self.bucket]
        self.cs = np.r_[0, np.cumsum(np.nan_to_num(des))]
        X, y = [], []
        for i in np.where(fit)[0][::3]:
            if i < 721 or i + 6 >= len(self.ts):
                continue
            X.append(self._feat(i)); y.append(np.mean(des[i + 1:i + 7]))
        self.beta = np.linalg.lstsq(np.array(X), np.array(y), rcond=None)[0]
        z = []
        for i in np.where(fit)[0][::6]:
            if i < 721 or i + 6 >= len(self.ts):
                continue
            v = self.var_hours(int(self.ts[i]), 6)
            if v:
                z.append(np.log(self.px[i + 6] / self.px[i]) / np.sqrt(v))
        self.z = np.sort(np.array(z))

    def _bucket(self, t_ms):
        d = dt.datetime.fromtimestamp((t_ms - HOUR) / 1000, dt.timezone.utc)
        return d.hour + (24 if (self.always_open and d.weekday() >= 5) else 0)

    def _mean(self, i, n):
        return (self.cs[i + 1] - self.cs[max(0, i + 1 - n)]) / n

    def _feat(self, i):
        return np.array([1.0, self._mean(i, 24), self._mean(i, 168), self._mean(i, 720)])

    def level(self, t_ms):
        """Deseasonalised hourly variance level from data at or before t_ms."""
        i = self.pos.get(int(t_ms))
        if i is None:
            j = np.searchsorted(self.ts, t_ms, side="right") - 1
            if j < 0:
                return None
            i = int(j)
        if i < 721:
            return None
        return max(float(self._feat(i) @ self.beta), 0.1 * self._mean(i, 720))

    def var_hours(self, t_ms, hours):
        lv = self.level(t_ms)
        return None if lv is None else lv * sum(self.seas[self._bucket(int(t_ms) + (k + 1) * HOUR)] for k in range(int(hours)))

    def var_minutes(self, t_ms, minutes):
        """Variance of the log return over the next `minutes` from t_ms (the hour containing t_ms sets the seasonal factor)."""
        lv = self.level(t_ms - (t_ms % HOUR))
        if lv is None:
            return None
        end = t_ms + minutes * 60000
        return lv * self.seas[self._bucket(end)] * minutes / 60

    def prob_above(self, spot, K, var, empirical=True):
        """P(price at horizon > K) for a driftless lognormal (normal or empirical standardised tails)."""
        sd = np.sqrt(var); x = np.log(np.asarray(K, float) / spot)
        if empirical:
            return 1 - np.searchsorted(self.z, x / sd) / len(self.z)
        from scipy.special import ndtr
        return 1 - ndtr(x / sd + sd / 2)


if __name__ == "__main__":
    for a in ("ETH", "SOL", "XRP", "BTC"):
        m = VolModel(a)
        print(a, "HAR", m.beta.round(3), "peak/trough seasonal", m.seas.max().round(2), m.seas.min().round(2), "z sd", m.z.std().round(3), "n", len(m.z))

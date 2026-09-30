"""Test 2: calibrate the model to each day's Deribit option surface, then use those parameters to predict
the next day's implied vols. Compared with a flat Black vol and with carrying yesterday's vol per contract."""
import json, os, datetime as dt
import numpy as np
from scipy.optimize import least_squares
from scipy.stats import norm
from model import bates, black, cf_grid, implied_vol, BTC_PRESET
from data import snapshot, DATA

MU_J, D_J = BTC_PRESET["muJ"], BTC_PRESET["dJ"]   # jump size is held at the preset; jump frequency is calibrated
LO = np.array([0.05, 0.05, 0.1, 0.05, -0.95, 0.0])
HI = np.array([3.0, 3.0, 20.0, 6.0, 0.95, 50.0])
PRESET_X = np.array([0.5, 0.55, BTC_PRESET["kv"], BTC_PRESET["sv"], BTC_PRESET["rho"], BTC_PRESET["lam"]])


def points(snap):
    """Liquid part of the surface: 2 to 120 days, within 1.5 standard deviations of the forward."""
    rows = []
    for e in snap["expiries"]:
        if not (2 / 365 <= e["T"] <= 120 / 365):
            continue
        z = np.log(e["K"] / e["F"]) / (e["iv"] * np.sqrt(e["T"]))
        for K, iv in zip(e["K"][np.abs(z) <= 1.5], e["iv"][np.abs(z) <= 1.5]):
            rows.append((e["expiry"], e["F"], e["T"], K, iv))
    if len(rows) < 15 or len({r[0] for r in rows}) < 3:
        return None
    exp, F, T, K, iv = map(np.array, zip(*rows))
    side = np.where(K >= F, 1.0, -1.0)
    d1 = (np.log(F / K) + iv * iv * T / 2) / (iv * np.sqrt(T))
    return dict(exp=exp, F=F, T=T, K=K, iv=iv, side=side, px=black(F, K, iv * iv * T, side), vega=F * norm.pdf(d1) * np.sqrt(T))


def model_prices(x, p):
    m = dict(v0=x[0] ** 2, th=x[1] ** 2, kv=x[2], sv=x[3], rho=x[4], lam=x[5], muJ=MU_J, dJ=D_J)
    out = np.empty(len(p["K"]))
    for e in np.unique(p["exp"]):
        s = p["exp"] == e
        T = p["T"][s][0]
        out[s] = bates(p["F"][s], p["K"][s], p["side"][s], T, T, m)
    return out


def model_iv(x, p):
    px = model_prices(x, p)
    iv = implied_vol(px, p["F"], p["K"], p["T"], p["side"])
    return np.where(np.isfinite(iv), iv, p["iv"] + (px - p["px"]) / p["vega"])


def fit(p, x0, free):
    free = np.array(free)
    def resid(z):
        x = x0.copy(); x[free] = z
        return (model_prices(x, p) - p["px"]) / p["vega"]
    r = least_squares(resid, np.clip(x0[free], LO[free] + 1e-6, HI[free] - 1e-6), bounds=(LO[free], HI[free]), max_nfev=80, diff_step=1e-3)
    x = x0.copy(); x[free] = r.x
    return x


def rmse(e):
    e = np.asarray(e)
    return float(100 * np.sqrt(np.mean(e * e))) if len(e) else float("nan")


if __name__ == "__main__":
    ALL, HESTON, LEVEL = [0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4], [0, 1]
    d, days = dt.date(2025, 8, 25), []
    warm = {"bates": PRESET_X.copy(), "heston": np.append(PRESET_X[:5], 0.0), "preset_shape": PRESET_X.copy()}
    while d <= dt.date(2026, 9, 29):
        snap = snapshot(d)
        p = points(snap) if snap else None
        if p:
            rec = dict(date=d, p=p, x={})
            for name, free in (("bates", ALL), ("heston", HESTON), ("preset_shape", LEVEL)):
                x0 = warm[name].copy()
                if name == "preset_shape":
                    x0[2:] = PRESET_X[2:]
                rec["x"][name] = warm[name] = fit(p, x0, free)
            days.append(rec)
            if len(days) % 50 == 0:
                print(len(days), "days calibrated", flush=True)
        d += dt.timedelta(days=1)

    ins = {k: [] for k in ("bates", "heston", "preset_shape", "flat")}
    oos = {k: [] for k in ("bates", "heston", "preset_shape", "flat")}
    common = {k: [] for k in ("bates", "sticky", "flat")}
    buckets = {b: {k: [] for k in ("bates", "flat")} for b in ("under_2_weeks", "over_2_weeks", "near_the_money", "wings")}
    for rec in days:
        for k in ("bates", "heston", "preset_shape"):
            ins[k] += list(model_iv(rec["x"][k], rec["p"]) - rec["p"]["iv"])
        ins["flat"] += list(rec["p"]["iv"].mean() - rec["p"]["iv"])
    pairs = 0
    for a, b in zip(days[:-1], days[1:]):
        if (b["date"] - a["date"]).days != 1:
            continue
        pairs += 1
        p = b["p"]
        err = {k: model_iv(a["x"][k], p) - p["iv"] for k in ("bates", "heston", "preset_shape")}
        err["flat"] = a["p"]["iv"].mean() - p["iv"]
        for k in oos:
            oos[k] += list(err[k])
        prev = {(e, k): v for e, k, v in zip(a["p"]["exp"], a["p"]["K"], a["p"]["iv"])}
        has = np.array([(e, k) in prev for e, k in zip(p["exp"], p["K"])])
        if has.any():
            common["sticky"] += list(np.array([prev[(e, k)] for e, k in zip(p["exp"][has], p["K"][has])]) - p["iv"][has])
            common["bates"] += list(err["bates"][has]); common["flat"] += list(err["flat"][has])
        z = np.abs(np.log(p["K"] / p["F"]) / (p["iv"] * np.sqrt(p["T"])))
        for name, sel in (("under_2_weeks", p["T"] < 14 / 365), ("over_2_weeks", p["T"] >= 14 / 365), ("near_the_money", z < 0.5), ("wings", z >= 0.5)):
            for k in ("bates", "flat"):
                buckets[name][k] += list(err[k][sel])
    X = np.array([r["x"]["bates"] for r in days])
    res = dict(
        days=len(days), day_pairs=pairs, points_per_day=float(np.mean([len(r["p"]["K"]) for r in days])),
        in_sample_rmse_vol_pts={k: rmse(v) for k, v in ins.items()},
        next_day_rmse_vol_pts={k: rmse(v) for k, v in oos.items()},
        next_day_rmse_same_contracts={k: rmse(v) for k, v in common.items()}, same_contract_points=len(common["sticky"]),
        next_day_rmse_by_bucket={b: {k: rmse(v) for k, v in d_.items()} for b, d_ in buckets.items()},
        calibrated_median=dict(zip(["spot_vol", "long_run_vol", "reversion", "vol_of_vol", "correlation", "jumps_per_year"], np.median(X, 0).round(3).tolist())),
        calibrated_iqr=dict(zip(["spot_vol", "long_run_vol", "reversion", "vol_of_vol", "correlation", "jumps_per_year"],
                                [[round(float(a), 3), round(float(b), 3)] for a, b in zip(np.percentile(X, 25, 0), np.percentile(X, 75, 0))])),
        preset=dict(reversion=BTC_PRESET["kv"], vol_of_vol=BTC_PRESET["sv"], correlation=BTC_PRESET["rho"], jumps_per_year=BTC_PRESET["lam"]),
    )
    print(json.dumps(res, indent=1))
    res["daily_params"] = [[str(r["date"])] + r["x"]["bates"].round(4).tolist() for r in days]
    json.dump(res, open(os.path.join(DATA, "..", "results_calibration.json"), "w"), indent=1)

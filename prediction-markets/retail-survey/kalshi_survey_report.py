"""Report on data/kalshi_segments.parquet: where takers lose and makers gain, by category, price, time to close, series and year."""
import json, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
seg = pd.read_parquet(os.path.join(HERE, "data", "kalshi_segments.parquet"))
seg = seg[seg["ttc"] != "after_close"]
MIN_D = float(sys.argv[1]) if len(sys.argv) > 1 else 2e5     # minimum dollars for a row to be reported


def table(df, keys, min_d=MIN_D):
    g = df.groupby(keys, observed=True)[["trades", "contracts", "dollars", "taker_pnl", "maker_gross", "fees"]].sum().reset_index()
    g = g[g["dollars"] >= min_d].copy()
    g["taker_ret_pct"] = 100 * g["taker_pnl"] / g["dollars"]              # taker P&L per dollar staked, after fees
    g["maker_cents_per_contract"] = 100 * g["maker_gross"] / g["contracts"]
    g["maker_gross_usd"] = g["maker_gross"]
    return g.sort_values("dollars", ascending=False)


def rows(g, cols):
    return [{c: (round(float(r[c]), 2) if isinstance(r[c], (float, np.floating)) else (int(r[c]) if isinstance(r[c], (np.integer,)) else str(r[c]))) for c in cols} for _, r in g.iterrows()]


C = ["trades", "dollars", "taker_ret_pct", "maker_cents_per_contract", "maker_gross_usd"]
out = dict(
    total=dict(trades=float(seg["trades"].sum()), dollars=float(seg["dollars"].sum()), taker_ret_pct=float(100 * seg["taker_pnl"].sum() / seg["dollars"].sum()),
               maker_gross_usd=float(seg["maker_gross"].sum()), fees_usd=float(seg["fees"].sum())),
    by_year=rows(table(seg, ["year"], 0).sort_values("year"), ["year"] + C),
    by_price=rows(table(seg, ["price_bucket"], 0), ["price_bucket"] + C),
    by_category=rows(table(seg, ["category"]).sort_values("taker_ret_pct"), ["category"] + C),
    by_category_price=rows(table(seg, ["category", "price_bucket"]).sort_values("maker_gross_usd", ascending=False).head(40), ["category", "price_bucket"] + C),
    by_ttc=rows(table(seg, ["ttc"], 0), ["ttc"] + C),
    by_category_ttc=rows(table(seg, ["category", "ttc"]).sort_values("maker_gross_usd", ascending=False).head(30), ["category", "ttc"] + C),
)
# series that made makers the most in 2025, with the same series in 2024 alongside (persistence check)
s25 = table(seg[seg["year"] == 2025], ["series"]).sort_values("maker_gross_usd", ascending=False).head(25)
s24 = table(seg[seg["year"] == 2024], ["series"], 0).set_index("series")
top = []
for _, r in s25.iterrows():
    prev = s24.loc[r["series"]] if r["series"] in s24.index else None
    top.append(dict(series=r["series"], category=seg[seg["series"] == r["series"]]["category"].iloc[0], dollars_2025=round(float(r["dollars"])), taker_ret_2025_pct=round(float(r["taker_ret_pct"]), 2),
                    maker_gross_2025_usd=round(float(r["maker_gross_usd"])), taker_ret_2024_pct=(round(float(prev["taker_ret_pct"]), 2) if prev is not None else None), dollars_2024=(round(float(prev["dollars"])) if prev is not None else None)))
out["top_series_for_makers_2025"] = top
# longshot / favourite split per category and year: is the pattern stable?
lp = seg[seg["price_bucket"].isin(["00-05", "05-10"])]; fp = seg[seg["price_bucket"].isin(["90-95", "95-99"])]
out["longshot_taker_ret_by_category_year"] = rows(table(lp, ["category", "year"], 5e4).sort_values(["category", "year"]), ["category", "year"] + C)
out["favourite_taker_ret_by_category_year"] = rows(table(fp, ["category", "year"], 5e4).sort_values(["category", "year"]), ["category", "year"] + C)
json.dump(out, open(os.path.join(HERE, "results_kalshi_survey.json"), "w"), indent=1)
print(json.dumps({k: out[k] for k in ("total", "by_year", "by_price", "by_category", "by_ttc")}, indent=1))

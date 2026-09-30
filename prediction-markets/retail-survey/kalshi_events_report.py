"""Risk view of the Kalshi retail-loss pools from data/kalshi_events.parquet (event x month x price bucket):
how much of each pool's maker gain comes from its single biggest event, how consistent it is month by month,
and the distribution of per-event maker P&L. Pools are defined by series lists and price buckets."""
import json, os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ev = pd.read_parquet(os.path.join(HERE, "data", "kalshi_events.parquet"))
cat = json.load(open(os.path.join(HERE, "data", "kalshi_series.json")))
ev["category"] = ev["series"].map(lambda s: (cat.get(s) or {}).get("category") or "unknown")
LO = ["00-05", "05-10", "10-20"]
POOLS = {
    "economics_longshots": (ev["category"] == "Economics") & ev["price_bucket"].isin(LO),
    "politics_elections_longshots": ev["category"].isin(["Politics", "Elections"]) & ev["price_bucket"].isin(LO),
    "sports_longshots": (ev["category"] == "Sports") & ev["price_bucket"].isin(LO),
    "sports_longshots_5_20c": (ev["category"] == "Sports") & ev["price_bucket"].isin(["05-10", "10-20"]),
    "crypto_longshots": (ev["category"] == "Crypto") & ev["price_bucket"].isin(LO),
    "weather_all": ev["category"] == "Climate and Weather",
    "weather_65_90c": (ev["category"] == "Climate and Weather") & ev["price_bucket"].isin(["65-80", "80-90"]),
    "mentions_all": ev["category"] == "Mentions",
    "entertainment_longshots": (ev["category"] == "Entertainment") & ev["price_bucket"].isin(LO),
    "exotics_parlays": ev["category"] == "Exotics",
    "sports_main_lines_50_80c": (ev["category"] == "Sports") & ev["price_bucket"].isin(["50-65", "65-80"]),
    "btc_daily_all": ev["series"] == "KXBTCD",
}


def pool_report(df, since="2024-01"):
    df = df[df["month"] >= since]
    by_ev = df.groupby("event")[["dollars", "maker_gross", "contracts"]].sum()
    by_m = df.groupby("month")[["dollars", "maker_gross", "contracts"]].sum().sort_index()
    tot = float(by_ev["maker_gross"].sum())
    top = by_ev["maker_gross"].sort_values(ascending=False)
    worst = by_ev["maker_gross"].sort_values().head(5)
    m = by_m["maker_gross"]
    return dict(events=int(len(by_ev)), months=int(len(by_m)), dollars=float(by_ev["dollars"].sum()), maker_gross=tot,
                maker_cents_per_contract=float(100 * tot / by_ev["contracts"].sum()) if by_ev["contracts"].sum() else None,
                share_from_top_event=float(top.iloc[0] / tot) if tot > 0 and len(top) else None, top_event=str(top.index[0]) if len(top) else None,
                share_from_top5_events=float(top.head(5).sum() / tot) if tot > 0 else None,
                months_positive=f"{int((m > 0).sum())}/{len(m)}", worst_month_usd=float(m.min()) if len(m) else None, median_month_usd=float(m.median()) if len(m) else None,
                monthly_t=float(m.mean() / m.std(ddof=1) * np.sqrt(len(m))) if len(m) > 3 and m.std() > 0 else None,
                worst_events=[(str(k), round(float(v))) for k, v in worst.items()],
                events_with_maker_loss_pct=float(100 * (by_ev["maker_gross"] < 0).mean()),
                monthly=[(k, round(float(v))) for k, v in m.items()])


if __name__ == "__main__":
    out = {name: pool_report(ev[mask]) for name, mask in POOLS.items()}
    json.dump(out, open(os.path.join(HERE, "results_kalshi_pools.json"), "w"), indent=1)
    for name, r in out.items():
        print(f"\n### {name}: events {r['events']}, ${r['dollars']:,.0f} staked, maker gross ${r['maker_gross']:,.0f} ({r['maker_cents_per_contract']:.2f}c/contract)")
        mt = f"{r['monthly_t']:.2f}" if r['monthly_t'] is not None else "n/a"
        print(f"   top event share {r['share_from_top_event']:.0%} ({r['top_event']}), top-5 share {r['share_from_top5_events']:.0%}, months positive {r['months_positive']}, monthly t {mt}, worst month ${r['worst_month_usd']:,.0f}, median month ${r['median_month_usd']:,.0f}")
        print(f"   events where makers lost: {r['events_with_maker_loss_pct']:.0f}%; worst events {r['worst_events'][:3]}")

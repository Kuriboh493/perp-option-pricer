"""Where does Kalshi retail lose? Every trade in the Becker dataset (2021 - Jan 2026), from the taker's side:
taker return per dollar after Kalshi's 7% taker fee, and the maker's gross return, aggregated by series, year,
taker price bucket and time to close. Output: data/kalshi_segments.parquet plus a JSON summary."""
import glob, json, os, sys
import numpy as np, pandas as pd, pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
B = os.path.join(HERE, "data", "becker", "data", "kalshi")
PRICE_BINS = [0, 5, 10, 20, 35, 50, 65, 80, 90, 95, 101]
PRICE_LABELS = ["00-05", "05-10", "10-20", "20-35", "35-50", "50-65", "65-80", "80-90", "90-95", "95-99"]
TTC_BINS = [-1e18, 0, 3600, 6 * 3600, 24 * 3600, 7 * 86400, 1e18]
TTC_LABELS = ["after_close", "<1h", "1-6h", "6-24h", "1-7d", ">7d"]


def load_markets():
    cols = ["ticker", "result", "close_time"]
    parts = [pq.read_table(f, columns=cols).to_pandas() for f in sorted(glob.glob(os.path.join(B, "markets", "*.parquet")))]
    m = pd.concat(parts, ignore_index=True)
    m = m[m["result"].isin(["yes", "no"])].drop_duplicates("ticker")
    m["yes"] = (m["result"] == "yes").astype(np.int8)
    m["close_s"] = m["close_time"].astype("int64") // 10 ** 9
    return m.set_index("ticker")[["yes", "close_s"]]


def process(files, markets, limit=None):
    acc, files = [], files[:limit]
    batches = [files[i:i + 40] for i in range(0, len(files), 40)]
    for i, fs in enumerate(batches):
        t = pd.concat([pq.read_table(f, columns=["ticker", "count", "yes_price", "taker_side", "created_time"]).to_pandas() for f in fs], ignore_index=True)
        t = t.join(markets, on="ticker", how="inner")
        if t.empty:
            continue
        p = np.where(t["taker_side"].values == "yes", t["yes_price"].values, 100 - t["yes_price"].values) / 100.0
        y = np.where(t["taker_side"].values == "yes", t["yes"].values, 1 - t["yes"].values).astype(float)
        n = t["count"].values.astype(float)
        fee = 0.07 * p * (1 - p)
        created_s = t["created_time"].astype("int64").values // 10 ** 9
        ttc = t["close_s"].values - created_s
        d = pd.DataFrame(dict(
            series=t["ticker"].str.split("-").str[0].values, year=pd.to_datetime(created_s, unit="s").year,
            price_bucket=pd.cut(p * 100, PRICE_BINS, labels=PRICE_LABELS, right=False), ttc=pd.cut(ttc, TTC_BINS, labels=TTC_LABELS, right=False),
            trades=1.0, contracts=n, dollars=n * p, taker_pnl=n * (y - p - fee), maker_gross=n * ((1 - y) - (1 - p)), fees=n * fee))
        acc.append(d.groupby(["series", "year", "price_bucket", "ttc"], observed=True).sum().reset_index())
        if i % 10 == 0:
            print(i * 40, "files", flush=True)
            if len(acc) > 20:
                acc = [pd.concat(acc).groupby(["series", "year", "price_bucket", "ttc"], observed=True).sum().reset_index()]
    return pd.concat(acc).groupby(["series", "year", "price_bucket", "ttc"], observed=True).sum().reset_index()


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    markets = load_markets(); print(len(markets), "resolved markets", flush=True)
    files = sorted(glob.glob(os.path.join(B, "trades", "*.parquet")))
    seg = process(files, markets, limit)
    cat = json.load(open(os.path.join(HERE, "data", "kalshi_series.json"))) if os.path.exists(os.path.join(HERE, "data", "kalshi_series.json")) else {}
    seg["category"] = seg["series"].map(lambda s: (cat.get(s) or {}).get("category") or "unknown")
    seg.to_parquet(os.path.join(HERE, "data", "kalshi_segments.parquet"))
    print("segments", len(seg), "trades", seg["trades"].sum(), "dollars", seg["dollars"].sum(), flush=True)

"""Second pass over Kalshi trades: aggregate to (event, month, price bucket) so monthly consistency and per-event
concentration of maker gains can be examined for any segment. Output: data/kalshi_events.parquet."""
import glob, os, sys
import numpy as np, pandas as pd, pyarrow.parquet as pq
from kalshi_survey import load_markets, PRICE_BINS, PRICE_LABELS, B

HERE = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    markets = load_markets(); print(len(markets), "markets", flush=True)
    files = sorted(glob.glob(os.path.join(B, "trades", "*.parquet")))
    acc, keys = [], ["event", "month", "price_bucket"]
    batches = [files[i:i + 40] for i in range(0, len(files), 40)]
    for i, fs in enumerate(batches):
        t = pd.concat([pq.read_table(f, columns=["ticker", "count", "yes_price", "taker_side", "created_time"]).to_pandas() for f in fs], ignore_index=True)
        t = t.join(markets, on="ticker", how="inner")
        if t.empty:
            continue
        p = np.where(t["taker_side"].values == "yes", t["yes_price"].values, 100 - t["yes_price"].values) / 100.0
        y = np.where(t["taker_side"].values == "yes", t["yes"].values, 1 - t["yes"].values).astype(float)
        n = t["count"].values.astype(float)
        created = t["created_time"].astype("int64").values // 10 ** 9
        after = created > t["close_s"].values
        tk = t["ticker"].str
        event = tk.rsplit("-", n=1).str[0].values
        d = pd.DataFrame(dict(event=event, month=pd.to_datetime(created, unit="s").strftime("%Y-%m"), price_bucket=pd.cut(p * 100, PRICE_BINS, labels=PRICE_LABELS, right=False),
                              trades=1.0, contracts=n, dollars=n * p, maker_gross=n * ((1 - y) - (1 - p)), fees=n * 0.07 * p * (1 - p)))[~after]
        acc.append(d.groupby(keys, observed=True).sum().reset_index())
        if i % 10 == 0:
            print(i * 40, "files", flush=True)
            if len(acc) > 20:
                acc = [pd.concat(acc).groupby(keys, observed=True).sum().reset_index()]
    ev = pd.concat(acc).groupby(keys, observed=True).sum().reset_index()
    ev["series"] = ev["event"].str.split("-").str[0]
    ev.to_parquet(os.path.join(HERE, "data", "kalshi_events.parquet")); print("done", len(ev), "rows", flush=True)

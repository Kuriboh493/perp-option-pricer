"""Minute candles for ETH/SOL/XRP (Coinbase, since 2026-07-25) and 5-minute S&P 500 bars (Yahoo, last 60 days), for the recent Kalshi series."""
import json, os, time, urllib.request, datetime as dt

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def coinbase_1m(product, start, end):
    rows, t = {}, start
    while t < end:
        e = min(t + 300 * 60, end)
        url = f"https://api.exchange.coinbase.com/products/{product}/candles?granularity=60&start={dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()}&end={dt.datetime.fromtimestamp(e, dt.timezone.utc).isoformat()}"
        for attempt in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research"}), timeout=30) as r:
                    for c in json.load(r):
                        rows[c[0]] = [c[3], c[4]]
                break
            except Exception:
                time.sleep(2 + 2 * attempt)
        t = e; time.sleep(0.25)
    return sorted([[k, v[0], v[1]] for k, v in rows.items()])


if __name__ == "__main__":
    start, end = int(dt.datetime(2026, 7, 25, tzinfo=dt.timezone.utc).timestamp()), int(time.time())
    for p in ("ETH-USD", "SOL-USD", "XRP-USD"):
        rows = coinbase_1m(p, start, end)
        json.dump(rows, open(os.path.join(OUT, f"{p.split('-')[0].lower()}_1m.json"), "w")); print(p, len(rows), "minutes", flush=True)
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?interval=5m&range=60d&includePrePost=false"
    r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    rows = [[t, o, c] for t, o, c in zip(r["timestamp"], q["open"], q["close"]) if c is not None and o is not None]
    json.dump(rows, open(os.path.join(OUT, "spx_5m.json"), "w")); print("SPX 5m", len(rows), rows[0], rows[-1])

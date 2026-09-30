"""Hourly spot prices for the assets behind the less-mature contracts: Coinbase candles for ETH/SOL/XRP/BTC, Yahoo for the S&P 500."""
import json, os, time, urllib.request, datetime as dt

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def coinbase(product, start, end):
    rows = {}
    t = start
    while t < end:
        e = min(t + 300 * 3600, end)
        url = f"https://api.exchange.coinbase.com/products/{product}/candles?granularity=3600&start={dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()}&end={dt.datetime.fromtimestamp(e, dt.timezone.utc).isoformat()}"
        for attempt in range(5):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research"}), timeout=30) as r:
                    for c in json.load(r):            # [time, low, high, open, close, volume]
                        rows[c[0]] = c[4]
                break
            except Exception:
                time.sleep(2 + 2 * attempt)
        t = e
        time.sleep(0.25)
    return [[k * 1000, v] for k, v in sorted(rows.items())]


def yahoo_hourly(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1h&range=730d&includePrePost=false"
    r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30))["chart"]["result"][0]
    return [[t * 1000, c] for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c is not None]


if __name__ == "__main__":
    start, end = int(dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc).timestamp()), int(time.time())
    for p in ("ETH-USD", "SOL-USD", "XRP-USD", "BTC-USD"):
        rows = coinbase(p, start, end)
        json.dump(rows, open(os.path.join(OUT, f"spot_{p.split('-')[0]}.json"), "w"))
        print(p, len(rows), "hours", rows[0], rows[-1], flush=True)
    rows = yahoo_hourly("%5EGSPC")
    json.dump(rows, open(os.path.join(OUT, "spot_SPX.json"), "w")); print("SPX", len(rows), rows[0], rows[-1])

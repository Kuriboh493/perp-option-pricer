"""One-minute BTC-USD candles from Coinbase since 2025-06-01, for the Polymarket windows (open, close per minute)."""
import json, os, time, urllib.request, datetime as dt

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "btc_1m.json")
if __name__ == "__main__":
    rows, t, end = {}, int(dt.datetime(2025, 6, 1, tzinfo=dt.timezone.utc).timestamp()), int(time.time())
    n = 0
    while t < end:
        e = min(t + 300 * 60, end)
        url = f"https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60&start={dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()}&end={dt.datetime.fromtimestamp(e, dt.timezone.utc).isoformat()}"
        for attempt in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research"}), timeout=30) as r:
                    for c in json.load(r):
                        rows[c[0]] = [c[3], c[4]]
                break
            except Exception:
                time.sleep(2 + 2 * attempt)
        t = e; n += 1
        if n % 300 == 0:
            print(n, "requests", len(rows), "minutes", flush=True)
        time.sleep(0.2)
    json.dump(sorted([[k, v[0], v[1]] for k, v in rows.items()]), open(OUT, "w"))
    print("done", len(rows), "minutes", flush=True)

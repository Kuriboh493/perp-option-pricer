"""Kalshi NFL game-winner markets settled since Aug 2026: hourly candlesticks (price + volume) for a price-bucket comparison with DKeX."""
import os, json, time, datetime as dt, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "kalshi")
K="https://api.elections.kalshi.com/trade-api/v2"
def get(path, attempts=6):
    for a in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(K+path, headers={"User-Agent":"research"}), timeout=30) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code==404: return None
            time.sleep(float(e.headers.get("Retry-After") or 0) or 3+3*a)
        except Exception: time.sleep(2+2*a)
    return None
os.makedirs(OUT, exist_ok=True)
markets=[]; cursor=None
while True:
    r=get("/markets?series_ticker=KXNFLGAME&status=settled&limit=1000&min_close_ts=1754006400"+(f"&cursor={cursor}" if cursor else ""))
    if not r: break
    markets+=r.get("markets",[]); cursor=r.get("cursor")
    if not cursor: break
    time.sleep(0.2)
json.dump(markets, open(os.path.join(OUT, "nfl_markets.json"),"w"))
print(len(markets), "markets", flush=True)
out={}
for i,m in enumerate(markets):
    end=int(dt.datetime.fromisoformat(m["close_time"].replace("Z","+00:00")).timestamp())
    start=end-14*86400
    r=get(f"/series/KXNFLGAME/markets/{m['ticker']}/candlesticks?start_ts={start}&end_ts={end}&period_interval=60")
    out[m["ticker"]]={"market":{k:m.get(k) for k in ("ticker","result","close_time","open_time","volume","title")}, "candles":(r or {}).get("candlesticks",[])}
    if i%25==0: print(i, m["ticker"], len(out[m["ticker"]]["candles"]), flush=True)
    time.sleep(0.15)
json.dump(out, open(os.path.join(OUT, "nfl_candles.json"),"w"))
print("done", sum(len(v["candles"]) for v in out.values()))

"""Download Kalshi's daily (v2: full candle fields for simulating resting orders) 'Bitcoin above $X at 5pm ET' markets (series KXBTCD) with hourly bid/ask candles.
Strikes are chosen from the Deribit index six hours before the close, so the selection uses no future information."""
import json, os, sys, time, threading, urllib.request, urllib.error, datetime as dt
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backtest"))
from data import load_hourly, HOUR

API = "https://api.elections.kalshi.com/trade-api/v2"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kalshi2")
CUTOFF = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)   # markets settled before this live under /historical
WIDTH = 0.03                                               # keep strikes within 3% of spot
MIN_GAP = 0.6                                             # seconds between requests, to stay under the rate limit
_lock, _last = threading.Lock(), [0.0]
_, index, _ = load_hourly()


def _pace():
    with _lock:
        wait = _last[0] + MIN_GAP - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def get(path):
    for attempt in range(12):
        _pace()
        try:
            with urllib.request.urlopen(urllib.request.Request(API + path, headers={"User-Agent": "research"}), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(float(e.headers.get("Retry-After") or 0) or min(30, 2 + 3 * attempt))
        except Exception:
            time.sleep(1 + 2 * attempt)
    raise RuntimeError(path)


def num(x):
    return None if x in (None, "") else float(x)


def candle_rows(cs, new):
    """[end_ts, bid close, ask close, volume, bid low, bid high, ask low, ask high, trade low, trade high, trade close]"""
    rows = []
    sfx = "_dollars" if new else ""
    for c in cs:
        b, a, p = c.get("yes_bid", {}), c.get("yes_ask", {}), c.get("price", {})
        rows.append([c["end_period_ts"], num(b.get("close" + sfx)), num(a.get("close" + sfx)), num(c.get("volume_fp" if new else "volume")),
                     num(b.get("low" + sfx)), num(b.get("high" + sfx)), num(a.get("low" + sfx)), num(a.get("high" + sfx)),
                     num(p.get("low" + sfx)), num(p.get("high" + sfx)), num(p.get("close" + sfx))])
    return rows


def fetch_event(d):
    ev = f"KXBTCD-{d.strftime('%y%b%d').upper()}17"
    path = os.path.join(OUT, ev + ".json")
    if os.path.exists(path):
        return
    hist = get(f"/historical/markets?event_ticker={ev}&limit=200")
    markets, new = (hist or {}).get("markets") or [], False
    if not markets:
        markets, new = (get(f"/markets?event_ticker={ev}&limit=200") or {}).get("markets") or [], True
    markets = [m for m in markets if m.get("strike_type") == "greater" and m.get("result") in ("yes", "no")]
    if not markets:
        json.dump([], open(path, "w")); return
    close = int(dt.datetime.fromisoformat(markets[0]["close_time"].replace("Z", "+00:00")).timestamp())
    spot = index.get((close - 6 * 3600) * 1000)
    if spot is None:
        json.dump([], open(path, "w")); return
    markets = [m for m in markets if abs(m["floor_strike"] / spot - 1) <= WIDTH]
    start, end = close - 8 * 3600, close
    out = []
    if new:
        r = get(f"/series/KXBTCD/events/{ev}/candlesticks?start_ts={start}&end_ts={end}&period_interval=60") or {}
        by = dict(zip(r.get("market_tickers", []), r.get("market_candlesticks", [])))
        for m in markets:
            out.append(dict(ticker=m["ticker"], strike=m["floor_strike"], result=m["result"], close=close,
                            settle=num(m.get("expiration_value")), candles=candle_rows(by.get(m["ticker"], []), True)))
    else:
        for m in markets:
            r = get(f"/historical/markets/{m['ticker']}/candlesticks?start_ts={start}&end_ts={end}&period_interval=60") or {}
            out.append(dict(ticker=m["ticker"], strike=m["floor_strike"], result=m["result"], close=close,
                            settle=num(m.get("expiration_value")), candles=candle_rows(r.get("candlesticks", []), False)))
    json.dump(out, open(path, "w"))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    days, d = [], dt.date(2025, 3, 1)
    while d <= dt.date(2026, 9, 29):
        days.append(d); d += dt.timedelta(days=1)
    with ThreadPoolExecutor(1) as ex:
        for i, _ in enumerate(ex.map(fetch_event, days)):
            if i % 100 == 0:
                print(i, "events", flush=True)
    print("done", len(days), flush=True)

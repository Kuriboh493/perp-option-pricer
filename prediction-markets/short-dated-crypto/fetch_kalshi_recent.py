"""Kalshi hourly and 15-minute price-threshold series, Aug-Sep 2026, via the event-level candlestick endpoint
(one request per event; only works for events after the 2026-08-01 historical cutoff). Saves every market's
candles (bid/ask/trade OHLC per minute) so quotes at any lead time can be read later."""
import json, os, sys, time, threading, urllib.request, urllib.error, datetime as dt

API = "https://api.elections.kalshi.com/trade-api/v2"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kalshi_recent")
SERIES = {"KXETHD": 1, "KXSOLD": 1, "KXXRPD": 1, "KXBTC": 1, "KXINXU": 1, "KXBTC15M": 1, "KXETH15M": 1}   # minute candles for all
SPAN = {"KXBTC15M": 40 * 60, "KXETH15M": 40 * 60}
DEFAULT_SPAN = 100 * 60          # the endpoint caps a response at ~5000 candles; 40 strikes x 100 minutes stays under it
MIN_GAP, _lock, _last = 0.6, threading.Lock(), [0.0]


def get(path):
    for attempt in range(12):
        with _lock:
            w = _last[0] + MIN_GAP - time.time()
            if w > 0:
                time.sleep(w)
            _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(API + path, headers={"User-Agent": "research"}), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(float(e.headers.get("Retry-After") or 0) or min(30, 2 + 3 * attempt))
        except Exception:
            time.sleep(2 + 3 * attempt)
    raise RuntimeError(path)


def num(x):
    if x in (None, ""):
        return None
    try:
        return float(str(x).replace(",", ""))           # some settlement values arrive formatted, e.g. "77,362.10"
    except ValueError:
        return None


def events(series):
    out, cursor = [], ""
    while True:
        r = get(f"/events?series_ticker={series}&status=settled&limit=200&with_nested_markets=true" + (f"&cursor={cursor}" if cursor else ""))
        if not r or not r.get("events"):
            break
        out += r["events"]
        cursor = r.get("cursor")
        if not cursor or len(out) > 6000:
            break
    return out


def fetch_event(series, ev, period):
    path = os.path.join(OUT, series, ev["event_ticker"] + ".json")
    if os.path.exists(path):
        return
    ms_ = [m for m in ev.get("markets", []) if m.get("result") in ("yes", "no")]
    if not ms_:
        json.dump([], open(path, "w")); return
    close = int(dt.datetime.fromisoformat(ms_[0]["close_time"].replace("Z", "+00:00")).timestamp())
    span = SPAN.get(series, DEFAULT_SPAN)
    r = get(f"/series/{series}/events/{ev['event_ticker']}/candlesticks?start_ts={close - span}&end_ts={close}&period_interval={period}") or {}
    by = dict(zip(r.get("market_tickers", []), r.get("market_candlesticks", [])))
    resolution = period
    if not any(by.values()):                              # thin events carry no minute candles; fall back to hour candles
        r = get(f"/series/{series}/events/{ev['event_ticker']}/candlesticks?start_ts={close - 8 * 3600}&end_ts={close}&period_interval=60") or {}
        by = dict(zip(r.get("market_tickers", []), r.get("market_candlesticks", []))); resolution = 60
    out = []
    for m in ms_:
        rows = []
        for c in by.get(m["ticker"], []):
            b, a, p = c.get("yes_bid", {}), c.get("yes_ask", {}), c.get("price", {})
            rows.append([c["end_period_ts"], num(b.get("close_dollars")), num(a.get("close_dollars")), num(c.get("volume_fp")),
                         num(b.get("low_dollars")), num(b.get("high_dollars")), num(a.get("low_dollars")), num(a.get("high_dollars")),
                         num(p.get("low_dollars")), num(p.get("high_dollars")), num(p.get("close_dollars"))])
        out.append(dict(ticker=m["ticker"], strike=m.get("floor_strike"), cap=m.get("cap_strike"), strike_type=m.get("strike_type"),
                        result=m["result"], close=close, settle=num(m.get("expiration_value")), resolution=resolution, candles=rows))
    json.dump(out, open(path, "w"))


if __name__ == "__main__":
    only = sys.argv[1:] or list(SERIES)
    for s in only:
        os.makedirs(os.path.join(OUT, s), exist_ok=True)
        evs = events(s)
        cutoff = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
        evs = [e for e in evs if e.get("markets") and dt.datetime.fromisoformat(e["markets"][0]["close_time"].replace("Z", "+00:00")) >= cutoff]
        print(s, len(evs), "events since Aug 1", flush=True)
        for i, e in enumerate(evs):
            fetch_event(s, e, SERIES[s])
            if i % 200 == 0:
                print(s, i, flush=True)
    print("done", flush=True)

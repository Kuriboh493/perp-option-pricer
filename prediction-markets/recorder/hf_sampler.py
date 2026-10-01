"""High-frequency sampler for markouts on the Kalshi BTC maker strategy.

Each day it wakes five minutes before the strategy places its resting bids (four hours before the 5pm ET close) and records,
until two minutes after the close:
  - Kalshi top of book for every KXBTCD strike within 5% of spot (every 2 s for the first 110 minutes, then every 5 s),
    written only when the quote changes plus a 60 s heartbeat;
  - every Kalshi trade on tickers with live BTC resting orders (for fill replay and the trade that filled us);
  - Coinbase BTC-USD spot every second;
  - Deribit mark IVs for the first daily expiry after the Kalshi close, every 30 s (the fair-value smile).
Timestamps are local receive times (UTC epoch seconds, NTP-synced clock), which is conservative for as-of lookups: a value is
only treated as known once it has been received. Kalshi trades also keep the exchange's own timestamp.
Data goes to data/hf.db. Reads only public endpoints."""
import json, math, os, sqlite3, sys, threading, time, urllib.request, urllib.error, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
HF_DB = os.path.join(HERE, "data", "hf.db")
MAIN_DB = os.path.join(HERE, "data", "recorder.db")
LOG = os.path.join(HERE, "data", "hf.log")
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
PRE_S, POST_S, FAST_S = 300, 120, 110 * 60
QUOTE_FAST, QUOTE_SLOW, TRADE_GAP, SPOT_GAP, DERIBIT_GAP, HEARTBEAT = 2.0, 5.0, 3.0, 1.0, 30.0, 60.0
WIDTH = 0.05
_stop = threading.Event()
_spot = {"px": None}


def log(msg):
    line = f"{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def fetch(url, attempts=3, timeout=15):
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hf-sampler"}), timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(float(e.headers.get("Retry-After") or 0) or 2 + 3 * attempt)
        except Exception:
            time.sleep(1 + attempt)
    return None


def connect(path=None):
    con = sqlite3.connect(path or HF_DB, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS kalshi_markets(ticker TEXT PRIMARY KEY, event TEXT, strike REAL, close_ts INT);
    CREATE TABLE IF NOT EXISTS kalshi_quotes(ts REAL, ticker TEXT, yes_bid REAL, yes_ask REAL, bid_size REAL, ask_size REAL);
    CREATE INDEX IF NOT EXISTS kq ON kalshi_quotes(ticker, ts);
    CREATE TABLE IF NOT EXISTS kalshi_trades(trade_id TEXT PRIMARY KEY, ticker TEXT, ts REAL, yes_price REAL, no_price REAL, count REAL, taker_side TEXT, received_ts REAL);
    CREATE INDEX IF NOT EXISTS kt ON kalshi_trades(ticker, ts);
    CREATE TABLE IF NOT EXISTS spot(ts REAL, price REAL, exchange_time TEXT);
    CREATE INDEX IF NOT EXISTS sp ON spot(ts);
    CREATE TABLE IF NOT EXISTS deribit_iv(ts REAL, expiry INT, strike REAL, cp TEXT, mark_iv REAL, bid_price REAL, ask_price REAL, underlying REAL, index_price REAL, exchange_ts REAL);
    CREATE INDEX IF NOT EXISTS di ON deribit_iv(ts);
    CREATE TABLE IF NOT EXISTS windows(event TEXT PRIMARY KEY, start_ts INT, end_ts INT, close_ts INT);
    """)
    return con


def event_for(now):
    sys.path.insert(0, HERE)
    from recorder import btc_event
    return btc_event(now)


def event_markets(event):
    r = fetch(f"{KALSHI}/markets?event_ticker={event}&limit=300")
    return [m for m in (r or {}).get("markets", []) if m.get("strike_type") == "greater"]


def live_btc_tickers():
    try:
        con = sqlite3.connect(f"file:{MAIN_DB}?mode=ro", uri=True, timeout=10)
        rows = con.execute("SELECT DISTINCT market FROM orders WHERE strategy='btc_fav' AND status='live'").fetchall()
        con.close()
        return [r[0] for r in rows]
    except Exception:
        return []


# ---------- samplers ----------
def kalshi_loop(event, close, start, end, db):
    con = connect(db)
    last = {}
    next_quote = next_trade = next_tickers = 0.0
    tickers, rr, cursors = [], 0, {}
    while not _stop.is_set() and time.time() < end:
        now = time.time()
        if now >= next_tickers:
            tickers = live_btc_tickers(); next_tickers = now + 30
        if now >= next_quote:
            ms = event_markets(event)
            rt = time.time()
            spot = _spot["px"]
            for m in ms:
                try:
                    k = float(m["floor_strike"]); yb = float(m["yes_bid_dollars"]); ya = float(m["yes_ask_dollars"])
                    bs = float(m.get("yes_bid_size_fp") or 0); as_ = float(m.get("yes_ask_size_fp") or 0)
                except (KeyError, TypeError, ValueError):
                    continue
                if spot and abs(math.log(k / spot)) > WIDTH:
                    continue
                key = (yb, ya, bs, as_)
                prev = last.get(m["ticker"])
                if prev is None:
                    con.execute("INSERT OR IGNORE INTO kalshi_markets VALUES(?,?,?,?)", (m["ticker"], event, k, close))
                if prev is None or prev[0] != key or rt - prev[1] >= HEARTBEAT:
                    con.execute("INSERT INTO kalshi_quotes VALUES(?,?,?,?,?,?)", (rt, m["ticker"], yb, ya, bs, as_))
                    last[m["ticker"]] = (key, rt)
            con.commit()
            next_quote = now + (QUOTE_FAST if now < start + FAST_S else QUOTE_SLOW)
        elif tickers and now >= next_trade:
            tk = tickers[rr % len(tickers)]; rr += 1
            since = cursors.get(tk, start)
            r = fetch(f"{KALSHI}/markets/trades?ticker={tk}&limit=1000&min_ts={int(since) - 1}")
            rt = time.time()
            for t in (r or {}).get("trades", []):
                ts = dt.datetime.fromisoformat(t["created_time"].replace("Z", "+00:00")).timestamp()
                con.execute("INSERT OR IGNORE INTO kalshi_trades VALUES(?,?,?,?,?,?,?,?)",
                            (t["trade_id"], tk, ts, float(t["yes_price_dollars"]), float(t["no_price_dollars"]), float(t.get("count_fp") or 0), t.get("taker_side"), rt))
                cursors[tk] = max(cursors.get(tk, 0), ts)
            con.commit()
            next_trade = now + TRADE_GAP
        time.sleep(0.05)


def spot_loop(end, db):
    con = connect(db)
    n = 0
    while not _stop.is_set() and time.time() < end:
        t0 = time.time()
        r = fetch("https://api.exchange.coinbase.com/products/BTC-USD/ticker", attempts=1, timeout=5)
        if r and r.get("price"):
            px = float(r["price"]); _spot["px"] = px
            con.execute("INSERT INTO spot VALUES(?,?,?)", (time.time(), px, r.get("time")))
            n += 1
            if n % 30 == 0:
                con.commit()
        time.sleep(max(0.0, SPOT_GAP - (time.time() - t0)))
    con.commit()


def deribit_expiry_after(close, names):
    best = None
    for n in names:
        try:
            d = dt.datetime.strptime(n.split("-")[1], "%d%b%y").replace(hour=8, tzinfo=dt.timezone.utc).timestamp()
        except (IndexError, ValueError):
            continue
        if d > close and (best is None or d < best):
            best = d
    return best


def deribit_loop(close, end, db):
    con = connect(db)
    while not _stop.is_set() and time.time() < end:
        t0 = time.time()
        r = fetch("https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option", attempts=2, timeout=20)
        rows = (r or {}).get("result", [])
        rt = time.time()
        exp = deribit_expiry_after(close, [x["instrument_name"] for x in rows])
        if exp:
            tag = dt.datetime.fromtimestamp(exp, dt.timezone.utc).strftime("%-d%b%y").upper()
            for x in rows:
                p = x["instrument_name"].split("-")
                if len(p) == 4 and p[1] == tag and x.get("mark_iv"):
                    con.execute("INSERT INTO deribit_iv VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (rt, int(exp), float(p[2]), p[3], float(x["mark_iv"]), x.get("bid_price"), x.get("ask_price"),
                                 x.get("underlying_price"), x.get("estimated_delivery_price"), (x.get("creation_timestamp") or 0) / 1000))
            con.commit()
        time.sleep(max(0.0, DERIBIT_GAP - (time.time() - t0)))


def run_window(event, close, start, end, db=None):
    con = connect(db)
    con.execute("INSERT OR REPLACE INTO windows VALUES(?,?,?,?)", (event, int(start), int(end), int(close))); con.commit()
    log(f"window {event}: {dt.datetime.fromtimestamp(start, dt.timezone.utc):%H:%M}-{dt.datetime.fromtimestamp(end, dt.timezone.utc):%H:%M} UTC")
    threads = [threading.Thread(target=spot_loop, args=(end, db), daemon=True),
               threading.Thread(target=kalshi_loop, args=(event, close, start, end, db), daemon=True),
               threading.Thread(target=deribit_loop, args=(close, end, db), daemon=True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    c = connect(db)
    counts = {tb: c.execute(f"SELECT COUNT(*) FROM {tb}").fetchone()[0] for tb in ("kalshi_quotes", "kalshi_trades", "spot", "deribit_iv")}
    log(f"window {event} done; table sizes {counts}")


def main():
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    if "--test" in sys.argv:                                  # sample right now for N seconds into a separate database
        secs = int(sys.argv[sys.argv.index("--test") + 1]) if len(sys.argv) > sys.argv.index("--test") + 1 else 60
        now = time.time(); ev = event_for(now); ms = event_markets(ev)
        close = int(dt.datetime.fromisoformat(ms[0]["close_time"].replace("Z", "+00:00")).timestamp())
        run_window(ev, close, now, now + secs, db=os.path.join(HERE, "data", "hf_test.db"))
        return
    log("hf sampler started")
    while True:
        now = time.time()
        ev = event_for(now)
        ms = event_markets(ev)
        if not ms:
            time.sleep(300); continue
        close = int(dt.datetime.fromisoformat(ms[0]["close_time"].replace("Z", "+00:00")).timestamp())
        start, end = close - 4 * 3600 - PRE_S, close + POST_S
        if now >= end:
            time.sleep(600); continue
        if now < start:
            time.sleep(min(600, start - now)); continue
        run_window(ev, close, start, end)                     # also resumes a window after a restart


if __name__ == "__main__":
    main()

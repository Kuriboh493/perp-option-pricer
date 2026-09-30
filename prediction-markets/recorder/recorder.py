"""Live paper-trading recorder for the far-dated longshot pool on Kalshi and Polymarket.

Every cycle it (1) refreshes the universe of open markets resolving 7-180 days out whose cheaper side is quoted at
3-20 cents in the target categories, (2) snapshots each market's order book, (3) pulls new trades, (4) advances virtual
resting offers on the longshot side (one joining the best ask, one a tick inside it) using a queue-position model fed by
the printed trades, and (5) records resolutions for filled positions. No orders are sent anywhere; only public endpoints
are read. State lives in data/recorder.db (SQLite); run report.py for fills, capacity and P&L."""
import json, os, re, sqlite3, sys, time, urllib.request, urllib.error, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "recorder.db")
LOG = os.path.join(HERE, "data", "recorder.log")
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
CYCLE_S, UNIVERSE_S = 300, 1800
MIN_DAYS, MAX_DAYS = 7, 180
PRICE_LO, PRICE_HI = 0.03, 0.20
PER_PLATFORM, ORDER_SIZE, MAX_POSITIONS = 120, 100, 5
KALSHI_CATS = {"Economics", "Politics", "Elections", "Entertainment", "Companies", "World", "Science and Technology", "Mentions", "Health", "Social", "Transportation", "Climate and Weather"}
PM_EXCLUDE = re.compile(r"bitcoin|btc|ethereum|\beth\b|solana|\bsol\b|xrp|doge|crypto|up-or-down|updown|\bnba\b|\bnfl\b|\bmlb\b|\bnhl\b|\bufc\b|\bmma\b|soccer|premier-league|la-liga|serie-a|bundesliga|champions|\bvs\b|-vs-|spread|tennis|golf|pga|super-bowl|world-series|stanley|playoffs|ncaa|cricket|rugby|boxing|esports|counter-strike|dota|league-of-legends|valorant|f1-|grand-prix|win-on-|beat-")
_last = {"kalshi": 0.0, "pm": 0.0}


def log(msg):
    line = f"{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def get(url, host, gap, data=None, attempts=4):
    for attempt in range(attempts):
        w = _last[host] + gap - time.time()
        if w > 0:
            time.sleep(w)
        _last[host] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "paper-recorder", "Content-Type": "application/json"}, data=json.dumps(data).encode() if data is not None else None)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(float(e.headers.get("Retry-After") or 0) or min(30, 2 + 3 * attempt))
        except Exception:
            time.sleep(2 + 2 * attempt)
    return None


def kget(path):
    return get(KALSHI + path, "kalshi", 0.6)


def db():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS universe(ts INT, platform TEXT, market TEXT, title TEXT, category TEXT, side TEXT, token TEXT, other_token TEXT, condition TEXT, close_ts INT, vol24 REAL, price REAL);
    CREATE TABLE IF NOT EXISTS snapshots(ts INT, platform TEXT, market TEXT, side TEXT, best_bid REAL, best_ask REAL, bid_size REAL, ask_size REAL, ask_depth_to_20c REAL, bid_depth REAL);
    CREATE TABLE IF NOT EXISTS trades(platform TEXT, market TEXT, trade_id TEXT PRIMARY KEY, ts INT, taker_buys_longshot INT, price REAL, size REAL);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, platform TEXT, market TEXT, side TEXT, kind TEXT, price REAL, size REAL, remaining REAL, queue_ahead REAL, placed_ts INT, status TEXT, filled_ts INT);
    CREATE TABLE IF NOT EXISTS fills(order_id INT, ts INT, price REAL, size REAL);
    CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY, platform TEXT, market TEXT, side TEXT, price REAL, size REAL, opened_ts INT, result TEXT, pnl REAL, resolved_ts INT);
    CREATE TABLE IF NOT EXISTS cursors(platform TEXT, market TEXT, last_ts INT, PRIMARY KEY(platform, market));
    """)
    return con


# ---------- universe ----------
def kalshi_categories():
    path = os.path.join(HERE, "..", "edge2", "data", "kalshi_series.json")
    return json.load(open(path)) if os.path.exists(path) else {}


def kalshi_universe(now):
    cats, out, cursor, pages = kalshi_categories(), [], "", 0
    lo, hi = now + MIN_DAYS * 86400, now + MAX_DAYS * 86400
    while pages < 25:
        r = kget(f"/markets?status=open&limit=1000&min_close_ts={lo}&max_close_ts={hi}" + (f"&cursor={cursor}" if cursor else ""))
        if not r or not r.get("markets"):
            break
        for m in r["markets"]:
            try:
                ya, na, v = float(m["yes_ask_dollars"]), float(m["no_ask_dollars"]), float(m.get("volume_24h_fp") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            cat = (cats.get(m["ticker"].split("-")[0]) or {}).get("category")
            if v <= 0 or cat not in KALSHI_CATS:
                continue
            side, price = ("yes", ya) if ya <= na else ("no", na)
            if PRICE_LO <= price <= PRICE_HI:
                close = int(dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")).timestamp())
                out.append(dict(platform="kalshi", market=m["ticker"], title=m.get("title", "")[:120], category=cat, side=side, token=None, other_token=None, condition=None, close_ts=close, vol24=v, price=price))
        cursor, pages = r.get("cursor"), pages + 1
        if not cursor:
            break
    out.sort(key=lambda x: -x["vol24"])
    return out[:PER_PLATFORM]


def pm_universe(now):
    out = []
    dmin = dt.datetime.fromtimestamp(now + MIN_DAYS * 86400, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dmax = dt.datetime.fromtimestamp(now + MAX_DAYS * 86400, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for offset in range(0, 5000, 500):
        r = get(f"https://gamma-api.polymarket.com/markets?closed=false&active=true&limit=500&offset={offset}&order=volume24hr&ascending=false&end_date_min={dmin}&end_date_max={dmax}", "pm", 0.2)
        if not r:
            break
        for m in r:
            try:
                toks = json.loads(m.get("clobTokenIds") or "[]"); bb, ba = float(m.get("bestBid") or 0), float(m.get("bestAsk") or 0); v = float(m.get("volume24hr") or 0)
            except (TypeError, ValueError):
                continue
            text = ((m.get("slug") or "") + " " + (m.get("question") or "")).lower()
            if len(toks) != 2 or v <= 0 or not (0 < bb < ba < 1) or PM_EXCLUDE.search(text):
                continue
            yes_ask, no_ask = ba, 1 - bb
            side, price, tok, other = ("yes", yes_ask, toks[0], toks[1]) if yes_ask <= no_ask else ("no", no_ask, toks[1], toks[0])
            if PRICE_LO <= price <= PRICE_HI and m.get("endDate"):
                close = int(dt.datetime.fromisoformat(m["endDate"].replace("Z", "+00:00")).timestamp())
                cat = "finance" if re.search(r"\bfed\b|rate|cpi|inflation|gdp|recession|treasury|tariff", text) else "politics" if re.search(r"election|president|senate|governor|trump|mayor|parliament|minister|congress|vote|ceasefire|ukraine|israel|iran|nato|war|resign", text) else "entertainment" if re.search(r"oscar|grammy|emmy|box-office|album|song|movie|netflix|swift|kanye|eurovision", text) else "other"
                out.append(dict(platform="pm", market=m["conditionId"], title=(m.get("question") or "")[:120], category=cat, side=side, token=tok, other_token=other, condition=m["conditionId"], close_ts=close, vol24=v, price=price))
        if len(r) < 500:
            break
    out.sort(key=lambda x: -x["vol24"])
    return out[:PER_PLATFORM]


# ---------- books and trades ----------
def kalshi_book(u):
    r = kget(f"/markets/{u['market']}/orderbook?depth=50")
    if not r or "orderbook_fp" not in r:
        return None
    ob = r["orderbook_fp"] or {}
    yes_bids = [(float(p), float(s)) for p, s in (ob.get("yes_dollars") or [])]
    no_bids = [(float(p), float(s)) for p, s in (ob.get("no_dollars") or [])]
    if u["side"] == "yes":                      # selling YES: our competition is NO bids (YES asks at 1 - p)
        bids, asks = yes_bids, [(round(1 - p, 4), s) for p, s in no_bids]
    else:
        bids, asks = no_bids, [(round(1 - p, 4), s) for p, s in yes_bids]
    return book_stats(bids, asks)


def pm_books(us):
    out = {}
    for i in range(0, len(us), 40):
        chunk = us[i:i + 40]
        r = get("https://clob.polymarket.com/books", "pm", 0.2, data=[{"token_id": u["token"]} for u in chunk])
        if not r:
            continue
        by = {b.get("asset_id"): b for b in r}
        for u in chunk:
            b = by.get(u["token"])
            if not b:
                continue
            bids = [(float(x["price"]), float(x["size"])) for x in b.get("bids", [])]
            asks = [(float(x["price"]), float(x["size"])) for x in b.get("asks", [])]
            out[u["market"]] = book_stats(bids, asks)
    return out


def book_stats(bids, asks):
    bids = sorted(bids, key=lambda x: -x[0]); asks = sorted(asks, key=lambda x: x[0])
    if not bids or not asks:
        return None
    return dict(best_bid=bids[0][0], best_ask=asks[0][0], bid_size=bids[0][1], ask_size=asks[0][1],
                ask_depth_to_20c=sum(s for p, s in asks if p <= PRICE_HI), bid_depth=sum(s for p, s in bids), asks=asks, bids=bids)


def kalshi_trades(u, since_ts):
    r = kget(f"/markets/trades?ticker={u['market']}&limit=1000" + (f"&min_ts={since_ts}" if since_ts else ""))
    out = []
    for t in (r or {}).get("trades", []):
        ts = int(dt.datetime.fromisoformat(t["created_time"].replace("Z", "+00:00")).timestamp())
        taker_side = t.get("taker_side")
        price = float(t["yes_price_dollars"]) if taker_side == "yes" else float(t["no_price_dollars"])
        out.append(dict(trade_id=t["trade_id"], ts=ts, taker_buys_longshot=int(taker_side == u["side"]), price=price, size=float(t.get("count_fp") or 0)))
    return out


def pm_trades(u, since_ts):
    r = get(f"https://data-api.polymarket.com/trades?market={u['condition']}&limit=500", "pm", 0.2) or []
    out = []
    for t in r:
        ts = int(t.get("timestamp") or 0)
        if ts <= since_ts:
            continue
        buys_longshot = (t.get("asset") == u["token"] and t.get("side") == "BUY") or (t.get("asset") == u["other_token"] and t.get("side") == "SELL")
        price = float(t["price"]) if t.get("asset") == u["token"] else 1 - float(t["price"])
        out.append(dict(trade_id=t.get("transactionHash", "") + ":" + str(t.get("asset"))[:8] + ":" + str(ts) + ":" + str(t.get("size")), ts=ts, taker_buys_longshot=int(bool(buys_longshot)), price=price, size=float(t.get("size") or 0)))
    return out


# ---------- paper orders ----------
def place_orders(con, u, book, now):
    live = con.execute("SELECT kind FROM orders WHERE platform=? AND market=? AND status='live'", (u["platform"], u["market"])).fetchall()
    have = {k for (k,) in live}
    npos = con.execute("SELECT COUNT(*) FROM positions WHERE platform=? AND market=?", (u["platform"], u["market"])).fetchone()[0]
    if npos >= MAX_POSITIONS:
        return
    tick = 0.01
    if "join" not in have:
        con.execute("INSERT INTO orders(platform,market,side,kind,price,size,remaining,queue_ahead,placed_ts,status) VALUES(?,?,?,?,?,?,?,?,?,'live')",
                    (u["platform"], u["market"], u["side"], "join", book["best_ask"], ORDER_SIZE, ORDER_SIZE, book["ask_size"], now))
    if "improve" not in have and book["best_ask"] - book["best_bid"] > tick + 1e-9:
        con.execute("INSERT INTO orders(platform,market,side,kind,price,size,remaining,queue_ahead,placed_ts,status) VALUES(?,?,?,?,?,?,?,?,?,'live')",
                    (u["platform"], u["market"], u["side"], "improve", round(book["best_ask"] - tick, 4), ORDER_SIZE, ORDER_SIZE, 0.0, now))


def advance_orders(con, u, new_trades):
    orders = con.execute("SELECT id, price, remaining, queue_ahead, placed_ts FROM orders WHERE platform=? AND market=? AND status='live'", (u["platform"], u["market"])).fetchall()
    for oid, price, remaining, queue, placed in orders:
        for t in sorted(new_trades, key=lambda x: x["ts"]):
            if t["ts"] < placed or not t["taker_buys_longshot"] or t["price"] < price - 1e-9:
                continue
            qty = t["size"]
            take = min(qty, queue); queue -= take; qty -= take
            if qty > 0 and remaining > 0:
                f = min(qty, remaining); remaining -= f
                con.execute("INSERT INTO fills(order_id, ts, price, size) VALUES(?,?,?,?)", (oid, t["ts"], price, f))
                if remaining <= 1e-9:
                    con.execute("UPDATE orders SET status='filled', filled_ts=?, remaining=0, queue_ahead=? WHERE id=?", (t["ts"], queue, oid))
                    con.execute("INSERT INTO positions(platform,market,side,price,size,opened_ts) VALUES(?,?,?,?,?,?)", (u["platform"], u["market"], u["side"], price, ORDER_SIZE, t["ts"]))
                    break
        else:
            con.execute("UPDATE orders SET remaining=?, queue_ahead=? WHERE id=?", (remaining, queue, oid))


def resolve_positions(con, now):
    rows = con.execute("SELECT DISTINCT platform, market FROM positions WHERE result IS NULL").fetchall()
    for platform, market in rows:
        if platform == "kalshi":
            r = kget(f"/markets/{market}")
            m = (r or {}).get("market") or {}
            if m.get("status") in ("settled", "finalized") and m.get("result") in ("yes", "no"):
                settle(con, platform, market, m["result"], now)
        else:
            r = get(f"https://gamma-api.polymarket.com/markets?condition_ids={market}", "pm", 0.2)
            m = r[0] if r else {}
            try:
                prices = json.loads(m.get("outcomePrices") or "[]")
            except Exception:
                prices = []
            if m.get("closed") and set(prices) == {"0", "1"}:
                settle(con, platform, market, "yes" if prices[0] == "1" else "no", now)


def settle(con, platform, market, result, now):
    for pid, side, price, size in con.execute("SELECT id, side, price, size FROM positions WHERE platform=? AND market=? AND result IS NULL", (platform, market)).fetchall():
        pnl = size * (price if result != side else -(1 - price))     # short the longshot: keep the premium if it loses
        con.execute("UPDATE positions SET result=?, pnl=?, resolved_ts=? WHERE id=?", (result, pnl, now, pid))
    con.execute("UPDATE orders SET status='closed' WHERE platform=? AND market=? AND status='live'", (platform, market))


# ---------- main loop ----------
def cycle(con, universe, now):
    kal = [u for u in universe if u["platform"] == "kalshi"]; pm = [u for u in universe if u["platform"] == "pm"]
    books = pm_books(pm)
    for u in universe:
        book = kalshi_book(u) if u["platform"] == "kalshi" else books.get(u["market"])
        if not book:
            continue
        con.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?)", (now, u["platform"], u["market"], u["side"], book["best_bid"], book["best_ask"], book["bid_size"], book["ask_size"], book["ask_depth_to_20c"], book["bid_depth"]))
        row = con.execute("SELECT last_ts FROM cursors WHERE platform=? AND market=?", (u["platform"], u["market"])).fetchone()
        since = row[0] if row else now - 3600
        trades = kalshi_trades(u, since) if u["platform"] == "kalshi" else pm_trades(u, since)
        new = []
        for t in trades:
            try:
                con.execute("INSERT INTO trades VALUES(?,?,?,?,?,?,?)", (u["platform"], u["market"], t["trade_id"], t["ts"], t["taker_buys_longshot"], t["price"], t["size"]))
                new.append(t)
            except sqlite3.IntegrityError:
                pass
        if trades:
            con.execute("INSERT OR REPLACE INTO cursors VALUES(?,?,?)", (u["platform"], u["market"], max(t["ts"] for t in trades)))
        advance_orders(con, u, new)
        if now < u["close_ts"] and PRICE_LO <= book["best_ask"] <= PRICE_HI + 0.05:
            place_orders(con, u, book, now)
        con.commit()


def main():
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    con = db()
    universe, last_universe = [], 0
    log("recorder started")
    while True:
        now = int(time.time())
        try:
            if now - last_universe >= UNIVERSE_S or not universe:
                universe = kalshi_universe(now) + pm_universe(now)
                last_universe = now
                con.executemany("INSERT INTO universe VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", [(now, u["platform"], u["market"], u["title"], u["category"], u["side"], u["token"], u["other_token"], u["condition"], u["close_ts"], u["vol24"], u["price"]) for u in universe])
                con.commit()
                log(f"universe: {sum(u['platform']=='kalshi' for u in universe)} kalshi + {sum(u['platform']=='pm' for u in universe)} polymarket markets")
            t0 = time.time()
            cycle(con, universe, now)
            resolve_positions(con, now)
            live = con.execute("SELECT COUNT(*) FROM orders WHERE status='live'").fetchone()[0]
            filled = con.execute("SELECT COUNT(*) FROM orders WHERE status='filled'").fetchone()[0]
            log(f"cycle done in {time.time() - t0:.0f}s: {live} live paper orders, {filled} filled so far")
        except Exception as e:
            log(f"error: {type(e).__name__}: {e}")
        if "--once" in sys.argv:
            break
        time.sleep(max(10, CYCLE_S - (time.time() - now)))


if __name__ == "__main__":
    main()

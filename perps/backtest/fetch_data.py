"""Download the public Deribit data the backtest needs into backtest/data/ (cached; safe to re-run)."""
import json, os, time, urllib.request, urllib.parse, datetime as dt
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
START = dt.date(2023, 1, 6)          # first Friday of the weekly test
DAILY_FROM = dt.date(2025, 8, 25)    # daily cross-sections for the calibration test
END = dt.date(2026, 9, 29)
UTC = dt.timezone.utc


def get(host, method, **params):
    url = f"https://{host}/api/v2/public/{method}?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)["result"]
        except Exception as e:  # rate limit or transient network error
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed: {url}")


def ms(d, hour=0, minute=0):
    return int(dt.datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC).timestamp() * 1000)


def fetch_option_window(d):
    """Option trades between 08:05 and 10:05 UTC, just after the daily 08:00 expiry."""
    path = os.path.join(DATA, "trades", f"{d}.json")
    if os.path.exists(path):
        return
    start, end, rows = ms(d, 8, 5), ms(d, 10, 5), []
    for _ in range(4):
        r = get("history.deribit.com", "get_last_trades_by_currency_and_time", currency="BTC", kind="option",
                start_timestamp=start, end_timestamp=end, count=1000, sorting="asc")
        rows += [[t["timestamp"], t["instrument_name"], t["price"], t.get("iv"), t["index_price"], t["amount"]] for t in r["trades"]]
        if not r.get("has_more") or not r["trades"]:
            break
        start = r["trades"][-1]["timestamp"] + 1
    json.dump(rows, open(path, "w"))


def fetch_hourly():
    path = os.path.join(DATA, "hourly.json")
    if os.path.exists(path):
        return
    perp, fund = {}, {}
    d = START - dt.timedelta(days=400)   # extra history for trailing realized vol
    while d <= END:
        e = min(d + dt.timedelta(days=20), END + dt.timedelta(days=1))
        c = get("www.deribit.com", "get_tradingview_chart_data", instrument_name="BTC-PERPETUAL",
                start_timestamp=ms(d), end_timestamp=ms(e), resolution=60)
        perp.update(zip(c["ticks"], c["close"]))
        for f in get("www.deribit.com", "get_funding_rate_history", instrument_name="BTC-PERPETUAL",
                     start_timestamp=ms(d), end_timestamp=ms(e)):
            fund[f["timestamp"]] = [f["index_price"], f["interest_1h"]]
        d = e
    ts = sorted(set(perp) & set(fund))
    json.dump([[t, perp[t], fund[t][0], fund[t][1]] for t in ts], open(path, "w"))


def fetch_delivery():
    path = os.path.join(DATA, "delivery.json")
    if os.path.exists(path):
        return
    out, off = {}, 0
    while True:
        r = get("www.deribit.com", "get_delivery_prices", index_name="btc_usd", offset=off, count=1000)
        for x in r["data"]:
            out[x["date"]] = x["delivery_price"]
        off += 1000
        if off >= r["records_total"]:
            break
    json.dump(out, open(path, "w"))


if __name__ == "__main__":
    os.makedirs(os.path.join(DATA, "trades"), exist_ok=True)
    days, d = [], START
    while d <= END:
        if d >= DAILY_FROM or d.weekday() == 4:
            days.append(d)
        d += dt.timedelta(days=1)
    fetch_delivery(); print("delivery prices done", flush=True)
    fetch_hourly(); print("hourly perp, index and funding done", flush=True)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(fetch_option_window, days))
    print("option windows done:", len(days), flush=True)

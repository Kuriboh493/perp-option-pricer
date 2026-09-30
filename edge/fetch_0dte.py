"""Deribit BTC option trades 02:00-04:00 UTC, about five hours before the 08:00 UTC daily expiry.
Keeps trade direction and mark price so the effective spread can be measured."""
import json, os, sys, datetime as dt
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backtest"))
from fetch_data import get, ms

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "deribit_0dte")


def fetch(d):
    path = os.path.join(OUT, f"{d}.json")
    if os.path.exists(path):
        return
    start, end, rows = ms(d, 2), ms(d, 4), []
    for _ in range(4):
        r = get("history.deribit.com", "get_last_trades_by_currency_and_time", currency="BTC", kind="option",
                start_timestamp=start, end_timestamp=end, count=1000, sorting="asc")
        rows += [[t["timestamp"], t["instrument_name"], t["price"], t.get("iv"), t["index_price"], t["amount"],
                  1 if t["direction"] == "buy" else -1, t.get("mark_price")] for t in r["trades"]]
        if not r.get("has_more") or not r["trades"]:
            break
        start = r["trades"][-1]["timestamp"] + 1
    json.dump(rows, open(path, "w"))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    days, d = [], dt.date(2025, 3, 1)
    while d <= dt.date(2026, 9, 29):
        days.append(d); d += dt.timedelta(days=1)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(fetch, days))
    print("done", len(days), flush=True)

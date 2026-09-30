"""Deribit DVOL (30-day implied vol index) hourly, as a market-implied volatility input."""
import json, os, sys, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "perps", "backtest"))
from fetch_data import get, ms

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "dvol.json")
if __name__ == "__main__":
    rows, d = [], dt.date(2024, 12, 1)
    while d <= dt.date(2026, 9, 30):
        e = min(d + dt.timedelta(days=40), dt.date(2026, 10, 1))
        r = get("www.deribit.com", "get_volatility_index_data", currency="BTC", resolution=3600, start_timestamp=ms(d), end_timestamp=ms(e))
        rows += [[x[0], x[4]] for x in r["data"]]      # [ts, close]
        d = e
    rows = sorted({r[0]: r for r in rows}.values())
    json.dump(rows, open(OUT, "w")); print(len(rows), "hours", rows[0], rows[-1])

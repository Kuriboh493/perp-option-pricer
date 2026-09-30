# Live paper-trading recorder: far-dated longshots

Measures the two things the trade surveys cannot: whether resting offers on far-dated longshots get lifted, and how much of that flow exists. Reads only public endpoints; sends no orders.

Every five minutes `recorder.py`:

1. refreshes a universe of open Kalshi and Polymarket markets resolving 7–180 days out whose cheaper side is quoted at 3–20¢, in the non-sports, non-crypto categories (top 120 per platform by 24-hour volume);
2. snapshots each order book (touch sizes, ask depth up to 20¢, total bid depth);
3. pulls new trades and records whether the taker bought the longshot side;
4. advances two virtual offers per market of 100 contracts each, one joining the best ask and one a tick inside it, with a queue model: printed buys at or above the offer price first consume the size that was ahead, then fill the order;
5. checks resolutions for filled positions and books the P&L (a short longshot keeps the premium when it loses, pays `1 − p` when it hits).

State is `data/recorder.db` (SQLite: universe, snapshots, trades, orders, fills, positions) and `data/recorder.log`.

```
../../.venv/bin/python recorder.py --once      # one cycle in the foreground (~3 min)
../../.venv/bin/python report.py               # fills, capacity, adverse selection, P&L
```

It runs continuously under launchd: `com.noahsolomon.longshot-recorder.plist` (copy to `~/Library/LaunchAgents/` and `launchctl load` it; `launchctl unload` stops it). Fill rates mean something after a few days; P&L only once positions resolve, weeks out.

Limitations: the queue model is approximate (it cannot see cancellations ahead of the order); Polymarket trades come from the data API with second resolution; the universe is capped, so capacity numbers are for the tracked markets only.

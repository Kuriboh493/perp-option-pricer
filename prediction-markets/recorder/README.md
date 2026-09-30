# Live paper-trading recorder

Paper-trades the two strategies from this research live, to measure what backtests cannot: real fill rates, available size, and P&L as positions resolve. Reads only public endpoints; sends no orders.

| Strategy | Rule | What it measures |
|---|---|---|
| Far-dated longshots | Rest offers on the 3–20¢ side of markets 7–180 days from resolution (from [../retail-survey/](../retail-survey/)) | Whether offers get lifted, how much flow exists |
| BTC daily favourites | At 1pm ET, rest a bid on the favourite side of every Kalshi "Bitcoin above $X at 5pm" strike within 3% of spot quoted beyond 80/20, and record the taker alternative (from [../kalshi-btc/](../kalshi-btc/)) | Live fill rate and ¢/contract against the backtest's 2.7¢ taker / 4.65¢ resting |

## Far-dated longshots

Every five minutes `recorder.py`:

1. refreshes a universe of open Kalshi and Polymarket markets resolving 7–180 days out whose cheaper side is quoted at 3–20¢, in the non-sports, non-crypto categories (top 120 per platform by 24-hour volume);
2. snapshots each order book (touch sizes, ask depth up to 20¢, total bid depth);
3. pulls new trades and records whether the taker bought the longshot side;
4. advances two virtual offers per market of 100 contracts each, one joining the best ask and one a tick inside it, with a queue model: printed buys at or above the offer price first consume the size that was ahead, then fill the order;
5. checks resolutions for filled positions and books the P&L (a short longshot keeps the premium when it loses, pays `1 − p` when it hits).

## BTC daily favourites

Once a day, in the first cycle at or after four hours before the 5pm ET close, `btc_place` reads the day's KXBTCD strikes and Coinbase spot. For every strike within 3% of spot whose mid is at least 80¢ or at most 20¢ it records two 100-contract paper trades on the favourite side: a *taker* buy at the ask (charged Kalshi's taker fee) and a *resting* buy at the best bid, queued behind the size already there. `btc_advance` fills resting bids from printed trades where takers sold the favourite at or below the bid, and cancels whatever is left after an hour, matching the backtest. Positions settle when Kalshi resolves the contract, usually minutes after the close.

## Running it

State is `data/recorder.db` (SQLite: universe, snapshots, trades, orders, fills, positions) and `data/recorder.log`.

```
../../.venv/bin/python recorder.py --once      # one cycle in the foreground (~3 min)
../../.venv/bin/python report.py               # fills, capacity, adverse selection, P&L
```

It runs continuously under launchd: `com.noahsolomon.longshot-recorder.plist` (copy to `~/Library/LaunchAgents/` and `launchctl load` it; `launchctl unload` stops it). Fill rates mean something after a few days; P&L only once positions resolve, weeks out.

Limitations: the queue model is approximate (it cannot see cancellations ahead of the order); Polymarket trades come from the data API with second resolution; the universe is capped, so capacity numbers are for the tracked markets only.

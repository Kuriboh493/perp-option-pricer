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

## Adverse selection on the BTC maker fills

The resting-bid edge measured in the backtest (fill price about 2¢ below the Deribit-implied fair value) only counts if it survives what the market learns from the trade that filled us. Three pieces measure that:

- **`hf_sampler.py`** (own launchd job, `com.noahsolomon.btc-hf-sampler`) runs each day from five minutes before placement to two minutes after the 5pm ET close and writes `data/hf.db`:
  - Kalshi top of book for every strike within 5% of spot: every 2 s for 110 minutes, then every 5 s; only changes plus a 60 s heartbeat.
  - Every trade on tickers with live resting orders.
  - Coinbase spot every second.
  - Deribit mark IVs for the first daily expiry after the Kalshi close, every 30 s.

  All timestamps are local receive times; Kalshi trades also keep the exchange time. Storage is well under 1 MB a day.
- **`btc_advance` in `recorder.py`** now keeps sub-second fill times, records every partial fill with the trade that caused it (`fills.trade_id`, `fills.trade_size`), and books a `join_partial` position when an order expires partly filled. The queue rule is unchanged and lives in `btc_maker.replay_fills`.
- **`markouts.py`** builds one record per fill (quotes and fair value immediately before, spot, strike, time to settlement, settlement value) and computes:
  - fair-value markouts at 1 s, 10 s, 1 m, 5 m and 30 m;
  - Kalshi-mid and spot moves at the same horizons;
  - execution edge, and net maker edge = execution edge + markout.

  Results are grouped by price, distance from spot in standard deviations, time to expiry, queue ahead, size of the filling trade, and whether BTC was moving toward the strike in the minute before.

Definitions (per contract, cents):

| Quantity | Definition |
|---|---|
| Fair value FV(t) | Deribit-implied probability our side pays, from the smile and spot received at or before t (`btc_maker.prob_above`) |
| Execution edge | FV(fill) − fill price, split into (FV − Kalshi mid before fill) + (mid − fill price) |
| Markout_h | FV(fill + h) − FV(fill); negative = toxic fill |
| Control drift_h | the same markout from random moments while the order rested unfilled, with the whole window before the fill |
| Adverse selection_h | mean fill markout − mean control drift |
| Net maker edge_h | execution edge + markout_h = FV(fill + h) − fill price |

The control matters because a favourite's fair value drifts with no information at all (time decay and the volatility premium accruing). The from-placement markout is also reported, as E[value change | posted].

Report: `reports/markouts.md` with seven plots:

1. markouts by horizon against the control
2. 1 m and 5 m markout distributions
3. execution edge vs markout
4. markout by queue depth
5. realized P&L vs execution edge
6. cumulative P&L of filled orders
7. the edge-decay curve from fill to settlement

The 30-minute decomposition separates directly measured quantities from inferred interpretations:

- **The 1 s and 10 s horizons are approximate:** Kalshi is polled every 2 s and its exchange clock is not synchronised with local receive times.
- **"Behavioral mispricing" is not cleanly identified:** FV − mid also contains fair-value model error.
- **The volatility premium is very noisy per fill.** It is computed as control drift plus the residual to settlement.

`python markouts.py --fill-model through` re-derives fills from the stored trades with a price-through rule. This checks how much the conservative queue model, which favours large sweeping trades, skews the measured toxicity.

## Running it

State is `data/recorder.db` (SQLite: universe, snapshots, trades, orders, fills, positions) and `data/recorder.log`.

```
../../.venv/bin/python recorder.py --once      # one cycle in the foreground (~3 min)
../../.venv/bin/python report.py               # fills, capacity, adverse selection, P&L
../../.venv/bin/python markouts.py             # BTC maker markouts and edge decay -> reports/markouts.md
../../.venv/bin/python markouts.py --synthetic # same pipeline on synthetic data with known adverse selection
../../.venv/bin/python -m unittest test_btc_maker -v
```

Both run continuously under launchd: `com.noahsolomon.longshot-recorder.plist` and `com.noahsolomon.btc-hf-sampler.plist` (copy to `~/Library/LaunchAgents/` and `launchctl load` them; `launchctl unload` stops them). Fill rates mean something after a few days; P&L only once positions resolve, weeks out.

Limitations: the queue model is approximate (it cannot see cancellations ahead of the order); Polymarket trades come from the data API with second resolution; the universe is capped, so capacity numbers are for the tracked markets only.

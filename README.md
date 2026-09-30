# Perps and prediction markets

Two lines of work that started from one question, "can a pricing model beat the market?", and ended in different places.

| | What it is | Answer |
|---|---|---|
| [perps/](perps/) | A pricer for options on perpetual swaps (crypto and real-world assets), its Deribit backtest, and a 0DTE test | The model gives consistent prices and Greeks once fitted, but it is not a trading signal: no edge after costs on weekly, daily or 0DTE options. |
| [prediction-markets/](prediction-markets/) | Where retail loses on Kalshi and Polymarket: every trade 2021–2026, quote-level tests on crypto contracts, and a live paper-trading recorder | Short-dated crypto contracts are efficient. The money is in longshots priced a week or more from resolution: buyers lose 55–80% of stake on Kalshi and 35–55% on Polymarket, every year, in economics and politics above all. |
| [common/](common/) | The BTC short-horizon volatility forecaster both sides use | |

## Map

```
perps/
  index.html            the pricer (live copy: https://claude.ai/artifact/2SWRtaixcgxfD3eXhZvXXy)
  backtest/             Deribit BTC options, 2023–2026: weekly straddles, daily calibration, structural checks
  zero-dte/             5-hour straddles into the daily expiry, with measured costs
prediction-markets/
  retail-survey/        every Kalshi trade and Polymarket fill, scored from the taker's side; event-level risk
  kalshi-btc/           Kalshi's daily BTC contracts with quotes: favourite-longshot rule, resting orders, de-biased market
  short-dated-crypto/   Kalshi hourly/15-minute series and Polymarket Up/Down windows with minute prices
  recorder/             live paper-trading recorder for the far-dated longshot pool (runs under launchd)
common/
  volfc.py              seasonal HAR volatility forecast for BTC on Deribit hourly data
```

Each folder has a README with how to run it, results and limitations. Downloaded data (about 90 GB in total, mostly the [Becker dataset](https://github.com/jon-becker/prediction-market-analysis)) is ignored by git and recreated by the `fetch_*.py` scripts.

## Setup

```
python -m venv .venv && .venv/bin/pip install numpy scipy pandas pyarrow
```

Scripts are run from their own folder with that interpreter. The pricer is a single HTML file with no dependencies.

## Headline numbers

- Kalshi takers lose 4.0% of every dollar after fees ($330M on $8.15B, 2021–Jan 2026). Polymarket takers break even before fees (+0.3% on $20.8B).
- Kalshi non-sports longshots (5–20¢) bought more than a week before resolution lose 57–80% of stake; inside the final hour, 6–18%.
- The pricer's own signals never beat market prices; a de-biased market price forecast outcomes better than any model that ignored the market.
- One quote-level edge survived out of sample: taking the favourite side of Kalshi's daily BTC contracts four hours before close, 2.7¢ per contract as a taker and about 4.7¢ with resting orders, with crash risk and unknown capacity.

This is research, not investment advice.

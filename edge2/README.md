# Where does retail lose in event contracts?

A search across Kalshi and Polymarket, all categories, for segments where retail takers systematically overpay, using every recorded trade rather than a model. Companion to [../edge/](../edge/), which tested one crypto series with quotes and execution.

Data: the [Becker prediction-market dataset](https://github.com/jon-becker/prediction-market-analysis) (every Kalshi trade and Polymarket on-chain fill, 2021 to January 2026, 36 GB), plus samples pulled from the Kalshi and Polymarket APIs for 2026. The downloaded data is not committed; `fetch_*.py` and the survey scripts recreate everything.

## Run it

```
python -m venv .venv && .venv/bin/pip install numpy scipy pandas pyarrow
curl -o data/becker.tar.zst https://s3.jbecker.dev/data.tar.zst
mkdir -p data/becker && tar --use-compress-program=unzstd -xf data/becker.tar.zst -C data/becker data/kalshi data/polymarket/markets data/polymarket/trades data/polymarket/blocks
.venv/bin/python kalshi_survey.py && .venv/bin/python kalshi_survey_report.py      # every Kalshi trade, ~1.5 h
.venv/bin/python kalshi_events_scan.py && .venv/bin/python kalshi_events_report.py # event-level risk view, ~1.5 h
.venv/bin/python pm_survey.py && .venv/bin/python pm_survey_report.py              # every Polymarket fill, ~1 h
.venv/bin/python fetch_prices.py fetch_1m.py fetch_btc_1m.py fetch_dvol.py        # spot prices for the model tests
.venv/bin/python fetch_kalshi_recent.py && .venv/bin/python kalshi_recent_edge.py  # Kalshi hourly/15-minute series, Aug-Sep 2026
.venv/bin/python fetch_polymarket.py && .venv/bin/python polymarket_edge.py        # Polymarket Up/Down windows with minute prices
```

## Kalshi: every trade, 2021 to January 2026

67.7 million trades, $8.15 billion staked by takers. Each trade is scored from the taker's side: what they paid, what the contract paid out, minus Kalshi's 7% taker fee. The maker's gross gain is the mirror image before any maker fee.

**Takers lost 4.0% of every dollar staked after fees: $330M in total, $187M of it fees and $142M to the makers on the other side.** The loss is not spread evenly.

### By price paid

| Taker price (¢) | Trades | Staked | Taker return after fee | Maker gross ¢/contract |
|---|---|---|---|---|
| 0–5 | 3.56M | $35.9M | −49.5% | 0.88 |
| 5–10 | 3.49M | $71.1M | −41.4% | 2.40 |
| 10–20 | 6.32M | $217.6M | −23.3% | 2.48 |
| 20–35 | 10.04M | $586.2M | −5.3% | 0.07 |
| 35–50 | 11.40M | $1,064.1M | −12.1% | 3.43 |
| 50–65 | 11.57M | $1,539.6M | −1.1% | −1.06 |
| 65–80 | 9.18M | $1,491.1M | −3.2% | 0.89 |
| 80–90 | 5.51M | $1,165.7M | −0.8% | −0.26 |
| 90–95 | 2.88M | $742.9M | +0.3% | −0.77 |
| 95–99 | 3.78M | $1,237.2M | +0.1% | −0.26 |

Longshots are where retail bleeds: contracts bought under 10¢ lose 41–50% of the stake, 10–20¢ contracts lose 23%. Favourites above 90¢ are priced fairly to slightly cheap; makers lose on them. The 35–50¢ row is one event, the 2024 presidential election (buyers of 35–50¢ contracts lost $57M), not a pattern.

### By category (≥ $2M staked)

| Category | Trades | Staked | Taker return after fee | Maker gross ¢/contract | Maker gross |
|---|---|---|---|---|---|
| Exotics (parlays) | 0.38M | $16.2M | −22.7% | 1.61 | $3.0M |
| Mentions | 1.48M | $41.9M | −7.3% | 2.01 | $2.3M |
| Companies | 0.06M | $3.9M | −6.9% | 2.28 | $0.2M |
| Economics | 1.24M | $181.9M | −5.6% | 1.54 | $7.2M |
| Entertainment | 1.68M | $84.9M | −4.8% | 1.31 | $2.6M |
| Sports | 43.23M | $6,107.1M | −4.1% | 0.80 | $101.5M |
| Climate and Weather | 4.47M | $116.1M | −4.0% | 0.96 | $2.7M |
| Elections | 0.89M | $244.1M | −3.7% | 1.03 | $5.7M |
| Crypto | 6.63M | $406.9M | −3.7% | 0.85 | $6.6M |
| Politics | 3.82M | $667.2M | −3.5% | 0.77 | $11.0M |
| Financials | 2.06M | $204.7M | −2.0% | 0.14 | $0.6M |

### By time to close

| Time to close | Trades | Staked | Taker return after fee | Maker gross ¢/contract |
|---|---|---|---|---|
| < 1 h | 18.79M | $2,187.2M | −2.6% | 0.34 |
| 1–6 h | 24.91M | $3,477.8M | −4.4% | 0.85 |
| 6–24 h | 9.94M | $765.3M | −5.7% | 1.47 |
| 1–7 d | 7.31M | $610.0M | −5.9% | 1.49 |
| > 7 d | 6.79M | $1,111.2M | −3.6% | 0.80 |

Prices are worst a day to a week before close and best in the final hour.

### The repeatable pools

Segments where takers lose heavily in every year with meaningful volume. "Mispricing" is the taker loss before the taker fee (what a maker collects); "maker net" charges the 1.75% maker fee on every contract, an upper bound since most series charge makers nothing.

| Pool | 2023 | 2024 | 2025 | 2025 staked | 2025 maker net |
|---|---|---|---|---|---|
| Economics longshots (< 20¢: Fed decisions, CPI, payrolls, gas) | −60% | −27% | −90% | $12.6M | $11.1M (5.3¢/contract) |
| Politics + Elections longshots (< 20¢) | −3% | −61% | −70% | $16.5M | $11.2M (4.6¢) |
| Sports longshots (< 20¢) | – | – | −14% | $222.5M | $27.9M (1.1¢) |
| Sports longshots, more than a week out | – | – | −31% to −78% | $11.2M | $4.5M (3.4¢) |
| Crypto longshots (< 20¢) | – | −13% | −10% | $12.0M | $1.0M (0.9¢) |
| Entertainment longshots (< 20¢) | – | −24% | −30% | $3.5M | $1.0M (1.6¢) |
| Parlays (Exotics) | – | – | −18% | $16.2M | $2.7M (1.5¢) |
| Mentions ("will X say Y") | – | – | −5% | $41.9M | $2.1M (1.8¢) |
| Weather, all prices | +2% | −4% | −2% | $68.8M | $1.4M (0.8¢) |

Two cautions. The Economics and Politics pools are made of few events (eight Fed meetings a year, one presidential election), so their losses are lumpy and a single surprise pays longshot holders many times over; the event-level scan below measures that. And "maker" here means whoever was on the other side, mostly professional market makers; a new maker competes with them for fills.

The Weather pool is instructive about decay: in 2024, takers overpaid for 65–90¢ weather favourites by 10% (makers earned 7–8¢ a contract); by 2025 the same buckets were within 2–3% of fair.

(Sections on event-level risk, Polymarket, and the 2026 execution tests follow once those runs finish.)

# Retail survey: every trade on Kalshi and Polymarket

A search across Kalshi and Polymarket, all categories, for segments where retail takers systematically overpay, using every recorded trade rather than a model. Companions: [../kalshi-btc/](../kalshi-btc/) tests one series with quotes and execution; [../short-dated-crypto/](../short-dated-crypto/) tests the newer hourly and 15-minute markets; [../recorder/](../recorder/) measures fills live.

Data: the [Becker prediction-market dataset](https://github.com/jon-becker/prediction-market-analysis) (every Kalshi trade and Polymarket on-chain fill, 2021 to January 2026, 36 GB), plus samples pulled from the Kalshi and Polymarket APIs for 2026. The downloaded data is not committed; `fetch_*.py` and the survey scripts recreate everything.

## Run it

```
curl -o data/becker.tar.zst https://s3.jbecker.dev/data.tar.zst          # 36 GB
mkdir -p data/becker && tar --use-compress-program=unzstd -xf data/becker.tar.zst -C data/becker data/kalshi data/polymarket/markets data/polymarket/trades data/polymarket/blocks
../../.venv/bin/python kalshi_survey.py && ../../.venv/bin/python kalshi_survey_report.py      # every Kalshi trade, ~1.5 h
../../.venv/bin/python kalshi_events_scan.py && ../../.venv/bin/python kalshi_events_report.py # event-level risk view, ~1.5 h
../../.venv/bin/python pm_survey.py && ../../.venv/bin/python pm_survey_report.py              # every Polymarket fill, ~1 h
```

`kalshi_survey.py` also needs `data/kalshi_series.json`, the series-to-category map from Kalshi's `/series` endpoint (the first run of the recorder or the snippet in the git history rebuilds it).

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

## Polymarket: every on-chain fill, 2023 to January 2026

208 million fills, $20.8 billion staked by takers, scored the same way (gross, since most Polymarket markets charged no fee in this period; crypto takers now pay the same 7% formula as Kalshi). Categories are keyword-classified from the market slug, so "other" is large.

**Takers roughly break even overall (+0.3% gross), but the favourite-longshot bias is stronger than on Kalshi.** Contracts bought under 10¢ lose 27–32% of stake; buyers of 80–95¢ favourites earn 2.6–3.4%, so makers lose there.

| Taker price (¢) | Staked | Taker return (gross) |
|---|---|---|
| 0–5 | $75.5M | −26.8% |
| 5–10 | $71.5M | −31.6% |
| 10–20 | $188.5M | −11.8% |
| 20–35 | $565.3M | −0.5% |
| 35–50 | $1,770.7M | −11.2% (2024 election) |
| 50–65 | $2,478.5M | +9.2% (2024 election) |
| 65–80 | $1,388.3M | +1.7% |
| 80–90 | $1,069.8M | +2.6% |
| 90–95 | $913.1M | +3.4% |
| 95–99 | $12,246.9M | +0.1% |

### Where the longshot loss lives: long-dated contracts

Polymarket longshots in 2025, by time to resolution:

| Time to close | < 5¢ | 5–10¢ | 10–20¢ |
|---|---|---|---|
| < 1 h | +34% | −4% | −4% |
| 1–6 h | +6% | +4% | 0% |
| 6–24 h | −25% | −4% | 0% |
| 1–7 d | −40% | −28% | −9% |
| > 7 d | −56% ($25M) | −51% ($23M) | −35% ($59M) |

Short-dated longshots (the crypto Up/Down windows, in-game sports) are priced about fairly. The money is in "will X happen by [date]" contracts weeks or months out, priced at a few cents, that almost never happen. Part of that premium is real: the seller's collateral is locked until resolution.

### The repeatable pools (taker loss before fees, by year)

| Pool | 2024 | 2025 | 2026 (Jan) | 2025 staked | 2025 maker gross | Concentration |
|---|---|---|---|---|---|---|
| Finance longshots (< 20¢: Fed decision sizes, "no change" contracts) | −43% | −78% | −75% | $20.3M | $15.8M | top family 48% (the Fed-cut ladder), 16% of markets lost |
| Politics longshots (< 20¢) | −20% | −45% | −86% | $43.8M | $19.7M | top market 26% (NYC mayor), 14% of markets lost |
| Entertainment longshots (< 20¢) | +30% | −37% | −26% | $4.7M | $1.7M | top market 28% (TikTok ban) |
| Crypto longshots (< 20¢) | −11% | −13% | **+18%** | $59.0M | $7.8M | top family 19% |
| Sports longshots (< 20¢) | **+39%** | −5% | **+11%** | $50.5M | $2.5M | top-5 markets 97% |
| All longshots < 10¢ | −21% | −37% | −9% | $88.4M | $32.5M | top market 13% |

Finance and politics longshots lose in every year; sports and crypto longshots on Polymarket flip sign between years (a few big upsets pay them), so they are not a pool to sell blindly. The crypto Up/Down families (15-minute, hourly, daily) net to zero for takers on $1.3B: those markets are efficient on average, which matches the quote-level tests in [../kalshi-btc/](../kalshi-btc/) and [../short-dated-crypto/](../short-dated-crypto/).

## The common thread: longshots priced weeks out

On both platforms the longshot overpricing grows with time to resolution. Kalshi 2025, non-sports longshots, taker loss before fees:

| Time to close | < 5¢ | 5–10¢ | 10–20¢ |
|---|---|---|---|
| < 1 h | −15% | −18% | −6% |
| 1–6 h | −39% | −47% | −36% |
| 6–24 h | −62% | −53% | −26% |
| 1–7 d | −73% | −79% | −57% |
| > 7 d | −75% | −80% | −70% |

Polymarket shows the same gradient (above). A contract priced at 5–20¢ with a week or more to run loses its buyer 55–80% of the stake on Kalshi and 35–55% on Polymarket. Sports is the exception where even the final hour is bad for longshot buyers (Kalshi sports 5–20¢ inside an hour: −18% to −31%, on $74M).

## Event-level risk of the Kalshi pools (`kalshi_events_report.py`)

The pools above are attractive on average; the question is how lumpy. From the event × month scan, since January 2024:

| Pool | Events | Maker gross | Months positive | Monthly t | Worst month | Top event's share | Top-5 share |
|---|---|---|---|---|---|---|---|
| Economics longshots | 613 | $11.6M (5.1¢/contract) | 19/23 | 2.8 | −$39k | 33% (Sep 2025 Fed) | 83% |
| Politics + Elections longshots | 1,406 | $27.9M (3.9¢) | 19/23 | 1.9 | −$243k | 20% (2024 presidential) | 58% |
| Sports longshots (5–20¢) | 13,490 | $28.1M (1.6¢) | 8/12 | 1.9 | −$1.6M | 15% | 37% |
| Crypto longshots | 19,820 | $1.7M (1.1¢) | 17/21 | 3.1 | −$124k | 5% | 18% |
| Weather, all prices | 4,509 | $3.0M (1.1¢) | 20/23 | 2.7 | −$14k | 4% | 14% |
| Mentions | 510 | $2.3M (2.0¢) | 8/11 | 2.6 | −$18k | 9% | 21% |
| Entertainment longshots | 2,662 | $1.3M (1.6¢) | 21/23 | 2.2 | −$110k | 17% | 48% |
| BTC daily (KXBTCD), all prices | 5,414 | $4.0M (0.9¢) | 13/14 | 4.7 | −$49k | 5% | 11% |
| Sports main lines 50–80¢ | 15,491 | $49.9M (1.3¢) | 9/12 | 1.7 | −$7.0M | 21% | 83% |

Reading this:

- **The most consistent pools are the diversified ones**: BTC daily (13 of 14 months, t = 4.7), weather (20 of 23), crypto longshots (17 of 21). They are also the smallest in dollars.
- **Economics and politics longshots pay the most per contract but come from few events.** The Economics pool's worst event was the September 2024 Fed meeting, when the 50 bp cut that longshot buyers held actually happened (−$189k for makers). Five events make 83% of the gain.
- **Sports longshots are a positive-expectation, high-variance business.** A single upset (Pacers–Thunder game 5, June 2025) cost makers $4.9M against a $28M total; four months of twelve were losing. Sports main lines are ordinary market-making: makers lose in 58% of events and live on the spread.

## What this says about a strategy

1. The cleanest retail-eating trade on both platforms is **selling long-dated longshots**: post offers at 5–20¢ on "will X happen by [date]" contracts a week or more from resolution, in economics, politics and entertainment, where buyers lose 55–80% of stake. It is lumpy (few events, occasional 5–10× payouts against you), capital is locked until resolution, and on Kalshi you compete with professional makers for the fill; Polymarket makers pay no fee and earn rebates.
2. **Short-dated crypto markets are efficient.** Polymarket's Up/Down families net to zero for takers on $1.3B, and the tests in [../kalshi-btc/](../kalshi-btc/) and [../short-dated-crypto/](../short-dated-crypto/) confirm it at the quote level. Do not expect a pricing model to beat them.
3. **Sports is where the money is, but as a market maker, not a picker**: $101M of maker gross on Kalshi in 2025, mostly spread capture on main lines with large single-event swings. Longshot selling in sports (1.6¢ a contract on $205M) is the retail-facing slice.
4. Favourites above 90¢ are fairly priced on Kalshi and slightly *cheap* on Polymarket (takers earn 2.6–3.4% on 80–95¢). The [../kalshi-btc/](../kalshi-btc/) result (favourites on Kalshi BTC daily earning 2.7–4.7¢ four hours out) is a quote-level, short-horizon version of the same bias.

## Limitations

Categories on Kalshi come from the series API; on Polymarket from slug keywords, so "other" is a grab-bag. Maker gains are gross; Kalshi charges makers 1.75% on flagged series since April 2025 and Polymarket pays makers rebates. "Maker" means whoever took the other side, mostly professionals. Time to close uses the market's listed end date, which Polymarket sometimes sets a few hours off. Survey figures are historical averages, not tradable quotes: capacity and fills are unknown, and several pools depend on a few large events.

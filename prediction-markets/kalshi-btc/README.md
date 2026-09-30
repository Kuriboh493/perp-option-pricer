# Kalshi daily BTC contracts with quotes

A search for a trading edge in Kalshi's daily "Bitcoin above $X at 5pm ET" contracts, using quotes, the pricer's model and the seasonal volatility forecast in [../../common/volfc.py](../../common/volfc.py). The 0DTE options test that shared this code now lives in [../../perps/zero-dte/](../../perps/zero-dte/). Rules were chosen on March–December 2025 and judged only on January–September 2026.

**Result:** the model did not produce an edge that survived costs and out-of-sample testing. One model-free effect did: Kalshi's BTC contracts overprice longshots and underprice favorites.

## Run it

```
../../.venv/bin/python ../../perps/backtest/fetch_data.py   # hourly Deribit index, perp and funding (shared with the backtest)
../../.venv/bin/python fetch_kalshi.py             # Kalshi KXBTCD quotes, paced for the rate limit (about an hour)
../../.venv/bin/python volfc.py                    # volatility forecast diagnostics
../../.venv/bin/python kalshi_edge.py              # prediction-market test
../../.venv/bin/python favorite_rule.py            # stress test of the rule that survived
../../.venv/bin/python fetch_kalshi2.py fetch_dvol.py   # retry data: full candles (high/low/trades) and Deribit DVOL
../../.venv/bin/python kalshi_v2.py                # retry: resting orders, de-biased market, DVOL, blend
../../.venv/bin/python favorite_maker.py           # stress test of the favourite rule executed with resting orders
```

## Volatility forecast (`../../common/volfc.py`)

Hour-of-day × weekday/weekend seasonality times a HAR level (1-day, 7-day and 30-day realized variance), with a rolling 90-day bias correction. Fitted on 2022-01 to 2025-02 only. Out of sample it beats a trailing 24-hour estimate at 1–6 hour horizons (6-hour correlation with realized variance 0.48 vs 0.37). US-open hours carry up to 2.7× average variance; early weekend hours 0.2–0.3×.

## Kalshi: "Bitcoin above $X at 5pm ET" (`kalshi_edge.py`, `favorite_rule.py`)

About 24,000 quoted prices over 577 days, strikes within 3% of spot, traded at the quoted bid or ask with Kalshi's taker fee.

**Rule that survived:** 4 hours before close, buy the favorite on any contract whose mid-price is at least 80¢ or at most 20¢.

| 100 contracts per trade, after fees | Training (2025) | Test (2026) |
|---|---|---|
| Trades | 1,461 | 2,229 |
| Profit per contract | 1.2¢ | 2.7¢ |
| t-stat (daily totals) | 1.7 | 6.2 |
| Total | $1,724 | $6,020 |
| Worst day / max drawdown | – | −$363 / −$549 |

- All 20 neighbouring settings (1–6 hours before close, cutoffs 5–30¢) were profitable in 2026, t = 2.7 to 7.1.
- 8 of 9 test months were positive.
- Both halves earn: favorites 3.0¢ per contract, fading longshots 2.4¢.

**Risks:** it wins about 97% of the time for about 3¢ and pays about 94¢ per contract, so a fast multi-percent BTC move produces large losses. Order-book depth is not in the data, so capacity is unknown. The effect was weaker in 2025 and may close.

**The model's own rules failed.** The best 2025 rule (pricer jump model, 1 hour before close, trade when it disagrees with the quote by 4¢ or more) made 10.9¢ per contract in training and −4.1¢ in 2026 (t = −2.1). In 2026 only the empirical-returns probability scored better than the market mid (Brier 0.070 vs 0.071). Taking the favorite trade only when that model agrees raised profit to 3.2¢ per contract, but that filter was chosen after seeing the test data.

## Retry: resting orders and better probabilities (`kalshi_v2.py`, `favorite_maker.py`)

Motivated by Burgi, Deng & Whelan (2026), who find on 300k+ Kalshi contracts that makers earn more than takers and that crypto contracts carry the strongest favourite-longshot bias. Kalshi's API flags maker-fee series as `quadratic_with_maker_fees`; the BTC daily series is plain `quadratic`, so resting orders pay no fee (results with a 0.0175·P(1−P) maker fee are in the JSON and differ by about 0.1¢).

Execution is simulated from hourly candles: a resting order at the current best quote ("join") or one cent inside it ("improve") counts as filled only if a trade printed at or through that price in the following hour. This ignores queue position, so fills are optimistic. Fill rates: 65% at the bid, 68% at the ask.

**Probability models on 2026 (Brier, lower is better):** de-biased market 0.0688, logistic blend 0.0694, seasonal-forecast empirical tails 0.0698, DVOL-based 0.0699, market mid 0.0710, the pricer's jump model 0.0721. The de-biased market probability is an isotonic map from the 2025 mid-price to outcome frequency; it beats every model that ignores the market, and the pricer's own model is the weakest.

**Model-driven rules** (chosen on 2025, judged on 2026):

| Execution | Best 2025 rule | 2026 result |
|---|---|---|
| Taker | jump model, 1h, 4¢ edge | −4.1¢ per contract, 312 trades, t = −2.1 |
| Join | de-biased market, 3h, 10¢ edge | +7.8¢, 59 fills, t = 1.5 |
| Improve | jump model, 4h, 10¢ edge | +10.7¢, 59 fills, t = 2.3 |

Resting instead of crossing turns the model rules from losers into small, thinly-traded winners; 59 fills is too few to call.

**Favourite rule as a maker** (4h before close, rest on the favourite side when mid is beyond 80/20):

| | Taker | Join | Improve |
|---|---|---|---|
| Fills (2026) | 2,227 | 1,689 | 829 |
| Per contract | 2.7¢ | **4.65¢** | 4.25¢ |
| t-stat (daily totals) | 6.2 | 8.4 | 5.2 |
| Total, 100 contracts/trade | $6,018 | $7,854 | $3,521 |
| Worst day / max drawdown | −$363 / −$549 | −$327 / −$428 | −$181 / −$313 |

All 20 neighbouring settings (1–6h, cutoffs 5–30¢) are profitable as join, t = 4.8 to 10.5; all nine months of 2026 are positive (0.9¢ in January to 8.8¢ in March). Adverse selection is present but mild: quotes that fill win 96.7% of the time, those that do not fill win 100%. Filtering on the de-biased probability changes nothing, because it agrees with the rule on every quote.

## Limitations

The Deribit hourly index stands in for CF Benchmarks' BRTI and for Deribit's 30-minute settlement average. Kalshi quotes are hourly candle closes, without depth; resting-order fills ignore queue position. Several rule grids were tested, so single results near t = 2 should be read as leads, not findings. This is research, not investment advice.
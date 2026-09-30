# Edge search: 0DTE options and prediction markets

A search for a trading edge in two short-horizon BTC markets, using the pricer's model and a seasonal volatility forecast. Rules were chosen on March–December 2025 and judged only on January–September 2026.

**Result:** the model did not produce an edge that survived costs and out-of-sample testing. One model-free effect did: Kalshi's BTC contracts overprice longshots and underprice favorites.

## Run it

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python ../backtest/fetch_data.py   # hourly Deribit index, perp and funding (shared with the backtest)
.venv/bin/python fetch_0dte.py               # Deribit option trades 02:00-04:00 UTC
.venv/bin/python fetch_kalshi.py             # Kalshi KXBTCD quotes, paced for the rate limit (about an hour)
.venv/bin/python volfc.py                    # volatility forecast diagnostics
.venv/bin/python dte0.py                     # 0DTE test
.venv/bin/python kalshi_edge.py              # prediction-market test
.venv/bin/python favorite_rule.py            # stress test of the rule that survived
```

## Volatility forecast (`volfc.py`)

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

## 0DTE options on Deribit (`dte0.py`)

At 03:00 UTC each day, the 5-hour at-the-money straddle into the 08:00 UTC expiry, traded unhedged. Costs are measured from trades against mark price.

- Selling earned about 10% of premium before costs in both halves.
- Measured costs are about 15% of premium (median 6.2% paid over mark, plus about 9% in exchange fees), so no rule survives when paying the spread.
- **Exploratory:** if filled at the mark price, selling only when the market is at least 30% above the model's value made +$97 per day in 2026 (t = 2.3, 107 days). Profit rose with stricter cutoffs in both halves, but the cutoff was chosen after seeing the test data and fills at the mark are not guaranteed.

## Limitations

The Deribit hourly index stands in for CF Benchmarks' BRTI and for Deribit's 30-minute settlement average. Kalshi quotes are hourly candle closes, without depth. Several rule grids were tested, so single results near t = 2 should be read as leads, not findings. This is research, not investment advice.

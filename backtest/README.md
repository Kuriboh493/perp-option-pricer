# Backtest

Tests the pricer's model (Heston stochastic volatility with Merton jumps) against public Deribit BTC option data, January 2023 to September 2026.

## Run it

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python fetch_data.py   # downloads ~57 MB into data/ (cached, not committed)
.venv/bin/python checks.py       # funding and market-hours checks
.venv/bin/python weekly.py       # straddle trading test, ~10 s
.venv/bin/python calib.py        # daily calibration test, a few minutes
```

`model.py` is a NumPy port of the page's pricing core and reproduces it to the cent.

## Results

### 1. Trading on the model (194 weeks, $100k notional per week)

Each Friday the model values the one-week at-the-money straddle from past prices only (spot vol = 14-day realized, long-run vol = 180-day realized, other parameters from the BTC preset). It buys if the model price is above the market, sells if below, and delta-hedges with the perp until expiry, funding included.

| Strategy | Avg per week | Share of premium | t-stat |
|---|---|---|---|
| Model signal, before costs | +$86 | +1.8% | 0.95 |
| Model signal, after costs | −$298 | −6.1% | −3.2 |
| Always sell, before costs | +$328 | +6.8% | 3.7 |
| Always sell, after costs | −$56 | −1.2% | −0.6 |

The model signal has no measurable edge. Weekly options were overpriced by about 7% of premium, but assumed costs (1% spread, exchange fees, taker-fee hedging) remove it. Market implied vol forecast next week's realized vol with an RMSE of 12.3 vol points; the model managed 15.9.

### 2. Daily calibration (401 days, about 84 contracts a day)

| Model | Same-day fit (RMSE, vol pts) | Next day |
|---|---|---|
| Stochastic vol + jumps | 1.8 | 4.0 |
| Stochastic vol only | 2.1 | 4.2 |
| Flat Black vol | 5.4 | 6.3 |
| Yesterday's vol per contract | – | 2.9 (model 3.5 on the same contracts) |

The model fits the smile well but does not forecast it better than persistence, and it is weakest on options under two weeks. Fitted parameters differ from the BTC preset: vol of vol about 3.4 (preset 1.5), correlation about −0.29 (preset −0.1), and mean reversion at the fitting cap of 20 (preset 3).

### 3. Structural checks

- **Funding:** averaged 6.4%/yr against the model's ~4.5%, with a median of 0.8% and a 5th–95th percentile range of −1.3% to +33%. The perp traded 1.9 bp over spot on average against a predicted 0.4 bp.
- **Market hours:** a closed hour carries about 21% of an open hour's variance on weeknights and about 9% on weekends for US stocks, and about 23% on weekends for gold futures, against a single default of 12%.

## Limitations

Deribit options are BTC-settled options on futures, not USD-margined options on the perp. Market prices are medians of trades in a 08:05–10:05 UTC window, not quotes. Costs are assumptions. Settlement uses the 08:00 index rather than Deribit's 30-minute average (0.09% apart on average). Options on real-world-asset perps have no historical market to test against.

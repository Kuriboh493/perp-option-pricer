# 0DTE straddles on Deribit

At 03:00 UTC each day, the 5-hour at-the-money BTC straddle into Deribit's 08:00 UTC expiry, valued with the pricer's model (Bates shape fitted in [../backtest/](../backtest/), level from the seasonal volatility forecast in [../../common/volfc.py](../../common/volfc.py)) and traded unhedged. Rules chosen on March–December 2025, judged on January–September 2026. Costs are measured from the trades themselves (price paid against mark, plus exchange fees).

## Run it

```
../../.venv/bin/python ../backtest/fetch_data.py   # hourly index, perp and funding (shared)
../../.venv/bin/python fetch_0dte.py               # option trades 02:00–04:00 UTC, 576 days
../../.venv/bin/python dte0.py
```

## Results

- Selling the straddle earned about 10% of premium before costs in both halves of the sample.
- Measured costs are about 15% of premium (median 6.2% paid over mark, plus about 9% in exchange fees), so no rule survives when paying the spread.
- Exploratory: if filled at the mark price, selling only when the market is at least 30% above the model's value made +$97 per day in 2026 (t = 2.3, 107 days). Profit rose with stricter cutoffs in both halves, but the cutoff was chosen after seeing the test data and fills at the mark are not guaranteed.

Full numbers are in `results_0dte.json`.

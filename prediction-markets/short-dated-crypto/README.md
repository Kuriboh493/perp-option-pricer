# Short-dated crypto contracts, 2026

These use live quotes and minute prices rather than settled trades, with the short-horizon volatility model from `volfc2.py` (seasonal HAR per asset, fitted before August 2026) as the probability model. Rules are picked on the first part of each sample and judged on the rest.

**Polymarket hourly "Bitcoin Up or Down" windows** (`polymarket_edge.py`; 1,499 windows sampled every 4 hours, October 2025 to May 2026 so far; test period from April 2026):

- Calibration at the quoted price is close to fair at every bucket except 35–65¢ (buyers lose 4–8%) and 80–90¢ (buyers earn 3%). The favourite rule that worked on Kalshi does not survive here: −1.1¢ per contract out of sample.
- The model beats the market only in the last two minutes (Brier 0.051 vs 0.058 at 60 s), and a "trade when the model disagrees by 20¢" rule made 26¢ a contract in training. That is a stale-print artifact: filled at the next printed trade instead of the last one, it drops to 4¢ in training and 1.3¢ out of sample (16 trades, t = 0.1).
- **Polymarket daily windows** (285): the only survivor is buying the ≥ 95¢ favourite 15 minutes before close, +1.5¢ per contract out of sample on 19 trades (t = 5.6): real but too small to matter.

**Kalshi ETH daily 5pm contracts** (`kalshi_recent_edge.py`; 52 events, August–September 2026, minute quotes): the market's mid beats the model at every lead from 50 minutes to 2 minutes; the favourite rule made +2.8¢ in September on 44 trades (t = 0.95). Kalshi's hourly ETH/SOL/XRP events carry trades but no standing two-sided quotes at the hour marks, so they cannot be tested this way. The 15-minute BTC series and the S&P hourly series were still downloading when this was written and are not included.

The conclusion matches the trade-level surveys: short-dated crypto contracts are efficient; a pricing model does not beat them, and whatever bias exists is in the far-dated longshots.

## Run it

```
../../.venv/bin/python fetch_prices.py && ../../.venv/bin/python fetch_1m.py && ../../.venv/bin/python fetch_btc_1m.py   # spot: hourly and minute
../../.venv/bin/python fetch_kalshi_recent.py KXETHD KXSOLD KXXRPD KXBTC15M KXINXU KXBTC   # minute candles, one request per event (hours)
../../.venv/bin/python fetch_polymarket.py                                                   # Up/Down windows with minute price history (hours)
../../.venv/bin/python volfc2.py                                                             # volatility model diagnostics
../../.venv/bin/python kalshi_recent_edge.py && ../../.venv/bin/python polymarket_edge.py
```

`volfc2.py` is the asset-generic version of [../../common/volfc.py](../../common/volfc.py): hour-of-day seasonality times a HAR level per asset, fitted before August 2026.

# Perp Option Pricer

A single-file, dependency-free pricer for options written on perpetual swaps, covering 24/7 crypto and real-world assets whose reference market closes. Open `index.html` in a browser.

Preset figures are examples, not live quotes.

## Model

- **Perp fair value.** Two funding rules. *Linear*: funding accrues at `κ(F − S) + ιS`, giving `F = S(κ − ι)/(κ − (r − q))`, the risk-neutral spot sampled at an exponential time of mean `1/κ` (Ackerer, Hugonnier & Jermann, *Mathematical Finance* 2025). *Clamped*: longs pay `ι + soft(p − ι, γ)` per interval on the premium `p = (F − S)/S`, flat inside the clamp, so no arbitrage puts the basis at `p = c ± γ` with `c` the carry per interval (He, Manela, Ross & von Wachter 2025). The clamp explains why a perp can sit a few basis points from spot for weeks; in the backtest data the Deribit basis averaged 1.9 bp inside a ±5 bp dead zone.
- **Perp drift.** The perp tracks spot, so its risk-neutral forward is `F·e^((r−q)T)`; options use generalised Black on that forward rather than Black-76 on the mark.
- **Stochastic volatility.** Heston: variance follows `dv = κ_v(θ − v)dt + ξ√v dW`, starting at spot vol squared, reverting to long-run vol squared, and correlated `ρ` with the price.
- **Jumps.** Merton jumps on top (the Bates model): Poisson arrivals, lognormal sizes, compensated drift, no jump risk premium, no jumps in variance.
- **Pricing.** Closed-form characteristic function, one numerical integral per expiry (Lewis 2001), sampled on `u = sinh(t)/2`. Checked against the Broadie–Kaya Heston benchmark (6.8061) and against Black and the Merton series in the zero vol-of-vol limit.
- **Market hours.** The variance process runs on a vol clock in which a closed hour counts as a fixed fraction of an open hour, scaled so a full week equals a calendar week. Jumps arrive on calendar time. Holidays are ignored.
- **Everlasting options.** A margined contract paying `κ(mark − payoff)` every period Δ, priced as `Σ κ(1+κ)^−(n+1) E[payoff at nΔ]`, an undiscounted geometric basket of European payoffs with mean horizon `Δ/κ` (Ackerer, Hugonnier & Jermann, Theorem 6; `κ = 1` recovers the original 2^−i weights). Checked against their Black–Scholes closed form to 0.15%.
- **Settlement.** Linear USD-margined perp, premium paid up front, European exercise against the mark, flat rates, no fees, no liquidation or oracle risk.
- **Greeks.** Central finite differences on the full model.

Not modelled: rough or multi-factor volatility, inverse or quanto contracts, discrete dividends, discrete or clamped funding.

## References

- Ackerer, Hugonnier & Jermann, [Perpetual Futures Pricing](https://arxiv.org/abs/2310.11771), *Mathematical Finance* (2025)
- He, Manela, Ross & von Wachter, [Fundamentals of Perpetual Futures](https://arxiv.org/abs/2212.06888) (2025)
- Kim & Park, [Designing funding rates for perpetual futures in cryptocurrency markets](https://arxiv.org/abs/2506.08573) (2025)
- Burgi, Deng & Whelan, [Makers or Takers: The Economics of the Kalshi Prediction Market](https://www2.gwu.edu/~forcpgm/2026-001.pdf) (2026)

## Backtest

See [backtest/](backtest/) for tests against Deribit BTC option data. In short: the model fits market smiles well, but it has no trading edge and does not forecast volatility better than market prices.

## Edge search

See [edge/](edge/) for a search for an edge in 0DTE options and Kalshi prediction markets. The model's own signals did not survive out of sample; a model-free favorite-longshot rule on Kalshi's BTC contracts did (2.7¢ per contract after fees in 2026 as a taker, 4.65¢ with resting orders, t = 6.2 and 8.4), with tail risk and unknown capacity. The de-biased market price forecasts outcomes better than any model that ignores it.

## Retail survey

See [edge2/](edge2/) for a trade-level survey of where retail loses across every Kalshi and Polymarket category (2021 to 2026): takers lose 4% of every dollar on Kalshi, concentrated in longshots priced a week or more from resolution (55–80% of stake lost), while short-dated crypto contracts are efficient on both platforms.

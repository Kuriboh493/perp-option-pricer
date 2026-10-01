# Perp option pricer

A single-file pricer for options written on perpetual swaps, for 24/7 crypto and for real-world assets whose reference market closes. Open [index.html](index.html) in a browser; a hosted copy is at https://claude.ai/artifact/2SWRtaixcgxfD3eXhZvXXy. Preset figures are examples, not live quotes.

## Model

- **Perp fair value.** Two funding rules. *Linear*: funding accrues at `κ(F − S) + ιS`, giving `F = S(κ − ι)/(κ − (r − q))`, the risk-neutral spot sampled at an exponential time of mean `1/κ` (Ackerer, Hugonnier & Jermann, *Mathematical Finance* 2025). *Clamped*: longs pay `ι + soft(p − ι, γ)` per interval on the premium `p = (F − S)/S`, flat inside the clamp, so no arbitrage puts the basis at `p = c ± γ` with `c` the carry per interval (He, Manela, Ross & von Wachter 2025). The clamp explains why a perp can sit a few basis points from spot for weeks; in the backtest data the Deribit basis averaged 1.9 bp inside a ±5 bp dead zone.
- **Perp drift.** The perp tracks spot, so its risk-neutral forward is `F·e^((r−q)T)`; options use generalised Black on that forward rather than Black-76 on the mark.
- **Jump diffusion (default).** Merton (1976): spot is lognormal with constant diffusion volatility between jumps; jumps arrive as a Poisson process with lognormal sizes and compensated drift. Prices are the Poisson-weighted sum of Black prices with variance `σ²τ + nδ²`, so the smile comes only from the jumps. Jump risk is priced as if diversifiable.
- **Stochastic volatility (optional).** A model switch adds Heston variance `dv = κ_v(θ − v)dt + ξ√v dW` on top of the same jumps (the Bates model), priced from the closed-form characteristic function with one numerical integral (Lewis 2001), sampled on `u = sinh(t)/2` and checked against the Broadie–Kaya benchmark (6.8061). In the Deribit backtest it fit smiles better in sample (1.8 vs 3.5 vol points) but forecast the next day no better, so the simpler jump-diffusion model is the default. With vol of vol at its floor the two agree to 1e-6.
- **Market hours.** The variance process runs on a vol clock in which a closed hour counts as a fixed fraction of an open hour, scaled so a full week equals a calendar week. Jumps arrive on calendar time. Holidays are ignored.
- **Everlasting options.** A margined contract paying `κ(mark − payoff)` every period Δ, priced as `Σ κ(1+κ)^−(n+1) E[payoff at nΔ]`, an undiscounted geometric basket of European payoffs with mean horizon `Δ/κ` (Ackerer, Hugonnier & Jermann, Theorem 6; `κ = 1` recovers the original 2^−i weights). Checked against their Black–Scholes closed form to 0.15%.
- **Settlement.** Linear USD-margined perp, premium paid up front, European exercise against the mark, flat rates, no fees, no liquidation or oracle risk.
- **Greeks.** Central finite differences on the full model.

Not modelled: rough or multi-factor volatility, jumps in variance, inverse or quanto contracts, discrete dividends, discrete funding paths.

## Tests

- [backtest/](backtest/): Deribit BTC options, January 2023 to September 2026. The model fits market smiles well (1.8 vol points) but has no trading edge and does not forecast volatility better than market prices. It also checks the funding and market-hours assumptions against data.
- [zero-dte/](zero-dte/): 5-hour at-the-money straddles into Deribit's daily expiry, 576 days. Selling earns about 10% of premium before costs, and measured costs (about 15% of premium) remove it; a model-ranked subset is a lead if fills happen at the mark.

## References

- Ackerer, Hugonnier & Jermann, [Perpetual Futures Pricing](https://arxiv.org/abs/2310.11771), *Mathematical Finance* (2025)
- He, Manela, Ross & von Wachter, [Fundamentals of Perpetual Futures](https://arxiv.org/abs/2212.06888) (2025)
- Kim & Park, [Designing funding rates for perpetual futures in cryptocurrency markets](https://arxiv.org/abs/2506.08573) (2025)
- Bankman-Fried & White, Everlasting Options (2021)

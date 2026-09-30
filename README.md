# Perp Option Pricer

A single-file, dependency-free pricer for options written on perpetual swaps, covering 24/7 crypto and real-world assets whose reference market closes. Open `index.html` in a browser.

Preset figures are examples, not live quotes.

## Model

- **Perp fair value.** Funding accrues continuously at `κ(F − S) + ιS` with `κ = 1 / funding interval`, giving `F = S(κ − ι)/(κ − (r − q))`.
- **Perp drift.** The perp tracks spot, so its risk-neutral forward is `F·e^((r−q)T)`; options use generalised Black on that forward rather than Black-76 on the mark.
- **Stochastic volatility.** Heston: variance follows `dv = κ_v(θ − v)dt + ξ√v dW`, starting at spot vol squared, reverting to long-run vol squared, and correlated `ρ` with the price.
- **Jumps.** Merton jumps on top (the Bates model): Poisson arrivals, lognormal sizes, compensated drift, no jump risk premium, no jumps in variance.
- **Pricing.** Closed-form characteristic function, one numerical integral per expiry (Lewis 2001), sampled on `u = sinh(t)/2`. Checked against the Broadie–Kaya Heston benchmark (6.8061) and against Black and the Merton series in the zero vol-of-vol limit.
- **Market hours.** The variance process runs on a vol clock in which a closed hour counts as a fixed fraction of an open hour, scaled so a full week equals a calendar week. Jumps arrive on calendar time. Holidays are ignored.
- **Everlasting options.** Priced as `Σ 2^(−i) · C(i·Δ)`, a weighted basket of European options one funding period apart.
- **Settlement.** Linear USD-margined perp, premium paid up front, European exercise against the mark, flat rates, no fees, no liquidation or oracle risk.
- **Greeks.** Central finite differences on the full model.

Not modelled: rough or multi-factor volatility, inverse or quanto contracts, discrete dividends, discrete or clamped funding.

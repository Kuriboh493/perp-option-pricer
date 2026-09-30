# Perp Option Pricer

A single-file, dependency-free pricer for options written on perpetual swaps, covering 24/7 crypto and real-world assets whose reference market closes. Open `index.html` in a browser.

Preset figures are examples, not live quotes.

## Model

- **Perp fair value.** Funding accrues continuously at `κ(F − S) + ιS` with `κ = 1 / funding interval`, giving `F = S(κ − ι)/(κ − (r − q))`.
- **Perp drift.** The perp tracks spot, so its risk-neutral forward is `F·e^((r−q)T)`; options use generalised Black on that forward rather than Black-76 on the mark.
- **Jumps.** Merton jump-diffusion: Poisson arrivals, lognormal sizes, compensated drift, no jump risk premium.
- **Market hours.** Variance accrues per hour; a closed hour carries a fixed fraction of an open hour's variance. Input volatility is normalised so a full week matches its calendar-time value. Holidays are ignored.
- **Everlasting options.** Priced as `Σ 2^(−i) · C(i·Δ)`, a weighted basket of European options one funding period apart.
- **Settlement.** Linear USD-margined perp, premium paid up front, European exercise against the mark, flat rates, no fees, no liquidation or oracle risk.
- **Greeks.** Central finite differences on the full model.

Not modelled: stochastic volatility, inverse or quanto contracts, discrete dividends, discrete or clamped funding.

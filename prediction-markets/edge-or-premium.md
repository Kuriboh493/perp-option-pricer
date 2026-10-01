# Real edge, or the volatility risk premium?

The prediction-market work here found strategies that made money out of sample. This note asks whether that money is a genuine mispricing or simply payment for bearing risk, because the two call for very different decisions about whether and how to trade.

## Short answer

| Strategy | Profit per contract | What it is |
|---|---|---|
| Kalshi BTC favourites, buying at the ask | about 2¢ | **Volatility risk premium.** No mispricing relative to the options market. |
| Kalshi BTC favourites, resting bids | about 4.4¢ | **About 2.3¢ volatility premium, plus about 2¢ of genuine edge** from providing liquidity. |
| Far-dated longshots (selling 5–20¢ contracts a week or more out) | buyers lose 57–80% of stake | **Most likely genuine mispricing.** Not consistent with a risk premium. Least tested for execution. |

## The distinction

A strategy can earn money in two ways:

- **Risk premium.** You are paid for holding a risk others want to shed. The returns are real but they are wages for risk: steady gains, occasional large losses, and other markets pay the same premium for the same risk.
- **Mispricing.** The price is wrong relative to what the same risk costs elsewhere. You earn more than the going rate for the risk you hold.

For the BTC contracts there is an external benchmark: Deribit's options already price Bitcoin's tail risk. For event contracts (Fed decisions, elections) there is none, so the test there is whether the risk is systematic.

## BTC favourites: benchmarked against options

The rule: four hours before Kalshi's 5pm ET close, take the favourite side of every "Bitcoin above $X" strike within 3% of spot quoted beyond 80/20.

Every rule trade (3,491 trades on 533 days, 2025–2026) was priced against the Deribit options market at the same moment. The options smile for the first expiry after the Kalshi close was fitted from trades in the preceding hour and rescaled to the four-hour Kalshi window by hour-of-week volatility. The result is the options market's probability that the favourite wins, which already includes whatever options traders charge for tail risk. Each trade's profit then splits exactly into two parts:

- **outcome − options probability:** what the options market also earns on the same risk (tail compensation)
- **options probability − price paid:** how much cheaper Kalshi was than options (mispricing)

| | Price paid | Options-implied | Won | Profit | Tail compensation | Kalshi cheaper than options |
|---|---|---|---|---|---|---|
| Taker (buy at the ask) | 94.2¢ | 93.7¢ | 96.6% | 2.04¢ (t = 5.1) | 2.87¢ (t = 7.2) | −0.83¢ |
| Resting (buy at the bid, when filled) | 91.1¢ | 93.1¢ | 95.5% | 4.35¢ (t = 7.1) | 2.33¢ (t = 3.9) | +2.02¢ (t = 22) |

**Buying at the ask is the volatility risk premium.** Kalshi's ask sits at or slightly above the options market's price, so there is no Kalshi-specific mispricing. The profit comes from the fact that the options market itself overprices large short-term moves:

| Options-implied probability | Trades | Average implied | Actually won |
|---|---|---|---|
| 80–90% | 774 | 85.8% | 90.3% |
| 90–95% | 779 | 92.7% | 96.9% |
| 95–98% | 904 | 96.7% | 99.0% |
| 98–100% | 977 | 99.0% | 99.4% |

That gap is the well-documented short-horizon variance risk premium that option sellers earn. A taker on Kalshi collects the same premium through a different instrument.

**Resting orders add a genuine edge of about 2¢.** Filled bids sat below the options market's fair value on 86% of trades. That is payment for providing liquidity: waiting in the queue instead of crossing the spread, and accepting the risk of being filled when the price is about to move against you.

**It is volatility risk, not crash insurance.** Favourites that lose when Bitcoin rallies earned nearly as much as those that lose in a crash (2026: 2.43¢ vs 2.97¢ as a taker, 4.34¢ vs 4.97¢ resting). Nobody pays to insure against rallies, so the premium is for large moves in either direction.

**Hedging does not help.** Buying the equivalent protection on Deribit costs the same premium the trade earns. A hedged taker position loses about 0.8¢ a contract; a hedged resting position keeps about 2¢ before Deribit's costs, which are large for replicating a small binary payoff.

## Far-dated longshots: is the risk systematic?

Across every Kalshi trade from 2021 to January 2026, buyers of non-sports longshots (5–20¢) more than a week before resolution lost 57–80% of their stake; Polymarket shows the same pattern at 35–55%. With no options market to benchmark against, the question is whether sellers are being paid for risk that cannot be diversified away. Three checks say mostly not:

- **Hits do not cluster.** Monthly maker P&L across seven longshot categories (economics, politics, entertainment, crypto, weather, mentions, companies and science) is barely correlated, mostly between −0.3 and +0.3.
- **It diversifies almost fully.** An equal-risk mix of the seven pools earned a monthly Sharpe ratio of 1.11, against 1.34 if the pools were fully independent and 0.51 for the average single pool.
- **The size is implausible as a risk premium.** A 57–80% expected loss for buyers is far beyond any reasonable price for event risk that can be spread across hundreds of independent contracts. It looks like overpaying for lottery tickets, consistent with the favourite-longshot literature on both platforms.

One exception: the politics pool's monthly P&L moved with Bitcoin over 18 months (correlation 0.52), largely because of November 2024, when the election resolved and Bitcoin rallied in the same month.

## What it means for trading

1. **Use resting orders only on the BTC favourites.** That is where the genuine edge is. Taking the ask is a short-volatility position with extra steps.
2. **Size the BTC trade as a short-volatility position.** Expect to give back weeks of gains on a day Bitcoin moves 3–4% within hours.
3. **The longshot pool is the purest candidate for real edge**, if the offers actually get filled at meaningful size.

## What is still unproven

The backtests cannot see order-book queues or depth. The live paper-trading recorder ([recorder/](recorder/)) settles the two open questions:

- **Do resting BTC bids fill, and about 2¢ below fair?** If yes, there is a small genuine edge on top of the volatility premium.
- **Do longshot offers get lifted, and how much flow is there?** If yes, the largest genuine edge is tradeable.

If neither holds up live, what remains is the volatility risk premium: a legitimate return, but one that should be sized for occasional large losses.

## Method notes

- Deribit has no expiry at Kalshi's 5pm close; the next expiry is about 15 hours later. Rescaling it to the four-hour window by plain clock time instead of the hour-of-week volatility clock moves the taker's mispricing component from −0.83¢ to +0.62¢. The genuine part of the taker edge is therefore somewhere in that range, small either way. The resting result holds under both.
- Option prices come from trades in the hour before each decision, not live quotes.
- Resting fills in the backtest count when a trade printed at or through the bid in the next hour, ignoring queue position, so they are optimistic. The recorder models the queue explicitly.
- Code: [kalshi-btc/tail_test.py](kalshi-btc/tail_test.py) (options benchmark), [kalshi-btc/favorite_maker.py](kalshi-btc/favorite_maker.py) (symmetry and fills), [retail-survey/](retail-survey/) (longshot pools); results in `kalshi-btc/results_tail_test.json`.

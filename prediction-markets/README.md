# Prediction markets: where retail loses

Five studies of Kalshi, Polymarket and DraftKings, from broad to narrow.

| Folder | Question | Answer |
|---|---|---|
| [retail-survey/](retail-survey/) | Across every category and every trade (2021 to January 2026), where do takers lose? | Kalshi takers lose 4.0% of every dollar after fees; Polymarket takers break even before fees. On both, the loss sits in longshots priced a week or more from resolution (Kalshi 57–80% of stake, Polymarket 35–55%), worst in economics and politics. Event-level scans show which pools are steady and which hang on a few events. |
| [kalshi-btc/](kalshi-btc/) | With quotes and execution, is there an edge in Kalshi's daily BTC contracts? | The favourite-longshot rule survived out of sample: 2.7¢ per contract as a taker, about 4.7¢ with resting orders (t = 6–8, 2026), with crash risk and unknown capacity. Model-driven rules did not; a de-biased market price was the best forecaster. |
| [short-dated-crypto/](short-dated-crypto/) | Are the newer hourly, 15-minute and Polymarket Up/Down crypto markets mispriced? | No. They are efficient at the quote level; an apparent last-minute edge on Polymarket vanishes under a latency-aware fill. |
| [recorder/](recorder/) | Do resting offers on far-dated longshots actually fill, and how much flow is there? | Measuring live: a paper-trading recorder snapshots books and trades every five minutes and simulates resting offers on ~150 markets. |
| [draftkings/](draftkings/) | Same question for DraftKings: the DKeX exchange (every trade since June 2026), the sportsbook, Pick6 and DFS. | Exchange singles are near fair (buyers lose 1.6%); combos lose 19% of stake, $22.8M to the makers in six weeks, from a 2–2.7% per-leg markup that compounds plus retail's picks. The sportsbook's premium is vig and dog shading the house keeps; Pick6 and DFS have no price to beat. |

**Is any of this real edge, or just the volatility risk premium?** See [edge-or-premium.md](edge-or-premium.md): taking the ask on BTC favourites is the volatility premium; resting orders add about 2¢ of genuine edge; far-dated longshots look like real mispricing.

Fees used throughout: Kalshi taker 7% of `p(1−p)` per contract, maker 0 on plain series and 1.75% on flagged ones; Polymarket crypto taker 7% of `p(1−p)`, makers 0.

Literature that shaped the tests: Burgi, Deng & Whelan, [Makers or Takers: The Economics of the Kalshi Prediction Market](https://www2.gwu.edu/~forcpgm/2026-001.pdf) (2026); Cardozo & Rivero-Wildemauwe, [The Favorite–Longshot Bias in Prediction Markets: Evidence from Polymarket](https://arxiv.org/abs/2609.12878) (2026); Becker, [prediction-market-analysis dataset](https://github.com/jon-becker/prediction-market-analysis).

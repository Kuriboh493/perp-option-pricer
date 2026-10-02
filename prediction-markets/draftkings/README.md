# DraftKings: where retail loses

The same question as [../retail-survey/](../retail-survey/) asked of DraftKings instead of Kalshi: across everything DraftKings sells, where do retail bettors systematically overpay, and could someone else take the other side? DraftKings runs four products: the sportsbook (house-set odds), DraftKings Predictions (an order-book exchange, DKeX, run by its CFTC-licensed subsidiary Railbird since June 2026), Pick6 (pick'em contests) and classic daily fantasy. Only the exchange can be measured trade by trade, and it turns out to publish everything.

**Short answer.** On the exchange, single contracts are priced about fairly (buyers lose 1.6% of stake, mostly the spread). Combos (parlays) are the pool: buyers lost 19% of $120M in six weeks, $22.8M to the market makers, positive every week. The structural part of that is a markup of 2–2.7% per leg that compounds to 4% on a two-leg combo and 24% on an eight-leg one; the rest, in this sample, is that the legs retail chose lost. The maker on the other side is DraftKings' own desk, so the open question is whether anyone else can quote combos. On the sportsbook, the retail premium is vig and favourite-longshot shading that DraftKings keeps and defends with limits; Pick6 and DFS are peer-to-peer games where the edge is skill, not price.

## Run it

```
../../.venv/bin/pip install curl_cffi duckdb                   # Akamai refuses plain curl; curl_cffi impersonates Chrome TLS
../../.venv/bin/python fetch_dkex.py                            # Railbird daily reports: market, settlement, time & sales (3 GB, idempotent)
../../.venv/bin/python build_dkex.py                            # into data/dkex/dkex.duckdb (12.4M trades, 4.7M contracts)
../../.venv/bin/python survey_dkex.py                           # every trade scored from the YES buyer's side -> results_survey.json
../../.venv/bin/python combos_dkex.py                           # combo price vs product of leg prices -> results_combos.json
../../.venv/bin/python fetch_books.py                           # DraftKings sportsbook + Pinnacle snapshot into data/
../../.venv/bin/python dk_vs_pinnacle.py && ../../.venv/bin/python dk_hold.py && ../../.venv/bin/python dkex_vs_books.py
../../.venv/bin/python fetch_kalshi_nfl.py && ../../.venv/bin/python kalshi_vs_dkex.py   # same NFL games on Kalshi
../../.venv/bin/python pick6.py                                 # Pick6 ladders vs the sportsbook's own prices (needs data/dk/pick6_home.html)
```

Data: Railbird Exchange publishes three CSV families a day at `https://railbirdexchange.com/reports/<family>/manifest.json` (`daily-market`, `daily-settlement`, `time-and-sales`), from June 11, 2026. The sportsbook's content API (`sportsbook-nash.draftkings.com/api/sportscontent/dkusoh/v1/leagues/<id>`) and the Predictions and Pick6 pages open with the same TLS impersonation. Pinnacle's guest API is the sharp reference. None of the downloaded data is committed.

## DraftKings Predictions (DKeX): every trade, June 11 to October 1, 2026

113 business days, 12.4 million trades, 2.09 billion contracts ($2.09 billion of collateral; the YES side put up $494 million). 183,000 single contracts and 3.6 million combo contracts traded; 4.49 million settled. Sports only in practice: NFL, college football and MLB are 85% of single-contract volume; politics and finance contracts barely trade.

The public time & sales has no aggressor flag, so every trade is scored from the YES buyer's side: what they paid against what the contract settled at. For single contracts that measures the mispricing of the contract at each price without saying who crossed the spread; for combos the YES buyer is the retail customer in every practical case (combos are bespoke contracts, `COMBO-<hash>`, created when a customer builds one, and DraftKings has said its in-house desk lays most of the volume, with Flutter as the other large maker).

| | Trades | Contracts | YES stake | YES buyer return | To the other side |
|---|---|---|---|---|---|
| Single contracts | 6.8M | 844M | $374M | −1.6% | $5.9M |
| Combos | 5.6M | 1,244M | $120M | **−19.3%** | **$22.8M** |

### Singles are close to fair

| Price paid (¢) | Contracts | YES stake | Hit rate | YES buyer return | NO buyer return |
|---|---|---|---|---|---|
| 0–5 | 31.7M | $0.8M | 2.3% | −12.4% | +0.3% |
| 5–10 | 43.3M | $3.0M | 5.7% | −18.3% | +1.4% |
| 10–20 | 62.3M | $8.9M | 15.5% | +8.2% | −1.4% |
| 20–35 | 92.2M | $25.2M | 27.6% | +1.2% | −0.4% |
| 35–50 | 234.8M | $103.0M | 42.0% | −4.3% | +3.4% |
| 50–65 | 266.0M | $145.4M | 54.2% | −0.8% | +1.0% |
| 65–80 | 57.2M | $40.4M | 69.1% | −2.2% | +5.3% |
| 80–90 | 22.5M | $19.0M | 84.5% | +0.1% | −0.4% |
| 90–95 | 12.3M | $11.3M | 92.6% | +0.7% | −7.7% |
| 95–99 | 14.9M | $14.4M | 98.1% | +1.0% | −34.1% |

The favourite-longshot bias is there but small and thin: contracts under 10¢ lose their buyers 12–18%, on $3.8 million of stake in sixteen weeks (0.9¢ a contract for the seller, t = 1.4 on weekly totals). Everything from 10¢ up is within a few points of fair, and favourites above 80¢ are fair to slightly cheap, as on Kalshi and Polymarket. The 35–50¢ and 65–80¢ rows are September's NFL favourites losing, not a pattern (four NFL weeks).

By market type the picture is the same: moneylines −3.8% for YES buyers, spreads −5.5%, totals +3 to +8% (the Over side; its buyers won in this sample), player props mixed. By league, MLB (+2.0%, $136M), college football (0.0%, $100M) and the WNBA (+2.3%) are fair; the NFL's −8.9% on $108M is four weeks of upsets, three of them profitable for the makers.

**Where the moneyline premium sits.** Moneylines are the one market type where settlement time equals the end of the game for both outcomes, so time-to-event cuts are clean (totals, props and TD scorers settle the moment the YES outcome happens, which pushes winners into the short buckets and makes every other market type look as if in-play buyers win; those tables are in `results_survey.json` but are artefacts):

| Hours before the end of the game | YES stake | YES buyer return | Seller ¢/contract |
|---|---|---|---|
| < 1 (in-play) | $32.8M | −0.9% | 0.4 |
| 1–3 (mostly in-play) | $54.8M | −2.3% | 1.0 |
| 3–6 | $37.2M | −7.3% | 3.5 |
| 6–24 | $15.8M | −6.2% | 3.1 |
| 1–7 days | $3.6M | −7.0% | 3.3 |

Pre-game moneyline buyers pay about 7% over fair; in-play buyers about 1%. That 7% is not retail stupidity but DraftKings' sportsbook vig in exchange form: the live comparison below shows DKeX's quotes sitting on the sportsbook's prices with the two sides of each game summing to 1.03. Both YES buyers lose, and the maker collects the spread: $3.7 million on $53 million of pre-game moneyline stake (3.4¢ a contract, 11 of 16 weeks positive, t = 2.2); $8.7 million with spreads added (4.1¢, 12 of 16 weeks, worst week −$14k).

### Combos are the pool

| Legs | Contracts | YES stake | Price | Hit rate | YES buyer return | Seller ¢/contract |
|---|---|---|---|---|---|---|
| 2 | 172M | $43.5M | 25.3¢ | 22.9% | −9.2% | 2.3 |
| 3 | 185M | $26.3M | 14.2¢ | 12.3% | −13.4% | 1.9 |
| 4 | 189M | $18.0M | 9.5¢ | 7.3% | −23.0% | 2.2 |
| 5 | 155M | $10.5M | 6.8¢ | 4.9% | −28.1% | 1.9 |
| 6 | 151M | $7.4M | 4.9¢ | 3.2% | −34.8% | 1.7 |
| 7 | 111M | $4.2M | 3.8¢ | 2.2% | −41.9% | 1.6 |
| 8 | 256M | $8.2M | 3.2¢ | 1.7% | −47.6% | 1.5 |

The loss rises with every leg and holds for every composition: combos made only of moneylines, spreads and totals lose 8.5% (two legs) to 46% (eight); with a touchdown-scorer leg 10.5% to 53%; with other player props 13% to 48%. Eight-leg combos are the most traded by contract count. By price, combos under 5¢ lose 41% of stake and 5–10¢ combos 29%, against 12–18% for single contracts at the same prices: the same bettor behaviour the Kalshi survey found in far-dated longshots, delivered through parlays instead.

**Weekly, the maker never lost.** Six weeks of settled combos (August 26 to October 1): $22.8 million on $118 million of stake, six of six weeks positive, worst week +$175k, best +$9.5M (NFL week 3), t = 2.6 on weekly totals, 1.9¢ a contract. Two- and three-leg combos alone made $7.5 million (2.1¢ a contract); six-leg and longer $8.2 million on only $20 million of stake.

### How much of the combo loss is the price, and how much the picks

`combos_dkex.py` takes every combo made only of "Yes" moneyline legs in the NFL and college football (independent games, so the product of leg prices is the fair price if the legs are fair), maps each leg to that team's next game, and prices it at the last single-contract trade at or before the combo trade. 524,000 combo trades, 91 million contracts, legs traded within six hours:

| Legs | Combo price | Product of leg prices | Markup | Per leg | Markup as % of price | Realized return | Return at leg prices |
|---|---|---|---|---|---|---|---|
| 2 | 28.9¢ | 27.8¢ | 1.040 | 2.0% | 3.9% | −14% | −11% |
| 3 | 22.7¢ | 21.2¢ | 1.070 | 2.3% | 6.6% | −23% | −18% |
| 4 | 16.8¢ | 15.2¢ | 1.100 | 2.4% | 9.1% | −37% | −31% |
| 5 | 12.7¢ | 11.3¢ | 1.130 | 2.5% | 11.5% | −42% | −35% |
| 6 | 9.8¢ | 8.4¢ | 1.166 | 2.6% | 14.3% | −52% | −44% |
| 7 | 7.8¢ | 6.5¢ | 1.199 | 2.6% | 16.6% | −51% | −41% |
| 8 | 5.8¢ | 4.6¢ | 1.241 | 2.7% | 19.4% | −56% | −45% |

Three things follow.

- **The markup is applied at the combo, not in the legs.** Single-contract moneylines are fair to within the spread; the combo price is their product times 1.02–1.027 per leg, and the per-leg factor itself grows with leg count. The median two-leg combo trades 4% above its product and only 18% of two-leg trades print below it; for eight legs the median is 26% above and 2% print below. This is the same finding the Kalshi parlay study reports ([Prices, Probabilities, and Parlays](https://arxiv.org/abs/2607.14430)): overpricing that grows with leg count on top of calibrated legs. The 1¢ tick does the rest at the bottom: combos under 5¢ trade at 1.38× their product because the desk will not quote below a cent or two.
- **Longshot combos are marked up far more.** Where the legs are mostly underdogs (product below 0.5ⁿ), eight-leg combos trade at 6× their product; mostly-favourite eight-leggers at 1.23×.
- **In this sample the picks lost more than the markup took.** At the product of leg prices, these combos would still have returned −11% (two legs) to −45% (eight): September's NFL and college favourites that retail stacked lost together (weeks 38 and 39 returned −41% and −38% at leg prices; week 36 +26%). The structural edge for the maker is the markup column; the realized column adds a lumpy, correlated bet against retail's favourite picks that will sometimes go the other way.

### The same NFL games on Kalshi

`kalshi_vs_dkex.py` scores Kalshi's NFL game-winner contracts (192 settled since August, hourly candlesticks weighted by volume, 1.1 billion contracts) against DKeX's NFL moneyline singles (80 million contracts):

| Price (¢) | Kalshi YES return (before 7% taker fee) | DKeX YES return |
|---|---|---|
| 10–20 | −31% | −9% |
| 20–35 | +18% | +4% |
| 35–50 | +7% | +2% |
| 50–65 | −17% | −12% |
| 65–80 | +3% | −16% |
| 80–90 | −1% | −4% |
| 90–95 | +6% | +7% |
| All | **−2.1%** | **−6.4%** |

Kalshi's hourly cut shows the same shape as DKeX's: −1% inside the final hour, −5% at 3–6 hours, −11% at 6–24 hours. Same games, same season, same bias; the DKeX buyer pays about four points more, which is the spread DraftKings' desk quotes.

### DKeX quotes are the sportsbook's prices

For this week's NFL games (33 contracts with open interest above 1,000 on October 1), the last DKeX trade sits 0.4 points from Pinnacle's devigged probability on average and 1.7 points below DraftKings' own sportsbook price, with the two sides of each game summing to 1.03. DraftKings' sportsbook price for the same team is 2.1 points above Pinnacle's fair value. In other words the exchange is quoted by the sportsbook's pricing with a 3¢ spread; an outside maker posting inside that spread would be at better-than-fair prices and still better than anything retail sees on the sportsbook.

## DraftKings Sportsbook: the premium is vig and shading, kept by the house

A single-day snapshot (October 2, 2026) of main lines against Pinnacle, matched by teams and date (`dk_vs_pinnacle.py`):

| Market | Matched | DraftKings hold | Pinnacle hold |
|---|---|---|---|
| Moneyline | 82 | 4.2% | 3.7% |
| Spread | 75 | 4.7% | 3.3% |
| Total | 83 | 4.7% | 3.7% |

The extra hold sits on underdogs. Against Pinnacle's devigged probability, a DraftKings bettor pays 3.3 points over fair for a team Pinnacle puts under 20%, 2.7 for 20–50%, 1.6 for 50–80% and 0.8 for favourites above 80%: the classic favourite-longshot shading. Favourites are nearly fairly priced even after vig.

Elsewhere on the book (`dk_hold.py`): team totals 5.3–6.4% hold, scoring props 6.6%, and futures 21–46% (Super Bowl winner 22% over 32 teams, AFC/NFC top seed 21%, NBA Finals 21%, college football champion 24%, NFL MVP 45%, college basketball champion 46%). Futures are the sportsbook's version of the far-dated longshot pool, with the house as the only seller.

None of this is retail-facing edge for an outsider: the house keeps the premium, and it limits accounts that beat it. What the literature and trade press find exploitable at the margin is (a) promotions, where a boosted price is simply above fair (a +170 boost on a fair +150 is worth about 7% of stake, [BettingUSA](https://www.bettingusa.com/sports/bonuses/odds-boosts/)), and (b) same-game parlay pricing errors, where DraftKings has paid less than the product of its own legs or priced a four-leg SGP at a competitor's three-leg price ([Action Network](https://www.actionnetwork.com/general/draftkings-same-game-parlay-sports-betting)); both are capped by limits. Baseball-only evidence suggests books do not shade main lines against the public's favourite bias beyond the hold ([the profit-bias identity](https://arxiv.org/abs/2609.06739)); the snapshot above says DraftKings does shade dogs.

## Pick6 and DFS: peer-to-peer, no price to beat

Pick6 in 2026 is a contest format: entries of the same pick count compete for a prize pool, scored by standings points, where each correct pick scores its multiplier. The lobby page embeds its data (`pick6.py` decodes the Remix stream); each player has a main line at 1× and a ladder of alternate lines with multipliers from 0.5× to 10×. Pick6 player ids are the sportsbook's participant ids, so each rung can be priced against DraftKings' own "N+ points" ladder. On the 14 WNBA cards offered on October 2, 75 rungs priced: multipliers average 92% of the sportsbook-fair multiplier, expected standings points 0.50 per alternate rung against 0.54 for the main line, and only the 5× and higher rungs reach the main line's expectation. There is no price edge; the edge in Pick6 is being better than the other entrants at choosing picks, less the rake.

Classic DFS is the same story with older numbers: DraftKings' rake runs about 8% on cheap contests and more at higher stakes, and 1.3% of players took 91% of profits in the 2015 studies ([Fantasy Footballers on contest selection](https://www.thefantasyfootballers.com/dfs/nfl-dfs-contest-selection-for-draftkings/), [integer-programming DFS paper](https://arxiv.org/pdf/1604.01455)). Retail loses to sharper entrants and the rake, not to a mispriced quote.

## What this says about a strategy

1. **Combos on DKeX are the retail-eating trade**, the counterpart of selling far-dated longshots on Kalshi: 19% of stake lost, $22.8M in six weeks, positive every week, a 2–2.7% per-leg markup that compounds, plus a correlated bet against whatever favourites retail stacks that week. The market maker is DraftKings' desk (and Flutter). Whether a third party can post offers on a bespoke combo contract, and whether the exchange routes customer combo flow to the book or to the desk, is the question to settle with an account; everything else about the pool is measured.
2. **Pre-game moneylines and spreads on DKeX carry a 7–8% premium that is the sportsbook's vig.** The desk earns 3–4¢ a contract on it. On an order book that is capacity for a maker quoting inside the desk's 3¢ spread, at Pinnacle-fair prices, in the hours before kickoff.
3. **Longshot singles under 10¢ lose 12–18%** but are a $4M pool over four months; **in-play moneylines are fair** (−1%), so there is nothing to pick off in the final hour.
4. **The sportsbook's premium is not for sale** except through promotions and the occasional SGP pricing error, and DraftKings limits whoever collects it. Pick6 and DFS have no mispriced quote at all.

## Limitations

The time & sales reports do not say who was the aggressor, so single-contract returns are contract-level mispricings, not taker losses. Combos are attributed to retail buyers on DraftKings' own description of its combo market making. The sample is three and a half months, four NFL weeks and six weeks of combos; the per-leg markup is measured on all-moneyline NFL and college combos only (91 million of 1.2 billion combo contracts fully priced) and assumes independent games. Contract settlement time stands in for event time, which is exact for moneylines and biased for anything that can settle early. The sportsbook and Pinnacle comparison is one day's snapshot; Pinnacle's "fair" is a multiplicative devig. Kalshi returns come from hourly candles at the hour's mean price, before fees. The Pick6 sample is 14 players on one day. Prices and the exchange's structure are as of October 2, 2026; DraftKings discontinued combo maker rebates in September 2026, saying liquidity targets were met.

Sources: [Railbird Exchange reports](https://railbirdexchange.com/) via [nosherzapoo/dkex-railbird-dashboard](https://github.com/nosherzapoo/dkex-railbird-dashboard) (which documents the manifests); [DraftKings DKeX launch](https://rg.org/news/gambling-industry/draftkings-launches-prediction-market); [DKeX combos and in-house market making](https://www.legalsportsreport.com/272589/draftkings-eyes-in-house-combos-as-predictions-volume-surges/); [Flutter as a DKeX market maker](https://dimers.com/industry/news/flutter-prediction-markets-fanduel-kalshi); [DKeX combo data commentary](https://frontrunningpredictions.substack.com/p/front-running-what-can-we-learn-from); [Prices, Probabilities, and Parlays: Systematic Bias in Sports Prediction Markets](https://arxiv.org/abs/2607.14430); [The profit-bias identity in sports betting](https://arxiv.org/abs/2609.06739).

This is research, not investment advice.

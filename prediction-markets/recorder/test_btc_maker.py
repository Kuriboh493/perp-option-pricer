"""Tests for the BTC maker markout machinery. Run: ../../.venv/bin/python -m unittest test_btc_maker -v"""
import math, os, random, shutil, sys, tempfile, unittest
import numpy as np
from scipy.stats import norm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import btc_maker as B  # noqa: E402


class AsOf(unittest.TestCase):
    def test_strict_and_inclusive(self):
        s = B.Series([10, 20, 30], ["a", "b", "c"])
        self.assertEqual(s.asof(20), "b")
        self.assertEqual(s.asof(20, strict=True), "a")          # "immediately before" never sees the same-time point
        self.assertIsNone(s.asof(5))
        self.assertEqual(s.asof(29.9), "b")
        self.assertIsNone(s.asof(29.9, max_age=5))              # stale data is rejected, not carried forward


class Clock(unittest.TestCase):
    def test_flat_clock_is_hours(self):
        flat = [1.0] * 48
        self.assertAlmostEqual(B.variance_clock(0, 7200, flat), 2.0)
        self.assertAlmostEqual(B.variance_clock(1800, 5400, flat), 1.0)   # partial hours weighted by overlap
        self.assertEqual(B.variance_clock(10, 10, flat), 0.0)


class FairValue(unittest.TestCase):
    def test_flat_smile_matches_lognormal_digital(self):
        flat, s0 = [1.0] * 48, 0.5
        t, close, expiry = 1_790_000_000, 1_790_000_000 + 4 * 3600, 1_790_000_000 + 15 * 3600
        smile = dict(s0=s0, coef=[0.0, 0.0, s0], expiry=expiry, ts=t, forward=80000.0, index=80000.0)
        V = s0 ** 2 * (close - t) / (365 * 86400)
        for K in (78000, 80000, 82000):
            want = norm.cdf((math.log(80000 / K) - V / 2) / math.sqrt(V))
            self.assertAlmostEqual(B.prob_above(smile, 80000, K, t, close, flat), want, places=3)

    def test_monotone_and_sides_sum_to_one(self):
        smile = B.fit_smile(np.arange(70000, 92000, 1000), [0.45 + 0.02 * ((k - 80000) / 5000) ** 2 for k in np.arange(70000, 92000, 1000)], 80000, 1_790_054_000, 1_790_000_000)
        ps = [B.prob_above(smile, 80000, k, 1_790_000_000, 1_790_014_400) for k in (76000, 78000, 80000, 82000, 84000)]
        self.assertTrue(all(a > b for a, b in zip(ps, ps[1:])))
        self.assertAlmostEqual(B.side_value(ps[1], "yes") + B.side_value(ps[1], "no"), 1.0)

    def test_side_quote(self):
        self.assertEqual(B.side_quote(0.90, 0.92, "yes"), (0.90, 0.92, 0.91))
        b, a, m = B.side_quote(0.07, 0.09, "no")
        self.assertAlmostEqual(b, 0.91); self.assertAlmostEqual(a, 0.93); self.assertAlmostEqual(m, 0.92)


def trade(ts, qty, taker_side, yes_price, tid=None):
    return dict(ts=ts, count=qty, taker_side=taker_side, yes_price=yes_price, no_price=round(1 - yes_price, 4), trade_id=tid or f"t{ts}")


class Fills(unittest.TestCase):
    def test_queue_then_fill_and_partial(self):
        placed, price = 1000.0, 0.90
        trades = [trade(1001, 300, "no", 0.90), trade(1002, 50, "yes", 0.91),     # buyer of our side: ignored
                  trade(1003, 250, "no", 0.90), trade(1004, 40, "no", 0.92)]      # sale above our bid: ignored
        hits = B.favourite_sell_trades(trades, "yes", price, placed, 3600)
        self.assertEqual([h["ts"] for h in hits], [1001, 1003])
        portions, rem, q = B.replay_fills(hits, price, queue=500, size=100)
        self.assertEqual(len(portions), 1); self.assertAlmostEqual(portions[0]["qty"], 50); self.assertAlmostEqual(rem, 50); self.assertAlmostEqual(q, 0)
        self.assertEqual(portions[0]["ts"], 1003)

    def test_through_rule(self):
        hits = B.favourite_sell_trades([trade(1001, 10, "no", 0.89)], "yes", 0.90, 1000, 3600)
        self.assertEqual(B.replay_fills(hits, 0.90, 500, 100)[1], 100)            # recorder rule: still queued
        portions, rem, _ = B.replay_fills(hits, 0.90, 500, 100, through=True)    # trade below our bid: level cleared
        self.assertEqual(rem, 0); self.assertEqual(portions[0]["qty"], 100)

    def test_matches_original_btc_advance_rule(self):
        """The refactor must reproduce the recorder's original fill time on random tapes."""
        rng = random.Random(3)
        for _ in range(200):
            placed, price, queue, size = 0.0, 0.9, rng.choice([0, 100, 500, 2000]), 100.0
            tape = sorted([trade(rng.uniform(-100, 4000), rng.choice([1, 10, 50, 200, 800]), rng.choice(["yes", "no"]), rng.choice([0.88, 0.89, 0.90, 0.91]), tid=str(i)) for i in range(40)], key=lambda t: t["ts"])
            # original logic
            q, rem, want = queue, size, None
            for t in tape:
                if t["ts"] < placed or t["ts"] > placed + 3600 or t["taker_side"] == "yes" or t["yes_price"] > price + 1e-9:
                    continue
                qty = t["count"]; take = min(qty, q); q -= take; qty -= take
                if qty > 0:
                    rem -= min(qty, rem)
                    if rem <= 1e-9:
                        want = t["ts"]; break
            portions, r2, _ = B.replay_fills(B.favourite_sell_trades(tape, "yes", price, placed, 3600), price, queue, size)
            got = portions[-1]["ts"] if r2 <= 1e-9 else None
            self.assertEqual(got, want)


class Markouts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import markouts as M
        cls.M = M
        cls.dir = tempfile.mkdtemp()
        main_db, hf_db, cls.truth = M.make_synthetic(cls.dir, days=12, seed=5)
        cls.recs, cls.res = M.run(main_db, hf_db, os.path.join(cls.dir, "reports"), cls.dir, source="synthetic")
        markets, quotes, spot, smiles, _ = M.load_market_data(hf_db)
        cls.pricer = M.Pricer(markets, quotes, spot, smiles)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_identities(self):
        for r in self.recs:
            for _, lab in self.M.HORIZONS:
                if r[f"net_{lab}"] is not None:
                    self.assertAlmostEqual(r[f"net_{lab}"], r["exec_edge"] + r[f"markout_{lab}"], places=12)
            if r["realized"] is not None and r["residual_to_settle"] is not None:
                self.assertAlmostEqual(r["realized"], r["spread_capture"] + r["mispricing_vs_mid"] + r["markout_30m"] + r["residual_to_settle"], places=12)

    def test_recovers_injected_adverse_selection(self):
        tox = [r["markout_10s"] for r, t in zip(self.recs, self.truth) if t["toxic"]]
        ok = [r["markout_10s"] for r, t in zip(self.recs, self.truth) if not t["toxic"]]
        self.assertLess(np.mean(tox), -0.01)                    # toxic fills: fair value falls by a cent or more
        self.assertLess(abs(np.mean(ok)), 0.004)                # healthy fills: about zero
        self.assertLess(self.res["markouts"]["10s"]["adverse_selection_c"], -0.4)

    def test_no_lookahead(self):
        """Fair value at t must not change when data after t is altered."""
        r = self.recs[0]; t = r["fill_ts"]
        before = self.pricer.fv(r["ticker"], r["side"], t)
        sp = self.pricer.spot
        i = next(k for k, ts in enumerate(sp.ts) if ts > t)
        saved = list(sp.v); sp.v[i:] = [x * 0.5 for x in sp.v[i:]]
        self.assertEqual(self.pricer.fv(r["ticker"], r["side"], t), before)
        sp.v = saved

    def test_quote_before_fill_is_strict(self):
        r = self.recs[0]
        q = self.pricer.quotes[r["ticker"]]
        self.assertLess(q.asof_ts(r["fill_ts"], strict=True), r["fill_ts"])


if __name__ == "__main__":
    unittest.main()

"""Adverse selection on the Kalshi BTC maker strategy: post-fill markouts against the Deribit-implied fair value.

For every resting-bid fill (simulated by the recorder, or real if a live source is added later) this builds a record with the
quote, spot and Deribit fair value immediately before the fill, fair value / Kalshi mid / spot at +1s, +10s, +1m, +5m, +30m,
and the settlement value, then summarises execution edge, markouts, net maker edge and a decomposition, with tables and plots.

Conventions (all per contract, in probability units = dollars per $1 contract; reports show cents):
  fair value FV(t)      Deribit-implied probability that our side pays, using only data received at or before t
  execution edge        FV(fill) - fill price
  markout_h             FV(fill + h) - FV(fill)            negative = adverse selection (toxic fill)
  net maker edge_h      execution edge + markout_h = FV(fill + h) - fill price
  control drift_h       FV(s + h) - FV(s) at random moments s while the same orders were resting and unfilled
  adverse selection_h   mean markout_h on fills - mean control drift_h
Quotes "immediately before the fill" are the last snapshot strictly before the fill time.

Usage:
  python markouts.py                      # analyse data/recorder.db + data/hf.db
  python markouts.py --fill-model through # re-derive fills from stored trades with the price-through rule
  python markouts.py --synthetic          # run the whole pipeline on synthetic data with known adverse selection
Outputs: reports/markouts.md, reports/*.png, results_markouts.json, data/maker_fills.csv, table maker_fills in data/maker_fills.db."""
import csv, json, math, os, random, sqlite3, sys, datetime as dt
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from btc_maker import Series, fit_smile, prob_above, side_value, side_quote, favourite_sell_trades, replay_fills, cluster_mean_ci, variance_clock  # noqa: E402

HORIZONS = [(1, "1s"), (10, "10s"), (60, "1m"), (300, "5m"), (1800, "30m")]
LIFE_S = 3600
SPOT_MAX_AGE, SMILE_MAX_AGE, QUOTE_MAX_AGE = 5.0, 120.0, 90.0
N_CONTROL = 5


# ---------- loading ----------
def load_market_data(hf_db):
    con = sqlite3.connect(hf_db)
    markets = {t: dict(strike=k, close=c) for t, k, c in con.execute("SELECT ticker, strike, close_ts FROM kalshi_markets")}
    quotes = defaultdict(lambda: ([], []))
    for ts, tk, yb, ya, bs, as_ in con.execute("SELECT ts, ticker, yes_bid, yes_ask, bid_size, ask_size FROM kalshi_quotes ORDER BY ts"):
        quotes[tk][0].append(ts); quotes[tk][1].append((yb, ya, bs, as_))
    quotes = {tk: Series(a, b) for tk, (a, b) in quotes.items()}
    sp = con.execute("SELECT ts, price FROM spot ORDER BY ts").fetchall()
    spot = Series([r[0] for r in sp], [r[1] for r in sp])
    snaps = defaultdict(list)
    for ts, exp, k, cp, iv, und, idx in con.execute("SELECT ts, expiry, strike, cp, mark_iv, underlying, index_price FROM deribit_iv"):
        snaps[ts].append((exp, k, cp, iv, und, idx))
    trades = defaultdict(list)
    for tid, tk, ts, yp, np_, cnt, side in con.execute("SELECT trade_id, ticker, ts, yes_price, no_price, count, taker_side FROM kalshi_trades"):
        trades[tk].append(dict(trade_id=tid, ts=ts, yes_price=yp, no_price=np_, count=cnt, taker_side=side))
    con.close()
    return markets, quotes, spot, SmileBook(snaps), trades


class SmileBook:
    """Deribit smiles by snapshot receive time, fitted lazily; as-of lookup never returns a later snapshot."""

    def __init__(self, snaps):
        self.raw = snaps
        self.series = Series(list(snaps.keys()), list(snaps.keys()))
        self.cache = {}

    def asof(self, t):
        ts = self.series.asof(t, max_age=SMILE_MAX_AGE)
        if ts is None:
            return None
        if ts not in self.cache:
            rows = self.raw[ts]
            by_k = defaultdict(list)
            for exp, k, cp, iv, und, idx in rows:
                by_k[k].append(iv / 100.0)
            ks = sorted(by_k)
            und = [r[4] for r in rows if r[4]]; idx = [r[5] for r in rows if r[5]]
            self.cache[ts] = fit_smile(ks, [float(np.mean(by_k[k])) for k in ks], float(np.median(und)) if und else None,
                                       rows[0][0], ts, float(np.median(idx)) if idx else None)
        return self.cache[ts]


def load_orders(main_db):
    con = sqlite3.connect(main_db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(orders)")]
    if "strategy" not in cols:
        con.close()
        return [], {}, {}
    orders = [dict(zip(["id", "market", "side", "price", "size", "remaining", "queue", "placed", "status", "filled_ts"], r)) for r in con.execute(
        "SELECT id, market, side, price, size, remaining, queue_ahead, placed_ts, status, filled_ts FROM orders WHERE strategy='btc_fav' AND kind='join'")]
    fcols = [r[1] for r in con.execute("PRAGMA table_info(fills)")]
    sel = "order_id, ts, size" + (", trade_id, trade_size" if "trade_size" in fcols else ", NULL, NULL")
    fills = defaultdict(list)
    ids = {o["id"] for o in orders}
    for oid, ts, qty, tid, tsz in con.execute(f"SELECT {sel} FROM fills"):
        if oid in ids:
            fills[oid].append(dict(ts=float(ts), qty=float(qty), trade_id=tid, trade_size=tsz))
    results = {m: r for m, r in con.execute("SELECT market, result FROM positions WHERE strategy='btc_fav' AND result IS NOT NULL")}
    con.close()
    return orders, fills, results


# ---------- per-fill records ----------
class Pricer:
    def __init__(self, markets, quotes, spot, smiles):
        self.markets, self.quotes, self.spot, self.smiles = markets, quotes, spot, smiles

    def fv(self, ticker, side, t):
        m = self.markets.get(ticker)
        if not m:
            return None
        s = self.spot.asof(t, max_age=SPOT_MAX_AGE)
        return side_value(prob_above(self.smiles.asof(t), s, m["strike"], t, m["close"]), side)

    def quote(self, ticker, side, t, strict=False):
        q = self.quotes.get(ticker)
        v = q.asof(t, max_age=QUOTE_MAX_AGE, strict=strict) if q else None
        if not v:
            return None, None, None, None, None
        b, a, mid = side_quote(v[0], v[1], side)
        return b, a, mid, v[2], v[3]

    def remaining_sd(self, t, close):
        sm = self.smiles.asof(t)
        if not sm or t >= close:
            return None
        T_D = (sm["expiry"] - t) / (365 * 86400)
        w = variance_clock(t, close) / max(variance_clock(t, sm["expiry"]), 1e-12)
        return sm["s0"] * math.sqrt(max(T_D * w, 1e-12))


def build_records(orders, fills, results, pricer, source="sim"):
    recs = []
    for o in orders:
        m = pricer.markets.get(o["market"])
        if not m:
            continue
        sign = 1 if o["side"] == "yes" else -1
        y = None
        if o["market"] in results:
            y = 1.0 if results[o["market"]] == o["side"] else 0.0
        for f in fills.get(o["id"], []):
            t = f["ts"]
            bid, ask, mid, bs, as_ = pricer.quote(o["market"], o["side"], t, strict=True)
            s = pricer.spot.asof(t, max_age=SPOT_MAX_AGE)
            s60 = pricer.spot.asof(t - 60, max_age=SPOT_MAX_AGE)
            fv0 = pricer.fv(o["market"], o["side"], t)
            sd = pricer.remaining_sd(t, m["close"])
            dist = sign * math.log(s / m["strike"]) if s else None
            r = dict(source=source, order_id=o["id"], ticker=o["market"], side=o["side"], strike=m["strike"], placed_ts=o["placed"], fill_ts=t,
                     day=dt.datetime.fromtimestamp(m["close"], dt.timezone.utc).date().isoformat(), price=o["price"], qty=f["qty"],
                     queue_ahead=o["queue"], trade_size=f["trade_size"], bid_before=bid, ask_before=ask, mid_before=mid,
                     spot_at_fill=s, fv_at_fill=fv0, tte_min=(m["close"] - t) / 60, dist_pct=100 * dist if dist is not None else None,
                     dist_sd=dist / sd if (dist is not None and sd) else None,
                     pre_move_bp=1e4 * sign * math.log(s / s60) if (s and s60) else None, settle_value=y,
                     exec_edge=fv0 - o["price"] if fv0 is not None else None,
                     spread_capture=mid - o["price"] if mid is not None else None,
                     mispricing_vs_mid=fv0 - mid if (fv0 is not None and mid is not None) else None,
                     realized=y - o["price"] if y is not None else None)
            for h, lab in HORIZONS:
                fvh = pricer.fv(o["market"], o["side"], t + h)
                _, _, midh, _, _ = pricer.quote(o["market"], o["side"], t + h)
                sh = pricer.spot.asof(t + h, max_age=SPOT_MAX_AGE)
                r[f"fv_{lab}"] = fvh; r[f"mid_{lab}"] = midh; r[f"spot_{lab}"] = sh
                r[f"markout_{lab}"] = fvh - fv0 if (fvh is not None and fv0 is not None) else None
                r[f"mid_markout_{lab}"] = midh - mid if (midh is not None and mid is not None) else None
                r[f"spot_move_bp_{lab}"] = 1e4 * sign * math.log(sh / s) if (sh and s) else None
                r[f"net_{lab}"] = fvh - o["price"] if fvh is not None else None
            r["residual_to_settle"] = y - r["fv_30m"] if (y is not None and r["fv_30m"] is not None) else None
            recs.append(r)
    return recs


def control_drift(orders, fills, pricer, seed=7):
    """Baselines for the same orders and horizons:
    placement: FV(placed + h) - FV(placed), i.e. E[value change | posted], whatever happened next (includes later fills);
    random:    FV(s + h) - FV(s) for random s with the whole window [s, s + h] inside the order's resting, unfilled life,
               i.e. the drift of the same contract when no fill occurred (theta and volatility-premium accrual, spot noise).
    Adverse selection is reported against the random baseline; the placement baseline is shown alongside."""
    rng = random.Random(seed)
    out = dict(placement=defaultdict(list), random=defaultdict(list))
    for o in orders:
        if o["market"] not in pricer.markets:
            continue
        fts = [f["ts"] for f in fills.get(o["id"], [])]
        end = min(fts) if fts else o["placed"] + LIFE_S
        day = dt.datetime.fromtimestamp(pricer.markets[o["market"]]["close"], dt.timezone.utc).date().isoformat()
        for h, lab in HORIZONS:
            v0 = pricer.fv(o["market"], o["side"], o["placed"]); vh = pricer.fv(o["market"], o["side"], o["placed"] + h)
            if v0 is not None and vh is not None:
                out["placement"][lab].append((vh - v0, day))
            if end - h <= o["placed"]:
                continue
            for _ in range(N_CONTROL):
                s_ = rng.uniform(o["placed"], end - h)
                a_, b_ = pricer.fv(o["market"], o["side"], s_), pricer.fv(o["market"], o["side"], s_ + h)
                if a_ is not None and b_ is not None:
                    out["random"][lab].append((b_ - a_, day))
    return out


def rederive_fills(orders, trades, through=True):
    fills = defaultdict(list)
    for o in orders:
        hits = favourite_sell_trades(trades.get(o["market"], []), o["side"], o["price"], o["placed"], LIFE_S)
        portions, _, _ = replay_fills(hits, o["price"], o["queue"], o["size"], through=through)
        fills[o["id"]] = [dict(ts=p["ts"], qty=p["qty"], trade_id=p["trade_id"], trade_size=p["trade_size"]) for p in portions]
    return fills


# ---------- summaries ----------
def wmean(vals, w):
    v = np.asarray(vals, float); w = np.asarray(w, float); ok = np.isfinite(v)
    return float(np.sum(v[ok] * w[ok]) / np.sum(w[ok])) if ok.any() and np.sum(w[ok]) > 0 else None


def c(x, nd=2):
    return None if x is None else round(100 * x, nd)


def stat_block(recs, key):
    vals = [r[key] for r in recs if r.get(key) is not None]
    days = [r["day"] for r in recs if r.get(key) is not None]
    qty = [r["qty"] for r in recs if r.get(key) is not None]
    if not vals:
        return dict(n=0)
    m, lo, hi, n = cluster_mean_ci(np.repeat(vals, 1), days)
    return dict(n=n, mean_c=c(wmean(vals, qty)), mean_unweighted_c=c(m), ci95_c=[c(lo), c(hi)] if lo is not None else None,
                median_c=c(float(np.median(vals))), pct_negative=round(100 * float(np.mean(np.asarray(vals) < 0)), 1))


def bucketize(v, edges, labels):
    if v is None:
        return None
    for e, lab in zip(edges, labels):
        if v < e:
            return lab
    return labels[-1]


GROUPS = {
    "price_bucket": lambda r: bucketize(r["price"], [0.85, 0.90, 0.95, 9], ["80-85c", "85-90c", "90-95c", "95-99c"]),
    "distance_sd": lambda r: bucketize(r["dist_sd"], [0.5, 1.0, 1.5, 99], ["<0.5 sd", "0.5-1 sd", "1-1.5 sd", ">1.5 sd"]),
    "time_to_expiry": lambda r: bucketize(r["tte_min"], [180, 210, 9999], ["<3h", "3-3.5h", ">3.5h"]),
    "queue_ahead": lambda r: bucketize(r["queue_ahead"], [1000, 5000, 1e12], ["<1k", "1k-5k", ">5k"]),
    "filling_trade_size": lambda r: bucketize(r["trade_size"], [100, 1000, 1e12], ["<100", "100-1k", ">1k"]),
    "prefill_btc_move": lambda r: None if r["pre_move_bp"] is None else ("toward strike" if r["pre_move_bp"] < 0 else "away from strike"),
}


def grouped(recs):
    out = {}
    for g, f in GROUPS.items():
        rows = defaultdict(list)
        for r in recs:
            k = f(r)
            if k is not None:
                rows[k].append(r)
        out[g] = {k: dict(fills=len(v), contracts=round(sum(x["qty"] for x in v)), exec_edge_c=c(wmean([x["exec_edge"] for x in v], [x["qty"] for x in v])),
                          markout_1m_c=c(wmean([x["markout_1m"] for x in v], [x["qty"] for x in v])), markout_5m_c=c(wmean([x["markout_5m"] for x in v], [x["qty"] for x in v])),
                          net_5m_c=c(wmean([x["net_5m"] for x in v], [x["qty"] for x in v])), realized_c=c(wmean([x["realized"] for x in v], [x["qty"] for x in v])))
                  for k, v in sorted(rows.items())}
    return out


def summarise(recs, orders, fills, ctrl):
    done = [o for o in orders if o["status"] in ("filled", "expired")]
    any_fill = [o for o in done if fills.get(o["id"])]
    full = [o for o in done if o["status"] == "filled"]
    res = dict(
        orders=dict(placed=len(orders), finished=len(done), fully_filled=len(full), any_fill=len(any_fill),
                    fill_rate_full=round(len(full) / len(done), 3) if done else None, fill_rate_any=round(len(any_fill) / len(done), 3) if done else None,
                    avg_qty_filled_per_filled_order=round(float(np.mean([sum(f["qty"] for f in fills[o["id"]]) for o in any_fill])), 1) if any_fill else None,
                    avg_queue_ahead_all=round(float(np.mean([o["queue"] for o in orders])), 0) if orders else None,
                    avg_queue_ahead_filled=round(float(np.mean([o["queue"] for o in any_fill])), 0) if any_fill else None),
        fills=len(recs), contracts_filled=round(sum(r["qty"] for r in recs)),
        execution_edge=stat_block(recs, "exec_edge"), spread_capture=stat_block(recs, "spread_capture"), mispricing_vs_mid=stat_block(recs, "mispricing_vs_mid"),
        realized_pnl=stat_block(recs, "realized"), residual_to_settle=stat_block(recs, "residual_to_settle"))
    res["markouts"] = {}
    for h, lab in HORIZONS:
        mk = stat_block(recs, f"markout_{lab}")
        ctl = {k: [v for v, _ in ctrl[k][lab]] for k in ("random", "placement")}
        ctl_days = {k: [d for _, d in ctrl[k][lab]] for k in ("random", "placement")}
        drift = {k: cluster_mean_ci(ctl[k], ctl_days[k]) for k in ctl}
        as_rand = (mk["mean_unweighted_c"] - c(drift["random"][0])) if (mk.get("n") and drift["random"][0] is not None) else None
        res["markouts"][lab] = dict(fill_markout=mk, mid_markout=stat_block(recs, f"mid_markout_{lab}"), spot_move_bp=stat_block(recs, f"spot_move_bp_{lab}"),
                                    net_maker_edge=stat_block(recs, f"net_{lab}"),
                                    control_drift_random_c=c(drift["random"][0]), control_drift_random_n=drift["random"][3],
                                    control_drift_placement_c=c(drift["placement"][0]), control_drift_placement_n=drift["placement"][3],
                                    adverse_selection_c=round(as_rand, 2) if as_rand is not None else None)
    res["groups"] = grouped(recs)
    # decomposition (h = 30m): realized = spread capture + mispricing vs mid + adverse selection + drift + residual to settlement
    m30 = res["markouts"]["30m"]
    res["decomposition_30m"] = dict(
        measured=dict(realized_pnl_c=res["realized_pnl"].get("mean_unweighted_c"), execution_edge_c=res["execution_edge"].get("mean_unweighted_c"),
                      spread_capture_c=res["spread_capture"].get("mean_unweighted_c"), fv_minus_kalshi_mid_c=res["mispricing_vs_mid"].get("mean_unweighted_c"),
                      fill_markout_30m_c=m30["fill_markout"].get("mean_unweighted_c"), control_drift_30m_c=m30["control_drift_random_c"],
                      residual_to_settlement_c=res["residual_to_settle"].get("mean_unweighted_c")),
        inferred=dict(liquidity_premium_c=res["spread_capture"].get("mean_unweighted_c"),
                      behavioral_mispricing_or_model_error_c=res["mispricing_vs_mid"].get("mean_unweighted_c"),
                      adverse_selection_c=m30["adverse_selection_c"],
                      variance_risk_premium_c=(m30["control_drift_random_c"] + res["residual_to_settle"]["mean_unweighted_c"])
                      if (m30["control_drift_random_c"] is not None and res["residual_to_settle"].get("mean_unweighted_c") is not None) else None),
        notes=["Identity per fill: realized = spread capture + (FV - mid) + markout_30m + (settle - FV_30m). Exact for each fill.",
               "Splitting markout_30m into adverse selection and drift uses the control average, not a per-fill quantity.",
               "FV - mid mixes behavioral mispricing with fair-value model error (15h smile rescaled to the Kalshi window).",
               "Variance risk premium = control drift + residual to settlement; the residual is very noisy per fill (binary payoff)."])
    return res


# ---------- report ----------
def plots(recs, res, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(outdir, exist_ok=True)
    files = []

    def save(fig, name):
        p = os.path.join(outdir, name); fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig); files.append(name)
    labs = [lab for _, lab in HORIZONS]
    # 1. average markouts by horizon
    fig, ax = plt.subplots(figsize=(7, 4))
    means = [res["markouts"][l]["fill_markout"].get("mean_unweighted_c") or 0 for l in labs]
    drift = [res["markouts"][l]["control_drift_random_c"] or 0 for l in labs]
    x = np.arange(len(labs)); ax.bar(x - 0.2, means, 0.4, label="fills"); ax.bar(x + 0.2, drift, 0.4, label="control (random resting moments)")
    ax.axhline(0, color="k", lw=0.8); ax.set_xticks(x); ax.set_xticklabels(labs); ax.set_ylabel("fair-value markout (cents)"); ax.legend(); ax.set_title("Average markout by horizon")
    save(fig, "1_markouts_by_horizon.png")
    # 2. distributions of 1m and 5m markouts
    fig, axs = plt.subplots(1, 2, figsize=(9, 3.5))
    for ax, lab in zip(axs, ["1m", "5m"]):
        v = [100 * r[f"markout_{lab}"] for r in recs if r.get(f"markout_{lab}") is not None]
        if v:
            ax.hist(v, bins=40, color="#3b6ea5")
        ax.axvline(0, color="k", lw=0.8); ax.set_title(f"{lab} markout"); ax.set_xlabel("cents")
    save(fig, "2_markout_distributions.png")
    # 3. execution edge vs subsequent markout
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    for lab, col in (("1m", "#3b6ea5"), ("5m", "#d0743c")):
        pts = [(100 * r["exec_edge"], 100 * r[f"markout_{lab}"]) for r in recs if r.get("exec_edge") is not None and r.get(f"markout_{lab}") is not None]
        if pts:
            ax.scatter(*zip(*pts), s=10, alpha=0.6, label=lab, color=col)
    ax.axhline(0, color="k", lw=0.8); ax.axvline(0, color="k", lw=0.8); ax.set_xlabel("execution edge at fill (cents)"); ax.set_ylabel("markout (cents)"); ax.legend(); ax.set_title("Execution edge vs subsequent markout")
    save(fig, "3_edge_vs_markout.png")
    # 4. markout by queue depth
    fig, ax = plt.subplots(figsize=(6, 4)); g = res["groups"].get("queue_ahead", {})
    ks = list(g); x = np.arange(len(ks))
    ax.bar(x - 0.2, [g[k]["markout_1m_c"] or 0 for k in ks], 0.4, label="1m"); ax.bar(x + 0.2, [g[k]["markout_5m_c"] or 0 for k in ks], 0.4, label="5m")
    ax.set_xticks(x); ax.set_xticklabels([f"{k}\n(n={g[k]['fills']})" for k in ks]); ax.axhline(0, color="k", lw=0.8); ax.set_ylabel("cents"); ax.set_title("Markout by queue ahead at placement"); ax.legend()
    save(fig, "4_markout_by_queue.png")
    # 5. realized P&L vs execution edge
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    pts = [(100 * r["exec_edge"], 100 * r["realized"]) for r in recs if r.get("exec_edge") is not None and r.get("realized") is not None]
    if pts:
        ax.scatter(*zip(*pts), s=10, alpha=0.5)
        e = np.array([p[0] for p in pts]); v = np.array([p[1] for p in pts]); bins = np.quantile(e, [0, .25, .5, .75, 1]) if len(e) >= 8 else None
        if bins is not None:
            mids, means = [], []
            for lo, hi in zip(bins[:-1], bins[1:]):
                sel = (e >= lo) & (e <= hi)
                if sel.any():
                    mids.append(e[sel].mean()); means.append(v[sel].mean())
            ax.plot(mids, means, "o-", color="#d0743c", label="quartile means"); ax.legend()
    ax.axhline(0, color="k", lw=0.8); ax.set_xlabel("execution edge at fill (cents)"); ax.set_ylabel("realized P&L per contract (cents)"); ax.set_title("Realized P&L vs execution edge")
    save(fig, "5_realized_vs_edge.png")
    # 6. cumulative P&L from actually filled orders
    fig, ax = plt.subplots(figsize=(7, 3.8))
    pts = sorted((r["fill_ts"], r["realized"] * r["qty"]) for r in recs if r.get("realized") is not None)
    if pts:
        ax.plot([dt.datetime.fromtimestamp(t, dt.timezone.utc) for t, _ in pts], np.cumsum([v for _, v in pts]))
    ax.axhline(0, color="k", lw=0.8); ax.set_ylabel("cumulative P&L ($)"); ax.set_title("Cumulative P&L, filled resting orders only"); fig.autofmt_xdate()
    save(fig, "6_cumulative_pnl.png")
    # 7. edge decay curve
    fig, ax = plt.subplots(figsize=(7.5, 4))
    pts = ["fill"] + labs + ["settle"]
    blocks = [res["execution_edge"]] + [res["markouts"][l]["net_maker_edge"] for l in labs] + [res["realized_pnl"]]
    ys = [b.get("mean_unweighted_c") for b in blocks]
    lo = [b["ci95_c"][0] if b.get("ci95_c") else None for b in blocks]; hi = [b["ci95_c"][1] if b.get("ci95_c") else None for b in blocks]
    xs = np.arange(len(pts))
    ok = [i for i, y in enumerate(ys) if y is not None]
    ax.plot([xs[i] for i in ok], [ys[i] for i in ok], "o-", label="FV(t+h) - fill price")
    okc = [i for i in ok if lo[i] is not None]
    if okc:
        ax.fill_between([xs[i] for i in okc], [lo[i] for i in okc], [hi[i] for i in okc], alpha=0.2, label="95% CI (clustered by day)")
    adj = [None] + [((res["markouts"][l]["net_maker_edge"].get("mean_unweighted_c") or 0) - (res["markouts"][l]["control_drift_random_c"] or 0)) if res["markouts"][l]["net_maker_edge"].get("n") else None for l in labs] + [None]
    oka = [i for i, y in enumerate(adj) if y is not None]
    if oka:
        ax.plot([xs[0]] + [xs[i] for i in oka], [ys[0]] + [adj[i] for i in oka], "s--", label="drift-adjusted (minus control drift)")
    ax.axhline(0, color="k", lw=0.8); ax.set_xticks(xs); ax.set_xticklabels(pts); ax.set_ylabel("cents per contract"); ax.set_title("Edge decay after fill"); ax.legend()
    save(fig, "7_edge_decay.png")
    return files


def markdown(res, files, args):
    L = [f"# Maker adverse-selection report", "", f"Generated {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC. Fill model: `{args['fill_model']}`. Data: `{args['source']}`.", ""]
    o = res["orders"]
    L += ["## Orders and fills", "", f"- Resting orders placed: {o['placed']}; finished: {o['finished']}; fully filled: {o['fully_filled']}; any fill: {o['any_fill']}",
          f"- Fill rate (full / any): {o['fill_rate_full']} / {o['fill_rate_any']}; average quantity filled per filled order: {o['avg_qty_filled_per_filled_order']}",
          f"- Average queue ahead at placement: all orders {o['avg_queue_ahead_all']}, filled orders {o['avg_queue_ahead_filled']}",
          f"- Fill records: {res['fills']} ({res['contracts_filled']} contracts)", ""]
    if not res["fills"]:
        L += ["No fills with high-frequency coverage yet. The sampler starts recording at the next 1pm ET placement; re-run after a few trading days.", ""]
        return "\n".join(L)
    e = res["execution_edge"]
    L += ["## Execution edge at fill", "", "| Quantity | Mean (¢) | 95% CI | Median | n |", "|---|---|---|---|---|"]
    for name, key in (("Execution edge (FV − fill)", "execution_edge"), ("Spread capture (mid − fill)", "spread_capture"), ("FV − Kalshi mid", "mispricing_vs_mid"), ("Realized P&L (settle − fill)", "realized_pnl")):
        b = res[key]; L.append(f"| {name} | {b.get('mean_unweighted_c')} | {b.get('ci95_c')} | {b.get('median_c')} | {b.get('n')} |")
    L += ["", "## Markouts by horizon", "", "| Horizon | Fill markout mean (¢) | 95% CI | Median | % negative | Control drift (¢) | Adverse selection (¢) | Net maker edge (¢) | Kalshi-mid markout (¢) | n |", "|---|---|---|---|---|---|---|---|---|---|"]
    for _, lab in HORIZONS:
        m = res["markouts"][lab]; f = m["fill_markout"]
        L.append(f"| {lab} | {f.get('mean_unweighted_c')} | {f.get('ci95_c')} | {f.get('median_c')} | {f.get('pct_negative')} | {m['control_drift_random_c']} | {m['adverse_selection_c']} | {m['net_maker_edge'].get('mean_unweighted_c')} | {m['mid_markout'].get('mean_unweighted_c')} | {f.get('n')} |")
    L += ["", "1s and 10s are approximate: Kalshi is polled every 2 s, spot every 1 s, and the Kalshi exchange clock is not synchronised to local receive times.", ""]
    d = res["decomposition_30m"]
    L += ["## Decomposition (30-minute horizon)", "", "**Directly measured** (mean per filled contract, cents):", ""]
    L += [f"- {k}: {v}" for k, v in d["measured"].items()]
    L += ["", "**Inferred economic interpretation** (not separately identified; see notes):", ""]
    L += [f"- {k}: {v}" for k, v in d["inferred"].items()]
    L += ["", *[f"- {n}" for n in d["notes"]], "", "## By group", ""]
    for g, rows in res["groups"].items():
        L += [f"### {g}", "", "| Group | Fills | Contracts | Exec edge | Markout 1m | Markout 5m | Net 5m | Realized |", "|---|---|---|---|---|---|---|---|"]
        L += [f"| {k} | {v['fills']} | {v['contracts']} | {v['exec_edge_c']} | {v['markout_1m_c']} | {v['markout_5m_c']} | {v['net_5m_c']} | {v['realized_c']} |" for k, v in rows.items()]
        L.append("")
    L += ["## Plots", ""] + [f"![{f}]({f})" for f in files]
    return "\n".join(L)


def write_outputs(recs, res, files, args, hf_db, outdir, data_dir):
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(HERE if args["source"] == "live" else outdir, "results_markouts.json"), "w") as f:
        json.dump(res, f, indent=1, default=str)
    with open(os.path.join(outdir, "markouts.md"), "w") as f:
        f.write(markdown(res, files, args))
    if recs:
        keys = list(recs[0].keys())
        with open(os.path.join(data_dir, "maker_fills.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(recs)
        con = sqlite3.connect(os.path.join(data_dir, "maker_fills.db"), timeout=30)   # separate file: never contend with the live sampler
        con.execute("DROP TABLE IF EXISTS maker_fills")
        con.execute(f"CREATE TABLE maker_fills({', '.join(k + (' TEXT' if isinstance(recs[0][k], str) else ' REAL') for k in keys)})")
        con.executemany(f"INSERT INTO maker_fills VALUES({','.join('?' * len(keys))})", [[r[k] for k in keys] for r in recs])
        con.commit(); con.close()


def run(main_db, hf_db, outdir, data_dir, fill_model="recorder", source="live"):
    markets, quotes, spot, smiles, trades = load_market_data(hf_db)
    orders, fills, results = load_orders(main_db)
    if fill_model == "through":
        fills = rederive_fills(orders, trades, through=True)
    pricer = Pricer(markets, quotes, spot, smiles)
    covered = [o for o in orders if o["market"] in markets]
    recs = build_records(covered, fills, results, pricer)
    ctrl = control_drift(covered, fills, pricer)
    res = summarise(recs, covered, fills, ctrl)
    args = dict(fill_model=fill_model, source=source)
    files = plots(recs, res, outdir) if recs else []
    write_outputs(recs, res, files, args, hf_db, outdir, data_dir)
    return recs, res


# ---------- synthetic data (pipeline check with known adverse selection) ----------
def make_synthetic(dirpath, days=20, toxic_share=0.5, toxic_drop=0.012, seed=1):
    """Two days' worth of structure repeated: spot follows a random walk; toxic fills are followed by a spot move against the
    favourite sized so fair value falls by about toxic_drop within a minute; healthy fills by no move."""
    from hf_sampler import connect
    rng = np.random.default_rng(seed)
    main, hf = os.path.join(dirpath, "recorder.db"), os.path.join(dirpath, "hf.db")
    for p in (main, hf):
        if os.path.exists(p):
            os.remove(p)
    sys.path.insert(0, HERE)
    import recorder as R
    R.DB = main
    mc = R.db(); hc = connect(hf)
    base = int(dt.datetime(2026, 9, 1, 21, tzinfo=dt.timezone.utc).timestamp())
    truth = []
    for d in range(days):
        close = base + d * 86400; t0 = close - 4 * 3600; S0 = 80000.0 + rng.normal(0, 500)
        # spot path at 1 s for 95 minutes
        n = 95 * 60; steps = rng.normal(0, 0.45 / math.sqrt(365 * 86400), n)
        path = S0 * np.exp(np.cumsum(steps))
        ts = t0 + np.arange(n)
        strikes = [round(S0 * (1 - k) / 250) * 250 for k in (0.012, 0.018, 0.024)]
        fills_at = sorted(rng.uniform(t0 + 300, t0 + 3000, size=len(strikes)))
        for i, (k, fts) in enumerate(zip(strikes, fills_at)):
            toxic = rng.random() < toxic_share
            if toxic:                                        # push spot down after the fill (toward the strike)
                j = int(fts - t0) + 1
                path[j:] *= math.exp(-0.0022)
            truth.append(dict(day=d, toxic=toxic))
        for t, s in zip(ts, path):
            hc.execute("INSERT INTO spot VALUES(?,?,?)", (float(t), float(s), None))
        for snap in range(t0, t0 + n, 30):                    # flat-ish smile, next-day 08:00 expiry
            exp = close + 11 * 3600
            for kk in np.arange(70000, 92000, 1000):
                hc.execute("INSERT INTO deribit_iv VALUES(?,?,?,?,?,?,?,?,?,?)", (float(snap), exp, float(kk), "C", 45.0 + 0.00002 * (kk - 80000) ** 2 / 1000, None, None, S0, S0, float(snap)))
        for i, (k, fts) in enumerate(zip(strikes, fills_at)):
            tk = f"KXBTCD-SYN{d:02d}-T{k}"
            hc.execute("INSERT INTO kalshi_markets VALUES(?,?,?,?)", (tk, f"SYN{d}", float(k), close))
            from btc_maker import prob_above
            sm = fit_smile(np.arange(70000, 92000, 1000), [(45.0 + 0.00002 * (kk - 80000) ** 2 / 1000) / 100 for kk in np.arange(70000, 92000, 1000)], S0, close + 11 * 3600, t0, S0)
            p0 = prob_above(sm, S0, k, t0, close)
            bid = math.floor((p0 - 0.02) * 100) / 100; ask = bid + 0.01
            for qt in range(t0, t0 + n, 10):
                hc.execute("INSERT INTO kalshi_quotes VALUES(?,?,?,?,?,?)", (float(qt), tk, bid, ask, 2000.0, 1500.0))
            oid = mc.execute("INSERT INTO orders(platform,market,side,kind,price,size,remaining,queue_ahead,placed_ts,status,filled_ts,strategy) VALUES('kalshi',?,?,'join',?,100,0,?,?,'filled',?,'btc_fav')",
                             (tk, "yes", bid, float(rng.choice([500, 3000, 8000])), t0, float(fts))).lastrowid
            mc.execute("INSERT INTO fills(order_id, ts, price, size, trade_id, trade_size) VALUES(?,?,?,?,?,?)", (oid, float(fts), bid, 100.0, f"t{oid}", float(rng.choice([50, 400, 2500]))))
            res_ = "yes" if path[-1] > k else "no"
            mc.execute("INSERT INTO positions(platform,market,side,price,size,opened_ts,strategy,kind,fee,result,pnl) VALUES('kalshi',?,?,?,100,?,'btc_fav','join',0,?,0)", (tk, "yes", bid, float(fts), res_))
    mc.commit(); hc.commit()
    return main, hf, truth


def main():
    if "--synthetic" in sys.argv:
        d = os.path.join(HERE, "data", "synthetic"); os.makedirs(d, exist_ok=True)
        main_db, hf_db, truth = make_synthetic(d)
        recs, res = run(main_db, hf_db, os.path.join(HERE, "reports", "synthetic"), d, source="synthetic")
        print(f"synthetic: {len(recs)} fills, toxic share {np.mean([t['toxic'] for t in truth]):.2f}")
        print(json.dumps({lab: res["markouts"][lab]["adverse_selection_c"] for _, lab in HORIZONS}, indent=1))
        print("report: reports/synthetic/markouts.md")
        return
    fm = "through" if "--fill-model" in sys.argv and sys.argv[sys.argv.index("--fill-model") + 1] == "through" else "recorder"
    recs, res = run(os.path.join(HERE, "data", "recorder.db"), os.path.join(HERE, "data", "hf.db"), os.path.join(HERE, "reports"), os.path.join(HERE, "data"), fill_model=fm)
    print(f"{len(recs)} fill records; report: reports/markouts.md")
    if recs:
        print(json.dumps({lab: dict(markout=res['markouts'][lab]['fill_markout'].get('mean_unweighted_c'), adverse_selection=res['markouts'][lab]['adverse_selection_c'], net=res['markouts'][lab]['net_maker_edge'].get('mean_unweighted_c')) for _, lab in HORIZONS}, indent=1))


if __name__ == "__main__":
    main()

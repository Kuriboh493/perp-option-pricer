"""Where does Polymarket retail lose? Every on-chain CLOB fill in the Becker dataset from the taker's side (gross, before fees),
by category (keyword-classified), market family, year, price bucket and time to close. Output: data/pm_segments.parquet."""
import glob, json, os, re, sys
import numpy as np, pandas as pd, pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
EXCHANGES = {"0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e", "0xc5d563a36ae78145c45a50134d48a1215220f80a"}   # CTF Exchange, NegRisk CTF Exchange
B = os.path.join(HERE, "data", "becker", "data", "polymarket")
PRICE_BINS = [0, 5, 10, 20, 35, 50, 65, 80, 90, 95, 101]
PRICE_LABELS = ["00-05", "05-10", "10-20", "20-35", "35-50", "50-65", "65-80", "80-90", "90-95", "95-99"]
TTC_BINS = [-1e18, 0, 3600, 6 * 3600, 24 * 3600, 7 * 86400, 1e18]
TTC_LABELS = ["after_close", "<1h", "1-6h", "6-24h", "1-7d", ">7d"]
CATS = [
    ("crypto", r"bitcoin|btc|ethereum|\beth\b|solana|\bsol\b|xrp|doge|crypto|up-or-down|updown|hyperliquid|memecoin|\bbnb\b"),
    ("sports", r"\bnba\b|\bnfl\b|\bmlb\b|\bnhl\b|\bufc\b|\bmma\b|soccer|premier-league|la-liga|serie-a|bundesliga|champions|\bepl\b|\bvs\b|-vs-|spread|o/u|over-under|f1-|grand-prix|tennis|golf|pga|wimbledon|open-winner|super-bowl|world-series|stanley|playoffs|ncaa|march-madness|cricket|rugby|boxing|esports|counter-strike|dota|league-of-legends|valorant|win-on-|beat-"),
    ("politics", r"election|president|senate|governor|trump|biden|harris|mayor|parliament|primary|congress|democrat|republican|prime-minister|chancellor|referendum|impeach|cabinet|nominee|vote|ballot|poll|approval|tariff|executive-order|supreme-court|ceasefire|ukraine|russia|israel|gaza|iran|nato"),
    ("weather", r"temperature|highest-temp|lowest-temp|rain|snow|hurricane|storm|tornado|heat|weather|degrees|\bnyc-|-in-.*-on-"),
    ("finance", r"\bfed\b|rate-cut|rate-hike|interest-rate|cpi|inflation|s&p|sp500|nasdaq|dow|stock|gdp|unemployment|jobs-report|recession|treasury|gold|oil|silver|tesla|nvidia|apple|microsoft|market-cap|ipo|earnings"),
    ("entertainment", r"oscar|grammy|emmy|box-office|rotten|spotify|billboard|netflix|movie|album|song|taylor-swift|kanye|drake|eurovision|bachelor|survivor|tv|streaming|youtube|tiktok|mrbeast"),
    ("tech", r"openai|gpt|chatgpt|\bai\b|llm|gemini|claude|grok|spacex|starship|launch|iphone|apple-event|google|meta-|deepseek|nvidia|model-release|agi"),
]


def classify(text):
    for name, pat in CATS:
        if re.search(pat, text):
            return name
    return "other"


def load_markets():
    cols = ["condition_id", "question", "slug", "outcome_prices", "clob_token_ids", "end_date"]
    m = pd.concat([pq.read_table(f, columns=cols).to_pandas() for f in sorted(glob.glob(os.path.join(B, "markets", "*.parquet")))], ignore_index=True).drop_duplicates("condition_id")
    rows = []
    for r in m.itertuples(index=False):
        try:
            prices = json.loads(r.outcome_prices or "[]"); toks = json.loads(r.clob_token_ids or "[]")
        except Exception:
            continue
        if len(toks) != 2 or len(prices) != 2 or set(prices) != {"0", "1"} or pd.isna(r.end_date):
            continue
        text = ((r.slug or "") + " " + (r.question or "")).lower()
        cat = classify(text); fam = re.sub(r"[-_]?\d[\d\-:apm]*", "", (r.slug or ""))[:40]
        end_s = int(pd.Timestamp(r.end_date).timestamp())
        for i, tok in enumerate(toks):
            rows.append((str(tok), cat, fam, int(prices[i] == "1"), end_s))
    t = pd.DataFrame(rows, columns=["token", "category", "family", "win", "end_s"]).drop_duplicates("token").set_index("token")
    return t


def block_table():
    pts = []
    for f in sorted(glob.glob(os.path.join(B, "blocks", "*.parquet"))):
        t = pq.read_table(f, columns=["block_number", "timestamp"]).to_pandas()
        if t.empty:
            continue
        t = t.sort_values("block_number")
        for r in (t.iloc[0], t.iloc[-1]):
            pts.append((int(r["block_number"]), int(pd.Timestamp(r["timestamp"]).timestamp())))
    pts = np.array(sorted(set(pts)))
    return pts[:, 0].astype(float), pts[:, 1].astype(float)


def process(files, markets, bx, by, limit=None):
    acc, files = [], files[:limit]
    batches = [files[i:i + 40] for i in range(0, len(files), 40)]
    for i, fs in enumerate(batches):
        t = pd.concat([pq.read_table(f, columns=["maker_asset_id", "taker_asset_id", "maker_amount", "taker_amount", "block_number", "fee", "taker"]).to_pandas() for f in fs], ignore_index=True)
        t = t[~t["taker"].str.lower().isin(EXCHANGES)]                # drop the taker-order mirror event; keep one event per maker fill
        taker_buys = t["taker_asset_id"].values != "0"
        token = np.where(taker_buys, t["taker_asset_id"].values, t["maker_asset_id"].values)
        usdc = np.where(taker_buys, t["maker_amount"].values, t["taker_amount"].values).astype(float) / 1e6
        size = np.where(taker_buys, t["taker_amount"].values, t["maker_amount"].values).astype(float) / 1e6
        ok = (size > 0) & (usdc > 0)
        d = pd.DataFrame(dict(token=token[ok], p=usdc[ok] / size[ok], size=size[ok], usdc=usdc[ok], buys=taker_buys[ok], block=t["block_number"].values[ok], fee=t["fee"].values[ok].astype(float) / 1e6))
        d = d[(d["p"] > 0) & (d["p"] < 1)].join(markets, on="token", how="inner")
        if d.empty:
            continue
        ts = np.interp(d["block"].values.astype(float), bx, by)
        y = d["win"].values.astype(float); p = d["p"].values
        # taker buys token at p: return y - p per token; taker sells token at p: return p - y (same as buying the other side at 1-p)
        taker_ret = np.where(d["buys"].values, y - p, p - y)
        eff_p = np.where(d["buys"].values, p, 1 - p)                        # price of the side the taker effectively bought
        ttc = d["end_s"].values - ts
        g = pd.DataFrame(dict(category=d["category"].values, family=d["family"].values, year=pd.to_datetime(ts, unit="s").year,
                              price_bucket=pd.cut(eff_p * 100, PRICE_BINS, labels=PRICE_LABELS, right=False), ttc=pd.cut(ttc, TTC_BINS, labels=TTC_LABELS, right=False),
                              trades=1.0, contracts=d["size"].values, dollars=d["size"].values * eff_p, taker_gross=d["size"].values * taker_ret, fees=d["fee"].values))
        acc.append(g.groupby(["category", "family", "year", "price_bucket", "ttc"], observed=True).sum().reset_index())
        if i % 25 == 0:
            print(i * 40, "files", flush=True)
            if len(acc) > 20:
                acc = [pd.concat(acc).groupby(["category", "family", "year", "price_bucket", "ttc"], observed=True).sum().reset_index()]
    return pd.concat(acc).groupby(["category", "family", "year", "price_bucket", "ttc"], observed=True).sum().reset_index()


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    markets = load_markets(); print(len(markets), "resolved outcome tokens", markets["category"].value_counts().to_dict(), flush=True)
    bx, by = block_table(); print(len(bx), "block anchor points", flush=True)
    files = sorted(glob.glob(os.path.join(B, "trades", "*.parquet")))
    seg = process(files, markets, bx, by, limit)
    seg["maker_gross"] = -seg["taker_gross"]
    seg.to_parquet(os.path.join(HERE, "data", "pm_segments.parquet"))
    print("segments", len(seg), "trades", seg["trades"].sum(), "dollars", seg["dollars"].sum(), "taker ret %", 100 * seg["taker_gross"].sum() / seg["dollars"].sum(), flush=True)

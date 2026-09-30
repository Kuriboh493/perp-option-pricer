"""Sample of Polymarket's Bitcoin 'Up or Down' markets with minute-level price history of the Up token.
15-minute windows every 2 hours since 2026-01-01, hourly windows every 4 hours since 2025-10-01, daily windows since 2025-06-01.
Slugs embed the window start (unix ts for 15m; ET date/hour for hourly and daily), so no listing endpoint is needed."""
import json, os, time, urllib.request, urllib.error, datetime as dt
from zoneinfo import ZoneInfo

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "polymarket")
ET, UTC = ZoneInfo("America/New_York"), dt.timezone.utc
GAP = 0.3
_last = [0.0]


def get(url, attempts=8, timeout=30):
    for attempt in range(attempts):
        w = _last[0] + GAP - time.time()
        if w > 0:
            time.sleep(w)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research"}), timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(float(e.headers.get("Retry-After") or 0) or min(30, 2 + 3 * attempt))
        except Exception:
            time.sleep(2 + 2 * attempt)
    return None


def hour_label(t):
    h = t.hour % 12 or 12
    return f"{h}{'am' if t.hour < 12 else 'pm'}"


def slugs(kind, start_utc, span_s):
    """Slugs name the window START for 15m and hourly markets, and the END day (noon ET) for daily markets."""
    if kind == "15m":
        return [f"btc-updown-15m-{int(start_utc.timestamp())}"]
    t = start_utc.astimezone(ET) if kind == "1h" else (start_utc + dt.timedelta(seconds=span_s)).astimezone(ET)
    mon, day, yr = t.strftime("%B").lower(), t.day, t.year
    if kind == "1h":
        return [f"bitcoin-up-or-down-{mon}-{day}-{hour_label(t)}-et", f"bitcoin-up-or-down-{mon}-{day}-{yr}-{hour_label(t)}-et"]
    return [f"bitcoin-up-or-down-on-{mon}-{day}", f"bitcoin-up-or-down-on-{mon}-{day}-{yr}"]


def fetch(kind, start_utc, span_s):
    path = os.path.join(OUT, kind, f"{int(start_utc.timestamp())}.json")
    if os.path.exists(path):
        return
    ev = None
    for s in slugs(kind, start_utc, span_s):
        r = get(f"https://gamma-api.polymarket.com/events?slug={s}")
        if r:
            ev = r[0]; break
    if not ev or not ev.get("markets"):
        json.dump(None, open(path, "w")); return
    m = ev["markets"][0]
    toks = json.loads(m.get("clobTokenIds") or "[]")
    outcomes = json.loads(m.get("outcomes") or "[]")
    end = int(start_utc.timestamp()) + span_s          # the metadata endDate is unreliable for daily markets
    hist = []
    if toks:                                            # fetch in <=6h chunks; some long spans hang server-side
        a, b = int(start_utc.timestamp()) - 300, end + 300
        while a < b:
            c = min(a + 6 * 3600, b)
            h = get(f"https://clob.polymarket.com/prices-history?market={toks[0]}&startTs={a}&endTs={c}&fidelity=1", attempts=2, timeout=15)
            if h is None:
                h = get(f"https://clob.polymarket.com/prices-history?market={toks[0]}&startTs={a}&endTs={c}&fidelity=5", attempts=2, timeout=15) or {}
            hist += [[x["t"], x["p"]] for x in h.get("history", [])]
            a = c
    json.dump(dict(slug=ev.get("slug"), question=m.get("question"), description=m.get("description"), outcomes=outcomes,
                   outcome_prices=m.get("outcomePrices"), volume=ev.get("volume"), start=int(start_utc.timestamp()), end=end,
                   token_up=toks[0] if toks else None, history=hist), open(path, "w"))


if __name__ == "__main__":
    for k in ("15m", "1h", "1d"):
        os.makedirs(os.path.join(OUT, k), exist_ok=True)
    jobs = []
    t = dt.datetime(2025, 5, 31, 12, tzinfo=ET)             # window start; the market is named for the end day
    while t < dt.datetime(2026, 9, 30, tzinfo=ET):
        jobs.append(("1d", t.astimezone(UTC), 86400)); t += dt.timedelta(days=1)
    t = dt.datetime(2025, 10, 1, tzinfo=UTC)
    while t < dt.datetime(2026, 10, 1, tzinfo=UTC):
        jobs.append(("1h", t, 3600)); t += dt.timedelta(hours=4)
    t = dt.datetime(2026, 1, 1, tzinfo=UTC)
    while t < dt.datetime(2026, 10, 1, tzinfo=UTC):
        jobs.append(("15m", t, 900)); t += dt.timedelta(hours=2)
    print(len(jobs), "windows", flush=True)
    for i, (k, s, span) in enumerate(jobs):
        fetch(k, s, span)
        if i % 250 == 0:
            print(i, k, s.isoformat(), flush=True)
    print("done", flush=True)

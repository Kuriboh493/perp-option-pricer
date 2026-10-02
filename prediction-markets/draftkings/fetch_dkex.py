"""Download Railbird Exchange (DKeX, DraftKings Predictions) daily reports: Daily Market, Daily Settlement and Time & Sales.
The exchange publishes a manifest per family at https://railbirdexchange.com/reports/<family>/manifest.json; the files sit behind
Akamai, so plain curl is refused and this uses curl_cffi's Chrome TLS impersonation. One request a second, idempotent."""
import json, os, sys, time, urllib.parse
from curl_cffi import requests

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "dkex", "raw")
FAMILIES = ["daily-market", "daily-settlement", "time-and-sales"]


def main():
    os.makedirs(RAW, exist_ok=True)
    s = requests.Session(impersonate="chrome")
    n = 0
    for fam in FAMILIES:
        r = s.get(f"https://railbirdexchange.com/reports/{fam}/manifest.json", timeout=60)
        if r.status_code != 200:
            print(fam, "manifest", r.status_code); continue
        reps = sorted(r.json()["reports"], key=lambda x: x["date"])
        json.dump(reps, open(os.path.join(HERE, "data", "dkex", f"manifest_{fam}.json"), "w"))
        print(fam, len(reps), reps[0]["date"], reps[-1]["date"], flush=True)
        for rep in reps:
            fn = os.path.join(RAW, f"{fam}_{rep['date']}.csv")
            if os.path.exists(fn) and os.path.getsize(fn) > 0:
                continue
            url = "https://railbirdexchange.com" + urllib.parse.quote(rep["href"])
            for attempt in range(3):
                try:
                    rr = s.get(url, timeout=180)
                    if rr.status_code == 200:
                        open(fn, "wb").write(rr.content); n += 1; break
                    print("fail", rr.status_code, url, flush=True)
                except Exception as e:
                    print("err", e, flush=True)
                time.sleep(3)
            time.sleep(1.0)
    print("downloaded", n)


if __name__ == "__main__":
    main()

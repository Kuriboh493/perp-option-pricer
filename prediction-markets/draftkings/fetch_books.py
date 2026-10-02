"""Snapshot DraftKings sportsbook (content API, needs Chrome TLS impersonation) and Pinnacle (guest API) odds into data/.
DraftKings league payloads carry the main lines; category payloads carry props and futures. Pinnacle sport ids: 15 football, 4 basketball, 19 hockey, 3 baseball, 33 tennis, 29 soccer, 17 golf, 22 MMA, 6 boxing, 24 politics."""
import os, json, time
from curl_cffi import requests
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DK = os.path.join(HERE, "data", "dk"); PIN = os.path.join(HERE, "data", "pinnacle")
LEAGUES = {"nfl": 88808, "nba": 42648, "nhl": 42133, "mlb": 84240, "ncaaf": 87637, "ncaab": 92483, "epl": 40253, "ucl": 40685, "ufc": 9034, "laliga": 40031, "seriea": 40030, "wnba": 94682}
CATEGORIES = {88808: [492, 1000, 1342, 1001, 1003, 528, 530, 529, 787, 1076, 1286, 1304], 42648: [519, 518, 1017], 42133: [1189, 1675, 1190], 87637: [529, 1000, 1342, 1001], 84240: [743, 1031], 94682: [1215, 1241]}


def main():
    os.makedirs(DK, exist_ok=True); os.makedirs(PIN, exist_ok=True)
    s = requests.Session(impersonate="chrome")
    base = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusoh/v1/leagues"
    for name, lid in LEAGUES.items():
        r = s.get(f"{base}/{lid}", timeout=60)
        print(name, lid, r.status_code, len(r.content))
        if r.status_code == 200:
            json.dump(r.json(), open(os.path.join(DK, f"league_{name}.json"), "w"))
        for cid in CATEGORIES.get(lid, []):
            r = s.get(f"{base}/{lid}/categories/{cid}", timeout=60)
            if r.status_code == 200:
                json.dump(r.json(), open(os.path.join(DK, f"{name}_cat_{cid}.json"), "w"))
            time.sleep(0.5)
        time.sleep(0.5)
    for sid in [15, 4, 19, 3, 33, 29, 17, 22, 6, 24]:
        for kind, path in [("matchups", "matchups"), ("straight", "markets/straight")]:
            req = urllib.request.Request(f"https://guest.api.arcadia.pinnacle.com/0.1/sports/{sid}/{path}", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                open(os.path.join(PIN, f"{kind}_{sid}.json"), "wb").write(resp.read())
            time.sleep(1)
    print("done")


if __name__ == "__main__":
    main()

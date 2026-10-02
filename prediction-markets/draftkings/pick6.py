"""DraftKings Pick6 (2026 format: peer-to-peer contests, standings points = sum of each correct pick's multiplier).
The lobby page embeds its loader data as a Remix turbo-stream payload; this decodes it, lists each featured player's
ladder of alternate lines with multipliers, and compares each 'more' rung's multiplier with DraftKings' own sportsbook ladder
('N+' points selections; Pick6 player ids are the sportsbook's participant ids). Fair multiplier for a rung = P(main) / P(rung)
using the sportsbook's raw prices for both, so the vig largely cancels; E[points] = multiplier x P(rung). Results in results_pick6.json."""
import os, re, json, collections

HERE = os.path.dirname(os.path.abspath(__file__))
DK = os.path.join(HERE, "data", "dk")


def hydrate(arr):
    def hyd(i):
        if not isinstance(i, int): return i
        if i < 0: return None
        v = arr[i]
        if isinstance(v, dict): return {arr[int(k[1:])] if k.startswith("_") else k: hyd(val) for k, val in v.items()}
        if isinstance(v, list): return [hyd(x) for x in v]
        return v
    return hyd(0)


def main():
    raw = open(os.path.join(DK, "pick6_home.html")).read()
    chunk = re.findall(r'enqueue\("((?:[^"\\]|\\.)*)"\)', raw)[0]
    arr = json.loads(chunk.encode().decode("unicode_escape", errors="ignore"))
    ld = hydrate(arr)["loaderData"]
    home = ld["routes/_homeShared"]
    comps = {c["competitionId"]: c for c in home.get("allCompetitions", [])} if isinstance(home.get("allCompetitions"), list) else {}
    cards = home["pickCardsResponse"]["pickCardByPickableId"]
    # sportsbook: WNBA player points ladders (category 1215): one-sided 'N+' selections, i.e. P(points >= N) = P(more than N-0.5)
    sb = collections.defaultdict(dict); names = {}
    d = json.load(open(os.path.join(DK, "94682_cat_1215.json"))); mk = {m["id"]: m for m in d["markets"]}
    for s in d["selections"]:
        m = mk.get(s["marketId"]); pid = str((s.get("participants") or [{}])[0].get("id"))
        lab = (s.get("label") or "").strip()
        if not m or not m["name"].endswith(" Points") or not lab.endswith("+") or not s.get("trueOdds"): continue
        names[pid] = s["participants"][0]["name"]; sb[pid][float(lab[:-1]) - 0.5] = 1 / s["trueOdds"]
    rows = []
    for pid, card in cards.items():
        ent = str(card["entities"][0]["dkId"]); lad = sb.get(ent, {})
        main = next((mk for mk in card["activePickableMarkets"] if len(mk["activeSelections"]) == 2), None)
        if not main: continue
        ml = main["targetValue"]; pm = lad.get(ml)
        for mk in card["activePickableMarkets"]:
            for sel in mk["activeSelections"]:
                side = "more" if sel["statLinePropositionId"] == 1 else "less"
                if len(mk["activeSelections"]) == 2: side = "main " + side
                pa = lad.get(mk["targetValue"]) if side.endswith("more") else None
                r = dict(player=names.get(ent, ent), stat="Points", line=mk["targetValue"], side=side, mult=sel["standingsMultiplier"], paused=mk["isPaused"], main_line=ml, sb_p_main=pm, sb_p_rung=pa)
                if pm and pa:
                    r["fair_mult"] = pm / pa; r["ev_points_rung"] = r["mult"] * pa; r["ev_points_main"] = pm
                rows.append(r)
    for r in rows: r.setdefault("fair_mult", None); r["sb_devig_p_rung"] = r.get("sb_p_rung"); r["sb_devig_p_main"] = r.get("sb_p_main")
    print(f"{'player':22s} {'side':10s} {'line':>5s} {'mult':>5s} {'P(rung)':>8s} {'P(main)':>8s} {'fair x':>7s} {'E[pts] rung':>11s} {'E[pts] main':>11s}")
    for r in sorted(rows, key=lambda r: (r["player"], r["line"])):
        if r.get("fair_mult") is None: continue
        print(f"{r['player']:22s} {r['side']:10s} {r['line']:5} {r['mult']:5} {r['sb_devig_p_rung']:8.3f} {r['sb_devig_p_main']:8.3f} {r['fair_mult']:7.2f} {r['ev_points_rung']:11.3f} {r['ev_points_main']:11.3f}{'  paused' if r['paused'] else ''}")
    ok = [r for r in rows if r.get("fair_mult") and not r["side"].startswith("main")]
    if ok:
        import statistics as S
        print(f"\n{len(ok)} alternate rungs matched to sportsbook prices; mean multiplier / fair multiplier = {S.mean(r['mult']/r['fair_mult'] for r in ok):.3f}; "
              f"rungs with E[points] above the main line's {sum(r['ev_points_rung'] > r['ev_points_main'] for r in ok)}; mean E[points] rung {S.mean(r['ev_points_rung'] for r in ok):.3f} vs main {S.mean(r['ev_points_main'] for r in ok):.3f}")
        for lo, hi in [(0, 0.8), (0.8, 1.2), (1.2, 2.5), (2.5, 100)]:
            v = [r for r in ok if lo <= r["mult"] < hi]
            if v: print(f"  multiplier in [{lo},{hi}): n={len(v)} mean mult {S.mean(r['mult'] for r in v):.2f} mean fair {S.mean(r['fair_mult'] for r in v):.2f} mean E[points] {S.mean(r['ev_points_rung'] for r in v):.3f}")
    json.dump(rows, open(os.path.join(HERE, "results_pick6.json"), "w"), indent=1)


if __name__ == "__main__":
    main()

"""Score forecast v1 against the results log (issue #15).

    python -m forecast.score [--pull PULL_ID]

Reads forecasts/v1/ (never written) and the latest pull in results/results_log.csv (or the one
named), scores the races that are called, and writes

    results/results.json            the site's data contract (docs/results-contract.md)
    results/score_provisional.json  every measure below, in full
    results/score_provisional.md    a short table-led summary

Definitions, as in the backtests (forecast.backtest) where they exist:
- The event scored is the one v1 published a probability for: in races.csv, that v1's Democratic
  side wins (`p_dem_win`; the side is a Democrat, or the stand-in independent in Nebraska, Idaho
  and South Dakota); in the House, that the Democrat wins (`p_dem_win`).
- Favourite: the outcome v1 gave the highest probability (Democratic side or Republican; in the
  House also the stand-in independent). An upset is a called race the favourite lost; expected
  upsets are the sum over called races of 1 - P(favourite). An exact tie has no favourite and is
  counted as neither.
- Brier: mean (p - y)^2; log loss: mean -[y log p + (1 - y) log(1 - p)] with p clipped to
  [0.001, 0.999], as in the backtests; calibration in the backtests' five bins of p.
- Vote share: the actual Democratic share of the two-party vote minus v1's median, in points
  (positive means Democrats did better than v1's median), over called Democrat-against-Republican
  races with at least MIN_COUNTED of the expected vote counted; 80% coverage counts results
  below, inside and above v1's 80% interval.
- Groups: Senate, governor and House, and all three together. The three Senate races where an
  independent stands in for the Democratic side (Nebraska, Idaho, South Dakota) are reported in
  their own group and left out of "senate" and "all", as v1's backtests left stand-in races out
  of scoring; a "senate_incl_independents" group gives the Senate with them.
- Seats: dem/rep/ind seats are those already won (plus the seats not up), so they are final
  only when `complete`. Percentiles in v1's simulated distributions (mid-rank: P(below) + half
  P(equal)) are given only for a complete chamber; before that, the range they can still take.
- Turnout is left null until the counts are near final.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .results import LOG, RESULTS, ROOT, V1, DATA, _surname

MIN_COUNTED = 0.85
EPS = 1e-3
BINS = (0, 0.2, 0.4, 0.6, 0.8, 1.0)
SENATE_NOW = {"R": 53, "D": 47}                 # as in forecast.vote_model
GOVERNORS_NOT_UP = {"D": 6, "R": 8}             # KY NJ VA DE NC WA; LA MS IN MO MT ND UT WV
HOUSE_SEATS = 435
CONTRACT = ROOT / "docs" / "results-contract.md"


# --------------------------------------------------------------------------- maths
def brier(p, y) -> float | None:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2)) if len(p) else None


def log_loss(p, y, eps: float = EPS) -> float | None:
    p, y = np.clip(np.asarray(p, float), eps, 1 - eps), np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))) if len(p) else None


def calibration(p, y, bins=BINS) -> list[dict]:
    d = pd.DataFrame({"p": np.asarray(p, float), "y": np.asarray(y, float)})
    d["bin"] = pd.cut(d["p"], bins, include_lowest=True)
    g = d.groupby("bin", observed=False).agg(races=("y", "size"), mean_p=("p", "mean"), win_rate=("y", "mean"))
    return [{"bin": f"{lo:.1f}-{hi:.1f}", "races": int(r.races),
             "mean_p": _r(r.mean_p), "win_rate": _r(r.win_rate)}
            for (lo, hi), (_, r) in zip(zip(bins[:-1], bins[1:]), g.iterrows())]


def favourite_counts(probs: pd.DataFrame, outcome: pd.Series) -> dict:
    """probs: one column per outcome, rows sum to 1; outcome: the column that happened."""
    top = probs.max(axis=1)
    tie = probs.eq(top, axis=0).sum(axis=1) > 1
    fav = probs.idxmax(axis=1)
    won = (fav == outcome) & ~tie
    return {"favourites_won": int(won.sum()), "upsets": int(((fav != outcome) & ~tie).sum()),
            "ties": int(tie.sum()), "expected_upsets": float((1 - top).sum()),
            "upset_mask": (fav != outcome) & ~tie}


def vote_error(actual, median, lo, hi) -> dict:
    a, m = np.asarray(actual, float), np.asarray(median, float)
    e = 100 * (a - m)
    n = len(e)
    return {"n": n,
            "mean_error_toward_dem": _r(e.mean()) if n else None,
            "mae": _r(np.abs(e).mean()) if n else None,
            "rmse": _r(math.sqrt((e ** 2).mean())) if n else None,
            "below_80": int((a < np.asarray(lo, float)).sum()),
            "inside_80": int(((a >= np.asarray(lo, float)) & (a <= np.asarray(hi, float))).sum()),
            "above_80": int((a > np.asarray(hi, float)).sum()),
            "coverage_80": _r(((a >= np.asarray(lo, float)) & (a <= np.asarray(hi, float))).mean()) if n else None}


def mid_percentile(dist: pd.Series, value: float) -> float:
    """dist: probability indexed by seat count. P(below) + half P(equal)."""
    dist = dist / dist.sum()
    return float(dist[dist.index < value].sum() + 0.5 * dist[dist.index == value].sum())


def quantile(dist: pd.Series, q: float) -> float:
    dist = (dist / dist.sum()).sort_index()
    return float(dist.index[np.searchsorted(dist.cumsum().to_numpy(), q - 1e-12)])


def _r(x, nd: int = 4):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), nd)


# --------------------------------------------------------------------------- frame
def frame(results: pd.DataFrame) -> pd.DataFrame:
    """v1's probabilities next to the latest results, one row per v1 race."""
    r = pd.read_csv(V1 / "races.csv")
    sw = pd.DataFrame({
        "id": r["race_id"], "office": r["office"], "state": r["state"], "d_kind": r["d_side"],
        "dem_name": r["dem_candidate"], "rep_name": r["rep_candidate"], "stand_in": None,
        "p_D": r["p_dem_win"], "p_R": 1 - r["p_dem_win"], "p_I": 0.0,
        "median": r["dem_share_median"], "lo80": r["dem_share_lo80"], "hi80": r["dem_share_hi80"],
        "vote_scored": r["d_side"].eq("democrat"), "incumbent_party": r["incumbent_party"]})
    h = pd.read_csv(V1 / "house_districts.csv")
    ho = pd.DataFrame({
        "id": h["cd"], "office": "house", "state": h["state"], "d_kind": "democrat",
        "dem_name": h["dem_candidates"], "rep_name": h["rep_candidates"], "stand_in": h["stand_in"],
        "p_D": h["p_dem_win"], "p_R": h["p_rep_win"], "p_I": h["p_ind_win"],
        "median": h["dem_share_median"], "lo80": h["dem_share_lo80"], "hi80": h["dem_share_hi80"],
        "vote_scored": h["contested"].astype(bool), "incumbent_party": None,
        "presidential_lean": h["presidential_lean_dem_2p"]})
    f = pd.concat([sw, ho], ignore_index=True)
    f["group"] = np.where(f["d_kind"].eq("independent_challenger"), "independent", f["office"])
    res = results.set_index("id")[["called", "winner_party", "winner_name", "dem_share_2p", "pct_counted",
                                   "source", "pulled_at"]]
    f = f.join(res, on="id")
    f["called"] = f["called"].fillna(False).astype(bool)
    f["outcome"] = [_outcome(row) for row in f.itertuples(index=False)]
    f["y"] = (f["outcome"] == "D").astype(float).where(f["called"])
    return f


def _outcome(row) -> str | None:
    """Which of v1's outcomes happened: D (Democratic side), R, I (House stand-in), other."""
    if not row.called or pd.isna(row.winner_party):
        return None
    sur = _surname(row.winner_name)
    if row.office == "house":
        if isinstance(row.stand_in, str) and _surname(row.stand_in) == sur:
            return "I"
        return {"D": "D", "R": "R"}.get(row.winner_party, "other")
    if row.d_kind == "independent_challenger":
        if _surname(row.dem_name) == sur:
            return "D"
        return "R" if row.winner_party == "R" else "other"
    return {"D": "D", "R": "R"}.get(row.winner_party, "other")


def lean_baseline(f: pd.DataFrame) -> pd.Series:
    """The plain last-presidential lean (2024 Democratic two-party share) for each race, the
    backtests' baseline: the state's for Senate and governor, the district's for the House.
    Null if the county panel is not available locally."""
    lean = pd.Series(np.nan, index=f.index)
    if "presidential_lean" in f:
        lean = f["presidential_lean"].astype(float).copy()
    panel = DATA / "processed" / "county_panel.parquet"
    if panel.exists():
        p = pd.read_parquet(panel, columns=["year", "state_po", "dem", "rep"])
        g = p[p["year"] == 2024].groupby("state_po")[["dem", "rep"]].sum()
        st = g["dem"] / (g["dem"] + g["rep"])
        sw = f["office"].ne("house")
        lean[sw] = f.loc[sw, "state"].map(st)
    return lean


# --------------------------------------------------------------------------- scoring
def score_group(f: pd.DataFrame) -> dict:
    c = f[f["called"] & f["outcome"].notna()]
    probs = c[["p_D", "p_R", "p_I"]].rename(columns=lambda s: s[2:])
    out = {"races": int(len(f)), "called": int(len(c))}
    if len(c) == 0:
        return out | {"favourites_won": 0, "upsets": 0, "ties": 0, "expected_upsets": 0.0, "brier": None,
                      "log_loss": None, "calibration": [], "upset_list": [], "unmodelled_winners": []}
    fc = favourite_counts(probs, c["outcome"])
    mask = fc.pop("upset_mask")
    p_winner = [float(r[o]) if o in r else 0.0 for (_, r), o in zip(probs.iterrows(), c["outcome"])]
    c = c.assign(p_winner=p_winner)
    ups = c[mask].sort_values("p_winner")
    out |= fc
    out["expected_upsets"] = _r(out["expected_upsets"], 2)
    out["brier"] = _r(brier(c["p_D"], c["y"]))
    out["log_loss"] = _r(log_loss(c["p_D"], c["y"]))
    out["calibration"] = calibration(c["p_D"], c["y"])
    out["upset_list"] = [{"id": r.id, "winner_party": r.winner_party, "winner_name": r.winner_name,
                          "v1_p_winner": _r(r.p_winner, 3)} for r in ups.itertuples()]
    out["unmodelled_winners"] = [{"id": r.id, "winner_name": r.winner_name, "winner_party": r.winner_party}
                                 for r in c[c["outcome"] == "other"].itertuples()]
    lean = c["lean"].astype(float)
    if lean.notna().all():
        call = (lean > 0.5).astype(float)
        out["baseline_lean"] = {"brier": _r(brier(call, c["y"])),
                                "favourites_won": int((call == c["y"]).sum())}
    else:
        out["baseline_lean"] = None
    return out


def vote_group(f: pd.DataFrame, stand_ins: bool = False) -> dict:
    """Vote-share error over called races with enough counted. Democrat-against-Republican races
    only, unless stand_ins (the independent-challenger group, scored on the independent's share)."""
    ok = f["vote_scored"] | (stand_ins & f["group"].eq("independent"))
    v = f[f["called"] & ok & f["dem_share_2p"].notna() & f["median"].notna()
          & (f["pct_counted"] >= MIN_COUNTED)]
    out = vote_error(v["dem_share_2p"], v["median"], v["lo80"], v["hi80"])
    lean = v["lean"].astype(float)
    out["baseline_lean_mae"] = _r((100 * (v["dem_share_2p"] - lean).abs()).mean()) if len(v) and lean.notna().all() else None
    out["baseline_lean_mean_error_toward_dem"] = _r((100 * (v["dem_share_2p"] - lean)).mean()) if len(v) and lean.notna().all() else None
    return out


def chambers(f: pd.DataFrame) -> tuple[dict, dict, dict]:
    """Seats won so far, control where already decided, v1's chance for that party, percentiles."""
    ch, chance, pct = {}, {}, {}
    c = f[f["called"]]

    # Senate: Democratic caucus = seats not up held by D/I + Democratic-side wins in D-v-R races.
    sen = f[f["office"] == "senate"]
    up_d = int(sen["incumbent_party"].isin(["D", "I"]).sum())
    hold_d, hold_r = SENATE_NOW["D"] - up_d, SENATE_NOW["R"] - (len(sen) - up_d)
    sc = c[c["office"] == "senate"]
    d = hold_d + int(((sc["outcome"] == "D") & (sc["group"] == "senate")).sum())
    i = int((((sc["outcome"] == "D") & (sc["group"] == "independent")) | (sc["outcome"] == "other")).sum())
    r = hold_r + int((sc["outcome"] == "R").sum())
    seats = pd.read_csv(V1 / "senate_seats.csv")
    seats["rep_seats"] = 100 - seats["dem_seats"] - seats["independent_seats"]
    control = "D" if d >= 51 else "R" if r >= 50 else None
    ch["senate"] = {"dem_seats": d, "rep_seats": r, "ind_seats": i, "control": control,
                    "complete": bool(len(sc) == len(sen))}
    chance["senate"] = {"p_dem_control": _r(seats.loc[seats["dem_seats"] >= 51, "probability"].sum(), 3),
                        "p_rep_control": _r(seats.loc[seats["rep_seats"] >= 50, "probability"].sum(), 3)}
    pct["senate"] = _percentiles(seats.groupby("dem_seats")["probability"].sum(), d,
                                 d + int((~sen["called"] & (sen["group"] == "senate")).sum()),
                                 ch["senate"]["complete"])

    # House
    hc = c[c["office"] == "house"]
    hd, hr, hi = (int((hc["outcome"] == o).sum()) for o in ("D", "R", "I"))
    hi += int((hc["outcome"] == "other").sum())
    hs = pd.read_csv(V1 / "house_seats.csv")
    control = "D" if hd >= 218 else "R" if hr >= 218 else None
    complete = bool(len(hc) == HOUSE_SEATS)
    ch["house"] = {"dem_seats": hd, "rep_seats": hr, "ind_seats": hi,
                   "control": control, "complete": complete}
    chance["house"] = {"p_dem_control": _r(hs.loc[hs["dem_seats"] >= 218, "probability"].sum(), 3),
                       "p_rep_control": _r(hs.loc[hs["rep_seats"] >= 218, "probability"].sum(), 3)}
    pct["house"] = _percentiles(hs.groupby("dem_seats")["probability"].sum(), hd,
                                hd + HOUSE_SEATS - len(hc), complete)

    # Governors: 50 in all, 14 not up; "control" is a majority (26) of governorships.
    gov = f[f["office"] == "governor"]
    gc = c[c["office"] == "governor"]
    gd = GOVERNORS_NOT_UP["D"] + int(((gc["outcome"] == "D") & (gc["group"] == "governor")).sum())
    gi = int((((gc["outcome"] == "D") & (gc["group"] == "independent")) | (gc["outcome"] == "other")).sum())
    gr = GOVERNORS_NOT_UP["R"] + int((gc["outcome"] == "R").sum())
    gs = pd.read_csv(V1 / "governor_seats.csv")
    gs["rep_seats"] = 50 - gs["dem_seats"] - gs["independent_seats"]
    control = "D" if gd >= 26 else "R" if gr >= 26 else None
    ch["governor"] = {"dem_seats": gd, "rep_seats": gr, "ind_seats": gi, "control": control,
                      "complete": bool(len(gc) == len(gov))}
    chance["governor"] = {"p_dem_control": _r(gs.loc[gs["dem_seats"] >= 26, "probability"].sum(), 3),
                          "p_rep_control": _r(gs.loc[gs["rep_seats"] >= 26, "probability"].sum(), 3)}
    pct["governor"] = _percentiles(gs.groupby("dem_seats")["probability"].sum(), gd,
                                   gd + int((~gov["called"]).sum()), ch["governor"]["complete"])
    for k in ch:
        w = ch[k]["control"]
        chance[k]["winner"] = w
        chance[k]["v1_p_winner"] = None if w is None else chance[k][f"p_{'dem' if w == 'D' else 'rep'}_control"]
    return ch, chance, pct


def _percentiles(dist: pd.Series, lo: int, hi: int, complete: bool) -> dict:
    out = {"v1_median": quantile(dist, 0.5), "v1_lo80": quantile(dist, 0.1), "v1_hi80": quantile(dist, 0.9),
           "dem_seats_so_far": lo, "dem_seats_max_possible": hi}
    if complete:
        out |= {"percentile": _r(mid_percentile(dist, lo), 3),
                "inside_80": bool(out["v1_lo80"] <= lo <= out["v1_hi80"])}
    else:
        out |= {"percentile": None, "inside_80": None,
                "percentile_range": [_r(mid_percentile(dist, lo), 3), _r(mid_percentile(dist, hi), 3)]}
    return out


def score(f: pd.DataFrame) -> dict:
    f = f.assign(lean=lean_baseline(f))
    groups = {"all": f[f["group"] != "independent"], "senate": f[f["group"] == "senate"],
              "governor": f[f["group"] == "governor"], "house": f[f["group"] == "house"],
              "independent": f[f["group"] == "independent"],
              "senate_incl_independents": f[f["office"] == "senate"],
              "house_contested": f[(f["office"] == "house") & f["vote_scored"]],
              "senate_and_governor": f[f["group"].isin(["senate", "governor"])]}
    races = {k: score_group(g) for k, g in groups.items()}
    votes = {k: vote_group(g) for k, g in groups.items() if k not in ("independent", "senate_incl_independents")}
    votes["independent"] = vote_group(groups["independent"], stand_ins=True)
    ch, chance, pct = chambers(f)
    uncalled = f[~f["called"]].sort_values(["office", "id"])
    return {"races": races, "vote_share": votes, "chambers": ch, "chamber_chance": chance,
            "seat_percentiles": pct,
            "uncalled": {o: list(uncalled.loc[uncalled["office"] == o, "id"]) for o in ("senate", "governor", "house")},
            "turnout": None}


# --------------------------------------------------------------------------- outputs
def contract_json(f: pd.DataFrame, s: dict, as_of: str) -> dict:
    rows = []
    for r in f.itertuples(index=False):
        called = bool(r.called)
        rows.append({"id": r.id, "office": r.office, "called": called,
                     "winner_party": r.winner_party if called else None,
                     "winner_name": r.winner_name if called else None,
                     "dem_share_2p": _r(r.dem_share_2p) if pd.notna(r.dem_share_2p) else None,
                     "pct_counted": _r(r.pct_counted) if pd.notna(r.pct_counted) else None,
                     "source": r.source if isinstance(r.source, str) else None,
                     "pulled_at": r.pulled_at if isinstance(r.pulled_at, str) else None})
    states = pd.read_csv(V1 / "turnout_states.csv")["state"]
    keep = ("called", "favourites_won", "upsets", "expected_upsets", "brier", "log_loss")
    va = s["vote_share"]["all"]
    sen_comp = pd.read_csv(V1 / "senate_seats.csv")
    return {
        "schema": 1, "as_of": as_of, "status": "provisional",
        "note": ("Race calls and vote counts from the Associated Press public results feed, pulled "
                 f"{as_of}; Senate and governor calls cross-checked against Wikipedia. Counts are incomplete."),
        "races": rows,
        "chambers": s["chambers"],
        "turnout": {"national": None, "states": {st: None for st in states}},
        "score": {**{k: {x: s["races"][k][x] for x in keep} for k in ("all", "senate", "house", "governor")},
                  "vote_share": {x: va[x] for x in ("n", "mean_error_toward_dem", "mae", "above_80",
                                                    "inside_80", "below_80")},
                  "seat_percentiles": {k: s["seat_percentiles"][k]["percentile"]
                                       for k in ("senate", "house", "governor")}},
        "comparison": {"as_of": "2026-10-22",
                       "senate_control": [{"name": "v1", "p_dem": _r(sen_comp.loc[sen_comp["dem_seats"] >= 51,
                                                                                   "probability"].sum(), 2),
                                           "source": "forecasts/v1", "captured": "2026-10-22",
                                           "news_report": False}],
                       "races": [], "final": {"senate_control": [], "races": []}},
    }


def _pct(x, nd=0):
    if x is not None and nd == 0 and 0 < x < 1 and round(100 * x) in (0, 50, 100):
        nd = 1          # 0.495 is not shown as 50%, nor 0.996 as 100%
    return "–" if x is None else f"{100 * x:.{nd}f}%"


def _num(x, nd=3):
    return "–" if x is None else f"{x:.{nd}f}"


def _label(race_id: str) -> str:
    return race_id[5:] if race_id.startswith("2026-") else race_id


def markdown(s: dict, as_of: str) -> str:
    R, V = s["races"], s["vote_share"]
    names = {"senate": "Senate", "governor": "Governor", "house": "House", "all": "All three",
             "independent": "Independent challengers (NE, ID, SD)"}
    L = [f"# Forecast v1: Provisional Score", "",
         f"**Provisional.** Results pulled from the AP public results feed at {as_of}. Counting is still "
         "under way and the uncalled races are left out; these numbers will change, and the final score "
         "waits for certification. v1 is scored as published on 22 October 2026.", "",
         "## Race Calls", "",
         "| | Called | Favourite won | Upsets | Expected upsets | Brier | Log loss | Baseline Brier (2024 lean) |",
         "|---|---|---|---|---|---|---|---|"]
    for k in ("senate", "governor", "house", "all", "independent"):
        g = R[k]
        b = g.get("baseline_lean") or {}
        L.append(f"| {names[k]} | {g['called']} of {g['races']} | {g['favourites_won']} | {g['upsets']} | "
                 f"{_num(g['expected_upsets'], 1)} | {_num(g['brier'])} | {_num(g['log_loss'])} | {_num(b.get('brier'))} |")
    L += ["", "The event scored is the one v1 gave a probability for: a win for the Democratic side (in "
          "Nebraska, Idaho and South Dakota, the independent). The baseline calls every race for the party "
          "that won it in the 2024 presidential vote. The three independent-challenger races are reported "
          "on their own and left out of the Senate and all-race rows; including them, the Senate Brier is "
          f"{_num(R['senate_incl_independents']['brier'])} over {R['senate_incl_independents']['called']} called races.", ""]
    ups = R["all"]["upset_list"] + R["independent"]["upset_list"]
    L += ["## Upsets", ""]
    if ups:
        L += ["| Race | Winner | v1's chance for the winner |", "|---|---|---|"]
        party = {"D": "Democrat", "R": "Republican", "I": "Independent"}
        for u in sorted(ups, key=lambda u: u["v1_p_winner"]):
            L.append(f"| {_label(u['id'])} | {u['winner_name']} ({party.get(u['winner_party'], u['winner_party'])}) | "
                     f"{_pct(u['v1_p_winner'])} |")
        by = pd.Series([u["winner_party"] for u in ups]).value_counts()
        L += ["", "Winners of the upsets by party: " + ", ".join(f"{party.get(p, p)}s {n}" for p, n in by.items()) + "."]
    else:
        L.append("None among the called races.")
    um = R["all"]["unmodelled_winners"] + R["independent"]["unmodelled_winners"]
    if um:
        L += ["", "Won by a candidate v1 did not model as either side: " +
              ", ".join(f"{u['id']} ({u['winner_name']})" for u in um) + "."]
    L += ["", "## Calibration", "", "Called races by v1's probability of a Democratic-side win.", "",
          "| Bin | Senate and governor: races | mean p | won | House: races | mean p | won |",
          "|---|---|---|---|---|---|---|"]
    for a, b in zip(R["senate_and_governor"]["calibration"], R["house"]["calibration"]):
        L.append(f"| {a['bin']} | {a['races']} | {_num(a['mean_p'], 2)} | {_num(a['win_rate'], 2)} | "
                 f"{b['races']} | {_num(b['mean_p'], 2)} | {_num(b['win_rate'], 2)} |")
    L += ["", "## Two-Party Vote Share", "",
          f"Called Democrat-against-Republican races with at least {MIN_COUNTED:.0%} of the expected vote counted. "
          "Error is the actual Democratic share minus v1's median, in points.", "",
          "| | Races | Mean error | MAE | RMSE | Below 80% | Inside 80% | Above 80% | Coverage | Baseline MAE |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for k in ("senate", "governor", "house", "all", "independent"):
        v = V[k]
        L.append(f"| {names[k]} | {v['n']} | {_num(v['mean_error_toward_dem'], 2)} | {_num(v['mae'], 2)} | "
                 f"{_num(v['rmse'], 2)} | {v['below_80']} | {v['inside_80']} | {v['above_80']} | "
                 f"{_pct(v['coverage_80'])} | {_num(v['baseline_lean_mae'], 2)} |")
    L += ["", "The target coverage is 80%, with about 10% of results on each side. For the independent "
          "challengers the share is the independent's share of the independent-plus-Republican vote. The "
          "baseline is the 2024 presidential two-party share of the state or district.", "",
          "## Seats and Control", "",
          "| | Democrats | Republicans | Other | Complete | Control | v1's chance for that party | v1 median (80% range) | Percentile |",
          "|---|---|---|---|---|---|---|---|---|"]
    for k in ("senate", "house", "governor"):
        c, ch, p = s["chambers"][k], s["chamber_chance"][k], s["seat_percentiles"][k]
        ctl = {"D": "Democrats", "R": "Republicans", None: "not yet decided"}[c["control"]]
        if p["percentile"] is not None:
            per = f"{_pct(p['percentile'])} ({'inside' if p['inside_80'] else 'outside'} the 80% range)"
        else:
            lo, hi = p["percentile_range"]
            per = f"not final; between {_pct(lo)} and {_pct(hi)}"
        L.append(f"| {names[k]} | {c['dem_seats']} | {c['rep_seats']} | {c['ind_seats']} | "
                 f"{'yes' if c['complete'] else 'no'} | {ctl} | {_pct(ch['v1_p_winner'])} | "
                 f"{p['v1_median']:.0f} ({p['v1_lo80']:.0f} to {p['v1_hi80']:.0f}) | {per} |")
    L += ["", "Seats include those not up in 2026 (Senate: Democratic caucus, with independents who caucus with "
          "Democrats). Senate control needs 51 Democratic-caucus seats or 50 Republican; a governor majority is 26.",
          "", "## Not Yet Scored", ""]
    u = s["uncalled"]
    L += [f"- Uncalled: {len(u['senate'])} Senate ({', '.join(map(_label, u['senate'])) or 'none'}), "
          f"{len(u['governor'])} governor ({', '.join(map(_label, u['governor'])) or 'none'}) and "
          f"{len(u['house'])} House races. Races in a runoff count as uncalled.",
          "- Turnout: not scored. Counts are far from final, especially where mail ballots arrive late, so "
          "every turnout measure is left null.",
          "- Montana's Senate race, a stated weakness before the election: v1 modelled it as the Democrat "
          "against the Republican, though the main challenger is an independent. It is scored as v1 "
          "defined it once called.", ""]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pull", help="pull_id in the results log (default: the latest)")
    a = ap.parse_args()
    log = pd.read_csv(LOG, dtype={"winner_party": "string"})
    pid = a.pull or log["pull_id"].max()
    res = log[log["pull_id"] == pid]
    as_of = res["pulled_at"].iloc[0]
    f = frame(res)
    s = score(f)
    full = {"as_of": as_of, "status": "provisional", "pull_id": pid, "min_counted_for_vote_share": MIN_COUNTED,
            **s}
    (RESULTS / "score_provisional.json").write_text(json.dumps(full, indent=1, default=_json_default) + "\n")
    (RESULTS / "results.json").write_text(json.dumps(contract_json(f, s, as_of), indent=1,
                                                     default=_json_default) + "\n")
    (RESULTS / "score_provisional.md").write_text(markdown(s, as_of))
    print(markdown(s, as_of))


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if o is pd.NA:
        return None
    raise TypeError(type(o))


if __name__ == "__main__":
    main()

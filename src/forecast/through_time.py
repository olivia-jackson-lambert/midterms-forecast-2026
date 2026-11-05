"""Forecast v1 through time (issue #29): v1's code rerun as of earlier and later dates. DIAGNOSTIC ONLY.

    python -m forecast.through_time [--fetch] [--pull PULL_ID]

Each rerun is v1's own code (tag `v1`; the model modules are unchanged since) with v1's fits
and seeds, run as it would have stood on one date with only what was public on that date:

- Race polls: every 2026 race article on Wikipedia at its last revision on or before the end of
  the date (23:59:59 UTC), parsed with v1's parser, and averaged with v1's rules relative to the
  date (fieldwork ended on or before the date and within 90 days of it; 21-day half-life).
- Generic ballot: the mean of the aggregators on Wikipedia's 2026 House page at its revision as
  of the same moment, as v1 read the live page on 22 October.
- Everything else as in v1: the fits (2018 and 2022), the generic-ballot bias and spread (from
  30 September values in earlier cycles, which do not depend on the 2026 date), the candidates and
  incumbents (v1's race and House pages of 22 October), the turnout-weighted leans and the seeds.

22 October uses v1's own saved inputs (the pages v1 fetched that day, and its generic ballot),
and must reproduce forecasts/v1 exactly; the script stops if it does not. The revision-based
inputs for 22 October are also built, and compared with v1's, as a check on the method.

Each date is run twice: as v1 was built, and with the generic-ballot bias set to 0 (H1 in #24,
spread unchanged). Every rerun is scored against the latest results pull with forecast.score's
measures, as in forecast.diagnostics. Nothing here changes v1 or its score (#15).

Writes results/through_time.json (for the site's Results view) and the "Through Time" section
of results/diagnostics.md. Rerun tables go to data/processed/through_time_v1/<date>_<variant>/
(local, never committed, each marked DIAGNOSTIC). Revisions are cached under
data/raw/polls/through_time/.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import diagnostics as dg
from . import generic_ballot, house, polls, vote_model
from .ingest import OUT, RAW
from .results import RESULTS, V1

YEAR = dg.YEAR
DATES = ["2026-09-01", "2026-09-15", "2026-10-01", "2026-10-15", "2026-10-22", "2026-10-29", "2026-11-02"]
V1_DATE = "2026-10-22"
AS_OF_TIME = "T23:59:59Z"
RAW_TT = RAW / "polls" / "through_time"
TT = OUT / "through_time_v1"
VARIANTS = {"v1_as_built": ("v1's code as built, inputs as of the date", None),
            "bias_0": ("generic-ballot bias set to 0 (H1 in #24), spread as v1", 0.0)}
SECTION = "## Through Time"
SCORE_KEYS = ("called", "upsets", "expected_upsets", "brier", "log_loss", "vote_n", "mean_error", "mae", "coverage_80")
SENATE_SEATS, GOVERNORS, HOUSE_SEATS = 100, 50, house.SEATS


def as_of(date: str) -> str:
    return date + AS_OF_TIME


# --------------------------------------------------------------------------- seats and control
def _quantile(by: pd.Series, q: float) -> int:
    """Smallest seat count whose cumulative probability reaches q (by: probability by seat count)."""
    c = by.sort_index().cumsum() / by.sum()
    return int(c.index[np.searchsorted(c.to_numpy(), q - 1e-9)])


def seat_summary(dist: pd.DataFrame, total: int, majority: int) -> dict:
    """Control chances and Democratic seats (median, 80% range) from a v1-format seat distribution
    (dem_seats, independent_seats, probability). Republicans hold the seats that are neither."""
    rep = total - dist["dem_seats"] - dist["independent_seats"]
    by = dist.groupby("dem_seats")["probability"].sum()
    return {"dem_control": round(float(dist.loc[dist["dem_seats"] >= majority, "probability"].sum()), 4),
            "rep_control": round(float(dist.loc[rep >= majority, "probability"].sum()), 4),
            "dem_seats_median": _quantile(by, 0.5), "dem_seats_lo80": _quantile(by, 0.1),
            "dem_seats_hi80": _quantile(by, 0.9)}


def _senate_summary(dist: pd.DataFrame) -> dict:
    """Control as v1 states it: Democrats need 51 (the Vice President is a Republican), Republicans 50."""
    s = seat_summary(dist, SENATE_SEATS, 51)
    rep = SENATE_SEATS - dist["dem_seats"] - dist["independent_seats"]
    s["rep_control"] = round(float(dist.loc[rep >= 50, "probability"].sum()), 4)
    return s


def chances_from_dists(dists: dict) -> dict:
    """A majority of governorships is 26; the House needs 218."""
    return {"senate": _senate_summary(dists["senate"]), "governor": seat_summary(dists["governor"], GOVERNORS, 26),
            "house": seat_summary(dists["house"], HOUSE_SEATS, house.MAJORITY)}


def distributions(run: dict) -> dict:
    f, s = run["race_frame"], run["race_sims"]
    return {"senate": vote_model.senate_seats(f, s), "governor": vote_model.governor_seats(f, s),
            "house": house.seat_distribution(run["house_frame"], run["house_sims"])}


def v1_distributions() -> dict:
    return {k: pd.read_csv(V1 / f"{k}_seats.csv") for k in ("senate", "governor", "house")}


def seats_gap(dists: dict) -> float:
    """Largest difference between a rerun's seat distributions and forecasts/v1's (v1 rounded to 4 dp)."""
    gap = 0.0
    for k, v1 in v1_distributions().items():
        key = ["dem_seats", "independent_seats"]
        m = v1.merge(dists[k][key + ["probability"]], on=key, how="outer", suffixes=("_v1", "_r")).fillna(0.0)
        gap = max(gap, float((m["probability_v1"] - m["probability_r"].round(4)).abs().max()))
    return gap


# --------------------------------------------------------------------------- inputs as of a date
def polls_as_of(date: str, fetch: bool = False) -> pd.DataFrame | None:
    """Every 2026 race article's polls at the date's revision (cached; fetched only with fetch)."""
    p = dg.load_late(as_of(date), RAW_TT)
    if p is None and fetch:
        p = dg.fetch_late(as_of(date), RAW_TT)
    return p


def generic_ballot_as_of(date: str, fetch: bool = False) -> dict:
    """The aggregators' generic ballot on the 2026 House page at the date's revision, or the reason
    it cannot be read. Never filled in from another date."""
    cached = sorted(RAW_TT.glob(f"house_2026_asof{date}_rev*.html"))
    if not cached and not fetch:
        return {"status": "not fetched"}
    try:
        g = dg.generic_ballot_late(as_of(date), RAW_TT)
    except ValueError as e:                       # no aggregate table on that revision
        return {"status": f"not reconstructible: {e}"}
    if g is None:
        return {"status": "not reconstructible: no revision of the House page on or before the date"}
    return {"status": "ok", **g}


def v1_generic_ballot() -> dict:
    h = generic_ballot.history()
    r = h[h["year"] == YEAR].iloc[0]
    return {"status": "ok", "as_of": str(r["as_of"]), "revision": None, "sources": str(r["source"]),
            "dem": float(r["dem"]), "rep": float(r["rep"]), "gb_dem_2p": float(r["gb_dem_2p"])}


def poll_summary(avgs: pd.DataFrame, ref: pd.DataFrame) -> dict:
    """Races and polls behind the averages, and the mean move of the average against v1's (points,
    toward Democrats) over races polled on both dates."""
    a = avgs[avgs["n_polls"] > 0]
    both = a.merge(ref[ref["n_polls"] > 0][["race_id", "poll_avg"]], on="race_id", suffixes=("", "_v1"))
    move = 100 * (both["poll_avg"] - both["poll_avg_v1"])
    return {"races_with_polls": int(len(a)), "polls_used": int(a["n_polls"].sum()),
            "races_polled_on_both": int(len(both)),
            "mean_change_vs_v1": round(float(move.mean()), 2) if len(both) else None,
            "mean_abs_change_vs_v1": round(float(move.abs().mean()), 2) if len(both) else None}


# --------------------------------------------------------------------------- scoring
def scores(res: pd.DataFrame, d: Path) -> dict:
    m = dg.metrics(res, d)
    return {g: {k: m[g][k] for k in SCORE_KEYS} for g in dg.GROUPS}


def race_movers(d: Path, ref: Path = V1, n: int = 5) -> list[dict]:
    """The Senate and governor races whose Democratic win chance differs most from v1's."""
    a = pd.read_csv(ref / "races.csv")[["race_id", "p_dem_win"]]
    b = pd.read_csv(d / "races.csv")[["race_id", "p_dem_win"]]
    m = a.merge(b, on="race_id", suffixes=("_v1", ""))
    m["change"] = m["p_dem_win"] - m["p_dem_win_v1"]
    m = m.reindex(m["change"].abs().sort_values(ascending=False).index).head(n)
    return [{"id": r.race_id, "p_dem_win": round(float(r.p_dem_win), 3), "p_dem_win_v1": round(float(r.p_dem_win_v1), 3)}
            for r in m.itertuples()]


# --------------------------------------------------------------------------- compute
def compute(pull: str | None = None, fetch: bool = False) -> dict:
    res = dg.results(pull)
    fits = dg.fitted()
    v1_avgs = polls.averages(YEAR, when=V1_DATE)
    note = "Diagnostic rerun for issue #29 (forecast through time)."

    # 1. 22 October with v1's own inputs must reproduce forecasts/v1 exactly.
    base = dg.rerun(fits, v1_avgs)
    d = dg.write_tables(base, f"{V1_DATE}_v1_as_built", v1_avgs, TT, note)
    gap, sgap = dg.reproduction_gap(d), seats_gap(distributions(base))
    if gap > 0 or sgap > 0:
        raise SystemExit(f"the 22 October rerun does not reproduce forecasts/v1 (tables {gap}, seats {sgap}); stopping")

    out = {"label": "DIAGNOSTIC. Reruns of v1's code at other dates; not part of v1's score (#15). v1 and the v1 tag are unchanged.",
           "issue": 29, "relates_to": [24], "pull_id": res["pull_id"].iloc[0], "pulled_at": res["pulled_at"].iloc[0],
           "status": "provisional", "min_counted_for_vote_share": dg.MIN_COUNTED, "as_of_time": AS_OF_TIME[1:],
           "reproduction": {"date": V1_DATE, "max_abs_difference_tables": gap, "max_abs_difference_seats": sgap},
           "v1_as_published": {"scores": scores(res, V1),
                                "note": "Control chances and seats for v1 are the 22 October v1_as_built row, which reproduces v1; "
                                        "v1's own seat files are rounded to four decimals, which takes up to 0.2 points off a chance."},
           "rows": []}

    gb_v1 = v1_generic_ballot()
    for date in DATES:
        own = date == V1_DATE
        gb = gb_v1 if own else generic_ballot_as_of(date, fetch)
        p = None if own else polls_as_of(date, fetch)
        problems = []
        if gb["status"] != "ok":
            problems.append(f"generic ballot {gb['status']}")
        if not own and p is None:
            problems.append("race-poll revisions not fetched")
        avgs = v1_avgs if own else (polls.averages(YEAR, p, when=date) if p is not None else None)
        inputs = {"race_polls": "v1's pages, fetched 22 October" if own else f"Wikipedia revisions as of {date}{AS_OF_TIME}",
                  "poll_cutoff": date, "generic_ballot": {k: gb.get(k) for k in ("status", "as_of", "revision", "sources", "updated", "gb_dem_2p")},
                  **(poll_summary(avgs, v1_avgs) if avgs is not None else {})}
        for name, (desc, bias) in VARIANTS.items():
            row = {"date": date, "variant": name, "description": desc, "label": "DIAGNOSTIC", "status": "provisional",
                   "pull_id": out["pull_id"], "inputs": inputs}
            if problems:
                out["rows"].append({**row, "reconstructed": False, "note": "; ".join(problems),
                                    "chances": None, "house_vote_mean": None, "scores": None})
                continue
            r = base if (own and bias is None) else dg.rerun(fits, avgs, bias=bias, gb=None if own else gb["gb_dem_2p"])
            d = dg.write_tables(r, f"{date}_{name}", avgs, TT, note)
            out["rows"].append({**row, "reconstructed": True,
                                "house_vote_mean": round(float(r["env"]["mean"]), 5), "bias": round(float(r["env"]["bias"]), 4),
                                "chances": chances_from_dists(distributions(r)), "scores": scores(res, d),
                                "largest_changes_from_v1": race_movers(d)})
            print(f"{date} {name}: done", flush=True)

    # The method check: 22 October from revisions rather than v1's own fetch.
    rp, rg = polls_as_of(V1_DATE, fetch), generic_ballot_as_of(V1_DATE, fetch)
    chk = {"generic_ballot_revision": rg.get("gb_dem_2p"), "generic_ballot_v1": gb_v1["gb_dem_2p"]}
    if rp is not None:
        ra = polls.averages(YEAR, rp, when=V1_DATE)
        m = ra.merge(v1_avgs, on="race_id", how="outer", suffixes=("_rev", "_v1"))
        for c in ("n_polls_rev", "n_polls_v1"):
            m[c] = m[c].fillna(0).astype(int)
        both = m[(m["n_polls_rev"] > 0) & (m["n_polls_v1"] > 0)]
        chk |= {"races_with_polls_revision": int((m["n_polls_rev"] > 0).sum()), "races_with_polls_v1": int((m["n_polls_v1"] > 0).sum()),
                "races_same_poll_count": int((m["n_polls_rev"] == m["n_polls_v1"]).sum()), "races": int(len(m)),
                "max_abs_poll_avg_difference_points": round(float(100 * (both["poll_avg_rev"] - both["poll_avg_v1"]).abs().max()), 3)}
    out["revision_check_22_october"] = chk
    return out


# --------------------------------------------------------------------------- write-up
_f, _p = dg._f, dg._p


def _row(d: dict, date: str, variant: str) -> dict | None:
    return next((r for r in d["rows"] if r["date"] == date and r["variant"] == variant), None)


def _date(s: str) -> str:
    return f"{pd.Timestamp(s):%-d %b}"


def markdown(d: dict) -> str:
    L = [SECTION, "",
         "**DIAGNOSTIC.** v1's own code rerun as it would have stood on seven dates, each with only what was public "
         "that day (issue #29). v1 as published on 22 October remains the forecast of record and its score (#15) is "
         "unchanged; none of these reruns is part of it. "
         f"Scored against AP's pull at {d['pulled_at']} (provisional), with the measures used above.", "",
         "On each date the race polls are the Wikipedia race articles at their last revision on or before 23:59:59 UTC, "
         "averaged with v1's rules relative to that date, and the generic ballot is the aggregators' mean on the 2026 House "
         "page at the same revision time. Everything else is v1's: the fits, the generic-ballot bias and spread, the "
         "candidates and incumbents as of 22 October, and the seeds. The 22 October rerun uses v1's own saved inputs and "
         f"reproduces `forecasts/v1/` exactly (largest difference {d['reproduction']['max_abs_difference_tables']:g} in the tables, "
         f"{d['reproduction']['max_abs_difference_seats']:g} in the seat distributions).", "",
         "| Date | Run | Generic ballot (D, 2-party) | House vote centre | Races polled | Senate D | House D | Governors D | "
         "House seats (80%) | Brier | Log loss | Upsets (exp.) | Mean error | MAE | 80% coverage |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for date in DATES:
        for v, lab in (("v1_as_built", "as built"), ("bias_0", "bias 0")):
            r = _row(d, date, v)
            if r is None:
                continue
            gb = r["inputs"]["generic_ballot"].get("gb_dem_2p")
            if not r["reconstructed"]:
                L.append(f"| {_date(date)} | {lab} | {_p(gb, 1) if gb else '–'} | – | – | not reconstructed: {r['note']} |" + " – |" * 9)
                continue
            c, s = r["chances"], r["scores"]["all"]
            h = c["house"]
            L.append(f"| {_date(date)}{' (v1)' if date == V1_DATE and v == 'v1_as_built' else ''} | {lab} | {_p(gb, 1)} | "
                     f"{_p(r['house_vote_mean'], 1)} | {r['inputs']['races_with_polls']} | {_p(c['senate']['dem_control'])} | "
                     f"{_p(c['house']['dem_control'])} | {_p(c['governor']['dem_control'])} | {h['dem_seats_median']} "
                     f"({h['dem_seats_lo80']}–{h['dem_seats_hi80']}) | {_f(s['brier'], 3)} | {_f(s['log_loss'], 3)} | "
                     f"{s['upsets']} ({_f(s['expected_upsets'], 1)}) | {_f(s['mean_error'], sign=True)} | {_f(s['mae'])} | {_p(s['coverage_80'])} |")
    L += ["", "Scores are over all called races (Senate, governor and House); vote-share measures over races with at least "
          f"{dg.MIN_COUNTED:.0%} counted. By office, Brier and mean error:", "",
          "| Date | Run | Senate | Governor | House |", "|---|---|---|---|---|"]
    for date in DATES:
        for v, lab in (("v1_as_built", "as built"), ("bias_0", "bias 0")):
            r = _row(d, date, v)
            if r is None or not r["reconstructed"]:
                continue
            L.append(f"| {_date(date)} | {lab} | " + " | ".join(
                f"{_f(r['scores'][o]['brier'], 3)}; {_f(r['scores'][o]['mean_error'], sign=True)}" for o in ("senate", "governor", "house")) + " |")
    L += ["", reading(d), "", caveats(d), ""]
    return "\n".join(L)


def reading(d: dict) -> str:
    """Two or three plain sentences on what moved and why, from the numbers."""
    built = [r for r in d["rows"] if r["variant"] == "v1_as_built" and r["reconstructed"]]
    zero = [r for r in d["rows"] if r["variant"] == "bias_0" and r["reconstructed"]]
    if not built:
        return "No date other than 22 October could be reconstructed."
    me = [r["scores"]["all"]["mean_error"] for r in built]
    br = [r["scores"]["all"]["brier"] for r in built]
    gbs = [r["inputs"]["generic_ballot"]["gb_dem_2p"] for r in built]
    first, last = built[0], built[-1]
    z_me = [r["scores"]["all"]["mean_error"] for r in zero]
    s1 = (f"Across the seven dates the generic ballot v1 would have read ranged from {_p(min(gbs), 1)} to {_p(max(gbs), 1)} Democratic, "
          f"and the as-built rerun's mean error toward Democrats stayed between {_f(min(me), sign=True)} and {_f(max(me), sign=True)} points "
          f"(Brier {_f(min(br), 3)} to {_f(max(br), 3)}): no lock date from {_date(first['date'])} to {_date(last['date'])} would have removed the "
          "Republican lean of the miss.")
    s2 = (f"Setting the generic-ballot bias to 0 lowers the mean error on every date (to between {_f(min(z_me), sign=True)} and "
          f"{_f(max(z_me), sign=True)} points), by more than any change of date does, so the correction matters more than the lock date."
          if z_me and max(z_me) < min(me) else
          f"Setting the generic-ballot bias to 0 gives mean errors between {_f(min(z_me), sign=True)} and {_f(max(z_me), sign=True)} points.")
    moves = [r["inputs"].get("mean_change_vs_v1") for r in built if r["date"] != V1_DATE and r["inputs"].get("mean_change_vs_v1") is not None]
    c0, c1 = first["chances"], last["chances"]
    s3 = (f"What moved was the generic ballot, which carries the House ({_p(c0['house']['dem_control'])} to {_p(c1['house']['dem_control'])} "
          f"for Democrats), and, for the Senate ({_p(c0['senate']['dem_control'])} to {_p(c1['senate']['dem_control'])}) and governors "
          f"({_p(c0['governor']['dem_control'])} to {_p(c1['governor']['dem_control'])}), the race polls: more races polled "
          f"({first['inputs']['races_with_polls']} to {last['inputs']['races_with_polls']}) and averages that, over races polled on both dates, "
          f"differed from v1's by {_f(min(moves), sign=True)} to {_f(max(moves), sign=True)} points on average."
          if moves else "")
    return " ".join(x for x in (s1, s2, s3) if x)


def caveats(d: dict) -> str:
    chk = d.get("revision_check_22_october", {})
    bits = ["**Limits.** Candidates and incumbents are v1's as of 22 October on every date, so on the early dates a race whose "
            "primary had not yet been held is modelled with its eventual nominees, and its polls are matched to them: a small "
            "look-ahead in the early reruns. The generic ballot is what the House page listed, which can lag the aggregators' own updates."]
    if chk.get("races_with_polls_revision") is not None:
        bits.append(f"As a check on the method, the 22 October inputs rebuilt from revisions give {chk['races_with_polls_revision']} races with polls "
                    f"against v1's {chk['races_with_polls_v1']}, the same number of polls in {chk['races_same_poll_count']} of {chk['races']} races, and poll "
                    f"averages within {_f(chk['max_abs_poll_avg_difference_points'])} points; the generic ballot "
                    f"{_p(chk['generic_ballot_revision'], 2)} against v1's {_p(chk['generic_ballot_v1'], 2)}.")
    not_ok = [r for r in d["rows"] if not r["reconstructed"]]
    if not_ok:
        bits.append("Not reconstructed: " + "; ".join(f"{_date(r['date'])} ({r['note']})" for r in not_ok if r["variant"] == "v1_as_built") + ".")
    return " ".join(bits)


def write_section(md: str, path: Path = RESULTS / "diagnostics.md") -> None:
    """Put the section into diagnostics.md, replacing an earlier one, before the Files section."""
    text = path.read_text()
    text = re.sub(rf"\n{re.escape(SECTION)}\n.*?(?=\n## |\Z)", "\n", text, flags=re.S)
    if "\n## Files" in text:
        a, b = text.split("\n## Files", 1)
        text = a.rstrip("\n") + "\n\n" + md.rstrip("\n") + "\n\n## Files" + b
    else:
        text = text.rstrip("\n") + "\n\n" + md
    path.write_text(text)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="v1 rerun through time (issue #29). DIAGNOSTIC ONLY.")
    ap.add_argument("--pull", help="pull_id in results/results_log.csv (default: the latest)")
    ap.add_argument("--fetch", action="store_true",
                    help="fetch the Wikipedia revisions for each date (about 90 minutes at the API's pace)")
    a = ap.parse_args(argv)
    d = compute(a.pull, a.fetch)
    (RESULTS / "through_time.json").write_text(json.dumps(dg._clean(d), indent=1) + "\n")
    md = markdown(d)
    write_section(md)
    print(md)


if __name__ == "__main__":
    main()

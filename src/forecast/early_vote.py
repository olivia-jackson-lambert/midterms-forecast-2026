"""October early and mail vote, compared with each state's own last midterm (PLAN §4, §10 item 7).

The Signal
----------
States differ hugely in how people vote: in an all-mail state a third of the electorate may
have voted three weeks out, in a state with excuse-only absentee voting almost nobody has.
Comparing states with each other therefore measures voting rules, not enthusiasm. The signal
here compares each state with itself, at the same number of days before the election:

    feature_s = log(E_s,t / T_s,t-4) - log(E_s,t-4 / T_s,t-8)

where E is early ballots returned (mail returned plus in-person early) 21 days before
Election Day, and T is the state's total ballots counted in the midterm before (UF Election
Lab certified totals). A state running ahead of its own last midterm pace gets a positive
value. The offset added to Stage A's state logit would be k * feature, with k fitted on one
earlier transition; `turnout_model.simulate` re-pins the national total, so offsets only
move states against each other.

States whose voting rules changed between the two cycles are excluded (`RULE_CHANGES`):
a move to universal mail, a new no-excuse mail law or a shorter mail window changes the
pace for reasons that have nothing to do with turnout.

The Rule (set before looking at any results)
--------------------------------------------
Fit k on the 2018 transition (2018 pace against 2014), test on 2022 (2022 against 2018).
Wire the offsets into the 2026 forecast only if they improve BOTH the 2022 state turnout
MAE and the 2022 CVAP-weighted county MAE. If dated 2018 or 2022 state data do not exist,
do not wire it in.

What Exists (checked 13 October 2026)
-------------------------------------
- 2026, T-21 (13 October): UF Election Lab national CSV,
  https://election.lab.ufl.edu/data-downloads/earlyvote/2026/US.csv, saved on the day as
  raw/early_vote/uf_earlyvote_2026_US_20261013.csv. 37 states report returned ballots.
- 2022, T-21 (18 October): the national tracker was an RPubs page
  (https://rpubs.com/ElectProject/early_vote_2022). The Internet Archive holds the version
  "Last updated: 10/18/2022 10:18 AM Eastern" (captured 18 October 2022 15:03 UTC). It has
  national totals only (2,608,748 early votes); state figures sat on separate RPubs pages,
  which the Archive caught only on scattered dates (see `SNAPSHOTS[2022]`).
- 2018, T-21 (16 October): not available. McDonald's page
  (http://www.electproject.org/early_2018) was captured on 27 September and 20 October 2018,
  but its state table was an embedded Google Sheet whose tabs were never archived. The live
  sheet holds only the final pre-election report (as of 5 and 6 November 2018), a later
  revision, saved as raw/early_vote/gsheet_early_2018_final_accepted_20261013.csv for
  description only.
- 2014, T-21 (14 October): the same problem (http://www.electproject.org/2014_early_vote,
  captured 14 October 2014, embeds a sheet that was not archived).

So the 2018 fit and the 2022 test cannot be run, and under the rule the signal is not used
(`WIRED = False`, `state_offsets` returns nothing). The 2026 and 2022 downloads stay for
descriptive charts.

    python -m forecast.early_vote       # save today's 2026 copy; write the T-21 tables
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .ingest import OUT, RAW, UA

RAW_EV = RAW / "early_vote"

ELECTION_DAY = {2014: date(2014, 11, 4), 2018: date(2018, 11, 6),
                2022: date(2022, 11, 8), 2026: date(2026, 11, 3)}
DAYS_OUT = 21

UF_EARLY_VOTE_PAGE = "https://election.lab.ufl.edu/early-vote/2026-early-voting/"
UF_EARLY_VOTE_CSV = {2026: "https://election.lab.ufl.edu/data-downloads/earlyvote/2026/US.csv"}

# Where each cycle's early vote stood 21 days out, and whether it can be used.
SNAPSHOTS = {
    2026: {"usable": True, "as_of": "2026-10-13",
           "source": UF_EARLY_VOTE_CSV[2026],
           "file": "uf_earlyvote_2026_US_20261013.csv"},
    2022: {"usable": False, "as_of": "2022-10-18",
           "source": "https://rpubs.com/ElectProject/early_vote_2022",
           "archived": "https://web.archive.org/web/20221018150307/https://rstudio-pubs-static"
                       ".s3.amazonaws.com/948837_33894f88a1454fae8e8ac6d0e2c3f9e6.html",
           "file": "wayback/rpubs_early_vote_2022_20221018150307.html",
           "note": "national totals only at T-21; state pages archived on scattered dates"},
    2018: {"usable": False, "as_of": "2018-10-16",
           "source": "http://www.electproject.org/early_2018",
           "note": "state table was an embedded Google Sheet, never archived; live sheet is "
                   "the final 5-6 November 2018 report"},
    2014: {"usable": False, "as_of": "2014-10-14",
           "source": "http://www.electproject.org/2014_early_vote",
           "note": "state table was an embedded Google Sheet, never archived"},
}

# Voting-rule changes that move early-vote pace for reasons unrelated to turnout. Keyed by
# (earlier midterm, later midterm). Compiled from state law as reported by NCSL and the
# states; check against NCSL's tables before relying on any single entry.
RULE_CHANGES = {
    (2014, 2018): {
        "IA": "early voting window cut from 40 to 29 days (2017)",
        "UT": "most counties moved to all-mail between 2014 and 2018",
        "WA": "postage-paid ballot returns from 2018",
    },
    (2018, 2022): {
        "CA": "every active voter mailed a ballot (2021 law)",
        "NV": "every active voter mailed a ballot (AB 321, 2021)",
        "VT": "every active voter mailed a ballot (Act 60, 2021)",
        "UT": "all-mail statewide from 2019",
        "HI": "all-mail from 2020",
        "DC": "ballots mailed to all voters from 2020",
        "PA": "no-excuse mail voting (Act 77, 2019)",
        "VA": "no-excuse absentee and 45 days of early voting (2020)",
        "MI": "no-excuse absentee voting (Proposal 3, 2018)",
        "NJ": "permanent mail list and early in-person voting (2020-21)",
        "MA": "no-excuse mail voting (VOTES Act, 2022)",
        "DE": "no-excuse mail voting in 2022 (later struck down)",
        "NY": "early in-person voting from 2019",
        "GA": "mail ballots sent out from 29 days before, not 49 (SB 202, 2021)",
        "IA": "early voting window cut from 29 to 20 days (SF 413, 2021)",
        "KY": "three days of early in-person voting (2021)",
        "MD": "permanent mail list (2021)",
        "IL": "permanent mail list (2021)",
        "RI": "no-excuse mail voting (Let RI Vote Act, 2022)",
    },
    (2022, 2026): {
        "FL": "mail ballot requests now lapse after each general election cycle (SB 90, 2021)",
        "MI": "nine days of early in-person voting and a permanent mail list (Proposal 2, 2022)",
        "MN": "permanent absentee list (2023)",
        "NY": "no-excuse early mail voting (2024)",
        "CT": "early in-person voting from 2024",
        "DE": "no-excuse mail voting struck down (2022); early in-person voting kept",
        "UT": "universal mail being phased out (HB 300, 2025)",
        "OH": "shorter early voting and fewer drop boxes (HB 458, 2023)",
        "NC": "mail ballots due on Election Day (SB 747, 2023)",
    },
}

WIRED = False        # the rule could not be tested (no dated 2018 state data): not used
OFFSET_CLIP = 0.30   # cap on any state's logit offset, if ever wired


# --------------------------------------------------------------------------- the feature
def as_of(year: int) -> date:
    """The comparison date: DAYS_OUT days before that year's Election Day."""
    return ELECTION_DAY[year] - timedelta(days=DAYS_OUT)


def pace(ballots, prev_turnout):
    """Early ballots returned as a share of the state's previous-midterm turnout."""
    return np.asarray(ballots, dtype=float) / np.asarray(prev_turnout, dtype=float)


def pace_change(ev_now, turnout_prev, ev_then, turnout_prevprev):
    """log(this cycle's pace) minus log(the last midterm's pace at the same days-out)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.log(pace(ev_now, turnout_prev)) - np.log(pace(ev_then, turnout_prevprev))
    return np.where(np.isfinite(out), out, np.nan)


def feature_frame(now: pd.DataFrame, then: pd.DataFrame, turnout: pd.DataFrame,
                  year: int) -> pd.DataFrame:
    """One row per state: both paces, the feature, and why a state is left out.

    `now` and `then` have state_po and ballots (early ballots returned at T-21 in `year` and
    `year - 4`); `turnout` has year, state_po and uf_ballots (certified totals).
    """
    tot = turnout.pivot_table(index="state_po", columns="year", values="uf_ballots")
    d = (now[["state_po", "ballots"]].rename(columns={"ballots": "ev_now"})
         .merge(then[["state_po", "ballots"]].rename(columns={"ballots": "ev_then"}),
                on="state_po", how="outer"))
    d["turnout_prev"] = d["state_po"].map(tot.get(year - 4, pd.Series(dtype=float)))
    d["turnout_prevprev"] = d["state_po"].map(tot.get(year - 8, pd.Series(dtype=float)))
    d["pace_now"] = pace(d["ev_now"], d["turnout_prev"])
    d["pace_then"] = pace(d["ev_then"], d["turnout_prevprev"])
    d["feature"] = pace_change(d["ev_now"], d["turnout_prev"], d["ev_then"], d["turnout_prevprev"])
    changes = RULE_CHANGES.get((year - 4, year), {})
    d["rule_change"] = d["state_po"].map(changes).fillna("")
    d["excluded"] = np.select(
        [d["rule_change"] != "", ~(d["ev_now"] > 0) | ~(d["ev_then"] > 0), d["feature"].isna()],
        ["voting rules changed", "no early ballots reported in one cycle", "missing turnout"],
        default="")
    d.loc[d["excluded"] != "", "feature"] = np.nan
    return d.sort_values("state_po").reset_index(drop=True)


def fit_k(feature: pd.Series, residual: pd.Series, weight: pd.Series | None = None) -> float:
    """Least-squares slope through the origin of a state's logit turnout residual (actual
    minus Stage A median, national level pinned) on its feature, over usable states."""
    d = pd.concat({"x": feature, "y": residual,
                   "w": weight if weight is not None else pd.Series(1.0, index=feature.index)},
                  axis=1).dropna()
    if len(d) < 3 or (d["x"] ** 2 * d["w"]).sum() == 0:
        return 0.0
    return float((d["x"] * d["y"] * d["w"]).sum() / (d["x"] ** 2 * d["w"]).sum())


def offsets(feature: pd.Series, k: float, clip: float = OFFSET_CLIP) -> pd.Series:
    """Stage A state logit offsets, k * feature, capped; states without a feature get 0."""
    return (k * feature.astype(float)).clip(-clip, clip).fillna(0.0).rename("early_vote_offset")


def passes_rule(state_mae: tuple[float, float], county_mae: tuple[float, float]) -> bool:
    """The pre-registered rule. Each argument is (with offsets, without offsets) for 2022;
    both errors must fall."""
    return state_mae[0] < state_mae[1] and county_mae[0] < county_mae[1]


# --------------------------------------------------------------------------- 2026 (UF CSV)
def _num(s) -> pd.Series:
    return pd.to_numeric(pd.Series(s).astype(str).str.replace(",", ""), errors="coerce")


def _max_update(series: pd.Series) -> str:
    """Latest last_update as an ISO date (a string max is wrong for M/D/YYYY)."""
    dt = pd.to_datetime(series, errors="coerce", format="mixed")
    if dt.notna().any():
        return dt.max().strftime("%Y-%m-%d")
    vals = [str(v) for v in series.dropna().astype(str) if str(v).strip()]
    return max(vals) if vals else ""


def fetch_csv(year: int = 2026, on: date | None = None, force: bool = False) -> Path:
    """Save the UF Election Lab national CSV under a dated name (it is overwritten daily at
    the source, so each download is the only record of that day)."""
    url = UF_EARLY_VOTE_CSV.get(year)
    if url is None:
        raise ValueError(f"no UF early-vote CSV configured for {year}")
    RAW_EV.mkdir(parents=True, exist_ok=True)
    dest = RAW_EV / f"uf_earlyvote_{year}_US_{(on or date.today()):%Y%m%d}.csv"
    if dest.exists() and not force:
        return dest
    with requests.get(url, headers=UA, timeout=120) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(r.content)
    tmp.rename(dest)
    return dest


def parse_uf_csv(path: Path, year: int = 2026) -> pd.DataFrame:
    """One row per state: early ballots returned and their share of 2022 turnout."""
    raw = pd.read_csv(path)
    if "state_abbv" not in raw.columns:
        raise ValueError(f"unexpected early-vote schema in {path}")
    col = lambda c: _num(raw[c]).fillna(0.0).values if c in raw else np.zeros(len(raw))
    d = pd.DataFrame({
        "year": year,
        "state_po": raw["state_abbv"].astype(str).str.upper().str.strip(),
        "state": raw.get("state"),
        "turn_2022": _num(raw["turn_2022"]).values,
        "last_update": raw.get("last_update"),
        "request_all": col("request_all"), "accept_all": col("accept_all"),
        "inperson_all": col("inperson_all"), "voted_all": col("voted_all"),
    })
    # voted_all already combines mail and in-person in most states; fall back to the sum.
    d["ballots"] = np.where(d["voted_all"] > 0, d["voted_all"], d["accept_all"] + d["inperson_all"])
    d["early_share"] = d["ballots"] / d["turn_2022"].clip(lower=1.0)
    d["reporting"] = d["ballots"] > 0
    d["source"] = "uf_election_lab"
    d["source_url"] = UF_EARLY_VOTE_CSV[year]
    return d.sort_values("state_po").reset_index(drop=True)


# --------------------------------------------------------------------------- 2022 (RPubs)
_FIELDS = {"ballots": "Total Early Votes", "inperson": "In-Person Early Votes",
           "mail_returned": "Mail Ballots Returned", "mail_requested": "Mail Ballots Requested"}


def parse_rpubs(html: str) -> dict:
    """Headline numbers and update stamp from a 2022 RPubs tracker page (national or state)."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    out = {}
    for key, label in _FIELDS.items():
        m = re.search(re.escape(label) + r":\s*([0-9,]+)", text)
        out[key] = float(m.group(1).replace(",", "")) if m else np.nan
    m = re.search(r"Last update[d]?:\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{4})", text)
    out["last_update"] = (pd.to_datetime(m.group(1).replace("-", "/"), format="%m/%d/%Y").date()
                          if m else None)
    return out


def rpubs_2022_states(folder: Path | None = None) -> pd.DataFrame:
    """Every archived 2022 state page, with its stamp and days before Election Day."""
    folder = folder or RAW_EV / "wayback" / "rpubs2022"
    rows = []
    for p in sorted(folder.glob("rpubs_??_2022_*.html")):
        r = parse_rpubs(p.read_text(encoding="utf8", errors="ignore"))
        days = (ELECTION_DAY[2022] - r["last_update"]).days if r["last_update"] else np.nan
        rows.append({"state_po": p.name[6:8], "file": p.name, **r, "days_out": days})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- outputs
def state_offsets(year: int = 2026) -> pd.Series:
    """Offsets for Stage A. Empty while WIRED is False: the rule could not be tested, so
    `turnout_model.run(early_vote=True)` changes nothing."""
    return pd.Series(dtype=float, name="early_vote_offset")


def load(year: int = 2026) -> pd.DataFrame:
    """The cached state table, or an empty frame."""
    path = OUT / f"early_vote_{year}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame(columns=["year", "state_po", "ballots", "early_share", "reporting", "source"])


def national_pace(year: int = 2026) -> dict:
    """Early ballots returned as a share of 2022 turnout, over reporting states."""
    d = load(year)
    rep = d.loc[d["reporting"].astype(bool)] if len(d) else d
    if rep.empty:
        return {"year": year, "n_reporting": 0, "early_share": float("nan"),
                "source": "missing" if d.empty else "no_reports"}
    returned, base = float(rep["ballots"].sum()), float(rep["turn_2022"].sum())
    return {"year": year, "n_reporting": int(len(rep)), "n_states": int(len(d)),
            "ballots_returned": returned, "turn_2022_reporting": base,
            "early_share": returned / base if base else float("nan"),
            "last_update_max": _max_update(rep["last_update"]), "source": "uf_election_lab",
            "page": UF_EARLY_VOTE_PAGE}


def status() -> pd.DataFrame:
    """One row per cycle: what exists at T-21 and whether it can be used."""
    return pd.DataFrame([{"year": y, "election_day": ELECTION_DAY[y].isoformat(),
                          "t_minus_21": as_of(y).isoformat(), **{k: v for k, v in s.items()}}
                         for y, s in sorted(SNAPSHOTS.items())]).assign(wired=WIRED)


def build(year: int = 2026, path: Path | None = None) -> pd.DataFrame:
    """Write early_vote_{year}.parquet (state pace against 2022 turnout) and
    early_vote_status.csv. Uses the T-21 snapshot when it exists."""
    path = path or RAW_EV / SNAPSHOTS[year]["file"]
    if not path.exists():
        path = fetch_csv(year)
    d = parse_uf_csv(path, year)
    d["snapshot"] = path.name
    d["rule_change_since_2022"] = d["state_po"].map(RULE_CHANGES[(2022, 2026)]).fillna("")
    d["early_vote_offset"] = 0.0
    OUT.mkdir(parents=True, exist_ok=True)
    d.to_parquet(OUT / f"early_vote_{year}.parquet", index=False)
    status().to_csv(OUT / "early_vote_status.csv", index=False)
    return d


def main() -> None:
    try:
        print("saved today's copy:", fetch_csv(2026).name)
    except requests.RequestException as exc:
        print("could not download today's copy:", exc)
    d = build(2026)
    pace_ = national_pace(2026)
    print(f"2026 snapshot {d['snapshot'].iloc[0]}: {int(d['reporting'].sum())} states reporting, "
          f"{pace_['ballots_returned']:,.0f} ballots, {pace_['early_share']:.3f} of their 2022 turnout")
    print(status()[["year", "t_minus_21", "usable"]].to_string(index=False))
    print("wired into Stage A:", WIRED)


if __name__ == "__main__":
    main()

"""Write a forecast release: the published tables for one version.

    python -m forecast.release <version> [--draft] [--root DIR]

Reads the processed outputs of the pipeline (it does not fit anything) and writes, to
forecasts/<version>/ (forecasts/_draft/<version>/ with --draft, which git ignores):

    turnout_counties.csv  county turnout, 2022 and the 2026 forecast (median, 80% interval)
    turnout_states.csv    the same by state
    national.csv          national turnout and House vote, with the generic ballot behind it
    races.csv             every 2026 Senate and governor race, with its poll average
    senate_seats.csv      distribution of Democratic-caucus Senate seats
    house_districts.csv   all 435 House districts
    house_seats.csv       distribution of House seats (Democratic, Republican, independent)
    backtests.csv         the 2018 and 2022 backtest scores (turnout, races, House), one metric per row
    manifest.json         version, time, git commit, input dates, simulation counts, file hashes

Shares are rounded to four decimals and probabilities to three.

Column notes. In the turnout tables `lo80`/`hi80` include uncertainty in national turnout;
`lo80_county`/`lo80_state` (and `hi80_`) hold national turnout at its median, so they show
only what is left to the county or state itself. Turnout is votes cast as a share of
citizen voting-age population. In races.csv, `d_side` says who stands on the Democratic
side (a Democrat, or an independent where no Democrat runs) and the shares and
probabilities are for that side. `poll_avg` is the Democratic-side share of the two-party
poll average and `n_polls` the number of polls behind it (0 and blank where no polls exist).
The median of the fundamentals alone is not saved by the pipeline, so races.csv has no such
column.

In house_districts.csv the median and 80% interval are the Democratic share of the two-party
vote and are blank in the districts that are not modelled (a certain hold, where only one
party's candidate is on the ballot). `contested` is true where a Democrat stands against a
Republican; `stand_in` names the candidate who takes the place of a missing party;
`certain_hold_party` is D or R for a certain hold. The three win probabilities sum to one up
to rounding. In backtests.csv the "model" variant of the race backtest is the one with polls,
as published. The House rows appear once `forecast.backtest house` has run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import re
import zipfile
from pathlib import Path

import pandas as pd

from . import backtest, generic_ballot
from .ingest import RAW, OUT, ROOT

RAW_HOUSE = RAW / "house"

SHARE_DP, PROB_DP = 4, 3
FORECAST_YEAR = 2026

# Names for county units that are not a single Census county.
MERGED_NAMES = {
    "02000": "Alaska (statewide)",
    "09000": "Connecticut (statewide)",
    "11001": "District of Columbia",
    "29095": "Jackson, Clay and Platte (Kansas City unit)",
}
TURNOUT_VARIANTS = {True: "model", False: "no_out_party_term"}
TURNOUT_TRAINED_ON = {y: ("priors only" if not t else ", ".join(map(str, t))) for y, t in backtest.BACKTESTS.items()}


# --------------------------------------------------------------------------- inputs
def county_names() -> pd.Series:
    """County unit FIPS -> name, from the Census Gazetteer, with the merged units named by hand."""
    with zipfile.ZipFile(RAW / "gazetteer_counties_2024.zip") as z:
        df = pd.read_csv(z.open(z.namelist()[0]), sep="\t", dtype={"GEOID": str})
    df.columns = df.columns.str.strip()
    names = df.set_index("GEOID")["NAME"].str.strip()
    return pd.concat([names[~names.index.isin(list(MERGED_NAMES))], pd.Series(MERGED_NAMES)])


def _rounded(df: pd.DataFrame, shares: list[str] = (), probs: list[str] = ()) -> pd.DataFrame:
    df = df.copy()
    df[list(shares)] = df[list(shares)].round(SHARE_DP)
    df[list(probs)] = df[list(probs)].round(PROB_DP)
    return df


# --------------------------------------------------------------------------- tables
def turnout_counties() -> pd.DataFrame:
    f = pd.read_parquet(OUT / "turnout_2026.parquet")
    past = pd.read_parquet(OUT / "county_midterm_turnout.parquet")
    past = past[past["year"] == FORECAST_YEAR - 4].set_index("unit_fips")["turnout"]
    out = pd.DataFrame({
        "unit_fips": f["unit_fips"], "county": f["unit_fips"].map(county_names()), "state": f["state_po"],
        "turnout_2022": f["unit_fips"].map(past),
        "turnout_2026_median": f["median"], "turnout_2026_lo80": f["lo80"], "turnout_2026_hi80": f["hi80"],
        "turnout_2026_lo80_county": f["lo80_county"], "turnout_2026_hi80_county": f["hi80_county"],
        "cvap": f["cvap"].round().astype(int)})
    out = out.sort_values("unit_fips").reset_index(drop=True)
    return _rounded(out, shares=[c for c in out if c.startswith("turnout_")])


def turnout_states() -> pd.DataFrame:
    s = pd.read_parquet(OUT / "turnout_2026_states.parquet")
    past = pd.read_parquet(OUT / "county_midterm_turnout.parquet")
    past = past[past["year"] == FORECAST_YEAR - 4]
    past = past.groupby("state_po").apply(lambda d: d["ballots"].sum() / d["cvap"].sum(), include_groups=False)
    out = pd.DataFrame({
        "state": s["state_po"], "turnout_2022": s["state_po"].map(past),
        "turnout_2026_median": s["median"], "turnout_2026_lo80": s["lo80"], "turnout_2026_hi80": s["hi80"],
        "turnout_2026_lo80_state": s["lo80_state"], "turnout_2026_hi80_state": s["hi80_state"]})
    out = out.sort_values("state").reset_index(drop=True)
    return _rounded(out, shares=[c for c in out if c.startswith("turnout_")])


def national() -> pd.DataFrame:
    t = pd.read_csv(OUT / "turnout_2026_national.csv").set_index("quantile")["turnout"]
    env = generic_ballot.national_environment(FORECAST_YEAR)
    lo, hi = generic_ballot.interval(env)
    gb = generic_ballot.history()
    as_of = gb.loc[gb["year"] == FORECAST_YEAR, "as_of"].iloc[0]
    row = {"turnout_2026_median": t[0.5], "turnout_2026_lo80": t[0.1], "turnout_2026_hi80": t[0.9],
           "house_dem_2p_mean": env["mean"], "house_dem_2p_lo80": lo, "house_dem_2p_hi80": hi,
           "generic_ballot_dem_2p": env["gb_dem_2p"], "generic_ballot_bias": env["bias"],
           "generic_ballot_as_of": str(as_of)}
    return _rounded(pd.DataFrame([row]), shares=[c for c in row if c != "generic_ballot_as_of"])


def races() -> pd.DataFrame:
    v = pd.read_parquet(OUT / "vote_share_2026.parquet")
    out = pd.DataFrame({
        "race_id": v["race_id"], "state": v["state_po"],
        "office": v["office"].map({"SEN": "senate", "GOV": "governor"}), "special": v["special"],
        "incumbent": v["incumbent"], "incumbent_party": v["incumbent_party"], "open_seat": v["open_seat"],
        "dem_candidate": v["dem_candidate"], "rep_candidate": v["rep_candidate"], "d_side": v["d_side"],
        "dem_share_median": v["median"], "dem_share_lo80": v["lo80"], "dem_share_hi80": v["hi80"],
        "p_dem_win": v["p_dem_win"]})
    out = out.sort_values("race_id").reset_index(drop=True)
    out = out.merge(poll_averages(), on="race_id", how="left")
    out["n_polls"] = out["n_polls"].fillna(0).astype(int)
    out.loc[out["n_polls"] == 0, "poll_avg"] = float("nan")
    return _rounded(out, shares=["dem_share_median", "dem_share_lo80", "dem_share_hi80", "poll_avg"],
                    probs=["p_dem_win"])


def poll_averages() -> pd.DataFrame:
    """The 2026 race poll averages (Democratic side) and poll counts from forecast.polls."""
    a = pd.read_csv(OUT / "poll_averages.csv")
    return a[a["year"] == FORECAST_YEAR][["race_id", "poll_avg", "n_polls"]]


def house_districts() -> pd.DataFrame:
    h = pd.read_parquet(OUT / "house_2026.parquet")
    m = h["modelled"].astype(bool)
    out = pd.DataFrame({
        "cd": h["cd"], "state": h["state_po"], "incumbents_running": h["incumbents_running"].fillna(""),
        "dem_candidates": h["dem_candidates"].fillna(""), "rep_candidates": h["rep_candidates"].fillna(""),
        "stand_in": h["stand_in"].fillna(""), "contested": h["contested"].astype(bool),
        "certain_hold_party": h["sole_party"].where(~m).fillna(""),
        "presidential_lean_dem_2p": h["lean_plain"],
        "dem_share_median": h["median"].where(m), "dem_share_lo80": h["lo80"].where(m),
        "dem_share_hi80": h["hi80"].where(m),
        "p_dem_win": h["p_dem_win"], "p_rep_win": h["p_rep_win"], "p_ind_win": h["p_ind_win"]})
    out = out.sort_values("cd").reset_index(drop=True)
    return _rounded(out, shares=["presidential_lean_dem_2p", "dem_share_median", "dem_share_lo80",
                                 "dem_share_hi80"], probs=["p_dem_win", "p_rep_win", "p_ind_win"])


def house_seats() -> pd.DataFrame:
    s = pd.read_csv(OUT / "house_seats_2026.csv")
    s["probability"] = s["probability"].round(4)
    s = s[["dem_seats", "rep_seats", "independent_seats", "probability"]]
    return s.sort_values(["dem_seats", "independent_seats"]).reset_index(drop=True)


def senate_seats() -> pd.DataFrame:
    s = pd.read_csv(OUT / "senate_seats_2026.csv")
    # Four decimals: 20,000 simulations resolve 0.00005, and three would show the tails as 0.
    s["probability"] = s["probability"].round(4)
    return s.sort_values(["dem_seats", "independent_seats"]).reset_index(drop=True)


def backtests() -> pd.DataFrame:
    t = pd.read_csv(OUT / "backtest_turnout.csv")
    t["variant"] = t["out_party"].map(TURNOUT_VARIANTS)
    t["trained_on"] = t["year"].map(TURNOUT_TRAINED_ON)
    t = t.drop(columns="out_party").melt(["year", "variant", "trained_on"], var_name="metric")
    t.insert(0, "backtest", "turnout")
    r = pd.read_csv(OUT / "backtest_races.csv")
    r["variant"] = r["variant"].str.replace(" ", "_")
    r = r.melt(["year", "variant", "trained_on"], var_name="metric")
    r.insert(0, "backtest", "races")
    parts = [t, r]
    if (OUT / "backtest_house.csv").exists():
        hb = pd.read_csv(OUT / "backtest_house.csv").drop(columns="forecast_configuration", errors="ignore")
        hb["variant"] = hb["variant"].str.replace(" ", "_")
        hb = hb.melt(["year", "variant", "trained_on"], var_name="metric")
        hb.insert(0, "backtest", "house")
        parts.append(hb)
    out = pd.concat(parts, ignore_index=True)
    out["value"] = out["value"].astype(float).round(SHARE_DP + 2)
    return out[["backtest", "year", "variant", "trained_on", "metric", "value"]]


# --------------------------------------------------------------------------- manifest
def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
        return r.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _mtime(path: Path) -> str:
    return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def house_page_date() -> str | None:
    """Fetch date of the saved 2026 Wikipedia House page the model used (the newest copy)."""
    dates = [m.group(1) for p in RAW_HOUSE.glob(f"wiki_house_{FORECAST_YEAR}_*.html")
             if (m := re.search(r"_(\d{4}-\d{2}-\d{2})\.html$", p.name))]
    return max(dates) if dates else None


def latest_poll_end() -> str | None:
    """Latest end date among the 2026 race polls behind the averages."""
    p = pd.read_parquet(OUT / "polls.parquet", columns=["year", "end"])
    p = p[p["year"] == FORECAST_YEAR]["end"].dropna()
    return None if p.empty else str(p.max().date())


def manifest(version: str, draft: bool, files: list[Path]) -> dict:
    from . import house, turnout_model, vote_model       # for the simulation counts

    status = _git("status", "--porcelain")
    pages = [RAW / "races" / f"{FORECAST_YEAR}_United_States_{k}_elections.html"
             for k in ("Senate", "gubernatorial")]
    ev = pd.read_csv(OUT / "turnout_2026_early_vote.csv")
    return {
        "version": version,
        "draft": draft,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_working_tree_clean": None if status is None else status == "",
        "inputs": {
            "races_wikipedia_modified_utc": max(_mtime(p) for p in pages),
            "house_wikipedia_fetched": house_page_date(),
            "latest_poll_end_date": latest_poll_end(),
            "generic_ballot_as_of": national()["generic_ballot_as_of"].iloc[0],
            "early_vote_applied": bool(ev["applied"].iloc[0]) if "applied" in ev else False,
        },
        "simulations": {"turnout": turnout_model.SIMS, "vote": vote_model.SIMS, "house": house.SIMS},
        "sha256": {p.name: sha256(p) for p in files},
    }


# --------------------------------------------------------------------------- release
TABLES = {"turnout_counties.csv": turnout_counties, "turnout_states.csv": turnout_states,
          "national.csv": national, "races.csv": races, "senate_seats.csv": senate_seats,
          "house_districts.csv": house_districts, "house_seats.csv": house_seats,
          "backtests.csv": backtests}


def release(version: str, draft: bool = False, root: Path | None = None) -> Path:
    """Write the release tables and manifest; returns the folder."""
    root = Path(root) if root is not None else ROOT / "forecasts"
    folder = root / ("_draft" if draft else "") / version
    if folder.exists() and any(folder.iterdir()) and not draft:
        raise SystemExit(f"{folder} already has files; a published release is not overwritten")
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for name, build in TABLES.items():
        path = folder / name
        build().to_csv(path, index=False)
        files.append(path)
    m = manifest(version, draft, files)
    (folder / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
    return folder


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Write a forecast release from the processed outputs.")
    ap.add_argument("version", help="folder name, e.g. v1 or final")
    ap.add_argument("--draft", action="store_true", help="write to forecasts/_draft/<version>/ (git ignores it)")
    ap.add_argument("--root", type=Path, help="forecasts folder to write into (default: the repo's)")
    a = ap.parse_args(argv)
    folder = release(a.version, a.draft, a.root)
    for p in sorted(folder.iterdir()):
        print(f"{p.name:24s}{len(p.read_text().splitlines()) - 1 if p.suffix == '.csv' else '':>6}")
    print("wrote", folder)


if __name__ == "__main__":
    main()

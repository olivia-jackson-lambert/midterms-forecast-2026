"""Download and tidy the public inputs into county-level tables.

Everything is cached under data/raw/ (never committed). Outputs go to data/processed/.

    python -m forecast.ingest            # from the src/ directory
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
RAW.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

DATAVERSE = "https://dataverse.harvard.edu/api"
UA = {"User-Agent": "midterms-2026 research (personal, non-commercial)"}


# --------------------------------------------------------------------------- downloads
def dataverse_file(doi: str, filename: str) -> Path:
    """Fetch one file from a Harvard Dataverse dataset (original format), with caching."""
    dest = RAW / filename
    if dest.exists():
        return dest
    meta = requests.get(f"{DATAVERSE}/datasets/:persistentId/",
                        params={"persistentId": f"doi:{doi}"}, headers=UA, timeout=60).json()
    files = {f["dataFile"]["filename"]: f["dataFile"]["id"] for f in meta["data"]["latestVersion"]["files"]}
    if filename not in files:
        raise KeyError(f"{filename} not in {doi}: {sorted(files)}")
    url = f"{DATAVERSE}/access/datafile/{files[filename]}"
    r = requests.get(url, params={"format": "original"}, headers=UA, timeout=300)
    if r.status_code == 400:            # not an ingested tabular file: fetch it as stored
        r = requests.get(url, headers=UA, timeout=300)
    if r.status_code == 400 and "Guestbook" in r.text:
        raise SystemExit(
            f"\n{filename} needs MIT Election Lab's download form (a short guestbook).\n"
            f"Download it once from https://doi.org/{doi} and save it as:\n  {dest}\n"
            "then run this script again.")
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


# --------------------------------------------------------------------------- presidential results
def county_presidential() -> pd.DataFrame:
    """One row per county-year: total ballots and two-party Democratic share, 2000-2024.

    MIT's file reports some states by voting mode (election day, early, absentee...) and
    others as a single TOTAL row, and a few do both. Use TOTAL where it exists, otherwise
    sum the modes, so nothing is double counted.
    """
    path = dataverse_file("10.7910/DVN/VOQCHQ", "countypres_2000-2024.tab")
    df = pd.read_csv(path, sep="\t", dtype={"county_fips": str}, low_memory=False)
    df = df[df["county_fips"].notna() & (df["county_fips"] != "NA")].copy()
    df["county_fips"] = df["county_fips"].str.replace(r"\.0$", "", regex=True).str.zfill(5)
    df["mode"] = df["mode"].fillna("TOTAL").str.upper()

    has_total = df.groupby(["year", "county_fips"])["mode"].transform(lambda m: (m == "TOTAL").any())
    df = df[(df["mode"] == "TOTAL") | ~has_total]

    party = df["party"].str.upper()
    votes = (df.assign(dem=np.where(party == "DEMOCRAT", df["candidatevotes"], 0),
                       rep=np.where(party == "REPUBLICAN", df["candidatevotes"], 0))
               .groupby(["year", "state_po", "county_fips", "county_name"], as_index=False)
               .agg(dem=("dem", "sum"), rep=("rep", "sum"), total=("candidatevotes", "sum")))
    votes["dem_2p"] = votes["dem"] / (votes["dem"] + votes["rep"])
    return votes


# --------------------------------------------------------------------------- census
ACS_VARS = {
    "B01003_001E": "population",
    "B29001_001E": "cvap",                  # citizen voting-age population
    "B01002_001E": "median_age",
    "B19013_001E": "median_income",
    "B03002_001E": "race_total",
    "B03002_003E": "white_nh",
    "B15003_001E": "edu_total",
    "B15003_022E": "edu_ba", "B15003_023E": "edu_ma", "B15003_024E": "edu_prof", "B15003_025E": "edu_phd",
}


def acs_county(year: int = 2023) -> pd.DataFrame:
    """County demographics from the ACS 5-year API (no key needed at this volume)."""
    cache = RAW / f"acs5_{year}_county.json"
    if not cache.exists():
        key = os.environ.get("CENSUS_API_KEY")
        if not key:
            raise SystemExit("\nThe Census API needs a free key: sign up at "
                             "https://api.census.gov/data/key_signup.html, then run\n"
                             "  export CENSUS_API_KEY=<your key>\nbefore this script.")
        r = requests.get(f"https://api.census.gov/data/{year}/acs/acs5",
                         params={"get": "NAME," + ",".join(ACS_VARS), "for": "county:*", "key": key},
                         headers=UA, timeout=120, allow_redirects=False)
        if r.status_code in (301, 302):
            raise SystemExit("The Census API rejected the key (redirected to its key page). Check CENSUS_API_KEY.")
        r.raise_for_status()
        cache.write_text(r.text)
    rows = json.loads(cache.read_text())
    df = pd.DataFrame(rows[1:], columns=rows[0]).rename(columns=ACS_VARS)
    for c in ACS_VARS.values():
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["county_fips"] = df["state"] + df["county"]
    df["share_white_nh"] = df["white_nh"] / df["race_total"]
    df["share_ba_plus"] = df[["edu_ba", "edu_ma", "edu_prof", "edu_phd"]].sum(axis=1) / df["edu_total"]
    df.loc[df["median_income"] < 0, "median_income"] = np.nan   # Census uses negative sentinels
    return df[["county_fips", "NAME", "population", "cvap", "median_age", "median_income",
               "share_white_nh", "share_ba_plus"]]


# --------------------------------------------------------------------------- checks
# Certified national totals (millions of ballots for president) used as a sanity check.
NATIONAL_TOTAL_M = {2000: 105.4, 2004: 122.3, 2008: 131.5, 2012: 129.1, 2016: 136.7, 2020: 158.4, 2024: 155.2}


def check_presidential(votes: pd.DataFrame) -> pd.DataFrame:
    by_year = votes.groupby("year")["total"].sum().div(1e6).round(1)
    report = pd.DataFrame({"county_file_m": by_year, "certified_m": pd.Series(NATIONAL_TOTAL_M)})
    report["diff_pct"] = (report["county_file_m"] / report["certified_m"] - 1).mul(100).round(2)
    return report


def main() -> None:
    acs = acs_county(2023)
    acs.to_parquet(OUT / "acs_county_2023.parquet", index=False)
    print("ACS counties:", len(acs), "| total CVAP (M):", round(acs["cvap"].sum() / 1e6, 1))

    pres = county_presidential()
    pres.to_parquet(OUT / "county_presidential.parquet", index=False)

    print("presidential rows:", len(pres), "| counties per year:",
          pres.groupby("year")["county_fips"].nunique().to_dict())
    print(check_presidential(pres).to_string())
    unmatched = set(pres.loc[pres.year == 2024, "county_fips"]) - set(acs["county_fips"])
    print("2024 county FIPS with no ACS match:", len(unmatched), sorted(unmatched)[:12])


if __name__ == "__main__":
    main()

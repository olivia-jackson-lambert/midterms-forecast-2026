"""Download and tidy the public inputs into a county panel.

No API keys and no download forms: every source is a plain public file.

- Presidential results 2008-2016: MIT Election Lab's official county returns on GitHub
  (MEDSL/county-returns). 2020 and 2024: the tonmcg county mirror on GitHub (its 2012 and
  2016 files undercount CA, NY and RI, so it is only used for 2020 and 2024).
- Citizen voting-age population: the Census CVAP special tabulation, one 5-year vintage
  per election year.
- Demographics: ACS 5-year table-based summary files. Land area: Census Gazetteer.

Everything is cached under data/raw/ (never committed). Outputs go to data/processed/.

    python -m forecast.ingest            # from the src/ directory
"""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
# Data can live outside the repo (set TURNOUT_DATA), e.g. when the repo is in an iCloud folder
# that evicts large files.
DATA = Path(os.environ.get("TURNOUT_DATA", ROOT / "data"))
RAW = DATA / "raw"
OUT = DATA / "processed"
RAW.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "turnout-first-2026 research (personal, non-commercial)"}
YEARS = [2008, 2012, 2016, 2020, 2024]

MEDSL_PRES = "https://raw.githubusercontent.com/MEDSL/county-returns/master/countypres_2000-2016.csv"
MIRROR_PRES = ("https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/"
               "master/{year}_US_County_Level_Presidential_Results.csv")
CVAP_ZIP = ("https://www2.census.gov/programs-surveys/decennial/rdo/datasets/{v}/{v}-cvap/"
            "CVAP_{s}-{v}_ACS_csv_files.zip")
ACS_TABLE = ("https://www2.census.gov/programs-surveys/acs/summary_file/{v}/table-based-SF/"
             "data/5YRData/acsdt5y{v}-{t}.dat")
GAZETTEER = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{v}_Gazetteer/"
             "{v}_Gaz_counties_national.zip")


# --------------------------------------------------------------------------- downloads
def fetch(url: str, dest: Path) -> Path:
    """Download url to dest once; later calls use the cached copy."""
    if dest.exists():
        return dest
    with requests.get(url, headers=UA, timeout=600, stream=True) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.rename(dest)
    return dest


# --------------------------------------------------------------------------- geography
# Some places report results on geographies that don't match Census counties, so the panel
# uses "county units": Census counties, with a few merged so results and population line up.
#   Alaska: results by state house district, Census by borough -> one statewide unit.
#   Connecticut: old counties until 2020, planning regions from 2022 -> one statewide unit.
#   Kansas City, MO reports separately (MIT codes it 36000, EAVS 29380) and the 2020-24 mirror
#     folds it into Jackson County, so Jackson, Clay and Platte (the counties it spans) form one unit.
#   Washington DC: the 2024 mirror reports it by ward -> one unit.
#   Renamed or merged counties: Shannon SD -> Oglala Lakota, Bedford city VA -> Bedford
#     County, Kalawao HI (no separate results) -> Maui.
UNIT_REMAP = {"46113": "46102", "51515": "51019", "15005": "15009",
              "36000": "29095", "29380": "29095", "29047": "29095", "29165": "29095"}


def to_unit(fips: pd.Series) -> pd.Series:
    fips = fips.astype(str).str.zfill(5)
    st = fips.str[:2]
    fips = fips.replace(UNIT_REMAP)
    return fips.mask(st == "02", "02000").mask(st == "09", "09000").mask(st == "11", "11001")


# --------------------------------------------------------------------------- presidential results
# Alaska Division of Elections, official Election Summary Reports (20GENR, 24GENR).
AK_CERTIFIED = {2020: {"dem": 153_778, "rep": 189_951, "total": 359_530},
                2024: {"dem": 140_026, "rep": 184_458, "total": 338_177}}


def county_presidential() -> pd.DataFrame:
    """One row per county unit and year: Democratic, Republican and total presidential votes.

    Totals are the sum of candidate votes. MIT's totalvotes column is wrong in places
    (Fairfax city VA carries Fairfax County's total), and the candidate sums match the
    certified national totals.
    """
    m = pd.read_csv(fetch(MEDSL_PRES, RAW / "countypres_2000-2016.csv"))
    m = m[m["year"].isin(YEARS) & m["FIPS"].notna()].copy()
    m["county_fips"] = m["FIPS"].astype(int).astype(str).str.zfill(5)
    party = m["party"].fillna("").str.lower()
    m["dem"] = np.where(party == "democrat", m["candidatevotes"], 0)
    m["rep"] = np.where(party == "republican", m["candidatevotes"], 0)
    old = m.rename(columns={"candidatevotes": "total"})[["year", "state_po", "county_fips", "dem", "rep", "total"]]

    new = []
    for year in (2020, 2024):
        d = pd.read_csv(fetch(MIRROR_PRES.format(year=year), RAW / f"pres_mirror_{year}.csv"),
                        dtype={"county_fips": str})
        new.append(pd.DataFrame({"year": year, "state_name": d["state_name"], "county_fips": d["county_fips"],
                                 "dem": d["votes_dem"], "rep": d["votes_gop"], "total": d["total_votes"]}))
    new = pd.concat(new)
    # Map by state name, not FIPS prefix: MIT codes Kansas City as "36000", which is New York's prefix.
    states = m.drop_duplicates("state").set_index("state")["state_po"]
    new["state_po"] = new.pop("state_name").map(states)

    # The mirror's Alaska rows are wrong (2020 total about 9% high, 2024 two-party only);
    # use the certified statewide figures instead.
    new = new[new["state_po"] != "AK"]
    ak = pd.DataFrame([{"year": y, "state_po": "AK", "county_fips": "02000", **v} for y, v in AK_CERTIFIED.items()])

    df = pd.concat([old, new, ak], ignore_index=True)
    df["unit_fips"] = to_unit(df["county_fips"])
    votes = df.groupby(["year", "state_po", "unit_fips"], as_index=False)[["dem", "rep", "total"]].sum()
    votes["dem_2p"] = votes["dem"] / (votes["dem"] + votes["rep"])
    return votes


# --------------------------------------------------------------------------- census
def cvap_vintage(year: int) -> int:
    """CVAP 5-year vintage used as the denominator for an election year.

    The 5-year window centred on the election (ending two years later), capped at the
    latest release. For backtests, features must instead use a vintage published before
    1 October of the election year; that is handled in the feature step, not here.
    """
    return min(year + 2, 2024)


def cvap_county(vintage: int) -> pd.DataFrame:
    """Citizen voting-age population by county from the CVAP special tabulation."""
    cache = RAW / f"cvap_county_{vintage}.csv"
    if not cache.exists():
        url = CVAP_ZIP.format(v=vintage, s=vintage - 4)
        r = requests.get(url, headers=UA, timeout=600)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            name = next(n for n in z.namelist() if n.lower().endswith("county.csv"))
            cache.write_bytes(z.read(name))
    df = pd.read_csv(cache, encoding="latin-1", dtype=str)
    df.columns = df.columns.str.lower()
    df = df[df["lntitle"] == "Total"]
    return pd.DataFrame({"county_fips": df["geoid"].str[-5:],
                         "cvap": pd.to_numeric(df["cvap_est"]),
                         "cvap_moe": pd.to_numeric(df["cvap_moe"], errors="coerce")})


ACS_TABLES = {
    "b01003": {"B01003_E001": "population"},
    "b01002": {"B01002_E001": "median_age"},
    "b19013": {"B19013_E001": "median_income"},
    "b03002": {"B03002_E001": "race_total", "B03002_E003": "white_nh", "B03002_E004": "black_nh",
               "B03002_E012": "hispanic"},
    "b15003": {"B15003_E001": "edu_total", "B15003_E022": "edu_ba", "B15003_E023": "edu_ma",
               "B15003_E024": "edu_prof", "B15003_E025": "edu_phd"},
    "b01001": {**{f"B01001_E{i:03d}": f"age_18_29_{i}" for i in [*range(7, 12), *range(31, 36)]},
               **{f"B01001_E{i:03d}": f"age_65p_{i}" for i in [*range(20, 26), *range(44, 50)]}},
}


def acs_table(table: str, vintage: int) -> pd.DataFrame:
    """County rows of one ACS 5-year summary-file table (cached after the first download)."""
    cache = RAW / f"acs5_{vintage}_{table}_county.csv"
    if not cache.exists():
        lines = []
        with requests.get(ACS_TABLE.format(v=vintage, t=table), headers=UA, timeout=600, stream=True) as r:
            r.raise_for_status()
            for i, line in enumerate(r.iter_lines()):
                if i == 0 or line.startswith(b"0500000US"):
                    lines.append(line.decode("latin-1"))
        cache.write_text("\n".join(lines))
    df = pd.read_csv(cache, sep="|", dtype={"GEO_ID": str})
    cols = ACS_TABLES[table]
    df = df[["GEO_ID", *cols]].rename(columns=cols)
    df.insert(0, "county_fips", df.pop("GEO_ID").str[-5:])
    return df


def land_area(vintage: int = 2024) -> pd.DataFrame:
    path = fetch(GAZETTEER.format(v=vintage), RAW / f"gazetteer_counties_{vintage}.zip")
    df = pd.read_csv(path, sep="\t", dtype={"GEOID": str}, compression="zip")
    df.columns = df.columns.str.strip()
    return pd.DataFrame({"county_fips": df["GEOID"], "land_sqmi": df["ALAND_SQMI"]})


def acs_county(vintage: int = 2024) -> pd.DataFrame:
    """County demographics from the ACS 5-year summary files, with land area."""
    df = acs_table("b01003", vintage)
    for t in ACS_TABLES:
        if t != "b01003":
            df = df.merge(acs_table(t, vintage), on="county_fips", how="left")
    df = df.merge(land_area(), on="county_fips", how="left")
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.loc[df["median_income"] < 0, "median_income"] = np.nan   # Census uses negative sentinels
    df.loc[df["median_age"] < 0, "median_age"] = np.nan
    df["age_18_29"] = df.filter(like="age_18_29_").sum(axis=1)
    df["age_65p"] = df.filter(like="age_65p_").sum(axis=1)
    df["edu_ba_plus"] = df[["edu_ba", "edu_ma", "edu_prof", "edu_phd"]].sum(axis=1)
    return df[["county_fips", "population", "median_age", "median_income", "race_total", "white_nh",
               "black_nh", "hispanic", "edu_total", "edu_ba_plus", "age_18_29", "age_65p", "land_sqmi"]]


def acs_units(acs: pd.DataFrame) -> pd.DataFrame:
    """Aggregate county demographics to county units. Counts are summed; medians of merged
    units are population-weighted means of the county medians (an approximation)."""
    acs = acs.assign(unit_fips=to_unit(acs["county_fips"]))
    counts = ["population", "race_total", "white_nh", "black_nh", "hispanic", "edu_total", "edu_ba_plus",
              "age_18_29", "age_65p", "land_sqmi"]
    u = acs.groupby("unit_fips")[counts].sum()
    for med in ("median_age", "median_income"):
        ok = acs[med].notna()
        w = acs[ok].assign(wx=acs[med] * acs["population"])
        u[med] = w.groupby("unit_fips")["wx"].sum() / w.groupby("unit_fips")["population"].sum()
    return pd.DataFrame({
        "unit_fips": u.index,
        "population": u["population"].values,
        "median_age": u["median_age"].values,
        "median_income": u["median_income"].values,
        "share_white_nh": (u["white_nh"] / u["race_total"]).values,
        "share_black_nh": (u["black_nh"] / u["race_total"]).values,
        "share_hispanic": (u["hispanic"] / u["race_total"]).values,
        "share_ba_plus": (u["edu_ba_plus"] / u["edu_total"]).values,
        "share_18_29": (u["age_18_29"] / u["population"]).values,
        "share_65p": (u["age_65p"] / u["population"]).values,
        "log_density": np.log((u["population"] / u["land_sqmi"]).clip(lower=0.1)).values,
    })


# --------------------------------------------------------------------------- panel
def county_panel(pres: pd.DataFrame, acs: pd.DataFrame) -> pd.DataFrame:
    """County unit x presidential year: votes, CVAP, turnout (ballots for president / CVAP)
    and the latest ACS demographics."""
    parts = []
    for year in YEARS:
        v = cvap_vintage(year)
        c = cvap_county(v).assign(unit_fips=lambda x: to_unit(x["county_fips"]))
        c = c.groupby("unit_fips", as_index=False)["cvap"].sum()
        p = pres[pres["year"] == year].merge(c, on="unit_fips", how="left").assign(cvap_vintage=v)
        parts.append(p)
    panel = pd.concat(parts, ignore_index=True)
    panel["turnout"] = panel["total"] / panel["cvap"]
    return panel.merge(acs_units(acs), on="unit_fips", how="left")


# --------------------------------------------------------------------------- checks
# Certified national totals (millions of ballots for president) used as a sanity check.
NATIONAL_TOTAL_M = {2008: 131.5, 2012: 129.1, 2016: 136.7, 2020: 158.4, 2024: 155.2}


def check_presidential(votes: pd.DataFrame) -> pd.DataFrame:
    by_year = votes.groupby("year")["total"].sum().div(1e6).round(1)
    report = pd.DataFrame({"county_file_m": by_year, "certified_m": pd.Series(NATIONAL_TOTAL_M)})
    report["diff_pct"] = (report["county_file_m"] / report["certified_m"] - 1).mul(100).round(2)
    return report


def main() -> None:
    acs = acs_county(2024)
    acs.to_parquet(OUT / "acs_county_2024.parquet", index=False)
    print("ACS counties:", len(acs), "| population (M):", round(acs["population"].sum() / 1e6, 1))

    pres = county_presidential()
    panel = county_panel(pres, acs)
    panel.to_parquet(OUT / "county_panel.parquet", index=False)

    print("panel rows:", len(panel), "| units per year:", panel.groupby("year")["unit_fips"].nunique().to_dict())
    print(check_presidential(pres).to_string())
    print(panel.groupby("year").apply(lambda d: d["total"].sum() / d["cvap"].sum(), include_groups=False)
               .round(3).rename("national turnout (share of CVAP)").to_string())
    missing = panel[panel["cvap"].isna() | panel["population"].isna()]
    print("units missing CVAP or ACS:", len(missing), missing[["year", "unit_fips"]].values.tolist()[:12])


if __name__ == "__main__":
    main()

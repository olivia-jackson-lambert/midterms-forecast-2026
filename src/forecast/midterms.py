"""County midterm turnout for 2014, 2018 and 2022, and county Senate and governor results
for 2018 and 2022.

Sources (all public, no forms):
- Ballots cast: the EAC's Election Administration and Voting Survey (EAVS), question F1a
  (total who participated), reported by local election jurisdiction.
- Results: MIT Election Lab precinct returns on GitHub (2018-elections-official and
  2022-elections-official), aggregated to county.
- State check: UF Election Lab (Michael McDonald) total ballots counted, 1980-2022, CC BY 4.0.

Turnout numerator: EAVS ballots cast. Where a county's EAVS figure is missing or implausible,
the highest-office vote from MIT (the most votes cast in any statewide race or the sum of
House races in the county) is scaled up by that state's ratio of ballots to highest-office
votes.

    python -m forecast.midterms          # from the src/ directory, after forecast.ingest
"""
from __future__ import annotations

import zipfile

import numpy as np
import pandas as pd

from .ingest import OUT, RAW, cvap_county, fetch, to_unit

MIDTERMS = [2014, 2018, 2022]
EAC = "https://www.eac.gov/sites/default/files"
EAVS = {
    2014: (f"{EAC}/eac_assets/1/1/2014_EAVS_Excel_Files1.zip", "eavs2014.zip"),
    2018: (f"{EAC}/2019-10/EAVS_2018_for_Public_Release_nolabel%20v1.1.csv", "eavs2018.csv"),
    2022: (f"{EAC}/2023-06/2022_EAVS_for_Public_Release_nolabel_V1_CSV.zip", "eavs2022.zip"),
}
# Illinois city election authorities carry place codes in EAVS; map them to their county.
# (Maine's unorganised townships and statewide overseas ballots, a few hundred votes, are dropped.)
EAVS_CITIES = {"17030": "17089", "17066": "17113", "17140": "17031", "17222": "17163",
               "17283": "17095", "17590": "17143", "17650": "17201"}
UF_TURNOUT = "https://election.lab.ufl.edu/data-downloads/turnoutdata/Turnout_1980_2022_v1.2.csv"
MEDSL_2018 = "https://github.com/MEDSL/2018-elections-official/raw/master/{o}/{o}_precinct_general.zip"
MEDSL_2018_STATE = ("https://github.com/MEDSL/2018-elections-official/raw/master/individual_states/"
                    "2018-{s}-precinct-general.zip")
# Races missing from MIT's national 2018 files but present in its per-state files.
SUPPLEMENT_2018 = {"in": ["US SENATE", "US HOUSE"]}
MEDSL_2022 = ("https://github.com/MEDSL/2022-elections-official/raw/main/individual_states/"
              "2022-{s}-local-precinct-general.zip")
STATES = ("ak al ar az ca co ct dc de fl ga hi ia id il in ks ky la ma md me mi mn mo ms mt nc nd ne nh nj "
          "nm nv ny oh ok or pa ri sc sd tn tx ut va vt wa wi wv wy").split()

OFFICES = {"US SENATE": "SEN", "GOVERNOR": "GOV", "US HOUSE": "HOUSE"}
OFFICE_ALIASES = {"GOVERNOR/LIEUTENANT GOVERNOR": "GOVERNOR"}      # Iowa 2018
NOT_VOTES = {"UNDERVOTES", "OVERVOTES", "UNDER VOTES", "OVER VOTES", "UNDER/OVER VOTES", "BLANK/VOID",
             "BLANK", "TIMES BLANK VOTED", "TOTAL", "TOTAL VOTES", "BALLOTS CAST", "REGISTERED VOTERS"}
COLS = ["state_po", "county_fips", "precinct", "office", "district", "special", "stage", "mode", "candidate",
        "party_simplified", "votes"]


# --------------------------------------------------------------------------- ballots cast (EAVS)
def eavs_ballots(year: int) -> pd.DataFrame:
    """EAVS total ballots cast (F1a), summed from jurisdictions to counties.

    EAVS uses 10-digit FIPS for townships in New England, Michigan and Wisconsin; the first
    five digits are the county. Negative values are EAVS missing-data codes.
    """
    url, name = EAVS[year]
    (RAW / "eavs").mkdir(exist_ok=True)
    path = fetch(url, RAW / "eavs" / name)
    if year == 2014:
        with zipfile.ZipFile(path) as z:
            df = pd.read_excel(z.open("EAVS_Section_F.xlsx"), dtype={"FIPSCode": str})
        df = df.rename(columns={"QF1a": "F1a", "State": "State_Abbr"})
    else:
        df = pd.read_csv(path, usecols=["FIPSCode", "State_Abbr", "F1a"], dtype={"FIPSCode": str})
    df["F1a"] = pd.to_numeric(df["F1a"], errors="coerce")
    df["county_fips"] = df["FIPSCode"].str.zfill(10).str[:5].replace(EAVS_CITIES)
    df["missing"] = df["F1a"].isna() | (df["F1a"] < 0)
    out = df.groupby(["State_Abbr", "county_fips"], as_index=False).agg(
        ballots=("F1a", lambda v: v[v >= 0].sum()), any_missing=("missing", "any"))
    return out.rename(columns={"State_Abbr": "state_po"})


# --------------------------------------------------------------------------- results (MIT precincts)
def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """General-election rows for Senate, governor and House, each vote counted once."""
    df = df.assign(office=df["office"].str.upper().str.strip().replace(OFFICE_ALIASES))
    df = df[df["office"].isin(OFFICES) & df["stage"].eq("GEN") & df["state_po"].ne("DC")].copy()
    # Some files drop the leading zero from FIPS; Alaska has no county codes (one unit anyway).
    df["county_fips"] = df["county_fips"].str.replace(r"\.0$", "", regex=True).str.zfill(5)
    df.loc[df["state_po"].eq("AK"), "county_fips"] = "02000"
    df = df[~df["candidate"].astype(str).str.upper().str.strip().isin(NOT_VOTES)]
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0)
    # Some states report vote modes and a TOTAL row for the same precinct: keep TOTAL there.
    key = ["county_fips", "precinct", "office", "district"]
    has_total = df.groupby(key, dropna=False)["mode"].transform(lambda m: m.eq("TOTAL").any())
    df = df[df["mode"].eq("TOTAL") | ~has_total]
    # Some files add county or district total rows as if they were precincts ("COUNTY TOTAL",
    # "Burlington Totals"). Drop them where they duplicate the precinct rows; some states name
    # real precincts "... TOTAL", and those don't match the other rows' sum, so they stay.
    is_sum = df["precinct"].astype(str).str.contains(r"\btotals?\b", case=False, regex=True)
    k = ["county_fips", "office", "district", "candidate"]
    a = df[~is_sum].groupby(k, dropna=False)["votes"].sum()
    b = df[is_sum].groupby(k, dropna=False)["votes"].sum()
    dup = b[(a.reindex(b.index) - b).abs() <= 0.05 * b.clip(lower=1)].index
    drop = is_sum & df.set_index(k).index.isin(dup)
    return df[~drop]


def _read(path, chunks: bool = False) -> pd.DataFrame:
    kw = dict(usecols=COLS, dtype={"county_fips": str, "district": str, "precinct": str, "candidate": str,
                                  "special": str, "mode": str}, low_memory=False)
    with zipfile.ZipFile(path) as z:      # some zips also hold macOS __MACOSX metadata files
        name = next(n for n in z.namelist() if n.endswith(".csv") and not n.startswith("__MACOSX"))
        with z.open(name) as f:
            if not chunks:
                return _clean(pd.read_csv(f, **kw))
            parts = [c[c["office"].str.upper().str.strip().replace(OFFICE_ALIASES).isin(OFFICES)]
                     for c in pd.read_csv(f, chunksize=2_000_000, **kw)]
    return _clean(pd.concat(parts))


def precinct_results(year: int) -> pd.DataFrame:
    cache = RAW / "medsl" / f"results_{year}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    (RAW / "medsl").mkdir(exist_ok=True)
    if year == 2018:
        parts = [_read(fetch(MEDSL_2018.format(o=o), RAW / "medsl" / f"2018_{o}.zip"), chunks=o == "STATE")
                 for o in ("SENATE", "HOUSE", "STATE")]
        for s, offices in SUPPLEMENT_2018.items():
            d = _read(fetch(MEDSL_2018_STATE.format(s=s), RAW / "medsl" / f"2018_state_{s}.zip"))
            parts.append(d[d["office"].isin(offices)])
    else:
        parts = [_read(fetch(MEDSL_2022.format(s=s), RAW / "medsl" / f"2022_{s}.zip")) for s in STATES]
    df = pd.concat(parts, ignore_index=True)
    df.to_parquet(cache, index=False)
    return df


def county_results(year: int) -> pd.DataFrame:
    """County votes by race: office (SEN, GOV, HOUSE), special flag, Democratic, Republican, total.
    House is summed over all districts in the county."""
    df = precinct_results(year)
    df = df[df["county_fips"].str.len() == 5]
    df["race"] = df["office"].map(OFFICES)
    df["special"] = df["special"].astype(str).str.upper().eq("TRUE") & df["race"].eq("SEN")
    party = df["party_simplified"].fillna("")
    df["dem"] = np.where(party == "DEMOCRAT", df["votes"], 0)
    df["rep"] = np.where(party == "REPUBLICAN", df["votes"], 0)
    out = df.groupby(["state_po", "county_fips", "race", "special"], as_index=False)[["dem", "rep", "votes"]].sum()
    return out.rename(columns={"votes": "total"}).assign(year=year)


def highest_office(results: pd.DataFrame) -> pd.DataFrame:
    """Most votes cast in any one race type in each county."""
    return (results.groupby(["state_po", "county_fips"], as_index=False)["total"].max()
                   .rename(columns={"total": "highest_office"}))


# --------------------------------------------------------------------------- turnout
def uf_state_ballots() -> pd.DataFrame:
    df = pd.read_csv(fetch(UF_TURNOUT, RAW / "turnout_1980_2022.csv"), dtype=str)
    num = lambda s: pd.to_numeric(s.str.replace(",", "").str.rstrip("%"), errors="coerce")
    return pd.DataFrame({"year": num(df["YEAR"]).astype(int), "state_po": df["STATE_ABV"],
                         "uf_ballots": num(df["TOTAL_BALLOTS_COUNTED"]), "vep": num(df["VEP"]),
                         "vep_turnout": num(df["VEP_TURNOUT_RATE"]) / 100})


def county_midterm_turnout(year: int) -> pd.DataFrame:
    """Ballots cast per county unit, reconciled to UF's certified state totals.

    Three estimates per county:
      E  EAVS ballots cast;
      H  MIT highest-office vote times the state's ballots-to-highest-office ratio (2018, 2022);
      P  last presidential vote times the state's certified midterm-to-presidential ratio.
    P is crude but always available and hard to get badly wrong, so it is the referee: use E if
    it is within a factor of 1.6 of P (and, where MIT results exist, between 97% and 125% of the
    raw highest-office vote); otherwise H if it is within 1.6 of P; otherwise P ("imputed").
    Each state is then scaled to UF's total ballots counted. Imputed rows are fine as backtest
    anchors but are excluded from model training.
    """
    eavs = eavs_ballots(year)
    if year == 2014:
        df = eavs.assign(highest_office=0.0)
    else:
        df = eavs.merge(highest_office(county_results(year)), on=["state_po", "county_fips"], how="outer")
    df["unit_fips"] = to_unit(df["county_fips"])
    u = df.groupby("unit_fips", as_index=False).agg(eavs=("ballots", "sum"), highest_office=("highest_office", "sum"))

    # Frame: every county unit, with its state and last presidential vote.
    pres = pd.read_parquet(OUT / "county_panel.parquet", columns=["year", "state_po", "unit_fips", "total"])
    pres = pres[pres["year"] == year - 2].rename(columns={"total": "pres_votes"}).drop(columns="year")
    unmatched = sorted(set(u["unit_fips"]) - set(pres["unit_fips"]))
    if unmatched:
        print(f"{year}: jurisdictions with no county unit (dropped):", unmatched[:20])
    u = pres.merge(u, on="unit_fips", how="left").fillna({"eavs": 0, "highest_office": 0})

    uf = uf_state_ballots().query("year == @year").set_index("state_po")["uf_ballots"]
    P = u["pres_votes"] * u["state_po"].map(uf / u.groupby("state_po")["pres_votes"].sum())
    near = lambda x: (x / P).between(1 / 1.6, 1.6)
    ho = u["highest_office"].replace(0, np.nan)
    # Where EAVS matches the certified state total but MIT is far from it (a double-counted
    # file, say), don't use MIT. (Wisconsin's 2018 and 2022 EAVS rows have municipal codes with
    # no county, so they never match a county unit and MIT is used there.)
    st = u.groupby("state_po")[["eavs", "highest_office"]].sum().assign(uf=uf)
    bad = st.index[(st["eavs"] / st["uf"]).between(0.97, 1.03)
                   & ~(st["eavs"] / st["highest_office"]).between(0.97, 1.25)]
    ho = ho.mask(u["state_po"].isin(bad))
    e_ok = near(u["eavs"]) & ((u["eavs"] / ho).between(0.97, 1.25) | ho.isna())
    both = u[e_ok & ho.notna()].groupby("state_po")[["eavs", "highest_office"]].sum()
    ratio = both["eavs"] / both["highest_office"]
    H = ho * u["state_po"].map(ratio).fillna(1.02)
    h_ok = ~e_ok & H.notna() & near(H)

    u["source"] = np.select([e_ok, h_ok], ["eavs", "highest_office"], "imputed")
    u["ballots"] = np.select([e_ok, h_ok], [u["eavs"], H], P)
    u["ballots"] *= u["state_po"].map(uf / u.groupby("state_po")["ballots"].sum())
    return u[["state_po", "unit_fips", "ballots", "source", "eavs", "highest_office", "pres_votes"]].assign(year=year)


def cvap_vintage_midterm(year: int) -> int:
    return min(year + 2, 2024)


def midterm_panel() -> pd.DataFrame:
    parts = []
    for year in MIDTERMS:
        t = county_midterm_turnout(year)
        c = cvap_county(cvap_vintage_midterm(year)).assign(unit_fips=lambda x: to_unit(x["county_fips"]))
        c = c.groupby("unit_fips", as_index=False)["cvap"].sum()
        parts.append(t.merge(c, on="unit_fips", how="left"))
    panel = pd.concat(parts, ignore_index=True)
    panel["turnout"] = panel["ballots"] / panel["cvap"]
    return panel


def check_states(panel: pd.DataFrame) -> pd.DataFrame:
    s = panel.groupby(["year", "state_po"], as_index=False)["ballots"].sum()
    s = s.merge(uf_state_ballots(), on=["year", "state_po"], how="left")
    s["diff_pct"] = (s["ballots"] / s["uf_ballots"] - 1) * 100
    return s


def main() -> None:
    panel = midterm_panel()
    panel.to_parquet(OUT / "county_midterm_turnout.parquet", index=False)
    results = pd.concat([county_results(y) for y in (2018, 2022)], ignore_index=True)
    results.to_parquet(OUT / "county_midterm_results.parquet", index=False)

    print("units per year:", panel.groupby("year")["unit_fips"].nunique().to_dict())
    print("source:", panel.groupby(["year", "source"]).size().unstack(fill_value=0).to_string())
    states = check_states(panel)
    nat = states.groupby("year")[["ballots", "uf_ballots"]].sum().div(1e6).round(2)
    nat["diff_pct"] = (nat["ballots"] / nat["uf_ballots"] - 1).mul(100).round(2)
    print(nat.to_string())
    off = states[states["diff_pct"].abs() > 2].sort_values("diff_pct")
    print("states more than 2% off UF total ballots:\n", off.round(1).to_string(index=False))


if __name__ == "__main__":
    main()

"""House checks. The parser tests run offline on small saved fixtures; the data tests need

    cd src && python -m forecast.house          (and python -m forecast.backtest house)
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from forecast import house
from forecast.ingest import OUT

FIX = Path(__file__).parent / "fixtures" / "house"


# --------------------------------------------------------------------------- parsers (offline)
def test_cd_code():
    assert house.cd_code("Alabama 1") == "AL-01"
    assert house.cd_code("California 52") == "CA-52"
    assert house.cd_code("Alaska at-large") == "AK-AL"
    assert house.cd_code("Guam at-large") is None
    assert house.cd_code("Total") is None


@pytest.mark.parametrize("name, year, first, dem, rep", [
    ("downballot_pres2024_lines2026_votes_head.csv", 2024, "AK-AL", 140_026, 184_458),
    ("downballot_pres2020_lines2022_votes_head.csv", 2020, "AK-AL", 153_778, 189_951),
    # The 2018-lines sheet lists 2020 before 2016: the parser must pick the Clinton columns.
    ("downballot_pres2016_lines2018_votes_head.csv", 2016, "AK-AL", 116_454, 163_387),
])
def test_parse_pres_sheet(name, year, first, dem, rep):
    p = house.parse_pres_sheet((FIX / name).read_text(), year)
    assert p["cd"].iloc[0] == first
    assert p["dem"].iloc[0] == dem and p["rep"].iloc[0] == rep
    assert p["lean"].between(0, 1).all()
    assert p["cd"].str.match(r"^[A-Z]{2}-(\d\d|AL)$").all()


@pytest.fixture(scope="module")
def snippet() -> pd.DataFrame:
    return house.districts((FIX / "wiki_house_snippet.html").read_text(), 2022).set_index("cd")


def test_snippet_districts(snippet):
    assert list(snippet.index) == ["AK-AL", "AL-01", "AL-02", "CA-09", "CA-15", "FL-05", "FL-07"]   # no Guam


def test_contested_result(snippet):
    assert snippet.loc["AL-02", "contested"]
    assert snippet.loc["AL-02", "result_dem_2p"] == pytest.approx(29.0 / (29.0 + 69.1))
    assert snippet.loc["AL-02", "incumbency"] == -1
    # Alaska: first round, all Republicans summed; the instant runoff is ignored.
    assert snippet.loc["AK-AL", "result_dem_2p"] == pytest.approx(48.8 / (48.8 + 25.7 + 23.3))


def test_uncontested(snippet):
    # Only one candidate, or only one party's candidates: a certain hold.
    for cd, party in [("FL-05", "R"), ("CA-15", "D")]:
        assert not snippet.loc[cd, "contested"] and not snippet.loc[cd, "modelled"], cd
        assert np.isnan(snippet.loc[cd, "result_dem_2p"]), cd
        assert snippet.loc[cd, "sole_party"] == party, cd


def test_stand_in_for_missing_party(snippet):
    # A Republican against a Libertarian only: the Libertarian stands in for the Democratic side.
    r = snippet.loc["AL-01"]
    assert r["modelled"] and not r["contested"] and pd.isna(r["sole_party"])
    assert r["d_side"] == "independent_challenger" and r["r_side"] == "republican"
    assert r["stand_in"] == "Alexander Remrey"
    assert np.isnan(r["result_dem_2p"])                     # never trained or scored on
    assert r["result_side_2p"] == pytest.approx(16.2 / 100)


def test_two_members_one_running(snippet):
    r = snippet.loc["CA-09"]
    assert r["members"] == "Jerry McNerney; Josh Harder"
    assert r["incumbents_running"] == "Josh Harder" and r["incumbency"] == 1
    assert snippet.loc["FL-07", "incumbency"] == 0          # retired: open seat
    assert snippet.loc["FL-07", "winner"] == "R"


def test_2026_nominees_without_results():
    html = (FIX / "wiki_house_snippet.html").read_text()
    html = html.replace("Incumbent re-elected.", "Incumbent renominated")
    for pct in ["83.8%", "16.2%", "69.1%", "29.0%", "1.9%", "54.8%", "45.2%", "55.5%", "44.5%", "58.5%", "41.5%"]:
        html = html.replace(pct, "")
    d = house.districts(html, 2026).set_index("cd")
    assert d.loc["AL-02", "contested"] and np.isnan(d.loc["AL-02", "result_dem_2p"])
    assert d.loc["AL-02", "winner"] is None
    assert not d.loc["CA-15", "contested"] and d.loc["CA-15", "sole_party"] == "D"   # two Democrats
    # Before the election only an independent stands in for a missing party; a Republican facing
    # only a minor-party candidate is a certain hold, not a modelled contest.
    assert not d.loc["AL-01", "modelled"]


def test_2026_independent_against_democrat():
    """California 6, 2026: Kiley (elected as a Republican, now independent) against Pan."""
    html = (FIX / "wiki_house_ca06_2026.html").read_text()
    d = house.districts(html, 2026).set_index("cd")
    r = d.loc["CA-06"]
    assert r["modelled"] and not r["contested"] and pd.isna(r["sole_party"])
    assert r["d_side"] == "democrat" and r["r_side"] == "independent_challenger"
    assert r["stand_in"] == "Kevin Kiley" and r["incumbency"] == -1
    assert not d.loc["CA-07", "modelled"] and d.loc["CA-07", "sole_party"] == "D"   # two Democrats
    assert not d.loc["MA-02", "modelled"] and d.loc["MA-02", "sole_party"] == "D"   # unopposed


def test_simulate_fixes_uncontested():
    f = pd.DataFrame({"cd": ["AA-01", "AA-02", "AA-03", "AA-04"], "state_po": ["NY"] * 4,
                      "region": ["Northeast"] * 4, "lean_plain": [0.5, 0.8, 0.3, 0.5], "pres_nat": 0.5,
                      "incumbency": [0.0, 1.0, -1.0, 0.0], "track_record": 0.0,
                      "contested": [True, False, False, False], "modelled": [True, False, False, True],
                      "sole_party": [None, "D", "R", None],
                      "d_side": ["democrat", None, None, "democrat"],
                      "r_side": ["republican", None, None, "independent_challenger"]})
    n = 50
    params = {"a": np.zeros(n), "b": np.ones(n), "d": np.zeros(n), "h": np.zeros(n), "sigma": np.full(n, 0.1),
              "sigma_state": np.full(n, 0.05), "sigma_region": np.full(n, 0.02)}
    s = house.simulate(f, params, 2026, sims=200, house_fixed=0.5)
    assert (s[:, 1] == 1).all() and (s[:, 2] == 0).all()
    assert 0.3 < np.median(s[:, 0]) < 0.7
    # The stand-in race is a real contest, with more spread than the Democrat-v-Republican one.
    assert 0.3 < (s[:, 3] > 0.5).mean() < 0.7
    assert np.std(s[:, 3]) > np.std(s[:, 0])
    seats = house.seat_distribution(f, s)
    assert seats["probability"].sum() == pytest.approx(1)
    assert seats["dem_seats"].between(1, 3).all() and seats["independent_seats"].between(0, 1).all()
    assert (seats["independent_seats"] > 0).any()
    assert (seats["dem_seats"] + seats["independent_seats"] + seats["rep_seats"] == house.SEATS).all()


# --------------------------------------------------------------------------- data (after a run)
DISTRICTS = OUT / "house_2026.parquet"
SEATS = OUT / "house_seats_2026.csv"
needs_run = pytest.mark.skipif(not (DISTRICTS.exists() and SEATS.exists()), reason="run forecast.house first")


@pytest.fixture(scope="module")
def frames() -> dict:
    return {y: house.frame(y) for y in (2018, 2022, 2026)}


@needs_run
def test_435_districts_each_year(frames):
    for y, f in frames.items():
        assert len(f) == 435 and f["cd"].is_unique, y
        assert f.groupby("state_po").size().sum() == 435
        assert f["state_po"].nunique() == 50


@needs_run
def test_lean_in_unit_interval(frames):
    for y, f in frames.items():
        assert f["lean_plain"].between(0.05, 0.98).all(), y
        assert f["pres_nat"].between(0.45, 0.55).all()


@needs_run
def test_uncontested_handling(frames):
    for y, f in frames.items():
        u = f[~f["modelled"]]
        assert u["sole_party"].isin(["D", "R"]).all(), y
        assert f.loc[f["modelled"], "sole_party"].isna().all()
        assert len(u) < 60, y
        if y < 2026:
            assert f.loc[~f["contested"], "actual"].isna().all() and f.loc[f["contested"], "actual"].notna().all()
            assert (u["winner"] == u["sole_party"]).all()
    ca06 = frames[2026].set_index("cd").loc["CA-06"]
    assert ca06["modelled"] and ca06["r_side"] == "independent_challenger"


@needs_run
def test_past_seat_totals(frames):
    # Certified winners (Wikipedia). 2018: 235 Democrats were seated; North Carolina's 9th was
    # never certified and the Republican's uncertified lead is counted here, so 234.
    assert frames[2018]["winner"].eq("D").sum() == 234
    assert frames[2022]["winner"].eq("D").sum() == 213


@needs_run
def test_forecast_outputs():
    d = pd.read_parquet(DISTRICTS)
    assert len(d) == 435 and d["p_dem_win"].between(0, 1).all()
    assert (d.loc[~d["modelled"], "p_dem_win"].isin([0, 1])).all()
    assert 0 < d.set_index("cd").loc["CA-06", "p_dem_win"] < 1
    assert (d["p_dem_win"] + d["p_rep_win"] + d["p_ind_win"]).round(6).eq(1).all()
    s = pd.read_csv(SEATS)
    assert s["probability"].sum() == pytest.approx(1, abs=1e-9)
    assert s["dem_seats"].between(0, 435).all()
    # The seat distribution and the district table agree on expected seats.
    assert (s["dem_seats"] * s["probability"]).sum() == pytest.approx(d["p_dem_win"].sum(), abs=0.5)
    assert (s["dem_seats"] + s["independent_seats"] + s["rep_seats"] == 435).all()
    sure_d = int((~d["modelled"] & d["sole_party"].eq("D")).sum())
    sure_r = int((~d["modelled"] & d["sole_party"].eq("R")).sum())
    assert s["dem_seats"].min() >= sure_d and s["dem_seats"].max() <= 435 - sure_r

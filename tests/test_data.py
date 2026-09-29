"""Checks on the processed county panel. Run the ingest first:

    cd src && python -m forecast.ingest
    cd .. && python -m pytest
"""
import pandas as pd
import pytest

from forecast.ingest import NATIONAL_TOTAL_M, OUT, YEARS, check_presidential

PANEL = OUT / "county_panel.parquet"
pytestmark = pytest.mark.skipif(not PANEL.exists(), reason="run forecast.ingest first")


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return pd.read_parquet(PANEL)


def test_same_units_every_year(panel):
    units = panel.groupby("year")["unit_fips"].apply(frozenset)
    assert sorted(units.index) == YEARS
    assert units.nunique() == 1, "county units differ between years"
    assert 3_000 < len(units.iloc[0]) < 3_200


def test_one_row_per_unit_year(panel):
    assert not panel.duplicated(["year", "unit_fips"]).any()


def test_fifty_states_and_dc(panel):
    assert panel.groupby("year")["state_po"].nunique().eq(51).all()


def test_no_missing_denominators_or_demographics(panel):
    cols = ["total", "cvap", "population", "share_ba_plus", "share_white_nh", "median_age", "log_density"]
    assert panel[cols].notna().all().all(), panel.loc[panel[cols].isna().any(axis=1), ["year", "unit_fips"]]


def test_turnout_between_0_and_1(panel):
    assert (panel["turnout"] > 0).all()
    # CVAP is a survey estimate, so counties with a few hundred citizens can come out above 1.
    # Anything with at least 5,000 citizens of voting age must not.
    big = panel[panel["cvap"] >= 5_000]
    assert (big["turnout"] < 1).all(), big.loc[big["turnout"] >= 1, ["year", "unit_fips", "turnout"]]
    assert (panel["turnout"] > 1).mean() < 0.005


def test_national_turnout_plausible(panel):
    national = panel.groupby("year").apply(lambda d: d["total"].sum() / d["cvap"].sum(), include_groups=False)
    assert national.between(0.55, 0.70).all(), national


def test_two_party_share_between_0_and_1(panel):
    assert panel["dem_2p"].between(0, 1, inclusive="neither").all()


def test_national_totals_match_certified(panel):
    report = check_presidential(panel)
    assert set(report.index) == set(NATIONAL_TOTAL_M)
    assert report["diff_pct"].abs().max() < 0.5, report


def test_state_totals_move_plausibly(panel):
    """Catches partial or pre-certification counts, like a mirror file missing millions of
    California votes: no state's ballots should fall 15% or rise more than 40% in four years."""
    by_state = panel.pivot_table(index="state_po", columns="year", values="total", aggfunc="sum")
    change = by_state.pct_change(axis=1).iloc[:, 1:]
    bad = change[(change < -0.15) | (change > 0.40)].stack().dropna()
    assert bad.empty, bad

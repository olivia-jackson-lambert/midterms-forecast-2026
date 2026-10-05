"""Checks on county midterm turnout and results. Run first:

    cd src && python -m forecast.ingest && python -m forecast.midterms
"""
import pandas as pd
import pytest

from forecast.ingest import OUT
from forecast.midterms import MIDTERMS, check_states

TURNOUT = OUT / "county_midterm_turnout.parquet"
RESULTS = OUT / "county_midterm_results.parquet"
pytestmark = pytest.mark.skipif(not (TURNOUT.exists() and RESULTS.exists()), reason="run forecast.midterms first")


@pytest.fixture(scope="module")
def turnout() -> pd.DataFrame:
    return pd.read_parquet(TURNOUT)


@pytest.fixture(scope="module")
def results() -> pd.DataFrame:
    return pd.read_parquet(RESULTS)


def test_same_units_as_presidential_panel(turnout):
    pres_units = set(pd.read_parquet(OUT / "county_panel.parquet", columns=["unit_fips"])["unit_fips"])
    for year in MIDTERMS:
        assert set(turnout.loc[turnout["year"] == year, "unit_fips"]) == pres_units
    assert not turnout.duplicated(["year", "unit_fips"]).any()


def test_state_totals_match_certified(turnout):
    s = check_states(turnout)
    assert s["uf_ballots"].notna().all()
    assert s["diff_pct"].abs().max() < 0.5, s.loc[s["diff_pct"].abs() >= 0.5]


def test_turnout_between_0_and_1(turnout):
    assert turnout["ballots"].notna().all() and (turnout["turnout"] > 0).all()
    big = turnout[turnout["cvap"] >= 5_000]
    assert (big["turnout"] < 1).all(), big.loc[big["turnout"] >= 1, ["year", "unit_fips", "turnout"]]


def test_national_turnout(turnout):
    national = turnout.groupby("year").apply(lambda d: d["ballots"].sum() / d["cvap"].sum(), include_groups=False)
    assert national[2014] == pytest.approx(0.37, abs=0.02)
    assert national[2018] == pytest.approx(0.51, abs=0.02)
    assert national[2022] == pytest.approx(0.47, abs=0.02)


def test_little_imputation(turnout):
    share = turnout.assign(imp=turnout["source"].eq("imputed")).groupby("year")["imp"].mean()
    assert share[2014] < 0.10          # no county results for 2014 to fall back on
    assert share[2018] < 0.01 and share[2022] < 0.01


def test_races_found(results):
    races = results[results["race"] != "HOUSE"].groupby(["year", "race", "special"])["state_po"].nunique()
    assert races[(2018, "GOV", False)] == 36
    assert races[(2018, "SEN", False)] == 33 and races[(2018, "SEN", True)] == 2
    # 2022 gaps (CA Senate regular+special, TN governor) are filled from state / Wikipedia sources.
    assert races[(2022, "GOV", False)] == 36
    assert races[(2022, "SEN", False)] == 34 and races[(2022, "SEN", True)] == 2


@pytest.mark.parametrize("year, state, race, dem, rep", [
    (2018, "AZ", "SEN", 1_191_100, 1_135_200),     # certified: Sinema, McSally
    (2018, "NV", "SEN", 490_071, 441_202),          # Rosen, Heller
    (2022, "GA", "SEN", 1_946_117, 1_908_442),      # general election (not the runoff): Warnock, Walker
    (2022, "WI", "SEN", 1_310_467, 1_337_185),      # Barnes, Johnson
    (2022, "PA", "SEN", 2_751_012, 2_487_260),      # Fetterman, Oz
    (2022, "CA", "SEN", 6_621_621, 4_222_029),      # Padilla, Meuser (full term; SOS supplement)
    (2022, "TN", "GOV", 572_818, 1_129_390),        # Martin, Lee (Wikipedia; Lee ~70 under SOS)
])
def test_statewide_results_match_certified(results, year, state, race, dem, rep):
    r = results[(results["year"] == year) & (results["state_po"] == state) & (results["race"] == race) & ~results["special"]]
    # Tennessee governor Wikipedia county sum is ~70 Lee votes under SOS statewide certified.
    tol = 0.0002 if (year, state, race) == (2022, "TN", "GOV") else 0.002
    assert r["dem"].sum() == pytest.approx(dem, rel=tol)
    assert r["rep"].sum() == pytest.approx(rep, rel=tol)

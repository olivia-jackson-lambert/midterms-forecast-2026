"""Checks on Stage B inputs and the vote model. Run first:

    cd src && python -m forecast.races && python -m forecast.generic_ballot && python -m forecast.vote_model
"""
import numpy as np
import pandas as pd
import pytest

from forecast.ingest import OUT

RACES = OUT / "races.parquet"
pytestmark = pytest.mark.skipif(not RACES.exists(), reason="run forecast.races first")


@pytest.fixture(scope="module")
def races() -> pd.DataFrame:
    return pd.read_parquet(RACES)


# --------------------------------------------------------------------------- races
def test_race_counts(races):
    n = races.groupby(["year", "office", "special"]).size()
    for y in (2018, 2022, 2026):
        assert n[(y, "GOV", False)] == 36
        assert n[(y, "SEN", False)] == (34 if y == 2022 else 33)
        assert n[(y, "SEN", True)] == 2


def test_race_list_matches_turnout_features(races):
    """The Senate states the turnout model assumes are on the ballot match the parsed pages."""
    from forecast.features import SENATE
    for y in (2018, 2022, 2026):
        parsed = set(races.loc[(races["year"] == y) & races["office"].eq("SEN"), "state_po"])
        assert parsed == set(SENATE[y].split())


@pytest.mark.parametrize("race_id, open_seat, d_side", [
    ("2026-TX-SEN", True, "democrat"),               # Cornyn lost renomination
    ("2026-LA-SEN", True, "democrat"),               # Cassidy lost renomination
    ("2026-SC-SEN", False, "democrat"),              # interim appointee running
    ("2026-OK-SEN", True, "democrat"),               # interim appointee ineligible
    ("2026-NE-SEN", False, "independent_challenger"),
    ("2018-VT-SEN", False, "independent_incumbent"),
    ("2018-CA-SEN", False, "not_two_party"),         # two Democrats
    ("2022-AK-SEN", False, "not_two_party"),         # two Republicans in the final round
])
def test_race_classification(races, race_id, open_seat, d_side):
    r = races.set_index("race_id").loc[race_id]
    assert bool(r["open_seat"]) == open_seat
    assert r["d_side"] == d_side


def test_track_record_uses_the_right_person(races):
    r = races.set_index("race_id")
    assert r.loc["2026-VT-GOV", "prev_year"] == 2024             # Phil Scott
    assert pd.isna(r.loc["2026-SC-SEN", "prev_year"])            # Darline Graham, not Lindsey Graham


# --------------------------------------------------------------------------- results
def test_race_results_agree_with_county_files():
    """Certified statewide results (Wikipedia) against MIT county files. Known gaps only."""
    from forecast import vote_model as vm
    known = {"2018-DE-SEN", "2018-NY-GOV", "2018-OR-GOV", "2018-MS-SENS", "2022-IN-SEN"}
    for y in (2018, 2022):
        f = vm.frame(y)
        m = f[~f["independent"]].merge(vm.actual_shares(y).rename(columns={"actual": "county"}),
                                      on=["state_po", "office", "special"])
        off = m.loc[(m["county"] - m["result_dem_2p"]).abs() > 0.01, "race_id"]
        assert set(off) <= known, set(off) - known


def test_every_two_party_race_has_a_result():
    from forecast import vote_model as vm
    for y in (2018, 2022):
        f = vm.frame(y)
        assert f.loc[~f["independent"], "actual"].between(0.1, 0.9).all()


# --------------------------------------------------------------------------- generic ballot
def test_backtest_generic_ballot_is_from_before_october():
    """The leak this module exists to prevent: backtests may only use values public by 1 October."""
    from forecast import generic_ballot
    gb = generic_ballot.generic_ballot()
    past = gb[gb["year"] < 2026]
    assert (pd.to_datetime(past["as_of"]) <= pd.to_datetime(past["year"].astype(str) + "-09-30")).all()


def test_national_environment_uses_only_earlier_years():
    from forecast import generic_ballot
    h = generic_ballot.history()
    e = generic_ballot.national_environment(2022, h)
    assert e["n_years"] == len(h[(h["year"] < 2022) & h["house_dem_2p"].notna()])
    h2 = h.copy()
    h2.loc[h2["year"] == 2022, "house_dem_2p"] = 0.9          # changing 2022's result must not move 2022's forecast
    assert generic_ballot.national_environment(2022, h2)["mean"] == pytest.approx(e["mean"])


# --------------------------------------------------------------------------- simulation
def _toy_frame(n=6):
    return pd.DataFrame({
        "race_id": [f"r{i}" for i in range(n)], "state_po": ["AA", "AA", "BB", "CC", "DD", "EE"][:n],
        "office": ["SEN", "GOV"] * (n // 2), "office_i": [0, 1] * (n // 2), "region": ["West"] * n,
        "lean_plain": np.linspace(0.35, 0.65, n), "lean_turnout": np.linspace(0.35, 0.65, n),
        "pres_nat": 0.5, "incumbency": 0.0, "track_record": 0.0, "independent": False,
    })


def _toy_params(draws=200, sd=0.1):
    return {"a": np.zeros((draws, 2)), "b": np.ones((draws, 2)), "d": np.zeros((draws, 2)),
            "h": np.zeros((draws, 2)), "sigma": np.full((draws, 2), sd), "sigma_state": np.full(draws, sd),
            "sigma_region": np.full(draws, sd), "lean": "lean_plain"}


def test_simulation_shares_follow_the_lean(monkeypatch):
    from forecast import generic_ballot, vote_model as vm
    monkeypatch.setattr(generic_ballot, "national_environment", lambda y: {"mean": 0.5, "sd": 1e-6, "df": 30})
    f = _toy_frame()
    sims = vm.simulate(f, _toy_params(sd=1e-6), 2026, sims=500, turnout_weighted=False)
    assert sims.shape == (500, len(f))
    assert np.allclose(np.median(sims, 0), f["lean_plain"], atol=1e-3)


def test_shared_national_error_correlates_races(monkeypatch):
    from forecast import generic_ballot, vote_model as vm
    monkeypatch.setattr(generic_ballot, "national_environment", lambda y: {"mean": 0.5, "sd": 0.05, "df": 30})
    sims = vm.simulate(_toy_frame(), _toy_params(sd=0.01), 2026, sims=4000, turnout_weighted=False)
    c = np.corrcoef(sims.T)
    assert c[np.triu_indices_from(c, 1)].min() > 0.8

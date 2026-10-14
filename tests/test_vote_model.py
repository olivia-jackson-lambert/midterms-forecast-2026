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
        "pres_nat": 0.5, "incumbency": 0.0, "track_record": 0.0, "fundraising": 0.0, "independent": False,
    })


def _toy_params(draws=200, sd=0.1):
    return {"a": np.zeros((draws, 2)), "b": np.ones((draws, 2)), "d": np.zeros((draws, 2)),
            "h": np.zeros((draws, 2)), "q": np.zeros(draws), "sigma": np.full((draws, 2), sd), "sigma_state": np.full(draws, sd),
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


# --------------------------------------------------------------------------- fundraising (no network)
@pytest.mark.parametrize("fec_name, nominee, ok", [
    ("CRUZ, RAFAEL EDWARD  TED", "Ted Cruz", True),
    ("CASEY, ROBERT P. JR.", "Bob Casey Jr.", True),          # suffix
    ("VAN HOLLEN, CHRIS", "Chris Van Hollen", True),          # two-word surname
    ("CORTEZ MASTO, CATHERINE", "Catherine Cortez Masto", True),
    ("LUJAN, BEN RAY", "Ben Ray Luján", True),                # accent
    ("ARENHOLZ, ASHLEY HINSON", "Ashley Hinson", True),       # files under another surname
    ("COLLINS, MICHAEL A JR", "Susan Collins", True),         # same surname: both kept, largest receipts wins
    ("HOLLENBECK, DAVID", "Chris Van Hollen", False),
    ("JACKSON, ANNETTE", "Troy Jackson", True),
])
def test_fec_name_matching(fec_name, nominee, ok):
    from forecast.fundraising import _matches
    assert _matches(fec_name, nominee) is ok


# --------------------------------------------------------------------------- nominee track record
def _past_row(year, state, office, dem, rep, share, d_side="democrat", party="Democratic"):
    return {"year": year, "state_po": state, "office": office, "special": False, "d_side": d_side,
            "d_side_party": party, "dem_names": dem, "rep_names": rep, "result_dem_2p": share}


def test_name_matching_uses_first_initial_and_surname():
    from forecast.races import _ran_as, _surname
    assert _surname("Bob Casey Jr.") == "b casey"
    assert _surname("Daniel S. Sullivan") == _surname("Dan Sullivan") == "d sullivan"
    assert _surname("Darline Graham") != _surname("Lindsey Graham")
    race = _past_row(2020, "SC", "SEN", "Jaime Harrison", "Lindsey Graham", 0.45)
    assert _ran_as(race, _surname("Lindsey Graham")) == "R"
    assert _ran_as(race, _surname("Jaime Harrison")) == "D"
    assert _ran_as(race, _surname("Darline Graham")) is None


def test_minor_party_stand_ins_do_not_count_as_the_democratic_side():
    from forecast.races import _ran_as
    lib = _past_row(2022, "SD", "HOU", "Collin Duprel", "Dusty Johnson", 0.2, "independent_challenger", "Libertarian")
    ind = _past_row(2022, "ND", "HOU", "Cara Mund", "Kelly Armstrong", 0.4, "independent_challenger", "Independent")
    assert _ran_as(lib, "c duprel") is None
    assert _ran_as(ind, "c mund") == "D"


def test_nominee_history_takes_the_most_recent_race_on_either_side():
    from forecast.races import add_nominee_history
    past = pd.DataFrame([
        _past_row(2014, "XX", "SEN", "Ann Lee", "Bo Ray", 0.45),
        _past_row(2016, "XX", "GOV", "Cy Dunn", "Ann Lee", 0.60),          # Lee ran as a Republican in 2016
        _past_row(2018, "YY", "SEN", "Ann Lee", "Di Fox", 0.70),           # a different state
        _past_row(2020, "XX", "HOU", "Ed Poe", "Fay Ng", float("nan"), "not_two_party"),
    ])
    df = pd.DataFrame([{"year": 2026, "state_po": "XX", "dem_candidate": "Ann Lee", "rep_candidate": "Gus Hall"}])
    r = add_nominee_history(df, past).iloc[0]
    assert (r["dem_prev_year"], r["dem_prev_office"], r["dem_prev_side"], r["dem_prev_dem_2p"]) == (2016, "GOV", "R", 0.60)
    assert pd.isna(r["rep_prev_year"])
    assert pd.isna(add_nominee_history(df.assign(year=2014), past).iloc[0]["dem_prev_year"])     # nothing earlier than 2014


@pytest.fixture
def flat_expectation(monkeypatch):
    """Expected share 50% everywhere, so a record is just logit(share)."""
    from forecast import vote_model as vm
    monkeypatch.setattr(vm, "_expected_logit", lambda year, state, cache: 0.0)
    return vm


def _frame(**kw):
    base = {"prev_dem_2p": np.nan, "prev_year": np.nan, "state_po": "XX",
            "dem_prev_dem_2p": np.nan, "dem_prev_year": np.nan, "dem_prev_office": None, "dem_prev_side": None,
            "rep_prev_dem_2p": np.nan, "rep_prev_year": np.nan, "rep_prev_office": None, "rep_prev_side": None}
    return pd.DataFrame([{**base, **kw}])


def test_track_record_is_symmetric_between_parties(flat_expectation):
    vm = flat_expectation
    # a Democrat who took 60% ...
    d = vm.track_record(_frame(dem_prev_dem_2p=0.6, dem_prev_year=2020, dem_prev_office="SEN", dem_prev_side="D"))
    # ... is the mirror of a Republican who took 60% (the Democratic side had 40%)
    r = vm.track_record(_frame(rep_prev_dem_2p=0.4, rep_prev_year=2020, rep_prev_office="SEN", rep_prev_side="R"))
    assert d.iloc[0] == pytest.approx(float(np.log(0.6 / 0.4))) and r.iloc[0] == pytest.approx(-d.iloc[0])


def test_track_record_matches_the_incumbent_feature_when_only_the_incumbent_has_history(flat_expectation):
    vm = flat_expectation
    f = _frame(prev_dem_2p=0.55, prev_year=2020, dem_prev_dem_2p=0.55, dem_prev_year=2020,
               dem_prev_office="SEN", dem_prev_side="D")
    assert vm.track_record(f, nominees=True).iloc[0] == pytest.approx(vm.track_record(f, nominees=False).iloc[0])


def test_track_record_counts_a_rematch_once(flat_expectation):
    vm = flat_expectation
    f = _frame(dem_prev_dem_2p=0.4, dem_prev_year=2020, dem_prev_office="SEN", dem_prev_side="D",
               rep_prev_dem_2p=0.4, rep_prev_year=2020, rep_prev_office="SEN", rep_prev_side="R")
    assert vm.track_record(f).iloc[0] == pytest.approx(float(np.log(0.4 / 0.6)))


def test_known_statewide_histories(races):
    r = races.set_index("race_id")
    brown = r.loc["2026-OH-SENS"]                                    # Brown lost in 2024; 2018 is the one before
    assert (brown["dem_prev_year"], brown["dem_prev_office"], brown["dem_prev_side"]) == (2024, "SEN", "D")
    assert pd.isna(brown["rep_prev_year"])                           # Husted, appointed, has not stood statewide
    assert (r.loc["2026-NC-SEN", "dem_prev_year"], r.loc["2026-NC-SEN", "dem_prev_office"]) == (2020, "GOV")   # Cooper
    assert (r.loc["2026-AL-GOV", "dem_prev_year"], r.loc["2026-AL-GOV", "dem_prev_office"]) == (2020, "SEN")  # Jones
    assert (r.loc["2026-AK-SEN", "dem_prev_year"], r.loc["2026-AK-SEN", "dem_prev_office"]) == (2024, "HOU")  # Peltola, at-large House
    assert pd.isna(r.loc["2026-NH-SEN", "rep_prev_year"])            # John E. Sununu last ran in 2008, before the history
    assert pd.isna(r.loc["2026-SC-SEN", "rep_prev_year"])            # Darline Graham, not Lindsey Graham
    assert r.loc["2026-VT-GOV", "rep_prev_year"] == 2024 and r.loc["2026-VT-GOV", "prev_year"] == 2024   # Phil Scott
    assert r.loc["2026-WY-SEN", "rep_prev_office"] == "HOU"          # Hageman, at-large House in 2024


def test_sherrod_brown_2018_race_is_in_the_history():
    from forecast.races import RAW_RACES, _ran_as, _surname, races
    if not (RAW_RACES / "2018_United_States_Senate_elections.html").exists():
        pytest.skip("run forecast.races first")
    oh = races(2018).set_index("race_id").loc["2018-OH-SEN"]
    assert _ran_as(oh, _surname("Sherrod Brown")) == "D" and 0.52 < oh["result_dem_2p"] < 0.55


def test_at_large_house_history_is_parsed():
    from forecast.races import RAW_RACES, house_at_large
    if not (RAW_RACES / "2012_United_States_House_of_Representatives_elections.html").exists():
        pytest.skip("run forecast.races first")
    h = house_at_large(2012).set_index("state_po")
    assert set(h.index) == {"AK", "DE", "MT", "ND", "SD", "VT", "WY"}
    assert h.loc["VT", "result_dem_2p"] > 0.7 and h.loc["WY", "result_dem_2p"] < 0.3
    assert {"AK", "DE", "ND", "SD", "VT", "WY"} <= set(house_at_large(2024)["state_po"])      # Montana has two seats by 2022

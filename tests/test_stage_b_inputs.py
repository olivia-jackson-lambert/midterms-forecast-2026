"""Stage B data-input checks: generic ballot, race list, and 2022 result supplements.

Supplement parsers hit the network on first run and cache under data/raw/.
"""
from __future__ import annotations

import pandas as pd
import pytest

from forecast.generic_ballot import SOURCE_NOTES_2026, aggregates, snapshot
from forecast.midterms import CA_SENATE_CERTIFIED, TN_GOV_CERTIFIED, california_senate_2022, tennessee_governor_2022
from forecast.races import GOV_OPEN, SENATE_OPEN, SENATE_SPECIAL, governor_races, senate_races


def test_generic_ballot_backtest_snapshots():
    s18, s22 = snapshot(2018), snapshot(2022)
    # Wikipedia / RCP+538 eve-of-election averages: Dem lead in 2018, slight Rep edge in 2022.
    assert s18["margin"] == pytest.approx(8.0, abs=1.0)
    assert s22["margin"] == pytest.approx(-1.8, abs=1.0)
    assert s18["dem_2p"] > 0.52
    assert 0.45 < s22["dem_2p"] < 0.52


def test_generic_ballot_2026_sources_documented():
    s = snapshot(2026)
    assert s["n_sources"] >= 2
    assert s["dem"] > s["rep"]          # October 2026 Wikipedia aggregate table
    assert "wikipedia_aggregates" in SOURCE_NOTES_2026
    detail = aggregates(2026)
    assert {"Decision Desk HQ", "RealClearPolitics", "FiftyPlusOne"} <= set(detail["source"])


def test_california_senate_2022_matches_certified():
    df = california_senate_2022()
    assert set(df["special"]) == {False, True}
    assert df["county_fips"].nunique() == 58
    for special, cert in CA_SENATE_CERTIFIED.items():
        part = df[df["special"] == special]
        assert part["dem"].sum() == pytest.approx(cert["dem"], abs=1)
        assert part["rep"].sum() == pytest.approx(cert["rep"], abs=1)


def test_tennessee_governor_2022_matches_certified():
    df = tennessee_governor_2022()
    assert len(df) == 95
    assert df["dem"].sum() == pytest.approx(TN_GOV_CERTIFIED["dem"], abs=1)
    # Wikipedia county table undershoots Lee by ~70 votes vs SOS statewide certified.
    assert df["rep"].sum() == pytest.approx(TN_GOV_CERTIFIED["rep"], abs=100)


def test_races_2026_counts():
    sen, gov = senate_races(2026), governor_races(2026)
    assert len(sen) == 35          # 33 regular + FL and OH specials
    assert sen["special"].sum() == 2
    assert set(sen.loc[sen["special"], "state_po"]) == SENATE_SPECIAL
    assert set(sen.loc[sen["open_seat"], "state_po"]) == SENATE_OPEN
    assert len(gov) == 36
    assert set(gov.loc[gov["open_seat"], "state_po"]) == GOV_OPEN
    assert gov["incumbent_party"].notna().all() and sen["incumbent_party"].notna().all()

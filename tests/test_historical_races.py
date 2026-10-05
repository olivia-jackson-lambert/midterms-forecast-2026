"""Historical incumbency + scheduled specials for Stage B backtests."""
from __future__ import annotations

from forecast import historical_races, vote_model
from forecast.historical_races import GOV_OPEN, SENATE_OPEN, SENATE_SPECIAL


def test_historical_senate_open_sets():
    assert SENATE_OPEN[2018] == {"AZ", "TN", "UT"}
    assert {"AL", "PA", "VT"}.issubset(SENATE_OPEN[2022])
    s18 = historical_races.senate_races(2018)
    assert set(s18.loc[s18["open_seat"], "state_po"]) == SENATE_OPEN[2018]
    assert (s18.loc[s18["open_seat"], "incumbency"] == 0).all()
    # Sitting Dem (CA Feinstein) → +1; sitting Rep (TX Cruz) → -1.
    by = s18.set_index("state_po")
    assert by.loc["CA", "incumbency"] == 1.0
    assert by.loc["TX", "incumbency"] == -1.0


def test_scheduled_races_emits_historical_specials():
    r18 = vote_model.scheduled_races(2018)
    assert set(r18.loc[r18["special"], "state_po"]) == SENATE_SPECIAL[2018]
    # Regular + special for MN/MS.
    assert (r18["office"] == "SEN").sum() == 33 + 2
    r22 = vote_model.scheduled_races(2022)
    assert set(r22.loc[r22["special"], "state_po"]) == SENATE_SPECIAL[2022]
    assert (r22["office"] == "SEN").sum() == 34 + 2


def test_race_fundamentals_historical_incumbency():
    fund = vote_model.race_fundamentals(2018)
    assert fund["incumbency"].isin([-1.0, 0.0, 1.0]).all()
    open_ids = {f"2018-{st}-SEN" for st in SENATE_OPEN[2018]}
    assert set(fund.loc[fund["incumbency"] == 0, "race_id"]) >= open_ids
    gov = vote_model.race_fundamentals(2022)
    open_gov = {f"2022-{st}-GOV" for st in GOV_OPEN[2022]}
    assert open_gov <= set(gov.loc[gov["open_seat"], "race_id"])

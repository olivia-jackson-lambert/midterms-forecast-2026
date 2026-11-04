"""Checks on the comparison maths (forecast.compare) and the source parsers."""
import math

import numpy as np
import pandas as pd
import pytest

from forecast.compare import (RATING_P, brier, implied_two_way, log_loss, rating_to_p, seat_quantiles,
                              upsets)
from forecast.compare_archive import T270_CODES, decode_t270, parse_cook, t270_key_to_cd
from forecast.compare_sources import side_of


def test_rating_mapping_is_the_stated_one_and_symmetric():
    assert rating_to_p("Toss Up") == 0.50
    assert rating_to_p("Lean D") == 0.65 and rating_to_p("Lean R") == 0.35
    assert rating_to_p("Likely D") == 0.85 and rating_to_p("Likely R") == pytest.approx(0.15)
    assert rating_to_p("Solid D") == 0.97 and rating_to_p("Solid R") == pytest.approx(0.03)
    for d, r in [("Lean D", "Lean R"), ("Likely D", "Likely R"), ("Solid D", "Solid R")]:
        assert RATING_P[d] + RATING_P[r] == pytest.approx(1.0)


def test_rating_spellings():
    assert rating_to_p("Safe R") == rating_to_p("Solid R")
    assert rating_to_p("Leans D") == rating_to_p("Lean D")
    assert rating_to_p("Tilt R") == rating_to_p("Lean R")
    assert rating_to_p("Toss-up") == 0.5
    assert rating_to_p(None) is None
    with pytest.raises(ValueError):
        rating_to_p("Very Likely D")


def test_brier_by_hand():
    assert brier([0.8, 0.3], [1, 0]) == pytest.approx(((0.2) ** 2 + 0.3 ** 2) / 2)
    assert brier([0.5], [1]) == 0.25
    assert brier([1.0, 0.0], [1, 0]) == 0.0


def test_log_loss_by_hand_and_clipping():
    assert log_loss([0.8, 0.3], [1, 0]) == pytest.approx(-(math.log(0.8) + math.log(0.7)) / 2)
    assert log_loss([0.5], [0]) == pytest.approx(math.log(2))
    # A certain forecast that misses is clipped to 0.001 rather than infinite.
    assert log_loss([0.0], [1]) == pytest.approx(-math.log(0.001))
    assert np.isfinite(log_loss([1.0, 0.0], [0, 1]))


def test_upsets_count_half_for_fifty_fifty():
    assert upsets([0.9, 0.2, 0.5, 0.6], [0, 0, 1, 1]) == 1.5


def test_implied_two_way_removes_overround():
    assert implied_two_way(0.67, 0.34) == pytest.approx(0.67 / 1.01)
    assert implied_two_way(0.3, None) == 0.3
    assert implied_two_way(None, 0.25) == 0.75
    assert implied_two_way(None, None) is None


def test_seat_quantiles():
    d = pd.DataFrame({"dem_seats": [48, 49, 50, 51, 52], "probability": [0.1, 0.2, 0.4, 0.2, 0.1]})
    # The q-quantile is the smallest seat count whose cumulative probability reaches q.
    assert seat_quantiles(d) == [48, 50, 51]


def test_parse_cook_text():
    text = ("CPR Senate Race Ratings Oct 20, 2026 About ... Solid D Solid Democrat (2) 2 Dem 0 Rep CO Hickenlooper "
            "DE Coons Likely D Likely Democrat (0) 0 Dem 0 Rep Lean D Lean Democrat (0) 0 Dem 0 Rep "
            "Toss Up Toss Up (1) 0 Dem 1 Rep TX OPEN Lean R Lean Republican (0) 0 Dem 0 Rep "
            "Likely R Likely Republican (1) 0 Dem 1 Rep NE Ricketts Solid R Solid Republican (1) 0 Dem 1 Rep "
            "WY OPEN Hover over chart segments")
    updated, r = parse_cook(text, "senate")
    assert updated == "Oct 20, 2026"
    assert r == {"CO": "Solid D", "DE": "Solid D", "TX": "Toss Up", "NE": "Likely R", "WY": "Solid R"}


def test_parse_cook_house_text():
    text = ("CPR House Race Ratings Oct 16, 2026 Solid D Solid Democrat (1) AL-07 Sewell "
            "Likely D Likely Democrat (0) Lean D Lean Democrat (1) PA-10 Perry Toss Up Toss Up (1) PA-08 Bresnahan "
            "Lean R Lean Republican (1) KY-06 OPEN (Barr) Likely R Likely Republican (1) AK-AL Begich III "
            "Solid R Solid Republican (0) Hover over")
    _, r = parse_cook(text, "house")
    assert r == {"AL-07": "Solid D", "PA-10": "Lean D", "PA-08": "Toss Up", "KY-06": "Lean R", "AK-AL": "Likely R"}


def test_t270_decoding():
    assert t270_key_to_cd("0200") == "AK-AL"
    assert t270_key_to_cd("4215") == "PA-15"
    assert set(T270_CODES.values()) == set(RATING_P)
    assert decode_t270(["AK-AL", "PA-08"], "40") == {"AK-AL": "Likely R", "PA-08": "Toss Up"}


def test_side_of_independent_and_party_markers():
    races = pd.DataFrame({"race_id": ["2026-NE-SEN", "2026-TX-SEN"], "dem_candidate": ["Dan Osborn", "James Talarico"],
                          "rep_candidate": ["Pete Ricketts", "Ken Paxton"],
                          "d_side": ["independent_challenger", "democrat"]})
    assert side_of("Independent", "2026-NE-SEN", races) == "D"
    assert side_of("Dan Osborn", "2026-NE-SEN", races) == "D"
    assert side_of("Democrat", "2026-NE-SEN", races) is None  # the Democrat is not v1's Democratic side here
    assert side_of("Pete Ricketts (R)", "2026-NE-SEN", races) == "R"
    assert side_of("James Talarico", "2026-TX-SEN", races) == "D"
    assert side_of("Democratic Party", "control", races) == "D"

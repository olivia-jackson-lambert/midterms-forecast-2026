"""Scoring maths (forecast.score) and results parsing (forecast.results) on hand-checkable cases."""
import math

import numpy as np
import pandas as pd
import pytest

from forecast import results, score


# --------------------------------------------------------------------------- Brier and log loss
def test_brier_by_hand():
    # (0.9-1)^2 = 0.01, (0.2-0)^2 = 0.04, (0.5-1)^2 = 0.25 -> mean 0.1
    assert score.brier([0.9, 0.2, 0.5], [1, 0, 1]) == pytest.approx(0.1)


def test_brier_empty_is_none():
    assert score.brier([], []) is None


def test_log_loss_by_hand():
    # -(ln 0.8 + ln 0.5) / 2
    assert score.log_loss([0.8, 0.5], [1, 0]) == pytest.approx(-(math.log(0.8) + math.log(0.5)) / 2)


def test_log_loss_clips_certainty_like_the_backtests():
    # p = 0 for an event that happened is clipped to 0.001, not infinite
    assert score.log_loss([0.0], [1]) == pytest.approx(-math.log(1e-3))
    assert score.log_loss([1.0], [1]) == pytest.approx(-math.log(1 - 1e-3))


# --------------------------------------------------------------------------- calibration
def test_calibration_five_bins():
    cal = score.calibration([0.0, 0.1, 0.3, 0.5, 0.9, 1.0], [0, 1, 0, 1, 1, 1])
    assert [c["bin"] for c in cal] == ["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
    assert [c["races"] for c in cal] == [2, 1, 1, 0, 2]
    assert cal[0]["mean_p"] == pytest.approx(0.05) and cal[0]["win_rate"] == pytest.approx(0.5)
    assert cal[3]["mean_p"] is None                     # an empty bin has no mean
    assert cal[4]["win_rate"] == 1.0


def test_calibration_edges_match_backtest_bins():
    # pd.cut is right-closed: 0.2 falls in the first bin, 0.0 is included in it
    cal = score.calibration([0.0, 0.2, 0.2001], [0, 0, 0])
    assert [c["races"] for c in cal][:2] == [2, 1]


# --------------------------------------------------------------------------- favourites
def test_favourites_upsets_and_expected():
    probs = pd.DataFrame({"D": [0.9, 0.3, 0.6], "R": [0.1, 0.7, 0.4], "I": [0, 0, 0]})
    out = score.favourite_counts(probs, pd.Series(["D", "D", "R"]))
    assert out["favourites_won"] == 1 and out["upsets"] == 2 and out["ties"] == 0
    assert out["expected_upsets"] == pytest.approx(0.1 + 0.3 + 0.4)
    assert list(out["upset_mask"]) == [False, True, True]


def test_exact_tie_has_no_favourite():
    probs = pd.DataFrame({"D": [0.5], "R": [0.5], "I": [0.0]})
    out = score.favourite_counts(probs, pd.Series(["D"]))
    assert out["ties"] == 1 and out["favourites_won"] == 0 and out["upsets"] == 0
    assert out["expected_upsets"] == pytest.approx(0.5)


def test_house_stand_in_can_be_favourite():
    probs = pd.DataFrame({"D": [0.2], "R": [0.0], "I": [0.8]})
    assert score.favourite_counts(probs, pd.Series(["I"]))["favourites_won"] == 1


# --------------------------------------------------------------------------- vote share
def test_vote_error_by_hand():
    # errors +2, -1, +5 points; intervals put them inside, inside, above
    out = score.vote_error([0.52, 0.49, 0.60], [0.50, 0.50, 0.55], [0.45, 0.45, 0.50], [0.55, 0.55, 0.58])
    assert out["n"] == 3
    assert out["mean_error_toward_dem"] == pytest.approx(2.0)
    assert out["mae"] == pytest.approx(8 / 3, abs=0.005)
    assert out["rmse"] == pytest.approx(math.sqrt((4 + 1 + 25) / 3), abs=0.005)
    assert (out["below_80"], out["inside_80"], out["above_80"]) == (0, 2, 1)
    assert out["coverage_80"] == pytest.approx(2 / 3, abs=1e-4)


def test_vote_error_interval_ends_count_as_inside():
    out = score.vote_error([0.45, 0.55], [0.5, 0.5], [0.45, 0.45], [0.55, 0.55])
    assert out["inside_80"] == 2


def test_vote_error_empty():
    out = score.vote_error([], [], [], [])
    assert out["n"] == 0 and out["mae"] is None and out["inside_80"] == 0


# --------------------------------------------------------------------------- seat distributions
DIST = pd.Series({49: 0.2, 50: 0.3, 51: 0.4, 52: 0.1})


def test_mid_percentile():
    assert score.mid_percentile(DIST, 51) == pytest.approx(0.2 + 0.3 + 0.2)
    assert score.mid_percentile(DIST, 49) == pytest.approx(0.1)
    assert score.mid_percentile(DIST, 60) == pytest.approx(1.0)


def test_quantiles():
    assert score.quantile(DIST, 0.5) == 50          # cumulative 0.2, 0.5 -> reaches 0.5 at 50
    assert score.quantile(DIST, 0.1) == 49
    assert score.quantile(DIST, 0.9) == 51          # cumulative 0.9 at 51


def test_percentile_range_until_complete():
    out = score._percentiles(DIST, 50, 52, complete=False)
    assert out["percentile"] is None
    assert out["percentile_range"] == [pytest.approx(0.35), pytest.approx(0.95)]
    done = score._percentiles(DIST, 52, 52, complete=True)
    assert done["percentile"] == pytest.approx(0.95) and done["inside_80"] is False


# --------------------------------------------------------------------------- outcomes
def _row(**kw):
    base = dict(called=True, winner_party="D", winner_name="A B", office="senate", d_kind="democrat",
                dem_name="A B", stand_in=None)
    return pd.Series(base | kw)


def test_outcome_independent_challenger():
    r = _row(d_kind="independent_challenger", dem_name="Dan Osborn", winner_party="I", winner_name="Dan Osborn")
    assert score._outcome(r) == "D"                 # the independent is v1's Democratic side
    r = _row(d_kind="independent_challenger", dem_name="Dan Osborn", winner_party="R", winner_name="Pete Ricketts")
    assert score._outcome(r) == "R"


def test_outcome_unmodelled_winner():
    # Montana: v1's Democratic side is the Democrat; an independent winner is neither side
    r = _row(winner_party="I", winner_name="Seth Bodnar", dem_name="Alani Bankhead")
    assert score._outcome(r) == "other"


def test_outcome_house_stand_in_and_uncalled():
    r = _row(office="house", stand_in="Kevin Kiley", winner_party="R", winner_name="Kevin Kiley")
    assert score._outcome(r) == "I"
    assert score._outcome(_row(called=False)) is None


def test_no_called_races_gives_holdover_seats():
    f = score.frame(pd.DataFrame(columns=results.LOG_COLUMNS))
    ch, chance, pct = score.chambers(f)
    assert (ch["senate"]["dem_seats"], ch["senate"]["rep_seats"]) == (34, 31)   # 47 and 53 less the seats up
    assert (ch["governor"]["dem_seats"], ch["governor"]["rep_seats"]) == (6, 8)
    assert ch["house"]["dem_seats"] == 0 and ch["senate"]["control"] is None
    assert chance["senate"]["p_dem_control"] == pytest.approx(0.63, abs=0.01)   # README: 63%


# --------------------------------------------------------------------------- parsing the AP feed
def _ap(rid, office, st, seat, cands, status="Called", eevp=90.0, race_type="G", seat_name=None):
    meta = {"officeID": office, "statePostal": st, "seatNum": seat, "raceTypeID": race_type,
            "raceCallStatus": status, "seatName": seat_name,
            "candidates": {c[0]: {"first": c[1], "last": c[2], "party": c[3]} for c in cands}}
    prog = {"eevp": eevp, "lastUpdated": "2026-11-04T06:00:00Z",
            "candidates": [{"candidateID": c[0], "voteCount": c[4], **({"winner": "X"} if c[5:] else {})}
                           for c in cands]}
    return {rid: meta}, {rid: prog}


def test_parse_party_totals_stand_ins_and_calls():
    m, p = {}, {}
    for a, b in [
        _ap("tx", "S", "TX", "2", [("1", "James", "Talarico", "Dem", 600, True), ("2", "Ken", "Paxton", "GOP", 400),
                                   ("3", "Ted", "Brown", "Lib", 50)]),
        # Nebraska: the independent stands in for the Democratic side; not called yet
        _ap("ne", "S", "NE", "2", [("1", "Pete", "Ricketts", "GOP", 510), ("2", "Dan", "Osborn", "NP", 490)],
            status="Too Early to Call", eevp=71.0),
        # Ohio's special
        _ap("oh", "S", "OH", "3", [("1", "Sherrod", "Brown", "Dem", 52, True), ("2", "Jon", "Husted", "GOP", 48)],
            race_type="W"),
        # a Louisiana-style ballot: two Democrats and a Republican, sent to a runoff
        _ap("la", "H", "LA", "5", [("1", "P", "Moore", "Dem", 30, True), ("2", "Q", "Smith", "Dem", 10),
                                   ("3", "G", "Firment", "GOP", 40, True)], status="Runoff", race_type="L"),
    ]:
        m |= a
        p |= b
    rows = results.parse(m, p, "2026-11-04T06:40:00Z").set_index("id")
    tx = rows.loc["2026-TX-SEN"]
    assert bool(tx["called"]) and tx["winner_party"] == "D" and tx["winner_name"] == "James Talarico"
    assert tx["dem_share_2p"] == pytest.approx(0.6) and tx["pct_counted"] == pytest.approx(0.9)
    ne = rows.loc["2026-NE-SEN"]
    assert not ne["called"] and pd.isna(ne["winner_party"])
    assert ne["dem_votes"] == 490 and ne["dem_share_2p"] == pytest.approx(0.49)
    assert rows.loc["2026-OH-SENS", "winner_name"] == "Sherrod Brown"
    la = rows.loc["LA-05"]
    assert not la["called"] and la["dem_votes"] == 40 and la["dem_share_2p"] == pytest.approx(0.5)
    # races absent from the feed are present and empty, never guessed
    assert len(rows) == 35 + 36 + 435
    assert pd.isna(rows.loc["2026-GA-SEN", "ap_race_id"]) and not rows.loc["2026-GA-SEN", "called"]


def test_parse_rejects_two_feed_races_for_one_v1_race():
    a, b = _ap("x1", "G", "TX", None, [("1", "A", "B", "Dem", 1)])
    c, d = _ap("x2", "G", "TX", None, [("1", "A", "B", "Dem", 1)])
    with pytest.raises(ValueError):
        results.parse(a | c, b | d, "t")

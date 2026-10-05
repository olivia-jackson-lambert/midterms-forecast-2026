"""Stage B PLAN item 6 follow-ons: specials, fundraising coding, race-score gates."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from forecast import backtest, special_elections, vote_model
from forecast.fundraising import fundraising_feature


def test_special_elections_2026_series_positive_dem_swing():
    df = special_elections.series(2026)
    assert len(df) >= 11
    assert {"FL-01", "VA-GOV", "AZ-07"} <= set(df["race"])
    s = special_elections.summary(2026)
    assert s["n"] == len(df)
    # Cycle average should be Dem-positive (Ballotpedia / published trackers).
    assert s["mean_pp"] > 0
    assert s["mean"] == pytest.approx(special_elections.swing_pp_to_logit(s["mean_pp"]))


def test_special_elections_cycle_constant_for_backtests():
    s18 = special_elections.summary(2018)
    assert s18["source"] == "cycle_constant"
    assert s18["mean_pp"] == pytest.approx(8.0)


def test_fundraising_feature_shape_without_network(tmp_path, monkeypatch):
    """With empty FEC cache and a stubbed fetch, feature column is well-formed zeros."""
    import forecast.fundraising as fec

    monkeypatch.setattr(fec, "OUT", tmp_path)
    monkeypatch.setattr(fec, "RAW_FEC", tmp_path / "fec")
    monkeypatch.setattr(fec, "_fetch_senate_totals",
                        lambda year: pd.DataFrame(columns=[
                            "election_year", "state_po", "name", "party", "receipts",
                            "candidate_id", "incumbent_challenge"]))
    feat = fundraising_feature(2026)
    assert len(feat) == len(vote_model.scheduled_races(2026))
    assert (feat["fundraising"] == 0).all()


def test_fundraising_feature_codes_log_ratio(tmp_path, monkeypatch):
    import forecast.fundraising as fec

    monkeypatch.setattr(fec, "OUT", tmp_path)
    monkeypatch.setattr(fec, "RAW_FEC", tmp_path / "fec")

    def fake(year):
        return pd.DataFrame([
            {"election_year": year, "state_po": "GA", "name": "D", "party": "DEM",
             "receipts": np.e ** 2, "candidate_id": "1", "incumbent_challenge": "I"},
            {"election_year": year, "state_po": "GA", "name": "R", "party": "REP",
             "receipts": 1.0, "candidate_id": "2", "incumbent_challenge": "C"},
            {"election_year": year, "state_po": "TX", "name": "D", "party": "DEM",
             "receipts": 1.0, "candidate_id": "3", "incumbent_challenge": "C"},
            {"election_year": year, "state_po": "TX", "name": "R", "party": "REP",
             "receipts": np.e ** 2, "candidate_id": "4", "incumbent_challenge": "I"},
        ])

    monkeypatch.setattr(fec, "_fetch_senate_totals", fake)
    feat = fundraising_feature(2026).set_index("race_id")
    # Opposite signs after z-score for GA (Dem-heavy) vs TX (Rep-heavy).
    assert feat.loc["2026-GA-SEN", "fundraising_raw"] == pytest.approx(2.0)
    assert feat.loc["2026-TX-SEN", "fundraising_raw"] == pytest.approx(-2.0)
    assert feat.loc["2026-GA-SEN", "fundraising"] > 0
    assert feat.loc["2026-TX-SEN", "fundraising"] < 0
    assert feat.loc["2026-AZ-GOV", "fundraising"] == 0.0


def test_race_score_gate_beats_lean_baseline():
    """Hand-built case: soft probs beat hard lean calls on Brier (PLAN publish gate)."""
    # Lean wrongly calls three toss-ups; model assigns ~0.55/0.45 and is closer.
    out = pd.DataFrame({
        "p_dem_win": [0.9, 0.1, 0.55, 0.45, 0.7, 0.3],
        "actual_share": [0.8, 0.2, 0.52, 0.48, 0.65, 0.35],
        "baseline": [0.9, 0.1, 0.51, 0.49, 0.51, 0.49],  # hard calls miss the close pairs' nuance
        "lo80": [0.7, 0.0, 0.4, 0.3, 0.5, 0.15],
        "hi80": [1.0, 0.3, 0.7, 0.6, 0.85, 0.5],
    })
    # Make lean baseline worse: flip the close races' lean calls opposite of truth.
    out.loc[2, "baseline"] = 0.4   # lean says R, Dem wins
    out.loc[3, "baseline"] = 0.6   # lean says D, Rep wins
    s = backtest.score_races(out)
    assert s["n_races"] == 6
    assert s["beats_lean_baseline"] is True
    assert s["brier"] < s["baseline_brier"]


def test_ridge_fit_method_tag():
    rng = np.random.default_rng(1)
    f = vote_model.frame(2026, lean=pd.Series(
        {st: 0.5 for st in vote_model.scheduled_races(2026)["state_po"].unique()}))
    f = f.head(25).copy()
    f["actual_share"] = np.clip(f["baseline"] + rng.normal(0, 0.04, len(f)), 0.1, 0.9)
    f["incumbency"] = rng.choice([-1.0, 0.0, 1.0], len(f))
    f["fundraising"] = rng.normal(0, 1, len(f))
    # Force ridge path.
    import os
    os.environ["STAGE_B_PYMC"] = "0"
    try:
        params = vote_model.fit([f], draws=30, rng=rng)
    finally:
        os.environ.pop("STAGE_B_PYMC", None)
    assert params["fit_method"] == "ridge"
    assert params["n_train"] == 25

"""Unit checks on Stage B vote-share model and correlated race simulation.

Uses synthetic leans / fundamentals — no processed Stage B inputs required.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from forecast import simulate, vote_model
from forecast.vote_model import RACE_FEATURES, REGION, prior_params, scheduled_races


def _lean_for(year: int) -> pd.Series:
    """Deterministic fake presidential leans for every state on the schedule."""
    races = scheduled_races(year)
    states = sorted(races["state_po"].unique())
    rng = np.random.default_rng(year)
    return pd.Series(rng.uniform(0.35, 0.65, len(states)), index=states, name="pres_lean")


def _frame(year: int = 2026, n_override: int | None = None) -> pd.DataFrame:
    lean = _lean_for(year)
    f = vote_model.frame(year, lean=lean)
    if n_override is not None:
        f = f.head(n_override).copy()
    return f


def test_scheduled_races_2026_covers_senate_and_governor():
    r = scheduled_races(2026)
    assert set(r["office"]) == {"SEN", "GOV"}
    assert (r["office"] == "GOV").sum() == 36
    # Class 2 + FL/OH specials (see features.SENATE[2026])
    assert (r["office"] == "SEN").sum() == len(r.query("office == 'SEN'"))
    assert r.query("special")["state_po"].tolist() == ["FL", "OH"]
    assert r["race_id"].is_unique


def test_frame_uses_injected_lean_and_stub_fundamentals():
    lean = _lean_for(2026)
    f = vote_model.frame(2026, lean=lean)
    assert f["baseline"].notna().all()
    assert set(RACE_FEATURES).issubset(f.columns)
    assert (f["incumbency"] == 0).all() and (f["fundraising"] == 0).all()
    assert f["region"].isin(REGION.values()).all()
    # Baseline matches the injected lean.
    assert np.allclose(f["baseline"], f["state_po"].map(lean))


def test_national_swing_falls_back_to_prior(tmp_path):
    s = vote_model.national_swing(2026, source=tmp_path / "missing.parquet")
    assert s["source"] == "prior"
    assert s["sd"] > 0


def test_national_swing_reads_parquet(tmp_path):
    path = tmp_path / "generic_ballot_2026.parquet"
    pd.DataFrame({"mean": [0.02], "sd": [0.025]}).to_parquet(path)
    s = vote_model.national_swing(2026, source=path)
    assert s["mean"] == pytest.approx(0.02)
    assert s["sd"] == pytest.approx(0.025)
    assert s["source"] == str(path)


def test_prior_fit_and_ridge_fit_with_synthetic_actuals():
    rng = np.random.default_rng(0)
    prior = vote_model.fit(None, draws=40, rng=rng)
    assert prior["n_train"] == 0
    assert prior["gamma"].shape == (40, len(RACE_FEATURES))

    f = _frame(2026, n_override=30)
    f["actual_share"] = np.clip(f["baseline"] + rng.normal(0, 0.03, len(f)), 0.05, 0.95)
    # Non-zero features so the ridge path is exercised.
    f["incumbency"] = rng.choice([-1.0, 0.0, 1.0], len(f))
    f["fundraising"] = rng.normal(0, 1, len(f))
    post = vote_model.fit([f], draws=50, rng=rng)
    assert post["n_train"] == 30
    assert post["summary"] is not None
    assert post["gamma"].shape == (50, len(RACE_FEATURES))


def test_simulate_shape_bounds_and_correlation():
    f = _frame(2026, n_override=20)
    # Force two races into the same region so regional correlation is visible.
    f = f.copy()
    f.iloc[0, f.columns.get_loc("region")] = "West"
    f.iloc[1, f.columns.get_loc("region")] = "West"
    f.iloc[0, f.columns.get_loc("state_po")] = "CA"
    f.iloc[1, f.columns.get_loc("state_po")] = "OR"
    rng = np.random.default_rng(3)
    params = prior_params(80, rng)
    # Inflate shared error so pairwise corr is clearly positive.
    params["sigma_nat"] = np.full(80, 0.20)
    params["sigma_region"] = np.full(80, 0.10)
    params["sigma_state"] = np.full(80, 0.01)
    params["sigma_race"] = np.full(80, 0.01)
    swing = {"mean": 0.0, "sd": 0.0}  # pin swing; correlation comes from shared errors
    sims = simulate.simulate(f, params, swing, rng, n_sims=4000,
                             swing_values=np.zeros(4000))
    assert sims.shape == (4000, len(f))
    assert ((sims > 0) & (sims < 1)).all()
    corr = simulate.pairwise_correlation(sims, 0, 1)
    assert corr > 0.3


def test_independent_noise_has_low_correlation():
    f = _frame(2026, n_override=12)
    rng = np.random.default_rng(4)
    params = prior_params(60, rng)
    params["sigma_nat"] = np.full(60, 1e-6)
    params["sigma_region"] = np.full(60, 1e-6)
    params["sigma_state"] = np.full(60, 1e-6)
    params["sigma_race"] = np.full(60, 0.15)
    sims = simulate.simulate(f, params, {"mean": 0.0, "sd": 0.0}, rng, n_sims=3000,
                             swing_values=np.zeros(3000))
    corr = simulate.pairwise_correlation(sims, 0, 1)
    assert abs(corr) < 0.15


def test_summarise_and_seat_summary():
    f = _frame(2026, n_override=15)
    rng = np.random.default_rng(5)
    params = prior_params(40, rng)
    sims = simulate.simulate(f, params, {"mean": 0.0, "sd": 0.02}, rng, n_sims=500)
    out = vote_model.summarise(f, sims)
    assert len(out) == len(f)
    assert out["p_dem_win"].between(0, 1).all()
    assert (out["lo80"] <= out["median"]).all() and (out["median"] <= out["hi80"]).all()
    seats = simulate.seat_summary(f, sims)
    assert set(seats["office"]).issubset({"SEN", "GOV"})
    assert (seats["lo80"] <= seats["median"]).all()


def test_run_with_mocks_no_data_dir(tmp_path, monkeypatch):
    """vote_model.run should work without processed parquet files when lean is injected."""
    monkeypatch.setattr(vote_model, "OUT", tmp_path)
    lean = _lean_for(2026)
    out, info = vote_model.run(2026, train_years=None, sims=200, draws=30, lean=lean)
    assert len(out) == len(scheduled_races(2026))
    assert "seats" in info and info["params"]["n_train"] == 0
    assert out["p_dem_win"].between(0, 1).all()

"""Unit checks on Stage B vote-share model and correlated race simulation.

Uses synthetic leans / fundamentals where needed — no processed Stage B inputs required
for the core path. Wiring tests cover generic-ballot snapshot → national_swing and
races.py → incumbency.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from forecast import simulate, vote_model
from forecast.races import GOV_OPEN, SENATE_OPEN
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


def test_frame_uses_injected_lean_and_races_incumbency(tmp_path, monkeypatch):
    monkeypatch.setattr(vote_model, "OUT", tmp_path)  # no FEC cache → fundraising zeros
    lean = _lean_for(2026)
    f = vote_model.frame(2026, lean=lean)
    assert f["baseline"].notna().all()
    assert set(RACE_FEATURES).issubset(f.columns)
    assert (f["fundraising"] == 0).all()          # FEC cache absent
    assert f["region"].isin(REGION.values()).all()
    assert np.allclose(f["baseline"], f["state_po"].map(lean))
    # Open seats from races.py → incumbency 0; sitting Dem/Rep coded ±1.
    open_sen = f["office"].eq("SEN") & f["state_po"].isin(SENATE_OPEN)
    open_gov = f["office"].eq("GOV") & f["state_po"].isin(GOV_OPEN)
    assert (f.loc[open_sen | open_gov, "incumbency"] == 0).all()
    assert (f.loc[open_sen | open_gov, "open_seat"]).all()
    sitting = f.loc[~(open_sen | open_gov)]
    assert sitting["incumbency"].isin([-1.0, 1.0]).all()


def test_race_fundamentals_2026_codes_parties():
    fund = vote_model.race_fundamentals(2026)
    assert set(fund.columns) >= {"race_id", "incumbency", "fundraising", "open_seat"}
    # AK Senate: Dan Sullivan (R) running → -1; MI Senate open → 0; AZ governor Hobbs (D) → +1.
    by_id = fund.set_index("race_id")["incumbency"]
    assert by_id["2026-AK-SEN"] == -1.0
    assert by_id["2026-MI-SEN"] == 0.0
    assert by_id["2026-AZ-GOV"] == 1.0
    assert by_id["2026-FL-SENS"] == -1.0   # Moody (R) special


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


def test_national_swing_from_generic_ballot_snapshot(tmp_path, monkeypatch):
    """Cached snapshot → logit(gb) − logit(pres) when panel exists; else vs even."""
    monkeypatch.setattr(vote_model, "OUT", tmp_path)
    # No county_panel → vs_even path.
    snaps = pd.DataFrame([
        {"year": 2026, "dem": 48.0, "rep": 42.0, "dem_2p": 48 / 90, "margin": 6.0, "n_sources": 3,
         "sources": "A, B, C"},
    ])
    snaps.to_parquet(tmp_path / "generic_ballot_snapshot.parquet", index=False)
    detail = pd.DataFrame({
        "year": [2026, 2026, 2026],
        "source": ["A", "B", "C"],
        "dem": [47.0, 48.0, 49.0],
        "rep": [43.0, 42.0, 41.0],
        "dem_2p": [47 / 90, 48 / 90, 49 / 90],
        "margin": [4.0, 6.0, 8.0],
    })
    detail.to_parquet(tmp_path / "generic_ballot_aggregates.parquet", index=False)
    s = vote_model.national_swing(2026, blend_specials=False)
    assert s["source"] == "generic_ballot.snapshot/vs_even"
    assert s["mean"] == pytest.approx(float(vote_model.logit(48 / 90)))
    assert s["sd"] >= vote_model.SWING_PRIOR[2026]["sd"]
    assert s["n_sources"] == 3


def test_national_swing_blends_special_elections(tmp_path, monkeypatch):
    monkeypatch.setattr(vote_model, "OUT", tmp_path)
    pd.DataFrame([{
        "year": 2026, "dem": 50.0, "rep": 50.0, "dem_2p": 0.5, "margin": 0.0,
        "n_sources": 1, "sources": "X",
    }]).to_parquet(tmp_path / "generic_ballot_snapshot.parquet", index=False)
    s = vote_model.national_swing(2026, blend_specials=True)
    assert "special_elections" in s["source"]
    assert "special_mean_pp" in s and s["special_n"] >= 10
    # Blended mean sits between GB (≈0 vs even) and special mean.
    from forecast.special_elections import summary
    spec = summary(2026)
    assert min(0.0, spec["mean"]) <= s["mean"] <= max(0.0, spec["mean"]) or \
        abs(s["mean"] - 0.5 * spec["mean"]) < 1e-9


def test_national_swing_subtracts_presidential_national(tmp_path, monkeypatch):
    monkeypatch.setattr(vote_model, "OUT", tmp_path)
    # Tiny fake panel: national dem_2p = 0.50 in 2024.
    panel = pd.DataFrame({
        "year": [2024, 2024],
        "state_po": ["CA", "TX"],
        "dem": [100.0, 50.0],
        "rep": [100.0, 50.0],
    })
    panel.to_parquet(tmp_path / "county_panel.parquet", index=False)
    pd.DataFrame([{
        "year": 2026, "dem": 55.0, "rep": 45.0, "dem_2p": 0.55, "margin": 10.0,
        "n_sources": 1, "sources": "X",
    }]).to_parquet(tmp_path / "generic_ballot_snapshot.parquet", index=False)
    s = vote_model.national_swing(2026, blend_specials=False)
    assert s["source"] == "generic_ballot.snapshot/vs_presidential"
    assert s["mean"] == pytest.approx(float(vote_model.logit(0.55) - vote_model.logit(0.5)))


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
    assert abs(corr) < 0.20


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
    # Empty OUT → prior GB path, then blended with curated specials.
    assert "prior" in info["swing"]["source"] or "generic_ballot" in info["swing"]["source"]

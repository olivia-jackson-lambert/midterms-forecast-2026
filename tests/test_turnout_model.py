"""Unit checks on the turnout simulation, with synthetic inputs (no data needed)."""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pymc")
from forecast.features import DEMOGRAPHICS, STATE_FEATURES  # noqa: E402
from forecast.turnout_model import simulate  # noqa: E402


def _inputs(n=200, draws=50, seed=0):
    rng = np.random.default_rng(seed)
    f = pd.DataFrame(rng.standard_normal((n, len(DEMOGRAPHICS))), columns=DEMOGRAPHICS)
    for c in STATE_FEATURES:
        f[c] = rng.integers(-1, 2, n).astype(float)
    f["state_po"] = rng.choice(["AA", "BB", "CC"], n)
    f["anchor"] = rng.normal(-0.2, 0.3, n)
    f["pres_minus_anchor"] = rng.normal(0.6, 0.2, n)
    f["cvap"] = rng.integers(1_000, 500_000, n).astype(float)
    f["out_party_lean"] = rng.normal(0, 0.1, n)
    p = {"gamma": rng.normal(0, 0.05, (draws, len(STATE_FEATURES))), "beta": rng.normal(0, 0.05, (draws, len(DEMOGRAPHICS))),
         "lam": rng.normal(0.5, 0.05, draws), "rho": rng.normal(-0.2, 0.02, draws), "tau": np.full(draws, 0.03),
         "sigma_state": np.full(draws, 0.15), "sigma": np.full(draws, 0.08), "kappa": np.full(draws, 0.1),
         "nu": np.full(draws, 6.0), "phi": np.full(draws, 0.3), "anchor_mean": -0.2}
    return f, p


def test_simulation_hits_national_draws():
    f, p = _inputs()
    rng = np.random.default_rng(1)
    nat = rng.uniform(0.40, 0.55, 300)
    sims = simulate(f, p, nat, rng, cvap_ratio=1.0)
    assert sims.shape == (300, len(f))
    assert ((sims > 0) & (sims < 1)).all()
    w = f["cvap"].to_numpy()
    assert np.allclose((sims * w).sum(1) / w.sum(), nat, atol=1e-4)


def test_cvap_ratio_scales_the_target():
    f, p = _inputs()
    rng = np.random.default_rng(2)
    nat = np.full(100, 0.45)
    sims = simulate(f, p, nat, rng, cvap_ratio=1.02)
    w = f["cvap"].to_numpy()
    assert np.allclose((sims * w).sum(1) / w.sum(), 0.459, atol=1e-4)


def test_state_offset_preserves_national_total():
    f, p = _inputs(n=120, draws=40, seed=3)
    rng = np.random.default_rng(4)
    nat = np.full(80, 0.48)
    off = pd.Series({"AA": 0.25, "BB": -0.20, "CC": 0.0})
    sims = simulate(f, p, nat, rng, cvap_ratio=1.0, state_offset=off)
    w = f["cvap"].to_numpy()
    assert np.allclose((sims * w).sum(1) / w.sum(), nat, atol=1e-4)
    # AA counties should sit above BB after a strong positive offset.
    aa = f["state_po"].eq("AA").to_numpy()
    bb = f["state_po"].eq("BB").to_numpy()
    assert sims[:, aa].mean() > sims[:, bb].mean()

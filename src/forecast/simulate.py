"""Correlated simulation of Stage B race outcomes (and helpers for joint draws).

Each simulation draw shares a national error and a regional error across races, so
win probabilities and seat totals are not the product of independent race margins —
the usual public-forecast mistake called out in PLAN.md.

    share_logit_r,s = logit(baseline_r) + swing_s + X_r . gamma_s
                      + sigma_state * u_state
                      + sigma_nat * e_nat_s
                      + sigma_region * e_region[region(r), s]
                      + sigma_race * e_race_r,s

Stage A county turnout simulation stays in `turnout_model.simulate`; this module is
the race-level joint draw used by `vote_model.run`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.special import expit, logit as _logit

# Local copies avoid an import cycle with vote_model (which calls into this module).
RACE_FEATURES = ["incumbency", "fundraising"]
REGIONS = ("Northeast", "Midwest", "South", "West")
SIMS = 20_000


def _logit_share(p, eps: float = 1e-4):
    return _logit(np.clip(p, eps, 1 - eps))


def swing_draws(swing: dict, n_sims: int, rng: np.random.Generator) -> np.ndarray:
    """Draws of national Democratic swing on the logit scale."""
    return rng.normal(swing["mean"], swing["sd"], n_sims)


def correlated_errors(n_sims: int, n_races: int, state_idx: np.ndarray,
                      region_idx: np.ndarray, n_states: int, n_regions: int,
                      params: dict, pick: np.ndarray,
                      rng: np.random.Generator) -> np.ndarray:
    """sims x races additive logit errors with national + regional + state + race terms."""
    m = n_sims
    e_nat = params["sigma_nat"][pick, None] * rng.standard_normal((m, 1))
    e_reg = params["sigma_region"][pick, None] * rng.standard_normal((m, n_regions))
    e_state = params["sigma_state"][pick, None] * rng.standard_normal((m, n_states))
    e_race = params["sigma_race"][pick, None] * rng.standard_normal((m, n_races))
    return e_nat + e_reg[:, region_idx] + e_state[:, state_idx] + e_race


def simulate(f: pd.DataFrame, params: dict, swing: dict,
             rng: np.random.Generator, n_sims: int = SIMS,
             swing_values: np.ndarray | None = None) -> np.ndarray:
    """Democratic two-party share draws (sims x races) for race frame `f`.

    Pass `swing_values` to pin or externally supply the national swing draws (length
    n_sims); otherwise they are drawn from `swing`'s mean/sd.
    """
    n = len(f)
    base = f["baseline"].to_numpy(dtype=float)
    if np.isnan(base).any():
        raise ValueError("baseline has NaNs; supply lean to vote_model.frame / simulate")
    X = f[RACE_FEATURES].fillna(0).to_numpy(dtype=float)
    state_idx, _ = pd.factorize(f["state_po"])
    region_idx, region_names = pd.factorize(f["region"])
    # Keep a stable region axis even if a region is missing from this frame.
    n_regions = max(len(region_names), len(REGIONS))
    n_post = len(params["sigma_nat"])
    pick = rng.integers(0, n_post, n_sims)
    sw = swing_values if swing_values is not None else swing_draws(swing, n_sims, rng)

    out = np.empty((n_sims, n), dtype=np.float32)
    # Chunk to keep peak memory modest at 20k sims.
    for start in range(0, n_sims, 2000):
        sl = slice(start, min(start + 2000, n_sims))
        p = pick[sl]
        m = len(p)
        lin = _logit_share(base)[None, :] + sw[sl, None] + (X @ params["gamma"][p].T).T
        lin = lin + correlated_errors(m, n, state_idx, region_idx, state_idx.max() + 1,
                                      n_regions, params, p, rng)
        out[sl] = expit(lin)
    return out


def seat_summary(f: pd.DataFrame, sims: np.ndarray) -> pd.DataFrame:
    """Seat-count distributions for Senate and governor (Dem wins per simulation)."""
    rows = []
    for office, idx in f.groupby("office").indices.items():
        wins = (sims[:, idx] > 0.5).sum(axis=1)
        q = np.quantile(wins, [0.1, 0.5, 0.9])
        rows.append({"office": office, "n_races": len(idx),
                     "lo80": q[0], "median": q[1], "hi80": q[2],
                     "mean": wins.mean()})
    return pd.DataFrame(rows)


def pairwise_correlation(sims: np.ndarray, a: int, b: int) -> float:
    """Pearson correlation of two races' share draws (for tests / diagnostics)."""
    return float(np.corrcoef(sims[:, a], sims[:, b])[0, 1])

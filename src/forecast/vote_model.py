"""Stage B: race-level two-party Democratic share.

On the probability (share) scale, each race is

    share_r = inv_logit( logit(baseline_r) + national_swing
                         + gamma . race_features_r + state_effect
                         + national_error + regional_error + race_noise ),

where:
- baseline_r is the state's recent presidential two-party lean, optionally reweighted
  by Stage A county turnout draws;
- national_swing comes from the generic-ballot average (and later special-election
  over-performance), with its own uncertainty;
- race_features are incumbency and fundraising (stubs until Stage B inputs land);
- errors share a national term and a Census-region term so simulations are correlated.

This module is a working skeleton: prior-based parameters and mock-friendly frames so
tests and wiring run before generic-ballot / race-fundamentals tables exist.

    python -m forecast.vote_model     # prior-based 2026 race table (needs race frame inputs)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit, logit as _logit

from .features import GOVERNOR, SENATE
from .ingest import OUT

SIMS = 20_000
SEED = 2026
RACE_FEATURES = ["incumbency", "fundraising"]

# Census regions for correlated regional errors (DC treated as South).
REGION = {
    "CT": "Northeast", "ME": "Northeast", "MA": "Northeast", "NH": "Northeast",
    "RI": "Northeast", "VT": "Northeast", "NJ": "Northeast", "NY": "Northeast",
    "PA": "Northeast",
    "IL": "Midwest", "IN": "Midwest", "MI": "Midwest", "OH": "Midwest", "WI": "Midwest",
    "IA": "Midwest", "KS": "Midwest", "MN": "Midwest", "MO": "Midwest", "NE": "Midwest",
    "ND": "Midwest", "SD": "Midwest",
    "DE": "South", "FL": "South", "GA": "South", "MD": "South", "NC": "South",
    "SC": "South", "VA": "South", "WV": "South", "AL": "South", "KY": "South",
    "MS": "South", "TN": "South", "AR": "South", "LA": "South", "OK": "South",
    "TX": "South", "DC": "South",
    "AZ": "West", "CO": "West", "ID": "West", "MT": "West", "NV": "West",
    "NM": "West", "UT": "West", "WY": "West", "AK": "West", "CA": "West",
    "HI": "West", "OR": "West", "WA": "West",
}
REGIONS = ("Northeast", "Midwest", "South", "West")

# Placeholder national-swing priors until generic-ballot rebuild lands (Stage B inputs).
# Mean 0 = no national shift from the presidential baseline; sd is wide on purpose.
SWING_PRIOR = {2018: {"mean": 0.04, "sd": 0.03},   # D+ midterm environment (illustrative)
               2022: {"mean": -0.02, "sd": 0.03},
               2026: {"mean": 0.00, "sd": 0.04}}


def logit(p: np.ndarray | float, eps: float = 1e-4) -> np.ndarray | float:
    p = np.clip(p, eps, 1 - eps)
    return _logit(p)


# --------------------------------------------------------------------------- races
def scheduled_races(year: int) -> pd.DataFrame:
    """Senate and governor races on the ballot in `year`, from the Stage A schedule lists.

    Specials: Florida and Ohio Senate seats in 2026 are already in SENATE[2026]; they are
    flagged here so incumbency / fundraising tables can attach later. Historical specials
    are not reconstructed in this scaffold.
    """
    rows = []
    for office, states in (("SEN", SENATE[year].split()), ("GOV", GOVERNOR[year].split())):
        for st in states:
            special = office == "SEN" and year == 2026 and st in ("FL", "OH")
            # FL and OH also appear once for the regular Class-2 cycle; keep a single row
            # per (state, office, special). Regular Class-2 still covers FL/OH via the list,
            # so mark only the explicit specials once — both appear in SENATE[2026] once each.
            rows.append({"year": year, "state_po": st, "office": office, "special": special,
                         "race_id": f"{year}-{st}-{office}{'S' if special else ''}"})
    return pd.DataFrame(rows)


def race_fundamentals(year: int) -> pd.DataFrame:
    """Incumbency and fundraising by race.

    Stub: zeros until Ballotpedia / FEC tables are wired. Shape matches what `frame` expects
    so callers can merge real columns later without changing the model interface.
    """
    path = OUT / f"race_fundamentals_{year}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    r = scheduled_races(year)
    r["incumbency"] = 0.0          # +1 Dem incumbent, -1 Rep, 0 open
    r["fundraising"] = 0.0         # standardized log Dem/Rep receipts (stub)
    return r[["race_id", "incumbency", "fundraising"]]


def presidential_lean(year: int) -> pd.Series:
    """State two-party Democratic share in the last presidential election (year - 2).

    Reads county_panel when present; otherwise returns an empty series so callers can
    inject a lean column. Turnout-weighted baseline belongs in `baseline`.
    """
    panel = OUT / "county_panel.parquet"
    if not panel.exists():
        return pd.Series(dtype=float, name="pres_lean")
    p = pd.read_parquet(panel)
    p = p[p["year"] == year - 2]
    g = p.groupby("state_po")[["dem", "rep"]].sum()
    lean = g["dem"] / (g["dem"] + g["rep"])
    lean.name = "pres_lean"
    return lean


def baseline(races: pd.DataFrame, lean: pd.Series | None = None,
             turnout_weights: pd.DataFrame | None = None) -> pd.Series:
    """Race baseline = state presidential lean (optionally turnout-reweighted).

    `turnout_weights` (optional): columns unit_fips, state_po, weight — e.g. Stage A
    median turnout * CVAP. When omitted, the lean series is used as-is (already statewide).
    """
    if lean is None:
        lean = presidential_lean(int(races["year"].iloc[0]))
    if turnout_weights is not None and lean is not None and not lean.empty:
        # Re-express lean with turnout-weighted county votes when a county lean table is
        # supplied as turnout_weights with dem/rep columns; otherwise state lean stands.
        if {"dem", "rep"}.issubset(turnout_weights.columns):
            w = turnout_weights.copy()
            w["w"] = w.get("weight", 1.0)
            g = w.groupby("state_po").apply(
                lambda d: (d["dem"] * d["w"]).sum() / ((d["dem"] + d["rep"]) * d["w"]).sum(),
                include_groups=False)
            lean = g.rename("pres_lean")
    base = races["state_po"].map(lean)
    return base.rename("baseline")


def national_swing(year: int, source: Path | None = None) -> dict:
    """Mean and sd of the national Democratic swing (logit scale).

    Reads `generic_ballot_{year}.parquet` (columns mean, sd) when Stage B inputs land;
    otherwise uses SWING_PRIOR placeholders.
    """
    path = source or (OUT / f"generic_ballot_{year}.parquet")
    if path.exists():
        row = pd.read_parquet(path).iloc[0]
        return {"mean": float(row["mean"]), "sd": float(row["sd"]), "source": str(path)}
    prior = SWING_PRIOR.get(year, {"mean": 0.0, "sd": 0.04})
    return {**prior, "source": "prior"}


# --------------------------------------------------------------------------- frames
def frame(year: int, lean: pd.Series | None = None,
          fundamentals: pd.DataFrame | None = None,
          turnout_weights: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per race for target year, with baseline and race features.

    Everything needed for Stage B simulation except posterior parameters. Pass `lean` and
    `fundamentals` in tests to avoid reading processed data.
    """
    races = scheduled_races(year)
    fund = fundamentals if fundamentals is not None else race_fundamentals(year)
    f = races.merge(fund, on="race_id", how="left")
    for c in RACE_FEATURES:
        if c not in f:
            f[c] = 0.0
        f[c] = f[c].fillna(0.0)
    f["baseline"] = baseline(f, lean=lean, turnout_weights=turnout_weights).values
    f["region"] = f["state_po"].map(REGION).fillna("South")
    f["year"] = year
    return f


# --------------------------------------------------------------------------- fit
def prior_params(draws: int = 1000, rng: np.random.Generator | None = None) -> dict:
    """Draw parameters from weakly informative priors (no race training data required)."""
    rng = rng or np.random.default_rng(SEED)
    return {
        "gamma": rng.normal(0, 0.15, size=(draws, len(RACE_FEATURES))),
        "sigma_state": np.abs(rng.normal(0, 0.05, draws)) + 0.02,
        "sigma_nat": np.abs(rng.normal(0, 0.04, draws)) + 0.02,
        "sigma_region": np.abs(rng.normal(0, 0.03, draws)) + 0.01,
        "sigma_race": np.abs(rng.normal(0, 0.05, draws)) + 0.02,
        "n_train": 0,
        "summary": None,
    }


def fit(train: list[pd.DataFrame] | None = None, draws: int = 1000,
        rng: np.random.Generator | None = None) -> dict:
    """Posterior (or prior) draws of Stage B parameters.

    With no usable training frames, returns `prior_params`. A PyMC hierarchical fit will
    replace this path once race outcomes and fundamentals for 2018/2022 are wired; the
    returned dict keys stay the same either way.
    """
    rng = rng or np.random.default_rng(SEED)
    if not train:
        return prior_params(draws, rng)

    d = pd.concat(train, ignore_index=True)
    need = ["baseline", "actual_share", *RACE_FEATURES]
    if not all(c in d.columns for c in need) or d["actual_share"].notna().sum() < 5:
        return prior_params(draws, rng)

    # Lightweight ridge update on the logit residual (scaffold stand-in for PyMC).
    # residual = logit(actual) - logit(baseline) ~ gamma . X + noise
    ok = d["actual_share"].notna() & d["baseline"].notna()
    y = logit(d.loc[ok, "actual_share"].to_numpy()) - logit(d.loc[ok, "baseline"].to_numpy())
    X = d.loc[ok, RACE_FEATURES].to_numpy()
    # Prior N(0, 0.15); observation variance ~0.08^2
    prior_prec = 1 / 0.15**2
    obs_var = 0.08**2
    xtx = X.T @ X / obs_var + prior_prec * np.eye(len(RACE_FEATURES))
    xty = X.T @ y / obs_var
    mean = np.linalg.solve(xtx, xty)
    cov = np.linalg.inv(xtx)
    gamma = rng.multivariate_normal(mean, cov, size=draws)
    params = prior_params(draws, rng)
    params["gamma"] = gamma
    params["n_train"] = int(ok.sum())
    params["summary"] = pd.DataFrame({"mean": mean, "sd": np.sqrt(np.diag(cov))},
                                     index=RACE_FEATURES)
    return params


# --------------------------------------------------------------------------- summarise / run
def summarise(f: pd.DataFrame, sims: np.ndarray) -> pd.DataFrame:
    """Per-race share quantiles and Democratic win probability."""
    q = np.quantile(sims, [0.1, 0.5, 0.9], axis=0)
    return pd.DataFrame({
        "race_id": f["race_id"].values,
        "year": f["year"].values,
        "state_po": f["state_po"].values,
        "office": f["office"].values,
        "special": f["special"].values,
        "baseline": f["baseline"].values,
        "lo80": q[0],
        "median": q[1],
        "hi80": q[2],
        "p_dem_win": (sims > 0.5).mean(axis=0),
    })


def run(target: int, train_years: list[int] | None = None, sims: int = SIMS,
        draws: int = 1000, params: dict | None = None,
        lean: pd.Series | None = None,
        fundamentals: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Fit (unless params given) and simulate all races in `target`."""
    from . import simulate as sim

    rng = np.random.default_rng(SEED + target)
    train = None
    if train_years:
        train = []
        for y in train_years:
            try:
                train.append(frame(y))
            except Exception:
                continue
            if "actual_share" not in train[-1].columns:
                # Attach actuals from processed midterm results when available.
                train[-1] = _attach_actuals(train[-1], y)
    params = params or fit(train, draws=draws, rng=rng)
    f = frame(target, lean=lean, fundamentals=fundamentals)
    if f["baseline"].isna().any() and lean is None:
        # No panel on disk: leave baseline NaN callers must supply lean in tests.
        pass
    swing = national_swing(target)
    sims_ = sim.simulate(f, params, swing, rng, n_sims=sims)
    out = summarise(f, sims_)
    seats = sim.seat_summary(f, sims_)
    return out, {"params": params, "swing": swing, "seats": seats, "sims": sims_}


def _attach_actuals(f: pd.DataFrame, year: int) -> pd.DataFrame:
    path = OUT / "county_midterm_results.parquet"
    if not path.exists():
        f["actual_share"] = np.nan
        return f
    r = pd.read_parquet(path)
    r = r[(r["year"] == year) & (r["race"].isin(["SEN", "GOV"]))]
    g = r.groupby(["state_po", "race", "special"], as_index=False)[["dem", "rep"]].sum()
    g["actual_share"] = g["dem"] / (g["dem"] + g["rep"])
    g = g.rename(columns={"race": "office"})
    return f.merge(g[["state_po", "office", "special", "actual_share"]],
                   on=["state_po", "office", "special"], how="left")


def main() -> None:
    # Prior-based 2026 table; real lean from county_panel when ingest has been run.
    lean = presidential_lean(2026)
    if lean.empty:
        print("no county_panel yet; writing schedule-only frame with baseline=NaN")
    out, info = run(2026, train_years=[2018, 2022], lean=None if lean.empty else lean)
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT / "vote_share_2026.parquet", index=False)
    info["seats"].to_parquet(OUT / "seat_counts_2026.parquet", index=False)
    print("races:", len(out), "| swing source:", info["swing"]["source"])
    print(out[["office", "state_po", "median", "p_dem_win"]].head(10).to_string(index=False))
    print(info["seats"].to_string(index=False))


if __name__ == "__main__":
    main()

"""Stage B: race-level two-party Democratic share.

On the probability (share) scale, each race is

    share_r = inv_logit( logit(baseline_r) + national_swing
                         + gamma . race_features_r + state_effect
                         + national_error + regional_error + race_noise ),

where:
- baseline_r is the state's recent presidential two-party lean, optionally reweighted
  by Stage A county turnout draws;
- national_swing blends the generic-ballot average with special-election over-performance;
- race_features are incumbency (from `races.py` for 2026) and FEC Senate fundraising;
- errors share a national term and a Census-region term so simulations are correlated.

PLAN §10 item 6: vote-share model with correlated simulation and 2018/2022 race backtests.
Fit uses PyMC when installed (`STAGE_B_PYMC=0` forces the ridge stand-in).

    python -m forecast.vote_model
"""
from __future__ import annotations

import os
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

# Fallback when generic-ballot snapshot / parquet is unavailable. Mean is Democratic
# advantage on the logit scale relative to the last presidential national lean.
SWING_PRIOR = {2018: {"mean": 0.04, "sd": 0.03},
               2022: {"mean": -0.02, "sd": 0.03},
               2026: {"mean": 0.00, "sd": 0.04}}


def logit(p: np.ndarray | float, eps: float = 1e-4) -> np.ndarray | float:
    p = np.clip(p, eps, 1 - eps)
    return _logit(p)


# --------------------------------------------------------------------------- races
def scheduled_races(year: int) -> pd.DataFrame:
    """Senate and governor races on the ballot in `year`, from the Stage A schedule lists.

    Specials: Florida and Ohio Senate seats in 2026 are already in SENATE[2026]; they are
    flagged here so incumbency / fundraising tables can attach. Historical specials
    are not reconstructed yet (PLAN race-backtest work).
    """
    rows = []
    for office, states in (("SEN", SENATE[year].split()), ("GOV", GOVERNOR[year].split())):
        for st in states:
            special = office == "SEN" and year == 2026 and st in ("FL", "OH")
            rows.append({"year": year, "state_po": st, "office": office, "special": special,
                         "race_id": f"{year}-{st}-{office}{'S' if special else ''}"})
    return pd.DataFrame(rows)


def _incumbency_code(open_seat: pd.Series, incumbent_party: pd.Series) -> pd.Series:
    """+1 Dem (or Dem-caucusing) incumbent, -1 Rep, 0 open / unknown."""
    open_ = open_seat.fillna(False).astype(bool)
    party = incumbent_party.fillna("").astype(str)
    code = np.where(open_, 0.0,
                    np.where(party.isin(["D", "I"]), 1.0,
                             np.where(party.eq("R"), -1.0, 0.0)))
    return pd.Series(code, index=open_seat.index, dtype=float)


def race_fundamentals(year: int) -> pd.DataFrame:
    """Incumbency and fundraising by race.

    Prefer `race_fundamentals_{year}.parquet` when present. Otherwise:
    - 2026 incumbency / open seats from `forecast.races`
    - Senate fundraising from OpenFEC (`forecast.fundraising`) when reachable / cached
    Governors have no FEC coverage — fundraising stays 0 for GOV.
    """
    path = OUT / f"race_fundamentals_{year}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    r = scheduled_races(year)
    r["incumbency"] = 0.0
    r["fundraising"] = 0.0
    r["open_seat"] = False
    if year == 2026:
        from . import races as race_meta
        meta = race_meta.races(2026).rename(columns={"race": "office"})
        m = r.drop(columns=["open_seat"]).merge(
            meta[["state_po", "office", "special", "open_seat", "incumbent_party"]],
            on=["state_po", "office", "special"], how="left")
        r["open_seat"] = m["open_seat"].fillna(False).astype(bool)
        r["incumbency"] = _incumbency_code(r["open_seat"], m["incumbent_party"])
    # FEC Senate fundraising: only from cache written by `python -m forecast.fundraising`.
    fec_path = OUT / f"fundraising_{year}.parquet"
    if fec_path.exists():
        feat = pd.read_parquet(fec_path)
        if "fundraising" in feat.columns:
            r = r.drop(columns=["fundraising"]).merge(
                feat[["race_id", "fundraising"]], on="race_id", how="left")
            r["fundraising"] = r["fundraising"].fillna(0.0)
    return r[["race_id", "incumbency", "fundraising", "open_seat"]]


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


def presidential_national_dem_2p(year: int) -> float | None:
    """National two-party Dem share in the presidential election two years before `year`."""
    panel = OUT / "county_panel.parquet"
    if not panel.exists():
        return None
    p = pd.read_parquet(panel, columns=["year", "dem", "rep"])
    p = p[p["year"] == year - 2]
    if p.empty:
        return None
    return float(p["dem"].sum() / (p["dem"].sum() + p["rep"].sum()))


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


def _swing_from_snapshot(year: int, snap: dict, detail: pd.DataFrame | None = None) -> dict:
    """Convert a generic-ballot snapshot dict into logit-scale national swing.

    mean = logit(gb dem_2p) − logit(last presidential national dem_2p), so the swing is
    the midterm environment relative to the presidential baseline already in `baseline`.
    When the presidential panel is missing, fall back to logit(gb) vs even (0.5).
    sd uses aggregator dispersion on the logit scale when available, else SWING_PRIOR sd.
    """
    prior = SWING_PRIOR.get(year, {"mean": 0.0, "sd": 0.04})
    gb = float(snap["dem_2p"])
    gb_logit = float(logit(gb))
    pres = presidential_national_dem_2p(year)
    if pres is not None:
        mean = gb_logit - float(logit(pres))
        anchor = "vs_presidential"
    else:
        mean = gb_logit  # vs even
        anchor = "vs_even"
    sd = float(prior["sd"])
    if detail is not None and len(detail) >= 2 and "dem_2p" in detail.columns:
        logits = logit(detail["dem_2p"].to_numpy(dtype=float))
        spread = float(np.nanstd(logits, ddof=1)) if len(logits) > 1 else 0.0
        if np.isfinite(spread) and spread > 0:
            sd = max(sd, spread)
    return {
        "mean": mean,
        "sd": sd,
        "source": f"generic_ballot.snapshot/{anchor}",
        "dem_2p": gb,
        "margin": float(snap.get("margin", float("nan"))),
        "n_sources": int(snap.get("n_sources", 0)),
    }


def _blend_specials(swing: dict, year: int) -> dict:
    """Average generic-ballot (or prior) swing with special-election over-performance."""
    from . import special_elections as se
    spec = se.summary(year)
    if spec.get("source") == "empty":
        return swing
    mean = 0.5 * float(swing["mean"]) + 0.5 * float(spec["mean"])
    sd = float(np.sqrt(0.5 * float(swing["sd"]) ** 2 + 0.5 * float(spec["sd"]) ** 2))
    out = {
        **swing,
        "mean": mean,
        "sd": max(sd, float(swing["sd"])),
        "special_mean": float(spec["mean"]),
        "special_mean_pp": float(spec.get("mean_pp", float("nan"))),
        "special_n": int(spec.get("n", 0)),
        "source": f"{swing['source']}+{spec['source']}",
    }
    return out


def national_swing(year: int, source: Path | None = None,
                   blend_specials: bool = True) -> dict:
    """Mean and sd of the national Democratic swing (logit scale).

    If `source` is passed, only that parquet is used (mean/sd columns); missing → prior.
    Otherwise resolution order:
      1. `generic_ballot_{year}.parquet` with mean/sd (hand-tuned override)
      2. cached `generic_ballot_snapshot.parquet` / live `generic_ballot.snapshot(year)`
      3. SWING_PRIOR placeholders
    Then, unless `blend_specials` is False or `source` was explicit, blend with
    `special_elections.summary(year)` (PLAN: GB + special over-performance).
    """
    prior = SWING_PRIOR.get(year, {"mean": 0.0, "sd": 0.04})

    def _from_mean_sd_parquet(path: Path) -> dict | None:
        if not path.exists():
            return None
        row = pd.read_parquet(path).iloc[0]
        if not {"mean", "sd"}.issubset(row.index):
            return None
        return {"mean": float(row["mean"]), "sd": float(row["sd"]), "source": str(path)}

    if source is not None:
        return _from_mean_sd_parquet(source) or {**prior, "source": "prior"}

    override = _from_mean_sd_parquet(OUT / f"generic_ballot_{year}.parquet")
    if override:
        swing = override
    else:
        swing = None
        snap_path = OUT / "generic_ballot_snapshot.parquet"
        if snap_path.exists():
            snaps = pd.read_parquet(snap_path)
            row = snaps.loc[snaps["year"] == year]
            if len(row):
                snap = row.iloc[0].to_dict()
                detail = None
                agg_path = OUT / "generic_ballot_aggregates.parquet"
                if agg_path.exists():
                    detail = pd.read_parquet(agg_path)
                    detail = detail[detail["year"] == year]
                swing = _swing_from_snapshot(year, snap, detail)
        if swing is None:
            try:
                from . import generic_ballot as gb
                snap = gb.snapshot(year)
                try:
                    detail = gb.aggregates(year)
                except Exception:
                    detail = None
                swing = _swing_from_snapshot(year, snap, detail)
            except Exception:
                swing = {**prior, "source": "prior"}

    if blend_specials:
        swing = _blend_specials(swing, year)
    return swing


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
    if "open_seat" not in f:
        f["open_seat"] = False
    f["open_seat"] = f["open_seat"].fillna(False).astype(bool)
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


def _fit_ridge(d: pd.DataFrame, draws: int, rng: np.random.Generator) -> dict:
    """Ridge stand-in on logit residual (used when PyMC is unavailable / disabled)."""
    ok = d["actual_share"].notna() & d["baseline"].notna()
    y = logit(d.loc[ok, "actual_share"].to_numpy()) - logit(d.loc[ok, "baseline"].to_numpy())
    # Subtract year-specific national swing mean so gamma learns race features, not climate.
    if "year" in d.columns:
        y = y.copy()
        years = d.loc[ok, "year"].to_numpy()
        for yr in np.unique(years):
            y[years == yr] -= national_swing(int(yr), blend_specials=True)["mean"]
    X = d.loc[ok, RACE_FEATURES].to_numpy()
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
    params["fit_method"] = "ridge"
    params["summary"] = pd.DataFrame({"mean": mean, "sd": np.sqrt(np.diag(cov))},
                                     index=RACE_FEATURES)
    return params


def _fit_pymc(d: pd.DataFrame, draws: int, rng: np.random.Generator) -> dict:
    """Hierarchical Stage B fit in PyMC (PLAN §4). Falls back to ridge on failure."""
    import pymc as pm

    ok = d["actual_share"].notna() & d["baseline"].notna()
    dd = d.loc[ok].copy()
    y = logit(dd["actual_share"].to_numpy()) - logit(dd["baseline"].to_numpy())
    years = dd["year"].to_numpy() if "year" in dd.columns else np.full(len(dd), 0)
    for yr in np.unique(years):
        y[years == yr] -= national_swing(int(yr), blend_specials=True)["mean"]
    X = dd[RACE_FEATURES].to_numpy(dtype=float)
    s_idx, _ = pd.factorize(dd["state_po"])
    n_state = int(s_idx.max()) + 1

    with pm.Model():
        gamma = pm.Normal("gamma", 0, 0.15, shape=len(RACE_FEATURES))
        sigma_state = pm.HalfNormal("sigma_state", 0.05)
        sigma_race = pm.HalfNormal("sigma_race", 0.08)
        u = pm.Normal("u_state", 0, 1, shape=n_state)
        mu = pm.math.dot(X, gamma) + sigma_state * u[s_idx]
        pm.Normal("y", mu=mu, sigma=sigma_race, observed=y)
        idata = pm.sample(draws, tune=max(500, draws), chains=2, target_accept=0.9,
                          random_seed=SEED, progressbar=False)

    def _dataset(group):
        return group.to_dataset() if hasattr(group, "to_dataset") else group

    post = _dataset(idata.posterior).stack(s=("chain", "draw"))
    # Subsample to `draws` for a stable shape matching prior_params.
    gamma_draws = np.asarray(post["gamma"].values).T  # features x samples → later transpose
    if gamma_draws.ndim == 1:
        gamma_draws = gamma_draws.reshape(1, -1)
    # post["gamma"] stacked: (feature, sample) or (sample, feature) depending on version
    g = np.asarray(post["gamma"].values)
    if g.ndim == 2 and g.shape[0] == len(RACE_FEATURES):
        gamma_mat = g.T
    else:
        gamma_mat = g.reshape(-1, len(RACE_FEATURES))
    if len(gamma_mat) > draws:
        pick = rng.choice(len(gamma_mat), draws, replace=False)
        gamma_mat = gamma_mat[pick]
    elif len(gamma_mat) < draws:
        extra = rng.choice(len(gamma_mat), draws - len(gamma_mat), replace=True)
        gamma_mat = np.vstack([gamma_mat, gamma_mat[extra]])

    params = prior_params(draws, rng)
    params["gamma"] = gamma_mat
    params["sigma_state"] = np.asarray(post["sigma_state"].values).ravel()[:draws]
    if len(params["sigma_state"]) < draws:
        params["sigma_state"] = np.resize(params["sigma_state"], draws)
    params["sigma_race"] = np.asarray(post["sigma_race"].values).ravel()[:draws]
    if len(params["sigma_race"]) < draws:
        params["sigma_race"] = np.resize(params["sigma_race"], draws)
    params["n_train"] = int(ok.sum())
    params["fit_method"] = "pymc"
    params["summary"] = pd.DataFrame({
        "mean": gamma_mat.mean(axis=0),
        "sd": gamma_mat.std(axis=0),
    }, index=RACE_FEATURES)
    return params


def fit(train: list[pd.DataFrame] | None = None, draws: int = 1000,
        rng: np.random.Generator | None = None) -> dict:
    """Posterior (or prior) draws of Stage B parameters.

    Preference: PyMC hierarchical fit when pymc is installed and STAGE_B_PYMC is not
    \"0\"; otherwise the ridge stand-in. Returned dict keys match either way.
    """
    rng = rng or np.random.default_rng(SEED)
    if not train:
        p = prior_params(draws, rng)
        p["fit_method"] = "prior"
        return p

    d = pd.concat(train, ignore_index=True)
    need = ["baseline", "actual_share", *RACE_FEATURES]
    if not all(c in d.columns for c in need) or d["actual_share"].notna().sum() < 5:
        p = prior_params(draws, rng)
        p["fit_method"] = "prior"
        return p

    use_pymc = os.environ.get("STAGE_B_PYMC", "1") != "0"
    if use_pymc:
        try:
            import pymc  # noqa: F401
            return _fit_pymc(d, draws, rng)
        except Exception:
            pass
    return _fit_ridge(d, draws, rng)


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
    # 2026 table: generic-ballot swing + races.py incumbency when available.
    lean = presidential_lean(2026)
    if lean.empty:
        print("no county_panel yet; writing schedule-only frame with baseline=NaN")
    out, info = run(2026, train_years=[2018, 2022], lean=None if lean.empty else lean)
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT / "vote_share_2026.parquet", index=False)
    info["seats"].to_parquet(OUT / "seat_counts_2026.parquet", index=False)
    swing = info["swing"]
    print("races:", len(out), "| swing source:", swing["source"],
          f"(mean={swing['mean']:+.3f}, sd={swing['sd']:.3f})")
    print(out[["office", "state_po", "median", "p_dem_win"]].head(10).to_string(index=False))
    print(info["seats"].to_string(index=False))


if __name__ == "__main__":
    main()

"""Stage A: county turnout, as a share of citizen voting-age population.

On the logit scale, each county's change from the last midterm is

    change = intercept[transition] + state race features . gamma + state effect
             + demographics . (beta + beta_shift[transition]) + lambda * (pres - anchor)
             + rho * (anchor - mean anchor) + noise,

with state effects ~ N(0, sigma_state), election-specific slope shifts ~ N(0, tau), and
Student-t noise whose scale grows for small counties (CVAP is a survey estimate there).

The national level is not taken from this model. Each simulation draws national turnout
from forecast.national and shifts every county by the same logit amount so that the
CVAP-weighted total matches it. The county model supplies the pattern around that level.

    python -m forecast.turnout_model     # fit on 2014->2018 and 2018->2022, forecast 2026
"""
from __future__ import annotations

import arviz as az
import numpy as np
import pandas as pd
import pymc as pm

from scipy.special import expit

from . import national
from .features import DEMOGRAPHICS, STATE_FEATURES, frame
from .ingest import OUT

SIMS = 20_000
SEED = 2026
OUT_PARTY = True     # include the out-party term (False reproduces the first backtest run)


# --------------------------------------------------------------------------- fit
def _dataset(group):
    """PyMC 6 returns xarray DataTree groups; older versions return Datasets."""
    return group.to_dataset() if hasattr(group, "to_dataset") else group


def fit(train: list[pd.DataFrame], draws: int = 1000, chains: int = 4,
        tune: int | None = None) -> dict:
    """Posterior draws of the model parameters. With no training frames, draws from the priors."""
    X_cols = DEMOGRAPHICS
    if train:
        d = pd.concat(train, ignore_index=True)
        d = d[d["train_ok"] & d["y"].notna() & d[X_cols + ["pres_minus_anchor"]].notna().all(axis=1)]
    else:
        d = None

    with pm.Model() as model:
        gamma = pm.Normal("gamma", 0, 0.2, shape=len(STATE_FEATURES))
        beta = pm.Normal("beta", 0, 0.1, shape=len(X_cols))
        lam = pm.Normal("lam", 0, 0.5)
        phi = pm.Normal("phi", 0, 0.5) if OUT_PARTY else 0.0
        rho = pm.Normal("rho", 0, 0.5)
        tau = pm.HalfNormal("tau", 0.05)
        sigma_state = pm.HalfNormal("sigma_state", 0.15)
        sigma = pm.HalfNormal("sigma", 0.15)
        kappa = pm.HalfNormal("kappa", 0.2)
        nu = pm.Gamma("nu", 4, 0.5)

        if d is not None:
            k_idx, k_names = pd.factorize(d["year"])
            s_idx, s_names = pd.factorize(d["year"].astype(str) + d["state_po"])
            mu = pm.Normal("mu", 0, 0.5, shape=len(k_names))
            beta_shift = pm.Normal("beta_shift", 0, 1, shape=(len(k_names), len(X_cols)))
            u_raw = pm.Normal("u_raw", 0, 1, shape=len(s_names))
            X = d[X_cols].to_numpy()
            mean = (mu[k_idx] + pm.math.dot(d[STATE_FEATURES].to_numpy(), gamma) + sigma_state * u_raw[s_idx]
                    + (X * (beta + tau * beta_shift[k_idx])).sum(axis=1)
                    + lam * d["pres_minus_anchor"].to_numpy() + rho * (d["anchor"].to_numpy() - d["anchor"].mean())
                    + phi * d["out_party_lean"].to_numpy())
            scale = pm.math.sqrt(sigma**2 + kappa**2 * 1000 / d["cvap"].to_numpy())
            pm.StudentT("y", nu=nu, mu=mean, sigma=scale, observed=d["y"].to_numpy())
            idata = pm.sample(draws, tune=1000 if tune is None else tune, chains=chains,
                              target_accept=0.95, random_seed=SEED, progressbar=False)
            post = _dataset(idata.posterior).stack(s=("chain", "draw"))
            summary = az.summary(idata, var_names=["gamma", "beta", "lam", "rho", "tau", "sigma_state", "sigma",
                                                   "kappa", "nu"] + (["phi"] if OUT_PARTY else []))
        else:
            idata = pm.sample_prior_predictive(draws * chains, random_seed=SEED)
            post = _dataset(idata.prior).stack(s=("chain", "draw"))
            summary = None
    names = ["gamma", "beta", "lam", "rho", "tau", "sigma_state", "sigma", "kappa", "nu"] + (["phi"] if OUT_PARTY else [])
    params = {n: post[n].values.T if post[n].ndim > 1 else post[n].values for n in names}
    params.setdefault("phi", np.zeros_like(params["lam"]))
    params["anchor_mean"] = float(d["anchor"].mean()) if d is not None else 0.0
    params["n_train"] = 0 if d is None else len(d)
    params["idata"] = idata
    params["summary"] = summary
    return params


# --------------------------------------------------------------------------- simulate
def simulate(f: pd.DataFrame, params: dict, national_draws: np.ndarray, rng: np.random.Generator,
             cvap_ratio: float, state_offset: pd.Series | None = None) -> np.ndarray:
    """County turnout draws (sims x counties) for frame f.

    national_draws are VEP turnout shares; cvap_ratio converts them to the CVAP basis used
    here (national CVAP-based turnout / VEP turnout at the last midterm).

    `state_offset` is an optional logit nudge by state_po (October early-vote pace). The
    national calibration still pins the CVAP-weighted total, so offsets reshuffle states.
    """
    n_sims, n = len(national_draws), len(f)
    n_post = len(params["lam"])
    pick = rng.integers(0, n_post, n_sims)
    X = f[DEMOGRAPHICS].fillna(0).to_numpy()
    Z = f[STATE_FEATURES].fillna(0).to_numpy()
    pma = f["pres_minus_anchor"].fillna(f["pres_minus_anchor"].median()).to_numpy()
    anc = f["anchor"].to_numpy()
    opl = f["out_party_lean"].fillna(0).to_numpy()
    s_idx, s_names = pd.factorize(f["state_po"])
    w = f["cvap"].to_numpy()
    target = np.clip(national_draws * cvap_ratio, 0.05, 0.95)
    if state_offset is not None and len(state_offset):
        off = f["state_po"].map(state_offset).fillna(0.0).to_numpy(dtype=float)
    else:
        off = np.zeros(n, dtype=float)

    out = np.empty((n_sims, n), dtype=np.float32)
    for start in range(0, n_sims, 1000):
        sl = slice(start, min(start + 1000, n_sims))
        p = pick[sl]
        m = len(p)
        beta = params["beta"][p] + params["tau"][p, None] * rng.standard_normal((m, X.shape[1]))
        u = params["sigma_state"][p, None] * rng.standard_normal((m, len(s_names)))
        scale = np.sqrt(params["sigma"][p, None] ** 2 + params["kappa"][p, None] ** 2 * 1000 / w[None, :])
        eps = scale * rng.standard_t(params["nu"][p, None], size=(m, n))
        d = (Z @ params["gamma"][p].T).T + beta @ X.T + u[:, s_idx] + params["lam"][p, None] * pma[None, :] \
            + params["rho"][p, None] * (anc - params["anchor_mean"])[None, :] + eps \
            + params["phi"][p, None] * opl[None, :] + off[None, :]
        lg = anc[None, :] + d
        # Shift each simulation so the CVAP-weighted total hits its national draw (bisection:
        # slower than Newton but cannot diverge on extreme draws).
        lo, hi = np.full(m, -10.0), np.full(m, 10.0)
        for _ in range(40):
            mid = (lo + hi) / 2
            above = (expit(lg + mid[:, None]) * w).sum(1) / w.sum() > target[sl]
            hi, lo = np.where(above, mid, hi), np.where(above, lo, mid)
        out[sl] = expit(lg + ((lo + hi) / 2)[:, None])
    return out


def summarise(f: pd.DataFrame, sims: np.ndarray) -> pd.DataFrame:
    q = np.quantile(sims, [0.1, 0.5, 0.9], axis=0)
    return pd.DataFrame({"unit_fips": f["unit_fips"], "state_po": f["state_po"], "cvap": f["cvap"],
                         "lo80": q[0], "median": q[1], "hi80": q[2]})


def cvap_vep_ratio(year: int) -> float:
    """National CVAP-based turnout / national VEP turnout in a past midterm."""
    mid = pd.read_parquet(OUT / "county_midterm_turnout.parquet").query("year == @year")
    return (mid["ballots"].sum() / mid["cvap"].sum()) / national.vep_turnout()[year]


def run(target: int, train_years: list[int], sims: int = SIMS, draws: int = 1000,
        params: dict | None = None, national_fixed: float | None = None,
        early_vote: bool = True, chains: int = 4, tune: int | None = None) -> tuple[pd.DataFrame, dict]:
    """Fit (unless params are given) and simulate target. national_fixed pins national turnout
    (CVAP basis) to one value, to test the county model on its own.

    When `early_vote` is True and `early_vote_{target}.parquet` exists, apply state logit
    offsets from relative October early-vote pace (PLAN §4 / §10 item 7).
    """
    rng = np.random.default_rng(SEED + target)
    params = params or fit([frame(y) for y in train_years], draws=draws, chains=chains,
                           tune=tune)
    f = frame(target)
    ratio = cvap_vep_ratio(target - 4)
    nat = national.draws(target, sims, rng) if national_fixed is None else np.full(sims, national_fixed / ratio)
    state_off = None
    ev_meta = {"applied": False}
    if early_vote:
        try:
            from . import early_vote as ev
            state_off = ev.state_offsets(target)
            if len(state_off) and float(np.abs(state_off.to_numpy(dtype=float)).sum()) > 0:
                ev_meta = {"applied": True, **ev.national_pace(target)}
        except Exception:
            state_off = None
    sims_ = simulate(f, params, nat, rng, ratio, state_offset=state_off)
    out = summarise(f, sims_)
    if "actual" in f:
        out["actual"] = f["actual"].values
        out["last_midterm"] = 1 / (1 + np.exp(-f["anchor"].values))
    w = f["cvap"].to_numpy()
    nat_sim = (sims_ * w[None, :]).sum(1) / w.sum()
    return out, {"params": params, "national": np.quantile(nat_sim, [0.1, 0.5, 0.9]),
                 "states": state_summary(f, sims_), "early_vote": ev_meta}


def state_summary(f: pd.DataFrame, sims: np.ndarray) -> pd.DataFrame:
    """State turnout quantiles, aggregated within each simulation (not by adding county quantiles)."""
    rows = []
    for st, idx in f.groupby("state_po").indices.items():
        w = f["cvap"].to_numpy()[idx]
        s = (sims[:, idx] * w[None, :]).sum(1) / w.sum()
        rows.append((st, *np.quantile(s, [0.1, 0.5, 0.9])))
    return pd.DataFrame(rows, columns=["state_po", "lo80", "median", "hi80"])


def main() -> None:
    out, info = run(2026, [2018, 2022], early_vote=True)
    # Each county's own uncertainty: the same model with national turnout fixed at its median.
    rel, rel_info = run(2026, [2018, 2022], params=info["params"],
                        national_fixed=info["national"][1], early_vote=True)
    out["lo80_county"], out["hi80_county"] = rel["lo80"].values, rel["hi80"].values
    out.to_parquet(OUT / "turnout_2026.parquet", index=False)
    st = info["states"].merge(rel_info["states"][["state_po", "lo80", "hi80"]], on="state_po",
                              suffixes=("", "_state"))      # *_state: national turnout held at its median
    st.to_parquet(OUT / "turnout_2026_states.parquet", index=False)
    info["params"]["summary"].to_csv(OUT / "turnout_2026_parameters.csv")
    pd.DataFrame({"quantile": [0.1, 0.5, 0.9], "turnout": info["national"]}).to_csv(
        OUT / "turnout_2026_national.csv", index=False)
    ev = info.get("early_vote") or {"applied": False}
    pd.DataFrame([ev]).to_csv(OUT / "turnout_2026_early_vote.csv", index=False)
    print("national 2026 turnout (CVAP basis), 10/50/90%:", np.round(info["national"], 3))
    print("early_vote applied:", ev.get("applied"),
          f"| reporting={ev.get('n_reporting', 'n/a')}")
    print(info["params"]["summary"])


if __name__ == "__main__":
    main()

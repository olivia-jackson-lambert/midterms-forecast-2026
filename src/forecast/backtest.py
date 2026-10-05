"""Backtests for Stage A (turnout) and Stage B (vote share).

Turnout (2018 / 2022): county model vs "same as the last midterm".

Vote share (2018 / 2022): Stage B against "same as the last presidential lean" (the plan's
baseline) and a stronger "uniform swing" reference: share error, Brier score, log loss,
80% interval coverage and calibration. Each year is fitted only on earlier midterms, once with
the turnout-weighted lean and once with the plain presidential lean.

    python -m forecast.backtest              # turnout + races when data exist
    python -m forecast.backtest races         # Stage B only
    python -m forecast.backtest turnout       # Stage A only
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from scipy.special import expit, logit

from .features import frame
from .ingest import OUT

BACKTESTS = {2018: [], 2022: [2018]}


# --------------------------------------------------------------------------- turnout
def score(out: pd.DataFrame) -> dict:
    ok = frame(int(out.attrs["year"]))["train_ok"].to_numpy()
    d = out[ok & out["actual"].notna()]
    w = d["cvap"]
    err, base = (d["median"] - d["actual"]).abs(), (d["last_midterm"] - d["actual"]).abs()
    big = d["cvap"] >= 5_000
    nat_actual = (d["actual"] * w).sum() / w.sum()
    return {
        "counties": len(d),
        "mae_pts": 100 * err.mean(), "baseline_mae_pts": 100 * base.mean(),
        "weighted_mae_pts": 100 * (err * w).sum() / w.sum(),
        "baseline_weighted_mae_pts": 100 * (base * w).sum() / w.sum(),
        "coverage80": d["actual"].between(d["lo80"], d["hi80"]).mean(),
        "coverage80_5k_plus": d.loc[big, "actual"].between(d.loc[big, "lo80"], d.loc[big, "hi80"]).mean(),
        "national_actual": nat_actual,
        **{f"bias_pts_{k}": 100 * (d["median"] - d["actual"])[m].mean() for k, m in
           {"small": d["cvap"] < 10_000, "mid": d["cvap"].between(10_000, 100_000),
            "large": d["cvap"] > 100_000}.items()},
    }


def run_turnout_backtests() -> pd.DataFrame:
    from . import turnout_model
    from .turnout_model import run

    rows = []
    for (year, train), out_party in [(bt, op) for op in (False, True) for bt in BACKTESTS.items()]:
        turnout_model.OUT_PARTY = out_party
        out, info = run(year, train)
        out.attrs["year"] = year
        out.to_parquet(OUT / f"backtest_turnout_{year}{'' if out_party else '_no_out_party'}.parquet",
                       index=False)
        if out_party:
            info["lean_draws"].to_parquet(OUT / f"lean_draws_{year}.parquet", index=False)
        s = score(out)
        s.update(year=year, out_party=out_party, national_lo80=info["national"][0],
                 national_median=info["national"][1], national_hi80=info["national"][2])
        fixed, _ = run(year, train, params=info["params"], national_fixed=s["national_actual"])
        fixed.attrs["year"] = year
        c = score(fixed)
        s.update({f"{k}_national_known": c[k] for k in
                  ("mae_pts", "weighted_mae_pts", "coverage80",
                   "bias_pts_small", "bias_pts_mid", "bias_pts_large")})
        rows.append(s)
    res = pd.DataFrame(rows).set_index(["out_party", "year"])
    res.to_csv(OUT / "backtest_turnout.csv")
    return res


# --------------------------------------------------------------------------- races (Stage B)
RACE_TRAIN = {2018: [], 2022: [2018]}


def _brier(p, y):
    return float(np.mean((p - y) ** 2))


def _log_loss(p, y, eps=1e-3):
    p = np.clip(p, eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def score_races(out: pd.DataFrame, year: int) -> dict:
    """Vote share and win-probability scores against two references:
    - "presidential lean": the state's last presidential two-party share as the forecast share,
      and a certain call for whichever party it favours (the plan's baseline);
    - "uniform swing": the presidential lean moved by the 30 September generic-ballot forecast
      of the national House vote, again called with certainty.
    """
    from . import generic_ballot
    d = out[out["actual"].notna()].copy()
    y = (d["actual"] > 0.5).astype(float).to_numpy()
    env = generic_ballot.national_environment(year)
    swing = logit(env["mean"]) - logit(d["pres_nat"].iloc[0]) if "pres_nat" in d else 0.0
    uniform = expit(logit(d["lean_plain"]) + swing)
    return {
        "races": len(d),
        "mae_pts": 100 * (d["median"] - d["actual"]).abs().mean(),
        "lean_mae_pts": 100 * (d["lean_plain"] - d["actual"]).abs().mean(),
        "uniform_swing_mae_pts": 100 * (uniform - d["actual"]).abs().mean(),
        "brier": _brier(d["p_dem_win"].to_numpy(), y),
        "lean_brier": _brier((d["lean_plain"] > 0.5).astype(float).to_numpy(), y),
        "uniform_swing_brier": _brier((uniform > 0.5).astype(float).to_numpy(), y),
        "log_loss": _log_loss(d["p_dem_win"].to_numpy(), y),
        "accuracy": float(((d["p_dem_win"] > 0.5) == (y > 0.5)).mean()),
        "coverage80": float(d["actual"].between(d["lo80"], d["hi80"]).mean()),
    }


def calibration(out: pd.DataFrame, bins=(0, 0.2, 0.4, 0.6, 0.8, 1.0)) -> pd.DataFrame:
    d = out[out["actual"].notna()].copy()
    d["won"] = (d["actual"] > 0.5).astype(float)
    d["bin"] = pd.cut(d["p_dem_win"], bins, include_lowest=True)
    return d.groupby("bin", observed=True).agg(races=("won", "size"), mean_p=("p_dem_win", "mean"),
                                              win_rate=("won", "mean")).reset_index()


def run_race_backtests() -> pd.DataFrame:
    """Each year fitted only on earlier midterms: the model, and two ablations (the plain
    presidential lean instead of the turnout-weighted one; no incumbent track record)."""
    from . import vote_model
    rows, cals = [], []
    variants = {"model": ("lean_turnout", True), "plain lean": ("lean_plain", True),
                "no track record": ("lean_turnout", False)}
    for year, train in RACE_TRAIN.items():
        for name, (lean, track) in variants.items():
            frames = [vote_model.frame(t) for t in train]
            f = vote_model.frame(year)
            if not track:
                for x in [*frames, f]:
                    x["track_record"] = 0.0
            params = vote_model.fit(frames, lean=lean)
            sims = vote_model.simulate(f, params, year, turnout_weighted=lean == "lean_turnout")
            out = vote_model.summarise(f, sims).assign(pres_nat=f["pres_nat"].values)
            s = score_races(out, year)
            s.update(year=year, variant=name, trained_on=",".join(map(str, train)) or "priors only")
            rows.append(s)
            if name == "model":
                out.to_parquet(OUT / f"backtest_races_{year}.parquet", index=False)
                cals.append(calibration(out).assign(year=year))
    res = pd.DataFrame(rows).set_index(["year", "variant"])
    res.to_csv(OUT / "backtest_races.csv")
    pd.concat(cals).to_csv(OUT / "backtest_races_calibration.csv", index=False)
    return res


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    mode = argv[0] if argv else "all"
    OUT.mkdir(parents=True, exist_ok=True)
    if mode in ("all", "turnout"):
        try:
            res = run_turnout_backtests()
            print(res.T.round(3).to_string())
        except FileNotFoundError as exc:
            print(f"turnout backtest skipped: {exc}")
    if mode in ("all", "races"):
        print(run_race_backtests().T.round(3).to_string())


if __name__ == "__main__":
    main()

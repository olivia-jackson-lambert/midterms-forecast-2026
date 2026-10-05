"""Backtests for Stage A (turnout) and Stage B (vote share).

Turnout (2018 / 2022): county model vs "same as the last midterm".

Vote share (2018 / 2022): Stage B win probabilities vs "same as the last presidential
lean" (PLAN §5). Scores Brier, log loss, and a coarse calibration table. The publish
gate is `beats_lean_baseline` (model Brier strictly below lean-baseline Brier).

    python -m forecast.backtest              # turnout + races when data exist
    python -m forecast.backtest races         # Stage B only
    python -m forecast.backtest turnout       # Stage A only
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from .features import frame
from .ingest import OUT

BACKTESTS = {2018: [], 2022: [2018]}
RACE_TRAIN = {2018: [], 2022: [2018]}


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
def _brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def _log_loss(p: np.ndarray, y: np.ndarray, eps: float = 1e-6) -> float:
    p = np.clip(p, eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration_table(p: np.ndarray, y: np.ndarray, bins: int = 5) -> pd.DataFrame:
    """Coarse reliability table: mean predicted win prob vs empirical win rate."""
    edges = np.linspace(0, 1, bins + 1)
    rows = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & (p < hi if i < bins - 1 else p <= hi)
        if not m.any():
            continue
        rows.append({
            "bin_lo": lo, "bin_hi": hi, "n": int(m.sum()),
            "mean_p": float(p[m].mean()), "win_rate": float(y[m].mean()),
        })
    return pd.DataFrame(rows)


def score_races(out: pd.DataFrame) -> dict:
    """Score Stage B forecasts. Requires columns p_dem_win, actual_share, baseline."""
    d = out.dropna(subset=["p_dem_win", "actual_share", "baseline"]).copy()
    if d.empty:
        return {"n_races": 0, "brier": np.nan, "log_loss": np.nan,
                "baseline_brier": np.nan, "beats_lean_baseline": False}
    y = (d["actual_share"] > 0.5).astype(float).to_numpy()
    p = d["p_dem_win"].to_numpy(dtype=float)
    # Lean baseline: treat presidential lean as a deterministic win probability
    # (hard 0/1 at 0.5) — the PLAN "same as the last presidential lean" rule.
    lean_call = (d["baseline"] > 0.5).astype(float).to_numpy()
    brier = _brier(p, y)
    base_brier = _brier(lean_call, y)
    return {
        "n_races": len(d),
        "brier": brier,
        "log_loss": _log_loss(p, y),
        "baseline_brier": base_brier,
        "beats_lean_baseline": bool(brier < base_brier),
        "accuracy": float(((p > 0.5) == (y > 0.5)).mean()),
        "baseline_accuracy": float((lean_call == y).mean()),
        "coverage80": float(d["actual_share"].between(d["lo80"], d["hi80"]).mean())
        if {"lo80", "hi80"}.issubset(d.columns) else np.nan,
    }


def run_race_backtests(sims: int = 2000, draws: int = 400) -> pd.DataFrame:
    """Fit Stage B with data available before each midterm; score vs lean baseline."""
    from . import vote_model

    panel = OUT / "county_panel.parquet"
    results = OUT / "county_midterm_results.parquet"
    if not (panel.exists() and results.exists()):
        print("race backtest skipped: need county_panel + county_midterm_results")
        return pd.DataFrame()

    rows, cal_parts = [], []
    for year, train_years in RACE_TRAIN.items():
        lean = vote_model.presidential_lean(year)
        if lean.empty:
            print(f"{year}: no presidential lean; skip")
            continue
        train = []
        for ty in train_years:
            f = vote_model.frame(ty, lean=vote_model.presidential_lean(ty))
            f = vote_model._attach_actuals(f, ty)
            train.append(f)
        # Force ridge in backtests for speed / portability unless STAGE_B_PYMC=1 explicitly.
        out, info = vote_model.run(
            year, train_years=None, sims=sims, draws=draws,
            params=vote_model.fit(train or None, draws=draws),
            lean=lean,
        )
        actual = vote_model._attach_actuals(
            vote_model.frame(year, lean=lean), year)
        out = out.merge(actual[["race_id", "actual_share"]], on="race_id", how="left")
        out.to_parquet(OUT / f"backtest_races_{year}.parquet", index=False)
        s = score_races(out)
        s["year"] = year
        s["swing_source"] = info["swing"]["source"]
        s["swing_mean"] = info["swing"]["mean"]
        s["fit_method"] = info["params"].get("fit_method", "unknown")
        s["n_train"] = info["params"].get("n_train", 0)
        rows.append(s)
        y = (out["actual_share"] > 0.5).astype(float).to_numpy()
        p = out["p_dem_win"].to_numpy()
        ok = np.isfinite(y) & np.isfinite(p)
        cal = calibration_table(p[ok], y[ok])
        cal["year"] = year
        cal_parts.append(cal)
        gate = "PASS" if s["beats_lean_baseline"] else "FAIL"
        print(f"{year}: n={s['n_races']} brier={s['brier']:.3f} "
              f"lean_brier={s['baseline_brier']:.3f} gate={gate} "
              f"fit={s['fit_method']}")

    res = pd.DataFrame(rows)
    if len(res):
        res.to_csv(OUT / "backtest_races.csv", index=False)
    if cal_parts:
        pd.concat(cal_parts, ignore_index=True).to_csv(OUT / "backtest_races_calibration.csv",
                                                       index=False)
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
        run_race_backtests()


if __name__ == "__main__":
    main()

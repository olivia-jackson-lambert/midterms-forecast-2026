"""Backtests for Stage A (turnout) and Stage B (vote share).

Turnout (2018 / 2022): county model vs "same as the last midterm".

Vote share (2018 / 2022): Stage B against "same as the last presidential lean" (the plan's
baseline) and a stronger "uniform swing" reference: share error, Brier score, log loss,
80% interval coverage and calibration. Each year is fitted only on earlier midterms, once with
the turnout-weighted lean and once with the plain presidential lean.

    python -m forecast.backtest              # turnout + races when data exist
    python -m forecast.backtest races         # Stage B only
    python -m forecast.backtest turnout       # Stage A only
    python -m forecast.backtest house         # House districts and seats (forecast.house)
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
    """Each year fitted only on earlier midterms: the model, and variants (the plain presidential
    lean instead of the turnout-weighted one; track record of the nominees on both sides, of the
    incumbent only, or none; with fundraising). "model" uses whatever vote_model switches on."""
    from . import vote_model
    rows, cals = [], []
    # variant: (lean, track record source, fundraising); the source is None for the model's own
    variants = {"model": ("lean_turnout", None, False), "plain lean": ("lean_plain", None, False),
                "nominee track record": ("lean_turnout", "track_record_nominees", False),
                "incumbent-only track record": ("lean_turnout", "track_record_incumbent", False),
                "no track record": ("lean_turnout", "none", False),
                "with fundraising": ("lean_turnout", None, True)}
    default = vote_model.USE_FUNDRAISING
    for year, train in RACE_TRAIN.items():
        for name, (lean, track, fund) in variants.items():
            vote_model.USE_FUNDRAISING = fund
            frames = [vote_model.frame(t) for t in train]
            f = vote_model.frame(year)
            vote_model.USE_FUNDRAISING = default
            if track:
                for x in [*frames, f]:
                    x["track_record"] = 0.0 if track == "none" else x[track]
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


# --------------------------------------------------------------------------- House
HOUSE_TRAIN = {2018: [], 2022: [2018]}


def score_house(out: pd.DataFrame, year: int, sims: np.ndarray | None = None) -> dict:
    """House scores on contested districts (a Democrat against a Republican), plus seat count.

    References, both called with certainty: "presidential lean" (the district's last presidential
    share) and "uniform swing" (that lean moved by the 30 September forecast of the national
    House vote). Seats without a contest count for the party on the ballot in every seat total;
    in races where an independent stands in for one side, the references call the Democratic
    side by its lean, and only a Democrat winning counts as a Democratic seat.
    """
    from . import generic_ballot
    from .house import MAJORITY, winners
    env = generic_ballot.national_environment(year)
    swing = logit(env["mean"]) - logit(out["pres_nat"].iloc[0])
    uniform = expit(logit(out["lean_plain"]) + swing)
    d = out[out["actual"].notna()]
    y = (d["actual"] > 0.5).astype(float).to_numpy()
    u = uniform[d.index]
    sure_d = int((~out["modelled"] & out["sole_party"].eq("D")).sum())
    actual_seats = int(out["winner"].eq("D").sum())
    c = (out["modelled"] & out["d_side"].eq("democrat")).to_numpy()
    res = {
        "districts": len(d),
        "mae_pts": 100 * (d["median"] - d["actual"]).abs().mean(),
        "lean_mae_pts": 100 * (d["lean_plain"] - d["actual"]).abs().mean(),
        "uniform_swing_mae_pts": 100 * (u - d["actual"]).abs().mean(),
        "brier": _brier(d["p_dem_win"].to_numpy(), y),
        "lean_brier": _brier((d["lean_plain"] > 0.5).astype(float).to_numpy(), y),
        "uniform_swing_brier": _brier((u > 0.5).astype(float).to_numpy(), y),
        "log_loss": _log_loss(d["p_dem_win"].to_numpy(), y),
        "accuracy": float(((d["p_dem_win"] > 0.5) == (y > 0.5)).mean()),
        "coverage80": float(d["actual"].between(d["lo80"], d["hi80"]).mean()),
        "bias_pts": 100 * (d["median"] - d["actual"]).mean(),
        "actual_dem_seats": actual_seats,
        "lean_dem_seats": sure_d + int((out["lean_plain"][c] > 0.5).sum()),
        "uniform_swing_dem_seats": sure_d + int((uniform[c] > 0.5).sum()),
        "expected_dem_seats": float(out["p_dem_win"].sum()),
    }
    if sims is not None:
        seats = winners(out, sims)[0].sum(axis=1)
        lo, med, hi = np.quantile(seats, [0.1, 0.5, 0.9])
        res.update(median_dem_seats=float(med), seats_lo80=float(lo), seats_hi80=float(hi),
                   p_dem_218=float((seats >= MAJORITY).mean()),
                   p_actual_majority=float(((seats >= MAJORITY) == (actual_seats >= MAJORITY)).mean()))
    res["seat_error"] = res.get("median_dem_seats", res["expected_dem_seats"]) - actual_seats
    res["lean_seat_error"] = res["lean_dem_seats"] - actual_seats
    res["uniform_swing_seat_error"] = res["uniform_swing_dem_seats"] - actual_seats
    return res


def run_house_backtests() -> pd.DataFrame:
    """Each year fitted only on earlier midterms (2018 on the priors alone): with and without
    the incumbent track record, and the forecast configuration with the national House vote
    known (to separate district error from the national miss)."""
    from . import house
    rows, cals = [], []
    for year, train in HOUSE_TRAIN.items():
        frames = [house.frame(t) for t in train]
        f = house.frame(year)
        fitted = {}
        for name in ("with track record", "no track record", "national vote known"):
            use = house.USE_TRACK_RECORD if name == "national vote known" else name == "with track record"
            tr = [x.assign(track_record=x["track_record_raw"] if use else 0.0) for x in frames]
            ff = f.assign(track_record=f["track_record_raw"] if use else 0.0)
            if use not in fitted:
                fitted[use] = house.fit(tr)
            params = fitted[use]
            fixed = float(f["house"].iloc[0]) if name == "national vote known" else None
            sims = house.simulate(ff, params, year, house_fixed=fixed)
            out = house.summarise(ff, sims)
            s = score_house(out, year, sims)
            s.update(year=year, variant=name, trained_on=",".join(map(str, train)) or "priors only",
                     forecast_configuration=use == house.USE_TRACK_RECORD and fixed is None)
            rows.append(s)
            if s["forecast_configuration"]:
                out.to_parquet(OUT / f"backtest_house_{year}.parquet", index=False)
                cals.append(calibration(out[out["actual"].notna()]).assign(year=year))
                params["summary"].to_csv(OUT / f"backtest_house_{year}_parameters.csv")
    res = pd.DataFrame(rows).set_index(["year", "variant"])
    res.to_csv(OUT / "backtest_house.csv")
    pd.concat(cals).to_csv(OUT / "backtest_house_calibration.csv", index=False)
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
    if mode in ("all", "house"):
        print(run_house_backtests().T.round(3).to_string())


if __name__ == "__main__":
    main()

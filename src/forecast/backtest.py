"""Backtest the turnout model on 2018 and 2022, using only data available before each election.

- 2022: county model fitted on the 2014->2018 transition; national level predicted from
  midterms up to 2018 and presidential turnout up to 2020.
- 2018: there is no earlier county transition to learn from (no public 2010 county turnout),
  so the county model runs on its priors alone; the national level uses elections to 2016.

Scored on counties whose actual turnout is not imputed, against "same as the last midterm".

    python -m forecast.backtest
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import frame
from .ingest import OUT
from . import turnout_model
from .turnout_model import run

BACKTESTS = {2018: [], 2022: [2018]}


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
        "weighted_mae_pts": 100 * (err * w).sum() / w.sum(), "baseline_weighted_mae_pts": 100 * (base * w).sum() / w.sum(),
        "coverage80": d["actual"].between(d["lo80"], d["hi80"]).mean(),
        "coverage80_5k_plus": d.loc[big, "actual"].between(d.loc[big, "lo80"], d.loc[big, "hi80"]).mean(),
        "national_actual": nat_actual,
        # Mean signed error (points) by county size: small (<10k CVAP), mid, large (>100k).
        **{f"bias_pts_{k}": 100 * (d["median"] - d["actual"])[m].mean() for k, m in
           {"small": d["cvap"] < 10_000, "mid": d["cvap"].between(10_000, 100_000), "large": d["cvap"] > 100_000}.items()},
    }


def main() -> None:
    rows = []
    for (year, train), out_party in [(bt, op) for op in (False, True) for bt in BACKTESTS.items()]:
        turnout_model.OUT_PARTY = out_party
        out, info = run(year, train)
        out.attrs["year"] = year
        out.to_parquet(OUT / f"backtest_turnout_{year}{'' if out_party else '_no_out_party'}.parquet", index=False)
        s = score(out)
        s.update(year=year, out_party=out_party, national_lo80=info["national"][0], national_median=info["national"][1],
                 national_hi80=info["national"][2])
        # Same fit with national turnout pinned to the actual level: tests the county pattern alone.
        fixed, _ = run(year, train, params=info["params"], national_fixed=s["national_actual"])
        fixed.attrs["year"] = year
        c = score(fixed)
        s.update({f"{k}_national_known": c[k] for k in
                  ("mae_pts", "weighted_mae_pts", "coverage80", "bias_pts_small", "bias_pts_mid", "bias_pts_large")})
        rows.append(s)
    res = pd.DataFrame(rows).set_index(["out_party", "year"])
    res.to_csv(OUT / "backtest_turnout.csv")
    print(res.T.round(3).to_string())


if __name__ == "__main__":
    main()

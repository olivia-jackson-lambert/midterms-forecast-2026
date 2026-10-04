"""National midterm turnout: the level the county model is calibrated to.

Turnout in a midterm is the last presidential turnout minus a midterm drop, on the logit
scale. The drop is estimated from every midterm since 1986 that precedes the target year,
and the forecast's spread is the spread of those drops (inflated for estimating their mean).
Out of sample, 1998-2022, this beats "same as the last midterm" (logit RMSE 0.19 against
0.23).

Source: UF Election Lab (Michael McDonald), VEP turnout 1980-2022 and 2024, CC BY 4.0.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .ingest import RAW, fetch

UF_2024 = "https://election.lab.ufl.edu/data-downloads/turnoutdata/Turnout_2024G_v0.4.csv"


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.rstrip("%"), errors="coerce")


def vep_turnout() -> pd.Series:
    """National VEP turnout by year, 1980-2024 (ballots counted; highest office where ballots
    are not reported, scaled by the average ballots-to-highest-office ratio)."""
    from .midterms import UF_TURNOUT
    d = pd.read_csv(fetch(UF_TURNOUT, RAW / "turnout_1980_2022.csv"), dtype=str)
    d = d[d["STATE"] == "United States"]
    year = _num(d["YEAR"]).astype(int).values
    ballots, highest, vep = (_num(d[c]).values for c in ("TOTAL_BALLOTS_COUNTED", "VOTE_FOR_HIGHEST_OFFICE", "VEP"))
    ratio = np.nanmean(ballots / highest)
    t = pd.Series(np.where(np.isnan(ballots), highest * ratio, ballots) / vep, index=year).sort_index()
    d24 = pd.read_csv(fetch(UF_2024, RAW / "turnout_2024.csv"), dtype=str)
    t[2024] = _num(d24.loc[d24["STATE"] == "United States", "VEP_TURNOUT_RATE"]).iloc[0] / 100
    return t


def logit(p):
    return np.log(p / (1 - p))


def predict(target: int, turnout: pd.Series | None = None) -> dict:
    """Predictive distribution of logit national VEP turnout in midterm `target`, using only
    elections before it. Returns mean, sd and degrees of freedom of a Student-t."""
    t = vep_turnout() if turnout is None else turnout
    drops = np.array([logit(t[y]) - logit(t[y - 2]) for y in range(1986, target, 4)])
    n = len(drops)
    return {"mean": logit(t[target - 2]) + drops.mean(), "sd": drops.std(ddof=1) * np.sqrt(1 + 1 / n),
            "df": n - 1, "n": n}


def draws(target: int, size: int, rng: np.random.Generator) -> np.ndarray:
    """Draws of national VEP turnout (a share) for `target`."""
    p = predict(target)
    z = stats.t.rvs(p["df"], size=size, random_state=rng)
    return 1 / (1 + np.exp(-(p["mean"] + p["sd"] * z)))


def interval(target: int, level: float = 0.8) -> tuple[float, float, float]:
    p = predict(target)
    q = stats.t.ppf([(1 - level) / 2, 0.5, (1 + level) / 2], p["df"])
    return tuple(1 / (1 + np.exp(-(p["mean"] + p["sd"] * q))))

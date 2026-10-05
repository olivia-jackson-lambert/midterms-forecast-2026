"""Special-election over-performance vs the last presidential lean.

PLAN §4 / §10: national_swing comes from the generic ballot *and* special-election
over-performance. Congressional specials for 2025–26 are curated from Ballotpedia's
public results table (checked-in constants; live HTML is unreliable here). Virginia's
2025 governor race is included as a high-turnout statewide signal.

Swing definition (percentage points of Democratic margin):
    swing_pp = (Dem − Rep special margin) − (Dem − Rep 2024 presidential margin)
Positive = Democrats over-performed the presidential baseline in that geography.

    python -m forecast.special_elections
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.special import logit as scipy_logit

from .ingest import OUT

# Ballotpedia: Special elections to the 119th United States Congress (House results table).
# MOV strings are Democratic margins in points (D+40 → +40, R+15 → −15).
# GA-14 date: Ballotpedia body text lists 7 Apr 2026; results table had 10 Mar — use body.
CONGRESSIONAL_SPECIALS_2026 = [
    {"date": "2025-04-01", "race": "FL-01", "state_po": "FL", "office": "HOUSE",
     "election_mov": -15.0, "pres_2024_mov": -37.0, "winner_party": "R",
     "source": "ballotpedia_119th_specials"},
    {"date": "2025-04-01", "race": "FL-06", "state_po": "FL", "office": "HOUSE",
     "election_mov": -14.0, "pres_2024_mov": -30.0, "winner_party": "R",
     "source": "ballotpedia_119th_specials"},
    {"date": "2025-09-09", "race": "VA-11", "state_po": "VA", "office": "HOUSE",
     "election_mov": 50.0, "pres_2024_mov": 34.0, "winner_party": "D",
     "source": "ballotpedia_119th_specials"},
    {"date": "2025-09-23", "race": "AZ-07", "state_po": "AZ", "office": "HOUSE",
     "election_mov": 40.0, "pres_2024_mov": 22.0, "winner_party": "D",
     "source": "ballotpedia_119th_specials"},
    {"date": "2025-11-04", "race": "TX-18", "state_po": "TX", "office": "HOUSE",
     "election_mov": 35.0, "pres_2024_mov": 40.0, "winner_party": "D",
     "source": "ballotpedia_119th_specials"},
    {"date": "2025-12-02", "race": "TN-07", "state_po": "TN", "office": "HOUSE",
     "election_mov": -9.0, "pres_2024_mov": -22.0, "winner_party": "R",
     "source": "ballotpedia_119th_specials"},
    {"date": "2026-04-07", "race": "GA-14", "state_po": "GA", "office": "HOUSE",
     "election_mov": -12.0, "pres_2024_mov": -37.0, "winner_party": "R",
     "source": "ballotpedia_119th_specials"},
    {"date": "2026-04-16", "race": "NJ-11", "state_po": "NJ", "office": "HOUSE",
     "election_mov": 21.0, "pres_2024_mov": 9.0, "winner_party": "D",
     "source": "ballotpedia_119th_specials"},
    {"date": "2026-06-02", "race": "CA-01", "state_po": "CA", "office": "HOUSE",
     "election_mov": -44.0, "pres_2024_mov": -39.0, "winner_party": "R",
     "source": "ballotpedia_119th_specials"},
    {"date": "2026-08-18", "race": "CA-14", "state_po": "CA", "office": "HOUSE",
     "election_mov": 6.2, "pres_2024_mov": 35.0, "winner_party": "D",
     "source": "ballotpedia_119th_specials"},
    {"date": "2026-08-25", "race": "GA-13", "state_po": "GA", "office": "HOUSE",
     "election_mov": 8.0, "pres_2024_mov": 42.0, "winner_party": "D",
     "source": "ballotpedia_119th_specials"},
]

# Statewide off-year signal (not a congressional special, but PLAN's "special-election energy").
STATEWIDE_SIGNAL_2026 = [
    {"date": "2025-11-04", "race": "VA-GOV", "state_po": "VA", "office": "GOV",
     "election_mov": 15.36, "pres_2024_mov": 5.8, "winner_party": "D",
     "source": "virginia_sos_wikipedia"},
]

# Cycle-level approximations when a race-level series is not curated (backtests).
# Units: Democratic margin swing vs prior presidential, percentage points.
CYCLE_SPECIAL_SWING_PP = {
    2018: 8.0,   # 2017–18 specials broadly D+ (illustrative published summary)
    2022: -1.0,  # 2021–22 specials near even / slight R lean into midterms
}


def margin_to_dem_2p(mov: float) -> float:
    """Democratic two-party share from a Dem margin in percentage points (D+10 → 0.55)."""
    return 0.5 + float(mov) / 200.0


def swing_pp_to_logit(swing_pp: float) -> float:
    """Approximate logit shift implied by a Democratic margin swing in points."""
    return float(scipy_logit(np.clip(margin_to_dem_2p(swing_pp), 1e-4, 1 - 1e-4))
                 - scipy_logit(0.5))


def series(cycle: int = 2026) -> pd.DataFrame:
    """Race-level special / off-year series for a midterm cycle (target election year)."""
    cols = ["date", "race", "state_po", "office", "election_mov", "pres_2024_mov",
            "swing_pp", "winner_party", "source", "cycle"]
    if cycle != 2026:
        return pd.DataFrame(columns=cols)
    rows = CONGRESSIONAL_SPECIALS_2026 + STATEWIDE_SIGNAL_2026
    df = pd.DataFrame(rows)
    df["swing_pp"] = df["election_mov"] - df["pres_2024_mov"]
    df["cycle"] = cycle
    return df.sort_values("date").reset_index(drop=True)


def summary(cycle: int = 2026) -> dict:
    """Mean / sd of special-election Dem over-performance on the logit scale."""
    df = series(cycle)
    if df.empty:
        if cycle in CYCLE_SPECIAL_SWING_PP:
            pp = CYCLE_SPECIAL_SWING_PP[cycle]
            return {
                "cycle": cycle, "n": 0, "mean_pp": float(pp), "sd_pp": 5.0,
                "mean": swing_pp_to_logit(pp), "sd": abs(swing_pp_to_logit(5.0)),
                "source": "cycle_constant",
            }
        return {"cycle": cycle, "n": 0, "mean_pp": 0.0, "sd_pp": 0.0,
                "mean": 0.0, "sd": 0.04, "source": "empty"}
    pp = df["swing_pp"].to_numpy(dtype=float)
    mean_pp = float(np.mean(pp))
    sd_pp = float(np.std(pp, ddof=1)) if len(pp) > 1 else 5.0
    return {
        "cycle": cycle,
        "n": int(len(df)),
        "mean_pp": mean_pp,
        "sd_pp": sd_pp,
        "median_pp": float(np.median(pp)),
        "mean": swing_pp_to_logit(mean_pp),
        "sd": max(abs(swing_pp_to_logit(sd_pp)), 0.02),
        "source": "special_elections.series",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = series(2026)
    df.to_parquet(OUT / "special_elections_2026.parquet", index=False)
    df.to_csv(OUT / "special_elections_2026.csv", index=False)
    s = summary(2026)
    pd.DataFrame([s]).to_parquet(OUT / "special_elections_summary.parquet", index=False)
    print(df[["date", "race", "election_mov", "pres_2024_mov", "swing_pp"]].to_string(index=False))
    print(f"n={s['n']} mean_pp={s['mean_pp']:+.1f} median_pp={s['median_pp']:+.1f} "
          f"logit_mean={s['mean']:+.3f} sd={s['sd']:.3f}")


if __name__ == "__main__":
    main()

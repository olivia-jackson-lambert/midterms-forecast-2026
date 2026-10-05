"""Build the minimal processed inputs needed for Stage B race backtests.

Reuses `ingest.county_presidential` for state lean and `midterms.county_results` for
Senate/governor actuals. Skips CVAP, ACS, and EAVS turnout (Stage A). Safe to re-run;
uses the same caches as `ingest` / `midterms`.

    python -m forecast.ensure_race_data
"""
from __future__ import annotations

import pandas as pd

from .ingest import OUT
from .ingest import county_presidential
from .midterms import county_results


def write_minimal_panel() -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    panel = county_presidential()
    panel.to_parquet(OUT / "county_panel.parquet", index=False)
    print(f"county_panel: {len(panel)} rows, years={sorted(panel.year.unique())}")
    return panel


def write_midterm_results() -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    # Skip HOUSE precincts for 2018 — Stage B only needs Senate + governor.
    r18 = county_results(2018, race_offices=("SENATE", "STATE"))
    r22 = county_results(2022)
    results = pd.concat([r18, r22], ignore_index=True)
    results.to_parquet(OUT / "county_midterm_results.parquet", index=False)
    races = results[results["race"] != "HOUSE"].groupby(["year", "race", "special"])["state_po"].nunique()
    print("midterm results races:\n", races.to_string())
    return results


def main() -> None:
    write_minimal_panel()
    write_midterm_results()
    print("race-backtest inputs ready under", OUT)


if __name__ == "__main__":
    main()

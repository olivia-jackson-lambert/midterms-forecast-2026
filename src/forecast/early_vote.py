"""October early / mail vote signal (PLAN §3 / §10 residual on Stage A).

US Elections Project (electproject.org) publishes state early-vote dashboards each
cycle. Confirm the 2026 page is up, then ingest state-level early-vote shares for the
October Stage A refresh.

This module is a stub until the 2026 USEP tables are confirmed reachable: it records
source URLs and a no-op loader that returns an empty frame when the cache is missing.

    python -m forecast.early_vote
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .ingest import OUT, RAW, UA

RAW_EV = RAW / "early_vote"
# Confirmed reachable host; 2026 path may appear / move as October approaches.
USEP_HOME = "https://electproject.github.io/Early-Vote-2024G/index.html"
USEP_NOTES_2026 = {
    "status": "confirm_2026_page",
    "usep_2024_reference": USEP_HOME,
    "plan": "Pull state early/mail shares once the 2026 USEP (or successor) page lists them; "
            "feed into turnout_model national/state adjustment in October.",
}


def load(year: int = 2026) -> pd.DataFrame:
    """State early-vote share of expected turnout, if a cache exists."""
    path = OUT / f"early_vote_{year}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame(columns=["year", "state_po", "early_share", "mail_share", "source"])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    RAW_EV.mkdir(parents=True, exist_ok=True)
    df = load(2026)
    print("early_vote rows:", len(df))
    print("2026 source notes:", USEP_NOTES_2026)
    # Persist notes for operators.
    pd.DataFrame([USEP_NOTES_2026]).to_csv(OUT / "early_vote_status.csv", index=False)


if __name__ == "__main__":
    main()

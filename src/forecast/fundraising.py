"""Candidate fundraising for Stage B race features.

PLAN §3 / §4: fundraising enters the vote-share equation.
- Senate: public OpenFEC API (`DEMO_KEY` works; set `FEC_API_KEY` for volume).
- Governors: not in FEC. FollowTheMoney / OpenSecrets state data needs a free API
  account key (`FTM_API_KEY`). Until that key is set, write an optional cache
  `data/processed/gov_fundraising_{year}.parquet` (columns race_id, fundraising)
  or leave GOV fundraising at 0.

    python -m forecast.fundraising
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .features import SENATE
from .ingest import OUT, RAW, UA

FEC = "https://api.open.fec.gov/v1/candidates/totals/"
RAW_FEC = RAW / "fec"
PARTY_DEM = {"DEM", "DFL"}
PARTY_REP = {"REP"}
# FollowTheMoney Ask Anything API (account key required; not called without FTM_API_KEY).
FTM = "https://api.followthemoney.org/"


def _api_key() -> str:
    return os.environ.get("FEC_API_KEY", "DEMO_KEY")


def _fetch_senate_totals(election_year: int) -> pd.DataFrame:
    """Page through OpenFEC candidate totals for Senate in `election_year`."""
    RAW_FEC.mkdir(parents=True, exist_ok=True)
    cache = RAW_FEC / f"senate_totals_{election_year}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    rows, page = [], 1
    while True:
        params = {
            "api_key": _api_key(),
            "office": "S",
            "election_year": election_year,
            "election_full": "true",
            "per_page": 100,
            "page": page,
            "sort": "-receipts",
        }
        with requests.get(FEC, params=params, headers=UA, timeout=120) as r:
            r.raise_for_status()
            payload = r.json()
        batch = payload.get("results") or []
        if not batch:
            break
        for row in batch:
            rows.append({
                "election_year": election_year,
                "state_po": row.get("state"),
                "name": row.get("name"),
                "party": (row.get("party") or "").upper(),
                "receipts": float(row.get("receipts") or 0.0),
                "candidate_id": row.get("candidate_id"),
                "incumbent_challenge": row.get("incumbent_challenge"),
            })
        pages = (payload.get("pagination") or {}).get("pages") or page
        if page >= pages:
            break
        page += 1
    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_parquet(cache, index=False)
    return df


def senate_party_receipts(election_year: int) -> pd.DataFrame:
    """One row per state: dem_receipts, rep_receipts (sum of active major-party candidates)."""
    raw = _fetch_senate_totals(election_year)
    if raw.empty:
        return pd.DataFrame(columns=["state_po", "dem_receipts", "rep_receipts", "year"])
    # Keep states on the Senate schedule for this cycle when known.
    schedule = set(SENATE.get(election_year, "").split())
    if schedule:
        raw = raw[raw["state_po"].isin(schedule)]
    dem = raw[raw["party"].isin(PARTY_DEM)].groupby("state_po")["receipts"].sum()
    rep = raw[raw["party"].isin(PARTY_REP)].groupby("state_po")["receipts"].sum()
    states = sorted(set(dem.index) | set(rep.index) | schedule)
    out = pd.DataFrame({"state_po": states})
    out["dem_receipts"] = out["state_po"].map(dem).fillna(0.0)
    out["rep_receipts"] = out["state_po"].map(rep).fillna(0.0)
    out["year"] = election_year
    return out


def fundraising_feature(election_year: int) -> pd.DataFrame:
    """Race-level fundraising feature for Senate; governors omitted (FEC gap).

    Returns columns race_id, fundraising (z-scored log Dem/Rep ratio).
    """
    from .vote_model import scheduled_races

    races = scheduled_races(election_year)
    sen = senate_party_receipts(election_year)
    by_state = sen.set_index("state_po") if len(sen) else pd.DataFrame()
    vals = []
    for _, row in races.iterrows():
        if row["office"] != "SEN" or by_state.empty or row["state_po"] not in by_state.index:
            vals.append(0.0)
            continue
        d = float(by_state.loc[row["state_po"], "dem_receipts"])
        r = float(by_state.loc[row["state_po"], "rep_receipts"])
        if d <= 0 or r <= 0:
            vals.append(0.0)
            continue
        vals.append(np.log(d / r))
    races = races.copy()
    races["fundraising_raw"] = vals
    # Standardize non-zero Senate values; leave exact zeros as zeros.
    mask = races["office"].eq("SEN") & races["fundraising_raw"].ne(0)
    z = races["fundraising_raw"].to_numpy(dtype=float).copy()
    if mask.sum() >= 2:
        mu, sd = z[mask].mean(), z[mask].std()
        if sd > 1e-8:
            z[mask] = (z[mask] - mu) / sd
        z = np.clip(z, -3, 3)
    races["fundraising"] = z
    return races[["race_id", "fundraising", "fundraising_raw"]]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for year in (2018, 2022, 2026):
        try:
            sen = senate_party_receipts(year)
            feat = fundraising_feature(year)
        except Exception as exc:
            print(f"{year}: FEC fetch failed ({exc})")
            continue
        sen.to_parquet(OUT / f"fec_senate_receipts_{year}.parquet", index=False)
        feat.to_parquet(OUT / f"fundraising_{year}.parquet", index=False)
        print(f"{year}: states={len(sen)} races_nonzero="
              f"{(feat['fundraising'] != 0).sum()} "
              f"mean_raw={feat.loc[feat.fundraising_raw != 0, 'fundraising_raw'].mean():+.2f}")
    key = os.environ.get("FTM_API_KEY")
    if key:
        print("FTM_API_KEY set — governor fundraising via FollowTheMoney not yet automated; "
              "write gov_fundraising_{year}.parquet manually for now.")
    else:
        print("Governor fundraising: no FTM_API_KEY; GOV feature stays 0 "
              "(optional cache: gov_fundraising_{year}.parquet).")


if __name__ == "__main__":
    main()

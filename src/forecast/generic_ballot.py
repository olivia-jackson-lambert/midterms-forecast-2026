"""Generic congressional ballot averages for midterm backtests and the 2026 forecast.

FiveThirtyEight's old polling endpoint is empty and its GitHub poll archive does not cover
the generic ballot, so averages are rebuilt from public Wikipedia aggregate tables that cite
RealClearPolitics, FiveThirtyEight (historical), Decision Desk HQ, FiftyPlusOne, NBC News and
Silver Bulletin.

    python -m forecast.generic_ballot
"""
from __future__ import annotations

import re
from io import StringIO

import pandas as pd
import requests

from .ingest import OUT, RAW, UA

RAW_GB = RAW / "generic_ballot"
WIKI = {
    2018: "https://en.wikipedia.org/wiki/2018_United_States_House_of_Representatives_election_ratings",
    2022: "https://en.wikipedia.org/wiki/2022_United_States_House_of_Representatives_election_ratings",
    2026: "https://en.wikipedia.org/wiki/2026_United_States_House_of_Representatives_elections",
}

# Prefer these aggregators when building the forecast snapshot; fall back to Wikipedia's
# published "Average" row when present.
PREFERRED = ("RealClearPolitics", "FiveThirtyEight", "Decision Desk HQ", "FiftyPlusOne",
             "Silver Bulletin", "NBC News")

# 2026 source notes for operators (scrapable vs blocked in this environment).
SOURCE_NOTES_2026 = {
    "wikipedia_aggregates": "reachable; table 'Generic congressional ballot aggregate polls'",
    "fiftyplusone": "reachable (https://fiftyplusone.news/polls/generic-ballot/generic-ballot)",
    "realclearpolling": "blocked here (HTTP 403); still cited on Wikipedia",
    "fivethirtyeight_project": "page loads as ABC News shell; no usable poll JSON (known empty)",
}


def _fetch_html(url: str, name: str) -> str:
    RAW_GB.mkdir(parents=True, exist_ok=True)
    path = RAW_GB / name
    if not path.exists():
        with requests.get(url, headers=UA, timeout=120) as r:
            r.raise_for_status()
            path.write_bytes(r.content)
    return path.read_text(encoding="utf-8", errors="replace")


def _pct(x) -> float:
    if pd.isna(x):
        return float("nan")
    s = re.sub(r"\[.*?\]", "", str(x).replace("%", "").replace(",", "")).strip()
    return float(s)


def _clean_source(s: str) -> str:
    return re.sub(r"\[.*?\]", "", str(s)).strip()


def _pick_aggregate_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    """Find the poll-aggregator table (Democratic / Republican share columns)."""
    for t in tables:
        cols = [str(c) for c in t.columns]
        flat = " ".join(cols).lower()
        if "democratic" in flat and "republican" in flat and (
                "poll" in flat or "aggregation" in flat or "source of poll" in flat):
            return t
        # 2026 Wikipedia uses Democrats / Republicans without a "Polling aggregates" MultiIndex.
        if (("democrats" in flat and "republicans" in flat)
                and ("source of poll" in flat or "aggregation" in flat or "margin" in flat)):
            return t
    raise ValueError("no generic-ballot aggregate table found")


def _normalize(df: pd.DataFrame, year: int) -> pd.DataFrame:
    # Flatten MultiIndex columns from the 2018/2022 ratings pages.
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[-1] if isinstance(c, tuple) else c for c in df.columns]
    rename = {}
    for c in df.columns:
        cl = str(c).lower()
        if "source" in cl:
            rename[c] = "source"
        elif cl.startswith("democratic") or cl == "democrats":
            rename[c] = "dem"
        elif cl.startswith("republican") or cl == "republicans":
            rename[c] = "rep"
        elif "date updated" in cl or cl == "dates updated":
            rename[c] = "as_of"
        elif "dates polled" in cl or "dates administered" in cl:
            rename[c] = "dates_polled"
    out = df.rename(columns=rename)
    need = {"source", "dem", "rep"}
    if not need.issubset(out.columns):
        raise ValueError(f"unexpected columns for {year}: {list(out.columns)}")
    out = out[out["source"].notna()].copy()
    out["source"] = out["source"].map(_clean_source)
    out = out[~out["source"].str.lower().isin({"nan", ""})]
    out["dem"] = out["dem"].map(_pct)
    out["rep"] = out["rep"].map(_pct)
    out = out[out["dem"].notna() & out["rep"].notna()]
    out["dem_2p"] = out["dem"] / (out["dem"] + out["rep"])
    out["margin"] = out["dem"] - out["rep"]          # positive = Democratic lead
    out["year"] = year
    keep = ["year", "source", "dem", "rep", "dem_2p", "margin"]
    for optional in ("as_of", "dates_polled"):
        if optional in out.columns:
            keep.append(optional)
    return out[keep]


def aggregates(year: int) -> pd.DataFrame:
    """One row per public aggregator (and Wikipedia's Average row, if present)."""
    html = _fetch_html(WIKI[year], f"wiki_generic_ballot_{year}.html")
    tables = pd.read_html(StringIO(html))
    return _normalize(_pick_aggregate_table(tables), year)


def snapshot(year: int) -> dict:
    """Point estimate used by the vote model: mean of preferred aggregators, else Average row."""
    df = aggregates(year)
    preferred = df[df["source"].isin(PREFERRED)]
    if preferred.empty:
        preferred = df[df["source"].str.lower().eq("average")]
    if preferred.empty:
        preferred = df
    # Drop the Wikipedia "Average" row from the mean when individual aggregators are present,
    # so it is not double-counted.
    if len(preferred) > 1:
        preferred = preferred[~preferred["source"].str.lower().eq("average")]
    return {
        "year": year,
        "dem": float(preferred["dem"].mean()),
        "rep": float(preferred["rep"].mean()),
        "dem_2p": float(preferred["dem_2p"].mean()),
        "margin": float(preferred["margin"].mean()),
        "n_sources": int(len(preferred)),
        "sources": ", ".join(preferred["source"].tolist()),
    }


def panel() -> pd.DataFrame:
    return pd.concat([aggregates(y) for y in (2018, 2022, 2026)], ignore_index=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    detail = panel()
    detail.to_parquet(OUT / "generic_ballot_aggregates.parquet", index=False)
    snaps = pd.DataFrame([snapshot(y) for y in (2018, 2022, 2026)])
    snaps.to_parquet(OUT / "generic_ballot_snapshot.parquet", index=False)
    detail.to_csv(OUT / "generic_ballot_aggregates.csv", index=False)
    snaps.to_csv(OUT / "generic_ballot_snapshot.csv", index=False)
    print(snaps.to_string(index=False))
    print("2026 source options:", SOURCE_NOTES_2026)


if __name__ == "__main__":
    main()

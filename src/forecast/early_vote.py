"""October early / mail vote signal (PLAN §3 / §10 item 7 — Stage A refresh).

US Elections Project / electproject early-vote pages for 2024 are the historical
reference. For 2026 the live national tracker is UF Election Lab (Michael McDonald):

  Page: https://election.lab.ufl.edu/early-vote/2026-early-voting/
  CSV:  https://election.lab.ufl.edu/data-downloads/earlyvote/2026/US.csv

Ingest builds state-level early/mail shares of 2022 turnout and optional Stage A
logit offsets (relative pace among reporting states). Re-run to refresh as states
update through October.

    python -m forecast.early_vote
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .ingest import OUT, RAW, UA

RAW_EV = RAW / "early_vote"

# Historical USEP reference (2024 cycle). 2026 live source is UF Election Lab.
USEP_HOME_2024 = "https://electproject.github.io/Early-Vote-2024G/index.html"
UF_EARLY_VOTE_PAGE = "https://election.lab.ufl.edu/early-vote/2026-early-voting/"
UF_EARLY_VOTE_CSV = {
    2026: "https://election.lab.ufl.edu/data-downloads/earlyvote/2026/US.csv",
}

# Relative early-vote pace → logit turnout nudge (reporting states only).
OFFSET_SCALE = 0.15
OFFSET_CLIP = 0.30


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _max_update(series: pd.Series) -> str:
    """Latest last_update as ISO date (string max is wrong for M/D/YYYY)."""
    dt = pd.to_datetime(series, errors="coerce")
    if dt.notna().any():
        return dt.max().strftime("%Y-%m-%d")
    vals = [str(v) for v in series.dropna().astype(str) if str(v).strip()]
    return max(vals) if vals else ""


def fetch_csv(year: int = 2026, force: bool = True) -> Path:
    """Download the UF Election Lab national early-vote CSV (refresh by default)."""
    url = UF_EARLY_VOTE_CSV.get(year)
    if url is None:
        raise ValueError(f"no UF early-vote CSV configured for {year}")
    RAW_EV.mkdir(parents=True, exist_ok=True)
    dest = RAW_EV / f"uf_earlyvote_{year}_US.csv"
    if dest.exists() and not force:
        return dest
    with requests.get(url, headers=UA, timeout=120) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(r.content)
    tmp.rename(dest)
    return dest


def parse_uf_csv(path: Path, year: int = 2026) -> pd.DataFrame:
    """Tidy UF US.csv into one row per state with early/mail shares of 2022 turnout."""
    raw = pd.read_csv(path)
    if "state_abbv" not in raw.columns:
        raise ValueError(f"unexpected early-vote schema in {path}")
    d = pd.DataFrame({
        "year": year,
        "state_po": raw["state_abbv"].astype(str).str.upper().str.strip(),
        "state": raw.get("state", pd.Series(index=raw.index, dtype=str)),
        "turn_2022": _num(raw["turn_2022"]),
        "last_update": raw.get("last_update"),
        "data_source": raw.get("data_source"),
        "request_all": _num(raw.get("request_all", 0)).fillna(0.0),
        "accept_all": _num(raw.get("accept_all", 0)).fillna(0.0),
        "inperson_all": _num(raw.get("inperson_all", 0)).fillna(0.0),
        "voted_all": _num(raw.get("voted_all", 0)).fillna(0.0),
    })
    denom = d["turn_2022"].clip(lower=1.0)
    # Returned ballots (mail accepted + in-person early when reported separately).
    # UF's voted_all already blends channels in most states; prefer it when present.
    d["ballots_returned"] = np.where(
        d["voted_all"] > 0,
        d["voted_all"],
        d["accept_all"] + d["inperson_all"],
    )
    d["early_share"] = d["ballots_returned"] / denom
    d["mail_share"] = d["accept_all"] / denom
    d["request_share"] = d["request_all"] / denom
    d["reporting"] = d["ballots_returned"] > 0
    d["source"] = "uf_election_lab"
    d["source_url"] = UF_EARLY_VOTE_CSV[year]
    return d.sort_values("state_po").reset_index(drop=True)


def offsets_from_frame(d: pd.DataFrame, scale: float = OFFSET_SCALE) -> pd.Series:
    """Logit turnout offsets from a tidy early-vote frame (reporting states)."""
    out = pd.Series(0.0, index=d["state_po"], name="early_vote_offset")
    if d.empty or "reporting" not in d.columns:
        return out
    rep = d.loc[d["reporting"] & d["early_share"].notna()].copy()
    if len(rep) < 3:
        return out
    pace = rep["early_share"].to_numpy(dtype=float)
    sd = float(np.std(pace, ddof=0))
    if sd < 1e-9:
        return out
    z = (pace - pace.mean()) / sd
    adj = np.clip(scale * z, -OFFSET_CLIP, OFFSET_CLIP)
    out.loc[rep["state_po"].values] = adj
    return out


def build(year: int = 2026, force: bool = True) -> pd.DataFrame:
    """Fetch, tidy, and cache `early_vote_{year}.parquet` (+ offsets)."""
    path = fetch_csv(year, force=force)
    df = parse_uf_csv(path, year=year)
    offs = offsets_from_frame(df)
    df["early_vote_offset"] = df["state_po"].map(offs).fillna(0.0)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / f"early_vote_{year}.parquet", index=False)
    offs.rename("early_vote_offset").to_frame().reset_index().rename(
        columns={"index": "state_po"}).to_parquet(
        OUT / f"early_vote_offsets_{year}.parquet", index=False)
    return df


def load(year: int = 2026) -> pd.DataFrame:
    """State early-vote shares; empty frame if cache missing."""
    path = OUT / f"early_vote_{year}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame(columns=[
        "year", "state_po", "early_share", "mail_share", "request_share",
        "reporting", "source", "early_vote_offset",
    ])


def state_offsets(year: int = 2026, scale: float = OFFSET_SCALE) -> pd.Series:
    """Logit turnout offsets from relative early-vote pace (reporting states).

    Non-reporting states get 0. Mean among reporters is ~0 so the national total
    is little changed; competitive / high-pace states get a positive nudge.
    """
    d = load(year)
    if d.empty:
        return pd.Series(dtype=float, name="early_vote_offset")
    if "early_vote_offset" in d.columns and scale == OFFSET_SCALE:
        return d.set_index("state_po")["early_vote_offset"].astype(float)
    return offsets_from_frame(d, scale=scale)


def national_pace(year: int = 2026) -> dict:
    """Aggregate returned ballots / 2022 turnout among reporting states."""
    d = load(year)
    if d.empty:
        return {"year": year, "n_reporting": 0, "early_share": float("nan"),
                "source": "missing"}
    rep = d.loc[d.get("reporting", False) == True]  # noqa: E712
    if rep.empty:
        return {"year": year, "n_reporting": 0, "early_share": float("nan"),
                "source": "no_reports"}
    returned = float(rep["ballots_returned"].sum()) if "ballots_returned" in rep else float(
        (rep["early_share"] * rep["turn_2022"]).sum())
    base = float(rep["turn_2022"].sum())
    return {
        "year": year,
        "n_reporting": int(len(rep)),
        "n_states": int(len(d)),
        "ballots_returned": returned,
        "turn_2022_reporting": base,
        "early_share": returned / base if base else float("nan"),
        "last_update_max": _max_update(rep["last_update"]) if "last_update" in rep else "",
        "source": "uf_election_lab",
        "page": UF_EARLY_VOTE_PAGE,
    }


def status(year: int = 2026) -> dict:
    pace = national_pace(year)
    return {
        "status": "ok" if pace.get("n_reporting", 0) else "no_reports",
        "year": year,
        "page": UF_EARLY_VOTE_PAGE,
        "csv": UF_EARLY_VOTE_CSV.get(year),
        "usep_2024_reference": USEP_HOME_2024,
        "n_reporting": pace.get("n_reporting", 0),
        "early_share": pace.get("early_share"),
        "last_update_max": pace.get("last_update_max", ""),
        "plan": "UF Election Lab 2026 early-vote CSV wired into forecast.early_vote; "
                "state logit offsets feed Stage A when present.",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    RAW_EV.mkdir(parents=True, exist_ok=True)
    df = build(2026, force=True)
    st = status(2026)
    pd.DataFrame([st]).to_csv(OUT / "early_vote_status.csv", index=False)
    pace = national_pace(2026)
    print("early_vote rows:", len(df), "| reporting:", int(df["reporting"].sum()))
    print("national pace (returned / 2022 turnout, reporting states):",
          f"{pace['early_share']:.4f}" if np.isfinite(pace["early_share"]) else "n/a",
          f"(n={pace['n_reporting']})")
    print("latest state update:", pace.get("last_update_max") or "n/a")
    print("source page:", UF_EARLY_VOTE_PAGE)
    offs = state_offsets(2026)
    if len(offs):
        top = offs.reindex(df.loc[df["reporting"], "state_po"]).dropna().sort_values(ascending=False)
        print("largest +offsets:", ", ".join(f"{s}={v:+.3f}" for s, v in top.head(5).items()))


if __name__ == "__main__":
    main()

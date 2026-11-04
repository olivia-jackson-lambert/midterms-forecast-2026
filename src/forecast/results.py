"""The 2026 results log: race calls and vote counts for every v1 race, from public sources.

    python -m forecast.results [--from-raw DIR]

One pull fetches AP's public results feed, the JSON behind AP's own results pages and the
embeds news sites use (no login or key):

    https://interactives.apelections.org/election-results/data-live/2026-11-03/results/national/metadata.json
    https://interactives.apelections.org/election-results/data-live/2026-11-03/results/national/progress.json

`metadata.json` holds each race's office, candidates and call status; `progress.json` its vote
counts, expected-vote share counted (AP's "eevp") and, for called races, the winner. Both are
served gzip-compressed whatever the request asks for, which is why a plain `curl` looks like a
stub; the bytes decompress to the full feed.

The raw files are kept under data/raw/results_2026/<pull time>/ (local, never committed); the
parsed rows are appended to results/results_log.csv, one row per v1 race per pull: 35 Senate and
36 governor rows (races.csv `race_id`) and 435 House rows (house_districts.csv `cd`).

Definitions follow v1 (forecast.races, forecast.house):
- `dem_votes` is the Democratic side's vote: every Democratic candidate's votes where v1's
  Democratic side is a Democrat (party totals, as in Louisiana's all-party ballot), or the named
  stand-in independent's votes where it is not (Nebraska, Idaho and South Dakota for the Senate;
  the House stand-ins). `rep_votes` is every Republican candidate's votes, or the Republican
  stand-in's in the House. `dem_share_2p` = dem_votes / (dem_votes + rep_votes).
- `pct_counted` is AP's expected-vote share counted, as a fraction (AP caps it at 0.99 until the
  count is final).
- `called` is true only when AP's call status is "Called"; a race sent to a runoff is not called.
  `winner_party` is D, R or I (any other party or none), from the winner's AP party code.

Nothing is interpolated: a field AP does not give is left blank.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import re
import time
from pathlib import Path

import pandas as pd
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("TURNOUT_DATA", ROOT / "data"))
RAW_RESULTS = DATA / "raw" / "results_2026"
V1 = ROOT / "forecasts" / "v1"
RESULTS = ROOT / "results"
LOG = RESULTS / "results_log.csv"

AP_BASE = "https://interactives.apelections.org/election-results/data-live/2026-11-03/results/national/"
AP_FILES = ("metadata.json", "progress.json")
UA = "turnout-first-2026 research (personal, non-commercial)"

AP_OFFICE = {"S": "senate", "G": "governor", "H": "house"}
PARTY = {"Dem": "D", "GOP": "R"}
AT_LARGE = {"AK", "DE", "ND", "SD", "VT", "WY"}

LOG_COLUMNS = ["pull_id", "pulled_at", "id", "office", "state", "ap_race_id", "call_status", "called",
               "winner_party", "winner_name", "called_at", "dem_side", "dem_votes", "rep_votes",
               "total_votes", "dem_share_2p", "pct_counted", "ap_last_updated", "source"]


# --------------------------------------------------------------------------- fetch
def _decode(raw: bytes) -> dict:
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


def pull(dest_root: Path = RAW_RESULTS) -> tuple[Path, str]:
    """Fetch both AP files once, a second apart, and keep the raw bytes. Returns (dir, pulled_at)."""
    pulled_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    stamp = pulled_at.strftime("%Y%m%dT%H%M%SZ")
    d = dest_root / stamp
    d.mkdir(parents=True, exist_ok=True)
    for name in AP_FILES:
        # curl, not requests: AP's CDN answers Python's HTTP client with 403 but serves curl
        # under the same self-identifying User-Agent. The bytes are gzip whatever is asked for.
        body = subprocess.run(["curl", "-sS", "--fail", "--max-time", "60", "-A", UA, AP_BASE + name],
                              check=True, capture_output=True).stdout
        (d / (name + ".gz" if body[:2] == b"\x1f\x8b" else name)).write_bytes(body)
        time.sleep(2)
    (d / "pull.json").write_text(json.dumps({"pulled_at": pulled_at.isoformat().replace("+00:00", "Z"),
                                             "base": AP_BASE, "files": list(AP_FILES)}, indent=1))
    return d, pulled_at.isoformat().replace("+00:00", "Z")


def load_raw(d: Path) -> tuple[dict, dict, str]:
    def read(name):
        p = d / (name + ".gz") if (d / (name + ".gz")).exists() else d / name
        return _decode(p.read_bytes())
    meta = json.loads((d / "pull.json").read_text())
    return read("metadata.json"), read("progress.json"), meta["pulled_at"]


# --------------------------------------------------------------------------- v1 races
def _surname(name: str) -> str:
    name = re.sub(r"\b(Jr|Sr|II|III|IV)\.?$", "", str(name).strip()).strip(" ,")
    return name.split()[-1].lower() if name else ""


def v1_races() -> pd.DataFrame:
    """Every v1 race with the Democratic and Republican side as v1 defined them."""
    r = pd.read_csv(V1 / "races.csv")
    sr = pd.DataFrame({"id": r["race_id"], "office": r["office"], "state": r["state"],
                       "special": r["special"].astype(bool),
                       "d_kind": r["d_side"], "d_name": r["dem_candidate"],
                       "r_kind": "republican", "r_name": r["rep_candidate"]})
    h = pd.read_csv(V1 / "house_districts.csv")
    has_d = h["dem_candidates"].notna()
    has_r = h["rep_candidates"].notna()
    stand = h["stand_in"].notna()
    hr = pd.DataFrame({"id": h["cd"], "office": "house", "state": h["state"], "special": False,
                       "d_kind": ["democrat" if d else ("independent_challenger" if s else "none")
                                  for d, s in zip(has_d, stand)],
                       "d_name": [None if d else (n if s else None) for d, s, n in zip(has_d, stand, h["stand_in"])],
                       "r_kind": ["republican" if rr else ("independent_challenger" if s and d else "none")
                                  for rr, s, d in zip(has_r, stand, has_d)],
                       "r_name": [None if rr else (n if s and d else None)
                                  for rr, s, d, n in zip(has_r, stand, has_d, h["stand_in"])]})
    return pd.concat([sr, hr], ignore_index=True)


def ap_key(v: dict) -> tuple | None:
    """(office, state, seat) for an AP race that v1 forecast, else None."""
    office = AP_OFFICE.get(v.get("officeID"))
    st = v.get("statePostal")
    if office is None or st == "US" or v.get("raceTypeID") not in ("G", "W", "L"):
        return None
    if office == "house":
        n = int(v["seatNum"])
        return office, st, "AL" if st in AT_LARGE else f"{n:02d}"
    if office == "senate":
        return office, st, "special" if v.get("raceTypeID") == "W" or "Unexpired" in str(v.get("seatName")) else ""
    return office, st, ""


def _v1_key(row) -> tuple:
    if row.office == "house":
        return "house", row.state, row.id.split("-")[1]
    if row.office == "senate":
        return "senate", row.state, "special" if row.special else ""
    return "governor", row.state, ""


# --------------------------------------------------------------------------- parse
def parse(metadata: dict, progress: dict, pulled_at: str, pull_id: str | None = None) -> pd.DataFrame:
    races = v1_races()
    ap = {}
    for rid, v in metadata.items():
        k = ap_key(v)
        if k is not None:
            if k in ap:
                raise ValueError(f"two AP races map to {k}: {ap[k]} and {rid}")
            ap[k] = rid
    rows = []
    for race in races.itertuples(index=False):
        rid = ap.get(_v1_key(race))
        base = {"pull_id": pull_id or pulled_at, "pulled_at": pulled_at, "id": race.id, "office": race.office,
                "state": race.state, "ap_race_id": rid, "source": AP_BASE + "progress.json"}
        if rid is None:
            rows.append(base | {"call_status": None, "called": False})
            continue
        m, p = metadata[rid], progress.get(rid, {})
        cands = {c["candidateID"]: dict(m["candidates"].get(c["candidateID"], {}), **c)
                 for c in p.get("candidates", [])}

        def side(kind, name, party):
            if kind == "none":
                return None
            if kind in ("democrat", "republican"):
                return sum(c["voteCount"] for c in cands.values() if c.get("party") == party)
            hits = [c for c in cands.values() if c.get("last", "").lower().split()[-1:] == [_surname(name)]]
            return hits[0]["voteCount"] if len(hits) == 1 else None

        dv = side(race.d_kind, race.d_name, "Dem")
        rv = side(race.r_kind, race.r_name, "GOP")
        status = m.get("raceCallStatus")
        called = status == "Called"
        winners = [c for c in cands.values() if c.get("winner") == "X"] if called else []
        w = winners[0] if len(winners) == 1 else None
        eevp = p.get("eevp")
        total = sum(c["voteCount"] for c in cands.values()) if cands else None
        rows.append(base | {
            "call_status": status, "called": bool(called and w is not None),
            "winner_party": PARTY.get(w.get("party"), "I") if w else None,
            "winner_name": " ".join(x for x in (w.get("first"), w.get("last")) if x) if w else None,
            "called_at": w.get("calledAt") if w else None,
            "dem_side": race.d_name if race.d_kind != "democrat" else "Democrats",
            "dem_votes": dv, "rep_votes": rv, "total_votes": total,
            "dem_share_2p": dv / (dv + rv) if dv and rv and total else None,
            "pct_counted": eevp / 100 if eevp is not None else None,
            "ap_last_updated": p.get("lastUpdated"),
        })
    out = pd.DataFrame(rows).reindex(columns=LOG_COLUMNS)
    for c in ("dem_votes", "rep_votes", "total_votes"):
        out[c] = out[c].astype("Int64")
    out["dem_share_2p"] = out["dem_share_2p"].astype(float).round(5)
    return out


def append_log(rows: pd.DataFrame, log: Path = LOG) -> pd.DataFrame:
    if log.exists():
        old = pd.read_csv(log)
        old = old[old["pull_id"] != rows["pull_id"].iloc[0]]
        rows = pd.concat([old, rows], ignore_index=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(log, index=False)
    return rows


def latest(log: Path = LOG) -> pd.DataFrame:
    """The most recent pull in the log, one row per v1 race."""
    d = pd.read_csv(log, dtype={"winner_party": "string"})
    return d[d["pull_id"] == d["pull_id"].max()].reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from-raw", type=Path, help="re-parse a pull already saved under data/raw/results_2026/")
    a = ap.parse_args()
    d, pulled_at = (a.from_raw, None) if a.from_raw else pull()
    meta, prog, pulled_at = load_raw(d)
    rows = parse(meta, prog, pulled_at, pull_id=d.name)
    append_log(rows)
    unmatched = rows["ap_race_id"].isna().sum()
    print(f"pull {d.name}: {len(rows)} v1 races, {int(rows['called'].sum())} called, "
          f"{unmatched} not found in the feed")
    print(rows.groupby("office")["called"].agg(["size", "sum"]).to_string())


if __name__ == "__main__":
    main()

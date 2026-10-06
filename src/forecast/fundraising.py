"""Senate nominees' fundraising to 30 June of the election year, from the FEC.

Only what was public by 1 October counts: receipts for this election up to 30 June of the
election year (cycle-to-date on the June quarterly report, filed by 15 July), for the
Democratic-side and Republican nominees named in forecast.races.
About ten requests per year; the key allows 60 an hour. Governors are not in FEC data, so the feature is Senate only.

Feature: log(Democratic-side receipts / Republican receipts), each floored at $25,000 so a
nominee who raised almost nothing does not produce an infinite ratio.

Needs a free api.data.gov key in the environment as FEC_API_KEY (never stored in the repo).

    python -m forecast.fundraising
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata

import numpy as np
import pandas as pd
import requests

from .ingest import OUT, RAW, UA

API = "https://api.open.fec.gov/v1"
RAW_FEC = RAW / "fec"
FLOOR = 25_000
PAUSE = 1.1          # seconds between requests (the key allows 60 an hour; responses are cached)


def _get(path: str, **params) -> dict:
    """GET from OpenFEC, caching each response under data/raw/fec/api/ (the key is never stored)."""
    tag = hashlib.sha1(json.dumps([path, sorted(params.items())], default=str).encode()).hexdigest()[:16]
    cache = RAW_FEC / "api" / f"{re.sub(r'[^a-z]+', '_', path.lower()).strip('_')}_{tag}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    out = _fetch(path, **params)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


def _fetch(path: str, **params) -> dict:
    key = os.environ.get("FEC_API_KEY")
    if not key:
        raise SystemExit("Set FEC_API_KEY (a free key from https://api.data.gov/signup/).")
    r = requests.get(f"{API}{path}", params={**params, "api_key": key}, headers=UA, timeout=30)
    time.sleep(PAUSE)
    if r.status_code == 429:
        wait = int(r.headers.get("retry-after", 3600)) // 60
        raise SystemExit(f"FEC hourly limit reached; try again in about {wait} minutes (cached responses are kept).")
    if r.status_code == 404:                  # e.g. a committee with no reports that cycle
        return {"results": []}
    if not r.ok:                              # never echo the URL: it carries the key
        raise RuntimeError(f"FEC API error {r.status_code} on {path}")
    return r.json()


def _letters(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|esq|mr|mrs|ms|dr)\b\.?", " ", s)
    return re.sub(r"[^a-z]", "", s)


def _matches(fec_name: str, nominee: str) -> bool:
    """FEC lists 'LAST, FIRST'; the nominee's name must end with that surname, ignoring
    suffixes, accents and spaces ('VAN HOLLEN, CHRIS' matches 'Chris Van Hollen')."""
    last = _letters(str(fec_name).split(",")[0])
    if last and _letters(nominee).endswith(last):
        return True
    # Filed under another surname with the nominee's as a middle name ("ARENHOLZ, ASHLEY HINSON").
    words = [_letters(w) for w in str(nominee).split()]
    fec = {_letters(w) for w in re.split(r"[ ,]+", str(fec_name))}
    return len(words) >= 2 and words[0] in fec and words[-1] in fec


def senate_candidates(year: int) -> pd.DataFrame:
    """Every Senate candidate whose election years include `year`, nationwide (FEC sometimes
    files the state wrongly: Van Hollen is listed under DC)."""
    rows, page = [], 1
    while True:
        d = _get("/candidates/search/", office="S", election_year=year, per_page=100, page=page)
        rows += [{"name": r["name"], "state": r.get("state"), "party": r.get("party"),
                  "committees": [c["committee_id"] for c in r.get("principal_committees", [])]}
                 for r in d.get("results", [])]
        if page >= (d.get("pagination") or {}).get("pages", 1):
            break
        page += 1
    return pd.DataFrame(rows)


def year_to_date(committees: list[str], year: int, report_type: str, ending: int) -> dict[str, float]:
    """Cycle-to-date receipts (Form 3 column B, which the API calls total_receipts_ytd) on each
    committee's latest filing of one report type whose coverage ends in year `ending` (a two-year
    cycle holds two year-end reports; only the first was public before the election)."""
    best, page = {}, 1
    while True:
        d = _get("/reports/house-senate/", committee_id=committees, cycle=year, report_type=report_type,
                 per_page=100, page=page)
        for r in d.get("results", []):
            if str(r.get("coverage_end_date", ""))[:4] != str(ending):
                continue
            ctd = r.get("total_receipts_ytd")       # on Form 3 this column is cycle-to-date
            rank = (ctd is not None, bool(r.get("most_recent")), str(r.get("receipt_date") or ""))
            c = r["committee_id"]
            if c not in best or rank > best[c][0]:
                best[c] = (rank, float(ctd or 0))
        if page >= (d.get("pagination") or {}).get("pages", 1):
            break
        page += 1
    return {c: v for c, (_, v) in best.items()}


def nominee_receipts(year: int) -> pd.DataFrame:
    """Receipts for this election to 30 June of the election year (cycle-to-date on the June
    report, or on the previous year-end report) for each Senate race's Democratic-side and
    Republican nominees. NaN where the FEC has no reports for the nominee yet."""
    cache = RAW_FEC / f"nominee_receipts_{year}.csv"
    if cache.exists():
        return pd.read_csv(cache)
    RAW_FEC.mkdir(parents=True, exist_ok=True)
    races = pd.read_parquet(OUT / "races.parquet")
    races = races[(races["year"] == year) & races["office"].eq("SEN") & races["d_side"].ne("not_two_party")]
    cands = senate_candidates(year)
    picks = []
    for _, r in races.iterrows():
        for side, name in (("dem", r["dem_candidate"]), ("rep", r["rep_candidate"])):
            m = cands[cands["name"].map(lambda n: _matches(n, name))]
            m = m[m["state"] == r["state_po"]] if (m["state"] == r["state_po"]).any() else m
            first = _letters(str(name).split()[0])
            same_first = m[m["name"].map(lambda n: first in {_letters(w) for w in re.split(r"[ ,]+", n)})]
            picks.append((r["race_id"], side, name, same_first if len(same_first) else m))
    committees = sorted({c for *_, m in picks for cs in m["committees"] for c in cs})
    prev = {}
    for i in range(0, len(committees), 50):           # keep URLs a sensible length
        chunk = committees[i:i + 50]
        ye = year_to_date(chunk, year, "YE", ending=year - 1)
        q2 = year_to_date(chunk, year, "Q2", ending=year)
        for c in chunk:
            # Cycle-to-date receipts on the June report; else on the previous year-end report;
            # else unknown (no reports yet, which is not the same as raising nothing).
            prev[c] = q2.get(c, ye.get(c, np.nan))
    rows = []
    for race_id, side, name, m in picks:
        # Several filers with the nominee's name (two Dan Sullivans in Alaska in 2026): the one
        # who raised the most is the campaign on the ballot.
        totals = [(np.nansum([prev.get(c, np.nan) for c in cs]) if any(np.isfinite(prev.get(c, np.nan)) for c in cs)
                   else -1.0, n) for n, cs in zip(m["name"], m["committees"])]
        total, fec_name = max(totals) if totals else (-1.0, "")
        total = np.nan if total < 0 else total
        rows.append({"race_id": race_id, "side": side, "nominee": name, "fec_name": fec_name,
                     "receipts_to_june": total})
    out = pd.DataFrame(rows)
    out.to_csv(cache, index=False)
    return out


def feature(year: int) -> pd.Series:
    """log(Democratic-side / Republican receipts to 30 June), by race_id (Senate only)."""
    r = nominee_receipts(year).pivot_table(index="race_id", columns="side", values="receipts_to_june",
                                           aggfunc="sum", dropna=False)
    # Unknown on either side (no reports yet): no fundraising signal for that race.
    return np.log(r["dem"].clip(lower=FLOOR) / r["rep"].clip(lower=FLOOR)).fillna(0.0).rename("fundraising")


def main() -> None:
    for y in (2018, 2022, 2026):
        n = nominee_receipts(y)
        unmatched = n[n["fec_name"].fillna("").eq("")]
        f = feature(y)
        print(f"{y}: {n['race_id'].nunique()} Senate races, {len(unmatched)} nominees with no FEC match "
              f"{unmatched['nominee'].tolist()}; log ratio mean {f.mean():+.2f}, sd {f.std():.2f}")


if __name__ == "__main__":
    main()

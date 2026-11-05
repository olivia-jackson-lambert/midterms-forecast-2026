"""Read forecasters' archived pages (Internet Archive) for the comparison with other forecasts.

    python -m forecast.compare_archive

Every page is fetched as the raw archived bytes (`web.archive.org/web/<timestamp>id_/<url>`), at
one request a second. Each source writes results/comparisons/<source>_<date>.csv with the
snapshot URL, the snapshot time and the page's own "last updated" date.

Sources handled here
    cook     Cook Political Report ratings pages (Senate, governor, House): the free summary
             lists every race by category.
    t270     270toWin's copies of forecasters' House maps (used for Split Ticket's House ratings,
             which have no archived page of their own). The digit codes in 270toWin's map string
             are decoded with a mapping checked against Cook's own page (see `T270_CODES`).

Sabato's Crystal Ball is transcribed by hand from its map images into
results/comparisons/sabato_*.csv (see the `note` column there); it is not parsed here.
"""
from __future__ import annotations

import gzip
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

from .compare_sources import OUTDIR, ROOT, STATES, now_utc, v1_house_ids, v1_races

UA = {"User-Agent": "midterms-forecast-2026 comparison (public research)"}
WAYBACK = "https://web.archive.org/web/{ts}id_/{url}"

RATINGS = ["Solid D", "Likely D", "Lean D", "Toss Up", "Lean R", "Likely R", "Solid R"]


def fetch(ts: str, url: str) -> str:
    time.sleep(1.0)
    r = requests.get(WAYBACK.format(ts=ts, url=url), headers=UA, timeout=120)
    r.raise_for_status()
    b = r.content
    if b[:2] == b"\x1f\x8b":
        b = gzip.decompress(b)
    return b.decode("utf-8", "ignore")


def page_text(html: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).replace("&nbsp;", " ")


# ---------------------------------------------------------------------- Cook

COOK_PAGES = {
    "senate": "https://www.cookpolitical.com/ratings/senate-race-ratings",
    "governor": "https://www.cookpolitical.com/ratings/governor-race-ratings",
    "house": "https://www.cookpolitical.com/ratings/house-race-ratings",
}
COOK_HEAD = {"Solid D": "Solid Democrat", "Likely D": "Likely Democrat", "Lean D": "Lean Democrat",
             "Toss Up": "Toss Up", "Lean R": "Lean Republican", "Likely R": "Likely Republican",
             "Solid R": "Solid Republican"}


def parse_cook(text: str, office: str) -> tuple[str | None, dict[str, str]]:
    """(page date, {state or district: rating}) from a Cook ratings page's text."""
    m = re.search(r"CPR \w+ Race Ratings (\w{3} \d{1,2}, \d{4})", text)
    updated = m.group(1) if m else None
    start = text.find("Solid D Solid Democrat")
    end = text.find("Hover over", start)
    body = text[start:end]
    out = {}
    for i, r in enumerate(RATINGS):
        a = body.find(f"{r} {COOK_HEAD[r]} (")
        b = body.find(f"{RATINGS[i + 1]} {COOK_HEAD[RATINGS[i + 1]]} (") if i + 1 < len(RATINGS) else len(body)
        seg = body[a:b]
        pat = r"\b([A-Z]{2}-(?:\d{2}|AL))\b" if office == "house" else r"(?<![A-Za-z])([A-Z]{2})(?= [A-Z])"
        for code in re.findall(pat, seg):
            if office != "house" and code not in STATES.values():
                continue
            out[code] = r
    return updated, out


def collect_cook(snapshots: dict[str, dict[str, str]], label: str) -> Path:
    """snapshots: office -> {'ts': wayback timestamp}. Writes cook_<label>.csv."""
    races, house = v1_races(), v1_house_ids()
    captured = now_utc()
    rows = []
    for office, ts in snapshots.items():
        url = COOK_PAGES[office]
        updated, ratings = parse_cook(page_text(fetch(ts, url)), office)
        for key, rating in ratings.items():
            if office == "house":
                rid = key if key in house else None
            else:
                sel = races[(races.state == key) & (races.office == office)]
                rid = sel.race_id.iloc[0] if len(sel) == 1 else None
            if rid is None:
                continue
            rows.append({"forecaster": "Cook Political Report", "office": office, "id": rid, "rating": rating,
                         "page_updated": updated, "snapshot": ts,
                         "source_url": WAYBACK.format(ts=ts, url=url).replace("id_/", "/"),
                         "captured": captured})
    path = OUTDIR / f"cook_{label}.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"{path.relative_to(ROOT)}: {len(rows)} rows")
    return path


# ---------------------------------------------------------------------- 270toWin House maps

# 270toWin's House map string has one digit per district, in the order of the page's
# `map_d3.races` keys (state FIPS + district). The digit codes below were matched against
# Cook's own page for the same date (Cook House ratings of 16 October, archived 22 October
# 18:51 UTC, against 270toWin's "Cook Political Report" map as of 16 October on the 22 October
# 01:51 UTC snapshot): each digit corresponded to exactly one Cook category in all 435 districts.
T270_CODES = {"0": "Toss Up", "1": "Solid D", "2": "Solid R", "3": "Likely D", "4": "Likely R",
              "5": "Lean D", "6": "Lean R"}
FIPS = {1: "AL", 2: "AK", 4: "AZ", 5: "AR", 6: "CA", 8: "CO", 9: "CT", 10: "DE", 12: "FL", 13: "GA",
        15: "HI", 16: "ID", 17: "IL", 18: "IN", 19: "IA", 20: "KS", 21: "KY", 22: "LA", 23: "ME", 24: "MD",
        25: "MA", 26: "MI", 27: "MN", 28: "MS", 29: "MO", 30: "MT", 31: "NE", 32: "NV", 33: "NH", 34: "NJ",
        35: "NM", 36: "NY", 37: "NC", 38: "ND", 39: "OH", 40: "OK", 41: "OR", 42: "PA", 44: "RI", 45: "SC",
        46: "SD", 47: "TN", 48: "TX", 49: "UT", 50: "VT", 51: "VA", 53: "WA", 54: "WV", 55: "WI", 56: "WY"}


def t270_key_to_cd(key: str) -> str:
    st, d = FIPS[int(key[:2])], int(key[2:])
    return f"{st}-AL" if d == 0 else f"{st}-{d:02d}"


def parse_t270_house(html: str):
    """(district ids in map order, {map name: map string}, page map string, page date)."""
    m = re.search(r"map_d3\.races = (\{.*?\});\n", html, re.S)
    keys = [t270_key_to_cd(k) for k in json.loads(m.group(1))]
    maps = {mm.group(1): mm.group(2) for mm in re.finditer(
        r'"name":"((?:[^"\\]|\\.)+)","description":"(?:[^"\\]|\\.)*","hashid":"\w+","map_string":"(\d+)"', html)}
    page = re.search(r"new HouseMultiDistrictsMap\('(\d+)'", html)
    created = re.search(r"date_created_formatted = '([^']+)'", html)
    return keys, maps, (page.group(1) if page else None), (created.group(1) if created else None)


def decode_t270(keys: list[str], s: str) -> dict[str, str]:
    return {cd: T270_CODES[c] for cd, c in zip(keys, s)}


def collect_t270_house(ts: str, slug: str, forecaster: str, label: str) -> Path:
    url = f"https://www.270towin.com/2026-house-election/{slug}"
    html = fetch(ts, url)
    keys, maps, page, created = parse_t270_house(html)
    house = v1_house_ids()
    captured = now_utc()
    rows = [{"forecaster": forecaster, "office": "house", "id": cd, "rating": r,
             "page_updated": created, "snapshot": ts, "via": "270toWin",
             "source_url": WAYBACK.format(ts=ts, url=url).replace("id_/", "/"), "captured": captured}
            for cd, r in decode_t270(keys, page).items() if cd in house]
    path = OUTDIR / f"{label}.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"{path.relative_to(ROOT)}: {len(rows)} rows")
    return path


def main():
    collect_cook({"senate": "20261022142742", "governor": "20261022142956", "house": "20261022185107"},
                 "2026-10-22")
    collect_cook({"senate": "20261103130008", "governor": "20261027190609", "house": "20261103101609"},
                 "final")
    collect_t270_house("20261022015123", "split-ticket-2026-house-ratings", "Split Ticket",
                       "splitticket_house_2026-10-22")
    collect_t270_house("20261102153155", "split-ticket-2026-house-ratings", "Split Ticket",
                       "splitticket_house_final")


if __name__ == "__main__":
    main()

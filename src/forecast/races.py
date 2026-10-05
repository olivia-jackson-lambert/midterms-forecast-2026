"""Senate and governor races for 2018, 2022 and 2026: incumbents, open seats and nominees.

Parsed from Wikipedia's "<year> United States Senate elections" and "... gubernatorial
elections" pages, saved under data/raw/races/ so every run sees the same snapshot. The 2026
pages are re-fetched with `--refresh` (they change as nominees are settled); 2018 and 2022
use the current pages, whose incumbency and nominee columns were all settled before October.

For 2018 and 2022 the pages also give each candidate's certified percentage; `result_dem_2p` is
the Democratic side's share of the two-party vote from those (summing all of a party's candidates
in all-party primaries such as Louisiana's). Stage B uses these as the race results.

Open seat: the incumbent is retiring, term-limited, lost renomination, resigned or is an
interim appointee who cannot run. Otherwise the incumbent (including an appointee) is running.

The vote model works in Democratic two-party share. Where no Democrat is on the ballot and the
main challenger is an independent (Nebraska and Idaho in 2026), that independent stands in for
the Democratic side and the race is flagged `independent_challenger`; the model gives those
races extra uncertainty. Races with no Democrat-or-independent against a Republican (or no
Republican) are flagged `not_two_party` and are left out of training and scoring.

    python -m forecast.races [--refresh]
"""
from __future__ import annotations

import re
import sys
from io import StringIO

import pandas as pd
import requests

from .ingest import OUT, RAW, UA

RAW_RACES = RAW / "races"
YEARS = (2018, 2022, 2026)
HISTORY_YEARS = (2012, 2014, 2016, 2018, 2020, 2022, 2024)      # for incumbents' previous results
PAGE = "https://en.wikipedia.org/wiki/{year}_United_States_{kind}_elections"

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
    "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}
OPEN = re.compile(r"retir|term[- ]limited|lost renomination|resign|ineligible|died|not seeking", re.I)
DEM = {"Democratic", "DFL", "Democratic–NPL", "Democratic-NPL", "Democratic–Farmer–Labor"}


def _page(year: int, kind: str, refresh: bool = False) -> str:
    RAW_RACES.mkdir(parents=True, exist_ok=True)
    path = RAW_RACES / f"{year}_United_States_{kind}_elections.html"
    if refresh or not path.exists():
        r = requests.get(PAGE.format(year=year, kind=kind), headers=UA, timeout=60)
        r.raise_for_status()
        path.write_text(r.text)
    return path.read_text()


def _clean(s) -> str:
    return re.sub(r"\[[^\]]*\]", "", str(s)).replace("\xa0", " ").strip()


def candidates(cell: str) -> list[tuple[str, str, float | None]]:
    """'▌Name (Party) 50.1% ▌Other (Party)' -> [(name, party, pct or None), ...]."""
    out = []
    cell = re.split(r"Runoff:|Instant[- ]runoff|Second round", _clean(cell), flags=re.I)[0]   # general election only
    for part in cell.split("▌")[1:]:
        m = re.match(r"\s*(?:Y\s+)?(.+?)\s*\(([^)]+)\)\s*([\d.]+)?\s*%?", part)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip(), float(m.group(3)) if m.group(3) else None))
    return out


def _party_code(p: str) -> str:
    p = _clean(p)
    if p in DEM or "Democratic" in p:          # includes fusion lines such as "Progressive/Democratic"
        return "D"
    if p.startswith("Republican"):
        return "R"
    return "I"


def _tables(year: int, kind: str, refresh: bool) -> list[tuple[pd.DataFrame, bool]]:
    """(table, is_special) for each state race table on the page."""
    out = []
    for t in pd.read_html(StringIO(_page(year, kind, refresh))):
        cols = [_clean(c[-1] if isinstance(c, tuple) else c) for c in t.columns]
        if not any("andidates" in c for c in cols) or not ({"Senator", "Governor", "Incumbent"} & set(cols)):
            continue
        if "Territory" in cols or "States" in cols and kind == "Senate":
            continue
        t = t.copy()
        t.columns = cols
        states = t[cols[0]].map(_clean).str.replace(r"\s*\(Class \d\)", "", regex=True)
        if not states.isin(STATES).mean() > 0.9:
            continue
        out.append((t.assign(_state=states), "(Class" in " ".join(t[cols[0]].astype(str))))
    return out


def races(year: int, refresh: bool = False) -> pd.DataFrame:
    rows = []
    for kind, office in (("Senate", "SEN"), ("gubernatorial", "GOV")):
        for t, special in _tables(year, kind, refresh):
            person = next(c for c in ("Senator", "Governor", "Incumbent") if c in t.columns)
            status = next(c for c in t.columns if re.match(r"(Status|Results?)$", c))
            cand = next(c for c in t.columns if "andidates" in c)
            for _, r in t.iterrows():
                if r["_state"] not in STATES:            # e.g. "Wisconsin (recall)" in 2012
                    continue
                cands = candidates(r[cand])
                dems = [n for n, p, _ in cands if _party_code(p) == "D"]
                reps = [n for n, p, _ in cands if _party_code(p) == "R"]
                inds = [n for n, p, _ in cands if _party_code(p) == "I" and p.startswith(("Independent", "Nonpartisan"))]
                inc_party = _party_code(r["Party"])
                stat = _clean(r[status])
                open_seat = bool(OPEN.search(stat))
                # Democratic side: an independent incumbent who caucuses with Democrats (King,
                # Sanders); else the Democratic nominee; else, with no Democrat at all, the
                # first-listed independent challenger to a Republican.
                if inc_party == "I" and not open_seat:
                    d_side, d_kind = _clean(r[person]).split(" (")[0], "independent_incumbent"
                elif dems:
                    d_side, d_kind = dems[0], "democrat"
                elif reps and any(v is not None for _, _, v in cands):
                    # Past race, no Democrat: the strongest non-Republican (e.g. Vermont 2020's
                    # Progressive nominee, who also won the Democratic primary).
                    others = sorted([c for c in cands if _party_code(c[1]) != "R" and c[2] is not None],
                                    key=lambda c: -c[2])
                    d_side, d_kind = (others[0][0], "independent_challenger") if others else (None, "not_two_party")
                elif inds and reps:
                    d_side, d_kind = inds[0], "independent_challenger"
                else:
                    d_side, d_kind = None, "not_two_party"
                if not reps:
                    d_kind = "not_two_party"       # e.g. two Democrats in California's top-two final
                # Past results: if the top two finishers were not the Democratic side and a
                # Republican (e.g. Alaska 2022, Murkowski against Tshibaka), it was not a D-R race.
                ranked = sorted([c for c in cands if c[2] is not None], key=lambda c: -c[2])
                if len(ranked) >= 2 and d_kind != "not_two_party":
                    top = {_party_code(ranked[0][1]), _party_code(ranked[1][1])}
                    if top == {"R"} or top == {"D"}:
                        d_kind = "not_two_party"
                pct = {n: v for n, _, v in cands if v is not None}
                # Party totals (all of a party's candidates, which matters in all-party primaries
                # such as Louisiana's); the Democratic side is its nominee or stand-in independent.
                d_total = sum(v for n, p, v in cands if v is not None and
                              (_party_code(p) == "D" if d_kind == "democrat" else n == d_side))
                r_total = sum(v for n, p, v in cands if v is not None and _party_code(p) == "R")
                rows.append({
                    "year": year, "state_po": STATES[r["_state"]], "office": office, "special": special,
                    "candidates": "; ".join(n for n, _, _ in cands),
                    "dem_pct": pct.get(d_side) if d_side else None, "rep_pct": pct.get(reps[0]) if reps else None,
                    "result_dem_2p": d_total / (d_total + r_total) if d_total and r_total else None,
                    "incumbent": _clean(r[person]).split(" (")[0], "incumbent_party": inc_party,
                    "status": stat, "open_seat": open_seat,
                    "dem_candidate": d_side, "rep_candidate": reps[0] if reps else None,
                    "d_side": d_kind,
                })
    df = pd.DataFrame(rows)
    # Incumbency code for the model: +1 Democratic-side incumbent running, -1 Republican, 0 open.
    df["incumbency"] = 0.0
    running = ~df["open_seat"]
    df.loc[running & df["incumbent_party"].isin(["D", "I"]), "incumbency"] = 1.0
    df.loc[running & df["incumbent_party"].eq("R"), "incumbency"] = -1.0
    df["race_id"] = df["year"].astype(str) + "-" + df["state_po"] + "-" + df["office"] + df["special"].map({True: "S", False: ""})
    return df.sort_values(["office", "special", "state_po"]).reset_index(drop=True)


def _surname(name) -> str:
    """First initial and surname ("Darline Graham" -> "d graham"), so namesakes do not match."""
    words = [w for w in re.sub(r"[^A-Za-z\- ]", " ", str(name)).lower().split() if w not in {"jr", "sr", "ii", "iii"}]
    return f"{words[0][0]} {words[-1]}" if words else ""


def add_incumbent_history(df: pd.DataFrame, past: pd.DataFrame) -> pd.DataFrame:
    """For each running incumbent, their last general election for the same office: the year
    and the Democratic side's two-party share in it (NaN if they have not run, e.g. appointees,
    or that race was not a Democrat-Republican contest)."""
    df = df.copy()
    df["prev_year"], df["prev_dem_2p"] = pd.NA, float("nan")
    for i, r in df[~df["open_seat"]].iterrows():
        sur = _surname(r["incumbent"])
        cand = past[(past["state_po"] == r["state_po"]) & (past["office"] == r["office"]) & (past["year"] < r["year"])]
        cand = cand[cand["candidates"].map(lambda c: sur in {_surname(n) for n in str(c).split("; ")})]
        if len(cand):
            last = cand.sort_values("year").iloc[-1]
            df.at[i, "prev_year"] = int(last["year"])
            df.at[i, "prev_dem_2p"] = last["result_dem_2p"] if last["d_side"] != "not_two_party" else float("nan")
    return df


def all_races(refresh: bool = False) -> pd.DataFrame:
    past = pd.concat([races(y) for y in HISTORY_YEARS], ignore_index=True)
    out = pd.concat([races(y, refresh=refresh and y == 2026) for y in YEARS], ignore_index=True)
    return add_incumbent_history(out, past)


def main() -> None:
    refresh = "--refresh" in sys.argv
    df = all_races(refresh)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / "races.parquet", index=False)
    for y, d in df.groupby("year"):
        print(y, d.groupby(["office", "special"]).size().to_dict(),
              "| open:", int(d["open_seat"].sum()), "| d_side:", d["d_side"].value_counts().to_dict())
    odd = df[df["d_side"] != "democrat"]
    print(odd[["race_id", "incumbent", "status", "dem_candidate", "rep_candidate", "d_side"]].to_string(index=False))


if __name__ == "__main__":
    main()

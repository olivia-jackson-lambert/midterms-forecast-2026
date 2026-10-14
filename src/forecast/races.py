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
HISTORY_YEARS = (2010, 2012, 2014, 2016, 2018, 2020, 2022, 2024)   # previous statewide results
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
# The incumbent shares a name with another candidate on the ballot.
NAMESAKES = {(2026, "AK", "SEN"): "Dan S. Sullivan"}   # incumbent Daniel S. Sullivan; Dan J. Sullivan also running
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


def _row(year: int, state: str, office: str, special: bool, cand_text, inc_text, party_text, status_text) -> dict:
    """One race: classify the sides, find the Democratic-side stand-in and the party totals."""
    cands = candidates(cand_text)
    dems = [n for n, p, _ in cands if _party_code(p) == "D"]
    reps = [n for n, p, _ in cands if _party_code(p) == "R"]
    inds = [n for n, p, _ in cands if _party_code(p) == "I" and p.startswith(("Independent", "Nonpartisan"))]
    inc_party = _party_code(party_text)
    stat = _clean(status_text)
    open_seat = bool(OPEN.search(stat))
    inc_name = _clean(inc_text).split(" (")[0]
    # Democratic side: an independent incumbent who caucuses with Democrats (King,
    # Sanders); else the Democratic nominee; else, with no Democrat at all, the
    # first-listed independent challenger to a Republican.
    if inc_party == "I" and not open_seat:
        d_side, d_kind = inc_name, "independent_incumbent"
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
    # Several Republicans on the November ballot (Alaska's top four): the incumbent if
    # running, else the past race's leader, else no single name.
    po = STATES[state]
    if len(reps) <= 1:
        rep_name = reps[0] if reps else None
    elif (year, po, office) in NAMESAKES:
        rep_name = NAMESAKES[(year, po, office)]
    elif inc_party == "R" and not open_seat and inc_name in reps:
        rep_name = inc_name
    elif any(n in pct for n in reps):
        rep_name = max((n for n in reps if n in pct), key=pct.get)
    else:
        rep_name = "Several Republicans (top four)"
    # Party totals (all of a party's candidates, which matters in all-party primaries
    # such as Louisiana's); the Democratic side is its nominee or stand-in independent.
    d_total = sum(v for n, p, v in cands if v is not None and
                  (_party_code(p) == "D" if d_kind == "democrat" else n == d_side))
    r_total = sum(v for n, p, v in cands if v is not None and _party_code(p) == "R")
    return {
        "year": year, "state_po": po, "office": office, "special": special,
        "candidates": "; ".join(n for n, _, _ in cands),
        "dem_pct": pct.get(d_side) if d_side else None, "rep_pct": pct.get(reps[0]) if reps else None,
        "result_dem_2p": d_total / (d_total + r_total) if d_total and r_total else None,
        "incumbent": inc_name, "incumbent_party": inc_party,
        "status": stat, "open_seat": open_seat,
        "dem_candidate": d_side, "rep_candidate": rep_name,
        "d_side": d_kind,
        "d_side_party": next((p for n, p, _ in cands if n == d_side), None),
        # every name on each side, to match a person to the side they ran on
        "dem_names": "; ".join(dems if d_kind == "democrat" else [d_side] if d_side else []),
        "rep_names": "; ".join(reps),
    }


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
                rows.append(_row(year, r["_state"], office, special, r[cand], r[person], r["Party"], r[status]))
    df = pd.DataFrame(rows)
    # Incumbency code for the model: +1 Democratic-side incumbent running, -1 Republican, 0 open.
    df["incumbency"] = 0.0
    running = ~df["open_seat"]
    df.loc[running & df["incumbent_party"].isin(["D", "I"]), "incumbency"] = 1.0
    df.loc[running & df["incumbent_party"].eq("R"), "incumbency"] = -1.0
    df["race_id"] = df["year"].astype(str) + "-" + df["state_po"] + "-" + df["office"] + df["special"].map({True: "S", False: ""})
    return df.sort_values(["office", "special", "state_po"]).reset_index(drop=True)


def house_at_large(year: int, refresh: bool = False) -> pd.DataFrame:
    """The at-large US House races of a year. One seat covers the whole state, so these are
    statewide elections. From Wikipedia's "<year> United States House of Representatives
    elections"; used only as history for the nominee track record."""
    rows = []
    for t in pd.read_html(StringIO(_page(year, "House_of_Representatives", refresh))):
        cols = [_clean(c[-1] if isinstance(c, tuple) else c) for c in t.columns]
        cand = [c for c in cols if "andidates" in c]
        person = [c for c in cols if c in ("Member", "Representative", "Incumbent")]
        status = [c for c in cols if re.match(r"(Status|Results?)$", c)]
        if not (cand and person and status and "Party" in cols):
            continue
        t = t.copy()
        t.columns = cols
        special = not any("PVI" in c for c in cols)
        for _, r in t.iterrows():
            m = re.match(r"(.+?)\s+at[- ]large", _clean(r[cols[0]]), flags=re.I)
            if m and m.group(1) in STATES:               # territories send delegates, not members
                rows.append(_row(year, m.group(1), "HOU", special, r[cand[0]], r[person[0]], r["Party"], r[status[0]]))
    return pd.DataFrame(rows)


def statewide_history() -> pd.DataFrame:
    """Every statewide general election in HISTORY_YEARS: Senate, governor and at-large House."""
    return pd.concat([*(races(y) for y in HISTORY_YEARS), *(house_at_large(y) for y in HISTORY_YEARS)],
                     ignore_index=True)


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


# Stand-ins for the Democratic side that count as one in a person's history: independents, not
# minor parties (a Libertarian's result says nothing about a Democrat's).
STAND_IN_PARTIES = ("Independent", "Nonpartisan", "Progressive")


def _ran_as(r, sur: str) -> str | None:
    """"D" or "R" if the person with this surname key was the Democratic side or a Republican in race r."""
    # A race that was not a Democrat-Republican contest still counts as the person's last race
    # (their record is then zero), the same on both sides.
    dem_ok = r["d_side"] in ("democrat", "independent_incumbent", "not_two_party") or (
        r["d_side"] == "independent_challenger" and str(r.get("d_side_party")).startswith(STAND_IN_PARTIES))
    if dem_ok and sur in {_surname(n) for n in str(r["dem_names"]).split("; ") if n}:
        return "D"
    if sur in {_surname(n) for n in str(r["rep_names"]).split("; ") if n}:
        return "R"
    return None


def add_nominee_history(df: pd.DataFrame, past: pd.DataFrame) -> pd.DataFrame:
    """For each side's nominee, their most recent earlier statewide general election in `past`
    (Senate, governor or at-large House, same state, first initial plus surname): its year, office,
    the side they ran on there ("D" or "R") and the Democratic side's two-party share in it (NaN if
    that race was not a Democrat-Republican contest). Columns dem_prev_* and rep_prev_*."""
    df = df.copy()
    past = past.sort_values(["year", "special"], ascending=[True, False])      # a general beats a special in a tie
    by_state = {k: g for k, g in past.groupby("state_po")}
    for side in ("dem", "rep"):
        cols = {c: [] for c in ("year", "office", "side", "dem_2p")}
        for _, r in df.iterrows():
            name = r[f"{side}_candidate"]
            hit = None
            if isinstance(name, str) and not name.startswith("Several"):
                sur = _surname(name)
                for _, p in by_state.get(r["state_po"], past.iloc[0:0]).iterrows():
                    if p["year"] < r["year"] and (w := _ran_as(p, sur)):
                        hit = (p, w)                      # sorted by year: the last hit is the most recent
            if hit:
                p, w = hit
                two = p["d_side"] != "not_two_party" and pd.notna(p["result_dem_2p"])
                vals = (int(p["year"]), p["office"], w, p["result_dem_2p"] if two else float("nan"))
            else:
                vals = (pd.NA, pd.NA, pd.NA, float("nan"))
            for c, v in zip(cols, vals):
                cols[c].append(v)
        for c, v in cols.items():
            df[f"{side}_prev_{c}"] = v
    return df


def all_races(refresh: bool = False) -> pd.DataFrame:
    past = statewide_history()
    out = pd.concat([races(y, refresh=refresh and y == 2026) for y in YEARS], ignore_index=True)
    return add_nominee_history(add_incumbent_history(out, past), past)


def main(refresh: bool | None = None) -> None:
    if refresh is None:
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

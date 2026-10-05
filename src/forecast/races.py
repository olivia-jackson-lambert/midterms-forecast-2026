"""2026 Senate and governor race list: incumbency, open seats and specials.

Curated from Ballotpedia's 2026 Senate and gubernatorial election pages (public, reachable
via WebFetch in October 2026). Ballotpedia's live HTML often returns empty from this
environment, so the tables below are checked-in constants rather than a live scrape.
Refresh against Ballotpedia before publishing the forecast.

    python -m forecast.races
"""
from __future__ import annotations

import pandas as pd

from .features import GOVERNOR, SENATE
from .ingest import OUT

# As of Ballotpedia, Sept–Oct 2026: incumbents who withdrew / are not seeking re-election.
# South Carolina: Lindsey Graham withdrew; Ballotpedia lists Darline Graham as the seat's
# pre-election holder after a 2026 change — treat as open for forecasting until nominees firm.
SENATE_OPEN = {"AL", "IL", "IA", "KY", "MI", "MN", "MT", "NH", "NC", "SC", "WY"}
SENATE_SPECIAL = {"FL", "OH"}

# Pre-election incumbent party holding the seat (I = independent caucusing with Democrats).
# Specials: FL Moody (R, appointed after Rubio), OH Husted (R, appointed after Vance).
# Oklahoma / Nebraska: appointed Republican incumbents running.
SENATE_INCUMBENT_PARTY = {
    "AL": "R", "AK": "R", "AR": "R", "CO": "D", "DE": "D", "FL": "R", "GA": "D", "ID": "R",
    "IL": "D", "IA": "R", "KS": "R", "KY": "R", "LA": "R", "ME": "R", "MA": "D", "MI": "D",
    "MN": "D", "MS": "R", "MT": "R", "NE": "R", "NH": "D", "NJ": "D", "NM": "D", "NC": "R",
    "OH": "R", "OK": "R", "OR": "D", "RI": "D", "SC": "R", "SD": "R", "TN": "R", "TX": "R",
    "VA": "D", "WV": "R", "WY": "R",
}
SENATE_INCUMBENT = {
    "AL": "Tommy Tuberville", "AK": "Dan Sullivan", "AR": "Tom Cotton", "CO": "John Hickenlooper",
    "DE": "Chris Coons", "FL": "Ashley Moody", "GA": "Jon Ossoff", "ID": "Jim Risch",
    "IL": "Dick Durbin", "IA": "Joni Ernst", "KS": "Roger Marshall", "KY": "Mitch McConnell",
    "LA": "Bill Cassidy", "ME": "Susan Collins", "MA": "Ed Markey", "MI": "Gary Peters",
    "MN": "Tina Smith", "MS": "Cindy Hyde-Smith", "MT": "Steve Daines", "NE": "Pete Ricketts",
    "NH": "Jeanne Shaheen", "NJ": "Cory Booker", "NM": "Ben Ray Luján", "NC": "Thom Tillis",
    "OH": "Jon Husted", "OK": "Alan Armstrong", "OR": "Jeff Merkley", "RI": "Jack Reed",
    "SC": "Lindsey Graham", "SD": "Mike Rounds", "TN": "Bill Hagerty", "TX": "John Cornyn",
    "VA": "Mark Warner", "WV": "Shelley Moore Capito", "WY": "Cynthia Lummis",
}

# Governors: Ballotpedia term-limits (Y) plus April 2026 retirements (Reynolds, Walz, Evers).
GOV_TERM_LIMITED = {
    "AL", "AK", "CA", "CO", "FL", "GA", "KS", "ME", "MI", "NM", "OH", "OK", "SC", "TN", "WY",
}
GOV_RETIRING = {"IA", "MN", "WI"}
GOV_OPEN = GOV_TERM_LIMITED | GOV_RETIRING

GOV_INCUMBENT_PARTY = {
    "AL": "R", "AK": "R", "AZ": "D", "AR": "R", "CA": "D", "CO": "D", "CT": "D", "FL": "R",
    "GA": "R", "HI": "D", "ID": "R", "IL": "D", "IA": "R", "KS": "D", "ME": "D", "MD": "D",
    "MA": "D", "MI": "D", "MN": "D", "NE": "R", "NV": "R", "NH": "R", "NM": "D", "NY": "D",
    "OH": "R", "OK": "R", "OR": "D", "PA": "D", "RI": "D", "SC": "R", "SD": "R", "TN": "R",
    "TX": "R", "VT": "R", "WI": "D", "WY": "R",
}
GOV_INCUMBENT = {
    "AL": "Kay Ivey", "AK": "Mike Dunleavy", "AZ": "Katie Hobbs", "AR": "Sarah Huckabee Sanders",
    "CA": "Gavin Newsom", "CO": "Jared Polis", "CT": "Ned Lamont", "FL": "Ron DeSantis",
    "GA": "Brian Kemp", "HI": "Josh Green", "ID": "Brad Little", "IL": "J.B. Pritzker",
    "IA": "Kim Reynolds", "KS": "Laura Kelly", "ME": "Janet Mills", "MD": "Wes Moore",
    "MA": "Maura Healey", "MI": "Gretchen Whitmer", "MN": "Tim Walz", "NE": "Jim Pillen",
    "NV": "Joe Lombardo", "NH": "Kelly Ayotte", "NM": "Michelle Lujan Grisham",
    "NY": "Kathy Hochul", "OH": "Mike DeWine", "OK": "Kevin Stitt", "OR": "Tina Kotek",
    "PA": "Josh Shapiro", "RI": "Dan McKee", "SC": "Henry McMaster", "SD": "Larry Rhoden",
    "TN": "Bill Lee", "TX": "Greg Abbott", "VT": "Phil Scott", "WI": "Tony Evers",
    "WY": "Mark Gordon",
}

# 2025–26 special-election over-performance lives in forecast.special_elections
# (Ballotpedia House specials + VA governor 2025). This module keeps the race schedule.


def senate_races(year: int = 2026) -> pd.DataFrame:
    rows = []
    for st in SENATE[year].split():
        rows.append({
            "year": year,
            "state_po": st,
            "race": "SEN",
            "special": st in SENATE_SPECIAL,
            "incumbent": SENATE_INCUMBENT.get(st),
            "incumbent_party": SENATE_INCUMBENT_PARTY.get(st),
            "open_seat": st in SENATE_OPEN,
            "source": "ballotpedia_2026_curated",
        })
    return pd.DataFrame(rows).sort_values(["special", "state_po"]).reset_index(drop=True)


def governor_races(year: int = 2026) -> pd.DataFrame:
    rows = []
    for st in GOVERNOR[year].split():
        rows.append({
            "year": year,
            "state_po": st,
            "race": "GOV",
            "special": False,
            "incumbent": GOV_INCUMBENT.get(st),
            "incumbent_party": GOV_INCUMBENT_PARTY.get(st),
            "open_seat": st in GOV_OPEN,
            "term_limited": st in GOV_TERM_LIMITED,
            "source": "ballotpedia_2026_curated",
        })
    return pd.DataFrame(rows).sort_values("state_po").reset_index(drop=True)


def races(year: int = 2026) -> pd.DataFrame:
    return pd.concat([senate_races(year), governor_races(year)], ignore_index=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = races(2026)
    df.to_parquet(OUT / "races_2026.parquet", index=False)
    df.to_csv(OUT / "races_2026.csv", index=False)
    print(f"races: {len(df)} (SEN {df.race.eq('SEN').sum()}, GOV {df.race.eq('GOV').sum()})")
    print("open Senate:", sorted(df.loc[df.race.eq("SEN") & df.open_seat, "state_po"]))
    print("special Senate:", sorted(df.loc[df.race.eq("SEN") & df.special, "state_po"]))
    print("open governor:", sorted(df.loc[df.race.eq("GOV") & df.open_seat, "state_po"]))
    from .special_elections import summary as special_summary
    s = special_summary(2026)
    print(f"special-election swing: n={s['n']} mean_pp={s['mean_pp']:+.1f}")


if __name__ == "__main__":
    main()

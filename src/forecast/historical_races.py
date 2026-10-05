"""Historical (2018 / 2022) race incumbency for Stage B backtests.

Curated from Wikipedia / Ballotpedia public election pages (checked-in constants).
Open seats: retirements and resignations where the incumbent did not run.
Incumbent party is the party holding the seat going into the election (I = independent
caucusing with Democrats). Specials: MN/MS 2018 and CA/OK 2022.

    python -m forecast.historical_races
"""
from __future__ import annotations

import pandas as pd

from .features import GOVERNOR, SENATE
from .ingest import OUT

# --- Senate open seats (incumbent not on the ballot) ---
SENATE_OPEN = {
    2018: {"AZ", "TN", "UT"},
    2022: {"AL", "MO", "NC", "OH", "PA", "VT", "OK"},  # OK = Inhofe resignation special
}

# Pre-election seat party for every Senate race on the schedule (regular + special).
# Independents caucusing with Democrats coded "I".
SENATE_PARTY = {
    2018: {
        "AZ": "R", "CA": "D", "CT": "D", "DE": "D", "FL": "D", "HI": "D", "IN": "D",
        "ME": "I", "MD": "D", "MA": "D", "MI": "D", "MN": "D", "MS": "R", "MO": "D",
        "MT": "D", "NE": "R", "NV": "R", "NJ": "D", "NM": "D", "NY": "D", "ND": "D",
        "OH": "D", "PA": "D", "RI": "D", "TN": "R", "TX": "R", "UT": "R", "VT": "I",
        "VA": "D", "WA": "D", "WV": "D", "WI": "D", "WY": "R",
        # Specials (same state appears once in SENATE[2018] for MN/MS Class-2 seats)
        # features.SENATE[2018] lists MN and MS once each — treated as the special/
        # Class-2 contests in midterms.special flags from MIT.
    },
    2022: {
        "AL": "R", "AK": "R", "AZ": "D", "AR": "R", "CA": "D", "CO": "D", "CT": "D",
        "FL": "R", "GA": "D", "HI": "D", "ID": "R", "IL": "D", "IN": "R", "IA": "R",
        "KS": "R", "KY": "R", "LA": "R", "MD": "D", "MO": "R", "NV": "D", "NH": "D",
        "NY": "D", "NC": "R", "ND": "R", "OH": "R", "OK": "R", "OR": "D", "PA": "R",
        "SC": "R", "SD": "R", "UT": "R", "VT": "D", "WA": "D", "WI": "R",
    },
}

# States with a Senate special on the ballot in addition to / instead of the Class race.
# 2018: MN (Franken→Smith), MS (Wicker Class-1 also? — Hyde-Smith Class-2 special).
# features.SENATE lists each once; midterms marks special from MIT. We flag both specials.
SENATE_SPECIAL = {
    2018: {"MN", "MS"},
    2022: {"CA", "OK"},
}

# --- Governors: open seats (term-limited or retiring) ---
# Sources: Wikipedia 2018 / 2022 gubernatorial elections (retirements + term limits).
GOV_OPEN = {
    2018: {
        "CA",  # Brown term-limited
        "CO",  # Hickenlooper retiring
        "CT",  # Malloy retiring
        "FL",  # Scott term-limited / ran Senate
        "GA",  # Deal term-limited
        "ID",  # Otter retiring
        "KS",  # Brownback resigned; Colyer interim; open primary era — treat open
        "ME",  # LePage term-limited
        "MI",  # Snyder term-limited
        "MN",  # Dayton retiring
        "NM",  # Martinez term-limited
        "OH",  # Kasich term-limited
        "OK",  # Fallin term-limited
        "OR",  # Brown ran (not open) — remove if wrong
        "SD",  # Daugaard term-limited
        "TN",  # Haslam term-limited
        "WY",  # Mead term-limited
    } - {"OR"},  # Kate Brown ran for re-election in 2018
    2022: {
        "AL",  # Ivey ran — not open
        "AK",  # Dunleavy ran
        "AZ",  # Ducey term-limited
        "AR",  # Hutchinson term-limited
        "CA",  # Newsom ran
        "CO",  # Polis ran
        "CT",  # Lamont ran
        "FL",  # DeSantis ran
        "GA",  # Kemp ran
        "HI",  # Ige term-limited
        "ID",  # Little ran
        "IL",  # Pritzker ran
        "IA",  # Reynolds ran
        "KS",  # Kelly ran
        "ME",  # Mills ran
        "MD",  # Hogan term-limited
        "MA",  # Baker retiring
        "MI",  # Whitmer ran
        "MN",  # Walz ran
        "NE",  # Ricketts term-limited
        "NV",  # Sisolak ran (lost)
        "NH",  # Sununu ran
        "NM",  # Lujan Grisham ran
        "NY",  # Hochul ran
        "OH",  # DeWine ran
        "OK",  # Stitt ran
        "OR",  # Brown term-limited
        "PA",  # Wolf term-limited
        "RI",  # McKee ran
        "SC",  # McMaster ran
        "SD",  # Noem ran
        "TN",  # Lee ran
        "TX",  # Abbott ran
        "VT",  # Scott ran
        "WI",  # Evers ran
        "WY",  # Gordon ran
    },
}

# Refine GOV_OPEN 2022 to actual opens only.
GOV_OPEN[2022] = {"AZ", "AR", "HI", "MD", "MA", "NE", "OR", "PA"}

# Pre-election governor party (who held the office going into the election).
GOV_PARTY = {
    2018: {
        "AL": "R", "AK": "I", "AZ": "R", "AR": "R", "CA": "D", "CO": "D", "CT": "D",
        "FL": "R", "GA": "R", "HI": "D", "ID": "R", "IL": "R", "IA": "R", "KS": "R",
        "ME": "R", "MD": "R", "MA": "R", "MI": "R", "MN": "D", "NE": "R", "NV": "R",
        "NH": "R", "NM": "R", "NY": "D", "OH": "R", "OK": "R", "OR": "D", "PA": "D",
        "RI": "D", "SC": "R", "SD": "R", "TN": "R", "TX": "R", "VT": "R", "WI": "R",
        "WY": "R",
    },
    2022: {
        "AL": "R", "AK": "R", "AZ": "R", "AR": "R", "CA": "D", "CO": "D", "CT": "D",
        "FL": "R", "GA": "R", "HI": "D", "ID": "R", "IL": "D", "IA": "R", "KS": "D",
        "ME": "D", "MD": "R", "MA": "R", "MI": "D", "MN": "D", "NE": "R", "NV": "D",
        "NH": "R", "NM": "D", "NY": "D", "OH": "R", "OK": "R", "OR": "D", "PA": "D",
        "RI": "D", "SC": "R", "SD": "R", "TN": "R", "TX": "R", "VT": "R", "WI": "D",
        "WY": "R",
    },
}


def _incumbency(open_seat: bool, party: str | None) -> float:
    if open_seat or not party:
        return 0.0
    if party in ("D", "I"):
        return 1.0
    if party == "R":
        return -1.0
    return 0.0


def senate_races(year: int) -> pd.DataFrame:
    open_set = SENATE_OPEN.get(year, set())
    party = SENATE_PARTY.get(year, {})
    specials = SENATE_SPECIAL.get(year, set())
    rows = []
    for st in SENATE[year].split():
        # When a state has a special and only one row in the schedule (MN/MS 2018,
        # CA/OK 2022), mark special=True so it joins midterms specials.
        special = st in specials
        op = st in open_set
        # CA 2022: Padilla ran in both regular and special — not open.
        if year == 2022 and st == "CA":
            op = False
        rows.append({
            "year": year, "state_po": st, "office": "SEN", "special": special,
            "open_seat": op, "incumbent_party": party.get(st),
            "incumbency": _incumbency(op, party.get(st)),
            "source": "historical_curated",
            "race_id": f"{year}-{st}-SEN{'S' if special else ''}",
        })
    return pd.DataFrame(rows)


def governor_races(year: int) -> pd.DataFrame:
    open_set = GOV_OPEN.get(year, set())
    party = GOV_PARTY.get(year, {})
    rows = []
    for st in GOVERNOR[year].split():
        op = st in open_set
        rows.append({
            "year": year, "state_po": st, "office": "GOV", "special": False,
            "open_seat": op, "incumbent_party": party.get(st),
            "incumbency": _incumbency(op, party.get(st)),
            "source": "historical_curated",
            "race_id": f"{year}-{st}-GOV",
        })
    return pd.DataFrame(rows)


def races(year: int) -> pd.DataFrame:
    return pd.concat([senate_races(year), governor_races(year)], ignore_index=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for year in (2018, 2022):
        df = races(year)
        df.to_parquet(OUT / f"historical_races_{year}.parquet", index=False)
        df.to_csv(OUT / f"historical_races_{year}.csv", index=False)
        print(f"{year}: {len(df)} races | open SEN "
              f"{sorted(df.loc[df.office.eq('SEN') & df.open_seat, 'state_po'])} | "
              f"open GOV {sorted(df.loc[df.office.eq('GOV') & df.open_seat, 'state_po'])}")


if __name__ == "__main__":
    main()

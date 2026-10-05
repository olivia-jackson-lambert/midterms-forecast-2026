"""Generic congressional ballot as of 30 September, and the national House vote it predicts.

Backtests may only use what was public by 1 October, so every year's value is the generic
ballot average as it stood on 30 September, never the final pre-election average:

- 1998-2016: FiveThirtyEight's daily average (fivethirtyeight/data, generic_topline_historical.csv).
- 2018: FiveThirtyEight's 2018-cycle daily average, from the Internet Archive's copy of
  projects.fivethirtyeight.com/generic-ballot-data/generic_topline.csv (24 May 2019). That
  file stops on 18 September 2018, so 2018 uses the 18 September value.
- 2022: FiveThirtyEight's average in Wikipedia's "2022 ... House election ratings" page as it
  stood on 30 September 2022 (revision 1113252945).
- 2026: FiveThirtyEight no longer publishes; the mean of the aggregators in Wikipedia's
  "2026 United States House of Representatives elections" page (fetched at run time).

The national House two-party vote for each year comes from Wikipedia's "<year> United States
House of Representatives elections" pages.

On 30 September the generic ballot has overstated the Democratic share of the eventual House
vote in almost every cycle. `national_environment(year)` estimates that bias and the spread
around it from earlier cycles only, and returns a Student-t forecast of the House vote.

    python -m forecast.generic_ballot [--refresh]
"""
from __future__ import annotations

import re
import sys
from io import StringIO

import numpy as np
import pandas as pd
import requests
from scipy import stats

from .ingest import OUT, RAW, UA, fetch

RAW_GB = RAW / "generic_ballot"
FTE_HISTORICAL = ("https://raw.githubusercontent.com/fivethirtyeight/data/master/"
                  "congress-generic-ballot/generic_topline_historical.csv")
FTE_2018 = ("https://web.archive.org/web/20190524202349id_/"
            "https://projects.fivethirtyeight.com/generic-ballot-data/generic_topline.csv")
WIKI_API = "https://en.wikipedia.org/w/api.php"
RATINGS_2022 = ("2022 United States House of Representatives election ratings", 1113252945)
HOUSE_2026 = "https://en.wikipedia.org/wiki/2026_United_States_House_of_Representatives_elections"
HOUSE_PAGE = "https://en.wikipedia.org/wiki/{year}_United_States_House_of_Representatives_elections"


def _num(x) -> float:
    s = re.sub(r"\[[^\]]*\]", "", str(x)).replace("%", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return float("nan")


# --------------------------------------------------------------------------- generic ballot
def _fte_on(df: pd.DataFrame, year: int) -> dict:
    df = df.assign(date=pd.to_datetime(df["modeldate"], format="mixed"))
    if "subgroup" in df:
        df = df[df["subgroup"].isin(["All polls", "Registered voters"]) | df["subgroup"].isna()]
        df = df[df["subgroup"] == df["subgroup"].iloc[0]] if df["subgroup"].nunique() > 1 else df
    d = df[(df["date"] <= f"{year}-09-30") & (df["date"] >= f"{year}-09-01")].sort_values("date")
    if d.empty:
        raise ValueError(f"no FiveThirtyEight value in September {year}")
    r = d.iloc[-1]
    return {"year": year, "dem": float(r["dem_estimate"]), "rep": float(r["rep_estimate"]),
            "as_of": r["date"].date().isoformat(), "source": "FiveThirtyEight"}


def _wiki_revision(title: str, revid: int) -> str:
    path = RAW_GB / f"wiki_rev{revid}.html"
    if not path.exists():
        r = requests.get(WIKI_API, params={"action": "parse", "oldid": revid, "prop": "text",
                                           "format": "json"}, headers=UA, timeout=60)
        r.raise_for_status()
        path.write_text(r.json()["parse"]["text"]["*"])
    return path.read_text()


def _aggregate_table(html: str) -> pd.DataFrame:
    """The 'source of poll aggregation' table, normalised to source, dem, rep, updated."""
    for t in pd.read_html(StringIO(html)):
        t.columns = [str(c[-1] if isinstance(c, tuple) else c) for c in t.columns]
        cols = {c.lower(): c for c in t.columns}
        src = next((cols[c] for c in cols if "source" in c), None)
        dem = next((cols[c] for c in cols if c.startswith("democrat")), None)
        rep = next((cols[c] for c in cols if c.startswith("republican")), None)
        upd = next((cols[c] for c in cols if "updated" in c), None)
        if src and dem and rep:
            out = pd.DataFrame({"source": t[src].map(lambda s: re.sub(r"\[[^\]]*\]", "", str(s)).strip()),
                                "dem": t[dem].map(_num), "rep": t[rep].map(_num),
                                "updated": t[upd].astype(str) if upd else ""})
            return out[out["dem"].notna() & out["rep"].notna() & ~out["source"].str.lower().eq("average")]
    raise ValueError("no aggregate table found")


def generic_ballot(refresh: bool = False) -> pd.DataFrame:
    """Generic ballot (Democratic and Republican %, before undecideds) as of 30 September."""
    RAW_GB.mkdir(parents=True, exist_ok=True)
    rows = []
    hist = pd.read_csv(fetch(FTE_HISTORICAL, RAW_GB / "fte_generic_topline_historical.csv"))
    for y in range(1998, 2018, 2):
        rows.append(_fte_on(hist, y))
    rows.append(_fte_on(pd.read_csv(fetch(FTE_2018, RAW_GB / "fte_generic_topline_2018cycle_wayback20190524.csv")), 2018))
    agg = _aggregate_table(_wiki_revision(*RATINGS_2022))
    fte = agg[agg["source"].str.contains("FiveThirtyEight")].iloc[0]
    rows.append({"year": 2022, "dem": fte["dem"], "rep": fte["rep"], "as_of": "2022-09-28",
                 "source": "FiveThirtyEight (Wikipedia revision 1113252945)"})
    path = RAW_GB / "wiki_house_2026.html"
    if refresh or not path.exists():
        path.write_text(requests.get(HOUSE_2026, headers=UA, timeout=60).text)
    a26 = _aggregate_table(path.read_text())
    rows.append({"year": 2026, "dem": a26["dem"].mean(), "rep": a26["rep"].mean(),
                 "as_of": pd.Timestamp(path.stat().st_mtime, unit="s").date().isoformat(),
                 "source": "mean of " + ", ".join(a26["source"])})
    gb = pd.DataFrame(rows)
    gb["gb_dem_2p"] = gb["dem"] / (gb["dem"] + gb["rep"])
    return gb


# --------------------------------------------------------------------------- House vote
def _house_2p(html: str) -> float:
    """Democratic share of the two-party House vote from the page's results summary."""
    for t in pd.read_html(StringIO(html), match="Popular vote"):
        t = t.fillna("").astype(str)
        dem = rep = None
        for _, r in t.iterrows():
            cells = [str(c) for c in r.tolist() if str(c) not in ("nan", "")]
            label = " ".join(cells[:2])
            nums = [_num(c) for c in cells]
            votes = [v for v in nums if v > 1e6]
            pcts = [_num(c) for c in cells if c.endswith("%")]
            val = votes[0] if votes else (pcts[0] if pcts else None)
            if val is None:
                continue
            if dem is None and re.search(r"\bDemocratic\b", label):
                dem = val
            elif rep is None and re.search(r"\bRepublican\b", label):
                rep = val
        if dem and rep:
            return dem / (dem + rep)
    raise ValueError("no House popular vote found")


def house_vote() -> pd.DataFrame:
    rows = []
    for y in range(1998, 2026, 2):
        path = RAW_GB / f"house_{y}.html"
        if not path.exists():
            path.write_text(requests.get(HOUSE_PAGE.format(year=y), headers=UA, timeout=60).text)
        rows.append({"year": y, "house_dem_2p": _house_2p(path.read_text())})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- national environment
def history() -> pd.DataFrame:
    gb = generic_ballot()
    return gb.merge(house_vote(), on="year", how="left")


def national_environment(year: int, hist: pd.DataFrame | None = None) -> dict:
    """Student-t forecast of the national House Democratic two-party share in `year`.

    House share = generic ballot (30 September, two-party) + bias + error. Bias and error
    spread come from every even year before `year` with both numbers (midterm and presidential).
    """
    h = history() if hist is None else hist
    past = h[(h["year"] < year) & h["house_dem_2p"].notna()]
    err = past["house_dem_2p"] - past["gb_dem_2p"]
    n = len(err)
    gb = float(h.loc[h["year"] == year, "gb_dem_2p"].iloc[0])
    return {"year": year, "gb_dem_2p": gb, "bias": float(err.mean()), "n_years": n,
            "mean": gb + float(err.mean()), "sd": float(err.std(ddof=1) * np.sqrt(1 + 1 / n)), "df": n - 1}


def interval(env: dict, level: float = 0.8) -> tuple[float, float]:
    q = stats.t.ppf([(1 - level) / 2, (1 + level) / 2], env["df"])
    return tuple(env["mean"] + env["sd"] * q)


def main() -> None:
    refresh = "--refresh" in sys.argv
    gb = generic_ballot(refresh)
    h = gb.merge(house_vote(), on="year", how="left")
    h["error"] = h["house_dem_2p"] - h["gb_dem_2p"]
    OUT.mkdir(parents=True, exist_ok=True)
    h.to_csv(OUT / "generic_ballot_history.csv", index=False)
    print(h[["year", "dem", "rep", "as_of", "gb_dem_2p", "house_dem_2p", "error", "source"]].round(4).to_string(index=False))
    for y in (2018, 2022, 2026):
        e = national_environment(y, h)
        lo, hi = interval(e)
        print(f"{y}: GB {e['gb_dem_2p']:.3f}, bias {e['bias']:+.3f} (n={e['n_years']}), "
              f"House forecast {e['mean']:.3f} (80%: {lo:.3f}-{hi:.3f})"
              + (f", actual {h.loc[h.year == y, 'house_dem_2p'].iloc[0]:.3f}" if y < 2026 else ""))


if __name__ == "__main__":
    main()

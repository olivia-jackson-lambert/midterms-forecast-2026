"""Cross-check AP's Senate and governor calls against Wikipedia's results tables.

    python -m forecast.crosscheck

Fetches the current revisions of "2026 United States Senate elections" and "2026 United States
gubernatorial elections" (rendered HTML through index.php?action=render, no login), keeps them
under data/raw/results_2026/wikipedia/<pull time>/ with their revision ids, and writes
results/crosscheck_wikipedia.csv: for every v1 Senate and governor race, the winner each source
shows (bold, ticked candidate in Wikipedia's summary tables) and whether the two agree.

Wikipedia's editors often mark a winner before AP calls a race, so a winner on Wikipedia alone
is not treated as a call; the file only flags disagreements between two calls. The House is not
cross-checked here: its Wikipedia page lists districts in per-state tables that are not yet
filled in consistently on election night.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import time
import unicodedata
from pathlib import Path

import lxml.html as LH
import pandas as pd

from .results import RAW_RESULTS, RESULTS, UA, latest, _surname

PAGES = {"senate": "2026_United_States_Senate_elections",
         "governor": "2026_United_States_gubernatorial_elections"}
WIKI = "https://en.wikipedia.org/w/index.php?title={t}&action=render"
API = ("https://en.wikipedia.org/w/api.php?action=query&prop=revisions&rvprop=timestamp|ids"
       "&format=json&titles={t}")
OUT = RESULTS / "crosscheck_wikipedia.csv"

STATE_NAMES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY"}


def _party(p: str | None) -> str | None:
    """D for Democratic (and Minnesota's DFL), R for Republican, I otherwise."""
    if p is None:
        return None
    return "D" if p.startswith("Democratic") or p == "DFL" else "R" if p == "Republican" else "I"


def _plain(name) -> str:
    return unicodedata.normalize("NFKD", _surname(name)).encode("ascii", "ignore").decode()


def _get(url: str) -> bytes:
    return subprocess.run(["curl", "-sS", "--fail", "--compressed", "--max-time", "60", "-A", UA, url],
                          check=True, capture_output=True).stdout


def fetch(dest_root: Path = RAW_RESULTS / "wikipedia") -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    d = dest_root / stamp
    d.mkdir(parents=True, exist_ok=True)
    revs = {}
    for office, t in PAGES.items():
        (d / f"{office}.html").write_bytes(_get(WIKI.format(t=t)))
        page = next(iter(json.loads(_get(API.format(t=t)))["query"]["pages"].values()))
        revs[office] = {"title": page["title"], **page["revisions"][0]}
        time.sleep(2)
    (d / "revisions.json").write_text(json.dumps(revs, indent=1))
    return d


def parse_page(html: str, office: str) -> pd.DataFrame:
    """One row per race in the page's summary tables: state, special, winner name and party."""
    doc = LH.fromstring(html)
    rows = []
    for tb in doc.xpath("//table"):
        hdr = " ".join(tb.xpath(".//th//text()"))
        if "Candidates" not in hdr or not ("Status" in hdr or "Results" in hdr):
            continue
        for tr in tb.xpath(".//tr"):
            cells = tr.xpath("./th|./td")
            if len(cells) < 4:
                continue
            first = " ".join(cells[0].text_content().split())
            m = re.match(r"([A-Za-z ]+?)\s*(\(Class \d\))?(\[.*)?$", first)
            if not m or m.group(1).strip() not in STATE_NAMES:
                continue
            st = STATE_NAMES[m.group(1).strip()]
            special = bool(m.group(2) and "3" in m.group(2)) if office == "senate" else False
            cand_cell = cells[-1]
            winner, party = None, None
            for li in cand_cell.xpath(".//li"):
                txt = " ".join(li.text_content().split())
                if li.xpath(".//b") and re.search(r"\(([^)]+)\)", txt):
                    name = " ".join(li.xpath(".//b")[0].text_content().split())
                    winner = name
                    party = re.search(r"\(([^)]+)\)", txt).group(1)
                    break
            rows.append({"state": st, "special": special, "wiki_winner": winner,
                         "wiki_winner_party": _party(party)})
    return pd.DataFrame(rows).drop_duplicates(["state", "special"])


def crosscheck(d: Path) -> pd.DataFrame:
    revs = json.loads((d / "revisions.json").read_text())
    ap = latest()
    ap = ap[ap["office"].isin(PAGES)].copy()
    ap["special"] = ap["id"].str.endswith("S")
    out = []
    for office in PAGES:
        w = parse_page((d / f"{office}.html").read_text(), office)
        a = ap[ap["office"] == office].merge(w, on=["state", "special"], how="left")
        a["wiki_revision"] = revs[office]["revid"]
        a["wiki_revision_time"] = revs[office]["timestamp"]
        a["wiki_source"] = WIKI.format(t=PAGES[office])
        out.append(a)
    x = pd.concat(out, ignore_index=True)
    both = x["called"].astype(bool) & x["wiki_winner"].notna()
    x["agree"] = pd.NA
    x.loc[both, "agree"] = [(wp == ap_p) and (_plain(wn) == _plain(an)) for wp, ap_p, wn, an in
                            zip(x.loc[both, "wiki_winner_party"], x.loc[both, "winner_party"],
                                x.loc[both, "wiki_winner"], x.loc[both, "winner_name"])]
    cols = ["id", "office", "called", "winner_party", "winner_name", "pulled_at", "wiki_winner",
            "wiki_winner_party", "wiki_revision", "wiki_revision_time", "agree", "wiki_source"]
    x = x[cols].rename(columns={"called": "ap_called", "winner_party": "ap_winner_party",
                                "winner_name": "ap_winner_name", "pulled_at": "ap_pulled_at"})
    x.to_csv(OUT, index=False)
    return x


def main() -> None:
    d = fetch()
    x = crosscheck(d)
    called = x["ap_called"].astype(bool)
    print(f"{called.sum()} AP calls; Wikipedia shows a winner in {x.loc[called, 'wiki_winner'].notna().sum()}; "
          f"disagreements: {(x['agree'] == False).sum()}")  # noqa: E712
    print(x[x["agree"] == False].to_string(index=False))  # noqa: E712
    print("winner on Wikipedia, not called by AP:", ", ".join(x.loc[~called & x["wiki_winner"].notna(), "id"]))


if __name__ == "__main__":
    main()

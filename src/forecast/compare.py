"""Score v1 against the other public forecasts as they stood on 22 October 2026 (issue #25).

    python -m forecast.compare [--results PATH]

Reads the dated source files in results/comparisons/ (written by forecast.compare_sources and
forecast.compare_archive, plus the hand-transcribed and news-report files) and the race calls
in results.json, and writes

    results/comparison.json   the `comparison` block of the results data contract, by chamber
    results/comparison.md     the write-up's tables

Conventions
    * Every probability is for the Democratic side as v1 defines it: the Democrat, or the
      independent where v1 has an independent in that place (Nebraska, Idaho and South Dakota
      Senate). A called race is a hit for that side when the winner is not a Republican.
    * Ratings become probabilities with RATING_P (Toss Up 50%, Lean 65%, Likely 85%, Solid 97%,
      mirrored for Republicans) and are scored in their own table, never pooled with
      probabilistic forecasts.
    * Market prices are reported as implied probabilities (the Democratic-side price over the sum
      of both sides' prices), not as models.
    * Log loss uses natural logarithms with probabilities clipped to [0.001, 0.999], since several
      forecasts publish 0% and 100%.
    * Only called races are scored. "Competitive" means the favourite had under 85% in at least
      one of the forecasts in the comparison.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "forecasts" / "v1"
SRC = ROOT / "results" / "comparisons"
OUT_JSON = ROOT / "results" / "comparison.json"
OUT_MD = ROOT / "results" / "comparison.md"
RESULTS_BRANCH = "origin/eval/results-log"

RATING_P = {"Toss Up": 0.50, "Lean D": 0.65, "Likely D": 0.85, "Solid D": 0.97,
            "Lean R": 0.35, "Likely R": 0.15, "Solid R": 0.03}
EPS = 0.001
COMPETITIVE = 0.85
MIN_COVERAGE = 0.9  # share of a chamber's called races a forecast must cover to join the common set
OFFICES = ["senate", "house", "governor"]
V1_NAME = "v1"
V1_CAPTURED = "2026-10-22T23:25:15Z"  # forecasts/v1/manifest.json created_utc


# ---------------------------------------------------------------------- maths

def rating_to_p(rating: str | None) -> float | None:
    """Democratic-side probability for a seven-point rating ('Tilt' counts as 'Lean')."""
    if rating is None or (isinstance(rating, float) and math.isnan(rating)):
        return None
    r = str(rating).strip().replace("Toss-up", "Toss Up").replace("Tossup", "Toss Up").replace("Tilt", "Lean")
    r = r.replace("Leans", "Lean").replace("Safe", "Solid")
    if r not in RATING_P:
        raise ValueError(f"unknown rating {rating!r}")
    return RATING_P[r]


def brier(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def log_loss(p, y, eps: float = EPS) -> float:
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def upsets(p, y) -> float:
    """Called races the forecast's favourite lost; a 50-50 forecast counts as half a miss."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.sum(np.where(p == 0.5, 0.5, ((p > 0.5) != (y == 1)).astype(float))))


def implied_two_way(p_dem, p_rep):
    if p_dem is None and p_rep is None:
        return None
    if p_rep is None:
        return p_dem
    if p_dem is None:
        return 1 - p_rep
    return p_dem / (p_dem + p_rep) if p_dem + p_rep > 0 else None


def seat_quantiles(dist: pd.DataFrame, col: str = "dem_seats", q=(0.1, 0.5, 0.9)) -> list[int]:
    d = dist.groupby(col)["probability"].sum().sort_index()
    c = d.cumsum() / d.sum()
    return [int(d.index[np.searchsorted(c.values + 1e-9, x)]) for x in q]


# ---------------------------------------------------------------------- inputs

def isnan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def clean(x):
    if isnan(x):
        return None
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    return x


def load_results(path: str | None):
    """(calls by id, description of the source). Tries PATH, results/results.json, then the
    results-log branch."""
    if path:
        text, where = Path(path).read_text(), path
    elif (ROOT / "results" / "results.json").exists():
        text, where = (ROOT / "results" / "results.json").read_text(), "results/results.json"
    else:
        text = subprocess.run(["git", "-C", str(ROOT), "show", f"{RESULTS_BRANCH}:results/results.json"],
                              capture_output=True, text=True, check=True).stdout
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", RESULTS_BRANCH],
                                capture_output=True, text=True, check=True).stdout.strip()
        where = f"results/results.json on branch eval/results-log (commit {commit})"
    res = json.loads(text)
    return res, where


def outcomes(res: dict) -> pd.DataFrame:
    rows = [{"office": r["office"], "id": r["id"], "y": 0 if r["winner_party"] == "R" else 1,
             "winner_party": r["winner_party"]}
            for r in res["races"] if r.get("called") and r.get("winner_party")]
    return pd.DataFrame(rows)


def v1_rows() -> pd.DataFrame:
    races = pd.read_csv(V1 / "races.csv")
    house = pd.read_csv(V1 / "house_districts.csv")
    a = pd.DataFrame({"office": races.office, "id": races.race_id, "p_dem": races.p_dem_win})
    b = pd.DataFrame({"office": "house", "id": house.cd, "p_dem": 1 - house.p_rep_win})
    out = pd.concat([a, b], ignore_index=True)
    out["forecaster"], out["kind"] = V1_NAME, "model"
    out["source"], out["captured"] = "forecasts/v1", V1_CAPTURED
    return out


def market_rows(source: str, path: Path) -> pd.DataFrame:
    """One implied probability per race (and per chamber) from a market price file."""
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path)
    d = d[d.price_yes.notna()].copy()
    # Prefer party markets (Kalshi tickers ending -D/-R, or the independent's own market) where a
    # race has both a party and a person market.
    d["pref"] = d.label.astype(str).str.contains(r"-(?:D|R|I)\]$|-[A-Z]{3,4}\]$", regex=True).astype(int)
    d["pref"] += d.label.astype(str).str.contains(r"-(?:D|R)\]$", regex=True).astype(int)
    d = d.sort_values(["office", "id", "side", "pref"], ascending=[True, True, True, False])
    d = d.drop_duplicates(["office", "id", "side"])
    rows = []
    for (office, rid), g in d.groupby(["office", "id"]):
        pd_ = g.loc[g.side == "D", "price_yes"]
        pr_ = g.loc[g.side == "R", "price_yes"]
        p = implied_two_way(float(pd_.iloc[0]) if len(pd_) else None, float(pr_.iloc[0]) if len(pr_) else None)
        if p is None:
            continue
        first = g.iloc[0]
        rows.append({"office": office, "id": rid, "p_dem": round(p, 4), "forecaster": source, "kind": "market",
                     "source": first.event_url, "captured": first.captured,
                     "price_time": max(g.price_time.dropna()) if g.price_time.notna().any() else None,
                     "cutoff": first.cutoff,
                     "price_dem": float(pd_.iloc[0]) if len(pd_) else None,
                     "price_rep": float(pr_.iloc[0]) if len(pr_) else None})
    return pd.DataFrame(rows)


def prob_rows(path: Path, name: str | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path)
    if name:
        d["forecaster"] = name
    d["kind"] = "model"
    d["source"] = d.source_url
    return d


def rating_rows(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path)
    d["kind"] = "rating"
    d["p_dem"] = d.rating.map(rating_to_p)
    d["source"] = d.source_url
    return d


def load_forecasts(when: str) -> pd.DataFrame:
    """Long table of race-level and chamber-level forecasts for 'oct22' or 'final'."""
    if when == "oct22":
        parts = [v1_rows(),
                 prob_rows(SRC / "ddhq_2026-10-22.csv"),
                 market_rows("Polymarket", SRC / "polymarket_2026-10-22.csv"),
                 market_rows("Kalshi", SRC / "kalshi_2026-10-22.csv"),
                 rating_rows(SRC / "cook_2026-10-22.csv"),
                 rating_rows(SRC / "sabato_senate_2026-10-22.csv"),
                 rating_rows(SRC / "sabato_house_2026-10-22.csv"),
                 rating_rows(SRC / "splitticket_house_2026-10-22.csv")]
    else:
        parts = [v1_rows(),
                 prob_rows(SRC / "ddhq_2026-11-03.csv"),
                 market_rows("Polymarket", SRC / "polymarket_2026-11-02.csv"),
                 market_rows("Kalshi", SRC / "kalshi_2026-11-02.csv"),
                 rating_rows(SRC / "cook_final.csv"),
                 rating_rows(SRC / "splitticket_house_final.csv")]
    d = pd.concat([p for p in parts if len(p)], ignore_index=True)
    d.loc[d.forecaster == V1_NAME, "note"] = "v1 is the 22 October forecast in both tables" if when == "final" else None
    return d


# ---------------------------------------------------------------------- scoring

def score_block(f: pd.DataFrame, y: pd.DataFrame, office: str, kind: str) -> dict:
    """Common-set scores for one chamber and one kind of forecast (probabilities or ratings).

    The common set is every called race that each forecaster in the group covers; v1 is always in
    the group (for ratings it is shown for reference on the same races)."""
    g = f[(f.office == office) & (f.id != "control") & (f.p_dem.notna())]
    called = set(y[y.office == office].id)
    names = [n for n in g.forecaster.unique() if n != V1_NAME and (g[g.forecaster == n].kind.iloc[0] in kind)]
    # A forecast that covers only part of the chamber (Kalshi's House markets, Sabato's listed House
    # races) would shrink the common set to its own races; it is left to the head-to-head table.
    partial = [n for n in names if len(called & set(g[g.forecaster == n].id)) < MIN_COVERAGE * len(called)]
    names = [n for n in names if n not in partial]
    if not names:
        return {"head_to_head_only": partial} if partial else {}
    wide = g[g.forecaster.isin(names + [V1_NAME])].pivot_table(index="id", columns="forecaster", values="p_dem",
                                                               aggfunc="first")
    common = wide.dropna().index.intersection(sorted(called))
    out = {"races_common": int(len(common)), "forecasters": {}, "head_to_head_only": partial}
    if len(common) == 0:
        return out
    wide = wide.loc[common]
    yy = y[y.office == office].set_index("id").loc[common, "y"].values
    fav = wide.apply(lambda c: np.maximum(c, 1 - c))
    comp = (fav < COMPETITIVE).any(axis=1).values
    out["races_competitive"] = int(comp.sum())
    for n in [V1_NAME] + names:
        p = wide[n].values
        out["forecasters"][n] = {
            "covered_called": int(len(called & set(g[g.forecaster == n].id))),
            "brier": round(brier(p, yy), 4), "log_loss": round(log_loss(p, yy), 4),
            "upsets_missed": upsets(p, yy),
            "brier_competitive": round(brier(p[comp], yy[comp]), 4) if comp.any() else None,
            "log_loss_competitive": round(log_loss(p[comp], yy[comp]), 4) if comp.any() else None,
            "upsets_missed_competitive": upsets(p[comp], yy[comp]) if comp.any() else None,
        }
    out["democratic_side_won"] = int(yy.sum())
    out["democratic_side_won_competitive"] = int(yy[comp].sum())
    return out


def head_to_head(f: pd.DataFrame, y: pd.DataFrame, office: str) -> list[dict]:
    """Each forecaster against v1 on every called race both cover (wider than the common set)."""
    g = f[(f.office == office) & (f.id != "control") & f.p_dem.notna()]
    v = g[g.forecaster == V1_NAME].set_index("id").p_dem
    yy = y[y.office == office].set_index("id").y
    rows = []
    for n in g.forecaster.unique():
        if n == V1_NAME:
            continue
        o = g[g.forecaster == n].drop_duplicates("id").set_index("id").p_dem
        ids = o.index.intersection(v.index).intersection(yy.index)
        if not len(ids):
            continue
        p, q, t = o[ids].values, v[ids].values, yy[ids].values
        comp = (np.maximum(p, 1 - p) < COMPETITIVE) | (np.maximum(q, 1 - q) < COMPETITIVE)
        rows.append({"forecaster": n, "kind": g[g.forecaster == n].kind.iloc[0], "n": int(len(ids)),
                     "brier": round(brier(p, t), 4), "v1_brier": round(brier(q, t), 4),
                     "log_loss": round(log_loss(p, t), 4), "v1_log_loss": round(log_loss(q, t), 4),
                     "upsets_missed": upsets(p, t), "v1_upsets_missed": upsets(q, t),
                     "n_competitive": int(comp.sum()),
                     "brier_competitive": round(brier(p[comp], t[comp]), 4) if comp.any() else None,
                     "v1_brier_competitive": round(brier(q[comp], t[comp]), 4) if comp.any() else None})
    return rows


# ---------------------------------------------------------------------- chamber level

def v1_control_and_seats() -> dict:
    s = pd.read_csv(V1 / "senate_seats.csv")
    h = pd.read_csv(V1 / "house_seats.csv")
    gv = pd.read_csv(V1 / "governor_seats.csv")
    for t in (s, h, gv):    # v1's four-decimal seat files sum to just under 1 (forecasts/README.md)
        t["probability"] /= t["probability"].sum()
    s["caucus"] = s.dem_seats + s.independent_seats
    return {
        "senate": {"p_dem": round(float(s.loc[s.dem_seats >= 51, "probability"].sum()), 3),
                   "seats": seat_quantiles(s, "dem_seats"),
                   "definition": "P(51+ Democratic seats), as in v1's vote_model"},
        "house": {"p_dem": round(float(h.loc[h.dem_seats >= 218, "probability"].sum()), 3),
                  "seats": seat_quantiles(h, "dem_seats"), "definition": "P(218+ Democratic seats)"},
        "governor": {"p_dem": round(float(gv.loc[gv.dem_seats >= 26, "probability"].sum()), 3),
                     "seats": seat_quantiles(gv, "dem_seats"),
                     "definition": "P(26+ Democratic governorships)"},
    }


def chamber_rows(when: str, f: pd.DataFrame) -> dict:
    """control and seats lists per office."""
    out = {o: {"control": [], "seats": []} for o in OFFICES}
    v = v1_control_and_seats()
    for o in OFFICES:
        lo, med, hi = v[o]["seats"]
        out[o]["control"].append({"name": V1_NAME, "p_dem": v[o]["p_dem"], "kind": "model", "source": "forecasts/v1",
                                  "captured": V1_CAPTURED, "news_report": False, "definition": v[o]["definition"]})
        out[o]["seats"].append({"name": V1_NAME, "dem_median": med, "dem_lo80": lo, "dem_hi80": hi,
                                "source": "forecasts/v1", "captured": V1_CAPTURED, "news_report": False})
    ctl = f[f.id == "control"]
    for _, r in ctl.iterrows():
        o = r.office
        item = {"name": r.forecaster, "p_dem": clean(r.p_dem), "kind": r.kind, "source": clean(r.source),
                "captured": clean(r.get("price_time")) or clean(r.get("model_date")) or clean(r.captured),
                "news_report": False}
        if r.kind == "market":
            item["note"] = f"implied probability from the last price at or before {r.cutoff}"
        out[o]["control"].append(item)
        if not isnan(r.get("seats_dem")):
            as_int = lambda v: None if isnan(v) else int(v)
            out[o]["seats"].append({"name": r.forecaster, "dem_projection": as_int(r.seats_dem),
                                    "dem_median": as_int(r.get("seats_median_sim")),
                                    "dem_lo80": as_int(r.get("seats_lo80")), "dem_hi80": as_int(r.get("seats_hi80")),
                                    "source": clean(r.source), "captured": clean(r.get("updated_at")) or clean(r.model_date),
                                    "news_report": False})
    news = pd.read_csv(SRC / "news_reports.csv")
    for _, r in news[news.when == when].iterrows():
        out[r.office]["control"].append({"name": r.forecaster, "p_dem": clean(r.p_dem), "kind": "model",
                                         "source": r.source_url, "captured": clean(r.model_date),
                                         "news_report": True, "note": r.note})
        if not isnan(r.seats_dem):
            out[r.office]["seats"].append({"name": r.forecaster, "dem_projection": int(r.seats_dem),
                                           "dem_lo80": None, "dem_hi80": None, "source": r.source_url,
                                           "captured": clean(r.model_date), "news_report": True})
    return out


def control_outcomes(res: dict) -> dict:
    ch = res["chambers"]
    called = {o: [r for r in res["races"] if r["office"] == o and r.get("called")] for o in OFFICES}
    total = {o: [r for r in res["races"] if r["office"] == o] for o in OFFICES}
    out = {}
    for o in OFFICES:
        uncalled = len(total[o]) - len(called[o])
        out[o] = {"control": ch[o].get("control"), "dem_seats_called": ch[o].get("dem_seats"),
                  "uncalled_races": uncalled, "complete": ch[o].get("complete")}
    return out


# ---------------------------------------------------------------------- build

def race_list(f: pd.DataFrame, office: str) -> list[dict]:
    g = f[(f.office == office) & (f.id != "control")]
    rows = []
    for _, r in g.sort_values(["id", "forecaster"]).iterrows():
        rows.append({"id": r.id, "forecaster": r.forecaster,
                     "p_dem": clean(r.p_dem) if r.kind != "rating" else None,
                     "rating": clean(r.get("rating")) if r.kind == "rating" else None,
                     "margin_dem": None,
                     "source": clean(r.source),
                     "captured": clean(r.get("price_time")) or clean(r.get("model_date")) or clean(r.get("page_updated"))
                     or clean(r.captured),
                     "read_from_chart": bool(r.get("read_from_chart")) if not isnan(r.get("read_from_chart")) else False})
    return rows


MISSING = [
    {"forecaster": "Silver Bulletin", "what": "race-by-race probabilities, House seats, governors (22 Oct and final)",
     "why": "behind the paywall; the public part of each model page shows only polling averages; free posts of 19 to 25 October quote no 22 October model numbers",
     "manual": True},
    {"forecaster": "Race to the WH", "what": "22 October numbers (all chambers)",
     "why": "the 22 October snapshots of the page and of its Infogram embeds exist, but every chart loads its data at view time from live-data.jifo.co, which the Archive did not keep",
     "manual": True},
    {"forecaster": "The Economist", "what": "22 October and final numbers",
     "why": "no snapshot of the 2026 forecast page in the Archive between 15 October and 4 November, and no dated report found", "manual": True},
    {"forecaster": "Split Ticket", "what": "Senate and governor ratings or probabilities",
     "why": "no archived Split Ticket forecast page; only its House ratings exist, via 270toWin's copy", "manual": True},
    {"forecaster": "midtermforecast.com", "what": "any numbers",
     "why": "the Archive holds only three static assets captured on 3 November, no page with numbers", "manual": True},
    {"forecaster": "Sabato's Crystal Ball", "what": "governor ratings; final (2 November) ratings",
     "why": "no 2026 governor page in the Archive; the final-ratings page was archived only as Cloudflare 403 challenges, and the live page returns the same challenge",
     "manual": True},
    {"forecaster": "Kalshi", "what": "most House districts", "why": "Kalshi listed markets for about 76 districts", "manual": False},
]


def build(results_path: str | None = None) -> dict:
    res, where = load_results(results_path)
    y = outcomes(res)
    calls_used = y.copy()
    calls_used["source"] = where
    calls_used.to_csv(SRC / "calls_used.csv", index=False)
    block = {"as_of": "2026-10-22",
             "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
             "results": {"source": where, "as_of": res.get("as_of"), "status": res.get("status"),
                         "called": {o: int((y.office == o).sum()) for o in OFFICES}},
             "conventions": {"probability": "Democratic side as v1 defines it (Democrat, or the independent in NE, ID, SD Senate); a hit when the winner is not a Republican",
                             "rating_mapping": RATING_P, "log_loss": f"natural log, probabilities clipped to [{EPS}, {1 - EPS}]",
                             "competitive": f"favourite under {COMPETITIVE:.0%} in at least one forecast in the comparison",
                             "markets": "implied probability = Democratic-side price / (Democratic-side + Republican price), last price at or before the cut-off; reported as prices, not models"},
             "missing": MISSING}
    outcomes_ch = control_outcomes(res)
    for when, key in (("oct22", None), ("final", "final")):
        f = load_forecasts(when)
        ch = chamber_rows(when, f)
        target = block if key is None else block.setdefault("final", {})
        for o in OFFICES:
            ctl_y = outcomes_ch[o]["control"]
            for c in ch[o]["control"]:
                c["brier"] = round((c["p_dem"] - (1 if ctl_y == "D" else 0)) ** 2, 4) if (ctl_y and c["p_dem"] is not None) else None
            target[o] = {"control": ch[o]["control"], "control_outcome": outcomes_ch[o], "seats": ch[o]["seats"],
                         "races": race_list(f, o),
                         "score": {"probabilities": score_block(f, y, o, ("model", "market")),
                                   "ratings": score_block(f, y, o, ("rating",)),
                                   "head_to_head": head_to_head(f, y, o)}}
    return block


# ---------------------------------------------------------------------- write-up

def pct(x):
    return "–" if x is None else f"{100 * x:.0f}%"


def fmt(x, d=3):
    return "–" if x is None else f"{x:.{d}f}"


def md_tables(b: dict, label: str) -> list[str]:
    L = []
    for o in OFFICES:
        blk = b[o]
        L.append(f"\n### {o.capitalize()}\n")
        oc = blk["control_outcome"]
        L.append(f"Outcome so far: control {oc['control'] or 'not yet decided'}; {oc['dem_seats_called']} Democratic seats "
                 f"among called races, {oc['uncalled_races']} races uncalled.\n")
        L.append("| Forecast | Chance of Democratic control | Brier | Democratic seats (median or projection, 80% range) | Source, date |")
        L.append("|---|---|---|---|---|")
        seats = {s["name"]: s for s in blk["seats"]}
        for c in sorted(blk["control"], key=lambda c: -(c["p_dem"] or 0)):
            s = seats.get(c["name"])
            st = "–"
            if s:
                mid = s.get("dem_median") if s.get("dem_median") is not None else s.get("dem_projection")
                rng = f" ({s['dem_lo80']} to {s['dem_hi80']})" if s.get("dem_lo80") is not None else ""
                st = f"{mid}{rng}"
            src = c["source"] if not str(c["source"]).startswith("http") else f"[link]({c['source']})"
            tag = " (news report)" if c.get("news_report") else ""
            kind = " (market price)" if c.get("kind") == "market" else ""
            L.append(f"| {c['name']}{kind}{tag} | {pct(c['p_dem'])} | {fmt(c.get('brier'), 2)} | {st} | {src}, {c['captured']} |")
        for k, title in (("probabilities", "Probabilities and market prices"), ("ratings", "Ratings (mapped to probabilities)")):
            sc = blk["score"][k]
            if not sc or not sc.get("forecasters") or len(sc["forecasters"]) < 2:
                if sc.get("head_to_head_only"):
                    L.append(f"\n{title}: {', '.join(sc['head_to_head_only'])} cover too few called races for a common set; see the head-to-head table.\n")
                continue
            L.append(f"\n{title}: {sc['races_common']} called races covered by every forecast in this table "
                     f"({sc['races_competitive']} competitive; the Democratic side won {sc['democratic_side_won']} "
                     f"of all and {sc['democratic_side_won_competitive']} of the competitive).\n")
            if sc.get("head_to_head_only"):
                L.append(f"Not in this table because they cover under {MIN_COVERAGE:.0%} of called races: "
                         f"{', '.join(sc['head_to_head_only'])} (see the head-to-head table).\n")
            L.append("| Forecast | Brier | Log loss | Upsets missed | Brier, competitive | Log loss, competitive | Upsets missed, competitive | Called races covered |")
            L.append("|---|---|---|---|---|---|---|---|")
            for n, s in sorted(sc["forecasters"].items(), key=lambda kv: kv[1]["brier"]):
                L.append(f"| {n} | {fmt(s['brier'])} | {fmt(s['log_loss'])} | {s['upsets_missed']:g} | "
                         f"{fmt(s['brier_competitive'])} | {fmt(s['log_loss_competitive'])} | "
                         f"{'–' if s['upsets_missed_competitive'] is None else format(s['upsets_missed_competitive'], 'g')} | {s['covered_called']} |")
        h2h = blk["score"]["head_to_head"]
        if h2h:
            L.append("\nEach forecast against v1 on every called race both cover:\n")
            L.append("| Forecast | Races | Brier | v1 Brier | Log loss | v1 log loss | Competitive races | Brier, competitive | v1 Brier, competitive |")
            L.append("|---|---|---|---|---|---|---|---|---|")
            for r in sorted(h2h, key=lambda r: r["forecaster"]):
                L.append(f"| {r['forecaster']} | {r['n']} | {fmt(r['brier'])} | {fmt(r['v1_brier'])} | {fmt(r['log_loss'])} | "
                         f"{fmt(r['v1_log_loss'])} | {r['n_competitive']} | {fmt(r['brier_competitive'])} | {fmt(r['v1_brier_competitive'])} |")
    return L


def write_md(b: dict, path: Path = OUT_MD) -> None:
    head = (ROOT / "results" / "comparison_intro.md").read_text() if (ROOT / "results" / "comparison_intro.md").exists() else ""
    L = [head.rstrip(), "\n## As of 22 October\n"]
    L += md_tables(b, "oct22")
    L += ["\n## Final pre-election numbers (1 to 3 November)\n",
          "v1 is shown at its 22 October values; the others are their last numbers before polls closed.\n"]
    L += md_tables(b["final"], "final")
    L += ["\n## Not found or not collected\n", "| Forecaster | What | Why |", "|---|---|---|"]
    L += [f"| {m['forecaster']} | {m['what']} | {m['why']} |" for m in b["missing"]]
    L += ["", f"Calls: {b['results']['source']}, pulled {b['results']['as_of']} ({b['results']['status']}).",
          f"Generated by `python -m forecast.compare` at {b['generated']}.", ""]
    path.write_text("\n".join(L))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", help="path to results.json (default: results/results.json, then the results-log branch)")
    a = ap.parse_args(argv)
    b = build(a.results)
    OUT_JSON.write_text(json.dumps(b, indent=1, ensure_ascii=False, default=clean) + "\n")
    write_md(b)
    print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

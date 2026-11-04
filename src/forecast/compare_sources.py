"""Collect market prices for the comparison with other forecasts (issue #25).

    python -m forecast.compare_sources polymarket [--when oct22|final]
    python -m forecast.compare_sources kalshi     [--when oct22|final]
    python -m forecast.compare_sources ddhq       (writes both dates)

Public, unauthenticated endpoints only, at a polite rate (one request every 0.3 s or slower):

    Polymarket  gamma-api.polymarket.com/events (market list)
                clob.polymarket.com/prices-history (hourly price history)
    Kalshi      api.elections.kalshi.com/trade-api/v2/events (market list)
                .../series/{series}/markets/{ticker}/candlesticks (hourly candles)
    DDHQ        elections2026.thehill.com/api/forecast/... (the JSON The Hill's public
                forecast pages load: each race's daily time series and final forecast)

Each run writes results/comparisons/<source>_<date>.csv, one row per market side, with the
URL queried, the price used, the timestamp of that price and the time of capture.

The price used is the last observation at or before the cut-off:

    oct22  23:59:59 ET on 22 October 2026 (EDT) = 2026-10-23T03:59:59Z, the day v1 was locked
    final  23:59:59 ET on 2 November 2026 (EST) = 2026-11-03T04:59:59Z, the eve of election day

A market price is a price, not a model. It is reported as an implied probability: the
Democratic-side price divided by the sum of the Democratic-side and Republican prices, which
removes the small overround between the two sides (see `implied_two_way`).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUTDIR = ROOT / "results" / "comparisons"
V1 = ROOT / "forecasts" / "v1"

CUTOFFS = {
    "oct22": dt.datetime(2026, 10, 23, 3, 59, 59, tzinfo=dt.timezone.utc),
    "final": dt.datetime(2026, 11, 3, 4, 59, 59, tzinfo=dt.timezone.utc),
}
CUTOFF_LABEL = {"oct22": "2026-10-22 23:59:59 ET (2026-10-23T03:59:59Z)",
                "final": "2026-11-02 23:59:59 ET (2026-11-03T04:59:59Z)"}
FILE_DATE = {"oct22": "2026-10-22", "final": "2026-11-02"}

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new-hampshire": "NH", "new-jersey": "NJ", "new-mexico": "NM",
    "new-york": "NY", "north-carolina": "NC", "north-dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode-island": "RI", "south-carolina": "SC",
    "south-dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west-virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}

UA = {"User-Agent": "midterms-forecast-2026 comparison (public research; github.com/olivia-jackson-lambert)"}
_last = [0.0]


def get(url: str, params: dict | None = None, pause: float = 0.3, tries: int = 4):
    """GET with a minimum gap between requests and a gentle back-off on 429/5xx."""
    for k in range(tries):
        wait = pause - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = requests.get(url, params=params, headers=UA, timeout=60)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 * (k + 1))
            continue
        r.raise_for_status()
    r.raise_for_status()


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def implied_two_way(p_dem: float | None, p_rep: float | None) -> float | None:
    """Democratic-side implied probability from the two sides' prices, overround removed."""
    if p_dem is None and p_rep is None:
        return None
    if p_rep is None:
        return p_dem
    if p_dem is None:
        return 1.0 - p_rep
    total = p_dem + p_rep
    return None if total <= 0 else p_dem / total


def v1_races() -> pd.DataFrame:
    return pd.read_csv(V1 / "races.csv")


def v1_house_ids() -> set[str]:
    return set(pd.read_csv(V1 / "house_districts.csv")["cd"])


def surname(name: str) -> str:
    parts = re.sub(r"\b(Jr\.?|Sr\.?|III|II|IV)\b", "", str(name)).split()
    return parts[-1].lower() if parts else ""


def race_id(office: str, st: str, races: pd.DataFrame) -> str | None:
    """v1 race_id for a statewide race (handles the FL and OH special Senate ids)."""
    code = "SEN" if office == "senate" else "GOV"
    rows = races[(races.state == st) & (races.office == office)]
    if len(rows) == 1:
        return rows.race_id.iloc[0]
    rid = f"2026-{st}-{code}"
    return rid if rid in set(races.race_id) else None


def side_of(label: str, rid: str | None, races: pd.DataFrame) -> str | None:
    """'D' (the Democratic side as v1 defines it: Democrat or independent challenger), 'R', or None.

    An explicit party marker in the label wins; failing that, the surname of v1's candidate."""
    lab = label.lower()
    row = races.set_index("race_id").loc[rid] if rid is not None and rid in set(races.race_id) else None
    indep = row is not None and row.d_side == "independent_challenger"
    if row is not None and indep and re.search(rf"\b{surname(row.dem_candidate)}\b", lab):
        return "D"
    if re.search(r"\(r\)|republican", lab):
        return "R"
    if re.search(r"\(i\)|independent", lab):
        return "D" if indep else None
    if re.search(r"\(d\)|democrat", lab):
        return None if indep else "D"
    if row is not None:
        if surname(row.dem_candidate) and re.search(rf"\b{surname(row.dem_candidate)}\b", lab):
            return "D"
    return None


# ---------------------------------------------------------------------- Polymarket

PM_EVENTS = "https://gamma-api.polymarket.com/events"
PM_HISTORY = "https://clob.polymarket.com/prices-history"


def pm_classify(slug: str, races: pd.DataFrame, house: set[str]):
    if slug == "which-party-will-win-the-senate-in-2026":
        return ("senate", "control")
    if slug == "which-party-will-win-the-house-in-2026":
        return ("house", "control")
    m = re.fullmatch(r"([a-z-]+)-senate-election-winner(-\d+)?", slug)
    if m and m.group(1) in STATES:
        rid = race_id("senate", STATES[m.group(1)], races)
        return ("senate", rid) if rid else None
    m = re.fullmatch(r"([a-z-]+)-governor-(?:winner-2026|election-winner)(-\d+)?", slug)
    if m and m.group(1) in STATES:
        rid = race_id("governor", STATES[m.group(1)], races)
        return ("governor", rid) if rid else None
    m = re.fullmatch(r"([a-z]{2})-(\d{2}|al)-house-election-winner(-\d+)?", slug)
    if m:
        cd = f"{m.group(1).upper()}-{m.group(2).upper()}"
        return ("house", cd) if cd in house else None
    return None


def pm_events() -> list[dict]:
    out, offset = [], 0
    while True:
        page = get(PM_EVENTS, {"tag_slug": "midterms", "limit": 100, "offset": offset})
        if not page:
            break
        out += page
        offset += len(page)
    return out


def pm_price_at(token: str, cutoff: dt.datetime):
    end = int(cutoff.timestamp())
    params = {"market": token, "startTs": end - 3 * 86400, "endTs": end, "fidelity": 60}
    hist = get(PM_HISTORY, params).get("history", [])
    hist = [h for h in hist if h["t"] <= end]
    if not hist:
        return None, None
    last = max(hist, key=lambda h: h["t"])
    return float(last["p"]), last["t"]


def collect_polymarket(when: str) -> Path:
    cutoff, races, house = CUTOFFS[when], v1_races(), v1_house_ids()
    captured = now_utc()
    rows = []
    for ev in pm_events():
        kind = pm_classify(ev.get("slug", ""), races, house)
        if not kind:
            continue
        office, rid = kind
        for m in ev.get("markets", []):
            label = m.get("groupItemTitle") or m.get("question") or ""
            if float(m.get("volume") or 0) == 0:
                continue
            side = side_of(label, rid, races)
            if side is None:
                continue
            token = json.loads(m["clobTokenIds"])[0]  # the "Yes" token
            price, t = pm_price_at(token, cutoff)
            rows.append({"office": office, "id": rid, "side": side, "label": label,
                         "question": m.get("question"), "price_yes": price, "price_time": iso(t),
                         "cutoff": CUTOFF_LABEL[when],
                         "event_url": f"https://polymarket.com/event/{ev['slug']}",
                         "api_url": f"{PM_HISTORY}?market={token}&startTs={int(cutoff.timestamp()) - 3 * 86400}"
                                    f"&endTs={int(cutoff.timestamp())}&fidelity=60",
                         "captured": captured})
    return _write("polymarket", when, rows)


# ---------------------------------------------------------------------- Kalshi

KS = "https://api.elections.kalshi.com/trade-api/v2"
KS_SERIES_RE = re.compile(r"^(?:KX)?(SENATE|SENATEPARTY-?|GOVPARTY-?|GOV|HOUSE)([A-Z]{2})(\d{1,2}|AL)?(S)?$")


def ks_classify(series: str, races: pd.DataFrame, house: set[str]):
    if series == "CONTROLS":
        return ("senate", "control")
    if series == "CONTROLH":
        return ("house", "control")
    m = KS_SERIES_RE.match(series)
    if not m:
        return None
    kind, st, num, special = m.groups()
    if st not in STATES.values():
        return None
    if kind.startswith("SENATE") and num is None:
        rows = races[(races.state == st) & (races.office == "senate")]
        if special:
            rows = rows[rows.special.astype(str) == "True"]
        return ("senate", rows.race_id.iloc[0]) if len(rows) == 1 else None
    if kind.startswith("GOV") and num is None and not special:
        rid = race_id("governor", st, races)
        return ("governor", rid) if rid else None
    if kind == "HOUSE" and num is not None:
        cd = f"{st}-{'AL' if num == 'AL' else num.zfill(2)}"
        return ("house", cd) if cd in house else None
    return None


def ks_price_at(series: str, ticker: str, cutoff: dt.datetime):
    end = int(cutoff.timestamp())
    url = f"{KS}/series/{series}/markets/{ticker}/candlesticks"
    params = {"start_ts": end - 3 * 86400, "end_ts": end, "period_interval": 60}
    candles = get(url, params).get("candlesticks", [])
    candles = [c for c in candles if c["end_period_ts"] <= end + 1]
    for c in sorted(candles, key=lambda c: -c["end_period_ts"]):
        close = (c.get("price") or {}).get("close_dollars")
        if close is not None:
            return float(close), c["end_period_ts"], "last trade", url
        bid = (c.get("yes_bid") or {}).get("close_dollars")
        ask = (c.get("yes_ask") or {}).get("close_dollars")
        if bid is not None and ask is not None:
            return (float(bid) + float(ask)) / 2, c["end_period_ts"], "bid-ask midpoint", url
    return None, None, None, url


def collect_kalshi(when: str) -> Path:
    cutoff, races, house = CUTOFFS[when], v1_races(), v1_house_ids()
    captured = now_utc()
    data = get(f"{KS}/series", {"category": "Elections"})
    series_list = [s["ticker"] for s in data.get("series", [])]
    rows = []
    for series in sorted(series_list):
        kind = ks_classify(series, races, house)
        if not kind:
            continue
        office, rid = kind
        evs = get(f"{KS}/events", {"series_ticker": series, "with_nested_markets": "true"}).get("events", [])
        for ev in evs:
            if not re.search(r"-(26|2026)$", ev["event_ticker"]):
                continue
            rid = kind[1]
            if office in ("senate", "governor"):
                # Trust the event title's state over the series ticker (SENATELA-26 is titled Kentucky).
                named = [st for name, st in STATES.items() if re.match(name.replace("-", " ") + r"\b", ev.get("title", "").lower())]
                if named:
                    sel = races[(races.state == named[0]) & (races.office == office)]
                    if len(sel) == 1:
                        rid = sel.race_id.iloc[0]
            for m in ev.get("markets", []):
                label = f"{m.get('yes_sub_title') or ''} [{m['ticker']}]"
                side = side_of(m.get("yes_sub_title") or "", rid, races)
                if side is None:
                    suffix = m["ticker"].rsplit("-", 1)[-1]
                    indep = rid in set(races.race_id) and \
                        races.set_index("race_id").loc[rid].d_side == "independent_challenger"
                    side = {"D": None if indep else "D", "R": "R", "I": "D" if indep else None}.get(suffix)
                if side is None:
                    continue
                price, t, basis, url = ks_price_at(series, m["ticker"], cutoff)
                rows.append({"office": office, "id": rid, "side": side, "label": label,
                             "question": ev.get("title"), "price_yes": price, "price_time": iso(t),
                             "price_basis": basis, "cutoff": CUTOFF_LABEL[when],
                             "event_url": f"https://kalshi.com/markets/{series.lower()}",
                             "api_url": f"{url}?start_ts={int(cutoff.timestamp()) - 3 * 86400}"
                                        f"&end_ts={int(cutoff.timestamp())}&period_interval=60",
                             "captured": captured})
    return _write("kalshi", when, rows)


# ---------------------------------------------------------------------- DDHQ (via The Hill)

HILL_API = "https://elections2026.thehill.com/api/forecast"
DDHQ_NAME = "DDHQ / The Hill"


def _ddhq_id(r: dict, races: pd.DataFrame, house: set[str]):
    st = r["stateAbb"]
    if r["office"] == "US Senate":
        rows = races[(races.state == st) & (races.office == "senate")]
        return ("senate", rows.race_id.iloc[0]) if len(rows) == 1 else (None, None)
    d = r["district"]
    cd = f"{st}-AL" if (not d or d.lower().startswith("at")) else f"{st}-{int(d):02d}"
    return ("house", cd) if cd in house else (None, None)


def _ddhq_dside(parties: list[dict]):
    """Probability and margin for the side that is not Republican (v1's 'Democratic side')."""
    gop = next((p for p in parties if p.get("abbrev") == "GOP"), None)
    other = next((p for p in parties if p.get("abbrev") != "GOP"), None)
    p = None if gop is None else round(1.0 - float(gop["winProbability"]), 4)
    margin = None if other is None or other.get("margin") is None else float(other["margin"])
    return p, margin


def _seat_range(sims: list[dict], q=(0.1, 0.5, 0.9)):
    """Quantiles of Democratic seats from DDHQ's simulation histogram (count per seat total)."""
    pts = sorted((next(x["seats"] for x in s["parties"] if x["partyId"] == 1), s["count"]) for s in sims)
    total = sum(c for _, c in pts)
    out, cum, k = [], 0, 0
    for seats, c in pts:
        cum += c
        while k < len(q) and cum >= q[k] * total:
            out.append(seats)
            k += 1
    return out


def collect_ddhq() -> list[Path]:
    """DDHQ's forecast through the public JSON endpoints The Hill's forecast pages load.

    Writes ddhq_2026-10-22.csv (each race's value on the 2026-10-22 point of its daily time
    series) and ddhq_2026-11-03.csv (the forecast as last updated before polls closed)."""
    races, house = v1_races(), v1_house_ids()
    captured = now_utc()
    top = get(f"{HILL_API}/2026", pause=1.0)
    oct22, final = [], []
    for ov in top["officeOverviews"]:
        office = {3: "house", 4: "senate"}[ov["forecast"]["officeId"]]
        url = f"{HILL_API}/2026"
        ts = {t["date"]: t for t in ov["timeseries"]}
        t = ts.get("2026-10-22")
        if t:
            dem = next(x for x in t["parties"] if x["abbrev"] == "DEM")
            oct22.append({"forecaster": DDHQ_NAME, "office": office, "id": "control", "p_dem": dem["winProbability"],
                          "seats_dem": dem["seats"], "seats_lo80": None, "seats_hi80": None,
                          "model_date": "2026-10-22", "updated_at": None, "source_url": url,
                          "captured": captured, "note": "time-series point for 2026-10-22; seats is the projection shown"})
        dem = next(x for x in ov["forecast"]["parties"] if x["abbrev"] == "DEM")
        lo, med, hi = _seat_range(ov["simulations"])
        final.append({"forecaster": DDHQ_NAME, "office": office, "id": "control", "p_dem": dem["winProbability"],
                      "seats_dem": dem["seats"], "seats_median_sim": med, "seats_lo80": lo, "seats_hi80": hi,
                      "model_date": ov["forecast"]["updatedAt"][:10], "updated_at": ov["forecast"]["updatedAt"] + " UTC",
                      "source_url": url, "captured": captured,
                      "note": "seats is the projection shown; 80% range from the simulation histogram"})
    for r in top["racesViz"]:
        office, rid = _ddhq_id(r, races, house)
        if rid is None:
            print("unmapped", r["slug"])
            continue
        url = f"{HILL_API}/race/{r['id']}"
        d = get(url, pause=1.0)
        f = d["forecast"]
        p, margin = _ddhq_dside(f["parties"])
        final.append({"forecaster": DDHQ_NAME, "office": office, "id": rid, "p_dem": p, "margin_dem": margin,
                      "rating": f.get("ratingWithParty"), "model_date": f["updatedAt"][:10],
                      "updated_at": f["updatedAt"] + " UTC", "source_url": url, "captured": captured})
        t = next((t for t in d.get("timeseries", []) if t["date"] == "2026-10-22"), None)
        if t:
            p, margin = _ddhq_dside(t["parties"])
            oct22.append({"forecaster": DDHQ_NAME, "office": office, "id": rid, "p_dem": p, "margin_dem": margin,
                          "rating": None, "model_date": "2026-10-22", "updated_at": None,
                          "source_url": url, "captured": captured, "note": "time-series point for 2026-10-22"})
    OUTDIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, rows in (("ddhq_2026-10-22.csv", oct22), ("ddhq_2026-11-03.csv", final)):
        path = OUTDIR / name
        pd.DataFrame(rows).to_csv(path, index=False)
        print(f"{path.relative_to(ROOT)}: {len(rows)} rows")
        paths.append(path)
    return paths


def _write(source: str, when: str, rows: list[dict]) -> Path:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    path = OUTDIR / f"{source}_{FILE_DATE[when]}.csv"
    pd.DataFrame(rows).sort_values(["office", "id", "side"]).to_csv(path, index=False)
    print(f"{path.relative_to(ROOT)}: {len(rows)} rows")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", choices=["polymarket", "kalshi", "ddhq"])
    ap.add_argument("--when", choices=list(CUTOFFS), default="oct22")
    a = ap.parse_args(argv)
    if a.source == "ddhq":
        collect_ddhq()
    else:
        {"polymarket": collect_polymarket, "kalshi": collect_kalshi}[a.source](a.when)


if __name__ == "__main__":
    main()

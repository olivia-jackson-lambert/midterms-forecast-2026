"""The House: Democratic two-party share and win probability in all 435 districts, and the
distribution of seats.

Same structure as Stage B (forecast.vote_model), with one office. On the logit scale, the
Democratic share of the two-party vote in district i (state s, region g) is

    logit(share_i) = logit(house_T)                              national House vote
                     + a + b * (logit(lean_i) - logit(pres_T))   district lean against the nation
                     + d * incumbency_i                          +1 Democratic incumbent running, -1 Republican
                     + h * track_record_i                        incumbent's last result against expectation
                     + region effect + state effect + district noise,

- lean_i: the district's Democratic two-party share in the last presidential election, on the
  map in force that year (2016 on the 2018 map, 2020 on the 2022 map, 2024 on the 2026 map), from
  The Downballot / Daily Kos Elections' calculations (see SHEETS). Not turnout weighted: Stage B
  showed weighting moves state leans by 0.07 points on average, and there is no public county or
  precinct split of every district to weight with;
- pres_T: national presidential two-party share (county panel, as in Stage B);
- house_T: national House two-party share; the actual result in training, and in a forecast a
  draw from forecast.generic_ballot.national_environment, the distribution Stage B uses;
- track_record_i: for an incumbent running again in a district that kept its shape (the last
  presidential result on the old and new lines within half a point), their last House result
  minus what a uniform swing predicted then, on the logit scale. Zero otherwise.

Where one major party has no candidate but the other faces an independent or minor-party
opponent, that opponent stands in for the missing side (as in Stage B), with INDEPENDENT_EXTRA_SD
more district noise, and an independent win is counted as neither party's seat. Only districts
with a single candidate or candidates of one party (California's same-party top-two finals) are
certain holds. Neither kind is used for training or scoring: only Democrat-against-Republican
results are.

Data (all public, cached under data/raw/house/):
- presidential results by district: The Downballot's public Google Sheets (SHEETS);
- district results 2016-2024, members and 2026 nominees: Wikipedia's "<year> United States House
  of Representatives elections" pages, which list every district with its member, status and
  candidates (with certified percentages for past years).

    python -m forecast.house [--refresh]
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import pymc as pm
import requests
from scipy.special import expit, logit

from . import generic_ballot
from .ingest import OUT, RAW, UA, fetch
from .races import STATES, _clean, _party_code, _surname, candidates
from .vote_model import INDEPENDENT_EXTRA_SD          # extra race noise where an independent stands in

RAW_HOUSE = RAW / "house"
SIMS = 20_000
SEED = 2026
SEATS = 435
MAJORITY = 218
REGIONS = ["Northeast", "Midwest", "South", "West"]
REGION = {**{s: "Northeast" for s in "CT ME MA NH RI VT NJ NY PA".split()},
          **{s: "Midwest" for s in "IL IN MI OH WI IA KS MN MO NE ND SD".split()},
          **{s: "South" for s in "DE FL GA MD NC SC VA WV AL KY MS TN AR LA OK TX DC".split()},
          **{s: "West" for s in "AZ CO ID MT NV NM UT WY AK CA HI OR WA".split()}}
ABBR = {v: k for k, v in STATES.items()}

# Presidential results by congressional district: The Downballot (formerly Daily Kos Elections),
# the "Vote totals" tab of each public sheet, exported as CSV. Key: (presidential year, map year).
# Index page: https://the-db.co/presbycd
SHEETS = {
    (2024, 2026): ("1eZfaFI-c-PFOoKx1-zZA2MP0_dxRq_LVK0re3BOQqy0", "1491069057"),  # all maps adopted for 2026
    (2024, 2024): ("1ng1i_Dm_RMDnEvauH44pgE6JCUsapcuu8F2pCfeLWFo", "1491069057"),
    (2020, 2022): ("1CKngqOp8fzU22JOlypoxNsxL6KSAH920Whc-rd7ebuM", "1913458313"),
    (2020, 2020): ("1XbUXnI9OyfAuhP5P3vWtMuGc5UJlrhXbzZo3AwMuHtk", "2098782715"),
    (2016, 2018): ("1zLNAuRqPauss00HDz4XbTH2HqsCzMe0pR8QmD1K8jk8", "470496023"),
    (2016, 2016): ("1VfkHtzBTP5gf4jAu8tcVQgsBJ1IDvXEHjuMqYlOgYbA", "1445854919"),
}
SHEET_URL = "https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
DEM_NOMINEE = {2016: "Clinton", 2020: "Biden", 2024: "Harris"}
# Wikipedia House pages. Past years are the copies generic_ballot.house_vote() saved; 2026 is
# saved with the fetch date in the name, and the newest copy is used.
HOUSE_PAGE = "https://en.wikipedia.org/wiki/{year}_United_States_House_of_Representatives_elections"
PREV = {2018: 2016, 2022: 2020, 2026: 2024}          # last House election before each midterm
# Off: in the 2022 backtest (trained on 2018) the track record made Brier and vote-share error
# worse (0.035 v 0.031, 2.26 v 2.22 points), failing the rule Stage B set for fundraising before
# any House run: a term stays only if it improves 2022 on both. notes/house.md.
USE_TRACK_RECORD = False
SAME_SHAPE = 0.005                                   # district "kept its shape": |change in lean| below this
# Member on the November ballot in this district: past years "re-elected" or "lost re-election"
# (including "re-elected but died" afterwards), 2026 "renominated", "running" (Louisiana) or
# "advanced to general" (top-two states). Everything else (retiring, lost renomination, did not
# advance, resigned, new seat) is an open seat.
RUNNING = re.compile(r"re-elected|lost re-election|renominated|incumbent running|advanced to (the )?general", re.I)
# ... unless they lost the nomination (New York 2018: Crowley stayed on a minor-party line) or withdrew.
NOT_RUNNING = re.compile(r"lost renomination|withdrew", re.I)


# --------------------------------------------------------------------------- downloads
def pres_sheet_path(pres_year: int, map_year: int) -> Path:
    RAW_HOUSE.mkdir(parents=True, exist_ok=True)
    sid, gid = SHEETS[(pres_year, map_year)]
    return fetch(SHEET_URL.format(sid=sid, gid=gid), RAW_HOUSE / f"downballot_pres{pres_year}_lines{map_year}_votes.csv")


def house_page(year: int, refresh: bool = False) -> str:
    """Saved Wikipedia House page. 2026 copies carry their fetch date and are never overwritten."""
    if year < 2026:
        path = RAW / "generic_ballot" / f"house_{year}.html"
        if not path.exists():
            generic_ballot.house_vote()
        return path.read_text()
    RAW_HOUSE.mkdir(parents=True, exist_ok=True)
    saved = sorted(RAW_HOUSE.glob(f"wiki_house_{year}_*.html"))
    if refresh or not saved:
        path = RAW_HOUSE / f"wiki_house_{year}_{date.today().isoformat()}.html"
        if not path.exists():
            r = requests.get(HOUSE_PAGE.format(year=year), headers=UA, timeout=60)
            r.raise_for_status()
            path.write_text(r.text)
            time.sleep(1)
        saved = sorted(RAW_HOUSE.glob(f"wiki_house_{year}_*.html"))
    return saved[-1].read_text()


# --------------------------------------------------------------------------- parsers
def _votes(x) -> float:
    s = str(x).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return float("nan")


def cd_code(location: str) -> str | None:
    """'Alabama 1' -> 'AL-01', 'Alaska at-large' -> 'AK-AL'; None for anything else."""
    loc = _clean(location)
    m = re.match(r"(.+?)\s+(at-large|\d+)$", loc, re.I)
    if not m or m.group(1) not in STATES:
        return None
    st, n = STATES[m.group(1)], m.group(2)
    return f"{st}-AL" if n.lower() == "at-large" else f"{st}-{int(n):02}"


def parse_pres_sheet(text: str, pres_year: int) -> pd.DataFrame:
    """District, Democratic and Republican presidential votes from a Downballot 'Vote totals' CSV.

    The sheets differ in layout (one to four elections, one or two header rows), so the columns
    are found from the header row naming the Democratic nominee next to 'Trump'.
    """
    raw = pd.read_csv(StringIO(text), header=None, dtype=str, keep_default_na=False)
    dem = DEM_NOMINEE[pres_year]
    col = None
    for _, row in raw.iterrows():
        cells = [c.strip() for c in row.tolist()]
        for j in range(len(cells) - 1):
            if cells[j] == dem and cells[j + 1] == "Trump":
                col = j
                break
        if col is not None:
            break
    if col is None:
        raise ValueError(f"no {dem}/Trump columns found")
    rows = raw[raw[0].str.strip().str.match(r"^[A-Z]{2}-(\d\d|AL)$")]
    out = pd.DataFrame({"cd": rows[0].str.strip(), "dem": rows[col].map(_votes), "rep": rows[col + 1].map(_votes)})
    out["lean"] = out["dem"] / (out["dem"] + out["rep"])
    out["state_po"] = out["cd"].str[:2]
    return out.reset_index(drop=True)


def pres_by_district(pres_year: int, map_year: int) -> pd.DataFrame:
    return parse_pres_sheet(pres_sheet_path(pres_year, map_year).read_text(), pres_year)


def _member(cell) -> str:
    return re.split(r"\s+Redistricted from", _clean(cell))[0].strip()


def district_rows(html: str) -> pd.DataFrame:
    """Every row of the page's per-state district tables (columns Location ... Candidates).

    A district appears twice when redistricting put two members in it; both rows are kept here.
    """
    rows = []
    for t in pd.read_html(StringIO(html)):
        cols = [_clean(c[-1] if isinstance(c, tuple) else c) for c in t.columns]
        if not cols or cols[0] != "Location" or not any("andidates" in c for c in cols):
            continue
        status = next((c for c in cols if c in ("Results", "Status")), None)
        member = next((c for c in cols if c in ("Member", "Representative")), None)
        cand = next(c for c in cols if "andidates" in c)
        t = t.copy()
        t.columns = cols
        for _, r in t.iterrows():
            cd = cd_code(r["Location"])
            if cd is None:
                continue
            rows.append({"cd": cd, "member": _member(r[member]), "member_party": _clean(r["Party"]),
                         "status": _clean(r[status]) if status else "", "candidates_cell": str(r[cand])})
    return pd.DataFrame(rows)


def _running(member: str, party: str, status: str) -> bool:
    if not member or member.lower().startswith(("none", "vacant")) or party.lower().startswith(("none", "vacant")):
        return False
    return bool(RUNNING.search(status)) and not NOT_RUNNING.search(status)


def _stand_in(cands: list, party: str) -> tuple[str, float | None]:
    """The main opponent of a lone major party: the strongest other candidate in a past race,
    or, before the election, the first independent listed."""
    others = [c for c in cands if _party_code(c[1]) != party]
    if any(c[2] is not None for c in others):
        best = max((c for c in others if c[2] is not None), key=lambda c: c[2])
    else:
        best = next((c for c in others if c[1].startswith(("Independent", "Nonpartisan"))), others[0])
    return best[0], best[2]


def districts(html: str, year: int) -> pd.DataFrame:
    """One row per district: members running, incumbency, candidates and (past years) result.

    d_side / r_side: "democrat" / "republican" when that party has a candidate. Where one major
    party is missing but the other faces an independent or minor-party opponent (California 6
    in 2026: Kiley, elected as a Republican, now an independent, against a Democrat), the main
    opponent stands in for the missing side ("independent_challenger"), as in Stage B.
    contested: a Democrat against a Republican (and, for past results, the top two finishers
    were not from one party). modelled: contested or a stand-in race. Districts that are neither
    (a single candidate, or only candidates of one party) are certain holds (sole_party).
    """
    rows = district_rows(html)
    out = []
    for cd, g in rows.groupby("cd", sort=True):
        cands = candidates(g["candidates_cell"].iloc[0])
        parties = [_party_code(p) for _, p, _ in cands]
        d_tot = sum(v for (_, p, v) in cands if v is not None and _party_code(p) == "D")
        r_tot = sum(v for (_, p, v) in cands if v is not None and _party_code(p) == "R")
        has_d, has_r = "D" in parties, "R" in parties
        # Before the election only an independent can stand in for a missing party, as in Stage B;
        # a Libertarian or Green against a lone major party is not a real contest. Past races use
        # the result (the strongest other candidate), and are excluded from training anyway.
        if any(v is not None for _, _, v in cands):
            has_other = any(p not in ("D", "R") for p in parties)
        else:
            has_other = any(pp.startswith(("Independent", "Nonpartisan")) for _, pp, _ in cands)
        ranked = sorted([c for c in cands if c[2] is not None], key=lambda c: -c[2])
        same_top_two = len(ranked) >= 2 and _party_code(ranked[0][1]) == _party_code(ranked[1][1])
        d_side = r_side = stand_in = None
        if has_d and has_r:
            d_side, r_side = "democrat", "republican"
        elif has_d and has_other:
            d_side, r_side = "democrat", "independent_challenger"
            stand_in, pct = _stand_in(cands, "D")
            r_tot = pct or 0.0
        elif has_r and has_other:
            d_side, r_side = "independent_challenger", "republican"
            stand_in, pct = _stand_in(cands, "R")
            d_tot = pct or 0.0
        modelled = d_side is not None and not same_top_two
        contested = modelled and stand_in is None
        if not modelled:
            d_side = r_side = stand_in = None
        running = [(m, p) for m, p, s in zip(g["member"], g["member_party"], g["status"]) if _running(m, p, s)]
        # An independent member who is the stand-in is the incumbent on that side (Kiley, CA-06),
        # as Stage B treats King and Sanders on the Democratic side.
        def side(m, p):
            code = _party_code(p)
            if code == "I" and stand_in and _surname(m) == _surname(stand_in):
                return 1 if d_side == "independent_challenger" else -1
            return 1 if code == "D" else -1 if code == "R" else 0
        inc = sum(side(m, p) for m, p in running)
        # Democratic side's share of the two sides' vote (past years). For stand-in races it is
        # kept for reference only; they are never used for training or scoring, as in Stage B.
        side_share = d_tot / (d_tot + r_tot) if modelled and d_tot and r_tot else np.nan
        # Who holds (or will hold) the seat when there is no contest: the only major party on the ballot.
        sole = None if modelled else "D" if has_d and not has_r else "R" if has_r and not has_d else None
        if year < 2026 and ranked:
            winner = _party_code(ranked[0][1])
        elif year < 2026 and len(cands) == 1:
            winner = _party_code(cands[0][1])
        else:
            winner = None
        out.append({
            "year": year, "cd": cd, "state_po": cd[:2],
            "members": "; ".join(g["member"]), "member_parties": "; ".join(g["member_party"]),
            "status": " | ".join(g["status"]),
            "incumbents_running": "; ".join(m for m, _ in running),
            "incumbency": float(np.clip(inc, -1, 1)),
            "candidates": "; ".join(n for n, _, _ in cands),
            "dem_candidates": "; ".join(n for n, p, _ in cands if _party_code(p) == "D"),
            "rep_candidates": "; ".join(n for n, p, _ in cands if _party_code(p) == "R"),
            "stand_in": stand_in, "d_side": d_side, "r_side": r_side,
            "contested": contested, "modelled": modelled, "sole_party": sole,
            "result_side_2p": side_share, "result_dem_2p": side_share if contested else np.nan,
            "winner": winner,
        })
    df = pd.DataFrame(out)
    # Past races with both parties listed but two of one party in the top two (California's
    # top-two final, Louisiana's all-party primary): the seat went to that party.
    tie = ~df["modelled"] & df["sole_party"].isna()
    df.loc[tie, "sole_party"] = df.loc[tie, "winner"]
    if (~df["modelled"] & df["sole_party"].isna()).any():
        raise ValueError(f"{year}: no major party in {df.loc[~df['modelled'] & df['sole_party'].isna(), 'cd'].tolist()}")
    return df


# --------------------------------------------------------------------------- frame
def national_pres(year: int) -> float:
    """National Democratic two-party presidential share in `year` (county panel, as Stage B)."""
    p = pd.read_parquet(OUT / "county_panel.parquet", columns=["year", "dem", "rep"])
    p = p[p["year"] == year]
    return float(p["dem"].sum() / (p["dem"].sum() + p["rep"].sum()))


def track_record(cur: pd.DataFrame, year: int, house_votes: pd.Series) -> pd.DataFrame:
    """For each running incumbent: their last House result against a uniform-swing expectation.

    Used only where the district kept its shape between the last election and this one (the
    same presidential election gives a lean within SAME_SHAPE on the old and new lines) and the
    running member was a candidate in that district last time. Otherwise zero.
    """
    py = PREV[year]
    old_lines = pres_by_district(py, py).set_index("cd")["lean"]
    new_lines = pres_by_district(py, year).set_index("cd")["lean"]
    prev = districts(house_page(py), py).set_index("cd")
    nat = national_pres(py)
    same = (new_lines - old_lines.reindex(new_lines.index)).abs() < SAME_SHAPE
    out = pd.DataFrame({"same_shape": cur["cd"].map(same).fillna(False).astype(bool),
                        "prev_dem_2p": np.nan, "track_record_raw": 0.0}, index=cur.index)
    for i, r in cur.iterrows():
        if not r["incumbents_running"] or not out.at[i, "same_shape"] or r["cd"] not in prev.index:
            continue
        p = prev.loc[r["cd"]]
        names = {_surname(n) for n in str(p["candidates"]).split("; ")}
        mine = [m for m in r["incumbents_running"].split("; ") if _surname(m) in names]
        if not mine or not np.isfinite(p["result_dem_2p"]):
            continue
        expected = logit(house_votes[py]) + logit(old_lines[r["cd"]]) - logit(nat)
        out.at[i, "prev_dem_2p"] = p["result_dem_2p"]
        out.at[i, "track_record_raw"] = float(logit(p["result_dem_2p"]) - expected)
    return out


def frame(year: int, refresh: bool = False) -> pd.DataFrame:
    """One row per district (435): lean, incumbency, track record and (past years) the result."""
    pres_year = PREV[year]
    d = districts(house_page(year, refresh), year)
    lean = pres_by_district(pres_year, year)
    f = lean[["cd", "lean"]].rename(columns={"lean": "lean_plain"}).merge(d, on="cd", how="outer", indicator=True)
    missing = f[f["_merge"] != "both"]
    if len(missing):
        raise ValueError(f"{year}: districts in only one source: {missing[['cd', '_merge']].to_dict('records')}")
    f = f.drop(columns="_merge")
    f["pres_nat"] = national_pres(pres_year)
    f["region"] = f["state_po"].map(REGION)
    house = generic_ballot.house_vote().set_index("year")["house_dem_2p"]
    f = pd.concat([f, track_record(f, year, house)], axis=1)
    f["track_record"] = f["track_record_raw"] if USE_TRACK_RECORD else 0.0
    if year < 2026:
        f["actual"] = f["result_dem_2p"].where(f["contested"])
        f["house"] = float(house[year])
    return f.sort_values("cd").reset_index(drop=True)


# --------------------------------------------------------------------------- fit
PARAMS = ["a", "b", "d", "h", "sigma", "sigma_state", "sigma_region"]


def fit(train: list[pd.DataFrame], draws: int = 1000) -> dict:
    """Posterior draws (prior draws when `train` is empty), with Stage B's priors."""
    with pm.Model():
        a = pm.Normal("a", 0.0, 0.15)
        b = pm.Normal("b", 1.0, 0.3)
        d = pm.Normal("d", 0.0, 0.2)
        h = pm.Normal("h", 0.0, 0.5)
        sigma = pm.HalfNormal("sigma", 0.3)
        sigma_state = pm.HalfNormal("sigma_state", 0.1)
        sigma_region = pm.HalfNormal("sigma_region", 0.05)
        if train:
            t = pd.concat(train, ignore_index=True)
            t = t[t["actual"].notna()]
            x = (logit(t["lean_plain"]) - logit(t["pres_nat"])).to_numpy()
            st_idx, _ = pd.factorize(t["year"].astype(str) + t["state_po"])
            rg_idx, _ = pd.factorize(t["year"].astype(str) + t["region"])
            u = pm.Normal("u", 0, 1, shape=int(st_idx.max()) + 1)
            g = pm.Normal("g", 0, 1, shape=int(rg_idx.max()) + 1)
            mu = (logit(t["house"].to_numpy()) + a + b * x + d * t["incumbency"].to_numpy()
                  + h * t["track_record"].to_numpy() + sigma_state * u[st_idx] + sigma_region * g[rg_idx])
            pm.Normal("y", mu, sigma, observed=logit(t["actual"].to_numpy()))
            idata = pm.sample(draws, tune=2000, chains=4, target_accept=0.95, random_seed=SEED, progressbar=False)
            post, n_train = idata.posterior, len(t)
        else:
            idata = pm.sample_prior_predictive(draws * 4, random_seed=SEED)
            post, n_train = idata.prior, 0
    post = (post.to_dataset() if hasattr(post, "to_dataset") else post).stack(s=("chain", "draw"))
    params = {n: np.asarray(post[n].values) for n in PARAMS}
    params["n_train"] = n_train
    params["summary"] = pd.DataFrame({n: params[n] for n in PARAMS}).describe(
        percentiles=[0.055, 0.945]).T[["mean", "5.5%", "94.5%"]]
    return params


# --------------------------------------------------------------------------- simulate
def simulate(f: pd.DataFrame, params: dict, year: int, sims: int = SIMS, house_fixed: float | None = None,
             rng: np.random.Generator | None = None) -> np.ndarray:
    """Democratic-side share draws, sims x districts, with shared national, regional and state
    errors. Stand-in races get INDEPENDENT_EXTRA_SD more district noise, as in Stage B. Districts
    without a contest are 1 (only Democrats on the ballot) or 0 (only Republicans)."""
    rng = rng or np.random.default_rng(SEED + year)
    if house_fixed is None:
        env = generic_ballot.national_environment(year)
        house = np.clip(env["mean"] + env["sd"] * rng.standard_t(env["df"], sims), 0.3, 0.7)
    else:
        house = np.full(sims, house_fixed)
    k = rng.integers(0, len(params["sigma"]), sims)
    x = (logit(f["lean_plain"]) - logit(f["pres_nat"])).to_numpy()[None, :]
    st_idx, st_names = pd.factorize(f["state_po"])
    rg_idx = f["region"].map({r: i for i, r in enumerate(REGIONS)}).to_numpy()
    u = params["sigma_state"][k, None] * rng.standard_normal((sims, len(st_names)))
    g = params["sigma_region"][k, None] * rng.standard_normal((sims, len(REGIONS)))
    indep = (f["d_side"].eq("independent_challenger") | f["r_side"].eq("independent_challenger")).to_numpy()
    sd = np.sqrt(params["sigma"][k, None] ** 2 + np.where(indep, INDEPENDENT_EXTRA_SD ** 2, 0.0)[None, :])
    eps = sd * rng.standard_normal((sims, len(f)))
    lg = (logit(house)[:, None] + params["a"][k, None] + params["b"][k, None] * x
          + params["d"][k, None] * f["incumbency"].to_numpy()[None, :]
          + params["h"][k, None] * f["track_record"].to_numpy()[None, :] + u[:, st_idx] + g[:, rg_idx] + eps)
    s = expit(lg)
    fixed = ~f["modelled"].to_numpy()
    s[:, fixed] = np.where(f.loc[fixed, "sole_party"].eq("D").to_numpy(), 1.0, 0.0)[None, :]
    return s.astype(np.float32)


def winners(f: pd.DataFrame, sims: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Boolean sims x districts: Democratic, Republican and independent seat."""
    side_d = sims > 0.5
    d_ind = f["d_side"].eq("independent_challenger").to_numpy()[None, :]
    r_ind = f["r_side"].eq("independent_challenger").to_numpy()[None, :]
    dem = side_d & ~d_ind
    ind = (side_d & d_ind) | (~side_d & r_ind)
    return dem, ~dem & ~ind, ind


def summarise(f: pd.DataFrame, sims: np.ndarray) -> pd.DataFrame:
    q = np.quantile(sims, [0.1, 0.5, 0.9], axis=0)
    cols = ["cd", "year", "state_po", "members", "member_parties", "status", "incumbents_running", "incumbency",
            "dem_candidates", "rep_candidates", "stand_in", "d_side", "r_side", "contested", "modelled",
            "sole_party", "lean_plain", "pres_nat", "same_shape", "prev_dem_2p", "track_record_raw", "track_record"]
    out = f[[c for c in cols if c in f]].copy()
    out["lo80"], out["median"], out["hi80"] = q          # Democratic side's share
    dem, rep, ind = winners(f, sims)
    out["p_dem_win"], out["p_rep_win"], out["p_ind_win"] = dem.mean(0), rep.mean(0), ind.mean(0)
    if "actual" in f:
        out["actual"] = f["actual"].values
        out["winner"] = f["winner"].values
    return out


def seat_distribution(f: pd.DataFrame, sims: np.ndarray) -> pd.DataFrame:
    """Joint distribution of Democratic and independent seats (Republicans hold the rest)."""
    dem, _, ind = winners(f, sims)
    d = pd.DataFrame({"dem_seats": dem.sum(1), "independent_seats": ind.sum(1)})
    d = d.value_counts(normalize=True).rename("probability").reset_index()
    d["rep_seats"] = SEATS - d["dem_seats"] - d["independent_seats"]
    return d.sort_values(["dem_seats", "independent_seats"]).reset_index(drop=True)


def seat_summary(f: pd.DataFrame, sims: np.ndarray) -> dict:
    dem, rep, ind = winners(f, sims)
    seats, rseats = dem.sum(1), rep.sum(1)
    lo, med, hi = np.quantile(seats, [0.1, 0.5, 0.9])
    return {"median": float(med), "lo80": float(lo), "hi80": float(hi), "mean": float(seats.mean()),
            "p_dem_218": float((seats >= MAJORITY).mean()), "p_rep_218": float((rseats >= MAJORITY).mean()),
            "mean_independent_seats": float(ind.sum(1).mean())}


def run(year: int, train_years: list[int], sims: int = SIMS, params: dict | None = None,
        refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    params = params or fit([frame(y) for y in train_years])
    f = frame(year, refresh)
    s = simulate(f, params, year, sims)
    return summarise(f, s), {"params": params, "sims": s, "frame": f}


def check_against_pvi(html: str, f: pd.DataFrame) -> pd.Series:
    """Correlation, by state, of Wikipedia's Cook PVI with our lean: a check that both sources
    describe the same 2026 map (Cook's PVI blends 2020 and 2024, so it is close but not equal)."""
    pvi = {}
    for t in pd.read_html(StringIO(html)):
        cols = [_clean(c[-1] if isinstance(c, tuple) else c) for c in t.columns]
        if cols and cols[0] == "Location" and len(cols) > 1 and "PVI" in cols[1]:
            for loc, v in zip(t.iloc[:, 0], t.iloc[:, 1]):
                m = re.match(r"([DR])\+(\d+)|EVEN", _clean(v))
                cd = cd_code(loc)
                if cd and m:
                    pvi[cd] = 0 if m.group(0) == "EVEN" else int(m.group(2)) * (1 if m.group(1) == "D" else -1)
    d = f.assign(pvi=f["cd"].map(pvi), margin=100 * (2 * f["lean_plain"] - 1)).dropna(subset=["pvi"])
    nat = 100 * (2 * f["pres_nat"].iloc[0] - 1)
    d["gap"] = (d["margin"] - nat) / 2 - d["pvi"]
    return d.groupby("state_po")["gap"].agg(lambda g: g.abs().max())


def main(refresh: bool | None = None) -> None:
    if refresh is None:
        refresh = "--refresh" in sys.argv
    out, info = run(2026, [2018, 2022], refresh=refresh)
    f, s = info["frame"], info["sims"]
    out.to_parquet(OUT / "house_2026.parquet", index=False)
    seats = seat_distribution(f, s)
    summ = seat_summary(f, s)
    seats.to_csv(OUT / "house_seats_2026.csv", index=False)
    pd.DataFrame([summ]).to_csv(OUT / "house_seats_2026_summary.csv", index=False)
    info["params"]["summary"].to_csv(OUT / "house_parameters.csv")
    env = generic_ballot.national_environment(2026)
    print(f"national House vote, Democratic two-party: {env['mean']:.3f} (sd {env['sd']:.3f})")
    print(info["params"]["summary"].round(3).to_string())
    print(f"districts {len(f)}; Democrat v Republican {int(f['contested'].sum())}; stand-in races "
          f"{f.loc[f['modelled'] & ~f['contested'], 'cd'].tolist()}; certain holds D "
          f"{int((~f['modelled'] & f['sole_party'].eq('D')).sum())}, R {int((~f['modelled'] & f['sole_party'].eq('R')).sum())}; "
          f"track record available {int((f['track_record_raw'] != 0).sum())}, used: {USE_TRACK_RECORD}")
    print(f"Democratic seats: median {summ['median']:.0f} (80%: {summ['lo80']:.0f}-{summ['hi80']:.0f}); "
          f"P(218+) {summ['p_dem_218']:.3f}; P(Republicans 218+) {summ['p_rep_218']:.3f}; "
          f"independent seats, mean {summ['mean_independent_seats']:.2f}")
    print(out[out["modelled"] & ~out["contested"]][["cd", "dem_candidates", "rep_candidates", "stand_in", "incumbency", "lean_plain",
                                                     "median", "p_dem_win", "p_ind_win"]].round(3).to_string(index=False))
    gap = check_against_pvi(house_page(2026), f)
    print("largest gap between our lean and Wikipedia's Cook PVI, by state (points):")
    print(gap.sort_values(ascending=False).head(8).round(1).to_string())
    close = out[(out["p_dem_win"] > 0.1) & (out["p_dem_win"] < 0.9)].sort_values("p_dem_win")
    print(close[["cd", "incumbents_running", "dem_candidates", "rep_candidates", "lean_plain", "median",
                 "p_dem_win"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()

"""Race-level polls: collection, a simple average per race, and a blend with the fundamentals.

This is a separate layer on top of Stage B (forecast.vote_model). It is switched on and off by
vote_model.USE_POLLS and never changes the fundamentals fit itself.

Data
----
For every Senate and governor race in 2018, 2022 and 2026, the race's own Wikipedia article
("<year> United States Senate election in <State>", "... special election in <State>",
"<year> <State> gubernatorial election"), fetched from Wikipedia (one request a second; the
API, used for old revisions, about one every six seconds) and saved under data/raw/polls/. Past years use the article as it is now (its poll tables keep each poll's
field dates, so the date cut-off below does the work); the article as it stood on 1 October is
also saved, and `revision_check()` counts polls in the window that were not yet listed then.
2026 articles are saved with the fetch date in the file name and never overwritten.

Two races decided in an all-party first round, Mississippi's 2018 special and Louisiana's 2022
Senate race, get no polls: their results are party totals across several candidates.

Only general-election head-to-heads between the actual nominees are kept: tables with a column
for the Democratic-side nominee and one for the Republican nominee (forecast.races; an
independent standing in for the Democratic side is used where there is no Democrat). Tables in
party-primary sections and poll-aggregator rows are dropped. From each row: pollster, field
dates, sample size, population (LV, RV, A; blank when the article gives none) and both shares.

No look-ahead
-------------
2018 and 2022: a poll counts only if its field period ended on or before 26 September, which
leaves a few days for publication before the 1 October information date the backtests use.
2026: polls ending on or before the run date. In every year polls must also have ended within
WINDOW_DAYS (90) of the cut-off.

The poll average (fixed before any testing)
-------------------------------------------
- One poll per pollster: its most recent poll (sponsors in brackets are ignored, so PPP for two
  clients is one pollster). Where the same poll reports several versions, the likely-voter one
  is used, then the unspecified one, then registered voters, then adults. Where a pollster has
  several matchups with the same dates (e.g. with and without a minor candidate), the first
  table in the article wins.
- Each poll's Democratic-side two-party share, d / (d + r), weighted by
      0.5 ** (age / 21 days)                                   recency, half-life 21 days
    * sqrt(min(n, 2000) / 600)                                 sample size; 600 when not given
    * {LV or unspecified: 1.0, RV: 0.8, A: 0.6}                population
  where age is days from the end of fieldwork to the cut-off.
- Reported with the number of polls and their effective number, n_eff = (sum w)^2 / sum w^2.

The blend
---------
On the logit scale, a poll average P_r misses the result by
    logit(result_r) - logit(P_r) = N_y + e_r,
    N_y ~ Normal(0, s_nat^2)                      national polling error, shared by every race
    e_r ~ Normal(0, s_floor^2 + s_poll^2 / n_eff_r)   race error, shrinking with more polls.
No average bias is assumed (the sign of the national miss changes from year to year).

The three spreads are estimated in PyMC only from years before the target: 2018 for the 2022
backtest, 2018 and 2022 for 2026. The 2018 backtest has no earlier year, so it uses the priors
alone. They are weakly informative and set from the typical published error of a single
state-level poll, about 5 points of margin (2.5 points of share, roughly 0.10 on the logit
scale near 50%, so a standard deviation of about 0.12):
    s_nat   ~ LogNormal(log 0.05, 0.5)     a shared miss of about 2.5 points of margin
    s_floor ~ LogNormal(log 0.06, 0.5)     race error that more polls do not remove
    s_poll  ~ LogNormal(log 0.09, 0.5)     single-poll error that averaging does remove
which together give a single poll an error of about 0.12 (6 points of margin).

The fundamentals simulations are treated as the prior for each race and the poll average as a
noisy observation of it. In each simulation, the poll observation is perturbed by a draw of
the national error (the same for every race in that simulation) and of the race error, and the
fundamentals draw moves towards it by the precision weight
    k_r = v_f / (v_f + v_p),   v_f = variance of the fundamentals draws (logit),
                               v_p = s_nat^2 + s_floor^2 + s_poll^2 / n_eff_r.
This gives the usual precision-weighted mean and variance in every race and keeps the
correlations: fundamentals errors through the simulations, polling errors through the shared
national draw. Races with no qualifying poll keep the fundamentals forecast unchanged.

    python -m forecast.polls [--refresh] [--no-revisions]
        fetch (2026 again with --refresh), parse and average; --no-revisions skips the
        1 October revisions used only for the check on late-listed polls
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import time
import unicodedata
from io import StringIO

import numpy as np
import pandas as pd
import requests
from scipy.special import expit, logit

from .ingest import OUT, RAW, UA

RAW_POLLS = RAW / "polls"
WIKI_API = "https://en.wikipedia.org/w/api.php"
CUTOFF = {2018: "2018-09-26", 2022: "2022-09-26"}       # field period ended on or before
REVISION_AS_OF = {2018: "2018-10-01T00:00:00Z", 2022: "2022-10-01T00:00:00Z"}
WINDOW_DAYS = 90
HALF_LIFE_DAYS = 21.0
SAMPLE_REF, SAMPLE_CAP, SAMPLE_DEFAULT = 600, 2000, 600
POP_WEIGHT = {"LV": 1.0, "": 1.0, "V": 1.0, "RV": 0.8, "A": 0.6}
POP_ORDER = {"LV": 0, "V": 1, "": 1, "RV": 2, "A": 3}
PRIOR = {"s_nat": 0.05, "s_floor": 0.06, "s_poll": 0.09}  # medians on the logit scale
PRIOR_LOG_SD = 0.5
SEED = 2026
# Decided in an all-party first round with several candidates of one party on the ballot: the
# result is each party's total, which a head-to-head of two named candidates does not measure.
ALL_PARTY_FIRST_ROUND = {"2018-MS-SENS", "2022-LA-SEN"}
AGGREGATORS = re.compile(r"real ?clear|fivethirtyeight|538|270towin|decision desk|ddhq|race ?to ?the ?wh|"
                         r"silver bulletin|fiftyplusone|votehub|the hill|average|aggregat|cook political|"
                         r"split ticket|polymarket|kalshi|predictit", re.I)
PRIMARY_SECTION = re.compile(r"(democratic|republican|dfl|libertarian|green|independent|party)\b.*primar|"
                             r"^primary|primary election", re.I)
MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9


# --------------------------------------------------------------------------- articles
def title(year: int, office: str, special: bool, state: str) -> str:
    if office == "GOV":
        return f"{year} {state} gubernatorial election"
    return f"{year} United States Senate {'special ' if special else ''}election in {state}"


_last_request = [0.0]
PAGE_URL = "https://en.wikipedia.org/wiki/{}"
GAP_SECONDS = {"page": 1.0, "api": 6.0}     # the API allows anonymous clients about ten calls a minute


def _get(url: str, params: dict | None = None, kind: str = "page") -> requests.Response:
    """Polite GET: spaced requests, and waits out a 429 (Retry-After) before trying again."""
    for _ in range(6):
        wait = GAP_SECONDS[kind] - (time.time() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        r = requests.get(url, params=params, headers=UA, timeout=60)
        _last_request[0] = time.time()
        if r.status_code != 429:
            return r
        time.sleep(float(r.headers.get("retry-after", 30)) + 1)
    r.raise_for_status()
    return r


def _api(params: dict) -> dict:
    r = _get(WIKI_API, {**params, "format": "json", "formatversion": 2}, kind="api")
    r.raise_for_status()
    return r.json()


def revision_as_of(page: str, when: str) -> int | None:
    """Id of the article's last revision at or before `when` (ISO timestamp)."""
    j = _api({"action": "query", "prop": "revisions", "titles": page, "rvlimit": 1, "rvdir": "older",
              "rvstart": when, "rvprop": "ids|timestamp", "redirects": 1})
    pages = j["query"]["pages"]
    revs = pages[0].get("revisions") if pages else None
    return int(revs[0]["revid"]) if revs else None


def article(race_id: str, page: str, refresh: bool = False, as_of: str | None = None) -> str | None:
    """HTML of the article (or of its revision as of `as_of`), cached under data/raw/polls/.

    Files are only ever added: past years are saved once; 2026 is saved per fetch date."""
    RAW_POLLS.mkdir(parents=True, exist_ok=True)
    if as_of:
        hits = sorted(RAW_POLLS.glob(f"{race_id}_asof*.html"))
        if hits:
            return hits[-1].read_text()
        rev = revision_as_of(page, as_of)
        if rev is None:
            return None
        html = _api({"action": "parse", "oldid": rev, "prop": "text"})["parse"]["text"]
        (RAW_POLLS / f"{race_id}_asof{as_of[:10]}_rev{rev}.html").write_text(html)
        return html
    current = race_id.startswith("2026")
    hits = sorted(RAW_POLLS.glob(f"{race_id}_[0-9]*.html" if current else f"{race_id}.html"))
    if hits and not (refresh and current):
        return hits[-1].read_text()
    r = _get(PAGE_URL.format(page.replace(" ", "_")))
    if r.status_code == 404:
        return None
    r.raise_for_status()
    html = r.text
    name = f"{race_id}_{dt.date.today():%Y%m%d}.html" if current else f"{race_id}.html"
    path = RAW_POLLS / name
    if not path.exists():
        path.write_text(html)
    return html


# --------------------------------------------------------------------------- parsing
def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s).replace("\u2019", "'")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def _clean(s) -> str:
    return re.sub(r"\[[^\]]*\]", "", str(s)).replace("\xa0", " ").strip()


SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def surname(name: str) -> str:
    words = [w for w in re.sub(r"[^a-z' \-]", " ", _norm(name)).split() if w.strip(".") not in SUFFIXES]
    return words[-1] if words else ""


def _match(columns: list[str], name: str) -> str | None:
    """The single column naming this candidate (surname, then first name to break ties)."""
    sur = surname(name)
    if not sur:
        return None
    hits = [c for c in columns if sur in re.findall(r"[a-z'\-]+", _norm(c))]
    if len(hits) > 1:                       # e.g. Dan S. Sullivan and Dan J. Sullivan, Alaska 2026
        hits = [c for c in hits if _norm(name) in _norm(c)] or hits
    if len(hits) > 1:
        first = _norm(name).split()[0].strip(".")
        hits = [c for c in hits if first in _norm(c).split()] or hits
    return hits[0] if len(hits) == 1 else None


def _date_part(s: str) -> tuple[int | None, int | None, int | None]:
    """'Sep 30' -> (None, 9, 30); '2, 2022' -> (2022, None, 2); 'September 2018' -> (2018, 9, None)."""
    year = re.search(r"\b(19|20)\d{2}\b", s)
    month = next((MONTHS[w] for w in re.findall(r"[a-z]+", s.lower()) if w in MONTHS), None)
    s_wo_year = re.sub(r"\b(19|20)\d{2}\b", "", s)
    day = re.search(r"\b(\d{1,2})\b", s_wo_year)
    return (int(year.group()) if year else None, month, int(day.group(1)) if day else None)


def parse_dates(text: str, default_year: int) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Start and end of fieldwork from strings such as 'September 20–25, 2018',
    'Sep 30 – Oct 2, 2022', 'December 28, 2017 – January 2, 2018' or 'October 1, 2018'.
    A month with no day ('September 2018') ends on the month's last day."""
    t = _clean(text).replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    t = re.sub(r"(?i)\b(released|published|conducted|field(ed)?)\b:?", "", t)
    parts = [p.strip() for p in re.split(r"\s*-\s*|\s+to\s+", t) if p.strip()]
    if not parts:
        return None, None
    ys, ms, ds = zip(*[_date_part(p) for p in parts])
    y_end = next((y for y in reversed(ys) if y), default_year)
    m_end = next((m for m in reversed(ms) if m), None)
    if m_end is None:
        return None, None
    d_end = ds[-1]
    try:
        end = (pd.Timestamp(y_end, m_end, d_end) if d_end else
               pd.Timestamp(y_end, m_end, 1) + pd.offsets.MonthEnd(0))
        y_start = ys[0] or (y_end - 1 if (ms[0] or m_end) > m_end else y_end)
        start = pd.Timestamp(y_start, ms[0] or m_end, ds[0] or 1)
    except ValueError:
        return None, None
    return start, end


def _sample(text) -> tuple[float | None, str]:
    t = _clean(text)
    pop = re.search(r"\b(LV|RV|A|V)\b", t)
    n = re.search(r"\d[\d,]*", t)
    size = float(n.group().replace(",", "")) if n else None
    return (size if size and size >= 50 else None), (pop.group(1) if pop else "")


def _pct(text) -> float | None:
    t = _clean(text)
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", t) or re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", t)
    return float(m.group(1)) if m else None


def _flat(col) -> str:
    if isinstance(col, tuple):
        parts = [str(c) for c in col if not str(c).startswith("Unnamed")]
        col = " ".join(dict.fromkeys(parts))
    return _clean(col)


def parse_polls(html: str, dem: str, rep: str, year: int) -> pd.DataFrame:
    """Every head-to-head row between `dem` and `rep` in the article's poll tables."""
    import lxml.html as LH
    root = LH.fromstring(html)
    section, rows, table_i = "", [], 0
    for el in root.iter("h2", "table"):
        if el.tag == "h2":
            section = el.text_content().strip()
            continue
        if "wikitable" not in (el.get("class") or ""):
            continue
        table_i += 1
        if PRIMARY_SECTION.search(section):
            continue
        try:
            t = pd.read_html(StringIO(LH.tostring(el, encoding="unicode")), thousands=None)[0]
        except ValueError:
            continue
        cols = [_flat(c) for c in t.columns]
        t.columns = range(len(cols))
        lc = [c.lower() for c in cols]
        src = next((i for i, c in enumerate(lc) if "poll source" in c or c == "source" or "pollster" in c), None)
        date = next((i for i, c in enumerate(lc) if "date" in c), None)
        size = next((i for i, c in enumerate(lc) if "sample" in c), None)
        if src is None or date is None or "aggregat" in lc[src] or "updated" in lc[date]:
            continue
        d_col, r_col = _match(cols, dem), _match(cols, rep)
        if d_col is None or r_col is None or d_col == r_col:
            continue
        di, ri = cols.index(d_col), cols.index(r_col)
        for _, r in t.iterrows():
            pollster = _clean(r[src])
            if not pollster or AGGREGATORS.search(pollster) or pollster.lower() == cols[src].lower():
                continue
            start, end = parse_dates(r[date], year)
            d, rp = _pct(r[di]), _pct(r[ri])
            if end is None or d is None or rp is None or d + rp <= 0:
                continue
            n, pop = _sample(r[size]) if size is not None else (None, "")
            rows.append({"pollster": pollster, "start": start, "end": end, "n": n, "population": pop,
                         "dem_pct": d, "rep_pct": rp, "table": table_i, "section": section})
    out = pd.DataFrame(rows, columns=["pollster", "start", "end", "n", "population", "dem_pct", "rep_pct",
                                      "table", "section"])
    return out.drop_duplicates(["pollster", "end", "n", "population", "dem_pct", "rep_pct"]).reset_index(drop=True)


def pollster_key(name: str) -> str:
    """'Public Policy Polling (D-End Citizens United)' -> 'public policy polling'."""
    return _norm(re.sub(r"\([^)]*\)", "", _clean(name))).strip(" .,")


# --------------------------------------------------------------------------- collection
def _races() -> pd.DataFrame:
    r = pd.read_parquet(OUT / "races.parquet")
    from .races import STATES
    names = {v: k for k, v in STATES.items()}
    r = r[r["d_side"].ne("not_two_party") & r["dem_candidate"].notna() & r["rep_candidate"].notna()]
    r = r[~r["race_id"].isin(ALL_PARTY_FIRST_ROUND)]
    r = r[~r["rep_candidate"].str.startswith("Several")]
    return r.assign(state=r["state_po"].map(names)).reset_index(drop=True)


def collect(years=(2018, 2022, 2026), refresh: bool = False, as_of: bool = False) -> pd.DataFrame:
    """All head-to-head poll rows for every modelled race (as_of: the 1 October revisions)."""
    out = []
    for _, r in _races()[lambda d: d["year"].isin(years)].iterrows():
        when = REVISION_AS_OF.get(int(r["year"])) if as_of else None
        if as_of and when is None:
            continue
        html = article(r["race_id"], title(r["year"], r["office"], r["special"], r["state"]), refresh, when)
        if html is None:
            print(f"{r['race_id']}: no article", flush=True)
            continue
        p = parse_polls(html, r["dem_candidate"], r["rep_candidate"], int(r["year"]))
        out.append(p.assign(race_id=r["race_id"], year=int(r["year"])))
    out = pd.concat(out, ignore_index=True)
    return out.assign(start=pd.to_datetime(out["start"]), end=pd.to_datetime(out["end"]),
                      n=pd.to_numeric(out["n"]), dem_pct=out["dem_pct"].astype(float),
                      rep_pct=out["rep_pct"].astype(float))


def qualifying(polls: pd.DataFrame, cutoff: str | pd.Timestamp, window: int = WINDOW_DAYS) -> pd.DataFrame:
    """Polls whose fieldwork ended on or before the cut-off and within `window` days of it."""
    c = pd.Timestamp(cutoff)
    return polls[(polls["end"] <= c) & (polls["end"] > c - pd.Timedelta(days=window))]


def one_per_pollster(polls: pd.DataFrame) -> pd.DataFrame:
    """Each pollster's latest poll, likely-voter version first, then the first table listed."""
    p = polls.assign(_key=polls["pollster"].map(pollster_key),
                     _pop=polls["population"].map(POP_ORDER).fillna(1), _row=np.arange(len(polls)))
    p = p.sort_values(["_key", "end", "_pop", "table", "_row"], ascending=[True, False, True, True, True])
    return p.drop_duplicates("_key").drop(columns=["_key", "_pop", "_row"])


def weights(polls: pd.DataFrame, cutoff) -> pd.Series:
    age = (pd.Timestamp(cutoff) - polls["end"]).dt.days.clip(lower=0)
    n = polls["n"].fillna(SAMPLE_DEFAULT).clip(upper=SAMPLE_CAP)
    pop = polls["population"].map(POP_WEIGHT).fillna(1.0)
    return 0.5 ** (age / HALF_LIFE_DAYS) * np.sqrt(n / SAMPLE_REF) * pop


def average(polls: pd.DataFrame, cutoff) -> dict:
    """Weighted Democratic-side two-party share for one race's qualifying polls."""
    p = one_per_pollster(qualifying(polls, cutoff))
    if p.empty:
        return {"poll_avg": np.nan, "n_polls": 0, "n_eff": 0.0, "last_poll": pd.NaT}
    w = weights(p, cutoff)
    share = p["dem_pct"] / (p["dem_pct"] + p["rep_pct"])
    return {"poll_avg": float((w * share).sum() / w.sum()), "n_polls": len(p),
            "n_eff": float(w.sum() ** 2 / (w ** 2).sum()), "last_poll": p["end"].max()}


def cutoff(year: int) -> str:
    return CUTOFF.get(year) or dt.date.today().isoformat()


def load(year: int) -> pd.DataFrame:
    p = pd.read_parquet(OUT / "polls.parquet")
    return p[p["year"] == year]


def averages(year: int, polls: pd.DataFrame | None = None, when: str | None = None) -> pd.DataFrame:
    polls = load(year) if polls is None else polls[polls["year"] == year]
    when = when or cutoff(year)
    rows = [{"race_id": rid, **average(g, when)} for rid, g in polls.groupby("race_id")]
    return pd.DataFrame(rows, columns=["race_id", "poll_avg", "n_polls", "n_eff", "last_poll"])


# --------------------------------------------------------------------------- error model
def _training(years: list[int]) -> pd.DataFrame:
    from . import vote_model
    out = []
    for y in years:
        f = vote_model.frame(y)[["race_id", "actual", "independent"]]
        a = f.merge(averages(y), on="race_id")
        a = a[a["actual"].notna() & ~a["independent"] & (a["n_polls"] > 0)]
        out.append(a.assign(year=y, err=logit(a["actual"]) - logit(a["poll_avg"])))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def fit_errors(train_years: list[int], draws: int = 1000) -> dict:
    """Draws of (s_nat, s_floor, s_poll): posterior on earlier years, or the priors alone."""
    import pymc as pm
    import pytensor.tensor as pt
    with pm.Model():
        s = {k: pm.LogNormal(k, np.log(v), PRIOR_LOG_SD) for k, v in PRIOR.items()}
        t = _training(train_years) if train_years else pd.DataFrame()
        if len(t):
            for y, g in t.groupby("year"):
                m = len(g)
                cov = (s["s_nat"] ** 2 * pt.ones((m, m))
                       + pt.diag(s["s_floor"] ** 2 + s["s_poll"] ** 2 / g["n_eff"].to_numpy()))
                pm.MvNormal(f"err_{y}", mu=np.zeros(m), cov=cov, observed=g["err"].to_numpy())
            idata = pm.sample(draws, tune=1000, chains=4, target_accept=0.95, random_seed=SEED, progressbar=False)
            post = idata.posterior
        else:
            post = pm.sample_prior_predictive(draws * 4, random_seed=SEED).prior
    post = post.to_dataset() if hasattr(post, "to_dataset") else post
    post = post.stack(s=("chain", "draw"))
    out = {k: np.asarray(post[k].values) for k in PRIOR}
    out["n_train"] = len(t)
    out["national_miss"] = t.groupby("year")["err"].mean().to_dict() if len(t) else {}
    return out


# --------------------------------------------------------------------------- blend
def blend(f: pd.DataFrame, sims: np.ndarray, year: int, train_years: list[int],
          errors: dict | None = None, avgs: pd.DataFrame | None = None,
          rng: np.random.Generator | None = None) -> tuple[np.ndarray, pd.DataFrame]:
    """Fundamentals draws (sims x races) moved towards each race's poll average.

    Returns the blended draws and a table of the poll average, n_eff and weight per race."""
    rng = rng or np.random.default_rng(SEED + year + 1)
    errors = errors or fit_errors(train_years)
    avgs = averages(year) if avgs is None else avgs
    a = f[["race_id"]].merge(avgs, on="race_id", how="left")
    has = a["n_polls"].fillna(0).to_numpy() > 0
    x = logit(np.clip(sims.astype(np.float64), 1e-6, 1 - 1e-6))
    n_sims = len(x)
    k = rng.integers(0, len(errors["s_nat"]), n_sims)
    v_f = x.var(axis=0)
    n_eff = a["n_eff"].fillna(1.0).clip(lower=1e-9).to_numpy()
    race_var = np.mean(errors["s_floor"] ** 2)[None] + np.mean(errors["s_poll"] ** 2) / n_eff
    v_p = np.mean(errors["s_nat"] ** 2) + race_var
    w = np.where(has, v_f / (v_f + v_p), 0.0)
    nat = errors["s_nat"][k] * rng.standard_normal(n_sims)
    race_sd = np.sqrt(errors["s_floor"][k, None] ** 2 + errors["s_poll"][k, None] ** 2 / n_eff[None, :])
    obs = logit(np.clip(a["poll_avg"].fillna(0.5).to_numpy(), 1e-6, 1 - 1e-6))[None, :] - nat[:, None] \
        - race_sd * rng.standard_normal((n_sims, len(f)))
    out = expit(x + w[None, :] * (obs - x)).astype(np.float32)
    info = a.assign(poll_weight=w, fundamentals_median=np.median(sims, axis=0),
                    blended_median=np.median(out, axis=0))
    return out, info


# --------------------------------------------------------------------------- checks and main
def revision_check(polls_now: pd.DataFrame, polls_then: pd.DataFrame) -> pd.DataFrame:
    """Qualifying polls per year in today's articles against the 1 October revisions."""
    rows = []
    for y in CUTOFF:
        now = qualifying(polls_now[polls_now["year"] == y], CUTOFF[y])
        then = qualifying(polls_then[polls_then["year"] == y], CUTOFF[y])
        k = ["race_id", "end", "dem_pct", "rep_pct"]
        late = now.merge(then[k].drop_duplicates(), on=k, how="left", indicator=True)
        rows.append({"year": y, "polls_now": len(now), "polls_1_october": len(then),
                     "in_now_not_then": int((late["_merge"] == "left_only").sum()),
                     "races_now": now["race_id"].nunique(), "races_1_october": then["race_id"].nunique()})
    return pd.DataFrame(rows)


def coverage(year: int, polls: pd.DataFrame | None = None) -> dict:
    from . import vote_model
    f = vote_model.frame(year)
    a = f[["race_id"]].merge(averages(year, polls), on="race_id", how="left")
    n = a["n_polls"].fillna(0)
    return {"year": year, "races": len(f), "races_with_polls": int((n > 0).sum()),
            "polls_used": int(n.sum()), "median_polls_where_any": float(n[n > 0].median()) if (n > 0).any() else 0.0,
            "mean_n_eff_where_any": float(a.loc[n > 0, "n_eff"].mean()) if (n > 0).any() else 0.0}


def main(refresh: bool | None = None) -> None:
    if refresh is None:
        refresh = "--refresh" in sys.argv
    polls = collect(refresh=refresh)
    polls.to_parquet(OUT / "polls.parquet", index=False)
    if "--no-revisions" not in sys.argv:
        then = collect(years=(2018, 2022), as_of=True)
        then.to_parquet(OUT / "polls_1_october.parquet", index=False)
        check = revision_check(polls, then)
        check.to_csv(OUT / "polls_revision_check.csv", index=False)
        print(check.to_string(index=False))
    cov = pd.DataFrame([coverage(y, polls) for y in (2018, 2022, 2026)])
    cov.to_csv(OUT / "polls_coverage.csv", index=False)
    print(cov.to_string(index=False))
    pd.concat([averages(y, polls).assign(year=y) for y in (2018, 2022, 2026)]).to_csv(
        OUT / "poll_averages.csv", index=False)


if __name__ == "__main__":
    main()

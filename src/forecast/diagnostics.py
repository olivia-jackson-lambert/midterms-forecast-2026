"""Election diagnostics for forecast v1 (issue #24). DIAGNOSTIC ONLY.

    python -m forecast.diagnostics [--fetch-late] [--pull PULL_ID]

Why v1 missed, tested hypothesis by hypothesis. Nothing here changes v1 or its score: v1 is
`forecasts/v1/` at tag `v1` and is only read. Every rerun below is v1's own code, with v1's
inputs and seeds, changed in one named place; its tables go to data/processed/diagnostics_v1/
(local, never committed) and are scored with forecast.score's own functions, so that a rerun
and v1 are measured in exactly the same way. The reruns are labelled DIAGNOSTIC throughout and
are never part of the score in #15.

Writes results/diagnostics.json (headline numbers) and results/diagnostics.md (the write-up).

Reproduction. The three models are refitted with the tagged code (src/ is unchanged since `v1`
for every model module) and the same seeds; the rerun is checked against forecasts/v1 before
anything else is computed, and the script stops if it does not match.

The hypotheses (issue #24):
- H1 national correction: the generic-ballot bias (-1.75 points) set to 0 (spread kept), and the
  raw generic ballot used as the national House vote with no correction and no spread.
- H2 shared polling miss: race-poll error (actual minus poll_avg) by race, and its relation to
  poll count, fieldwork date and pollster mix.
- H3 blend weight: polls alone against v1's blend, by number of polls.
- H4 interval width: the simulated national error against the realised shift.
- H5 turnout: waits for near-final counts.
- H6 late swing: race poll averages as of 3 November (Wikipedia revisions) against v1's.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import pickle
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import expit, logit

from . import generic_ballot, house, polls, release, score, vote_model
from .ingest import OUT, RAW
from .results import LOG, RESULTS, V1

YEAR = 2026
TRAIN = [2018, 2022]
V1_CUTOFF = "2026-10-22"                 # v1's run date, the poll cut-off it used (manifest: polls to 21 Oct)
LATE_AS_OF = "2026-11-03T12:00:00Z"      # Wikipedia revisions as of 7am ET on election day
LATE_CUTOFF = "2026-11-03"
DIAG = OUT / "diagnostics_v1"
RAW_LATE = RAW / "polls_late_2026"
HOUSE_PAGE_TITLE = "2026 United States House of Representatives elections"
MIN_COUNTED = score.MIN_COUNTED
Z80 = stats.norm.ppf(0.9)
PARTISAN = re.compile(r"\((?:[^)]*[\s/-])?(R|D)(?:\b|-)")      # Wikipedia's sponsor labels, e.g. 'Cygnal (R)'


# --------------------------------------------------------------------------- small pure helpers
def poll_bucket(n) -> str:
    n = 0 if pd.isna(n) else int(n)
    return "0" if n == 0 else "1-4" if n <= 4 else "5+"


def partisan_label(pollster: str) -> str:
    """'R' or 'D' where Wikipedia marks the pollster or its sponsor as partisan, else ''."""
    m = PARTISAN.search(str(pollster))
    return m.group(1) if m else ""


def sd_for_percentile(realised: float, dev: np.ndarray, q: float = 0.9) -> dict:
    """How wide the simulated deviations would have to be for `realised` to sit at quantile q.

    dev: simulated deviations from the median (one per simulation). The deviations are scaled
    by k = realised / quantile(dev, q); the implied SD is k * sd(dev). Also the realised value's
    percentile in the simulations as they are."""
    dev = np.asarray(dev, float)
    qv = float(np.quantile(dev, q))
    k = realised / qv
    return {"sd_simulated": float(dev.std()), "q_simulated": qv, "percentile_realised": float((dev < realised).mean()),
            "scale_needed": float(k), "sd_needed": float(k * dev.std())}


def polls_only(avg, n_eff, errors: dict) -> pd.DataFrame:
    """A polls-alone forecast with v1's own poll-error model: on the logit scale the result is
    Normal(logit(avg), s_nat^2 + s_floor^2 + s_poll^2 / n_eff), with v1's posterior mean variances."""
    avg, n_eff = np.asarray(avg, float), np.clip(np.asarray(n_eff, float), 1e-9, None)
    sd = np.sqrt(np.mean(errors["s_nat"] ** 2) + np.mean(errors["s_floor"] ** 2)
                 + np.mean(errors["s_poll"] ** 2) / n_eff)
    m = logit(avg)
    return pd.DataFrame({"median": expit(m), "lo80": expit(m - Z80 * sd), "hi80": expit(m + Z80 * sd),
                         "p_dem_win": stats.norm.cdf(m / sd), "sd_logit": sd})


@contextlib.contextmanager
def national_override(bias: float | None = None, sd: float | None = None, gb: float | None = None):
    """Temporarily replace generic_ballot.national_environment's bias, spread and/or the generic
    ballot itself (`gb`, two-party, e.g. its value on an earlier date) (DIAGNOSTIC).

    Both vote models look the function up on the module when they simulate, so the change
    reaches them and nothing else; the random draws are unchanged. The centre is always
    generic ballot + bias, as in v1."""
    orig = generic_ballot.national_environment

    def patched(year, hist=None):
        e = dict(orig(year, hist))
        if gb is not None:
            e["gb_dem_2p"] = gb
        if bias is not None:
            e["bias"] = bias
        if gb is not None or bias is not None:
            e["mean"] = e["gb_dem_2p"] + e["bias"]
        if sd is not None:
            e["sd"] = sd
        return e
    generic_ballot.national_environment = patched
    try:
        yield
    finally:
        generic_ballot.national_environment = orig


# --------------------------------------------------------------------------- late polls (H6)
def _revision_html(folder: Path, stem: str, page: str, as_of: str) -> tuple[str | None, int | None]:
    """The article as it stood at `as_of`, cached as <stem>_asof<date>_rev<id>.html in `folder`.
    A revision already saved for another date is reused rather than fetched again."""
    hits = sorted(folder.glob(f"{stem}_asof{as_of[:10]}_rev*.html"))
    if hits:
        return hits[-1].read_text(), int(hits[-1].stem.split("_rev")[-1])
    rev = polls.revision_as_of(page, as_of)
    if rev is None:
        return None, None
    same = sorted(folder.glob(f"{stem}_asof*_rev{rev}.html"))
    html = same[0].read_text() if same else polls._api({"action": "parse", "oldid": rev, "prop": "text"})["parse"]["text"]
    (folder / f"{stem}_asof{as_of[:10]}_rev{rev}.html").write_text(html)
    return html, rev


def fetch_late(as_of: str = LATE_AS_OF, folder: Path = RAW_LATE) -> pd.DataFrame:
    """Every 2026 race article as it stood at `as_of` (Wikipedia revision), parsed with v1's
    parser. Saved under data/raw/polls_late_2026/ (or `folder`), apart from v1's own poll files."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for _, r in polls._races()[lambda d: d["year"] == YEAR].iterrows():
        page = polls.title(YEAR, r["office"], r["special"], r["state"])
        html, _ = _revision_html(folder, r["race_id"], page, as_of)
        if html is None:
            print(f"{r['race_id']}: no revision at {as_of}", flush=True)
            continue
        p = polls.parse_polls(html, r["dem_candidate"], r["rep_candidate"], YEAR)
        out.append(p.assign(race_id=r["race_id"], year=YEAR))
    out = pd.concat(out, ignore_index=True)
    out = out.assign(start=pd.to_datetime(out["start"]), end=pd.to_datetime(out["end"]),
                     n=pd.to_numeric(out["n"]), dem_pct=out["dem_pct"].astype(float),
                     rep_pct=out["rep_pct"].astype(float))
    out.to_parquet(folder / f"polls_asof{as_of[:10]}.parquet", index=False)
    return out


def generic_ballot_late(as_of: str = LATE_AS_OF, folder: Path = RAW_LATE) -> dict | None:
    """The aggregators' generic ballot on Wikipedia's 2026 House page as it stood at `as_of`."""
    folder.mkdir(parents=True, exist_ok=True)
    html, rev = _revision_html(folder, "house_2026", HOUSE_PAGE_TITLE, as_of)
    if html is None:
        return None
    a = generic_ballot._aggregate_table(html)
    return {"as_of": as_of, "revision": rev, "sources": list(a["source"]), "updated": list(a["updated"]),
            "dem": float(a["dem"].mean()), "rep": float(a["rep"].mean()),
            "gb_dem_2p": float(a["dem"].mean() / (a["dem"].mean() + a["rep"].mean()))}


def load_late(as_of: str = LATE_AS_OF, folder: Path = RAW_LATE) -> pd.DataFrame | None:
    path = folder / f"polls_asof{as_of[:10]}.parquet"
    return pd.read_parquet(path) if path.exists() else None


# --------------------------------------------------------------------------- reruns
def fitted(refit: bool = False) -> dict:
    """v1's three fits (Stage B, poll errors, House), refitted with the tagged code and seeds and
    cached locally. The fits do not use the national environment, so every variant shares them."""
    DIAG.mkdir(parents=True, exist_ok=True)
    path = DIAG / "fits.pkl"
    if path.exists() and not refit:
        return pickle.loads(path.read_bytes())
    fits = {"vote": vote_model.fit([vote_model.frame(y) for y in TRAIN]),
            "polls": polls.fit_errors(TRAIN),
            "house": house.fit([house.frame(y) for y in TRAIN])}
    path.write_bytes(pickle.dumps(fits))
    return fits


def rerun(fits: dict, avgs: pd.DataFrame, bias: float | None = None, sd: float | None = None,
          gb: float | None = None) -> dict:
    """v1's Stage B (with the poll blend) and House simulations, as vote_model.run and house.run
    do them, with the same seeds; optionally with the national environment changed."""
    with national_override(bias, sd, gb):
        f = vote_model.frame(YEAR)
        s = vote_model.simulate(f, fits["vote"], YEAR)
        fund = vote_model.summarise(f, s)
        b, info = polls.blend(f, s, YEAR, TRAIN, errors=fits["polls"], avgs=avgs)
        out = vote_model.summarise(f, b)
        out["fundamentals_median"] = fund["median"].values
        out["fundamentals_p_dem_win"] = fund["p_dem_win"].values
        hf = house.frame(YEAR)
        hs = house.simulate(hf, fits["house"], YEAR)
        ho = house.summarise(hf, hs)
        env = generic_ballot.national_environment(YEAR)
    return {"races": out, "race_sims": b, "race_frame": f, "blend": info, "house": ho, "house_sims": hs,
            "house_frame": hf, "env": env}


def write_tables(run: dict, name: str, avgs: pd.DataFrame, base: Path = DIAG,
                 note: str = "Diagnostic rerun for issue #24.") -> Path:
    """The rerun's races.csv and house_districts.csv in v1's published format (release's own
    functions and rounding), in data/processed/diagnostics_v1/<name>/ (or `base`/<name>/).
    DIAGNOSTIC, not a release."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    run["races"].to_parquet(d / "vote_share_2026.parquet", index=False)
    run["house"].to_parquet(d / "house_2026.parquet", index=False)
    avgs.assign(year=YEAR).to_csv(d / "poll_averages.csv", index=False)
    orig = release.OUT
    release.OUT = d
    try:
        release.races().to_csv(d / "races.csv", index=False)
        release.house_districts().to_csv(d / "house_districts.csv", index=False)
    finally:
        release.OUT = orig
    (d / "DIAGNOSTIC.txt").write_text(f"{note} Not forecast v1 and not part of its score.\n")
    return d


def reproduction_gap(d: Path) -> float:
    """Largest absolute difference between a rerun's tables and forecasts/v1 (0 when exact)."""
    gap = 0.0
    for name, key in (("races.csv", "race_id"), ("house_districts.csv", "cd")):
        a, b = pd.read_csv(V1 / name).set_index(key), pd.read_csv(d / name).set_index(key)
        num = [c for c in a.columns if pd.api.types.is_float_dtype(a[c])]
        diff = (a[num] - b.loc[a.index, num]).abs().max().max()
        gap = max(gap, float(0 if pd.isna(diff) else diff))
    return gap


# --------------------------------------------------------------------------- scoring
GROUPS = ("senate", "governor", "house", "all")


def results(pull: str | None = None) -> pd.DataFrame:
    log = pd.read_csv(LOG, dtype={"winner_party": "string"})
    return log[log["pull_id"] == (pull or log["pull_id"].max())]


def metrics(res: pd.DataFrame, forecast_dir: Path = V1) -> dict:
    """forecast.score's race and vote-share measures for a folder of v1-format tables."""
    f = score.frame(res, forecast_dir)
    f = f.assign(lean=score.lean_baseline(f))
    groups = {"all": f[f["group"] != "independent"], "senate": f[f["group"] == "senate"],
              "governor": f[f["group"] == "governor"], "house": f[f["group"] == "house"]}
    out = {}
    for k in GROUPS:
        g, v = score.score_group(groups[k]), score.vote_group(groups[k])
        out[k] = {"called": g["called"], "upsets": g["upsets"], "expected_upsets": g["expected_upsets"],
                  "brier": g["brier"], "log_loss": g["log_loss"], "vote_n": v["n"],
                  "mean_error": v["mean_error_toward_dem"], "mae": v["mae"], "rmse": v["rmse"],
                  "coverage_80": v["coverage_80"], "below_80": v["below_80"], "above_80": v["above_80"]}
    return out


def scored_frame(res: pd.DataFrame) -> pd.DataFrame:
    """v1's rows with results, and whether each counts for the vote-share measures."""
    f = score.frame(res)
    f["vote_ok"] = (f["called"] & f["vote_scored"] & f["dem_share_2p"].notna() & f["median"].notna()
                    & (f["pct_counted"] >= MIN_COUNTED))
    return f


# --------------------------------------------------------------------------- H2 and H3: polls
def poll_detail(poll_rows: pd.DataFrame, cutoff: str) -> pd.DataFrame:
    """The polls behind each race's average (v1's rules: qualifying, one per pollster), with weight,
    two-party share, age and labels."""
    out = []
    for rid, g in poll_rows[poll_rows["year"] == YEAR].groupby("race_id"):
        p = polls.one_per_pollster(polls.qualifying(g, cutoff))
        if p.empty:
            continue
        out.append(p.assign(race_id=rid, w=polls.weights(p, cutoff).values,
                            share=(p["dem_pct"] / (p["dem_pct"] + p["rep_pct"])).values,
                            age=(pd.Timestamp(cutoff) - p["end"]).dt.days.values,
                            partisan=p["pollster"].map(partisan_label).values,
                            key=p["pollster"].map(polls.pollster_key).values))
    return pd.concat(out, ignore_index=True)


def race_poll_features(detail: pd.DataFrame) -> pd.DataFrame:
    def one(g):
        w = g["w"] / g["w"].sum()
        return pd.Series({"n_polls": len(g), "n_eff": g["w"].sum() ** 2 / (g["w"] ** 2).sum(),
                          "mean_age_days": float((w * g["age"]).sum()), "newest_age_days": float(g["age"].min()),
                          "share_partisan_r": float(w[g["partisan"] == "R"].sum()),
                          "share_partisan_d": float(w[g["partisan"] == "D"].sum()),
                          "share_lv": float(w[g["population"].isin(["LV", "V", ""])].sum())})
    return detail.groupby("race_id").apply(one, include_groups=False).reset_index()


def _corr(x, y) -> dict:
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 5 or np.std(x[ok]) == 0:
        return {"n": int(ok.sum()), "pearson_r": None, "pearson_p": None, "spearman_rho": None, "spearman_p": None}
    pr, sr = stats.pearsonr(x[ok], y[ok]), stats.spearmanr(x[ok], y[ok])
    return {"n": int(ok.sum()), "pearson_r": round(float(pr[0]), 3), "pearson_p": round(float(pr[1]), 3),
            "spearman_rho": round(float(sr[0]), 3), "spearman_p": round(float(sr[1]), 3)}


def _err_summary(e) -> dict:
    e = np.asarray(e, float)
    e = e[np.isfinite(e)]
    if not len(e):
        return {"n": 0, "mean": None, "sd": None, "mae": None, "rmse": None}
    return {"n": int(len(e)), "mean": round(float(e.mean()), 2), "sd": round(float(e.std(ddof=1)), 2) if len(e) > 1 else None,
            "mae": round(float(np.abs(e).mean()), 2), "rmse": round(float(np.sqrt((e ** 2).mean())), 2)}


def h2(sf: pd.DataFrame, detail: pd.DataFrame, errors: dict) -> dict:
    """Race-poll error, actual minus poll_avg, over scored Senate and governor races with polls."""
    v1 = pd.read_csv(V1 / "races.csv")[["race_id", "poll_avg", "n_polls"]]
    r = sf[sf["office"].ne("house") & sf["vote_ok"]].merge(v1, left_on="id", right_on="race_id")
    r = r[r["n_polls"] > 0].merge(race_poll_features(detail), on="race_id", suffixes=("", "_d"))
    r["err"] = 100 * (r["dem_share_2p"] - r["poll_avg"])
    r["err_logit"] = logit(r["dem_share_2p"]) - logit(r["poll_avg"])
    # What v1's poll-error model expected: a shared miss with sd s_nat, and race error around it.
    s_nat = float(np.sqrt(np.mean(errors["s_nat"] ** 2)))
    race_sd = np.sqrt(np.mean(errors["s_floor"] ** 2) + np.mean(errors["s_poll"] ** 2) / r["n_eff"])
    resid = r["err_logit"] - r["err_logit"].mean()
    out = {"races": _err_summary(r["err"]),
           "by_office": {o: _err_summary(r.loc[r["office"] == o, "err"]) for o in ("senate", "governor")},
           "share_positive": round(float((r["err"] > 0).mean()), 3),
           "model": {"s_nat_logit": round(s_nat, 4), "mean_error_logit": round(float(r["err_logit"].mean()), 4),
                     "mean_error_in_s_nat": round(float(r["err_logit"].mean() / s_nat), 2),
                     "race_sd_expected_logit": round(float(np.sqrt(np.mean(race_sd ** 2))), 4),
                     "race_sd_realised_logit": round(float(resid.std(ddof=1)), 4)},
           "correlations": {k: _corr(r[k], r["err"]) for k in
                            ("n_polls", "n_eff", "mean_age_days", "newest_age_days", "share_partisan_r",
                             "share_partisan_d", "share_lv")},
           "by_bucket": {b: _err_summary(r.loc[r["n_polls"].map(poll_bucket) == b, "err"]) for b in ("1-4", "5+")},
           "largest": [{"id": x.race_id, "err": round(float(x.err), 2), "n_polls": int(x.n_polls)}
                       for x in r.reindex(r["err"].abs().sort_values(ascending=False).index).head(6).itertuples()]}
    # Poll level: each poll in an average against its race's result.
    p = detail.merge(r[["race_id", "dem_share_2p"]], on="race_id")
    p["err"] = 100 * (p["dem_share_2p"] - p["share"])
    p["age_band"] = pd.cut(p["age"], [-1, 14, 28, 56, 90], labels=["0-14", "15-28", "29-56", "57-90"])
    out["polls"] = {"all": _err_summary(p["err"]), "age_corr": _corr(p["age"], p["err"]),
                    "by_age_days": {str(b): _err_summary(g["err"]) for b, g in p.groupby("age_band", observed=False)},
                    "by_label": {({"R": "Republican-labelled", "D": "Democratic-labelled"}.get(k, "unlabelled")):
                                 _err_summary(g["err"]) for k, g in p.groupby("partisan")},
                    "by_population": {(k or "unspecified"): _err_summary(g["err"]) for k, g in p.groupby("population")}}
    multi = p.groupby("key").filter(lambda g: g["race_id"].nunique() >= 3)
    out["polls"]["pollsters_3plus_races"] = sorted(
        [{"pollster": k, "races": int(g["race_id"].nunique()), "mean_err": round(float(g["err"].mean()), 2)}
         for k, g in multi.groupby("key")], key=lambda d: -d["races"])
    out["_rows"] = r
    return out


def h3(sf: pd.DataFrame, run_v1: dict, errors: dict) -> dict:
    """Polls alone (v1's own poll-error model) against v1's blend and the fundamentals."""
    v1 = pd.read_csv(V1 / "races.csv")
    b = run_v1["blend"][["race_id", "n_eff", "poll_weight"]]
    v1 = v1.merge(b, on="race_id", how="left")
    po = polls_only(v1["poll_avg"].fillna(0.5), v1["n_eff"].fillna(1.0), errors)
    has = v1["n_polls"] > 0
    for c in po.columns:
        v1[f"po_{c}"] = po[c].where(has)
    v1["bucket"] = v1["n_polls"].map(poll_bucket)
    r = sf[sf["office"].ne("house") & sf["group"].ne("independent")].merge(v1, left_on="id", right_on="race_id")
    called = r[r["called"] & r["outcome"].notna()]
    vote = r[r["vote_ok"]]
    out = {}
    sets = [("all", called, vote), ("polled", called[called["n_polls"] > 0], vote[vote["n_polls"] > 0])]
    sets += [(k, called[called["bucket"] == k], vote[vote["bucket"] == k]) for k in ("0", "1-4", "5+")]
    for name, g_c, g_v in sets:
        row = {"called": int(len(g_c)), "vote_n": int(len(g_v)),
               "mean_poll_weight": round(float(g_c["poll_weight"].mean()), 3) if len(g_c) else None}
        for src, med, lo, hi, p in (("blend", "dem_share_median", "dem_share_lo80", "dem_share_hi80", "p_dem_win"),
                                    ("fundamentals", "fundamentals_median", None, None, "fundamentals_p_dem_win"),
                                    ("polls_only", "po_median", "po_lo80", "po_hi80", "po_p_dem_win")):
            gc, gv = g_c[g_c[p].notna()], g_v[g_v[med].notna()]
            e = 100 * (gv["dem_share_2p"] - gv[med])
            row[src] = {"called": int(len(gc)), "brier": score._r(score.brier(gc[p], gc["y"])),
                        "vote_n": int(len(gv)), "mean_error": score._r(e.mean(), 2) if len(gv) else None,
                        "mae": score._r(e.abs().mean(), 2) if len(gv) else None,
                        "coverage_80": (score._r(((gv["dem_share_2p"] >= gv[lo]) & (gv["dem_share_2p"] <= gv[hi])).mean())
                                        if lo and len(gv) else None)}
        out[name] = row
    few = called[(called["bucket"] == "1-4") & called["po_p_dem_win"].notna()
                 & ((called["p_dem_win"] > 0.5).astype(float) == called["y"])]          # the favourite won
    gap = (few["po_p_dem_win"] - few["y"]) ** 2 - (few["p_dem_win"] - few["y"]) ** 2
    out["few_polls_worse_for_polls_only"] = list(few.loc[gap.sort_values(ascending=False).index[gap.sort_values(ascending=False) > 0.05], "id"])
    # Descriptive only (not a refit): the weight on the poll average that would have minimised the
    # squared vote-share error over these races, actual - fund = w * (poll - fund).
    pv = vote[vote["n_polls"] > 0]
    x, y = (pv["poll_avg"] - pv["fundamentals_median"]).to_numpy(), (pv["dem_share_2p"] - pv["fundamentals_median"]).to_numpy()
    out["best_weight_in_hindsight"] = {"n": int(len(pv)), "w": round(float((x * y).sum() / (x * x).sum()), 3),
                                       "v1_mean_weight": round(float(pv["poll_weight"].mean()), 3)}
    return out


# --------------------------------------------------------------------------- H4: interval width
def h4(sf: pd.DataFrame, run_v1: dict) -> dict:
    env = run_v1["env"]
    tsd = env["sd"] * np.sqrt(env["df"] / (env["df"] - 2))
    out = {"national_environment": {"mean": round(env["mean"], 4), "scale": round(env["sd"], 4), "df": env["df"],
                                    "sd_points": round(100 * tsd, 2),
                                    "q90_points": round(100 * env["sd"] * stats.t.ppf(0.9, env["df"]), 2)}}
    for name, sims, frame, key, off in (("house", run_v1["house_sims"], run_v1["house"], "cd", "house"),
                                        ("senate_and_governor", run_v1["race_sims"], run_v1["races"], "race_id", None)):
        ok = sf[sf["vote_ok"] & (sf["office"].eq("house") if off else sf["office"].ne("house"))]
        idx = frame.reset_index(drop=True).reset_index().set_index(key).loc[ok["id"], "index"].to_numpy()
        med = np.median(sims[:, idx], axis=0)
        dev = 100 * (sims[:, idx] - med[None, :]).mean(axis=1)
        realised = float(100 * (ok["dem_share_2p"].to_numpy() - med).mean())
        out[name] = {"n": int(len(idx)), "realised_mean_shift_points": round(realised, 2),
                     **{k: round(v, 3) for k, v in sd_for_percentile(realised, dev).items()}}
    # The national term alone: the realised House shift on the logit scale, against v1's t.
    h = sf[sf["vote_ok"] & sf["office"].eq("house")]
    shift = float((logit(h["dem_share_2p"]) - logit(h["median"])).mean())
    m = env["mean"]
    need = shift / stats.t.ppf(0.9, env["df"])
    out["national_term"] = {"realised_logit_shift": round(shift, 4),
                            "realised_shift_points_at_mean": round(100 * shift * m * (1 - m), 2),
                            "percentile_in_v1_t": round(float(stats.t.cdf(shift / logit_scale(env), env["df"])), 4),
                            "scale_needed_points": round(100 * need * m * (1 - m), 2),
                            "sd_needed_points": round(100 * need * m * (1 - m) * np.sqrt(env["df"] / (env["df"] - 2)), 2),
                            "ratio_to_v1": round(float(need / logit_scale(env)), 2)}
    return out


def logit_scale(env: dict) -> float:
    """v1's national spread on the logit scale (its t is on the share scale; near the mean the
    two differ by the factor m(1-m))."""
    m = env["mean"]
    return env["sd"] / (m * (1 - m))


def house_vote_so_far(res: pd.DataFrame) -> dict:
    """The national House two-party vote in AP's counts so far: every district's Democratic and
    Republican votes (stand-ins included as v1 defines the sides). Incomplete and provisional."""
    h = res[res["office"] == "house"]
    d, r = h["dem_votes"].sum(), h["rep_votes"].sum()
    w = h["total_votes"].fillna(0)
    return {"dem_2p": round(float(d / (d + r)), 4), "districts_with_votes": int((w > 0).sum()),
            "vote_weighted_pct_counted": round(float((h["pct_counted"].fillna(0) * w).sum() / w.sum()), 3),
            "districts_below_95pct": int((h["pct_counted"].fillna(0) < 0.95).sum())}


# --------------------------------------------------------------------------- H6: late polls
def h6(sf: pd.DataFrame, late: pd.DataFrame) -> dict:
    """How far the race averages moved between v1's cut-off and election day, with v1's own
    averaging rule on the 3 November revisions of the same Wikipedia articles."""
    v1 = polls.averages(YEAR, when=V1_CUTOFF)
    same_day = polls.averages(YEAR, late, when=V1_CUTOFF)           # late-listed polls only
    final = polls.averages(YEAR, late, when=LATE_CUTOFF)
    a = (v1.add_suffix("_v1").rename(columns={"race_id_v1": "race_id"})
         .merge(same_day.add_suffix("_listed").rename(columns={"race_id_listed": "race_id"}), on="race_id", how="outer")
         .merge(final.add_suffix("_final").rename(columns={"race_id_final": "race_id"}), on="race_id", how="outer"))
    for c in ("n_polls_v1", "n_polls_listed", "n_polls_final"):
        a[c] = a[c].fillna(0).astype(int)
    both = a[(a["n_polls_v1"] > 0) & (a["n_polls_final"] > 0)]
    move = 100 * (both["poll_avg_final"] - both["poll_avg_v1"])
    listed = a[(a["n_polls_v1"] > 0) & (a["n_polls_listed"] > 0)]
    new_polls = polls.qualifying(late, LATE_CUTOFF)
    new_polls = new_polls[new_polls["end"] > pd.Timestamp(V1_CUTOFF)]
    r = sf[sf["office"].ne("house") & sf["vote_ok"]].merge(both, left_on="id", right_on="race_id")
    e_v1, e_final = 100 * (r["dem_share_2p"] - r["poll_avg_v1"]), 100 * (r["dem_share_2p"] - r["poll_avg_final"])
    return {"as_of": LATE_AS_OF, "cutoff": LATE_CUTOFF,
            "races_with_polls": {"v1": int((a["n_polls_v1"] > 0).sum()), "final": int((a["n_polls_final"] > 0).sum())},
            "polls_ending_after_v1_cutoff": int(len(new_polls)),
            "races_with_new_polls": int(new_polls["race_id"].nunique()),
            "movement_toward_dem": _err_summary(move),
            "share_moving_toward_dem": round(float((move > 0).mean()), 3) if len(move) else None,
            "late_listed_effect": _err_summary(100 * (listed["poll_avg_listed"] - listed["poll_avg_v1"])),
            "scored": {"n": int(len(r)), "error_v1_avg": _err_summary(e_v1), "error_final_avg": _err_summary(e_final),
                       "share_of_error_closed": (round(float(1 - e_final.mean() / e_v1.mean()), 3) if len(r) else None)},
            "_table": a, "_final": final}


# --------------------------------------------------------------------------- H7 and H8: poll adjustments
# Election days of the earlier cycles: their polls (all public long before 22 October 2026) enter
# the house-effect estimate if fieldwork ended within WINDOW_DAYS of election day.
HE_ELECTION_DAY = {2018: "2018-11-06", 2022: "2022-11-08"}


def he_key(name: str) -> str:
    """The pollster's name for house effects: v1's key (sponsors in brackets dropped), with a
    leading 'the', a trailing 'inc' and the spacing around '/' tidied ('The Trafalgar Group' and
    'Trafalgar Group' are one firm). Names are not harmonised further (see the write-up)."""
    k = polls.pollster_key(name)
    k = re.sub(r"^the\s+", "", k)
    k = re.sub(r",?\s+inc\.?$", "", k)
    return re.sub(r"\s*/\s*", "/", k).strip()


def display_name(name: str) -> str:
    """'Cygnal (R)' -> 'Cygnal': the pollster's name as Wikipedia gives it, without sponsor marks."""
    return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", "", polls._clean(name))).strip(" .,")


def house_effect_rows(poll_rows: pd.DataFrame, cutoff: str = V1_CUTOFF) -> pd.DataFrame:
    """The polls the house effects are estimated from: 2018 and 2022 polls ending in the 90 days
    up to election day, and 2026 polls ending in the 90 days up to v1's cut-off (never later)."""
    out = []
    for y, g in poll_rows.groupby("year"):
        when = HE_ELECTION_DAY.get(int(y)) or (cutoff if int(y) == YEAR else None)
        if when is None:
            continue
        out.append(polls.qualifying(g, when))
    p = pd.concat(out, ignore_index=True)
    assert not ((p["year"] == YEAR) & (p["end"] > pd.Timestamp(cutoff))).any(), "a 2026 poll after the cut-off"
    return p.assign(he_key=p["pollster"].map(he_key), share=p["dem_pct"] / (p["dem_pct"] + p["rep_pct"]))


def _ridge_fit(y, race, pol, n_p, lam, h=None, sweeps: int = 2000, tol: float = 1e-12):
    """Minimise sum (y - a_race - h_pollster)^2 + lam * sum h^2 by alternating exact updates.
    y, race, pol: one entry per pollster-race cell (race and pol as integer codes)."""
    h = np.zeros(len(n_p)) if h is None else h.copy()
    n_r = np.bincount(race)
    for _ in range(sweeps):
        a = np.bincount(race, y - h[pol]) / n_r
        h_new = np.bincount(pol, y - a[race], minlength=len(n_p)) / (n_p + lam)
        done = np.max(np.abs(h_new - h)) < tol
        h = h_new
        if done:
            break
    return a, h


def estimate_house_effects(rows: pd.DataFrame, max_iter: int = 500, tol: float = 1e-10) -> tuple[pd.DataFrame, dict]:
    """Each pollster's persistent lean relative to other pollsters in the same races (DIAGNOSTIC).

    rows: one per poll, with he_key, race_id and share (Democratic two-party share). Each
    pollster's polls in a race are first averaged, so that a pollster counts once per race. On
    those pollster-race cells
        share = race effect + house effect of the pollster + noise,
        house effects ~ Normal(0, tau^2), noise ~ Normal(0, sigma^2),
    with a free effect for each race. Only races polled by two or more pollsters carry
    information. tau^2 and sigma^2 are estimated from the data by EM; given them, the house effect
    is the usual shrunken (ridge, or random-effect) estimate,
        h = sum over the pollster's races of (share - race effect) / (races + sigma^2 / tau^2),
    so a pollster seen in few races is pulled toward 0. Only differences between pollsters are
    identified; the zero is the average pollster, each counted once (the effects sum to 0). Returns one row per pollster and the fitted variances (share scale)."""
    c = rows.groupby(["he_key", "race_id"]).agg(share=("share", "mean"), polls=("share", "size")).reset_index()
    multi = c.groupby("race_id")["he_key"].transform("nunique") >= 2
    c = c[multi].reset_index(drop=True)
    race = pd.factorize(c["race_id"])[0]
    pol, keys = pd.factorize(c["he_key"])
    y = c["share"].to_numpy(float)
    n_p = np.bincount(pol).astype(float)
    N, R = len(y), race.max() + 1
    a = np.bincount(race, y) / np.bincount(race)
    s2 = float(((y - a[race]) ** 2).sum() / max(N - R, 1))
    t2 = s2 / 4
    h = None
    for it in range(max_iter):
        lam = s2 / t2
        a, h = _ridge_fit(y, race, pol, n_p, lam, h)
        v = s2 / (n_p + lam)                                  # posterior variance of each effect
        t2_new = max(float(np.mean(h ** 2 + v)), 1e-10)
        e = y - a[race] - h[pol]
        s2_new = float(((e ** 2).sum() + (n_p * v).sum()) / max(N - R, 1))
        done = abs(t2_new - t2) < tol and abs(s2_new - s2) < tol
        t2, s2 = t2_new, s2_new
        if done:
            break
    lam = s2 / t2
    a, h = _ridge_fit(y, race, pol, n_p, lam, h)
    raw = np.bincount(pol, y - a[race]) / n_p
    pp = rows.groupby("he_key").agg(n_polls=("share", "size"),
                                    name=("pollster", lambda s: s.map(display_name).mode().iloc[0]),
                                    share_r=("pollster", lambda s: float((s.map(partisan_label) == "R").mean())),
                                    share_d=("pollster", lambda s: float((s.map(partisan_label) == "D").mean())),
                                    years=("year", lambda s: ",".join(map(str, sorted(set(s))))))
    eff = pd.DataFrame({"he_key": keys, "n_races": n_p.astype(int), "raw": raw, "shrink": n_p / (n_p + lam),
                        "effect": h}).merge(pp, on="he_key", how="left")
    params = {"sigma": float(np.sqrt(s2)), "tau": float(np.sqrt(t2)), "lambda": float(lam), "iterations": it + 1,
              "cells": int(N), "races": int(R), "pollsters": int(len(keys))}
    return eff.sort_values("effect", key=np.abs, ascending=False).reset_index(drop=True), params


def adjust_polls(poll_rows: pd.DataFrame, effects: pd.DataFrame, year: int = YEAR) -> pd.DataFrame:
    """The year's polls with each pollster's house effect removed from its two-party share. The
    two shares keep their sum, so v1's averaging (weights, one poll per pollster) is unchanged.
    Pollsters with no estimate (never in a race with another pollster) are left as they are."""
    p = poll_rows.copy()
    sel = p["year"] == year
    h = p.loc[sel, "pollster"].map(he_key).map(effects.set_index("he_key")["effect"]).fillna(0.0)
    tot = p.loc[sel, "dem_pct"] + p.loc[sel, "rep_pct"]
    share = p.loc[sel, "dem_pct"] / tot - h
    p.loc[sel, "dem_pct"] = share * tot
    p.loc[sel, "rep_pct"] = tot - share * tot
    return p.assign(house_effect=np.where(sel, h.reindex(p.index).fillna(0.0), 0.0))


def drop_partisan(poll_rows: pd.DataFrame) -> pd.DataFrame:
    """Every poll Wikipedia labels with a Democratic or Republican sponsor left out (H8)."""
    return poll_rows[poll_rows["pollster"].map(partisan_label) == ""]


def compare_averages(sf: pd.DataFrame, before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """How a change of poll average moved v1's averages, and their error on the scored races."""
    a = before.merge(after, on="race_id", how="outer", suffixes=("_v1", "_new"))
    for c in ("n_polls_v1", "n_polls_new"):
        a[c] = a[c].fillna(0).astype(int)
    both = a[(a["n_polls_v1"] > 0) & (a["n_polls_new"] > 0)]
    move = 100 * (both["poll_avg_new"] - both["poll_avg_v1"])
    r = sf[sf["office"].ne("house") & sf["vote_ok"]].merge(both, left_on="id", right_on="race_id")
    e_v1, e_new = 100 * (r["dem_share_2p"] - r["poll_avg_v1"]), 100 * (r["dem_share_2p"] - r["poll_avg_new"])
    lost = a[(a["n_polls_v1"] > 0) & (a["n_polls_new"] == 0)]
    return {"races_with_polls": {"v1": int((a["n_polls_v1"] > 0).sum()), "new": int((a["n_polls_new"] > 0).sum())},
            "polls_in_averages": {"v1": int(a["n_polls_v1"].sum()), "new": int(a["n_polls_new"].sum())},
            "movement_toward_dem": _err_summary(move),
            "scored": {"n": int(len(r)), "error_v1_avg": _err_summary(e_v1), "error_new_avg": _err_summary(e_new)},
            "races_losing_all_polls": sorted(lost["race_id"]), "_table": a}


def h7(sf: pd.DataFrame, poll_rows: pd.DataFrame, effects: pd.DataFrame, params: dict,
       avg_v1: pd.DataFrame, avg_h7: pd.DataFrame) -> dict:
    est = effects
    used = poll_detail(adjust_polls(poll_rows, effects), V1_CUTOFF)
    used = used.assign(h=used["pollster"].map(he_key).map(effects.set_index("he_key")["effect"]).fillna(0.0))
    wmean = float((used["w"] * used["h"]).sum() / used["w"].sum())
    lab = used.assign(label=used["partisan"].map({"R": "Republican-labelled", "D": "Democratic-labelled"}).fillna("unlabelled"))
    top = est[est["n_races"] >= 3].head(10)
    return {"method": {"years": [2018, 2022, 2026], "window_days": polls.WINDOW_DAYS,
                       "windows": {**HE_ELECTION_DAY, YEAR: V1_CUTOFF}, "scale": "two-party share, points",
                       "shrinkage": "random-effect (ridge) estimate, sigma and tau by EM"},
            "fit": {"sigma_points": round(100 * params["sigma"], 2), "tau_points": round(100 * params["tau"], 2),
                    "lambda_races": round(params["lambda"], 2), "cells": params["cells"], "races": params["races"],
                    "pollsters_estimated": params["pollsters"], "pollsters_3plus_races": int((est["n_races"] >= 3).sum()),
                    "iterations": params["iterations"]},
            "largest_3plus_races": [{"pollster": x.name, "races": int(x.n_races), "effect_points": round(100 * x.effect, 2),
                                     "raw_points": round(100 * x.raw, 2), "share_r_labelled": round(x.share_r, 2),
                                     "share_d_labelled": round(x.share_d, 2), "years": x.years} for x in top.itertuples()],
            "largest_any": [{"pollster": x.name, "races": int(x.n_races), "effect_points": round(100 * x.effect, 2)}
                            for x in est.head(5).itertuples()],
            "largest_in_2026_averages": _in_averages(used, est),
            "applied_2026": {"polls_in_averages": int(len(used)),
                             "polls_with_an_effect": int((used["h"] != 0).sum()),
                             "weighted_mean_effect_points": round(100 * wmean, 2),
                             "by_label_mean_effect_points": {k: round(float(100 * g["h"].mean()), 2) for k, g in lab.groupby("label")}},
            "averages": compare_averages(sf, avg_v1, avg_h7)}


def _in_averages(used: pd.DataFrame, est: pd.DataFrame, k: int = 10) -> list[dict]:
    """The pollsters behind v1's 2026 averages with the largest estimated effects."""
    u = used.assign(he=used["pollster"].map(he_key)).groupby("he").agg(races_2026=("race_id", "nunique"))
    e = est.set_index("he_key").join(u, how="inner")
    e = e.reindex(e["effect"].abs().sort_values(ascending=False).index).head(k)
    return [{"pollster": x["name"], "races": int(x.n_races), "races_2026": int(x.races_2026), "effect_points": round(100 * x.effect, 2),
             "share_r_labelled": round(x.share_r, 2), "share_d_labelled": round(x.share_d, 2)} for i, x in e.iterrows()]


def h8(sf: pd.DataFrame, poll_rows: pd.DataFrame, avg_v1: pd.DataFrame, avg_h8: pd.DataFrame,
       run_v1: dict, run_h8: dict) -> dict:
    detail = poll_detail(poll_rows, V1_CUTOFF)
    window = polls.qualifying(poll_rows[poll_rows["year"] == YEAR], V1_CUTOFF)
    cmp = compare_averages(sf, avg_v1, avg_h8)
    lost = cmp["races_losing_all_polls"]
    b1 = run_v1["blend"].set_index("race_id")
    b8 = run_h8["blend"].set_index("race_id")
    v1 = pd.read_csv(V1 / "races.csv").set_index("race_id")
    rows = []
    for rid in lost:
        s = sf[sf["id"] == rid]
        rows.append({"id": rid, "v1_polls": int(v1.loc[rid, "n_polls"]), "v1_poll_avg": round(float(v1.loc[rid, "poll_avg"]), 4),
                     "v1_poll_weight": round(float(b1.loc[rid, "poll_weight"]), 3),
                     "h8_poll_weight": round(float(b8.loc[rid, "poll_weight"]), 3),
                     "v1_p_dem_win": round(float(run_v1["races"].set_index("race_id").loc[rid, "p_dem_win"]), 3),
                     "h8_p_dem_win": round(float(run_h8["races"].set_index("race_id").loc[rid, "p_dem_win"]), 3),
                     "winner": (s["winner_party"].iloc[0] if len(s) and pd.notna(s["winner_party"].iloc[0]) else None),
                     "actual": (round(float(s["dem_share_2p"].iloc[0]), 4) if len(s) and pd.notna(s["dem_share_2p"].iloc[0]) else None)})
    kept = [r for r in run_h8["blend"]["race_id"] if r not in lost]
    w1 = b1.loc[kept, "poll_weight"]
    w8 = b8.loc[kept, "poll_weight"]
    has = (w1 > 0) & (w8 > 0)
    return {"polls_in_window_2026": int(len(window)),
            "labelled_in_window": int((window["pollster"].map(partisan_label) != "").sum()),
            "labelled_in_v1_averages": {"R": int((detail["partisan"] == "R").sum()), "D": int((detail["partisan"] == "D").sum()),
                                        "all": int(len(detail))},
            "lost_all_polls": rows,
            "mean_poll_weight_kept_races": {"v1": round(float(w1[has].mean()), 3), "h8": round(float(w8[has].mean()), 3),
                                            "n": int(has.sum())},
            "averages": cmp}


# --------------------------------------------------------------------------- checks
def checks(res: pd.DataFrame) -> dict:
    h = pd.read_csv(OUT / "generic_ballot_history.csv")
    env = generic_ballot.national_environment(YEAR, h)
    used = h[(h["year"] < YEAR) & h["house_dem_2p"].notna()]["year"].astype(int).tolist()
    even = list(range(1998, YEAR, 2))
    first = results(pd.read_csv(LOG)["pull_id"].min())
    mn0 = first[first["id"].isin(["2026-MN-SEN", "2026-MN-GOV"])]
    pulls = sorted(pd.read_csv(LOG)["pull_id"].unique())
    return {"generic_ballot": {"n_years": env["n_years"], "years_used": used,
                               "even_years_not_used": [y for y in even if y not in used],
                               "reason_not_used": "no 30 September generic-ballot value is collected for them "
                                                  "(generic_ballot() covers 1998-2018 and 2022 only)",
                               "bias": round(env["bias"], 4),
                               "error_min": round(float(h.loc[h["year"].isin(used), "error"].min()), 4),
                               "error_max": round(float(h.loc[h["year"].isin(used), "error"].max()), 4),
                               "years_gb_overstated_dem": int((h.loc[h["year"].isin(used), "error"] < 0).sum()),
                               "as_of_2026": str(h.loc[h["year"] == YEAR, "as_of"].iloc[0]),
                               "as_of_history": sorted(h.loc[h["year"].isin(used), "as_of"].str[5:].unique().tolist())},
            "minnesota_first_logged_pull": [{"id": x.id, "pulled_at": x.pulled_at, "pct_counted": x.pct_counted,
                                             "dem_share_2p": x.dem_share_2p, "called_at": x.called_at} for x in mn0.itertuples()],
            "ap_pulls_kept_locally": pulls}


# --------------------------------------------------------------------------- write-up
def _f(x, nd=2, sign=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "–"
    return (f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}").replace("-", "\u2212")


def _th(x, nd=1) -> str:
    """0.989 -> '98.9th'."""
    return "–" if x is None else f"{100 * x:.{nd}f}th"


def _p(x, nd=0):
    return "–" if x is None else f"{100 * x:.{nd}f}%"


def _label(rid: str) -> str:
    return rid[5:] if rid.startswith("2026-") else rid


def markdown(d: dict) -> str:
    V, M1 = d["variants"], d["variants"]["v1"]["metrics"]
    h2, h3, h4, h6, ck = d["h2"], d["h3"], d["h4"], d["h6"], d["checks"]
    a, b = V["h1a_bias_0"]["metrics"], V["h1b_raw_generic_ballot"]["metrics"]
    late_ok = V["h6_late_polls"].get("metrics") is not None
    hv = d["house_vote_so_far"]
    nat = h4["national_term"]
    gbk = ck["generic_ballot"]
    L = ["# Forecast v1: Election Diagnostics", "",
         "**DIAGNOSTIC.** This page asks why forecast v1 missed where it did (issue #24). It does not change "
         "v1 or its score: v1 is scored as published in `score_provisional.md` (#15), and every rerun below is "
         "a counterfactual run of v1's own code, kept out of that score. "
         f"**Provisional:** results are AP's pull at {d['pulled_at']}, with counting still under way; called "
         f"races only, and vote-share measures over races with at least {MIN_COUNTED:.0%} of the expected vote counted.", "",
         "Every rerun uses v1's code as tagged, v1's inputs and v1's random seeds, and changes one named thing. "
         f"Before any rerun is scored, an unchanged rerun is checked against `forecasts/v1/`: the largest difference "
         f"in any published number is {d['reproduction']['max_abs_difference_from_forecasts_v1']:g}, so the reruns "
         "differ from v1 only by the change described.", "",
         "## Summary", "",
         "| | Question | Finding | Does it matter? |", "|---|---|---|---|",
         f"| H1 | Did the generic-ballot correction cause the miss? | Removing the −{abs(100 * gbk['bias']):.2f}-point correction "
         f"nearly halves the mean error ({_f(M1['all']['mean_error'], sign=True)} to {_f(a['all']['mean_error'], sign=True)} points) and lifts "
         f"80% coverage from {_p(M1['all']['coverage_80'])} to {_p(a['all']['coverage_80'])}; Brier {_f(M1['all']['brier'], 3)} to "
         f"{_f(a['all']['brier'], 3)} | Yes: the largest single factor |",
         f"| H2 | Did the race polls share a miss? | Poll averages understated Democrats by {_f(h2['races']['mean'])} points on "
         f"average (SD {_f(h2['races']['sd'])}) across {h2['races']['n']} races, {_p(h2['share_positive'])} in the same direction; "
         f"no clear relation with poll count or fieldwork date | Yes: a shared miss of about {_f(h2['model']['mean_error_in_s_nat'], 1)} times "
         "the spread v1 allowed for one |",
         f"| H3 | Was the poll weight too low? | On the {h3['polled']['vote_n']} polled races, polls alone: MAE "
         f"{_f(h3['polled']['polls_only']['mae'])} against the blend's {_f(h3['polled']['blend']['mae'])}; Brier "
         f"{_f(h3['polled']['polls_only']['brier'], 3)} against {_f(h3['polled']['blend']['brier'], 3)} | Little: the two barely differ |",
         f"| H4 | Were the intervals too narrow? | The realised House shift ({_f(h4['house']['realised_mean_shift_points'], sign=True)} points) sat at the "
         f"{_th(h4['house']['percentile_realised'])} percentile of v1's simulations; the 90th percentile would need the shared spread "
         f"about {_f(h4['house']['scale_needed'], 1)} times as wide | Yes, but mostly as a consequence of H1 |",
         "| H5 | Did turnout error explain the residual? | Not tested | Waits for near-final counts |",
         (f"| H6 | Did the polls move after 22 October? | Race averages moved {_f(h6['movement_toward_dem']['mean'], sign=True)} points on average "
          f"toward Democrats by 3 November; the late averages close {_p(h6['scored']['share_of_error_closed'])} of the mean poll error, and "
          f"Senate and governor Brier would have been {_f(_sg_brier(V['h6_late_polls']['metrics']), 3)} rather than "
          f"{_f(_sg_brier(M1), 3)} | Some: the lock date cost a little, but most of the poll error was there on election morning |")
         if late_ok else "| H6 | Did the polls move after 22 October? | Not run | Needs the 3 November poll timelines |",
         *summary_h7_h8(d),
         "",
         "## H1: The National Correction", "",
         f"v1 took the generic ballot on 22 October ({_p(d['variants']['h1a_bias_0']['house_vote_mean'], 1)} Democratic, two-party) and "
         f"shifted it by the historical mean of (House vote minus 30 September generic ballot), {_f(100 * gbk['bias'])} points, giving a "
         f"national House vote of {_p(M1_env_mean(d), 1)}. Two diagnostic reruns remove that correction:", "",
         "- **Bias 0:** the generic ballot itself as the centre of the national House vote, with v1's spread unchanged.",
         "- **Raw generic ballot:** the generic ballot used as the national House vote outright, with no correction and no "
         "national spread. This reading of \"the raw generic ballot\" in #24 is an interpretation; it isolates what the spread adds.", "",
         "| Run | Called races | Brier | Log loss | Upsets (expected) | Vote-share races | Mean error | MAE | 80% coverage | Below / above |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    rows = [("v1 as published", M1)] + [((("DIAGNOSTIC: ") + V[k]["description"].split(": ", 1)[1]), V[k]["metrics"])
                                        for k in ("h1a_bias_0", "h1b_raw_generic_ballot")]
    for name, m in rows:
        g = m["all"]
        L.append(f"| {name} | {g['called']} | {_f(g['brier'], 3)} | {_f(g['log_loss'], 3)} | {g['upsets']} ({_f(g['expected_upsets'], 1)}) | "
                 f"{g['vote_n']} | {_f(g['mean_error'], sign=True)} | {_f(g['mae'])} | {_p(g['coverage_80'])} | {g['below_80']} / {g['above_80']} |")
    L += ["", "By office (Brier; MAE; 80% coverage):", "",
          "| Run | Senate | Governor | House |", "|---|---|---|---|"]
    for name, m in rows:
        L.append(f"| {name} | " + " | ".join(f"{_f(m[o]['brier'], 3)}; {_f(m[o]['mae'])}; {_p(m[o]['coverage_80'])}"
                                              for o in ("senate", "governor", "house")) + " |")
    L += ["", f"Removing the correction moves every race toward Democrats, which is the direction of the miss, so all three "
          f"measures improve. The mean error falls from {_f(M1['all']['mean_error'], sign=True)} to {_f(a['all']['mean_error'], sign=True)} "
          f"points: the correction accounts for a little under half of the uniform shift, not all of it. The House gains most "
          f"(MAE {_f(M1['house']['mae'])} to {_f(a['house']['mae'])}); the governors' races least "
          f"({_f(M1['governor']['mae'])} to {_f(a['governor']['mae'])}), where the mean error was smaller to begin with "
          f"({_f(M1['governor']['mean_error'], sign=True)}) and most of the error is race-to-race scatter (RMSE {_f(M1['governor']['rmse'])}). Dropping the national spread as well (the raw generic ballot) changes little on these measures "
          f"(coverage {_p(a['all']['coverage_80'])} against {_p(b['all']['coverage_80'])}).", "",
          f"The generic ballot itself also understated Democrats. AP's House counts so far give Democrats "
          f"{_p(hv['dem_2p'], 1)} of the two-party House vote ({_p(hv['vote_weighted_pct_counted'])} of the expected vote counted, "
          f"{hv['districts_below_95pct']} districts under 95%; uncontested seats and incomplete western counts make this rough). "
          f"That is above both v1's {_p(M1_env_mean(d), 1)} and the uncorrected generic ballot. In 11 of the 12 earlier cycles the "
          "30 September generic ballot overstated the Democratic House vote; on present counts 2026 is the second exception, after 2008.", "",
          "Not a cause on these numbers: the choice of cycles. See the generic-ballot check below.", "",
          "## H2: A Shared Polling Miss", "",
          f"Error is the actual Democratic two-party share minus v1's race poll average (`poll_avg`), in points, over the "
          f"{h2['races']['n']} scored Senate and governor races that had polls.", "",
          "| | Races | Mean | SD | MAE | RMSE |", "|---|---|---|---|---|---|"]
    for name, e in [("All with polls", h2["races"]), ("Senate", h2["by_office"]["senate"]), ("Governor", h2["by_office"]["governor"]),
                    ("1 to 4 polls", h2["by_bucket"]["1-4"]), ("5 or more polls", h2["by_bucket"]["5+"])]:
        L.append(f"| {name} | {e['n']} | {_f(e['mean'], sign=True)} | {_f(e['sd'])} | {_f(e['mae'])} | {_f(e['rmse'])} |")
    md_ = h2["model"]
    L += ["", f"{_p(h2['share_positive'])} of the averages understated the Democrat. On the logit scale the mean miss was "
          f"{md_['mean_error_logit']:.3f}, against a shared polling error of SD {md_['s_nat_logit']:.3f} in v1's poll-error model "
          f"(fitted on 2018 and 2022): {md_['mean_error_in_s_nat']:.2f} standard deviations. Around that shared miss, races scattered "
          f"less than v1 expected (SD {md_['race_sd_realised_logit']:.3f} against {md_['race_sd_expected_logit']:.3f}). The polling error was "
          "mostly common to all races rather than race by race, which is the pattern that intervals built from independent race errors "
          "cannot absorb.", "",
          "What the race error does and does not relate to (correlation with the race's error, Pearson and Spearman):", "",
          "| Feature of the race's polls | Races | Pearson r (p) | Spearman ρ (p) |", "|---|---|---|---|"]
    names = {"n_polls": "Number of polls", "n_eff": "Effective number of polls", "mean_age_days": "Weighted mean fieldwork age (days)",
             "newest_age_days": "Age of the newest poll (days)", "share_partisan_r": "Weight on Republican-labelled polls",
             "share_partisan_d": "Weight on Democratic-labelled polls", "share_lv": "Weight on likely-voter polls"}
    for k, lab in names.items():
        c = h2["correlations"][k]
        L.append(f"| {lab} | {c['n']} | {_f(c['pearson_r'])} ({_f(c['pearson_p'], 3)}) | {_f(c['spearman_rho'])} ({_f(c['spearman_p'], 3)}) |")
    pl = h2["polls"]
    L += ["", "Poll by poll (each poll that entered an average, against its race's result):", "",
          "| Polls | Number | Mean error | SD | MAE |", "|---|---|---|---|---|"]
    for lab in ("Republican-labelled", "unlabelled", "Democratic-labelled"):
        e = pl["by_label"].get(lab)
        if e:
            L.append(f"| {lab[0].upper() + lab[1:]} | {e['n']} | {_f(e['mean'], sign=True)} | {_f(e['sd'])} | {_f(e['mae'])} |")
    for band, e in pl["by_age_days"].items():
        L.append(f"| Fieldwork ended {band} days before 22 October | {e['n']} | {_f(e['mean'], sign=True)} | {_f(e['sd'])} | {_f(e['mae'])} |")
    L += ["", "Neither the number of polls nor fieldwork date shows a reliable relation with the error: races with many polls missed "
          "by about as much on average as races with few, though with less scatter, and recent polls missed by as much as older ones "
          f"(poll-level correlation with age {_f(pl['age_corr']['pearson_r'])}). Pollster mix does show one: the more weight on polls "
          "Wikipedia labels as Republican-sponsored, the larger the miss, and Democratic-labelled polls missed least. Even the "
          "Democratic-labelled polls understated Democrats on average, so the mix shifts the size of the miss, not its sign. With seven "
          "features tested on 45 races, the p-values are indicative only. Labels are Wikipedia's sponsor marks, so unlabelled polls "
          "include partisan pollsters that are not marked.", "",
          "Largest race misses: " + ", ".join(f"{_label(x['id'])} ({_f(x['err'], 1, sign=True)}, {x['n_polls']} poll{'s' if x['n_polls'] != 1 else ''})"
                                               for x in h2["largest"]) + ".", "",
          "## H3: The Blend Weight", "",
          "Polls alone uses v1's own poll-error model: the result is centred on the poll average with v1's poll-error variance "
          "(shared, floor and per-poll terms), giving a median, an 80% interval and a win probability. Races with no polls have no "
          "polls-only forecast; there the blend is the fundamentals.", "",
          "| Polls in the race | Called | Mean poll weight | Brier: blend | fundamentals | polls only | Vote races | MAE: blend | fundamentals | polls only | Coverage: blend | polls only |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, lab in (("polled", "Any (1 or more)"), ("0", "0"), ("1-4", "1 to 4"), ("5+", "5 or more"), ("all", "All races")):
        r = h3[k]
        L.append(f"| {lab} | {r['called']} | {_f(r['mean_poll_weight'])} | {_f(r['blend']['brier'], 3)} | {_f(r['fundamentals']['brier'], 3)} | "
                 f"{_f(r['polls_only']['brier'], 3)} | {r['vote_n']} | {_f(r['blend']['mae'])} | {_f(r['fundamentals']['mae'])} | "
                 f"{_f(r['polls_only']['mae'])} | {_p(r['blend']['coverage_80'])} | {_p(r['polls_only']['coverage_80'])} |")
    bw = h3["best_weight_in_hindsight"]
    L += ["", f"Both inputs understated Democrats, the fundamentals by more, so in this election any weight on the fundamentals "
          f"cost accuracy: in hindsight, the weight on the poll average that minimises squared error over the {bw['n']} polled races is "
          f"{bw['w']:.2f}, against v1's mean of {bw['v1_mean_weight']:.2f} (descriptive only, not a refit; one year of error in one "
          "direction is a poor guide to the weight). Yet over all polled races polls alone and the blend are almost level; #24's "
          "election-night figures, on fewer races, had polls alone further ahead. The comparison differs by poll count. With one to "
          "four polls, polls alone are no better on vote share and worse on Brier: their uncertainty is wide, so they give the "
          "favourite less than the blend does in races the favourite won ("
          + ", ".join(_label(x) for x in h3["few_polls_worse_for_polls_only"]) + "). With five or more polls, polls alone beat the blend on both. A higher poll weight would have "
          "helped a little where polls were plentiful, but H3 is not where most of the error came from, and it is partly H1 in another "
          "form: the fundamentals were pulled toward Republicans by the same national correction.", "",
          "## H4: Interval Width", "",
          "Report only; nothing is refitted.", "",
          f"v1's national House vote was a Student-t with {h4['national_environment']['df']} degrees of freedom and scale "
          f"{_f(100 * h4['national_environment']['scale'])} points (SD {_f(h4['national_environment']['sd_points'])} points; 90th percentile "
          f"{_f(h4['national_environment']['q90_points'], sign=True)} points above the mean).", "",
          "| | Races | Realised mean shift (points) | Simulated SD of the mean shift | v1 90th percentile | Percentile of the realised shift | Widening needed for 90th | SD needed |",
          "|---|---|---|---|---|---|---|---|"]
    for k, lab in (("house", "House (contested, scored)"), ("senate_and_governor", "Senate and governor (scored)")):
        x = h4[k]
        L.append(f"| {lab} | {x['n']} | {_f(x['realised_mean_shift_points'], sign=True)} | {_f(x['sd_simulated'])} | "
                 f"{_f(x['q_simulated'], sign=True)} | {_th(x['percentile_realised'])} | {_f(x['scale_needed'], 2)}× | {_f(x['sd_needed'])} |")
    L += ["", "The simulated mean shift is the average, over the same scored races, of each simulation's deviation from v1's medians: "
          "it carries the national term and the shared regional and state terms together. "
          f"For the national term alone, the realised House shift on the logit scale ({nat['realised_logit_shift']:.3f}, about "
          f"{_f(nat['realised_shift_points_at_mean'])} points near v1's mean) sits at the {_th(nat['percentile_in_v1_t'])} percentile of v1's t; "
          f"putting it at the 90th would need a scale of about {_f(nat['scale_needed_points'])} points (SD about {_f(nat['sd_needed_points'])}), "
          f"{_f(nat['ratio_to_v1'], 1)} times v1's.", "",
          f"Two readings follow, and they point in different directions. The spread v1 used is the scatter of the 12 earlier "
          f"cycles' generic-ballot errors around their mean (from {_f(100 * gbk['error_min'], 1, sign=True)} to {_f(100 * gbk['error_max'], 1, sign=True)} points); "
          f"a 2026 miss of this size lies outside that history, so a wider national term, or a heavier tail, is a fair conclusion. But the interval was not only narrow; it was in the wrong place. With the "
          f"correction removed (H1), coverage across all scored races is {_p(a['all']['coverage_80'])} with v1's spread unchanged. "
          "Most of the coverage shortfall is the centre, and widening alone would have bought coverage with weaker calls.", "",
          "## H5: Turnout", "",
          f"**Waiting.** Counts are not near final: across House races, {_p(hv['vote_weighted_pct_counted'])} of the expected vote is counted, "
          f"and {hv['districts_below_95pct']} districts are under 95%. Turnout needs total ballots cast by county, over v1's citizen "
          "voting-age population denominators, which come with certification. Until then the turnout-first stage is untested, and "
          "whether county turnout error explains any of the vote-share residual after the uniform shift is unknown.", ""]
    L += ["## H6: The Late Swing", ""]
    if late_ok:
        mv, sc = h6["movement_toward_dem"], h6["scored"]
        lv = V["h6_late_polls"]["metrics"]
        both = V["h1a_and_h6"]["metrics"]
        L += [f"Source: each race's Wikipedia article as it stood at 12:00 UTC on 3 November (7 am Eastern on election day), parsed and averaged "
              f"with v1's own code and rules (one poll per pollster, 21-day half-life, 90-day window), with the cut-off moved from 22 October "
              f"to {pd.Timestamp(h6['cutoff']):%-d %B}. Silver Bulletin's and Decision Desk HQ's own timelines were not used: neither is in the repository's data "
              "and the averages here follow v1's definition, which theirs do not.", "",
              "| | Value |", "|---|---|",
              f"| Races with polls: 22 October / 3 November | {h6['races_with_polls']['v1']} / {h6['races_with_polls']['final']} |",
              f"| Polls with fieldwork ending after 22 October | {h6['polls_ending_after_v1_cutoff']} (in {h6['races_with_new_polls']} races) |",
              f"| Movement of the average, 22 October to 3 November (toward Democrats) | mean {_f(mv['mean'], sign=True)}, SD {_f(mv['sd'])}, "
              f"mean absolute {_f(mv['mae'])} points over {mv['n']} races |",
              f"| Races whose average moved toward Democrats | {_p(h6['share_moving_toward_dem'])} |",
              f"| Polls listed after 22 October but fielded before it (same cut-off) | mean {_f(h6['late_listed_effect']['mean'], sign=True)} points over {h6['late_listed_effect']['n']} races |",
              f"| Scored races: mean error of v1's average / of the 3 November average | {_f(sc['error_v1_avg']['mean'], sign=True)} / "
              f"{_f(sc['error_final_avg']['mean'], sign=True)} points ({sc['n']} races) |",
              f"| MAE of v1's average / of the 3 November average | {_f(sc['error_v1_avg']['mae'])} / {_f(sc['error_final_avg']['mae'])} |", "",
              "DIAGNOSTIC reruns with the 3 November averages (this looks past v1's lock date, so it measures what the lock date cost, "
              "not what v1 could have known):", "",
              "| Run | Brier (all) | Senate and governor Brier | MAE (all) | Mean error | 80% coverage |", "|---|---|---|---|---|---|"]
        for name, m in (("v1 as published", M1), ("DIAGNOSTIC: 3 November poll averages", lv),
                        ("DIAGNOSTIC: bias 0 and 3 November poll averages", both)):
            sg = _sg_brier(m)
            L.append(f"| {name} | {_f(m['all']['brier'], 3)} | {_f(sg, 3)} | {_f(m['all']['mae'])} | {_f(m['all']['mean_error'], sign=True)} | {_p(m['all']['coverage_80'])} |")
        L += ["", h6_reading(h6), ""]
        gl = d.get("generic_ballot_3_november")
        if gl:
            L += [f"The generic ballot on the same page at the same time (mean of {', '.join(gl['sources'])}; revision {gl['revision']}) "
                  f"was {_p(gl['gb_dem_2p'], 1)} Democratic, two-party, against {_p(d['variants']['h1a_bias_0']['house_vote_mean'], 1)} on "
                  "22 October.", ""]
    else:
        L += ["Not run: the 3 November revisions of the race articles are not saved. `python -m forecast.diagnostics --fetch-late` "
              "fetches them.", ""]
    L += markdown_h7_h8(d)
    L += ["## Checks", "",
          f"**Generic-ballot cycles.** `python -m forecast.generic_ballot` gives `n_years` = {gbk['n_years']} for 2026. The years used are "
          f"{', '.join(map(str, gbk['years_used']))}. The even years {' and '.join(map(str, gbk['even_years_not_used']))} drop out because no "
          "30 September generic-ballot value is collected for them (`generic_ballot()` reads 1998 to 2016 from FiveThirtyEight's history, "
          "2018 from its archived file and 2022 from Wikipedia), although their House votes are read. The write-up's \"11 of the 12 cycles "
          "since 1998\" is therefore right in count, and #24's concern that the code averages 14 cycles does not hold; the wording would "
          "be clearer as \"12 of the 14 cycles from 1998 to 2024 (2020 and 2024 lack a 30 September value)\". The docstring's \"every even "
          "year before `year` with both numbers\" is accurate. One related point: the bias is estimated from end-of-September values "
          f"(18 to 30 September), but 2026 used the value on {pd.Timestamp(gbk['as_of_2026']):%-d %B}, about three weeks later and closer to the election, "
          "when the generic ballot's historical overstatement may be smaller. That mismatch is untested.", "",
          "**Minnesota count order.** " + mn_line(ck), "",
          "**Archiving the AP feed.** " + ap_line(ck), "",
          "**Final counts.** This page should be rerun on final counts (`python -m forecast.diagnostics --pull <id>` after a new pull); "
          "#24 notes that late mail in the West tends to lean Democratic, so the shift may grow.", "",
          "## Files", "",
          "- `results/diagnostics.json`: the numbers on this page.",
          "- `src/forecast/diagnostics.py`: the code (`python -m forecast.diagnostics`); `tests/test_diagnostics.py`.",
          "- Rerun tables (local, not committed, each marked DIAGNOSTIC): `data/processed/diagnostics_v1/<run>/`.",
          "- 3 November Wikipedia revisions (local): `data/raw/polls_late_2026/`.",
          "- H7's estimated house effects, one row per pollster (local, DIAGNOSTIC): `data/processed/diagnostics_v1/house_effects.csv`.",
          "- `results/through_time.json` and the Through Time section: `src/forecast/through_time.py` (`python -m forecast.through_time`, run after `forecast.diagnostics`, which rewrites this page).", ""]
    return "\n".join(L)


def _moves(a, b, nd=2, sign=True, unit=" points") -> str:
    """'moves from +3.15 to +3.12 points', or 'is unchanged at +3.15 points' when the two round alike."""
    x, y = _f(a, nd, sign), _f(b, nd, sign)
    return f"is unchanged at {x}{unit}" if x == y else f"moves from {x} to {y}{unit}"


def _verdict(m0: dict, m: dict) -> str:
    """A plain verdict on a poll change: the overall Brier and mean error, and the Senate and
    governor Brier (the only races whose forecasts use race polls)."""
    db = m["all"]["brier"] - m0["all"]["brier"]
    de = abs(m["all"]["mean_error"]) - abs(m0["all"]["mean_error"])
    dsg = _sg_brier(m) - _sg_brier(m0)
    sg = f"Senate and governor Brier {_f(_sg_brier(m0), 3)} to {_f(_sg_brier(m), 3)}"
    if db < -0.003 or de < -0.5:
        return f"Some: it narrows the miss, but far less than H1 ({sg})"
    if dsg < -0.003:
        return f"Little overall, some for the polled races ({sg}); the shared miss remains"
    if dsg > 0.003:
        return f"No: slightly worse for the polled races ({sg})"
    return f"Little: the scores barely move ({sg})"


def summary_h7_h8(d: dict) -> list[str]:
    V, M1 = d["variants"], d["variants"]["v1"]["metrics"]
    if "h7" not in d:
        return []
    f7, a7, a8 = d["h7"]["fit"], d["h7"]["averages"], d["h8"]["averages"]
    m7, m8 = V["h7_house_effects"]["metrics"], V["h8_no_partisan"]["metrics"]
    return [
        f"| H7 | Would removing pollster house effects have helped? | House effects for {f7['pollsters_estimated']} pollsters "
        f"({f7['pollsters_3plus_races']} in three or more races) moved the race averages {_f(a7['movement_toward_dem']['mean'], sign=True)} points "
        f"on average; the mean error {_moves(M1['all']['mean_error'], m7['all']['mean_error'])} and the Brier score "
        f"{_moves(M1['all']['brier'], m7['all']['brier'], 3, False, '')} (with H1: {_f(V['h7_and_h1a']['metrics']['all']['brier'], 3)}) | {_verdict(M1, m7)} |",
        f"| H8 | Would leaving out partisan polls have helped? | {len(a8['races_losing_all_polls'])} races lose all their polls; the rest "
        f"move {_f(a8['movement_toward_dem']['mean'], sign=True)} points on average; the mean error {_moves(M1['all']['mean_error'], m8['all']['mean_error'])} "
        f"and the Brier score {_moves(M1['all']['brier'], m8['all']['brier'], 3, False, '')} "
        f"(with H1: {_f(V['h8_and_h1a']['metrics']['all']['brier'], 3)}) | {_verdict(M1, m8)} |"]


def _variant_tables(rows: list[tuple[str, dict]]) -> list[str]:
    L = ["| Run | Called races | Brier | Log loss | Upsets (expected) | Vote-share races | Mean error | MAE | 80% coverage | Below / above |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for name, m in rows:
        g = m["all"]
        L.append(f"| {name} | {g['called']} | {_f(g['brier'], 3)} | {_f(g['log_loss'], 3)} | {g['upsets']} ({_f(g['expected_upsets'], 1)}) | "
                 f"{g['vote_n']} | {_f(g['mean_error'], sign=True)} | {_f(g['mae'])} | {_p(g['coverage_80'])} | {g['below_80']} / {g['above_80']} |")
    L += ["", "By office (Brier; mean error; MAE; 80% coverage):", "",
          "| Run | Senate | Governor | House |", "|---|---|---|---|"]
    for name, m in rows:
        L.append(f"| {name} | " + " | ".join(f"{_f(m[o]['brier'], 3)}; {_f(m[o]['mean_error'], sign=True)}; {_f(m[o]['mae'])}; {_p(m[o]['coverage_80'])}"
                                              for o in ("senate", "governor", "house")) + " |")
    return L


def _avg_lines(a: dict, label: str) -> list[str]:
    sc, mv = a["scored"], a["movement_toward_dem"]
    return ["| | Value |", "|---|---|",
            f"| Races with polls: v1 / {label} | {a['races_with_polls']['v1']} / {a['races_with_polls']['new']} |",
            f"| Polls in the averages: v1 / {label} | {a['polls_in_averages']['v1']} / {a['polls_in_averages']['new']} |",
            f"| Change in the average, {label} minus v1 (toward Democrats) | mean {_f(mv['mean'], sign=True)}, SD {_f(mv['sd'])}, "
            f"mean absolute {_f(mv['mae'])} points over {mv['n']} races |",
            f"| Scored races: mean error of v1's average / of the {label} average | {_f(sc['error_v1_avg']['mean'], sign=True)} / "
            f"{_f(sc['error_new_avg']['mean'], sign=True)} points ({sc['n']} races) |",
            f"| MAE of v1's average / of the {label} average | {_f(sc['error_v1_avg']['mae'])} / {_f(sc['error_new_avg']['mae'])} |"]


def markdown_h7_h8(d: dict) -> list[str]:
    if "h7" not in d:
        return []
    V, M1 = d["variants"], d["variants"]["v1"]["metrics"]
    h7_, h8_ = d["h7"], d["h8"]
    f7, ap = h7_["fit"], h7_["applied_2026"]
    base = [("v1 as published", M1), ("DIAGNOSTIC: generic-ballot bias set to 0 (H1)", V["h1a_bias_0"]["metrics"])]
    L = ["## H7: Pollster House Effects", "",
         "**DIAGNOSTIC.** A house effect is a pollster's persistent lean relative to other pollsters polling the same race. Forecasters "
         "such as the Silver Bulletin estimate it and remove it before averaging; its public methodology page describes an iterative "
         "comparison of each firm with the average, with the share of a firm's gap that is removed growing with how much it has polled. "
         "This rerun asks whether a simple version of that adjustment would have reduced v1's miss.", "",
         "Method, fixed before scoring:", "",
         "- **Polls.** Head-to-head polls from the same Wikipedia race articles v1 used: 2018 and 2022 Senate and governor races "
         "(fieldwork ending in the 90 days up to election day; all of these were public long before 22 October 2026) and 2026 races "
         "(fieldwork ending in the 90 days up to v1's 22 October cut-off, never later). Each pollster's polls in a race are averaged "
         "first, so a pollster counts once per race however often it polled there.",
         f"- **Model.** On the two-party share, each pollster-race average = a race effect + the pollster's house effect + noise. The race "
         "effects are free, so a house effect measures only how a pollster differs from the others in the races it shared with them; "
         "races polled by a single pollster carry no information and are dropped. The house effects are treated as random, "
         f"Normal(0, τ²), around noise of variance σ², with both variances estimated from the data (EM): σ = {_f(f7['sigma_points'])} and "
         f"τ = {_f(f7['tau_points'])} points.",
         f"- **Shrinkage.** Each house effect is then the standard shrunken estimate: the pollster's mean deviation from the race effects, "
         f"multiplied by n / (n + σ²/τ²), where n is its number of races and σ²/τ² = {_f(f7['lambda_races'])}. A pollster seen in one race keeps "
         f"about {_p(1 / (1 + f7['lambda_races']))} of its raw deviation, one seen in ten races about {_p(10 / (10 + f7['lambda_races']))}. The "
         "reference is the average pollster in these data (each pollster counted once; the effects sum to zero), not the result: removing "
         "house effects cannot correct a miss that all pollsters share.",
         "- **Rerun.** Each 2026 poll's share has its pollster's house effect subtracted (pollsters with no estimate are left as they are), "
         "and v1's averages are rebuilt with v1's own code: one poll per pollster, 90-day window, 21-day half-life, sample-size and "
         "population weights. Everything else is v1's: fits, poll-error model, seeds and generic-ballot correction.",
         f"- **Pollster names.** v1's pollster key (sponsors in brackets dropped), with a leading \"the\", a trailing \"inc\" and the spacing "
         "around \"/\" tidied. Names are not otherwise harmonised, so a firm that appears under several names (Siena with different media "
         "partners, for example) is estimated under each, with fewer races and more shrinkage.", "",
         f"House effects were estimated for {f7['pollsters_estimated']} pollsters from {f7['cells']} pollster-race averages in {f7['races']} races; "
         f"{f7['pollsters_3plus_races']} pollsters appear in three or more races. As a check during development, a REML linear mixed model with the same "
         "structure (statsmodels MixedLM, not a project dependency) gave practically the same effects (correlation 0.9996, largest "
         "difference 0.5 points); the 2026 polls are those before the cut-off, so a new results pull does not change them. Positive means more Democratic than the other pollsters in the "
         "same races. The largest among pollsters in three or more races:", "",
         "| Pollster | Races | House effect (points) | Raw deviation | Share of its polls labelled R / D | Years |", "|---|---|---|---|---|---|"]
    for x in h7_["largest_3plus_races"]:
        L.append(f"| {x['pollster']} | {x['races']} | {_f(x['effect_points'], sign=True)} | {_f(x['raw_points'], sign=True)} | "
                 f"{_p(x['share_r_labelled'])} / {_p(x['share_d_labelled'])} | {x['years'].replace(',', ', ')} |")
    L += ["", "The largest among the pollsters behind v1's 2026 averages:", "",
          "| Pollster | Races (all years) | 2026 races | House effect (points) | Share of its polls labelled R / D |", "|---|---|---|---|---|"]
    for x in h7_["largest_in_2026_averages"]:
        L.append(f"| {x['pollster']} | {x['races']} | {x['races_2026']} | {_f(x['effect_points'], sign=True)} | "
                 f"{_p(x['share_r_labelled'])} / {_p(x['share_d_labelled'])} |")
    lab = ap["by_label_mean_effect_points"]
    L += ["", f"Of the {ap['polls_in_averages']} polls in v1's 2026 averages, {ap['polls_with_an_effect']} had a house effect to remove; their "
          f"weighted mean was {_f(ap['weighted_mean_effect_points'], sign=True)} points. Mean effect by Wikipedia's label: "
          + ", ".join(f"{k} {_f(v, sign=True)}" for k, v in sorted(lab.items())) + " points.", ""]
    L += _avg_lines(h7_["averages"], "H7") + [""]
    L += _variant_tables(base + [("DIAGNOSTIC: house effects removed (H7)", V["h7_house_effects"]["metrics"]),
                                 ("DIAGNOSTIC: house effects removed and bias 0 (H7 and H1)", V["h7_and_h1a"]["metrics"])])
    L += ["", h7_reading(d), ""]
    # H8
    lost = h8_["lost_all_polls"]
    lv = h8_["labelled_in_v1_averages"]
    mw = h8_["mean_poll_weight_kept_races"]
    L += ["## H8: Partisan Polls Left Out", "",
          "**DIAGNOSTIC.** v1's race averages rebuilt with every poll Wikipedia labels with a Democratic or Republican sponsor left out "
          "(the labels H2 uses, such as \"(R)\" or \"(D-sponsor)\"), and nothing else changed; where a pollster's latest poll was "
          "partisan-sponsored, its latest unlabelled poll is used if there is one. The Silver Bulletin's public methodology page says "
          "that for its generic-ballot average polls with partisan sponsors are excluded from the calculation of the \"true\" average "
          "against which house effects are measured, and that in its race averages they start from a prior of a lean toward the sponsor. "
          "Leaving them out of the average altogether, as here, is the simpler and stronger version of that idea, not their method.", "",
          f"Of the {lv['all']} polls in v1's 2026 averages, {lv['R']} were labelled Republican and {lv['D']} Democratic "
          f"({h8_['labelled_in_window']} of the {h8_['polls_in_window_2026']} polls in the 90-day window carry a label).", ""]
    L += _avg_lines(h8_["averages"], "H8") + [""]
    if lost:
        L += [f"**Races left without polls: {len(lost)}.** v1's blend treats a race with no qualifying poll exactly as it treats any "
              "unpolled race: the poll weight is 0 and the forecast is the fundamentals alone. No other source of polls is substituted.", "",
              "| Race | v1 polls (all labelled) | v1 poll average (D) | v1 poll weight | H8 poll weight | P(D win): v1 | H8 | Winner | Actual (D) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for x in lost:
            L.append(f"| {_label(x['id'])} | {x['v1_polls']} | {_p(x['v1_poll_avg'], 1)} | {_f(x['v1_poll_weight'])} | {_f(x['h8_poll_weight'])} | "
                     f"{_p(x['v1_p_dem_win'])} | {_p(x['h8_p_dem_win'])} | {x['winner'] or '–'} | {_p(x['actual'], 1) if x['actual'] is not None else '–'} |")
        L.append("")
    else:
        L += ["No race loses all its polls.", ""]
    L += [f"In the other polled races, fewer polls mean a smaller effective number, a wider poll error in v1's model and so a lower weight "
          f"on the polls: mean poll weight {_f(mw['v1'])} in v1 against {_f(mw['h8'])} here ({mw['n']} races).", ""]
    L += _variant_tables(base + [("DIAGNOSTIC: partisan polls left out (H8)", V["h8_no_partisan"]["metrics"]),
                                 ("DIAGNOSTIC: partisan polls left out and bias 0 (H8 and H1)", V["h8_and_h1a"]["metrics"])])
    L += ["", h8_reading(d), "",
          "**Limits of H7 and H8.** Both keep v1's poll-error model as fitted on v1's own 2018 and 2022 averages; a forecaster who "
          "adjusted or filtered polls would also refit that model on averages built the same way, which is not done here. Wikipedia's "
          "sponsor labels are incomplete (unlabelled polls include partisan firms that are not marked), and H7's house effects do not "
          "separate a pollster's lean from differences in timing within a race or in likely-voter screens. Both are DIAGNOSTIC reruns and "
          "change neither v1 nor its score.", ""]
    return L


def h7_reading(d: dict) -> str:
    V, M1 = d["variants"], d["variants"]["v1"]["metrics"]
    a, m = d["h7"]["averages"], V["h7_house_effects"]["metrics"]
    sc = a["scored"]
    return (f"Removing house effects moves the averages {_f(a['movement_toward_dem']['mean'], sign=True)} points toward Democrats on average "
            f"(mean absolute change {_f(a['movement_toward_dem']['mae'])}), and the scored races' poll error from "
            f"{_f(sc['error_v1_avg']['mean'], sign=True)} to {_f(sc['error_new_avg']['mean'], sign=True)} points (MAE "
            f"{_f(sc['error_v1_avg']['mae'])} to {_f(sc['error_new_avg']['mae'])}). Because house effects are measured against the "
            "average pollster, removing them corrects only how far a race's mix of pollsters leaned relative to that average "
            f"(the weighted mean effect in v1's 2026 averages was {_f(d['h7']['applied_2026']['weighted_mean_effect_points'], sign=True)} "
            "points), not a miss that every pollster shared, and most of 2026's poll error was shared (H2). So the adjustment "
            "mainly reduces race-to-race scatter: the overall mean error moves from "
            f"{_f(M1['all']['mean_error'], sign=True)} to {_f(m['all']['mean_error'], sign=True)} points and the Brier score from "
            f"{_f(M1['all']['brier'], 3)} to {_f(m['all']['brier'], 3)}, with the Senate Brier {_f(M1['senate']['brier'], 3)} to "
            f"{_f(m['senate']['brier'], 3)} and the governors' {_f(M1['governor']['brier'], 3)} to {_f(m['governor']['brier'], 3)}. "
            "The House, whose forecasts use no race polls, is unchanged.")


def h8_reading(d: dict) -> str:
    V, M1 = d["variants"], d["variants"]["v1"]["metrics"]
    a, m = d["h8"]["averages"], V["h8_no_partisan"]["metrics"]
    sc = a["scored"]
    return (f"Leaving out partisan polls moves the remaining averages {_f(a['movement_toward_dem']['mean'], sign=True)} points toward "
            f"Democrats on average, and the scored races' poll error from {_f(sc['error_v1_avg']['mean'], sign=True)} to "
            f"{_f(sc['error_new_avg']['mean'], sign=True)} points ({sc['n']} races with polls under both). The forecast's overall mean error "
            f"{_moves(M1['all']['mean_error'], m['all']['mean_error'])} and its Brier score "
            f"{_moves(M1['all']['brier'], m['all']['brier'], 3, False, '')} (Senate {_f(M1['senate']['brier'], 3)} to {_f(m['senate']['brier'], 3)}, "
            f"governors {_f(M1['governor']['brier'], 3)} to {_f(m['governor']['brier'], 3)}). The averages move toward Democrats, but with "
            "fewer polls v1's blend puts less weight on them and more on the fundamentals, which understated Democrats by more, so the "
            "two effects roughly cancel. Republican-sponsored polls missed most in H2, but the unlabelled polls that remain also "
            "understated Democrats, so the exclusion does not remove the shared miss.")


def M1_env_mean(d: dict) -> float:
    return float(pd.read_csv(V1 / "national.csv")["house_dem_2p_mean"].iloc[0])


def _sg_brier(m: dict):
    s, g = m["senate"], m["governor"]
    if s["brier"] is None or g["brier"] is None:
        return None
    return (s["brier"] * s["called"] + g["brier"] * g["called"]) / (s["called"] + g["called"])


def h6_reading(h6: dict) -> str:
    sc, mv = h6["scored"], h6["movement_toward_dem"]
    closed = sc["share_of_error_closed"] or 0
    if closed < 0.25:
        verdict = ("The late movement was small next to the miss: most of the poll error was still there on election morning, so on "
                   "this evidence the polls were mainly wrong, and the lock date cost comparatively little.")
    elif closed < 0.6:
        verdict = ("The late movement closed part of the poll error but left most of it: the lock date cost something, and the polls "
                   "were still wrong on election morning.")
    else:
        verdict = ("Most of the poll error closed by election morning: on this evidence the lock date, not the polls, cost most.")
    return (f"Averages moved {_f(mv['mean'], sign=True)} points on average. Over the scored races the 3 November averages close "
            f"{_p(closed)} of v1's mean poll error. " + verdict)


def mn_line(ck: dict) -> str:
    rows = ck["minnesota_first_logged_pull"]
    if not rows:
        return "No Minnesota rows in the log."
    t = rows[0]["pulled_at"]
    bits = "; ".join(f"{_label(r['id'])} {_p(r['dem_share_2p'], 1)} Democratic with {_p(r['pct_counted'])} counted, called at "
                     f"{r['called_at'][11:16]} UTC" for r in rows)
    return ("The snapshot in #24 saw Republicans ahead in both Minnesota races early in the count, before both went to the Democrats. "
            f"The repository cannot show the early lead: its first pull ({t}) came after both calls ({bits}). Early returns are ordered by "
            "how each county reports and by ballot type (in-person and mail are counted and released at different times), so an early "
            "lead says little about the result; the write-up should say so in a line before reading early returns as signal. The Internet "
            "Archive holds a capture of AP's national feed at 05:04 UTC on 4 November, just before both calls, which could document the "
            "early count if needed; it has not been downloaded here.")


def ap_line(ck: dict) -> str:
    return (f"The project keeps AP's raw files for its own {len(ck['ap_pulls_kept_locally'])} pulls "
            f"({', '.join(ck['ap_pulls_kept_locally'])}) under `data/raw/results_2026/` (local, not committed, as they are AP's). "
            "Publicly, the Internet Archive's index (queried 4 November) holds captures of the national `progress.json` and "
            "`metadata.json` at 04:28, 17:02 and 20:03 UTC on 3 November (before polls closed) and one at 05:04 UTC on 4 November "
            "(election night), plus some per-state and per-race files; the index showed none later at the time of the query. The #24 note that a direct `curl` returned a "
            "stub is explained in `results/README.md`: the files are gzip bytes, not a stub. No new archive request was made; saving "
            "the feed through the Internet Archive while it still shows the election-night state is still open.")


# --------------------------------------------------------------------------- main
VARIANTS = {   # name: (description, bias, sd, poll averages)
    "h1a_bias_0": ("H1: generic-ballot bias set to 0, spread as v1", 0.0, None, "v1"),
    "h1b_raw_generic_ballot": ("H1: raw generic ballot as the House vote, no correction and no national spread", 0.0, 0.0, "v1"),
    "h6_late_polls": ("H6: race poll averages as of 3 November (look-ahead past the lock date)", None, None, "late"),
    "h1a_and_h6": ("H1 and H6 together: bias 0 and 3 November poll averages", 0.0, None, "late"),
    "h7_house_effects": ("H7: race poll averages with pollster house effects removed", None, None, "h7"),
    "h8_no_partisan": ("H8: race poll averages without partisan-sponsored polls", None, None, "h8"),
    "h7_and_h1a": ("H7 and H1 together: bias 0 and house-effect-adjusted poll averages", 0.0, None, "h7"),
    "h8_and_h1a": ("H8 and H1 together: bias 0 and poll averages without partisan-sponsored polls", 0.0, None, "h8"),
}


def compute(pull: str | None = None, fetch: bool = False) -> dict:
    res = results(pull)
    sf = scored_frame(res)
    fits = fitted()
    avgs = {"v1": polls.averages(YEAR, when=V1_CUTOFF)}
    base = rerun(fits, avgs["v1"])
    gap = reproduction_gap(write_tables(base, "v1_reproduced", avgs["v1"]))
    if gap > 0:
        raise SystemExit(f"the rerun does not reproduce forecasts/v1 (largest difference {gap}); stopping")
    late = fetch_late() if fetch else load_late()
    gb_late = generic_ballot_late() if fetch else None
    if late is not None:
        avgs["late"] = polls.averages(YEAR, late, when=LATE_CUTOFF)
    poll_rows = pd.read_parquet(OUT / "polls.parquet")
    effects, he_params = estimate_house_effects(house_effect_rows(poll_rows, V1_CUTOFF))
    avgs["h7"] = polls.averages(YEAR, adjust_polls(poll_rows, effects), when=V1_CUTOFF)
    avgs["h8"] = polls.averages(YEAR, drop_partisan(poll_rows), when=V1_CUTOFF)
    runs = {}
    out = {"label": "DIAGNOSTIC. Not part of v1's score (#15); v1 and the v1 tag are unchanged.",
           "issue": 24, "pull_id": res["pull_id"].iloc[0], "pulled_at": res["pulled_at"].iloc[0],
           "status": "provisional", "min_counted_for_vote_share": MIN_COUNTED,
           "reproduction": {"max_abs_difference_from_forecasts_v1": gap, "code": "src/ unchanged since tag v1 for every model module"},
           "variants": {"v1": {"description": "v1 as published (the score in #15)", **{"metrics": metrics(res)}}}}
    for name, (desc, bias, sd, which) in VARIANTS.items():
        if which not in avgs:
            out["variants"][name] = {"description": desc, "metrics": None, "note": "late poll averages not available"}
            continue
        r = rerun(fits, avgs[which], bias, sd)
        if name == "h8_no_partisan":
            runs[name] = r
        d = write_tables(r, name, avgs[which])
        out["variants"][name] = {"description": desc, "house_vote_mean": round(r["env"]["mean"], 4),
                                 "house_vote_sd": round(r["env"]["sd"], 4), "metrics": metrics(res, d)}
    detail = poll_detail(pd.read_parquet(OUT / "polls.parquet"), V1_CUTOFF)
    out["h2"] = h2(sf, detail, fits["polls"])
    out["h3"] = h3(sf, base, fits["polls"])
    out["h4"] = h4(sf, base)
    out["house_vote_so_far"] = house_vote_so_far(res)
    out["h5"] = {"status": "waiting", "reason": "counts are not near final",
                 **{k: out["house_vote_so_far"][k] for k in ("vote_weighted_pct_counted", "districts_below_95pct")}}
    out["h6"] = h6(sf, late) if late is not None else {"status": "not run", "reason": "no 3 November revisions saved"}
    out["h7"] = h7(sf, poll_rows, effects, he_params, avgs["v1"], avgs["h7"])
    out["h8"] = h8(sf, poll_rows, avgs["v1"], avgs["h8"], base, runs["h8_no_partisan"])
    effects.assign(label="DIAGNOSTIC").to_csv(DIAG / "house_effects.csv", index=False)
    if gb_late is None and (RAW_LATE).exists() and sorted(RAW_LATE.glob("house_2026_asof*")):
        gb_late = generic_ballot_late()
    out["generic_ballot_3_november"] = gb_late
    out["checks"] = checks(res)
    return out


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Election diagnostics for v1 (issue #24). DIAGNOSTIC ONLY.")
    ap.add_argument("--pull", help="pull_id in results/results_log.csv (default: the latest)")
    ap.add_argument("--fetch-late", action="store_true",
                    help="fetch the 3 November Wikipedia revisions (about 15 minutes at the API's pace)")
    a = ap.parse_args(argv)
    d = compute(a.pull, a.fetch_late)
    (RESULTS / "diagnostics.json").write_text(json.dumps(_clean(d), indent=1) + "\n")
    md = markdown(d)
    (RESULTS / "diagnostics.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()

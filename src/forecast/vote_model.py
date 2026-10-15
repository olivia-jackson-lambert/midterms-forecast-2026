"""Stage B: two-party vote share and win probability for every Senate and governor race.

On the logit scale, the Democratic share of the two-party vote in race r (state s, office o) is

    logit(share_r) = logit(house_T)                          national environment
                     + a_o + b_o * (logit(lean_s) - logit(pres_T))   state lean against the nation
                     + d_o * incumbency_r                     +1 Democratic-side incumbent, -1 Republican
                     + h_o * track_record_r                   the incumbent's last result against expectation
                     + q * fundraising_r                      Senate only: log ratio of receipts to 30 June
                     + region effect + state effect + race noise,

- lean_s, the turnout-first baseline: the state's last presidential two-party share with each
  county weighted by Stage A's simulated midterm turnout (forecast.turnout_model.lean_draws);
- pres_T: the national presidential two-party share at the last presidential election;
- house_T: the national House two-party share. In training it is the actual result; in a
  forecast it is drawn from forecast.generic_ballot.national_environment, whose bias and
  spread are estimated from earlier cycles only;
- track_record_r: for a running incumbent, their last result for this office minus what a uniform
  swing predicted then (the state's lean moved by that year's national House vote), on the logit
  scale, from the Democratic side. Zero for open seats and incumbents who have not run before.

  A symmetric version for every nominee is built but switched off (USE_NOMINEE_TRACK_RECORD).
  Each nominee's overperformance is taken in their most recent earlier statewide general
  election (Senate, governor or at-large House seat, 2010 onwards; forecast.races): their own
  side's two-party share against the same uniform-swing expectation, from their own side. Then

      track_record = dem_record - rep_record

  where each record is 0 for a nominee with no statewide history (or whose last race was not a
  Democrat-Republican contest). The parties are treated alike: swap them and the sign flips.
  Where the two nominees faced each other in that race (Maryland's governor in 2022), it counts
  once, not twice. With only the incumbent having a history it equals the incumbent feature; the
  addition is challengers (Sherrod Brown, Roy Cooper, Doug Jones, Mary Peltola). One coefficient
  per office covers incumbents and challengers: one or two training midterms cannot separate two. This
  design was fixed before testing and failed the pre-registered rule (see the flag below);
- a_o, b_o, d_o, h_o, and the spreads of the region, state and race terms are fitted in PyMC on past
  midterms (2018 for the 2022 backtest; 2018 and 2022 for 2026). The 2018 backtest has no
  earlier race data, so it runs on the priors alone.

Nothing here is tuned on the year being predicted. Races with no Democrat or independent
against a Republican are not modelled; races where an independent stands in for the
Democratic side (forecast.races) get extra race-level uncertainty.

    python -m forecast.vote_model
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pymc as pm
from scipy.special import expit, logit

from . import generic_ballot
from .ingest import OUT

SIMS = 20_000
SEED = 2026
OFFICES = ["SEN", "GOV"]
REGIONS = ["Northeast", "Midwest", "South", "West"]
REGION = {**{s: "Northeast" for s in "CT ME MA NH RI VT NJ NY PA".split()},
          **{s: "Midwest" for s in "IL IN MI OH WI IA KS MN MO NE ND SD".split()},
          **{s: "South" for s in "DE FL GA MD NC SC VA WV AL KY MS TN AR LA OK TX DC".split()},
          **{s: "West" for s in "AZ CO ID MT NV NM UT WY AK CA HI OR WA".split()}}
INDEPENDENT_EXTRA_SD = 0.25      # added race noise where an independent stands in for the Democratic side
FIRST_ROUND_FROM_COUNTY_FILES = {"2018-MS-SENS"}
# Off: in the 2022 backtest (trained on 2018) fundraising made vote-share error and Brier worse
# (3.72 v 3.64 points, 0.069 v 0.067), failing the rule set before testing. PLAN.md, Race Results.
USE_FUNDRAISING = False
# Off: the track record of both nominees, instead of the incumbent's alone. Rule, set before testing:
# keep it only if the 2022 backtest (trained on 2018) improves on BOTH Brier score and vote-share
# error against the incumbent-only feature (0.0666, 3.64 points). It made both worse (0.0748,
# 3.77 points), so it fails. See notes/challenger_track_record.md.
USE_NOMINEE_TRACK_RECORD = False
# Race-level polls blended on top of the fundamentals (forecast.polls). On: in the 2022 backtest
# (trained on 2018) they cut Brier from 0.067 to 0.031 and share error from 3.64 to 2.67 points,
# passing the rule set before testing (both must improve). notes/race_polls.md.
USE_POLLS = True
# Senate seats not up in 2026, by caucus (53 Republicans, 47 Democrats and independents now).
SENATE_NOW = {"R": 53, "D": 47}


# --------------------------------------------------------------------------- data
def _pres(year: int) -> tuple[pd.Series, float]:
    """State and national Democratic two-party share in the presidential election before `year`."""
    p = pd.read_parquet(OUT / "county_panel.parquet", columns=["year", "state_po", "dem", "rep"])
    p = p[p["year"] == year - 2]
    g = p.groupby("state_po")[["dem", "rep"]].sum()
    return g["dem"] / (g["dem"] + g["rep"]), float(p["dem"].sum() / (p["dem"].sum() + p["rep"].sum()))


def lean_draws(year: int) -> pd.DataFrame:
    """Turnout-weighted state leans (simulations x states) saved by Stage A."""
    return pd.read_parquet(OUT / f"lean_draws_{year}.parquet")


def actual_shares(year: int) -> pd.DataFrame:
    r = pd.read_parquet(OUT / "county_midterm_results.parquet")
    r = r[(r["year"] == year) & r["race"].isin(OFFICES)]
    g = r.groupby(["state_po", "race", "special"], as_index=False)[["dem", "rep"]].sum()
    g["actual"] = g["dem"] / (g["dem"] + g["rep"])
    return g.rename(columns={"race": "office"})[["state_po", "office", "special", "actual"]]


def frame(year: int) -> pd.DataFrame:
    """One row per modelled race: leans, incumbency and (for past years) the result."""
    races = pd.read_parquet(OUT / "races.parquet")
    f = races[(races["year"] == year) & (races["d_side"] != "not_two_party")].reset_index(drop=True)
    plain, nat = _pres(year)
    f["lean_plain"] = f["state_po"].map(plain)
    f["lean_turnout"] = f["state_po"].map(lean_draws(year).median())
    f["pres_nat"] = nat
    f["region"] = f["state_po"].map(REGION)
    f["office_i"] = f["office"].map({o: i for i, o in enumerate(OFFICES)})
    f["independent"] = f["d_side"].ne("democrat")
    f["track_record_incumbent"] = track_record(f, nominees=False)
    f["track_record_nominees"] = track_record(f, nominees=True)
    f["track_record"] = f["track_record_nominees" if USE_NOMINEE_TRACK_RECORD else "track_record_incumbent"]
    f["fundraising"] = fundraising(f, year)
    if year < 2026:
        # Race results: certified candidate percentages from forecast.races. (MIT's county files
        # miss counties in places, e.g. Indiana 2022 and Delaware 2018; tests compare the two.)
        f["actual"] = f["result_dem_2p"].where(~f["independent"])
        # Wikipedia lists only the 27 November runoff for Mississippi's 2018 special; every other
        # race is the November general (first round), so use the county files' first round here.
        first_round = f["race_id"].isin(FIRST_ROUND_FROM_COUNTY_FILES)
        if first_round.any():
            county = f.merge(actual_shares(year), on=["state_po", "office", "special"], how="left",
                             suffixes=("", "_county"))["actual_county"]
            f.loc[first_round, "actual"] = county[first_round].values
        f["house"] = float(generic_ballot.history().set_index("year").loc[year, "house_dem_2p"])
    return f.reset_index(drop=True)


def fundraising(f: pd.DataFrame, year: int) -> pd.Series:
    """Senate nominees' log receipts ratio to 30 June (forecast.fundraising); 0 for governors,
    or everywhere when USE_FUNDRAISING is off or the FEC data have not been downloaded."""
    from . import fundraising as fec
    if not USE_FUNDRAISING or not (fec.RAW_FEC / f"nominee_receipts_{year}.csv").exists():
        return pd.Series(0.0, index=f.index)
    return f["race_id"].map(fec.feature(year)).fillna(0.0).where(f["office"].eq("SEN"), 0.0)


def _expected_logit(year: int, state: str, cache: dict) -> float:
    """What a uniform swing predicts for the state in `year`: its presidential lean (that year's
    in a presidential year, the previous one otherwise) moved by that year's national House vote."""
    if "house" not in cache:
        cache["house"] = generic_ballot.house_vote().set_index("year")["house_dem_2p"]
    if year not in cache:
        cache[year] = _pres(year + 2 if year % 4 == 0 else year)
    lean, nat = cache[year]
    return float(logit(cache["house"][year]) + logit(lean[state]) - logit(nat))


def track_record(f: pd.DataFrame, nominees: bool = True) -> pd.Series:
    """Track record feature (logit, Democratic side); see the module docstring.

    nominees=False: the old feature, the running incumbent's last result for the same office.
    nominees=True: dem_record - rep_record over both sides' nominees, any statewide office."""
    out, cache = pd.Series(0.0, index=f.index), {}
    if not nominees or "dem_prev_dem_2p" not in f:
        for i, r in f[f["prev_dem_2p"].notna()].iterrows():
            out[i] = logit(r["prev_dem_2p"]) - _expected_logit(int(r["prev_year"]), r["state_po"], cache)
        return out
    for i, r in f.iterrows():
        rec = {}
        for side in ("dem", "rep"):
            if pd.isna(r[f"{side}_prev_dem_2p"]):
                continue
            resid = logit(r[f"{side}_prev_dem_2p"]) - _expected_logit(int(r[f"{side}_prev_year"]), r["state_po"], cache)
            rec[side] = resid if r[f"{side}_prev_side"] == "D" else -resid      # from the nominee's own side
        same = (len(rec) == 2 and r["dem_prev_year"] == r["rep_prev_year"]
                and r["dem_prev_office"] == r["rep_prev_office"])               # they faced each other
        out[i] = 0.5 * (rec["dem"] - rec["rep"]) if same else rec.get("dem", 0.0) - rec.get("rep", 0.0)
    return out


# --------------------------------------------------------------------------- fit
def fit(train: list[pd.DataFrame], lean: str = "lean_turnout", draws: int = 1000) -> dict:
    """Posterior draws (or prior draws when `train` is empty) of the race-model parameters."""
    with pm.Model():
        a = pm.Normal("a", 0.0, 0.15, shape=2)
        b = pm.Normal("b", 1.0, 0.3, shape=2)
        d = pm.Normal("d", 0.0, 0.2, shape=2)
        h = pm.Normal("h", 0.0, 0.5, shape=2)
        q = pm.Normal("q", 0.0, 0.1)
        sigma = pm.HalfNormal("sigma", 0.3, shape=2)
        # Regional and same-state errors are barely identified by one or two midterms, so their
        # priors are set to typical sizes (a few points) rather than left wide.
        sigma_state = pm.HalfNormal("sigma_state", 0.1)
        sigma_region = pm.HalfNormal("sigma_region", 0.05)
        if train:
            t = pd.concat(train, ignore_index=True)
            t = t[t["actual"].notna() & ~t["independent"]]
            o = t["office_i"].to_numpy()
            x = (logit(t[lean]) - logit(t["pres_nat"])).to_numpy()
            st_idx, _ = pd.factorize(t["year"].astype(str) + t["state_po"])
            rg_idx, _ = pd.factorize(t["year"].astype(str) + t["region"])
            u = pm.Normal("u", 0, 1, shape=int(st_idx.max()) + 1)
            g = pm.Normal("g", 0, 1, shape=int(rg_idx.max()) + 1)
            mu = (logit(t["house"].to_numpy()) + a[o] + b[o] * x + d[o] * t["incumbency"].to_numpy()
                  + h[o] * t["track_record"].to_numpy() + q * t["fundraising"].to_numpy()
                  + sigma_state * u[st_idx] + sigma_region * g[rg_idx])
            pm.Normal("y", mu, sigma[o], observed=logit(t["actual"].to_numpy()))
            idata = pm.sample(draws, tune=2000, chains=4, target_accept=0.99, random_seed=SEED, progressbar=False)
            post = idata.posterior.to_dataset() if hasattr(idata.posterior, "to_dataset") else idata.posterior
            n_train = len(t)
        else:
            idata = pm.sample_prior_predictive(draws * 4, random_seed=SEED)
            post = idata.prior.to_dataset() if hasattr(idata.prior, "to_dataset") else idata.prior
            n_train = 0
    post = post.stack(s=("chain", "draw"))
    names = ["a", "b", "d", "h", "q", "sigma", "sigma_state", "sigma_region"]
    params = {n: np.asarray(post[n].values).T if post[n].ndim > 1 else np.asarray(post[n].values) for n in names}
    params.update(n_train=n_train, lean=lean)
    params["summary"] = pd.DataFrame({n + (f"[{o}]" if params[n].ndim > 1 else ""): v
                                      for n in names
                                      for o, v in (zip(OFFICES, params[n].T) if params[n].ndim > 1 else [("", params[n])])}
                                     ).describe(percentiles=[0.055, 0.945]).T[["mean", "5.5%", "94.5%"]]
    return params


# --------------------------------------------------------------------------- simulate
def simulate(f: pd.DataFrame, params: dict, year: int, sims: int = SIMS,
             rng: np.random.Generator | None = None, turnout_weighted: bool = True) -> np.ndarray:
    """Democratic two-party share draws, sims x races, with shared national, regional and
    state errors, and Stage A turnout uncertainty through the lean draws."""
    rng = rng or np.random.default_rng(SEED + year)
    env = generic_ballot.national_environment(year)
    house = env["mean"] + env["sd"] * rng.standard_t(env["df"], sims)
    house = np.clip(house, 0.3, 0.7)
    n_post = len(params["sigma_state"])
    k = rng.integers(0, n_post, sims)
    o = f["office_i"].to_numpy()
    if turnout_weighted and params["lean"] == "lean_turnout":
        ld = lean_draws(year)
        lean = ld[f["state_po"]].to_numpy()[rng.integers(0, len(ld), sims)]
    else:
        lean = np.broadcast_to(f[params["lean"]].to_numpy(), (sims, len(f)))
    x = logit(lean) - logit(f["pres_nat"].to_numpy())[None, :]
    st_idx, st_names = pd.factorize(f["state_po"])
    rg_idx = f["region"].map({r: i for i, r in enumerate(REGIONS)}).to_numpy()
    u = params["sigma_state"][k, None] * rng.standard_normal((sims, len(st_names)))
    g = params["sigma_region"][k, None] * rng.standard_normal((sims, len(REGIONS)))
    sd = params["sigma"][k][:, o]
    sd = np.sqrt(sd ** 2 + np.where(f["independent"].to_numpy(), INDEPENDENT_EXTRA_SD ** 2, 0.0)[None, :])
    eps = sd * rng.standard_normal((sims, len(f)))
    lg = (logit(house)[:, None] + params["a"][k][:, o] + params["b"][k][:, o] * x
          + params["d"][k][:, o] * f["incumbency"].to_numpy()[None, :]
          + params["h"][k][:, o] * f["track_record"].to_numpy()[None, :]
          + params["q"][k][:, None] * f["fundraising"].to_numpy()[None, :] + u[:, st_idx] + g[:, rg_idx] + eps)
    return expit(lg).astype(np.float32)


def summarise(f: pd.DataFrame, sims: np.ndarray) -> pd.DataFrame:
    q = np.quantile(sims, [0.1, 0.5, 0.9], axis=0)
    cols = ["race_id", "year", "state_po", "office", "special", "incumbent", "incumbent_party", "open_seat",
            "dem_candidate", "rep_candidate", "d_side", "lean_plain", "lean_turnout", "track_record", "fundraising"]
    out = f[[c for c in cols if c in f]].copy()
    out["lo80"], out["median"], out["hi80"] = q
    out["p_dem_win"] = (sims > 0.5).mean(axis=0)
    if "actual" in f:
        out["actual"] = f["actual"].values
    return out


def senate_seats(f: pd.DataFrame, sims: np.ndarray) -> pd.DataFrame:
    """Distribution of Democratic-caucus Senate seats after the election.

    Seats won by an independent challenger (Nebraska, Idaho, South Dakota in 2026) are not
    counted as Democratic: they have not said they would caucus with either party. The
    `independent_seats` column counts them.
    """
    sen = f["office"].eq("SEN").to_numpy()
    up_d = int((sen & f["incumbent_party"].isin(["D", "I"]).to_numpy()).sum())
    not_up_d = SENATE_NOW["D"] - up_d
    dem_races = sen & ~f["independent"].to_numpy()
    ind_races = sen & f["independent"].to_numpy()
    seats = not_up_d + (sims[:, dem_races] > 0.5).sum(1)
    ind = (sims[:, ind_races] > 0.5).sum(1)
    d = pd.DataFrame({"dem_seats": seats, "independent_seats": ind})
    return d.value_counts(normalize=True).rename("probability").reset_index().sort_values(["dem_seats", "independent_seats"])


def run(year: int, train_years: list[int], lean: str = "lean_turnout", sims: int = SIMS,
        params: dict | None = None) -> tuple[pd.DataFrame, dict]:
    params = params or fit([frame(y) for y in train_years], lean=lean)
    f = frame(year)
    s = simulate(f, params, year, sims)
    fundamentals = summarise(f, s)
    poll_info = None
    if USE_POLLS:
        from . import polls
        s, poll_info = polls.blend(f, s, year, train_years)
    out = summarise(f, s)
    # Keep the fundamentals-only forecast alongside, so readers can see what polls changed.
    out["fundamentals_median"] = fundamentals["median"].values
    out["fundamentals_p_dem_win"] = fundamentals["p_dem_win"].values
    return out, {"params": params, "sims": s, "frame": f, "polls": poll_info}


def main() -> None:
    out, info = run(2026, [2018, 2022])
    out.to_parquet(OUT / "vote_share_2026.parquet", index=False)
    seats = senate_seats(info["frame"], info["sims"])
    seats.to_csv(OUT / "senate_seats_2026.csv", index=False)
    info["params"]["summary"].to_csv(OUT / "vote_model_parameters.csv")
    env = generic_ballot.national_environment(2026)
    print(f"national House vote, Democratic two-party: {env['mean']:.3f} (sd {env['sd']:.3f})")
    print(info["params"]["summary"].round(3).to_string())
    p_control = seats.loc[seats["dem_seats"] >= 51, "probability"].sum()
    p_rep = seats.loc[53 + 47 - seats["dem_seats"] - seats["independent_seats"] >= 50, "probability"].sum()
    by_d = seats.groupby("dem_seats")["probability"].sum()
    print(f"Democratic-caucus Senate seats: median {np.interp(0.5, by_d.cumsum(), by_d.index):.0f}; "
          f"P(51+) {p_control:.2f}; P(Republicans hold 50+) {p_rep:.2f}")
    print(out.sort_values("p_dem_win")[["race_id", "dem_candidate", "rep_candidate", "median", "lo80", "hi80",
                                       "p_dem_win"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()

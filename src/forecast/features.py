"""County features for the turnout model (Stage A).

One frame per target midterm T: the anchor (turnout at the last midterm, T-4), the last
presidential turnout (T-2), county demographics and ex-ante state race features. Everything
in a frame is known before 1 October of year T, except the target itself.

Exception, documented in PLAN.md: demographics come from the ACS 2020-2024 release for every
year, because the table-based summary files only start with the 2021 vintage. They change
slowly and contain no election results.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .ingest import OUT

# Statewide races on the ballot (Senate including specials, governor). Sources: official
# results for 2014-2022; the 2026 lists are the scheduled races (Senate class 2 plus the
# Florida and Ohio specials; 36 governorships).
GOV = "AL AK AZ AR CA CO CT FL GA HI ID IL IA KS ME MD MA MI MN NE NV NH NM NY OH OK OR PA RI SC SD TN TX VT WI WY"
SENATE = {
    2014: "AL AK AR CO DE GA ID IL IA KS KY LA ME MA MI MN MS MT NE NH NJ NM NC OK OR RI SC SD TN TX VA WV WY HI",
    2018: "AZ CA CT DE FL HI IN ME MD MA MI MN MS MO MT NE NV NJ NM NY ND OH PA RI TN TX UT VT VA WA WV WI WY",
    2022: "AL AK AZ AR CA CO CT FL GA HI ID IL IN IA KS KY LA MD MO NV NH NY NC ND OH OK OR PA SC SD UT VT WA WI",
    2026: "AL AK AR CO DE GA ID IL IA KS KY LA ME MA MI MN MS MT NE NH NJ NM NC OK OR RI SC SD TN TX VA WV WY FL OH",
}
GOVERNOR = {y: GOV for y in (2014, 2018, 2022, 2026)}
# Party of the president at each midterm: the other party's voters tend to turn out more.
PRESIDENT = {2014: "D", 2018: "R", 2022: "D", 2026: "R"}

DEMOGRAPHICS = ["share_ba_plus", "share_18_29", "share_65p", "share_hispanic", "share_black_nh",
                "log_density", "log_income"]
# Governor races are on the same 36 states' ballots every midterm, so only Senate races and
# closeness change between cycles.
STATE_FEATURES = ["d_senate", "d_close"]


def logit(p):
    p = np.clip(p, 0.02, 0.98)
    return np.log(p / (1 - p))


def state_races(year: int, pres_margin: pd.Series) -> pd.DataFrame:
    """Per state: Senate race on the ballot, governor race, and closeness of the top races,
    measured ex ante by the state's last presidential margin (1 at a tie, 0 at 20+ points)."""
    states = pres_margin.index
    sen = states.isin(SENATE[year].split()).astype(float)
    gov = states.isin(GOVERNOR[year].split()).astype(float)
    close = np.clip(1 - pres_margin.abs() / 0.20, 0, 1) * np.maximum(sen, gov)
    return pd.DataFrame({"senate": sen, "governor": gov, "close": close}, index=states)


def _demographics() -> pd.DataFrame:
    p = pd.read_parquet(OUT / "county_panel.parquet")
    d = p[p["year"] == 2024].set_index("unit_fips")
    d = d.assign(log_income=np.log(d["median_income"]))[DEMOGRAPHICS]
    return (d - d.mean()) / d.std()


def frame(target: int) -> pd.DataFrame:
    """County frame for target midterm `target` (2018, 2022 or 2026)."""
    mid = pd.read_parquet(OUT / "county_midterm_turnout.parquet")
    pres = pd.read_parquet(OUT / "county_panel.parquet")
    m = mid.pivot(index="unit_fips", columns="year", values="turnout")
    src = mid.pivot(index="unit_fips", columns="year", values="source")
    cvap = mid.pivot(index="unit_fips", columns="year", values="cvap")
    pt = pres.pivot(index="unit_fips", columns="year", values="turnout")
    state = pres[pres["year"] == 2024].set_index("unit_fips")["state_po"]

    f = pd.DataFrame({"state_po": state})
    f["anchor"] = logit(m[target - 4])
    f["pres"] = logit(pt[target - 2])
    f["pres_minus_anchor"] = f["pres"] - f["anchor"]
    f["cvap"] = cvap[target] if target in cvap else cvap[target - 4]
    f["anchor_imputed"] = src[target - 4].eq("imputed")
    if target in m:
        f["actual"] = m[target]
        f["y"] = logit(m[target]) - f["anchor"]
        f["train_ok"] = ~f["anchor_imputed"] & src[target].ne("imputed")
    f = f.join(_demographics())

    # State race features, as changes from the last midterm (the model is in changes).
    by_state = pres[pres["year"] == target - 2].groupby("state_po")[["dem", "rep"]].sum()
    margin_now = (by_state["dem"] - by_state["rep"]) / (by_state["dem"] + by_state["rep"])
    prev = pres[pres["year"] == target - 6].groupby("state_po")[["dem", "rep"]].sum()
    margin_prev = (prev["dem"] - prev["rep"]) / (prev["dem"] + prev["rep"])
    now, before = state_races(target, margin_now), state_races(target - 4, margin_prev)
    sf = pd.DataFrame({"d_senate": now["senate"] - before["senate"],
                       "d_governor": now["governor"] - before["governor"],
                       "d_close": now["close"] - before["close"]})
    f = f.join(sf, on="state_po")
    # Out-party effect: county Democratic lean (last presidential two-party share minus the
    # national share) times the change in which party is out of power since the last midterm:
    # +lean when Democrats became the out-party (2018, 2026), -lean when Republicans did (2022).
    # Added after the first backtest run; see PLAN.md.
    last = pres[pres["year"] == target - 2].set_index("unit_fips")
    nat = last["dem"].sum() / (last["dem"].sum() + last["rep"].sum())
    out_sign = {"D": -1, "R": 1}
    f["out_party_lean"] = (last["dem_2p"] - nat) * (out_sign[PRESIDENT[target]] - out_sign[PRESIDENT[target - 4]]) / 2
    f["year"] = target
    return f.reset_index()

"""Checks on the release tables. Needs the pipeline's processed outputs:

    cd src && python -m forecast.pipeline
    cd .. && python -m pytest tests/test_release.py

The release is written to a temporary folder, never to forecasts/.
"""
import hashlib
import json

import pandas as pd
import pytest

pytest.importorskip("pymc")
from forecast.ingest import OUT  # noqa: E402
from forecast.pipeline import plan  # noqa: E402

NEEDED = ["turnout_2026.parquet", "turnout_2026_states.parquet", "turnout_2026_national.csv",
          "turnout_2026_early_vote.csv", "county_midterm_turnout.parquet", "vote_share_2026.parquet",
          "senate_seats_2026.csv", "governor_seats_2026.csv", "backtest_turnout.csv", "backtest_races.csv",
          "generic_ballot_history.csv", "house_2026.parquet", "house_seats_2026.csv", "poll_averages.csv",
          "polls.parquet"]
pytestmark = pytest.mark.skipif(not all((OUT / f).exists() for f in NEEDED),
                                reason="run the pipeline first (forecast.turnout_model, forecast.vote_model)")


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    from forecast.release import release
    return release("v1", draft=True, root=tmp_path_factory.mktemp("forecasts"))


def read(folder, name):
    return pd.read_csv(folder / name, dtype={"unit_fips": str})


def test_draft_goes_under_draft_folder(folder):
    assert folder.parent.name == "_draft" and folder.name == "v1"


def test_counties(folder):
    c = read(folder, "turnout_counties.csv")
    assert list(c.columns) == ["unit_fips", "county", "state", "turnout_2022", "turnout_2026_median",
                               "turnout_2026_lo80", "turnout_2026_hi80", "turnout_2026_lo80_county",
                               "turnout_2026_hi80_county", "cvap"]
    assert len(c) == 3104 and c["unit_fips"].is_unique
    assert c["county"].notna().all() and (c["county"] != "").all()
    assert c.loc[c["unit_fips"] == "29095", "county"].iloc[0].startswith("Jackson, Clay")
    for lo, mid, hi in [("turnout_2026_lo80", "turnout_2026_median", "turnout_2026_hi80"),
                        ("turnout_2026_lo80_county", "turnout_2026_median", "turnout_2026_hi80_county")]:
        assert (c[lo] <= c[mid]).all() and (c[mid] <= c[hi]).all()
    assert c["turnout_2026_median"].between(0, 1).all() and (c["cvap"] > 0).all()
    assert c["turnout_2022"].notna().mean() > 0.99


def test_states(folder):
    s = read(folder, "turnout_states.csv")
    assert len(s) == 51 and "DC" in set(s["state"]) and s["state"].is_unique
    assert s["turnout_2022"].notna().all()
    assert (s["turnout_2026_lo80"] <= s["turnout_2026_median"]).all()
    assert (s["turnout_2026_median"] <= s["turnout_2026_hi80"]).all()
    assert (s["turnout_2026_lo80_state"] <= s["turnout_2026_hi80_state"]).all()


def test_national(folder):
    n = read(folder, "national.csv")
    assert len(n) == 1
    r = n.iloc[0]
    assert r["turnout_2026_lo80"] <= r["turnout_2026_median"] <= r["turnout_2026_hi80"]
    assert r["house_dem_2p_lo80"] <= r["house_dem_2p_mean"] <= r["house_dem_2p_hi80"]
    assert 0.4 < r["generic_ballot_dem_2p"] < 0.6
    pd.Timestamp(r["generic_ballot_as_of"])


def test_races(folder):
    r = read(folder, "races.csv")
    assert len(r) == 71 and r["race_id"].is_unique
    assert set(r["office"]) == {"senate", "governor"}
    assert r["race_id"].str.startswith("2026-").all()
    assert r["p_dem_win"].between(0, 1).all()
    assert (r["dem_share_lo80"] <= r["dem_share_median"]).all()
    assert (r["dem_share_median"] <= r["dem_share_hi80"]).all()
    assert r["dem_share_median"].between(0, 1).all()
    assert r[["dem_candidate", "rep_candidate", "d_side", "state"]].notna().all().all()
    assert "poll_avg" in r and "n_polls" in r
    assert (r["n_polls"] >= 0).all() and r["poll_avg"].dropna().between(0, 1).all()
    assert r["poll_avg"].isna().equals(r["n_polls"] == 0)
    # The forecast before polls, published alongside so readers can see what polls changed.
    assert r["fundamentals_median"].between(0, 1).all()
    assert r["fundamentals_p_dem_win"].between(0, 1).all()


def test_house_districts(folder):
    h = read(folder, "house_districts.csv")
    assert len(h) == 435 and h["cd"].is_unique and h["state"].notna().all()
    p = h[["p_dem_win", "p_rep_win", "p_ind_win"]]
    assert ((p >= 0) & (p <= 1)).all().all()
    assert ((p.sum(axis=1) - 1).abs() <= 0.002).all()
    m = h[h["dem_share_median"].notna()]
    assert len(m) > 400
    assert (m["dem_share_lo80"] <= m["dem_share_median"]).all() and (m["dem_share_median"] <= m["dem_share_hi80"]).all()
    assert m["dem_share_median"].between(0, 1).all()
    held = h[h["dem_share_median"].isna()]
    assert held["certain_hold_party"].isin(["D", "R"]).all() and not held["contested"].any()
    assert h.loc[h["dem_share_median"].notna(), "certain_hold_party"].isna().all()
    assert h["presidential_lean_dem_2p"].between(0, 1).all()


def test_house_seats(folder):
    s = read(folder, "house_seats.csv")
    assert list(s.columns) == ["dem_seats", "rep_seats", "independent_seats", "probability"]
    assert ((s["dem_seats"] + s["rep_seats"] + s["independent_seats"]) == 435).all()
    assert s["probability"].between(0, 1).all() and abs(s["probability"].sum() - 1) < 0.01
    assert (s["probability"].round(5) == s["probability"]).all()
    assert abs(s["probability"].sum() - 1) < 1e-6         # exact: multiples of 1/20,000


def test_senate_seats(folder):
    s = read(folder, "senate_seats.csv")
    assert list(s.columns) == ["dem_seats", "independent_seats", "probability"]
    assert s["probability"].between(0, 1).all()
    assert abs(s["probability"].sum() - 1) < 0.01


def test_governor_seats(folder):
    s = read(folder, "governor_seats.csv")
    assert list(s.columns) == ["dem_seats", "independent_seats", "probability"]
    assert s["dem_seats"].between(6, 42).all()        # 6 Democrats not up; 36 races
    assert abs(s["probability"].sum() - 1) < 0.01


def test_backtests(folder):
    b = read(folder, "backtests.csv")
    assert list(b.columns) == ["backtest", "year", "variant", "trained_on", "metric", "value"]
    assert {"turnout", "races"} <= set(b["backtest"]) <= {"turnout", "races", "house"}
    assert set(b["year"]) == {2018, 2022}
    assert {"model", "no_polls"} <= set(b.loc[b["backtest"] == "races", "variant"])
    if (OUT / "backtest_house.csv").exists():
        assert "house" in set(b["backtest"])
    assert b["value"].notna().all()
    assert not b.duplicated(["backtest", "year", "variant", "metric"]).any()


def test_rounding(folder):
    r = (folder / "races.csv").read_text()
    c = read(folder, "turnout_counties.csv")
    assert (c["turnout_2026_median"].round(4) == c["turnout_2026_median"]).all()
    assert (read(folder, "races.csv")["p_dem_win"].round(3) == read(folder, "races.csv")["p_dem_win"]).all()
    assert r.splitlines()[0].islower()      # plain snake_case headers


def test_manifest(folder):
    m = json.loads((folder / "manifest.json").read_text())
    assert m["version"] == "v1" and m["draft"] is True
    assert pd.Timestamp(m["created_utc"]).tzinfo is not None
    assert m["simulations"]["turnout"] > 0 and m["simulations"]["vote"] > 0
    assert set(m["inputs"]) >= {"races_wikipedia_modified_utc", "generic_ballot_as_of",
                                "house_wikipedia_fetched", "latest_poll_end_date"}
    pd.Timestamp(m["inputs"]["house_wikipedia_fetched"])
    pd.Timestamp(m["inputs"]["latest_poll_end_date"])
    assert m["simulations"]["house"] > 0
    assert "git_commit" in m and "git_working_tree_clean" in m
    files = {p.name for p in folder.iterdir()} - {"manifest.json"}
    assert set(m["sha256"]) == files == {"turnout_counties.csv", "turnout_states.csv", "national.csv",
                                         "races.csv", "senate_seats.csv", "governor_seats.csv", "house_districts.csv",
                                         "house_seats.csv", "backtests.csv"}
    for name, digest in m["sha256"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest


def test_pipeline_order():
    names = [n for n, _ in plan(refresh=True)]
    assert names == ["ingest", "races", "midterms", "generic_ballot", "polls", "backtest", "turnout_model", "vote_model",
                     "house"]
    assert dict(plan(refresh=True))["races"] == {"refresh": True}
    assert dict(plan(refresh=True))["generic_ballot"] == {"refresh": True}
    assert dict(plan(refresh=True))["house"] == {"refresh": True}
    assert dict(plan())["races"] == {} and dict(plan())["house"] == {}
    assert "backtest" not in [n for n, _ in plan(skip_backtests=True)]

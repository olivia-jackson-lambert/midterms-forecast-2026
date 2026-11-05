"""Hand-checkable cases for the election diagnostics (forecast.diagnostics, issue #24)."""
import numpy as np
import pandas as pd
import pytest
from scipy import stats
from scipy.special import logit

from forecast import diagnostics as dg, generic_ballot


def test_poll_buckets():
    assert [dg.poll_bucket(n) for n in (0, np.nan, 1, 4, 5, 12)] == ["0", "0", "1-4", "1-4", "5+", "5+"]


def test_partisan_labels_follow_wikipedia_sponsor_marks():
    assert dg.partisan_label("Cygnal (R)") == "R"
    assert dg.partisan_label("Public Policy Polling (D-End Citizens United)") == "D"
    assert dg.partisan_label("Impact Research (D)/Fabrizio Ward (R)") in ("D", "R")
    assert dg.partisan_label("Emerson College") == ""
    assert dg.partisan_label("Marist (Dartmouth)") == ""          # a word starting with D is not a label


def test_sd_for_percentile_by_hand():
    # Deviations uniform on -10..10: the 90th percentile is 8, so a realised 4 sits at the 70th and
    # needs no widening (k = 0.5); a realised 16 needs the spread doubled.
    dev = np.linspace(-10, 10, 100_001)
    lo = dg.sd_for_percentile(4.0, dev)
    assert lo["q_simulated"] == pytest.approx(8.0, abs=1e-3)
    assert lo["percentile_realised"] == pytest.approx(0.7, abs=1e-3)
    assert lo["scale_needed"] == pytest.approx(0.5, abs=1e-3)
    hi = dg.sd_for_percentile(16.0, dev)
    assert hi["scale_needed"] == pytest.approx(2.0, abs=1e-3)
    assert hi["sd_needed"] == pytest.approx(2 * dev.std(), rel=1e-3)
    assert hi["percentile_realised"] == 1.0


def test_polls_only_uses_v1s_error_variances():
    errors = {"s_nat": np.array([0.03, 0.04]), "s_floor": np.array([0.05]), "s_poll": np.array([0.10])}
    po = dg.polls_only([0.5, 0.55], [4.0, 1.0], errors)
    sd0 = np.sqrt((0.03 ** 2 + 0.04 ** 2) / 2 + 0.05 ** 2 + 0.10 ** 2 / 4)
    assert po["sd_logit"][0] == pytest.approx(sd0)
    assert po["median"][0] == pytest.approx(0.5) and po["p_dem_win"][0] == pytest.approx(0.5)
    assert po["median"][1] == pytest.approx(0.55)
    assert po["p_dem_win"][1] == pytest.approx(stats.norm.cdf(logit(0.55) / po["sd_logit"][1]))
    assert (po["lo80"] < po["median"]).all() and (po["hi80"] > po["median"]).all()


def test_national_override_changes_only_bias_and_spread_and_restores():
    hist = pd.DataFrame({"year": [2018, 2022, 2026], "gb_dem_2p": [0.55, 0.51, 0.54],
                         "house_dem_2p": [0.54, 0.49, np.nan]})
    before = generic_ballot.national_environment(2026, hist)
    assert before["bias"] == pytest.approx(-0.015)
    with dg.national_override(bias=0.0):
        e = generic_ballot.national_environment(2026, hist)
        assert e["mean"] == pytest.approx(0.54) and e["sd"] == pytest.approx(before["sd"])
    with dg.national_override(bias=0.0, sd=0.0):
        assert generic_ballot.national_environment(2026, hist)["sd"] == 0.0
    assert generic_ballot.national_environment(2026, hist) == before          # restored


def test_error_summary():
    s = dg._err_summary([1.0, -1.0, 3.0, np.nan])
    assert s == {"n": 3, "mean": 1.0, "sd": 2.0, "mae": pytest.approx(5 / 3, abs=0.01),
                 "rmse": pytest.approx(np.sqrt(11 / 3), abs=0.01)}
    assert dg._err_summary([])["n"] == 0


# --------------------------------------------------------------------------- through time (issue #29)
import json
from pathlib import Path

from forecast import through_time as tt


def test_national_override_takes_a_dated_generic_ballot():
    hist = pd.DataFrame({"year": [2018, 2022, 2026], "gb_dem_2p": [0.55, 0.51, 0.54],
                         "house_dem_2p": [0.54, 0.49, np.nan]})
    before = generic_ballot.national_environment(2026, hist)
    with dg.national_override(gb=0.52):
        e = generic_ballot.national_environment(2026, hist)
        assert e["gb_dem_2p"] == 0.52 and e["bias"] == pytest.approx(-0.015)
        assert e["mean"] == pytest.approx(0.505) and e["sd"] == pytest.approx(before["sd"])
    with dg.national_override(bias=0.0, gb=0.52):
        assert generic_ballot.national_environment(2026, hist)["mean"] == pytest.approx(0.52)
    assert generic_ballot.national_environment(2026, hist) == before


def test_seat_summary_by_hand():
    # Governors: 24, 26 or 27 Democratic seats with probabilities 0.3, 0.5, 0.2, and one independent
    # seat in the 26 case: Democrats hold 26+ in 0.7; Republicans hold 50 - 24 = 26 in 0.3.
    dist = pd.DataFrame({"dem_seats": [24, 26, 27], "independent_seats": [0, 1, 0], "probability": [0.3, 0.5, 0.2]})
    s = tt.seat_summary(dist, 50, 26)
    assert s["dem_control"] == pytest.approx(0.7) and s["rep_control"] == pytest.approx(0.3)
    assert (s["dem_seats_lo80"], s["dem_seats_median"], s["dem_seats_hi80"]) == (24, 26, 27)


def test_senate_control_needs_51_for_democrats_and_50_for_republicans():
    dist = pd.DataFrame({"dem_seats": [49, 50, 51], "independent_seats": [0, 0, 0], "probability": [0.2, 0.3, 0.5]})
    s = tt._senate_summary(dist)
    assert s["dem_control"] == pytest.approx(0.5)            # 51 only
    assert s["rep_control"] == pytest.approx(0.5)            # 49 or 50 Democratic seats leave 51 or 50


def test_revision_cache_reuses_a_revision_saved_for_another_date(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(dg.polls, "revision_as_of", lambda page, when: 111)
    monkeypatch.setattr(dg.polls, "_api", lambda params: calls.append(params) or {"parse": {"text": "<p>x</p>"}})
    html, rev = dg._revision_html(tmp_path, "2026-XX-SEN", "Page", "2026-09-01T23:59:59Z")
    assert (html, rev, len(calls)) == ("<p>x</p>", 111, 1)
    html, rev = dg._revision_html(tmp_path, "2026-XX-SEN", "Page", "2026-09-15T23:59:59Z")
    assert (html, rev, len(calls)) == ("<p>x</p>", 111, 1)     # same revision: no second parse request
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-XX-SEN_asof2026-09-01_rev111.html",
                                                         "2026-XX-SEN_asof2026-09-15_rev111.html"]


def test_write_section_replaces_and_keeps_files_last(tmp_path):
    p = tmp_path / "d.md"
    p.write_text("# T\n\n## H6\n\ntext\n\n## Files\n\n- a\n")
    tt.write_section("## Through Time\n\nfirst\n", p)
    tt.write_section("## Through Time\n\nsecond\n", p)
    t = p.read_text()
    assert t.count("## Through Time") == 1 and "second" in t and "first" not in t
    assert t.index("## H6") < t.index("## Through Time") < t.index("## Files")


THROUGH_TIME = Path(__file__).resolve().parents[1] / "results" / "through_time.json"


@pytest.mark.skipif(not THROUGH_TIME.exists(), reason="through_time.json not written yet")
def test_through_time_file():
    d = json.loads(THROUGH_TIME.read_text())
    assert d["status"] == "provisional" and d["label"].startswith("DIAGNOSTIC")
    assert d["reproduction"]["max_abs_difference_tables"] == 0 and d["reproduction"]["max_abs_difference_seats"] == 0
    rows = d["rows"]
    assert {(r["date"], r["variant"]) for r in rows} == {(x, v) for x in tt.DATES for v in tt.VARIANTS}
    assert all(r["label"] == "DIAGNOSTIC" and r["pull_id"] == d["pull_id"] for r in rows)
    v1 = next(r for r in rows if r["date"] == tt.V1_DATE and r["variant"] == "v1_as_built")
    assert v1["scores"] == d["v1_as_published"]["scores"]      # the 22 October rerun is v1
    for r in rows:
        if r["reconstructed"]:
            c = r["chances"]
            assert 0 <= c["senate"]["dem_control"] + c["senate"]["rep_control"] <= 1.0001
            assert c["house"]["dem_seats_lo80"] <= c["house"]["dem_seats_median"] <= c["house"]["dem_seats_hi80"]
        else:
            assert r["chances"] is None and r["note"]


# --------------------------------------------------------------------------- H7 and H8: poll adjustments
def test_he_key_tidies_only_the_obvious():
    assert dg.he_key("The Trafalgar Group (R)") == dg.he_key("Trafalgar Group") == "trafalgar group"
    assert dg.he_key("The Glengariff Group, Inc.") == "glengariff group"
    assert dg.he_key("Siena College / NYT") == "siena college/nyt"
    assert dg.he_key("Marist College") != dg.he_key("Marist University")          # not harmonised further
    assert dg.display_name("Cygnal (R)") == "Cygnal"


def test_ridge_fit_by_hand():
    # Two races, each polled by A and B; A is 2 points above B in both. By symmetry h_A = -h_B and
    # each race effect is the race mean, so h_A = (0.01 + 0.01) / (2 + lambda).
    y = np.array([0.52, 0.50, 0.56, 0.54])
    race, pol = np.array([0, 0, 1, 1]), np.array([0, 1, 0, 1])
    for lam in (0.0, 1.0, 4.0):
        a, h = dg._ridge_fit(y, race, pol, np.array([2.0, 2.0]), lam)
        assert h[0] == pytest.approx(0.02 / (2 + lam)) and h[1] == pytest.approx(-0.02 / (2 + lam))
        assert a == pytest.approx([0.51, 0.55])


def _synthetic(n_races=40, seed=0):
    rng = np.random.default_rng(seed)
    lean = {"lefty": 0.03, "middle": 0.0, "righty": -0.03, "rare": 0.03}
    rows = []
    for r in range(n_races):
        truth = rng.uniform(0.4, 0.6)
        for p in ("lefty", "middle", "righty") + (("rare",) if r == 0 else ()):
            rows.append({"he_key": p, "race_id": f"R{r}", "share": truth + lean[p] + rng.normal(0, 0.005),
                         "pollster": p, "year": 2026})
    rows.append({"he_key": "alone", "race_id": "SOLO", "share": 0.7, "pollster": "alone", "year": 2026})
    return pd.DataFrame(rows)


def test_house_effects_recover_leans_and_shrink_small_samples():
    eff, par = dg.estimate_house_effects(_synthetic())
    e = eff.set_index("he_key")
    assert "alone" not in e.index                       # a race polled by one pollster says nothing
    # Only differences between pollsters are identified; the zero is the average pollster, each
    # pollster counted once, so the effects sum to 0.
    assert e["effect"].sum() == pytest.approx(0, abs=1e-6)
    assert e.loc["lefty", "effect"] - e.loc["middle", "effect"] == pytest.approx(0.03, abs=0.003)
    assert e.loc["middle", "effect"] - e.loc["righty", "effect"] == pytest.approx(0.03, abs=0.003)
    # Same true lean, one race: pulled toward 0 by n / (n + lambda).
    assert 0 < e.loc["rare", "effect"] < e.loc["rare", "raw"]
    assert e.loc["rare", "shrink"] == pytest.approx(1 / (1 + par["lambda"]))
    assert e.loc["lefty", "shrink"] > e.loc["rare", "shrink"]


def test_house_effect_rows_never_use_polls_after_the_cutoff():
    p = pd.DataFrame({"pollster": ["A", "A", "B"], "race_id": ["X", "X", "Y"], "year": [2026, 2026, 2022],
                      "end": pd.to_datetime(["2026-10-21", "2026-10-23", "2022-11-01"]),
                      "dem_pct": [50.0, 52.0, 45.0], "rep_pct": [50.0, 48.0, 55.0]})
    r = dg.house_effect_rows(p, "2026-10-22")
    assert list(r["end"].dt.strftime("%Y-%m-%d")) == ["2022-11-01", "2026-10-21"]
    assert r["share"].tolist() == pytest.approx([0.45, 0.5])


def test_adjust_polls_shifts_the_share_and_keeps_the_total():
    p = pd.DataFrame({"pollster": ["Cygnal (R)", "Unknown", "Cygnal"], "year": [2026, 2026, 2022],
                      "dem_pct": [45.0, 50.0, 40.0], "rep_pct": [45.0, 40.0, 50.0]})
    eff = pd.DataFrame({"he_key": ["cygnal"], "effect": [-0.02]})
    a = dg.adjust_polls(p, eff)
    assert a.loc[0, "dem_pct"] / 90 == pytest.approx(0.52) and a.loc[0, "dem_pct"] + a.loc[0, "rep_pct"] == pytest.approx(90)
    assert (a.loc[1, "dem_pct"], a.loc[1, "rep_pct"]) == (50.0, 40.0)        # no estimate: unchanged
    assert (a.loc[2, "dem_pct"], a.loc[2, "rep_pct"]) == (40.0, 50.0)        # other years untouched
    assert a["house_effect"].tolist() == pytest.approx([-0.02, 0.0, 0.0])


def test_drop_partisan_and_races_losing_all_polls():
    p = pd.DataFrame({"pollster": ["Cygnal (R)", "PPP (D-End Citizens United)", "Emerson College", "Marist (Dartmouth)"]})
    assert dg.drop_partisan(p)["pollster"].tolist() == ["Emerson College", "Marist (Dartmouth)"]
    before = pd.DataFrame({"race_id": ["A", "B"], "poll_avg": [0.5, 0.6], "n_polls": [2, 1], "n_eff": [2.0, 1.0]})
    after = pd.DataFrame({"race_id": ["A"], "poll_avg": [0.51], "n_polls": [1], "n_eff": [1.0]})
    sf = pd.DataFrame({"id": ["A", "B"], "office": ["senate", "senate"], "vote_ok": [True, True], "dem_share_2p": [0.53, 0.6]})
    c = dg.compare_averages(sf, before, after)
    assert c["races_losing_all_polls"] == ["B"] and c["races_with_polls"] == {"v1": 2, "new": 1}
    assert c["movement_toward_dem"]["mean"] == pytest.approx(1.0)
    assert c["scored"]["error_v1_avg"]["mean"] == pytest.approx(3.0) and c["scored"]["error_new_avg"]["mean"] == pytest.approx(2.0)


DIAGNOSTICS = Path(__file__).resolve().parents[1] / "results" / "diagnostics.json"


@pytest.mark.skipif(not DIAGNOSTICS.exists(), reason="diagnostics.json not written yet")
def test_diagnostics_file_has_the_poll_variants():
    d = json.loads(DIAGNOSTICS.read_text())
    if "h7" not in d:
        pytest.skip("diagnostics.json predates H7 and H8")
    v = d["variants"]
    for k in ("h7_house_effects", "h8_no_partisan", "h7_and_h1a", "h8_and_h1a"):
        assert set(v[k]["metrics"]) == set(v["v1"]["metrics"])
        assert set(v[k]["metrics"]["all"]) == set(v["v1"]["metrics"]["all"])
    assert v["h7_and_h1a"]["house_vote_mean"] == v["h1a_bias_0"]["house_vote_mean"]
    assert v["h7_house_effects"]["metrics"]["house"] == v["v1"]["metrics"]["house"]       # race polls do not reach the House
    assert d["h8"]["averages"]["races_with_polls"]["new"] + len(d["h8"]["lost_all_polls"]) == d["h8"]["averages"]["races_with_polls"]["v1"]

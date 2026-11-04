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

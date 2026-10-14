"""Early vote against each state's own last midterm (PLAN §10 item 7). Offline."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from forecast import early_vote


SAMPLE = """state,state_abbv,turn_2022,last_update,data_source,notes,request_all,accept_all,inperson_all,voted_all
Colorado,CO,2540666,10/13/2026,SOS,NA,4001514,190646,0,190646
Florida,FL,7796916,10/13/2026,SOS,NA,2176837,617531,0,617531
Georgia,GA,3964926,10/13/2026,SOS,NA,102880,10256,188257,0
Iowa,IA,1230417,8/12/2026,SOS,NA,0,0,0,0
"""

RPUBS_STATE = """<h1>Georgia 2022 Early Vote</h1><p>Last update: 10-9-2022</p>
<p>Total Early Votes: <strong>396</strong><br/>In-Person Early Votes: 0<br/>
Mail Ballots Returned: 396<br/>Mail Ballots Requested: 190,931</p>"""

RPUBS_NATIONAL = """<p>Last updated: 10/18/2022 10:18 AM Eastern Time</p>
<p>Total Early Votes: 2,608,748 &bull; In-Person Early Votes: 337,852 &bull;
Mail Ballots Returned: 2,270,896 &bull; Mail Ballots Requested: 16,580,443</p>"""


def test_comparison_dates_are_21_days_out():
    assert early_vote.as_of(2018) == date(2018, 10, 16)
    assert early_vote.as_of(2022) == date(2022, 10, 18)
    assert early_vote.as_of(2026) == date(2026, 10, 13)


def test_pace_change_is_log_ratio_of_own_paces():
    # 10% of last turnout now against 5% at the same point last time: log(2).
    f = early_vote.pace_change(100, 1000, 50, 1000)
    assert float(f) == pytest.approx(np.log(2))
    # Same pace relative to a bigger previous electorate: no change.
    assert float(early_vote.pace_change(200, 2000, 50, 500)) == pytest.approx(0.0)
    # Nothing reported in one cycle: undefined, not infinite.
    assert np.isnan(early_vote.pace_change(0, 1000, 50, 1000))


def test_feature_frame_excludes_rule_changes_and_non_reporters():
    now = pd.DataFrame({"state_po": ["CA", "CO", "GA", "IA"], "ballots": [400.0, 190.0, 20.0, 0.0]})
    then = pd.DataFrame({"state_po": ["CA", "CO", "GA", "IA"], "ballots": [100.0, 95.0, 10.0, 5.0]})
    turnout = pd.DataFrame({"year": [2014] * 4 + [2018] * 4,
                            "state_po": ["CA", "CO", "GA", "IA"] * 2,
                            "uf_ballots": [1000.0] * 8})
    d = early_vote.feature_frame(now, then, turnout, 2022).set_index("state_po")
    assert d.loc["CO", "feature"] == pytest.approx(np.log(2))
    assert d.loc["CO", "excluded"] == ""
    assert d.loc["CA", "excluded"] == "voting rules changed"      # universal mail from 2021
    assert d.loc["GA", "excluded"] == "voting rules changed"      # SB 202 shorter mail window
    assert d.loc["IA", "excluded"] != ""
    assert d.loc[["CA", "GA", "IA"], "feature"].isna().all()


def test_fit_k_and_offsets():
    x = pd.Series([0.1, -0.2, 0.3, 0.0], index=list("ABCD"))
    assert early_vote.fit_k(x, 0.5 * x) == pytest.approx(0.5)
    assert early_vote.fit_k(x.iloc[:2], x.iloc[:2]) == 0.0       # too few states
    off = early_vote.offsets(pd.Series([2.0, -0.1, np.nan], index=list("ABC")), k=0.5)
    assert off["A"] == early_vote.OFFSET_CLIP
    assert off["B"] == pytest.approx(-0.05)
    assert off["C"] == 0.0


def test_rule_needs_both_errors_to_fall():
    assert early_vote.passes_rule((4.0, 4.2), (4.5, 4.6))
    assert not early_vote.passes_rule((4.0, 4.2), (4.7, 4.6))
    assert not early_vote.passes_rule((4.3, 4.2), (4.5, 4.6))
    assert not early_vote.passes_rule((4.2, 4.2), (4.5, 4.6))


def test_not_wired_without_a_backtest():
    assert early_vote.WIRED is False
    assert not early_vote.SNAPSHOTS[2018]["usable"]
    assert len(early_vote.state_offsets(2026)) == 0
    s = early_vote.status()
    assert set(s["year"]) == {2014, 2018, 2022, 2026}
    assert s.loc[s["year"] == 2026, "t_minus_21"].iloc[0] == "2026-10-13"


def test_parse_uf_csv(tmp_path: Path):
    path = tmp_path / "US.csv"
    path.write_text(SAMPLE)
    d = early_vote.parse_uf_csv(path, 2026).set_index("state_po")
    assert d.loc["FL", "ballots"] == 617531
    assert d.loc["FL", "early_share"] == pytest.approx(617531 / 7796916)
    # voted_all missing: mail plus in-person.
    assert d.loc["GA", "ballots"] == 10256 + 188257
    assert not bool(d.loc["IA", "reporting"])


def test_national_pace(tmp_path: Path, monkeypatch):
    path = tmp_path / "US.csv"
    path.write_text(SAMPLE)
    monkeypatch.setattr(early_vote, "OUT", tmp_path)
    early_vote.parse_uf_csv(path, 2026).to_parquet(tmp_path / "early_vote_2026.parquet")
    p = early_vote.national_pace(2026)
    assert p["n_reporting"] == 3
    assert p["last_update_max"] == "2026-10-13"


def test_parse_rpubs_pages():
    st = early_vote.parse_rpubs(RPUBS_STATE)
    assert st["ballots"] == 396 and st["mail_requested"] == 190931
    assert st["last_update"] == date(2022, 10, 9)
    nat = early_vote.parse_rpubs(RPUBS_NATIONAL)
    assert nat["ballots"] == 2608748 and nat["inperson"] == 337852
    assert nat["last_update"] == date(2022, 10, 18)


def test_max_update_parses_mdy():
    assert early_vote._max_update(pd.Series(["9/28/2026", "10/4/2026"])) == "2026-10-04"


def test_load_missing_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(early_vote, "OUT", tmp_path)
    assert len(early_vote.load(2026)) == 0
    assert early_vote.national_pace(2026)["n_reporting"] == 0

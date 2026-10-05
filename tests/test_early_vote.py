"""UF Election Lab 2026 early-vote ingest (PLAN §10 item 7)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from forecast import early_vote


SAMPLE = """state,state_abbv,turn_2022,last_update,data_source,notes,request_all,accept_all,inperson_all,voted_all
Colorado,CO,2540666,10/2/2026,SOS,NA,4001514,4012,2,4014
Florida,FL,7796916,10/4/2026,SOS,NA,2176837,146038,0,146038
Georgia,GA,3964926,10/4/2026,SOS,NA,102880,686,0,686
Iowa,IA,1230417,8/12/2026,SOS,NA,0,0,0,0
Maryland,MD,2031635,10/4/2026,SOS,NA,596951,67593,0,67593
"""


def test_parse_uf_csv_shares(tmp_path: Path):
    path = tmp_path / "US.csv"
    path.write_text(SAMPLE)
    d = early_vote.parse_uf_csv(path, year=2026)
    assert set(d["state_po"]) == {"CO", "FL", "GA", "IA", "MD"}
    assert d.loc[d["state_po"] == "FL", "reporting"].iloc[0]
    assert not bool(d.loc[d["state_po"] == "IA", "reporting"].iloc[0])
    fl = d.set_index("state_po").loc["FL"]
    assert fl["early_share"] == pytest.approx(146038 / 7796916)
    assert fl["mail_share"] == pytest.approx(146038 / 7796916)
    assert fl["source"] == "uf_election_lab"


def test_state_offsets_mean_zero_among_reporters(tmp_path: Path, monkeypatch):
    path = tmp_path / "US.csv"
    path.write_text(SAMPLE)
    d = early_vote.parse_uf_csv(path, year=2026)
    monkeypatch.setattr(early_vote, "OUT", tmp_path)
    d.to_parquet(tmp_path / "early_vote_2026.parquet", index=False)
    off = early_vote.state_offsets(2026)
    rep = d.loc[d["reporting"], "state_po"]
    assert abs(float(off.loc[rep].mean())) < 1e-9
    # Florida has the highest pace among reporters → positive offset.
    assert off.loc["FL"] > off.loc["GA"]
    assert off.loc["IA"] == 0.0


def test_national_pace(tmp_path: Path, monkeypatch):
    path = tmp_path / "US.csv"
    path.write_text(SAMPLE)
    d = early_vote.parse_uf_csv(path, year=2026)
    monkeypatch.setattr(early_vote, "OUT", tmp_path)
    d.to_parquet(tmp_path / "early_vote_2026.parquet", index=False)
    pace = early_vote.national_pace(2026)
    assert pace["n_reporting"] == 4
    assert pace["early_share"] > 0
    assert pace["source"] == "uf_election_lab"


def test_load_missing_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(early_vote, "OUT", tmp_path)
    d = early_vote.load(2026)
    assert len(d) == 0
    assert "early_share" in d.columns

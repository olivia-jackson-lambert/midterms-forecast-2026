"""October refresh checklist helpers (PLAN §10 item 7)."""
from __future__ import annotations

import pandas as pd

from forecast import october_refresh as oct


def test_checklist_blocks_publish_tag():
    chk = oct.checklist(
        ev={"status": "ok", "n_reporting": 30, "last_update_max": "2026-10-04"},
        gb={"n_sources": 4, "dem_2p": 0.52, "margin": 4.0},
        spec={"n": 12, "mean_pp": 5.0},
        votes={"n_races": 70, "fit_method": "ridge"},
        turnout={"applied": False, "reason": "missing midterm turnout"},
        gates={"present": True, "all_pass": True, "coverage80_min": 0.9},
    )
    by = chk.set_index("item")["ok"]
    assert bool(by["early_vote_2026"])
    assert bool(by["race_backtest_soft_lean_gate"])
    assert bool(by["race_backtest_coverage80_ge_0.75"])
    assert not bool(by["publish_tag"])
    assert not bool(by["stage_a_early_vote_refresh"])


def test_race_backtest_gates_reads_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(oct, "OUT", tmp_path)
    pd.DataFrame([
        {"year": 2018, "brier": 0.18, "baseline_brier": 0.20,
         "beats_lean_baseline": True, "coverage80": 0.91},
        {"year": 2022, "brier": 0.16, "baseline_brier": 0.18,
         "beats_lean_baseline": True, "coverage80": 0.93},
    ]).to_csv(tmp_path / "backtest_races.csv", index=False)
    g = oct.race_backtest_gates()
    assert g["present"] and g["all_pass"]
    assert g["coverage80_min"] == 0.91

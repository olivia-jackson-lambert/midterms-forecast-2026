"""PLAN §10 item 7 — October refresh and publish-path prep (no git tag).

Refreshes early vote, generic-ballot snapshot, specials, and the 2026 Stage B
race table. Writes a local draft under `forecasts/_draft/` and a checklist CSV.
Does **not** create a git tag or commit published CSVs into `forecasts/` — that
waits for PLAN §7 publish week (19 October).

Stage A county turnout re-run requires `county_midterm_turnout.parquet`
(`python -m forecast.midterms`); when present, this module applies early-vote
offsets via `turnout_model.run`.

    python -m forecast.october_refresh
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .ingest import OUT, ROOT

DRAFT = ROOT / "forecasts" / "_draft"
CHECKLIST = OUT / "october_refresh_checklist.csv"


def _ok(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def refresh_early_vote(force: bool = True) -> dict:
    from . import early_vote as ev
    df = ev.build(2026, force=force)
    st = ev.status(2026)
    pd.DataFrame([st]).to_csv(OUT / "early_vote_status.csv", index=False)
    return {**st, "rows": int(len(df)), "reporting": int(df["reporting"].sum())}


def refresh_generic_ballot(force: bool = True) -> dict:
    from . import generic_ballot as gb
    if force:
        # Drop cached 2026 Wikipedia HTML so the snapshot can move with new polls.
        cache = gb.RAW_GB / "wiki_generic_ballot_2026.html"
        if cache.exists():
            cache.unlink()
    snaps = []
    detail_parts = []
    for year in (2018, 2022, 2026):
        detail_parts.append(gb.aggregates(year))
        snaps.append(gb.snapshot(year))
    detail = pd.concat(detail_parts, ignore_index=True)
    snap = pd.DataFrame(snaps)
    OUT.mkdir(parents=True, exist_ok=True)
    detail.to_parquet(OUT / "generic_ballot_aggregates.parquet", index=False)
    snap.to_parquet(OUT / "generic_ballot_snapshot.parquet", index=False)
    detail.to_csv(OUT / "generic_ballot_aggregates.csv", index=False)
    snap.to_csv(OUT / "generic_ballot_snapshot.csv", index=False)
    row = snap.loc[snap["year"] == 2026].iloc[0].to_dict()
    return {"year": 2026, "dem_2p": row["dem_2p"], "margin": row["margin"],
            "n_sources": int(row["n_sources"]), "sources": row["sources"]}


def refresh_specials() -> dict:
    from . import special_elections as se
    df = se.series(2026)
    s = se.summary(2026)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / "special_elections_2026.parquet", index=False)
    df.to_csv(OUT / "special_elections_2026.csv", index=False)
    pd.DataFrame([s]).to_parquet(OUT / "special_elections_summary.parquet", index=False)
    return {"n": int(s.get("n", len(df))), "mean_pp": float(s.get("mean_pp", float("nan"))),
            "source": s.get("source")}


def refresh_vote_share(sims: int = 4000, draws: int = 600) -> dict:
    """Fit Stage B on 2018+2022 and write the 2026 race table (processed + draft)."""
    from . import vote_model as vm
    os.environ.setdefault("STAGE_B_PYMC", "0")
    lean = vm.presidential_lean(2026)
    out, info = vm.run(2026, train_years=[2018, 2022], sims=sims, draws=draws,
                       lean=None if lean.empty else lean)
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT / "vote_share_2026.parquet", index=False)
    info["seats"].to_parquet(OUT / "seat_counts_2026.parquet", index=False)
    DRAFT.mkdir(parents=True, exist_ok=True)
    out.to_csv(DRAFT / "vote_share_2026.csv", index=False)
    info["seats"].to_csv(DRAFT / "seat_counts_2026.csv", index=False)
    swing = info["swing"]
    return {
        "n_races": int(len(out)),
        "swing_source": swing.get("source"),
        "swing_mean": float(swing.get("mean", float("nan"))),
        "swing_sd": float(swing.get("sd", float("nan"))),
        "fit_method": info["params"].get("fit_method"),
        "draft": str(DRAFT / "vote_share_2026.csv"),
    }


def refresh_turnout_if_ready(sims: int = 4000, draws: int = 250,
                             chains: int = 2, tune: int = 500) -> dict:
    """Stage A October refresh when midterm turnout panel exists."""
    mid = OUT / "county_midterm_turnout.parquet"
    if not mid.exists():
        return {"applied": False, "reason": "missing county_midterm_turnout.parquet "
                "(run python -m forecast.midterms)"}
    from . import turnout_model as tm
    out, info = tm.run(2026, [2018, 2022], sims=sims, draws=draws, early_vote=True,
                       chains=chains, tune=tune)
    rel, rel_info = tm.run(2026, [2018, 2022], params=info["params"],
                           national_fixed=float(info["national"][1]), early_vote=True)
    out["lo80_county"], out["hi80_county"] = rel["lo80"].values, rel["hi80"].values
    out.to_parquet(OUT / "turnout_2026.parquet", index=False)
    st = info["states"].merge(rel_info["states"][["state_po", "lo80", "hi80"]], on="state_po",
                              suffixes=("", "_state"))
    st.to_parquet(OUT / "turnout_2026_states.parquet", index=False)
    if info["params"].get("summary") is not None:
        info["params"]["summary"].to_csv(OUT / "turnout_2026_parameters.csv")
    pd.DataFrame({"quantile": [0.1, 0.5, 0.9], "turnout": info["national"]}).to_csv(
        OUT / "turnout_2026_national.csv", index=False)
    DRAFT.mkdir(parents=True, exist_ok=True)
    st.to_csv(DRAFT / "turnout_2026_states.csv", index=False)
    ev = info.get("early_vote") or {}
    pd.DataFrame([ev]).to_csv(OUT / "turnout_2026_early_vote.csv", index=False)
    return {
        "applied": True,
        "early_vote": bool(ev.get("applied")),
        "national_median": float(info["national"][1]),
        "n_counties": int(len(out)),
    }


def race_backtest_gates() -> dict:
    path = OUT / "backtest_races.csv"
    if not path.exists():
        return {"present": False}
    d = pd.read_csv(path)
    return {
        "present": True,
        "years": sorted(int(y) for y in d["year"]),
        "all_pass": bool(d["beats_lean_baseline"].all()),
        "coverage80_min": float(d["coverage80"].min()) if "coverage80" in d else float("nan"),
        "brier": {int(r.year): float(r.brier) for _, r in d.iterrows()},
        "lean_brier": {int(r.year): float(r.baseline_brier) for _, r in d.iterrows()},
        "coverage80": {int(r.year): float(r.coverage80) for _, r in d.iterrows()}
        if "coverage80" in d else {},
    }


def checklist(ev: dict, gb: dict, spec: dict, votes: dict, turnout: dict,
              gates: dict) -> pd.DataFrame:
    """One-row operator checklist for item 7 / publish readiness."""
    rows = [
        {"item": "early_vote_2026", "ok": ev.get("status") == "ok",
         "detail": f"n_reporting={ev.get('n_reporting')} last={ev.get('last_update_max')}"},
        {"item": "generic_ballot_2026", "ok": gb.get("n_sources", 0) >= 1,
         "detail": f"dem_2p={gb.get('dem_2p'):.3f} sources={gb.get('n_sources')}"},
        {"item": "special_elections_2026", "ok": spec.get("n", 0) >= 1,
         "detail": f"n={spec.get('n')} mean_pp={spec.get('mean_pp')}"},
        {"item": "vote_share_2026_draft", "ok": _ok(DRAFT / "vote_share_2026.csv"),
         "detail": f"n_races={votes.get('n_races')} fit={votes.get('fit_method')}"},
        {"item": "stage_a_early_vote_refresh", "ok": bool(turnout.get("applied")),
         "detail": turnout.get("reason") or f"early_vote={turnout.get('early_vote')} "
                   f"nat={turnout.get('national_median')}"},
        {"item": "race_backtest_soft_lean_gate",
         "ok": bool(gates.get("present") and gates.get("all_pass")),
         "detail": f"coverage80_min={gates.get('coverage80_min')}"},
        {"item": "race_backtest_coverage80_ge_0.75",
         "ok": bool(gates.get("present") and (gates.get("coverage80_min") or 0) >= 0.75),
         "detail": f"min={gates.get('coverage80_min')}"},
        {"item": "publish_tag", "ok": False,
         "detail": "wait for PLAN §7 week of 19 Oct — do not tag from this module"},
    ]
    out = pd.DataFrame(rows)
    out["as_of"] = date.today().isoformat()
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    DRAFT.mkdir(parents=True, exist_ok=True)
    print("=== early vote ===")
    ev = refresh_early_vote(force=True)
    print(ev)
    print("=== generic ballot ===")
    gb = refresh_generic_ballot(force=True)
    print(gb)
    print("=== special elections ===")
    spec = refresh_specials()
    print(spec)
    print("=== stage B vote share ===")
    votes = refresh_vote_share()
    print(votes)
    print("=== stage A turnout (if ready) ===")
    turnout = refresh_turnout_if_ready()
    print(turnout)
    gates = race_backtest_gates()
    chk = checklist(ev, gb, spec, votes, turnout, gates)
    chk.to_csv(CHECKLIST, index=False)
    DRAFT.joinpath("october_refresh_checklist.csv").write_text(chk.to_csv(index=False))
    DRAFT.joinpath("october_refresh_summary.json").write_text(json.dumps({
        "early_vote": {k: (None if isinstance(v, float) and not np.isfinite(v) else v)
                       for k, v in ev.items()},
        "generic_ballot": gb,
        "specials": spec,
        "vote_share": votes,
        "turnout": turnout,
        "gates": gates,
    }, indent=2, default=str))
    print("=== checklist ===")
    print(chk.to_string(index=False))
    print("draft dir:", DRAFT)
    print("processed checklist:", CHECKLIST)


if __name__ == "__main__":
    main()

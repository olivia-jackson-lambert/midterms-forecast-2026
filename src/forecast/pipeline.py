"""Run every step that builds the forecast, in the order the README gives.

    python -m forecast.pipeline [--refresh] [--skip-backtests] [--dry-run]

The steps are ingest, races, midterms, generic_ballot, polls, backtest, turnout_model and
vote_model. Each is the module's own main(), called in turn. Nothing is skipped
automatically: every step reads its own cache in data/raw/, so a repeat run is cheap
except for the model fits (about an hour in all).

--refresh re-downloads the 2026 Wikipedia pages (races and race polls) and the 2026 generic ballot.
--skip-backtests leaves out the backtest step. The 2026 models need the turnout-weighted
leans it saves for 2018 and 2022 (lean_draws_*.parquet), so the run stops before
starting if those files are missing.
--dry-run prints the plan and imports nothing.
"""
from __future__ import annotations

import argparse
import importlib
import time

from .ingest import OUT

STEPS = ["ingest", "races", "midterms", "generic_ballot", "polls", "backtest", "turnout_model", "vote_model"]
TAKES_REFRESH = {"races", "generic_ballot", "polls"}
NEEDED_FROM_BACKTEST = ["lean_draws_2018.parquet", "lean_draws_2022.parquet"]


def plan(refresh: bool = False, skip_backtests: bool = False) -> list[tuple[str, dict]]:
    """The steps to run, as (module name, keyword arguments for its main())."""
    out = []
    for name in STEPS:
        if skip_backtests and name == "backtest":
            continue
        kwargs = {"refresh": True} if refresh and name in TAKES_REFRESH else {}
        if name == "backtest":
            kwargs = {"argv": ["all"]}      # its main() would otherwise read our command line
        out.append((name, kwargs))
    return out


def run(refresh: bool = False, skip_backtests: bool = False, dry_run: bool = False) -> None:
    steps = plan(refresh, skip_backtests)
    if skip_backtests and not dry_run:
        missing = [f for f in NEEDED_FROM_BACKTEST if not (OUT / f).exists()]
        if missing:
            raise SystemExit(f"--skip-backtests needs {', '.join(missing)} in {OUT}; run the backtest once first")
    start = time.time()
    for name, kwargs in steps:
        if dry_run:
            print(f"would run forecast.{name}" + (" with refresh" if "refresh" in kwargs else ""))
            continue
        t0 = time.time()
        importlib.import_module(f"forecast.{name}").main(**kwargs)
        print(f"[{name}] done in {time.time() - t0:.1f}s", flush=True)
    if not dry_run:
        print(f"pipeline done in {(time.time() - start) / 60:.1f} min")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Run the whole forecast pipeline.")
    ap.add_argument("--refresh", action="store_true", help="re-download the 2026 race pages and generic ballot")
    ap.add_argument("--skip-backtests", action="store_true", help="leave out the backtest step")
    ap.add_argument("--dry-run", action="store_true", help="print the steps without running them")
    a = ap.parse_args(argv)
    run(a.refresh, a.skip_backtests, a.dry_run)


if __name__ == "__main__":
    main()

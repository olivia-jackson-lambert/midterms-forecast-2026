# 2026 Midterms: A Turnout-First Forecast

See `PLAN.md` for the goal, method, timeline and data sources.

## Setup

```
pip install -r requirements.txt
```

No API keys or download forms are needed. The ingest pulls public files from GitHub
(MIT Election Lab's county returns and a county results mirror) and from www2.census.gov
(CVAP, ACS summary files, Gazetteer), the EAC (EAVS) and the UF Election Lab. The first run downloads about 800 MB and caches
what it needs in `data/raw/`, which is never committed.

## Run

```
cd src && python -m forecast.ingest     # presidential panel: data/processed/county_panel.parquet
python -m forecast.midterms             # midterm turnout 2014-2022 and 2018/2022 results
python -m forecast.generic_ballot       # 2018/2022/2026 generic-ballot aggregates
python -m forecast.special_elections    # 2025–26 specials vs 2024 presidential lean
python -m forecast.races                # 2026 Senate/governor race list and incumbency
python -m forecast.historical_races     # 2018/2022 open seats / incumbency for backtests
python -m forecast.fundraising          # OpenFEC Senate receipts → fundraising feature
python -m forecast.ensure_race_data     # slim panel + MIT SEN/GOV results for race backtests
python -m forecast.backtest races       # Stage B Brier / calibration vs lean baseline
python -m forecast.early_vote           # UF Election Lab 2026 early/mail vote (refresh often)
python -m forecast.backtest             # turnout + Stage B race backtests (when data present)
python -m forecast.turnout_model        # 2026 county turnout forecast (Stage A)
python -m forecast.vote_model           # Stage B race table (GB + specials swing, incumbency, FEC)
cd .. && python -m pytest               # data and model checks
```

**Midterms rebuild (CA Senate + TN governor supplements).** `forecast.midterms` merges
state/Wikipedia gap-fills into `county_midterm_results.parquet` on every run. Re-run after
a fresh clone once MIT 2018/2022 precinct archives are cached under `data/raw/` (large
download on first pull). Supplement parsers are unit-tested without the full MIT cache;
`tests/test_midterms.py::test_races_found` expects 36 GOV / 34+2 SEN in 2022 only after
that rebuild.

Stage B unit tests (`tests/test_vote_model.py`) use synthetic leans and do not need
`data/processed/` — run them with `python -m pytest tests/test_vote_model.py`.

`county_panel.parquet` has one row per county unit and presidential year (2008 to 2024):
Democratic, Republican and total votes, two-party share, citizen voting-age population,
turnout as a share of it, and ACS 2020–2024 demographics. `PLAN.md` explains the county
units and known limits.

### iCloud

The repo sits in an iCloud-synced folder, and with "Optimise Mac Storage" on iCloud evicts
large files, which makes reads fail or crawl. iCloud skips anything ending in `.nosync`, so the
data lives in `data.nosync/` with `data` as a symlink to it. In a fresh clone:

```
mkdir -p data.nosync/raw data.nosync/processed && ln -s data.nosync data
```

The portfolio venv is set up the same way (`.venv` links to `.venv.nosync`). To keep data
somewhere else entirely, set `TURNOUT_DATA=/path/to/data`.

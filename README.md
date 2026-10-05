# 2026 Midterms: A Turnout-First Forecast

See `PLAN.md` for the goal, method, timeline and data sources.

## Setup

```
pip install -r requirements.txt
```

No API keys or download forms are needed. The ingest pulls public files from GitHub
(MIT Election Lab's county returns and a county results mirror) and from www2.census.gov
(CVAP, ACS summary files, Gazetteer), the EAC (EAVS), the UF Election Lab, FiveThirtyEight's
data repo and Wikipedia. The first run downloads about 800 MB and caches what it needs in
`data/raw/`, which is never committed.

## Run

In order (each step caches what it downloads):

```
cd src
python -m forecast.ingest            # presidential county panel, 2008-2024
python -m forecast.races             # races, incumbents, nominees and results (add --refresh for 2026)
python -m forecast.midterms          # midterm county turnout 2014-2022 and 2018/2022 county results
python -m forecast.generic_ballot    # generic ballot as of 30 September and House vote (add --refresh)
python -m forecast.backtest          # turnout and race backtests, 2018 and 2022
python -m forecast.turnout_model     # 2026 county turnout (Stage A)
python -m forecast.vote_model        # 2026 Senate and governor races (Stage B)
cd .. && python figures/make_figures.py   # figures in figures/out/
python -m pytest                     # data and model checks
```

`forecast.races` runs before `forecast.midterms` because MIT's party labels are wrong for
some nominees, and the parsed nominee names correct them. The backtests run before the 2026
models because Stage A saves the turnout-weighted leans Stage B needs (`lean_draws_*.parquet`).

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

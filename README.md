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
python -m forecast.backtest             # turnout backtests, 2018 and 2022
python -m forecast.turnout_model        # 2026 county turnout forecast
cd .. && python -m pytest               # data and model checks
```

`county_panel.parquet` has one row per county unit and presidential year (2008 to 2024):
Democratic, Republican and total votes, two-party share, citizen voting-age population,
turnout as a share of it, and ACS 2020–2024 demographics. `PLAN.md` explains the county
units and known limits.

### iCloud

If the repo sits in an iCloud-synced folder with "Optimise Mac Storage" on, iCloud can evict
data files and packages, which makes reads fail or crawl. Point the data somewhere local with
`export TURNOUT_DATA=/path/outside/icloud` (it defaults to `data/` in the repo).

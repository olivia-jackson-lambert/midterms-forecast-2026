# 2026 Midterms: A Turnout-First Forecast

See `PLAN.md` for the goal, method, timeline and data sources.

## Setup (one time)

1. **Census API key** (free): sign up at https://api.census.gov/data/key_signup.html, then add
   `export CENSUS_API_KEY=<your key>` to your shell profile. The key is read from the
   environment and is never written into the repo.
2. **MIT Election Lab files** need a short download form (guestbook) the first time. Download
   each file below from its DOI page and save it in `data/raw/` with the same filename:
   - `countypres_2000-2024.tab`: https://doi.org/10.7910/DVN/VOQCHQ
   - (later) Senate and House precinct files for 2018 and 2022, and state offices 2018 and 2022; see `PLAN.md`
3. Install: `pip install -r requirements.txt`

## Run

```
cd src && python -m forecast.ingest
```

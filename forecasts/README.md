# Forecasts

Published forecast tables live here as CSVs, **one set per tagged release** (PLAN §6–§7).

Until publish week (19 October):

1. Run the October refresh (no tag):

   ```bash
   STAGE_B_PYMC=0 PYTHONPATH=src python -m forecast.october_refresh
   ```

2. Review `data/processed/october_refresh_checklist.csv` and the local draft under
   `forecasts/_draft/` (gitignored).

3. When PLAN §7 says publish: copy the draft CSVs to versioned names in this folder
   (for example `vote_share_2026_v1.csv`), commit, and tag the commit. Do not tag
   from `october_refresh` itself.

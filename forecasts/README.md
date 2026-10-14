# Forecasts

Published forecast tables, one folder per tagged release (`v1/`, `v2/`, ..., `final/`). Each
folder is written by `python -m forecast.release <version>` and holds:

- `turnout_counties.csv`: county turnout, 2022 and the 2026 forecast (median and 80% interval)
- `turnout_states.csv`: the same by state, with DC
- `national.csv`: national turnout, the national House vote and the generic ballot behind it
- `races.csv`: every Senate and governor race (Democratic-side vote share, 80% interval, win probability)
- `senate_seats.csv`: distribution of Democratic-caucus Senate seats
- `backtests.csv`: the 2018 and 2022 backtest scores, one metric per row
- `manifest.json`: version, time, git commit, input dates, simulation counts and a SHA-256 for every file

Turnout is votes cast as a share of citizen voting-age population. `lo80` and `hi80` are the
10th and 90th percentiles of the simulations and include uncertainty in national turnout; the
`_county` and `_state` columns hold national turnout at its median, so they show only the
county's or state's own uncertainty. County rows are county units, not always counties:
Alaska, Connecticut and DC are one unit each, and Jackson, Clay and Platte counties (Missouri)
are one unit for Kansas City. In `races.csv` the shares and probabilities belong to the
Democratic side (`d_side`), which is an independent in the few races with no Democrat.
Shares are rounded to four decimals and probabilities to three, so the tails of
`senate_seats.csv` show as 0.

To release: refresh the 2026 inputs and run the pipeline (`python -m forecast.pipeline --refresh`),
check a draft (`python -m forecast.release v1 --draft`, written to `forecasts/_draft/v1/`,
which git ignores), then write the real one (`python -m forecast.release v1`), commit it with a
clean working tree (the manifest records whether it was clean) and tag the commit with the folder name.

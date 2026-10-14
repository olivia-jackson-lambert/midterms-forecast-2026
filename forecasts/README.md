# Forecasts

Published forecast tables, one folder per tagged release (`v1/`, `v2/`, ..., `final/`). Each
folder is written by `python -m forecast.release <version>` and holds:

- `turnout_counties.csv`: county turnout, 2022 and the 2026 forecast (median and 80% interval)
- `turnout_states.csv`: the same by state, with DC
- `national.csv`: national turnout, the national House vote and the generic ballot behind it
- `races.csv`: every Senate and governor race (Democratic-side vote share, 80% interval, win probability, poll average and number of polls)
- `senate_seats.csv`: distribution of Democratic-caucus Senate seats
- `house_districts.csv`: all 435 House districts: incumbents running, candidates, any stand-in, whether contested or a certain hold, presidential lean, median Democratic two-party share with 80% interval, and the probabilities that a Democrat, a Republican or an independent wins
- `house_seats.csv`: distribution of House seats (Democratic, Republican and independent seats, with probability)
- `backtests.csv`: the 2018 and 2022 backtest scores (turnout, races and House), one metric per row
- `manifest.json`: version, time, git commit, input dates (including the House page fetch date and the latest poll end date), simulation counts and a SHA-256 for every file

Turnout is votes cast as a share of citizen voting-age population. `lo80` and `hi80` are the
10th and 90th percentiles of the simulations and include uncertainty in national turnout; the
`_county` and `_state` columns hold national turnout at its median, so they show only the
county's or state's own uncertainty. County rows are county units, not always counties:
Alaska, Connecticut and DC are one unit each, and Jackson, Clay and Platte counties (Missouri)
are one unit for Kansas City. In `races.csv` the shares and probabilities belong to the
Democratic side (`d_side`), which is an independent in the few races with no Democrat.
In `races.csv`, `poll_avg` is the Democratic side's share of the two-party poll average and
`n_polls` the polls behind it (blank and 0 where there are none). The fundamentals-only median
is not saved by the pipeline, so it is not published. In `house_districts.csv` the median and
interval are blank in the districts that are not modelled: a certain hold (`certain_hold_party`
is D or R) has only one party's candidate on the ballot. `contested` means a Democrat against
a Republican; `stand_in` names the candidate who takes a missing party's place. The three win
probabilities sum to one up to rounding. In `backtests.csv` the `model` variant of the races
backtest is the one with polls. The House rows appear once the House backtest has run.
Shares are rounded to four decimals and probabilities to three, so the tails of
`senate_seats.csv` show as 0 (the seat files use four decimals, so their tails show).

To release: refresh the 2026 inputs and run the pipeline (`python -m forecast.pipeline --refresh`),
check a draft (`python -m forecast.release v1 --draft`, written to `forecasts/_draft/v1/`,
which git ignores), then write the real one (`python -m forecast.release v1`), commit it with a
clean working tree (the manifest records whether it was clean) and tag the commit with the folder name.

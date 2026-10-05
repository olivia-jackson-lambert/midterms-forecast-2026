# Forecasts

Published forecast tables, one folder per tagged release (`v1/`, `v2/`, ..., `final/`):

- `turnout_counties.csv`: county turnout forecast (median and 80% interval)
- `turnout_states.csv`: state turnout forecast
- `races.csv`: every Senate and governor race (vote share, 80% interval, win probability)
- `senate_seats.csv`: distribution of Democratic-caucus Senate seats

To release: refresh the 2026 inputs (`python -m forecast.races --refresh`,
`python -m forecast.generic_ballot --refresh`), run the pipeline in the README, copy the
tables here, commit, and tag the commit with the folder name.

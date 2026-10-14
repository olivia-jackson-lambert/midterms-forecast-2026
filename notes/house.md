# The House (13 October)

Code: `house.py`, `backtest.py` (`python -m forecast.backtest house`), tests in `tests/test_house.py`.

All 435 districts: the Democratic two-party share, the chance of winning, and the distribution of seats. Same structure as Stage B, with one office, backtested on 2018 and 2022 before anything was run for 2026.

## Sources

Everything is public and cached under `data/raw/house/`.

| Need | Source | Vintage |
|---|---|---|
| 2024 presidential by 2026 district | The Downballot, "2020 & 2024 presidential election results for congressional districts used in the 2026 elections", Vote totals tab (sheet `1eZfaFI-...`, linked from the-db.co/presbycd) | Downloaded 13 October 2026. The sheet says it covers every map adopted before the 2026 midterms |
| 2024 presidential by 2024 district | The Downballot, sheet for the 2024 lines (`1ng1i_Dm_...`), Vote totals tab | Downloaded 13 October 2026 |
| 2020 presidential by 2022 district | Daily Kos Elections, "2020 presidential election results for congressional districts used in 2022 elections" (`1CKngqOp...`), Vote totals tab | 2022 sheet, downloaded 13 October 2026 |
| 2020 presidential by 2020 district | Daily Kos Elections sheet for the 2020 lines (`1XbUXnI9...`), Vote totals tab | Downloaded 13 October 2026 |
| 2016 presidential by 2018 district | Daily Kos Elections, "2008, 2012 & 2016 presidential election results for congressional districts used in 2018 elections" (`1zLNAuRq...`), Vote totals tab (includes Pennsylvania's 2018 court map) | 2019 sheet, downloaded 13 October 2026 |
| 2016 presidential by 2016 district | Daily Kos Elections sheet for the 2016 lines (`1VfkHtzB...`), Vote totals tab | Downloaded 13 October 2026 |
| District results 2016, 2018, 2020, 2022, 2024; members and their status | Wikipedia, "<year> United States House of Representatives elections": one table per state with every district's member, status and candidates with certified percentages | The copies `generic_ballot.py` saved on 4 October 2026 |
| 2026 members, retirements and nominees | Wikipedia, "2026 United States House of Representatives elections" | Saved 13 October 2026 as `wiki_house_2026_2026-10-13.html`; `--refresh` saves a new dated copy and never overwrites |
| National House vote and generic ballot | `generic_ballot.py`, unchanged (the same distribution as Stage B) | |

Every source is used for the map in force that year: 2016 results on the 2018 map, 2020 on the 2022 map and 2024 on the 2026 map.

**Which maps changed for 2026.** Comparing the 2024 result on the 2024 and 2026 lines, district by district, nine states have new maps: Texas, California, North Carolina, Ohio, Utah, Florida, Tennessee, Louisiana and Alabama. That matches Wikipedia's article on 2025-2026 redistricting. Missouri's new map is not in force for 2026 (suspended by the referendum petition and kept off by the Supreme Court), nor is Virginia's (voided by the state supreme court), and both sheets agree. Indiana, Maryland, South Carolina, Kansas and New York did not change. As a check that the Downballot sheet and Wikipedia describe the same 2026 map, our lean is within 2.1 points of Wikipedia's Cook PVI in every district (Cook blends 2020 and 2024, so they are close but not equal).

**Results check.** Wikipedia's district results match MIT's precinct files (aggregated to district) within 0.03 points at the median in both 2018 and 2022. The larger gaps are in MIT's coding, not Wikipedia's: New York's fusion lines are filed under minor parties, Minnesota's DFL and Indiana 2022 are incomplete, and Delaware 2018 is short. So the House uses Wikipedia, and MIT is only a check (New Jersey 2022 is double counted in MIT anyway).

## Method

On the logit scale, the Democratic two-party share in district i is

- the national House vote (in training, the actual result; in a forecast, a draw from `generic_ballot.national_environment`, the same distribution Stage B uses);
- plus a + b times the district's lean against the nation: its last presidential two-party share against the national presidential share;
- plus d times incumbency: +1 if a Democratic member is on the November ballot in this district, -1 if a Republican, 0 for an open seat or two members of different parties drawn together;
- plus region, state and district errors, all fitted in PyMC with Stage B's priors.

Each year is fitted on earlier midterms only: 2018 runs on the priors alone, 2022 is fitted on 2018, and 2026 on 2018 and 2022. Each simulation (20,000) draws the national vote, the parameters, and the regional, state and district errors, so districts in the same state move together.

**Uncontested seats.** A district without both a Democrat and a Republican on the ballot (unopposed members, California top-two finals between two members of one party, and past races where the top two were from one party) has no two-party result. It is left out of training and scoring, and in a forecast it is a certain hold for the party on the ballot. That is 41 districts in 2018, 36 in 2022 and 19 in 2026.

**Incumbent track record: tested, left out.** The specification included the incumbent's last House result against a uniform-swing expectation, where the district kept its shape (the same presidential election within half a point on the old and new lines; 296 running members in 2018, 64 in 2022 after the census redraw, 239 in 2026). In the 2022 backtest it made both Brier and vote-share error worse (0.035 against 0.031, 2.26 against 2.21 points). Stage B's rule for fundraising, set before any House run, is that a term stays only if it improves 2022 on both, so it is off (`USE_TRACK_RECORD`). It is still computed and saved (`track_record_raw`), and with it the 2026 headline barely moves (median 232 seats, P(218+) 0.91).

**No turnout weighting.** District leans are plain presidential shares. Stage B showed turnout weighting moves state leans by 0.07 points on average, and weighting a district would need a county-by-district split of every map, which is not public for the 2026 lines.

## Backtest

Scored on districts with a Democrat against a Republican (394 in 2018, 399 in 2022). Both references are called with certainty. Seat counts include uncontested seats.

| | 2018 | 2022 |
|---|---|---|
| Brier score, model | 0.058 | **0.031** |
| Brier, presidential lean | 0.084 | 0.055 |
| Brier, lean plus uniform swing | **0.053** | 0.055 |
| Vote-share error, model (points) | 2.8 | **2.2** |
| Vote-share error, presidential lean | 3.5 | 3.2 |
| Vote-share error, uniform swing | 2.8 | 2.3 |
| Log loss | 0.220 | 0.101 |
| 80% interval coverage | 99% | 91% |
| Democratic seats, actual | 234 | 213 |
| Model, median (80% interval) | 229 (191-291) | 210 (195-225) |
| Presidential lean | 207 | 226 |
| Uniform swing | 223 | 206 |
| Model, chance of a Democratic majority | 62% | 26% |
| With the track record: Brier / error | 0.059 / 2.8 | 0.035 / 2.3 |
| National vote known: Brier / error / median seats | 0.058 / 2.7 / 238 | 0.031 / 2.2 / 207 |

2018's actual count is 234 rather than the 235 Democrats seated, because North Carolina's 9th was never certified and the Republican's uncertified lead is what Wikipedia lists.

Calibration (contested districts, model):

| Forecast chance | 2018 districts | 2018 Democratic win rate | 2022 districts | 2022 Democratic win rate |
|---|---|---|---|---|
| 0-20% | 122 | 1% | 180 | 1% |
| 20-40% | 72 | 10% | 13 | 38% |
| 40-60% | 32 | 72% | 12 | 67% |
| 60-80% | 33 | 91% | 17 | 65% |
| 80-100% | 135 | 100% | 177 | 99% |

**Reading it.** In 2022, trained on 2018, the model beats both references on Brier and vote-share error, though only narrowly on vote share against uniform swing (2.2 against 2.3 points). Its seat count was 3 too low, and the actual count was inside the 80% band. In 2018, on the priors alone, it beats the presidential lean but not uniform swing on Brier, and ties it on vote share. Its intervals that year are far too wide (99% coverage; a seat band of 100 seats) because the priors on the lean slope and district noise are loose. The 2018 forecasts were under-confident at both ends: districts given 20-40% went Democratic 10% of the time, and those given 60-80% did so 91% of the time. That is the loose priors rather than the national miss: with the national vote known, the 2018 scores barely change. With one midterm to learn from, the 2022 model's intervals are about right (91%).

## Decision

The rule was that the House goes in the forecast only if it beats both references on Brier and vote-share error in 2022. It does, so it can go in. Given the narrow vote-share margin over uniform swing and the 2018 result, I'd present it with that caveat: most of its edge on Brier comes from giving probabilities instead of certain calls, and on vote share it is only a little better than a uniform swing.

## 2026 (first run, 13 October)

National House vote 52.7% Democratic (two-party, sd 1.2 points), as in Stage B. Parameters, fitted on 2018 and 2022: lean slope 0.92, incumbency 0.09 on the logit scale (about 2 points in a close seat), district noise 0.11, state 0.09, region 0.02.

- **Democratic seats: median 232, 80% interval 219-250.**
- **Chance Democrats win 218 or more: 92%.**
- 205 districts at 90% or more for Democrats, 162 at 10% or less, 12 between 40% and 60%.

Outputs: `house_2026.parquet` (district table), `house_seats_2026.csv` (seat distribution), `house_seats_2026_summary.csv`, `house_parameters.csv`.

## Known gaps

- **California 6.** Kevin Kiley, elected as a Republican, is running as an independent against Richard Pan (Democratic) on the new map. With no Republican on the ballot the rule makes it a certain Democratic hold; in reality it is a contest.
- **Louisiana.** The new map's first round is on 3 November with several candidates from each party, and some seats may not be settled until later. The model treats each district as the summed Democratic against Republican vote.
- **Alaska and Maine** use first-round shares (all of a party's candidates summed), not the ranked-choice final round.
- **Nominee changes after 13 October** (for example North Carolina 11, where the member withdrew) need `--refresh`.
- **Correlation** is national, regional and by state only. Districts that move together for other reasons (heavily Hispanic districts in 2024, for example) are treated as independent within a state, so the seat interval may be too narrow.
- **2018 runs on priors alone.** Only the 2022 backtest tests the fitted model, and one midterm is a thin basis for the slopes.
- **Independents standing in for Democrats** (Stage B's Nebraska-style races) are not modelled for the House; no 2026 district has one except California 6 above.

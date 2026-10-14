# Track record for every nominee (13 October)

Written on the branch, not in PLAN.md. The result: it did not pass the rule I set beforehand, so it is built but switched off.

## What I built

Until now only a running incumbent got a track record: their last result for the same office against what a uniform swing predicted. Challengers who have run statewide before (Sherrod Brown in Ohio, Roy Cooper in North Carolina, Doug Jones in Alabama, Mary Peltola in Alaska) got nothing.

The new feature treats the two nominees alike.

- **History.** For each nominee, their most recent earlier statewide general election in the same state: Senate, governor, or an at-large House seat (Alaska, Delaware, Montana before 2022, North Dakota, South Dakota, Vermont, Wyoming). The Wikipedia pages for 2010 to 2024 all parse; the at-large House tables come from the "<year> United States House of Representatives elections" pages, saved under `raw/races/` like the others. Special elections count (Peltola's 2022 special is there, though her 2024 race is the later one).
- **Matching.** First initial plus surname, same state, as `races._surname` already does. A person is matched to the side they ran on in that race (Democratic side or a Republican). Independents standing in for the Democratic side count, minor-party candidates do not (a Libertarian's share says nothing about a Democrat's). `NAMESAKES` still pins Alaska's Dan S. Sullivan.
- **Overperformance.** Their side's two-party share against the state's lean moved by that year's national House vote, on the logit scale, exactly as `track_record` computes it, from the nominee's own side.
- **Feature.** `track_record = dem_record - rep_record`, with a record of 0 for a nominee with no history, or whose last race was not a Democrat against a Republican. Swap the parties and the sign flips. If the two nominees faced each other in that race (Maryland's governor in 2022, Jones and Tuberville in 2020), it counts once. If only the incumbent has a history, it is the same number as before.
- **One coefficient per office**, not separate ones for incumbents and challengers. The 2022 backtest trains on one midterm; I did not expect it to separate two coefficients, and a challenger's record is the same quantity as an incumbent's. I settled this before running anything.

Nominees with a usable statewide history (Democratic side / Republican, out of 71 to 72 races):

| | Democratic side | Republican | Incumbent-only feature was nonzero |
|---|---|---|---|
| 2018 | 30 | 20 | 45 |
| 2022 | 27 | 37 | 53 |
| 2026 | 28 | 26 | 35 |

I checked that the old incumbent columns in `races.parquet` come out unchanged with the history extended back to 2010.

## The rule, set before testing

Keep the feature only if, in `run_race_backtests`, the 2022 backtest (trained on 2018) improves on both Brier score and vote-share error against the current model (Brier 0.0666, error 3.64 points).

## Backtest

Scored on races with a Democrat against a Republican (68 in 2018, 70 in 2022). 2018 runs on priors alone.

| | 2018 Brier | 2018 error (pts) | 2022 Brier | 2022 error (pts) |
|---|---|---|---|---|
| Incumbent-only track record (the model) | 0.1490 | 5.09 | **0.0666** | **3.64** |
| Nominee track record | 0.1493 | 5.09 | 0.0748 | 3.77 |
| No track record | 0.1529 | 5.12 | 0.0724 | 3.87 |
| Plain lean instead of turnout-weighted | 0.1474 | 5.09 | 0.0686 | 3.75 |
| With fundraising | 0.1532 | 5.09 | 0.0690 | 3.72 |

The incumbent-only row reproduces the 5 October numbers exactly.

## Decision

It fails. In 2022 the nominee version is worse on both counts: Brier 0.0748 against 0.0666, error 3.77 points against 3.64. Against no track record at all it is mixed: Brier is worse (0.0748 against 0.0724) and error is slightly better (3.77 against 3.87). In short, it sits much nearer to having no feature than to the incumbent-only one. 2018 cannot say anything either way, as it runs on priors.

So `USE_NOMINEE_TRACK_RECORD` is `False` in `vote_model.py`, as with `USE_FUNDRAISING`. The forecast uses the incumbent-only feature, and the 2026 numbers are unchanged from 5 October (largest difference in any win probability: 0.0). The backtest table keeps both rows.

My guess about why, which I have not tested: a challenger's past result is mostly the state's lean and the national mood of that year, which the model already has, plus the incumbent they ran against. An incumbent's record is different, because the same person is on the ballot again with the same local ties. With 70 races to learn from there is not much room to find a small second effect.

## What it would have done in 2026

For the record only; none of this is in the forecast. Races where the nominee version moves the Democratic win probability by more than 5 points:

| Race | Before | With nominee record |
|---|---|---|
| Minnesota governor (Klobuchar's 2024 Senate win) | 76% | 91% |
| Alaska Senate (Peltola) | 20% | 35% |
| Ohio Senate special (Brown) | 30% | 40% |
| Alabama governor (Jones) | 8% | 14% |
| North Carolina Senate (Cooper) | 77% | 83% |

Eight races move by more than 2 points. The fitted coefficients barely change (Senate 0.29 against 0.30, governor 0.67 against 0.71), so the moves come from the extra inputs, not from the fit. The two races where a well-known challenger could most change the story, Ohio and Alaska, are exactly where I would not want to lean on a feature that failed its test.

## Files

- `src/forecast/races.py`: `_row` (shared race parsing), `house_at_large`, `statewide_history`, `add_nominee_history`; new `dem_prev_*` and `rep_prev_*` columns.
- `src/forecast/vote_model.py`: `track_record(f, nominees=...)`, the `USE_NOMINEE_TRACK_RECORD` flag.
- `src/forecast/backtest.py`: variants "nominee track record" and "incumbent-only track record".
- `tests/test_vote_model.py`: name matching, symmetry, rematch counted once, known histories.

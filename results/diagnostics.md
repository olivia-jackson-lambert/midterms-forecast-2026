# Forecast v1: Election Diagnostics

**DIAGNOSTIC.** This page asks why forecast v1 missed where it did (issue #24). It does not change v1 or its score: v1 is scored as published in `score_provisional.md` (#15), and every rerun below is a counterfactual run of v1's own code, kept out of that score. **Provisional:** results are AP's pull at 2026-11-04T10:41:53Z, with counting still under way; called races only, and vote-share measures over races with at least 85% of the expected vote counted.

Every rerun uses v1's code as tagged, v1's inputs and v1's random seeds, and changes one named thing. Before any rerun is scored, an unchanged rerun is checked against `forecasts/v1/`: the largest difference in any published number is 0, so the reruns differ from v1 only by the change described.

## Summary

| | Question | Finding | Does it matter? |
|---|---|---|---|
| H1 | Did the generic-ballot correction cause the miss? | Removing the −1.75-point correction nearly halves the mean error (+3.17 to +1.71 points) and lifts 80% coverage from 64% to 82%; Brier 0.030 to 0.022 | Yes: the largest single factor |
| H2 | Did the race polls share a miss? | Poll averages understated Democrats by 2.45 points on average (SD 2.92) across 45 races, 80% in the same direction; no clear relation with poll count or fieldwork date | Yes: a shared miss of about 1.8 times the spread v1 allowed for one |
| H3 | Was the poll weight too low? | On the 45 polled races, polls alone: MAE 3.34 against the blend's 3.38; Brier 0.066 against 0.067 | Little: the two barely differ |
| H4 | Were the intervals too narrow? | The realised House shift (+3.28 points) sat at the 98.9th percentile of v1's simulations; the 90th percentile would need the shared spread about 1.9 times as wide | Yes, but mostly as a consequence of H1 |
| H5 | Did turnout error explain the residual? | Not tested | Waits for near-final counts |
| H6 | Did the polls move after 22 October? | Race averages moved +0.59 points on average toward Democrats by 3 November; the late averages close 23% of the mean poll error, and Senate and governor Brier would have been 0.045 rather than 0.058 | Some: the lock date cost a little, but most of the poll error was there on election morning |

## H1: The National Correction

v1 took the generic ballot on 22 October (54.7% Democratic, two-party) and shifted it by the historical mean of (House vote minus 30 September generic ballot), −1.75 points, giving a national House vote of 52.9%. Two diagnostic reruns remove that correction:

- **Bias 0:** the generic ballot itself as the centre of the national House vote, with v1's spread unchanged.
- **Raw generic ballot:** the generic ballot used as the national House vote outright, with no correction and no national spread. This reading of "the raw generic ballot" in #24 is an interpretation; it isolates what the spread adds.

| Run | Called races | Brier | Log loss | Upsets (expected) | Vote-share races | Mean error | MAE | 80% coverage | Below / above |
|---|---|---|---|---|---|---|---|---|---|
| v1 as published | 424 | 0.030 | 0.096 | 20 (19.8) | 305 | +3.17 | 3.62 | 64% | 4 / 105 |
| DIAGNOSTIC: generic-ballot bias set to 0, spread as v1 | 424 | 0.022 | 0.079 | 10 (21.4) | 305 | +1.71 | 2.73 | 82% | 5 / 51 |
| DIAGNOSTIC: raw generic ballot as the House vote, no correction and no national spread | 424 | 0.022 | 0.077 | 10 (20.2) | 305 | +1.71 | 2.72 | 79% | 6 / 58 |

By office (Brier; MAE; 80% coverage):

| Run | Senate | Governor | House |
|---|---|---|---|
| v1 as published | 0.066; 3.47; 58% | 0.051; 3.73; 69% | 0.025; 3.63; 64% |
| DIAGNOSTIC: generic-ballot bias set to 0, spread as v1 | 0.050; 2.59; 77% | 0.047; 3.55; 73% | 0.017; 2.66; 83% |
| DIAGNOSTIC: raw generic ballot as the House vote, no correction and no national spread | 0.051; 2.57; 73% | 0.047; 3.55; 73% | 0.017; 2.65; 80% |

Removing the correction moves every race toward Democrats, which is the direction of the miss, so all three measures improve. The mean error falls from +3.17 to +1.71 points: the correction accounts for a little under half of the uniform shift, not all of it. The House gains most (MAE 3.63 to 2.66); the governors' races least (3.73 to 3.55), where the mean error was smaller to begin with (+1.81) and most of the error is race-to-race scatter (RMSE 5.05). Dropping the national spread as well (the raw generic ballot) changes little on these measures (coverage 82% against 79%).

The generic ballot itself also understated Democrats. AP's House counts so far give Democrats 55.7% of the two-party House vote (90% of the expected vote counted, 203 districts under 95%; uncontested seats and incomplete western counts make this rough). That is above both v1's 52.9% and the uncorrected generic ballot. In 11 of the 12 earlier cycles the 30 September generic ballot overstated the Democratic House vote; on present counts 2026 is the second exception, after 2008.

Not a cause on these numbers: the choice of cycles. See the generic-ballot check below.

## H2: A Shared Polling Miss

Error is the actual Democratic two-party share minus v1's race poll average (`poll_avg`), in points, over the 45 scored Senate and governor races that had polls.

| | Races | Mean | SD | MAE | RMSE |
|---|---|---|---|---|---|
| All with polls | 45 | +2.45 | 2.92 | 3.34 | 3.79 |
| Senate | 21 | +3.21 | 2.12 | 3.36 | 3.82 |
| Governor | 24 | +1.79 | 3.38 | 3.32 | 3.76 |
| 1 to 4 polls | 20 | +2.41 | 3.78 | 3.82 | 4.40 |
| 5 or more polls | 25 | +2.49 | 2.07 | 2.96 | 3.21 |

80% of the averages understated the Democrat. On the logit scale the mean miss was 0.103, against a shared polling error of SD 0.059 in v1's poll-error model (fitted on 2018 and 2022): 1.76 standard deviations. Around that shared miss, races scattered less than v1 expected (SD 0.127 against 0.160). The polling error was mostly common to all races rather than race by race, which is the pattern that intervals built from independent race errors cannot absorb.

What the race error does and does not relate to (correlation with the race's error, Pearson and Spearman):

| Feature of the race's polls | Races | Pearson r (p) | Spearman ρ (p) |
|---|---|---|---|
| Number of polls | 45 | 0.13 (0.404) | 0.04 (0.769) |
| Effective number of polls | 45 | 0.13 (0.407) | 0.06 (0.690) |
| Weighted mean fieldwork age (days) | 45 | −0.02 (0.897) | −0.16 (0.288) |
| Age of the newest poll (days) | 45 | −0.06 (0.696) | −0.33 (0.026) |
| Weight on Republican-labelled polls | 45 | 0.27 (0.069) | 0.26 (0.090) |
| Weight on Democratic-labelled polls | 45 | −0.39 (0.008) | −0.49 (0.001) |
| Weight on likely-voter polls | 45 | −0.08 (0.621) | −0.11 (0.470) |

Poll by poll (each poll that entered an average, against its race's result):

| Polls | Number | Mean error | SD | MAE |
|---|---|---|---|---|
| Republican-labelled | 116 | +3.69 | 2.35 | 3.87 |
| Unlabelled | 204 | +2.62 | 2.96 | 3.30 |
| Democratic-labelled | 47 | +1.04 | 2.95 | 2.44 |
| Fieldwork ended 0-14 days before 22 October | 108 | +2.94 | 2.87 | 3.61 |
| Fieldwork ended 15-28 days before 22 October | 110 | +2.52 | 2.56 | 2.91 |
| Fieldwork ended 29-56 days before 22 October | 108 | +3.00 | 2.95 | 3.54 |
| Fieldwork ended 57-90 days before 22 October | 41 | +2.26 | 3.52 | 3.52 |

Neither the number of polls nor fieldwork date shows a reliable relation with the error: races with many polls missed by about as much on average as races with few, though with less scatter, and recent polls missed by as much as older ones (poll-level correlation with age −0.04). Pollster mix does show one: the more weight on polls Wikipedia labels as Republican-sponsored, the larger the miss, and Democratic-labelled polls missed least. Even the Democratic-labelled polls understated Democrats on average, so the mix shifts the size of the miss, not its sign. With seven features tested on 45 races, the p-values are indicative only. Labels are Wikipedia's sponsor marks, so unlabelled polls include partisan pollsters that are not marked.

Largest race misses: RI-GOV (+7.5, 4 polls), AL-SEN (+7.0, 2 polls), OK-SEN (+6.8, 1 poll), TN-GOV (+6.5, 3 polls), TN-SEN (+6.0, 1 poll), GA-GOV (+5.2, 7 polls).

## H3: The Blend Weight

Polls alone uses v1's own poll-error model: the result is centred on the poll average with v1's poll-error variance (shared, floor and per-poll terms), giving a median, an 80% interval and a win probability. Races with no polls have no polls-only forecast; there the blend is the fundamentals.

| Polls in the race | Called | Mean poll weight | Brier: blend | fundamentals | polls only | Vote races | MAE: blend | fundamentals | polls only | Coverage: blend | polls only |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Any (1 or more) | 53 | 0.65 | 0.067 | 0.105 | 0.066 | 45 | 3.38 | 4.73 | 3.34 | 64% | 78% |
| 0 | 11 | 0.00 | 0.013 | 0.013 | – | 7 | 5.04 | 5.04 | – | 57% | – |
| 1 to 4 | 25 | 0.55 | 0.018 | 0.023 | 0.037 | 20 | 3.78 | 5.71 | 3.82 | 65% | 85% |
| 5 or more | 28 | 0.74 | 0.112 | 0.178 | 0.091 | 25 | 3.06 | 3.96 | 2.96 | 64% | 72% |
| All races | 64 | 0.54 | 0.058 | 0.089 | 0.066 | 52 | 3.60 | 4.78 | 3.34 | 63% | 78% |

Both inputs understated Democrats, the fundamentals by more, so in this election any weight on the fundamentals cost accuracy: in hindsight, the weight on the poll average that minimises squared error over the 45 polled races is 0.96, against v1's mean of 0.64 (descriptive only, not a refit; one year of error in one direction is a poor guide to the weight). Yet over all polled races polls alone and the blend are almost level; #24's election-night figures, on fewer races, had polls alone further ahead. The comparison differs by poll count. With one to four polls, polls alone are no better on vote share and worse on Brier: their uncertainty is wide, so they give the favourite less than the blend does in races the favourite won (VT-GOV, LA-SEN, OR-GOV, OK-GOV). With five or more polls, polls alone beat the blend on both. A higher poll weight would have helped a little where polls were plentiful, but H3 is not where most of the error came from, and it is partly H1 in another form: the fundamentals were pulled toward Republicans by the same national correction.

## H4: Interval Width

Report only; nothing is refitted.

v1's national House vote was a Student-t with 11 degrees of freedom and scale 1.19 points (SD 1.32 points; 90th percentile +1.62 points above the mean).

| | Races | Realised mean shift (points) | Simulated SD of the mean shift | v1 90th percentile | Percentile of the realised shift | Widening needed for 90th | SD needed |
|---|---|---|---|---|---|---|---|
| House (contested, scored) | 253 | +3.28 | 1.35 | +1.69 | 98.9th | 1.95× | 2.62 |
| Senate and governor (scored) | 52 | +2.64 | 1.11 | +1.40 | 98.8th | 1.89× | 2.11 |

The simulated mean shift is the average, over the same scored races, of each simulation's deviation from v1's medians: it carries the national term and the shared regional and state terms together. For the national term alone, the realised House shift on the logit scale (0.149, about 3.72 points near v1's mean) sits at the 99.5th percentile of v1's t; putting it at the 90th would need a scale of about 2.73 points (SD about 3.02), 2.3 times v1's.

Two readings follow, and they point in different directions. The spread v1 used is the scatter of the 12 earlier cycles' generic-ballot errors around their mean (from −3.6 to +0.7 points); a 2026 miss of this size lies outside that history, so a wider national term, or a heavier tail, is a fair conclusion. But the interval was not only narrow; it was in the wrong place. With the correction removed (H1), coverage across all scored races is 82% with v1's spread unchanged. Most of the coverage shortfall is the centre, and widening alone would have bought coverage with weaker calls.

## H5: Turnout

**Waiting.** Counts are not near final: across House races, 90% of the expected vote is counted, and 203 districts are under 95%. Turnout needs total ballots cast by county, over v1's citizen voting-age population denominators, which come with certification. Until then the turnout-first stage is untested, and whether county turnout error explains any of the vote-share residual after the uniform shift is unknown.

## H6: The Late Swing

Source: each race's Wikipedia article as it stood at 12:00 UTC on 3 November (7 am Eastern on election day), parsed and averaged with v1's own code and rules (one poll per pollster, 21-day half-life, 90-day window), with the cut-off moved from 22 October to 3 November. Silver Bulletin's and Decision Desk HQ's own timelines were not used: neither is in the repository's data and the averages here follow v1's definition, which theirs do not.

| | Value |
|---|---|
| Races with polls: 22 October / 3 November | 59 / 61 |
| Polls with fieldwork ending after 22 October | 276 (in 50 races) |
| Movement of the average, 22 October to 3 November (toward Democrats) | mean +0.59, SD 1.22, mean absolute 0.89 points over 59 races |
| Races whose average moved toward Democrats | 66% |
| Polls listed after 22 October but fielded before it (same cut-off) | mean +0.15 points over 59 races |
| Scored races: mean error of v1's average / of the 3 November average | +2.45 / +1.89 points (45 races) |
| MAE of v1's average / of the 3 November average | 3.34 / 2.74 |

DIAGNOSTIC reruns with the 3 November averages (this looks past v1's lock date, so it measures what the lock date cost, not what v1 could have known):

| Run | Brier (all) | Senate and governor Brier | MAE (all) | Mean error | 80% coverage |
|---|---|---|---|---|---|
| v1 as published | 0.030 | 0.058 | 3.62 | +3.17 | 64% |
| DIAGNOSTIC: 3 November poll averages | 0.028 | 0.045 | 3.56 | +3.11 | 65% |
| DIAGNOSTIC: bias 0 and 3 November poll averages | 0.021 | 0.039 | 2.66 | +1.66 | 83% |

Averages moved +0.59 points on average. Over the scored races the 3 November averages close 23% of v1's mean poll error. The late movement was small next to the miss: most of the poll error was still there on election morning, so on this evidence the polls were mainly wrong, and the lock date cost comparatively little.

The generic ballot on the same page at the same time (mean of Decision Desk HQ, FiftyPlusOne, NBC News, RealClearPolitics, Silver Bulletin; revision 1383555060) was 54.6% Democratic, two-party, against 54.7% on 22 October.

## Checks

**Generic-ballot cycles.** `python -m forecast.generic_ballot` gives `n_years` = 12 for 2026. The years used are 1998, 2000, 2002, 2004, 2006, 2008, 2010, 2012, 2014, 2016, 2018, 2022. The even years 2020 and 2024 drop out because no 30 September generic-ballot value is collected for them (`generic_ballot()` reads 1998 to 2016 from FiveThirtyEight's history, 2018 from its archived file and 2022 from Wikipedia), although their House votes are read. The write-up's "11 of the 12 cycles since 1998" is therefore right in count, and #24's concern that the code averages 14 cycles does not hold; the wording would be clearer as "12 of the 14 cycles from 1998 to 2024 (2020 and 2024 lack a 30 September value)". The docstring's "every even year before `year` with both numbers" is accurate. One related point: the bias is estimated from end-of-September values (18 to 30 September), but 2026 used the value on 22 October, about three weeks later and closer to the election, when the generic ballot's historical overstatement may be smaller. That mismatch is untested.

**Minnesota count order.** The snapshot in #24 saw Republicans ahead in both Minnesota races early in the count, before both went to the Democrats. The repository cannot show the early lead: its first pull (2026-11-04T06:40:11Z) came after both calls (MN-GOV 57.1% Democratic with 94% counted, called at 05:07 UTC; MN-SEN 55.8% Democratic with 94% counted, called at 05:07 UTC). Early returns are ordered by how each county reports and by ballot type (in-person and mail are counted and released at different times), so an early lead says little about the result; the write-up should say so in a line before reading early returns as signal. The Internet Archive holds a capture of AP's national feed at 05:04 UTC on 4 November, just before both calls, which could document the early count if needed; it has not been downloaded here.

**Archiving the AP feed.** The project keeps AP's raw files for its own 3 pulls (20261104T064011Z, 20261104T075718Z, 20261104T104153Z) under `data/raw/results_2026/` (local, not committed, as they are AP's). Publicly, the Internet Archive's index (queried 4 November) holds captures of the national `progress.json` and `metadata.json` at 04:28, 17:02 and 20:03 UTC on 3 November (before polls closed) and one at 05:04 UTC on 4 November (election night), plus some per-state and per-race files; the index showed none later at the time of the query. The #24 note that a direct `curl` returned a stub is explained in `results/README.md`: the files are gzip bytes, not a stub. No new archive request was made; saving the feed through the Internet Archive while it still shows the election-night state is still open.

**Final counts.** This page should be rerun on final counts (`python -m forecast.diagnostics --pull <id>` after a new pull); #24 notes that late mail in the West tends to lean Democratic, so the shift may grow.

## Through Time

**DIAGNOSTIC.** v1's own code rerun as it would have stood on seven dates, each with only what was public that day (issue #29). v1 as published on 22 October remains the forecast of record and its score (#15) is unchanged; none of these reruns is part of it. Scored against AP's pull at 2026-11-04T10:41:53Z (provisional), with the measures used above.

On each date the race polls are the Wikipedia race articles at their last revision on or before 23:59:59 UTC, averaged with v1's rules relative to that date, and the generic ballot is the aggregators' mean on the 2026 House page at the same revision time. Everything else is v1's: the fits, the generic-ballot bias and spread, the candidates and incumbents as of 22 October, and the seeds. The 22 October rerun uses v1's own saved inputs and reproduces `forecasts/v1/` exactly (largest difference 0 in the tables, 0 in the seat distributions).

| Date | Run | Generic ballot (D, 2-party) | House vote centre | Races polled | Senate D | House D | Governors D | House seats (80%) | Brier | Log loss | Upsets (exp.) | Mean error | MAE | 80% coverage |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 Sep | as built | 53.5% | 51.8% | 52 | 45% | 77% | 44% | 225 (212–241) | 0.040 | 0.123 | 26 (19.0) | +4.20 | 4.47 | 57% |
| 1 Sep | bias 0 | 53.5% | 53.5% | 52 | 67% | 97% | 63% | 239 (224–258) | 0.028 | 0.094 | 16 (20.4) | +2.70 | 3.29 | 71% |
| 15 Sep | as built | 54.0% | 52.3% | 55 | 52% | 86% | 48% | 229 (215–245) | 0.035 | 0.111 | 24 (19.6) | +3.78 | 4.11 | 60% |
| 15 Sep | bias 0 | 54.0% | 54.0% | 55 | 73% | 98% | 65% | 243 (227–263) | 0.025 | 0.087 | 13 (21.0) | +2.30 | 3.03 | 77% |
| 1 Oct | as built | 54.5% | 52.8% | 55 | 60% | 92% | 58% | 233 (219–250) | 0.031 | 0.099 | 21 (20.0) | +3.32 | 3.71 | 65% |
| 1 Oct | bias 0 | 54.5% | 54.5% | 55 | 77% | 99% | 73% | 248 (231–269) | 0.023 | 0.081 | 10 (21.5) | +1.84 | 2.77 | 82% |
| 15 Oct | as built | 54.4% | 52.7% | 57 | 64% | 91% | 61% | 232 (218–249) | 0.031 | 0.099 | 22 (19.6) | +3.39 | 3.77 | 64% |
| 15 Oct | bias 0 | 54.4% | 54.4% | 57 | 79% | 99% | 75% | 247 (230–268) | 0.022 | 0.080 | 12 (21.3) | +1.92 | 2.80 | 81% |
| 22 Oct (v1) | as built | 54.7% | 52.9% | 59 | 63% | 93% | 62% | 234 (219–252) | 0.030 | 0.096 | 20 (19.8) | +3.17 | 3.62 | 64% |
| 22 Oct | bias 0 | 54.7% | 54.7% | 59 | 78% | 99% | 75% | 249 (232–271) | 0.022 | 0.079 | 10 (21.4) | +1.71 | 2.73 | 82% |
| 29 Oct | as built | 54.5% | 52.8% | 59 | 66% | 92% | 65% | 232 (218–250) | 0.030 | 0.096 | 19 (19.6) | +3.27 | 3.70 | 65% |
| 29 Oct | bias 0 | 54.5% | 54.5% | 59 | 80% | 99% | 77% | 248 (231–269) | 0.022 | 0.078 | 9 (21.1) | +1.82 | 2.75 | 82% |
| 2 Nov | as built | 54.6% | 52.8% | 61 | 70% | 92% | 74% | 233 (219–251) | 0.029 | 0.093 | 19 (19.5) | +3.21 | 3.63 | 65% |
| 2 Nov | bias 0 | 54.6% | 54.6% | 61 | 83% | 99% | 84% | 248 (231–269) | 0.021 | 0.076 | 9 (21.0) | +1.76 | 2.70 | 83% |

Scores are over all called races (Senate, governor and House); vote-share measures over races with at least 85% counted. By office, Brier and mean error:

| Date | Run | Senate | Governor | House |
|---|---|---|---|---|
| 1 Sep | as built | 0.087; +4.25 | 0.071; +3.16 | 0.033; +4.30 |
| 1 Sep | bias 0 | 0.069; +3.12 | 0.066; +2.28 | 0.022; +2.70 |
| 15 Sep | as built | 0.078; +3.90 | 0.061; +2.89 | 0.029; +3.86 |
| 15 Sep | bias 0 | 0.061; +2.83 | 0.055; +2.11 | 0.019; +2.26 |
| 1 Oct | as built | 0.069; +3.56 | 0.053; +2.25 | 0.026; +3.40 |
| 1 Oct | bias 0 | 0.052; +2.55 | 0.049; +1.53 | 0.018; +1.80 |
| 15 Oct | as built | 0.064; +3.53 | 0.051; +2.07 | 0.027; +3.51 |
| 15 Oct | bias 0 | 0.049; +2.57 | 0.047; +1.40 | 0.018; +1.91 |
| 22 Oct | as built | 0.066; +3.47 | 0.051; +1.81 | 0.025; +3.28 |
| 22 Oct | bias 0 | 0.050; +2.53 | 0.047; +1.25 | 0.017; +1.68 |
| 29 Oct | as built | 0.063; +3.40 | 0.044; +1.77 | 0.026; +3.41 |
| 29 Oct | bias 0 | 0.048; +2.48 | 0.041; +1.24 | 0.018; +1.81 |
| 2 Nov | as built | 0.056; +3.28 | 0.041; +1.45 | 0.026; +3.38 |
| 2 Nov | bias 0 | 0.043; +2.37 | 0.038; +0.93 | 0.018; +1.78 |

Across the seven dates the generic ballot v1 would have read ranged from 53.5% to 54.7% Democratic, and the as-built rerun's mean error toward Democrats stayed between +3.17 and +4.20 points (Brier 0.029 to 0.040): no lock date from 1 Sep to 2 Nov would have removed the Republican lean of the miss. Setting the generic-ballot bias to 0 lowers the mean error on every date (to between +1.71 and +2.70 points), by more than any change of date does, so the correction matters more than the lock date. What moved was the generic ballot, which carries the House (77% to 92% for Democrats), and, for the Senate (45% to 70%) and governors (44% to 74%), the race polls: more races polled (52 to 61) and averages that, over races polled on both dates, differed from v1's by −0.30 to +0.54 points on average.

**Limits.** Candidates and incumbents are v1's as of 22 October on every date, so on the early dates a race whose primary had not yet been held is modelled with its eventual nominees, and its polls are matched to them: a small look-ahead in the early reruns. The generic ballot is what the House page listed, which can lag the aggregators' own updates. As a check on the method, the 22 October inputs rebuilt from revisions give 59 races with polls against v1's 59, the same number of polls in 60 of 60 races, and poll averages within 0.02 points; the generic ballot 54.66% against v1's 54.66%.

## Files

- `results/diagnostics.json`: the numbers on this page.
- `src/forecast/diagnostics.py`: the code (`python -m forecast.diagnostics`); `tests/test_diagnostics.py`.
- Rerun tables (local, not committed, each marked DIAGNOSTIC): `data/processed/diagnostics_v1/<run>/`.
- 3 November Wikipedia revisions (local): `data/raw/polls_late_2026/`.
- `results/through_time.json` and the Through Time section: `src/forecast/through_time.py` (`python -m forecast.through_time`, run after `forecast.diagnostics`, which rewrites this page).

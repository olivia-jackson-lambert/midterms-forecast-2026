# Forecast v1: Election Diagnostics

**DIAGNOSTIC.** This page asks why forecast v1 missed where it did (issue #24). It does not change v1 or its score: v1 is scored as published in `score_provisional.md` (#15), and every rerun below is a counterfactual run of v1's own code, kept out of that score. **Provisional:** results are AP's pull at 2026-11-08T22:59:13Z, with counting still under way; called races only, and vote-share measures over races with at least 85% of the expected vote counted.

Every rerun uses v1's code as tagged, v1's inputs and v1's random seeds, and changes one named thing. Before any rerun is scored, an unchanged rerun is checked against `forecasts/v1/`: the largest difference in any published number is 0, so the reruns differ from v1 only by the change described.

## Summary

| | Question | Finding | Does it matter? |
|---|---|---|---|
| H1 | Did the generic-ballot correction cause the miss? | Removing the −1.75-point correction nearly halves the mean error (+3.12 to +1.64 points) and lifts 80% coverage from 66% to 81%; Brier 0.044 to 0.033 | Yes: the largest single factor |
| H2 | Did the race polls share a miss? | Poll averages understated Democrats by 2.23 points on average (SD 3.07) across 52 races, 79% in the same direction; no clear relation with poll count or fieldwork date | Yes: a shared miss of about 1.6 times the spread v1 allowed for one |
| H3 | Was the poll weight too low? | On the 52 polled races, polls alone: MAE 3.27 against the blend's 3.36; Brier 0.066 against 0.067 | Little: the two barely differ |
| H4 | Were the intervals too narrow? | The realised House shift (+3.27 points) sat at the 99.0th percentile of v1's simulations; the 90th percentile would need the shared spread about 2.0 times as wide | Yes, but mostly as a consequence of H1 |
| H5 | Did turnout error explain the residual? | Not tested | Waits for near-final counts |
| H6 | Did the polls move after 22 October? | Race averages moved +0.59 points on average toward Democrats by 3 November; the late averages close 24% of the mean poll error, and Senate and governor Brier would have been 0.045 rather than 0.058 | Some: the lock date cost a little, but most of the poll error was there on election morning |
| H7 | Would removing pollster house effects have helped? | House effects for 337 pollsters (127 in three or more races) moved the race averages +0.12 points on average; the mean error is unchanged at +3.12 points and the Brier score is unchanged at 0.044 (with H1: 0.032) | Little overall, some for the polled races (Senate and governor Brier 0.058 to 0.052); the shared miss remains |
| H8 | Would leaving out partisan polls have helped? | 4 races lose all their polls; the rest move +0.31 points on average; the mean error is unchanged at +3.12 points and the Brier score moves from 0.044 to 0.045 (with H1: 0.033) | Little: the scores barely move (Senate and governor Brier 0.058 to 0.060) |

## H1: The National Correction

v1 took the generic ballot on 22 October (54.7% Democratic, two-party) and shifted it by the historical mean of (House vote minus 30 September generic ballot), −1.75 points, giving a national House vote of 52.9%. Two diagnostic reruns remove that correction:

- **Bias 0:** the generic ballot itself as the centre of the national House vote, with v1's spread unchanged.
- **Raw generic ballot:** the generic ballot used as the national House vote outright, with no correction and no national spread. This reading of "the raw generic ballot" in #24 is an interpretation; it isolates what the spread adds.

| Run | Called races | Brier | Log loss | Upsets (expected) | Vote-share races | Mean error | MAE | 80% coverage | Below / above |
|---|---|---|---|---|---|---|---|---|---|
| v1 as published | 477 | 0.044 | 0.139 | 32 (27.9) | 424 | +3.12 | 3.68 | 66% | 6 / 140 |
| DIAGNOSTIC: generic-ballot bias set to 0, spread as v1 | 477 | 0.033 | 0.112 | 18 (31.4) | 424 | +1.64 | 2.82 | 81% | 8 / 71 |
| DIAGNOSTIC: raw generic ballot as the House vote, no correction and no national spread | 477 | 0.033 | 0.110 | 18 (29.6) | 424 | +1.63 | 2.82 | 78% | 12 / 83 |

By office (Brier; MAE; 80% coverage):

| Run | Senate | Governor | House |
|---|---|---|---|
| v1 as published | 0.066; 3.69; 60% | 0.051; 3.56; 79% | 0.042; 3.69; 65% |
| DIAGNOSTIC: generic-ballot bias set to 0, spread as v1 | 0.050; 2.96; 77% | 0.047; 3.31; 82% | 0.031; 2.76; 82% |
| DIAGNOSTIC: raw generic ballot as the House vote, no correction and no national spread | 0.051; 2.96; 73% | 0.047; 3.31; 82% | 0.030; 2.76; 78% |

Removing the correction moves every race toward Democrats, which is the direction of the miss, so all three measures improve. The mean error falls from +3.12 to +1.64 points: the correction accounts for a little under half of the uniform shift, not all of it. The House gains most (MAE 3.69 to 2.76); the governors' races least (3.56 to 3.31), where the mean error was smaller to begin with (+1.97) and most of the error is race-to-race scatter (RMSE 4.83). Dropping the national spread as well (the raw generic ballot) changes little on these measures (coverage 81% against 78%).

The generic ballot itself also understated Democrats. AP's House counts so far give Democrats 56.5% of the two-party House vote (95% of the expected vote counted, 111 districts under 95%; uncontested seats and incomplete western counts make this rough). That is above both v1's 52.9% and the uncorrected generic ballot. In 11 of the 12 earlier cycles the 30 September generic ballot overstated the Democratic House vote; on present counts 2026 is the second exception, after 2008.

Not a cause on these numbers: the choice of cycles. See the generic-ballot check below.

## H2: A Shared Polling Miss

Error is the actual Democratic two-party share minus v1's race poll average (`poll_avg`), in points, over the 52 scored Senate and governor races that had polls.

| | Races | Mean | SD | MAE | RMSE |
|---|---|---|---|---|---|
| All with polls | 52 | +2.23 | 3.07 | 3.27 | 3.77 |
| Senate | 23 | +2.66 | 3.08 | 3.46 | 4.02 |
| Governor | 29 | +1.90 | 3.07 | 3.11 | 3.57 |
| 1 to 4 polls | 25 | +2.39 | 3.46 | 3.54 | 4.15 |
| 5 or more polls | 27 | +2.09 | 2.72 | 3.01 | 3.39 |

79% of the averages understated the Democrat. On the logit scale the mean miss was 0.091, against a shared polling error of SD 0.059 in v1's poll-error model (fitted on 2018 and 2022): 1.56 standard deviations. Around that shared miss, races scattered less than v1 expected (SD 0.140 against 0.160). The polling error was mostly common to all races rather than race by race, which is the pattern that intervals built from independent race errors cannot absorb.

What the race error does and does not relate to (correlation with the race's error, Pearson and Spearman):

| Feature of the race's polls | Races | Pearson r (p) | Spearman ρ (p) |
|---|---|---|---|
| Number of polls | 52 | 0.10 (0.480) | 0.04 (0.785) |
| Effective number of polls | 52 | 0.12 (0.408) | 0.06 (0.672) |
| Weighted mean fieldwork age (days) | 52 | −0.02 (0.864) | −0.17 (0.243) |
| Age of the newest poll (days) | 52 | −0.02 (0.870) | −0.27 (0.052) |
| Weight on Republican-labelled polls | 52 | 0.15 (0.283) | 0.22 (0.115) |
| Weight on Democratic-labelled polls | 52 | −0.24 (0.081) | −0.34 (0.012) |
| Weight on likely-voter polls | 52 | −0.07 (0.610) | −0.00 (0.984) |

Poll by poll (each poll that entered an average, against its race's result):

| Polls | Number | Mean error | SD | MAE |
|---|---|---|---|---|
| Republican-labelled | 126 | +3.55 | 2.72 | 3.92 |
| Unlabelled | 226 | +2.35 | 3.18 | 3.25 |
| Democratic-labelled | 53 | +0.52 | 4.12 | 2.97 |
| Fieldwork ended 0-14 days before 22 October | 118 | +2.61 | 3.27 | 3.58 |
| Fieldwork ended 15-28 days before 22 October | 117 | +2.42 | 2.75 | 2.95 |
| Fieldwork ended 29-56 days before 22 October | 117 | +2.74 | 3.15 | 3.48 |
| Fieldwork ended 57-90 days before 22 October | 53 | +1.76 | 4.62 | 3.96 |

Neither the number of polls nor fieldwork date shows a reliable relation with the error: races with many polls missed by about as much on average as races with few, though with less scatter, and recent polls missed by as much as older ones (poll-level correlation with age −0.08). Pollster mix does show one: the more weight on polls Wikipedia labels as Republican-sponsored, the larger the miss, and Democratic-labelled polls missed least. Even the Democratic-labelled polls understated Democrats on average, so the mix shifts the size of the miss, not its sign. With seven features tested on 45 races, the p-values are indicative only. Labels are Wikipedia's sponsor marks, so unlabelled polls include partisan pollsters that are not marked.

Largest race misses: MT-SEN (−7.7, 9 polls), RI-GOV (+7.6, 4 polls), AL-SEN (+7.0, 2 polls), OK-SEN (+6.9, 1 poll), TN-GOV (+6.5, 3 polls), TN-SEN (+6.0, 1 poll).

## H3: The Blend Weight

Polls alone uses v1's own poll-error model: the result is centred on the poll average with v1's poll-error variance (shared, floor and per-poll terms), giving a median, an 80% interval and a win probability. Races with no polls have no polls-only forecast; there the blend is the fundamentals.

| Polls in the race | Called | Mean poll weight | Brier: blend | fundamentals | polls only | Vote races | MAE: blend | fundamentals | polls only | Coverage: blend | polls only |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Any (1 or more) | 53 | 0.65 | 0.067 | 0.105 | 0.066 | 52 | 3.36 | 5.03 | 3.27 | 69% | 83% |
| 0 | 11 | 0.00 | 0.013 | 0.013 | – | 11 | 4.88 | 4.88 | – | 73% | – |
| 1 to 4 | 25 | 0.55 | 0.018 | 0.023 | 0.037 | 25 | 3.40 | 5.48 | 3.54 | 68% | 88% |
| 5 or more | 28 | 0.74 | 0.112 | 0.178 | 0.091 | 27 | 3.32 | 4.61 | 3.01 | 70% | 78% |
| All races | 64 | 0.54 | 0.058 | 0.089 | 0.066 | 63 | 3.62 | 5.00 | 3.27 | 70% | 83% |

Both inputs understated Democrats, the fundamentals by more, so in this election any weight on the fundamentals cost accuracy: in hindsight, the weight on the poll average that minimises squared error over the 52 polled races is 1.03, against v1's mean of 0.65 (descriptive only, not a refit; one year of error in one direction is a poor guide to the weight). Yet over all polled races polls alone and the blend are almost level; #24's election-night figures, on fewer races, had polls alone further ahead. The comparison differs by poll count. With one to four polls, polls alone are no better on vote share and worse on Brier: their uncertainty is wide, so they give the favourite less than the blend does in races the favourite won (VT-GOV, LA-SEN, OR-GOV, OK-GOV). With five or more polls, polls alone beat the blend on both. A higher poll weight would have helped a little where polls were plentiful, but H3 is not where most of the error came from, and it is partly H1 in another form: the fundamentals were pulled toward Republicans by the same national correction.

## H4: Interval Width

Report only; nothing is refitted.

v1's national House vote was a Student-t with 11 degrees of freedom and scale 1.19 points (SD 1.32 points; 90th percentile +1.62 points above the mean).

| | Races | Realised mean shift (points) | Simulated SD of the mean shift | v1 90th percentile | Percentile of the realised shift | Widening needed for 90th | SD needed |
|---|---|---|---|---|---|---|---|
| House (contested, scored) | 361 | +3.27 | 1.33 | +1.65 | 99.0th | 1.98× | 2.64 |
| Senate and governor (scored) | 63 | +2.25 | 1.09 | +1.36 | 97.8th | 1.66× | 1.81 |

The simulated mean shift is the average, over the same scored races, of each simulation's deviation from v1's medians: it carries the national term and the shared regional and state terms together. For the national term alone, the realised House shift on the logit scale (0.150, about 3.74 points near v1's mean) sits at the 99.5th percentile of v1's t; putting it at the 90th would need a scale of about 2.75 points (SD about 3.04), 2.3 times v1's.

Two readings follow, and they point in different directions. The spread v1 used is the scatter of the 12 earlier cycles' generic-ballot errors around their mean (from −3.6 to +0.7 points); a 2026 miss of this size lies outside that history, so a wider national term, or a heavier tail, is a fair conclusion. But the interval was not only narrow; it was in the wrong place. With the correction removed (H1), coverage across all scored races is 81% with v1's spread unchanged. Most of the coverage shortfall is the centre, and widening alone would have bought coverage with weaker calls.

## H5: Turnout

**Waiting.** Counts are not near final: across House races, 95% of the expected vote is counted, and 111 districts are under 95%. Turnout needs total ballots cast by county, over v1's citizen voting-age population denominators, which come with certification. Until then the turnout-first stage is untested, and whether county turnout error explains any of the vote-share residual after the uniform shift is unknown.

## H6: The Late Swing

Source: each race's Wikipedia article as it stood at 12:00 UTC on 3 November (7 am Eastern on election day), parsed and averaged with v1's own code and rules (one poll per pollster, 21-day half-life, 90-day window), with the cut-off moved from 22 October to 3 November. Silver Bulletin's and Decision Desk HQ's own timelines were not used: neither is in the repository's data and the averages here follow v1's definition, which theirs do not.

| | Value |
|---|---|
| Races with polls: 22 October / 3 November | 59 / 61 |
| Polls with fieldwork ending after 22 October | 276 (in 50 races) |
| Movement of the average, 22 October to 3 November (toward Democrats) | mean +0.59, SD 1.22, mean absolute 0.89 points over 59 races |
| Races whose average moved toward Democrats | 66% |
| Polls listed after 22 October but fielded before it (same cut-off) | mean +0.15 points over 59 races |
| Scored races: mean error of v1's average / of the 3 November average | +2.23 / +1.70 points (52 races) |
| MAE of v1's average / of the 3 November average | 3.27 / 2.76 |

DIAGNOSTIC reruns with the 3 November averages (this looks past v1's lock date, so it measures what the lock date cost, not what v1 could have known):

| Run | Brier (all) | Senate and governor Brier | MAE (all) | Mean error | 80% coverage |
|---|---|---|---|---|---|
| v1 as published | 0.044 | 0.058 | 3.68 | +3.12 | 66% |
| DIAGNOSTIC: 3 November poll averages | 0.043 | 0.045 | 3.63 | +3.07 | 66% |
| DIAGNOSTIC: bias 0 and 3 November poll averages | 0.032 | 0.039 | 2.77 | +1.60 | 82% |

Averages moved +0.59 points on average. Over the scored races the 3 November averages close 24% of v1's mean poll error. The late movement was small next to the miss: most of the poll error was still there on election morning, so on this evidence the polls were mainly wrong, and the lock date cost comparatively little.

The generic ballot on the same page at the same time (mean of Decision Desk HQ, FiftyPlusOne, NBC News, RealClearPolitics, Silver Bulletin; revision 1383555060) was 54.6% Democratic, two-party, against 54.7% on 22 October.

## H7: Pollster House Effects

**DIAGNOSTIC.** A house effect is a pollster's persistent lean relative to other pollsters polling the same race. Forecasters such as the Silver Bulletin estimate it and remove it before averaging; its public methodology page describes an iterative comparison of each firm with the average, with the share of a firm's gap that is removed growing with how much it has polled. This rerun asks whether a simple version of that adjustment would have reduced v1's miss.

Method, fixed before scoring:

- **Polls.** Head-to-head polls from the same Wikipedia race articles v1 used: 2018 and 2022 Senate and governor races (fieldwork ending in the 90 days up to election day; all of these were public long before 22 October 2026) and 2026 races (fieldwork ending in the 90 days up to v1's 22 October cut-off, never later). Each pollster's polls in a race are averaged first, so a pollster counts once per race however often it polled there.
- **Model.** On the two-party share, each pollster-race average = a race effect + the pollster's house effect + noise. The race effects are free, so a house effect measures only how a pollster differs from the others in the races it shared with them; races polled by a single pollster carry no information and are dropped. The house effects are treated as random, Normal(0, τ²), around noise of variance σ², with both variances estimated from the data (EM): σ = 2.07 and τ = 2.02 points.
- **Shrinkage.** Each house effect is then the standard shrunken estimate: the pollster's mean deviation from the race effects, multiplied by n / (n + σ²/τ²), where n is its number of races and σ²/τ² = 1.05. A pollster seen in one race keeps about 49% of its raw deviation, one seen in ten races about 90%. The reference is the average pollster in these data (each pollster counted once; the effects sum to zero), not the result: removing house effects cannot correct a miss that all pollsters share.
- **Rerun.** Each 2026 poll's share has its pollster's house effect subtracted (pollsters with no estimate are left as they are), and v1's averages are rebuilt with v1's own code: one poll per pollster, 90-day window, 21-day half-life, sample-size and population weights. Everything else is v1's: fits, poll-error model, seeds and generic-ballot correction.
- **Pollster names.** v1's pollster key (sponsors in brackets dropped), with a leading "the", a trailing "inc" and the spacing around "/" tidied. Names are not otherwise harmonised, so a firm that appears under several names (Siena with different media partners, for example) is estimated under each, with fewer races and more shrinkage.

House effects were estimated for 337 pollsters from 1563 pollster-race averages in 169 races; 127 pollsters appear in three or more races. As a check during development, a REML linear mixed model with the same structure (statsmodels MixedLM, not a project dependency) gave practically the same effects (correlation 0.9996, largest difference 0.5 points); the 2026 polls are those before the cut-off, so a new results pull does not change them. Positive means more Democratic than the other pollsters in the same races. The largest among pollsters in three or more races:

| Pollster | Races | House effect (points) | Raw deviation | Share of its polls labelled R / D | Years |
|---|---|---|---|---|---|
| Long Island University | 3 | +6.87 | +9.28 | 0% / 0% | 2022 |
| Kurt Jetta | 6 | +3.89 | +4.57 | 0% / 78% | 2022 |
| Lake Research Partners | 3 | +3.65 | +4.93 | 0% / 100% | 2022, 2026 |
| SoonerPoll | 4 | +3.23 | +4.08 | 0% / 0% | 2018, 2022 |
| St. Cloud State University | 4 | +3.19 | +4.03 | 0% / 0% | 2018, 2022 |
| Franklin & Marshall College | 5 | +3.05 | +3.69 | 0% / 0% | 2018, 2022, 2026 |
| Survey Monkey | 5 | +2.94 | +3.56 | 0% / 100% | 2022 |
| McLaughlin & Associates | 3 | −2.87 | −3.88 | 100% / 0% | 2022, 2026 |
| GQR | 3 | +2.61 | +3.53 | 0% / 100% | 2026 |
| Patriot Polling | 6 | −2.59 | −3.04 | 50% / 0% | 2022 |

The largest among the pollsters behind v1's 2026 averages:

| Pollster | Races (all years) | 2026 races | House effect (points) | Share of its polls labelled R / D |
|---|---|---|---|---|
| Advanced Targeting Research | 2 | 2 | +6.73 | 0% / 0% |
| Peak Insights | 2 | 2 | −5.69 | 100% / 0% |
| The Bullfinch Group | 1 | 1 | +4.88 | 0% / 0% |
| Emerson College/WPRI-TV | 2 | 2 | +4.19 | 0% / 0% |
| Aspect Strategic | 1 | 1 | −3.95 | 0% / 0% |
| Lake Research Partners | 3 | 2 | +3.65 | 0% / 100% |
| BSP Research | 1 | 1 | +3.59 | 0% / 100% |
| PennLive | 1 | 1 | +3.05 | 0% / 0% |
| Franklin & Marshall College | 5 | 1 | +3.05 | 0% / 0% |
| Public Opinon Strategies | 1 | 1 | −2.94 | 100% / 0% |

Of the 447 polls in v1's 2026 averages, 445 had a house effect to remove; their weighted mean was −0.38 points. Mean effect by Wikipedia's label: Democratic-labelled +0.74, Republican-labelled −1.32, unlabelled +0.12 points.

| | Value |
|---|---|
| Races with polls: v1 / H7 | 59 / 59 |
| Polls in the averages: v1 / H7 | 447 / 447 |
| Change in the average, H7 minus v1 (toward Democrats) | mean +0.12, SD 1.05, mean absolute 0.73 points over 59 races |
| Scored races: mean error of v1's average / of the H7 average | +2.23 / +2.19 points (52 races) |
| MAE of v1's average / of the H7 average | 3.27 / 3.04 |

| Run | Called races | Brier | Log loss | Upsets (expected) | Vote-share races | Mean error | MAE | 80% coverage | Below / above |
|---|---|---|---|---|---|---|---|---|---|
| v1 as published | 477 | 0.044 | 0.139 | 32 (27.9) | 424 | +3.12 | 3.68 | 66% | 6 / 140 |
| DIAGNOSTIC: generic-ballot bias set to 0 (H1) | 477 | 0.033 | 0.112 | 18 (31.4) | 424 | +1.64 | 2.82 | 81% | 8 / 71 |
| DIAGNOSTIC: house effects removed (H7) | 477 | 0.044 | 0.137 | 30 (27.8) | 424 | +3.12 | 3.68 | 66% | 6 / 138 |
| DIAGNOSTIC: house effects removed and bias 0 (H7 and H1) | 477 | 0.032 | 0.110 | 17 (31.2) | 424 | +1.63 | 2.81 | 82% | 8 / 69 |

By office (Brier; mean error; MAE; 80% coverage):

| Run | Senate | Governor | House |
|---|---|---|---|
| v1 as published | 0.066; +2.56; 3.69; 60% | 0.051; +1.97; 3.56; 79% | 0.042; +3.27; 3.69; 65% |
| DIAGNOSTIC: generic-ballot bias set to 0 (H1) | 0.050; +1.60; 2.96; 77% | 0.047; +1.35; 3.31; 82% | 0.031; +1.67; 2.76; 82% |
| DIAGNOSTIC: house effects removed (H7) | 0.053; +2.37; 3.60; 67% | 0.050; +2.06; 3.60; 79% | 0.042; +3.27; 3.69; 65% |
| DIAGNOSTIC: house effects removed and bias 0 (H7 and H1) | 0.039; +1.41; 2.83; 80% | 0.047; +1.45; 3.29; 85% | 0.031; +1.67; 2.76; 82% |

Removing house effects moves the averages +0.12 points toward Democrats on average (mean absolute change 0.73), and the scored races' poll error from +2.23 to +2.19 points (MAE 3.27 to 3.04). Because house effects are measured against the average pollster, removing them corrects only how far a race's mix of pollsters leaned relative to that average (the weighted mean effect in v1's 2026 averages was −0.38 points), not a miss that every pollster shared, and most of 2026's poll error was shared (H2). So the adjustment mainly reduces race-to-race scatter: the overall mean error moves from +3.12 to +3.12 points and the Brier score from 0.044 to 0.044, with the Senate Brier 0.066 to 0.053 and the governors' 0.051 to 0.050. The House, whose forecasts use no race polls, is unchanged.

## H8: Partisan Polls Left Out

**DIAGNOSTIC.** v1's race averages rebuilt with every poll Wikipedia labels with a Democratic or Republican sponsor left out (the labels H2 uses, such as "(R)" or "(D-sponsor)"), and nothing else changed; where a pollster's latest poll was partisan-sponsored, its latest unlabelled poll is used if there is one. The Silver Bulletin's public methodology page says that for its generic-ballot average polls with partisan sponsors are excluded from the calculation of the "true" average against which house effects are measured, and that in its race averages they start from a prior of a lean toward the sponsor. Leaving them out of the average altogether, as here, is the simpler and stronger version of that idea, not their method.

Of the 447 polls in v1's 2026 averages, 139 were labelled Republican and 64 Democratic (329 of the 732 polls in the 90-day window carry a label).

| | Value |
|---|---|
| Races with polls: v1 / H8 | 59 / 55 |
| Polls in the averages: v1 / H8 | 447 / 245 |
| Change in the average, H8 minus v1 (toward Democrats) | mean +0.31, SD 1.53, mean absolute 0.66 points over 55 races |
| Scored races: mean error of v1's average / of the H8 average | +2.35 / +2.25 points (49 races) |
| MAE of v1's average / of the H8 average | 3.40 / 3.33 |

**Races left without polls: 4.** v1's blend treats a race with no qualifying poll exactly as it treats any unpolled race: the poll weight is 0 and the forecast is the fundamentals alone. No other source of polls is substituted.

| Race | v1 polls (all labelled) | v1 poll average (D) | v1 poll weight | H8 poll weight | P(D win): v1 | H8 | Winner | Actual (D) |
|---|---|---|---|---|---|---|---|---|
| IL-GOV | 1 | 61.4% | 0.50 | 0.00 | 100% | 98% | D | 62.2% |
| KY-SEN | 1 | 44.9% | 0.30 | 0.00 | 1% | 1% | R | 43.8% |
| LA-SEN | 1 | 47.8% | 0.30 | 0.00 | 10% | 10% | R | 49.1% |
| MS-SEN | 1 | 46.3% | 0.30 | 0.00 | 7% | 8% | – | 50.1% |

In the other polled races, fewer polls mean a smaller effective number, a wider poll error in v1's model and so a lower weight on the polls: mean poll weight 0.68 in v1 against 0.60 here (55 races).

| Run | Called races | Brier | Log loss | Upsets (expected) | Vote-share races | Mean error | MAE | 80% coverage | Below / above |
|---|---|---|---|---|---|---|---|---|---|
| v1 as published | 477 | 0.044 | 0.139 | 32 (27.9) | 424 | +3.12 | 3.68 | 66% | 6 / 140 |
| DIAGNOSTIC: generic-ballot bias set to 0 (H1) | 477 | 0.033 | 0.112 | 18 (31.4) | 424 | +1.64 | 2.82 | 81% | 8 / 71 |
| DIAGNOSTIC: partisan polls left out (H8) | 477 | 0.045 | 0.141 | 32 (28.0) | 424 | +3.12 | 3.69 | 67% | 6 / 136 |
| DIAGNOSTIC: partisan polls left out and bias 0 (H8 and H1) | 477 | 0.033 | 0.114 | 18 (31.5) | 424 | +1.61 | 2.81 | 82% | 8 / 67 |

By office (Brier; mean error; MAE; 80% coverage):

| Run | Senate | Governor | House |
|---|---|---|---|
| v1 as published | 0.066; +2.56; 3.69; 60% | 0.051; +1.97; 3.56; 79% | 0.042; +3.27; 3.69; 65% |
| DIAGNOSTIC: generic-ballot bias set to 0 (H1) | 0.050; +1.60; 2.96; 77% | 0.047; +1.35; 3.31; 82% | 0.031; +1.67; 2.76; 82% |
| DIAGNOSTIC: partisan polls left out (H8) | 0.071; +2.62; 3.82; 63% | 0.050; +1.83; 3.51; 88% | 0.042; +3.27; 3.69; 65% |
| DIAGNOSTIC: partisan polls left out and bias 0 (H8 and H1) | 0.055; +1.53; 2.96; 83% | 0.046; +1.11; 3.27; 88% | 0.031; +1.67; 2.76; 82% |

Leaving out partisan polls moves the remaining averages +0.31 points toward Democrats on average, and the scored races' poll error from +2.35 to +2.25 points (49 races with polls under both). The forecast's overall mean error is unchanged at +3.12 points and its Brier score moves from 0.044 to 0.045 (Senate 0.066 to 0.071, governors 0.051 to 0.050). The averages move toward Democrats, but with fewer polls v1's blend puts less weight on them and more on the fundamentals, which understated Democrats by more, so the two effects roughly cancel. Republican-sponsored polls missed most in H2, but the unlabelled polls that remain also understated Democrats, so the exclusion does not remove the shared miss.

**Limits of H7 and H8.** Both keep v1's poll-error model as fitted on v1's own 2018 and 2022 averages; a forecaster who adjusted or filtered polls would also refit that model on averages built the same way, which is not done here. Wikipedia's sponsor labels are incomplete (unlabelled polls include partisan firms that are not marked), and H7's house effects do not separate a pollster's lean from differences in timing within a race or in likely-voter screens. Both are DIAGNOSTIC reruns and change neither v1 nor its score.

## Checks

**Generic-ballot cycles.** `python -m forecast.generic_ballot` gives `n_years` = 12 for 2026. The years used are 1998, 2000, 2002, 2004, 2006, 2008, 2010, 2012, 2014, 2016, 2018, 2022. The even years 2020 and 2024 drop out because no 30 September generic-ballot value is collected for them (`generic_ballot()` reads 1998 to 2016 from FiveThirtyEight's history, 2018 from its archived file and 2022 from Wikipedia), although their House votes are read. The write-up's "11 of the 12 cycles since 1998" is therefore right in count, and #24's concern that the code averages 14 cycles does not hold; the wording would be clearer as "12 of the 14 cycles from 1998 to 2024 (2020 and 2024 lack a 30 September value)". The docstring's "every even year before `year` with both numbers" is accurate. One related point: the bias is estimated from end-of-September values (18 to 30 September), but 2026 used the value on 22 October, about three weeks later and closer to the election, when the generic ballot's historical overstatement may be smaller. That mismatch is untested.

**Minnesota count order.** The snapshot in #24 saw Republicans ahead in both Minnesota races early in the count, before both went to the Democrats. The repository cannot show the early lead: its first pull (2026-11-04T06:40:11Z) came after both calls (MN-GOV 57.1% Democratic with 94% counted, called at 05:07 UTC; MN-SEN 55.8% Democratic with 94% counted, called at 05:07 UTC). Early returns are ordered by how each county reports and by ballot type (in-person and mail are counted and released at different times), so an early lead says little about the result; the write-up should say so in a line before reading early returns as signal. The Internet Archive holds a capture of AP's national feed at 05:04 UTC on 4 November, just before both calls, which could document the early count if needed; it has not been downloaded here.

**Archiving the AP feed.** The project keeps AP's raw files for its own 6 pulls (20261104T064011Z, 20261104T075718Z, 20261104T104153Z, 20261104T194255Z, 20261105T014421Z, 20261108T225913Z) under `data/raw/results_2026/` (local, not committed, as they are AP's). Publicly, the Internet Archive's index (queried 4 November) holds captures of the national `progress.json` and `metadata.json` at 04:28, 17:02 and 20:03 UTC on 3 November (before polls closed) and one at 05:04 UTC on 4 November (election night), plus some per-state and per-race files; the index showed none later at the time of the query. The #24 note that a direct `curl` returned a stub is explained in `results/README.md`: the files are gzip bytes, not a stub. No new archive request was made; saving the feed through the Internet Archive while it still shows the election-night state is still open.

**Final counts.** This page should be rerun on final counts (`python -m forecast.diagnostics --pull <id>` after a new pull); #24 notes that late mail in the West tends to lean Democratic, so the shift may grow.

## Through Time

**DIAGNOSTIC.** v1's own code rerun as it would have stood on seven dates, each with only what was public that day (issue #29). v1 as published on 22 October remains the forecast of record and its score (#15) is unchanged; none of these reruns is part of it. Scored against AP's pull at 2026-11-08T22:59:13Z (provisional), with the measures used above.

On each date the race polls are the Wikipedia race articles at their last revision on or before 23:59:59 UTC, averaged with v1's rules relative to that date, and the generic ballot is the aggregators' mean on the 2026 House page at the same revision time. Everything else is v1's: the fits, the generic-ballot bias and spread, the candidates and incumbents as of 22 October, and the seeds. The 22 October rerun uses v1's own saved inputs and reproduces `forecasts/v1/` exactly (largest difference 0 in the tables, 0 in the seat distributions).

| Date | Run | Generic ballot (D, 2-party) | House vote centre | Races polled | Senate D | House D | Governors D | House seats (80%) | Brier | Log loss | Upsets (exp.) | Mean error | MAE | 80% coverage |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 Sep | as built | 53.5% | 51.8% | 52 | 45% | 77% | 44% | 225 (212–241) | 0.057 | 0.176 | 39 (26.2) | +4.14 | 4.51 | 54% |
| 1 Sep | bias 0 | 53.5% | 53.5% | 52 | 67% | 97% | 63% | 239 (224–258) | 0.041 | 0.132 | 27 (29.1) | +2.63 | 3.36 | 71% |
| 15 Sep | as built | 54.0% | 52.3% | 55 | 52% | 86% | 48% | 229 (215–245) | 0.051 | 0.159 | 37 (27.2) | +3.73 | 4.16 | 59% |
| 15 Sep | bias 0 | 54.0% | 54.0% | 55 | 73% | 98% | 65% | 243 (227–263) | 0.037 | 0.122 | 23 (30.3) | +2.22 | 3.11 | 76% |
| 1 Oct | as built | 54.5% | 52.8% | 55 | 60% | 92% | 58% | 233 (219–250) | 0.046 | 0.143 | 34 (27.9) | +3.26 | 3.78 | 65% |
| 1 Oct | bias 0 | 54.5% | 54.5% | 55 | 77% | 99% | 73% | 248 (231–269) | 0.034 | 0.114 | 18 (31.3) | +1.76 | 2.87 | 81% |
| 15 Oct | as built | 54.4% | 52.7% | 57 | 64% | 91% | 61% | 232 (218–249) | 0.046 | 0.144 | 35 (27.5) | +3.34 | 3.83 | 64% |
| 15 Oct | bias 0 | 54.4% | 54.4% | 57 | 79% | 99% | 75% | 247 (230–268) | 0.034 | 0.114 | 20 (31.0) | +1.85 | 2.90 | 80% |
| 22 Oct (v1) | as built | 54.7% | 52.9% | 59 | 63% | 93% | 62% | 234 (219–252) | 0.044 | 0.139 | 32 (27.9) | +3.12 | 3.68 | 66% |
| 22 Oct | bias 0 | 54.7% | 54.7% | 59 | 78% | 99% | 75% | 249 (232–271) | 0.033 | 0.112 | 18 (31.4) | +1.64 | 2.82 | 81% |
| 29 Oct | as built | 54.5% | 52.8% | 59 | 66% | 92% | 65% | 232 (218–250) | 0.045 | 0.141 | 32 (27.6) | +3.23 | 3.75 | 65% |
| 29 Oct | bias 0 | 54.5% | 54.5% | 59 | 80% | 99% | 77% | 248 (231–269) | 0.033 | 0.112 | 17 (31.0) | +1.75 | 2.85 | 81% |
| 2 Nov | as built | 54.6% | 52.8% | 61 | 70% | 92% | 74% | 233 (219–251) | 0.044 | 0.138 | 32 (27.5) | +3.17 | 3.70 | 65% |
| 2 Nov | bias 0 | 54.6% | 54.6% | 61 | 83% | 99% | 84% | 248 (231–269) | 0.032 | 0.110 | 17 (30.9) | +1.69 | 2.81 | 81% |

Scores are over all called races (Senate, governor and House); vote-share measures over races with at least 85% counted. By office, Brier and mean error:

| Date | Run | Senate | Governor | House |
|---|---|---|---|---|
| 1 Sep | as built | 0.087; +3.27 | 0.071; +3.24 | 0.054; +4.30 |
| 1 Sep | bias 0 | 0.069; +2.13 | 0.066; +2.36 | 0.037; +2.69 |
| 15 Sep | as built | 0.078; +2.95 | 0.061; +2.96 | 0.049; +3.86 |
| 15 Sep | bias 0 | 0.061; +1.86 | 0.055; +2.17 | 0.034; +2.25 |
| 1 Oct | as built | 0.069; +2.61 | 0.053; +2.39 | 0.044; +3.39 |
| 1 Oct | bias 0 | 0.052; +1.57 | 0.049; +1.63 | 0.031; +1.79 |
| 15 Oct | as built | 0.064; +2.61 | 0.051; +2.21 | 0.045; +3.50 |
| 15 Oct | bias 0 | 0.049; +1.62 | 0.047; +1.51 | 0.032; +1.90 |
| 22 Oct | as built | 0.066; +2.56 | 0.051; +1.97 | 0.042; +3.27 |
| 22 Oct | bias 0 | 0.050; +1.60 | 0.047; +1.35 | 0.031; +1.67 |
| 29 Oct | as built | 0.063; +2.56 | 0.044; +1.92 | 0.044; +3.40 |
| 29 Oct | bias 0 | 0.048; +1.61 | 0.041; +1.33 | 0.031; +1.80 |
| 2 Nov | as built | 0.056; +2.42 | 0.041; +1.62 | 0.043; +3.37 |
| 2 Nov | bias 0 | 0.043; +1.51 | 0.038; +1.07 | 0.031; +1.77 |

Across the seven dates the generic ballot v1 would have read ranged from 53.5% to 54.7% Democratic, and the as-built rerun's mean error toward Democrats stayed between +3.12 and +4.14 points (Brier 0.044 to 0.057): no lock date from 1 Sep to 2 Nov would have removed the Republican lean of the miss. Setting the generic-ballot bias to 0 lowers the mean error on every date (to between +1.64 and +2.63 points), by more than any change of date does, so the correction matters more than the lock date. What moved was the generic ballot, which carries the House (77% to 92% for Democrats), and, for the Senate (45% to 70%) and governors (44% to 74%), the race polls: more races polled (52 to 61) and averages that, over races polled on both dates, differed from v1's by −0.30 to +0.54 points on average.

**Limits.** Candidates and incumbents are v1's as of 22 October on every date, so on the early dates a race whose primary had not yet been held is modelled with its eventual nominees, and its polls are matched to them: a small look-ahead in the early reruns. The generic ballot is what the House page listed, which can lag the aggregators' own updates. As a check on the method, the 22 October inputs rebuilt from revisions give 59 races with polls against v1's 59, the same number of polls in 60 of 60 races, and poll averages within 0.02 points; the generic ballot 54.66% against v1's 54.66%.

## Files

- `results/diagnostics.json`: the numbers on this page.
- `src/forecast/diagnostics.py`: the code (`python -m forecast.diagnostics`); `tests/test_diagnostics.py`.
- Rerun tables (local, not committed, each marked DIAGNOSTIC): `data/processed/diagnostics_v1/<run>/`.
- 3 November Wikipedia revisions (local): `data/raw/polls_late_2026/`.
- H7's estimated house effects, one row per pollster (local, DIAGNOSTIC): `data/processed/diagnostics_v1/house_effects.csv`.
- `results/through_time.json` and the Through Time section: `src/forecast/through_time.py` (`python -m forecast.through_time`, run after `forecast.diagnostics`, which rewrites this page).

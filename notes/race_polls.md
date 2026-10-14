# Race Polls (14 October)

Code: `polls.py`, switched on by `USE_POLLS` in `vote_model.py`. Tests: `tests/test_polls.py`.

Until now Stage B used no polls of individual races, only the state's lean, the national environment, incumbency and the incumbent's record. That is the main reason it disagreed with the published ratings in Texas, Ohio, Alaska and Iowa. This note adds race polls as a separate layer on top of the fundamentals, tests it against the rule set before testing, and keeps it.

## Data

Every Senate and governor race in 2018, 2022 and 2026 has its own Wikipedia article ("2018 United States Senate election in Texas", "2022 Ohio gubernatorial election", specials have their own). Each one is saved under `data/raw/polls/`. From every poll table I keep pollster, field dates, sample size, population (LV, RV or A; often blank) and the two nominees' shares.

- **Only head-to-heads between the actual nominees** (from `races.py`). Tables in party-primary sections, poll aggregators and hypothetical match-ups are dropped. Where an independent stands in for the Democratic side (Nebraska, Idaho and South Dakota in 2026, Utah in 2022), their column is used.
- **Two races get no polls**: Mississippi's 2018 special and Louisiana's 2022 Senate race. Both were decided in an all-party first round, so the result is a party total across several candidates, which a head-to-head of two names does not measure. I spotted this when reading the raw averages, before any backtest.
- **No look-ahead.** For 2018 and 2022 a poll counts only if its fieldwork ended by 26 September, which leaves a few days for publication before the 1 October information date. For 2026, polls ending by the run date. In every year a poll must also have ended within 90 days of the cut-off.
- **Today's articles against the 1 October versions.** The 2018 and 2022 articles are today's, so a poll that finished by 26 September but was only added later still counts. To check, I also saved every article as it stood on 1 October (Wikipedia API, revision before that date). In the window, 26 of 403 poll rows in 2018 and 31 of 468 in 2022 are missing from the 1 October versions. Rerunning the 2022 backtest with only the 1 October versions gives the same answer (table below), so this is not doing the work.

Wikipedia's API now allows anonymous clients about ten calls a minute, so the code waits six seconds between API calls and one second between page fetches, and waits out any 429.

**Coverage.** Races with at least one qualifying poll, and pollsters used (one poll each):

| | Races modelled | With polls | Polls used | Median per race (where any) | Mean effective number |
|---|---|---|---|---|---|
| 2018 | 70 | 64 | 299 | 4 | 3.6 |
| 2022 | 71 | 56 | 340 | 4 | 4.9 |
| 2026 | 71 | 57 | 402 | 5 | 5.5 |

The races without polls are mostly safe seats (Wyoming, Hawaii, Idaho governor). The exceptions in 2026 are Florida governor (the article has aggregator figures but no Jolly against Donalds poll), Colorado governor and Alaska governor (top four, with no single Republican nominee yet). They keep the fundamentals forecast.

## Method

All of this was written into the module's docstring before the first backtest.

**Poll average.** One poll per pollster: its latest, using the likely-voter version where a poll reports several (then unspecified, registered voters, adults). Sponsors in brackets are ignored, so PPP for two clients is one pollster. Each poll's Democratic-side two-party share is weighted by

- recency: half-life 21 days, counted from the end of fieldwork to the cut-off;
- sample size: square root of n over 600, with n capped at 2,000 (600 when not given);
- population: 1.0 for likely voters or unspecified, 0.8 for registered voters, 0.6 for adults.

The average comes with the number of polls and their effective number (sum of weights squared over the sum of squared weights).

**Poll error.** On the logit scale, result minus poll average = a national polling error shared by every race that year + a race error. The race error has a part that more polls do not remove and a part that shrinks with the effective number of polls. No average bias is assumed: the sign of the national miss changes between years.

The three spreads are fitted in PyMC on years before the target only: 2018 for the 2022 backtest, 2018 and 2022 for 2026. The 2018 backtest has no earlier year, so it runs on priors, set from the typical published error of a single state-level poll, about 5 points of margin (about 0.10 on the logit scale near 50%, a standard deviation of about 0.12): national 0.05, floor 0.06, single poll 0.09 (prior medians, log-normal with spread 0.5).

| Spread (logit) | Prior | Fitted on 2018 | Fitted on 2018 and 2022 |
|---|---|---|---|
| National | 0.049 | 0.046 | 0.049 |
| Race floor | 0.060 | 0.087 | 0.066 |
| Single poll | 0.091 | 0.204 | 0.241 |

Polls five weeks or more before the election are much noisier than the published figure for final polls, which is why the single-poll spread more than doubles once there is data. The national miss was -0.014 in 2018 and -0.057 in 2022 (on average the polls overstated the Democratic side, by about 1.4 points of share in 2022).

**Blend.** The fundamentals simulations are the prior for each race and the poll average a noisy observation of it. In each simulation the observation is perturbed by a draw of the national error (the same for every race in that simulation) and of the race error, and the fundamentals draw moves towards it by the precision weight: fundamentals variance over fundamentals plus poll variance. That gives the usual precision-weighted mean and variance in every race and keeps the correlations: fundamentals errors through the simulations, polling errors through the shared national draw. Races with no qualifying poll are untouched.

Polls get a median weight of 0.70 in the 2022 backtest, 0.92 in the 2018 backtest (the priors trust polls too much) and 0.67 in 2026 (between 0.30 and 0.85).

## Backtest

The rule, set before testing: keep polls only if the 2022 backtest (trained on 2018) improves on both Brier score and vote-share error against the current model (0.0666 and 3.64 points). Same fundamentals draws, with and without the poll layer.

| | 2018 | 2022 |
|---|---|---|
| Brier, no polls | 0.149 | 0.067 |
| Brier, with polls | **0.062** | **0.031** |
| Vote-share error, no polls (points) | 5.1 | 3.6 |
| Vote-share error, with polls | **2.7** | **2.7** |
| Log loss, no polls / with polls | 0.477 / 0.201 | 0.214 / 0.113 |
| Races called right, no polls / with polls | 82% / 93% | 90% / 94% |
| 80% interval coverage, no polls / with polls | 96% / 71% | 86% / 77% |
| 2022, polls from the 1 October versions only: Brier / error / coverage | | 0.031 / 2.6 / 81% |

**Calibration with polls** (races, mean forecast probability, share won by the Democratic side):

| Forecast | 2018 | 2022 |
|---|---|---|
| 0 to 20% | 20 races, 5%, 0% | 33 races, 2%, 0% |
| 20 to 40% | 4, 29%, 0% | 3, 31%, 33% |
| 40 to 60% | 6, 53%, 50% | 5, 48%, 80% |
| 60 to 80% | 6, 71%, 50% | 3, 71%, 100% |
| 80 to 100% | 32, 96%, 97% | 26, 96%, 100% |

**Decision: polls are in** (`USE_POLLS = True`). Both scores improve a lot in 2022, and in 2018 too, even on priors alone. Two cautions:

- The intervals got too narrow: 71% and 77% coverage against 80%. In 2018 that is the priors, which treat early polls like final polls. In 2022, trained on 2018, it is closer but still short. With 2018 and 2022 both in training the single-poll spread is larger again (0.24), so the 2026 intervals should be a little wider, but I have no out-of-sample test of that. Two elections are also not enough to estimate the national polling error well; its prior does most of the work.
- In 2022 the misses lean one way: races in the 40 to 80% band went to Democrats more often than forecast, which is the national polling miss of that year. A shared error is exactly what the model allows for, but it means the polls layer is only as good as the next year's polls.

In the backtest table (`backtest_races.csv`) "model" is now the model with polls and "no polls" the fundamentals alone; the other variants (plain lean, no track record, with fundraising) are fundamentals-only and compare with "no polls".

## 2026

The 2026 poll error is fitted on 2018 and 2022 and polls run to 14 October (articles saved on 13 October), three weeks later than the backtest cut-off. National House vote 52.7% Democratic (unchanged). Democrats hold 51 or more Senate seats in 64% of simulations with polls, against 39% without; Republicans hold 50 or more in 31%, against 56%.

Competitive races, Democratic-side win probability and median two-party share, without and with polls. Ratings (Cook and Sabato, as on Wikipedia's 2026 Senate and gubernatorial pages on 13 October) are for comparison only and never an input.

| Race | Without polls | Poll average (polls) | With polls | Cook | Sabato |
|---|---|---|---|---|---|
| NC Senate | 77%, 53.1 | 55.4 (17) | 98%, 54.7 | Likely D (flip) | Lean D (flip) |
| ME Senate | 79%, 53.6 | 50.9 (19) | 77%, 51.7 | Tossup | Tossup |
| MI Senate | 80%, 53.6 | 51.7 (28) | 85%, 52.3 | Tossup | Lean D |
| OH Senate (special) | 30%, 47.8 | 51.7 (16) | 58%, 50.5 | Tossup | Tossup |
| TX Senate | 32%, 48.0 | 51.3 (26) | 57%, 50.4 | Tossup | Tossup |
| IA Senate | 34%, 48.2 | 50.5 (16) | 47%, 49.8 | Tossup | Tossup |
| AK Senate | 20%, 46.5 | 51.2 (9) | 42%, 49.5 | Tossup | Lean D (flip) |
| KS Senate | 19%, 46.2 | 50.8 (10) | 37%, 49.2 | Tossup | Lean R |
| NE Senate (Osborn, independent) | 17%, 42.8 | 49.3 (7) | 27%, 48.1 | Likely R | Likely R |
| SD Senate (Bengs, independent) | 6%, 38.6 | 48.9 (4) | 17%, 46.5 | Solid R | Safe R |
| SC Senate | 11%, 44.8 | 48.6 (5) | 14%, 46.9 | Likely R | Likely R |
| GA Senate | 87%, 54.7 | 54.6 (7) | 96%, 54.6 | Likely D | Likely D |
| IA governor | 35%, 47.5 | 54.4 (10) | 88%, 53.2 | Lean D (flip) | Lean D (flip) |
| MI governor | 63%, 52.2 | 54.0 (20) | 93%, 53.7 | Lean D | Lean D |
| WI governor | 64%, 52.4 | 52.1 (6) | 74%, 52.2 | Tossup | Lean D |
| OH governor | 40%, 48.4 | 51.9 (11) | 67%, 51.2 | Tossup | Tossup |
| GA governor | 62%, 51.9 | 49.0 (6) | 46%, 49.7 | Tossup | Tossup |
| NV governor | 34%, 47.3 | 49.4 (3) | 37%, 48.7 | Tossup | Tossup |
| KS governor | 29%, 46.4 | 48.0 (6) | 22%, 47.6 | Lean R (flip) | Lean R (flip) |
| TX governor | 14%, 43.0 | 48.9 (22) | 21%, 48.0 | Lean R | Lean R |
| NH governor | 20%, 44.8 | 44.9 (5) | 5%, 44.9 | Likely R | Likely R |
| AK governor | 34%, 47.4 | none | 34%, 47.4 | Lean D (flip) | Lean D (flip) |
| FL governor | 35%, 47.4 | none | 35%, 47.4 | Lean R | Lean R |

**Reading it.** Polls move the model towards the ratings almost everywhere it disagreed with them: Texas, Ohio, Iowa and Alaska Senate move from Republican favourites to near coin flips, and Iowa and Michigan governor become clear Democratic leads. Where the polls agree with the fundamentals (Georgia Senate, New Hampshire governor) the forecast mostly gets more certain. Georgia governor moves furthest towards Republicans, and Kansas governor a little. The model is now more confident than the ratings in North Carolina and Michigan governor; with 2022's coverage of 77% in mind, those probabilities are probably a little high.

**Known problems.**
- Where a strong independent is on the ballot alongside both nominees (Montana Senate, Rhode Island governor), the poll's Democratic-against-Republican share ignores the independent. Montana's average is 29% for the Democratic side and the blended forecast has a narrow 32 to 39% band, which looks too sure. Neither race is close on the overall result.
- Alaska's poll tables mix ranked-choice rounds; the first row listed for each pollster is used.
- In 2026 polls run three weeks later than in the backtests, so they are a little more accurate than the error model assumes. That errs on the cautious side.
- Partisan and sponsored polls are included as they are, on both sides.

## Files (`data/processed/`)

`polls.parquet` (every parsed head-to-head), `polls_1_october.parquet`, `polls_revision_check.csv`, `poll_averages.csv`, `polls_coverage.csv`, `backtest_polls_2018.csv` and `_2022.csv` (average, weight and medians per race), `backtest_polls_2022_as_of_1_october.csv`, `backtest_races_*_no_polls.parquet`, `polls_2026_comparison.csv`.

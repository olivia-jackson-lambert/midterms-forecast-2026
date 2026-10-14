# 2026 Midterms: A Turnout-First Forecast

**Goal:** publish a transparent, falsifiable forecast of the 3 November 2026 midterms before Election Day, then score it honestly afterwards.

**Angle:** most public forecasts predict who wins. This one starts with turnout, forecasting how many people vote in each county, and builds vote share on top of that.

**Status:** planning. Today is 28 September 2026, and Election Day is 3 November 2026, 36 days away.

---

## 1. What We Forecast

**Must have:**
1. County-level turnout for November 2026, as a share of the voting-age population, with an 80% interval.
2. Two-party vote share and win probability for every 2026 **Senate** and **governor** race, about 70 races.

**Added 13 October:** the House, 435 districts (originally a stretch goal; built and backtested, see House As Built).

**Out of scope:** primaries, ballot measures and state legislatures.

## 2. Principles

- **Public data only.** No data, tools, code or knowledge from Hockeystick, the DNC or any client goes near this project. It must be a personal project in every respect.
- **Nonpartisan tone.** Present probabilities, not preferences.
- **Pre-register.** The published forecast is a tagged Git commit with a timestamp, so nobody can claim it was edited after the fact.
- **Score honestly.** After the election, publish every miss, not only the hits.
- **Employer:** confirmed on 28 September 2026 that personal projects like this are fine.

## 3. Data

Every source is public. Mark each one ✅ once its availability and licence are confirmed. On 29 September the ingest moved to sources that need **no API key and no download form**; the MIT Election Lab Dataverse copies (behind a guestbook) are now only a fallback.

| Need | Source | Status (checked 29 Sep 2026) |
|---|---|---|
| County presidential results, 2008–2016 | MIT Election Lab official county returns on GitHub (`MEDSL/county-returns`, `countypres_2000-2016.csv`), no form | ✅ in ingest; national totals within 0.25% of certified. Its `totalvotes` column is wrong in places (Fairfax city VA), so totals are summed from candidate votes |
| County presidential results, 2020 and 2024 | tonmcg mirror on GitHub (`US_County_Level_Election_Results_08-24`, MIT licence); Alaska replaced with the Division of Elections' certified statewide totals | ✅ in ingest. Don't use the mirror for 2012 or 2016: it undercounts CA, NY and RI by several million votes |
| Full county presidential file, 2000–2024 | MIT Election Lab Dataverse (doi:10.7910/DVN/VOQCHQ, v20) | ⚠️ guestbook form; not needed now |
| Senate results by state, 1976–2024 | MIT Election Lab Dataverse (doi:10.7910/DVN/PEJ5QU, v8) | ⚠️ guestbook form |
| House results by district, 1976–2024 | MIT Election Lab Dataverse (doi:10.7910/DVN/IG0UN2, v15) | ⚠️ guestbook form (stretch goal only) |
| **Midterm ballots cast by county, 2014, 2018, 2022** | EAC Election Administration and Voting Survey (EAVS), question F1a (total who participated), by election jurisdiction, no form | ✅ in `midterms.py`. Problems handled: Alabama 2014 reports registration, Illinois 2014 is blank, Hawaii and Utah 2014 are a third off, Wisconsin 2018 and 2022 have no county codes, Kansas City and Illinois city authorities have their own codes |
| **Certified state totals and national turnout history** | UF Election Lab (Michael McDonald): total ballots counted and VEP turnout by state, 1980–2022, and 2024 (v0.4), CC BY 4.0 | ✅ every state's county ballots are reconciled to these totals |
| **Midterm county results, 2018** | MIT Election Lab precinct returns on GitHub (`MEDSL/2018-elections-official`: `SENATE/`, `HOUSE/`, `STATE/` incl. governor; Indiana from its per-state file), no form. The repo is marked deprecated in favour of Dataverse | ✅ in `midterms.py`; all 36 governor and 35 Senate races; spot checks match certified to 0.2% |
| **Midterm county results, 2022** | MIT Election Lab precinct returns on GitHub (`MEDSL/2022-elections-official`, one file per state), no form; California Senate (regular + special) from SOS XLSX; Tennessee governor from Wikipedia's certified county table (SOS PDF is the same figures) | ✅ in `midterms.py`; spot checks match certified. New Jersey's House rows are double counted (not used) |
| Governor results, 2018 and 2022 | In the precinct files above; 2022 Tennessee filled from Wikipedia / SOS | ✅ |
| Citizen voting-age population (turnout denominator) | Census CVAP special tabulation, bulk CSVs on www2.census.gov, every 5-year vintage from 2005–2009 to 2020–2024; each election uses the vintage centred on it | ✅ in ingest |
| County demographics | ACS 5-year table-based summary files (2020–2024) on www2.census.gov: population, median age, income, race and ethnicity, education, age 18–29 and 65+ | ✅ in ingest. The Census API now needs a key, so it isn't used |
| Land area (for density) | Census Gazetteer counties file, 2024 | ✅ in ingest |
| Generic ballot as of 30 September, 1998–2022 (backtests and polling bias) | FiveThirtyEight's daily average (GitHub `fivethirtyeight/data`, 1998–2016); its 2018 file via the Internet Archive (stops 18 September 2018); its 2022 value from Wikipedia's ratings page as it stood on 30 September 2022 | ✅ `generic_ballot.py`. Never the final pre-election average |
| Generic ballot, 2026, and House popular vote 1998–2024 | 2026: mean of the aggregators on Wikipedia's 2026 House elections page (DDHQ, FiftyPlusOne, NBC News, RealClearPolitics, Silver Bulletin). House vote: Wikipedia's House election pages | ✅ refresh 2026 with `--refresh` before each release |
| 2025–26 special elections | Not used. They cannot be backtested (no comparable 2017–18 and 2021–22 series yet), and several 2026 contests are all-party or Democrat-against-Democrat | ☐ possible descriptive chart only |
| Races, incumbents, open seats, nominees; certified race results 2012–2022 | Wikipedia Senate and gubernatorial election pages, parsed from saved copies (2026 refreshed with `--refresh`) | ✅ `races.py`. Results cross-checked against MIT's county files (tests list the known gaps) |
| Candidate fundraising | OpenFEC API (`fundraising.py`, free key in `FEC_API_KEY`): each Senate nominee's cycle-to-date receipts on the June report, the last public before 1 October | ✅ downloaded; **not used**: it made the 2022 backtest worse (see Race Results) |
| Early and mail vote, 21 days out, 2014–2026 | 2026: UF Election Lab tracker CSV, saved on 13 October (21 days out). 2022: McDonald's RPubs tracker via the Internet Archive (18 October 2022 version, national totals only). 2018 and 2014: electproject.org pages via the Internet Archive (`forecast.early_vote`) | ⚠️ downloaded, **not used**: the 2018 and 2014 state tables were embedded Google Sheets the Archive never captured, so the backtest can't be run (see Early Vote Test) |
| County shapefiles | Census cartographic boundary files 2023 (20m) | ✅ |

**County units.** Results and Census geographies don't line up everywhere, so the panel uses county units: Alaska, Connecticut and DC are one unit each; Jackson, Clay and Platte counties (Kansas City, which reports separately) are one unit; Kalawao is merged into Maui, Bedford city into Bedford County, and Shannon SD is Oglala Lakota. That gives 3,104 units in every year.

**Midterm turnout numerator.** EAVS ballots cast where they pass two checks: within a factor of 1.6 of a crude estimate (last presidential vote times the state's certified midterm-to-presidential ratio) and, where MIT results exist, between 97% and 125% of the county's highest-office vote. Otherwise the MIT highest-office vote is scaled up by the state's ballots-to-highest-office ratio; failing that, the crude estimate is used and the row is marked imputed (256 units in 2014, 5 in 2018, 5 in 2022). Imputed rows are used as backtest anchors but never for training. Every state is then scaled to UF's certified total. County turnout correlates 0.80 between 2014 and 2018 and 0.81 between 2018 and 2022 (logit scale).

**Known limits.** CVAP is a survey estimate, so a handful of tiny counties show turnout above 100% (under 0.5% of rows, none with 5,000+ eligible citizens); the turnout model should shrink small counties. Chattahoochee GA shows about 20% turnout because Fort Moore's residents are counted there but mostly vote elsewhere.

All raw data lives in `data/` and is never committed (see `.gitignore`).

## 4. Model

**Structure: a hierarchical Bayesian model in PyMC, in two stages.**

**Stage A, turnout (county):**

`turnout_c,2026 ~ turnout_c,2022` (the last midterm), adjusted for:
- a national midterm-environment term, from special-election energy and the generic-ballot trend;
- a state effect: competitive top-of-ticket races raise turnout;
- county demographic slopes (age, education, density), shrunk toward national values;
- early-vote signal in October, where states report it (tested 13 October; not used, see below).

**Stage B, vote share (race):**

`two-party share_r ~ baseline_r + national_swing + state_effect + incumbency + fundraising`, where:
- `baseline_r` is the race's state partisan lean from recent presidential results, weighted by the turnout expected in Stage A;
- `national_swing` comes from the generic-ballot average and special-election over-performance, with its own uncertainty;
- errors are correlated across states, through a shared national error and regional errors, so the simulations don't treat each race as independent (the most common forecasting mistake).

**Simulation:** 20,000 or more draws of the whole election, giving win probabilities, seat-count distributions and county turnout intervals.

**Kept deliberately simple:** no candidate-quality scores from pundits, and no subjective adjustments. Anything that can't be backtested stays out.

### Stage A As Built (4 October)

Code: `features.py`, `national.py`, `turnout_model.py`, `backtest.py`.

**National level.** Midterm turnout is the last presidential turnout minus a midterm drop, on the logit scale, with the drop and its spread estimated from every midterm since 1986 before the target year (UF Election Lab VEP series). Out of sample since 1998 this beats "same as the last midterm" (logit RMSE 0.19 against 0.23). For 2026: 64.3% in 2024 gives a median of about 47.5% of the eligible population.

**County pattern.** Each county's logit change from the last midterm depends on:
- how far presidential turnout ran above the last midterm (the strongest predictor, about 0.57);
- regression towards the mean (about -0.17);
- a Senate race joining or leaving the ballot (+0.05) and the change in closeness of the top race (governor races are on the same 36 ballots every midterm, so they cancel out);
- the out-party effect: county partisan lean times the change in which party holds the White House (+0.10);
- seven demographic slopes (education, age 18-29 and 65+, Hispanic, Black, density, income) that may shift between elections;
- a state effect (spread 0.14) and Student-t county noise that grows for small counties.

**Simulation.** 20,000 draws. Each draws national turnout, then shifts every county by the same amount so the eligible-population-weighted total matches it.

**Deviations from the protocol, stated openly:**
- Demographics come from ACS 2020–2024 for every year (the table-based files start with the 2021 vintage). They change slowly and contain no results.
- There is no public 2010 county turnout, so the 2018 backtest has no earlier county transition to learn from and runs on priors alone. Only the 2022 backtest tests the full county model.
- The out-party term was added after the first backtest showed a county-size bias that flipped sign between 2018 and 2022. Both versions are reported below; the forecast uses the version with it.

### Early Vote Test (13 October)

Code: `early_vote.py`. The old version ranked states' early-vote pace against each other, which mostly measures voting rules: all-mail states always look ahead. The new one compares each state with itself, 21 days before Election Day:

`feature = log(early ballots now / last midterm's turnout) − log(early ballots at the same point last time / the turnout before that)`

The offset would be k × feature on Stage A's state logit, with the national total still pinned. States whose voting rules changed between the two cycles are left out (for 2018 to 2022: California, Nevada, Vermont, Utah, Hawaii and DC moved to all-mail; Pennsylvania, Virginia, Michigan, Massachusetts, Delaware and Rhode Island added no-excuse mail; Georgia and Iowa shortened their mail windows; and others; the full list is in the code).

**The rule, set before looking:** fit k on 2018 (2018 pace against 2014), test on 2022. Use it only if it improves both the 2022 state turnout error and the 2022 weighted county error. If dated 2018 or 2022 state data don't exist, don't use it.

**What exists 21 days out:**
- 2026 (13 October): the UF Election Lab CSV, saved on the day. 37 states report; 4.4 million ballots returned, 5.4% of those states' 2022 turnout.
- 2022 (18 October): the Internet Archive has McDonald's national page as updated at 10:18 that morning (2.6 million early votes in 25 reporting states). State figures were on separate pages; the Archive holds just 8 versions of 7 of them (early October or after the election), none near 18 October.
- 2018 (16 October) and 2014 (14 October): nothing by state. The electproject.org pages were archived, but their tables were embedded Google Sheets whose contents were never captured. The live 2018 sheet holds only the final pre-election report (5 and 6 November), a later revision; it is saved for description only.

**Decision:** no 2018 data at the right date, so there is nothing to fit k on and no fair 2022 test. Under the rule, early vote stays out of the forecast (`early_vote.WIRED = False`; `turnout_model.run(early_vote=True)` now changes nothing). The national 2026 and 2022 totals aren't comparable either, because the reporting states differ. The downloads stay for descriptive charts.

### Stage B As Built (5 October)

Code: `races.py`, `generic_ballot.py`, `vote_model.py`, `backtest.py`. On the logit scale, the Democratic two-party share in a race is:

- the national House vote (in training, the actual result; in a forecast, drawn from the 30 September generic ballot with its historical bias and spread, estimated from earlier cycles only);
- plus the state's lean against the nation, where the lean is the last presidential vote re-weighted county by county with Stage A turnout, with a separate slope for Senate (0.89) and governor races (0.76);
- plus incumbency (Senate 0.06, governor 0.21) and the incumbent's track record: their last result against what a uniform swing predicted (Senate 0.30, governor 0.71);
- plus regional, same-state and race errors, all fitted in PyMC.

Each simulation draws the national vote, the errors and a Stage A turnout draw, so turnout uncertainty carries into vote share. Races with no Democrat face an independent challenger (Nebraska, Idaho, South Dakota Senate in 2026): the independent stands in for the Democratic side with extra uncertainty, and their seats are not counted as Democratic.

**What turnout weighting does.** Re-weighting counties by forecast turnout moves state leans very little: by 0.07 points on average in 2026, at most 0.5. In backtests it gives a small edge in 2022 and none in 2018. The turnout-first angle matters more for county turnout itself and for uncertainty than for who wins.

**First 2026 run (5 October).** National House vote 52.8% Democratic (two-party). Democrats hold 51 or more Senate seats in 40% of simulations; Republicans hold 50 or more in 55%.

### Nominee Track Record (Tested 14 October, Left Out)

Incumbents' track records help (Race Results). The same idea for every nominee, using each candidate's most recent statewide race (Senate, governor or at-large House, 2010 onwards), was built and tested under the same rule. It made the 2022 backtest worse on both Brier (0.075 against 0.067) and vote-share error (3.77 against 3.64 points), so it is off (`USE_NOMINEE_TRACK_RECORD = False`). Challengers' past overperformance does not seem to carry over the way incumbents' does. It would have moved Alaska Senate from 20% to 35% and Ohio Senate from 30% to 40% for the Democratic side. Details in `notes/challenger_track_record.md`.

### House As Built (14 October)

Code: `house.py`. The same structure as Stage B: each district's lean is the 2024 presidential two-party share on the map in force for 2026 (nine states redrew for 2026: Texas, California, North Carolina, Ohio, Utah, Florida, Tennessee, Louisiana and Alabama), moved by the national House vote, plus incumbency and regional, state and district errors, fitted in PyMC on earlier midterms. Presidential results by district come from The Downballot's public sheets; results, members and nominees from Wikipedia's House pages. Turnout weighting is left out (it barely moves leans in Stage B), and so is the incumbent track record, which made the 2022 House backtest worse.

Only independents stand in for a missing party (California 6: Kiley, now an independent, against a Democrat). Districts with one candidate, one party's candidates, or a lone major party against a minor-party candidate are certain holds (15 in 2026).

| House backtest | 2018 (priors only) | 2022 (fitted on 2018) |
|---|---|---|
| Brier: model / lean / uniform swing | 0.058 / 0.084 / 0.053 | **0.031** / 0.055 / 0.055 |
| Vote-share error, points: model / lean / uniform swing | 2.78 / 3.53 / 2.77 | **2.21** / 3.22 / 2.31 |
| Democratic seats: actual / model median (80%) | 234 / 228 (191-291) | 213 / 210 (195-225) |

The model beats both baselines in 2022, narrowly on vote share against uniform swing. In 2018, on priors alone, it does not beat uniform swing on Brier. **First 2026 run (14 October):** Democrats win a median of 232 seats (80%: 218-250) and 218 or more in 91% of simulations. Known gaps: Alaska and Maine use first-round shares; Louisiana's 3 November vote has several candidates per party; seat intervals may be a little narrow because errors are only national, regional and state. Details in `notes/house.md`.

## 5. Backtest (The Credibility)

For **2018** and **2022**, fit the model using only data available on 1 October of that year, then score it against the actual results:
- **Races:** Brier score, log loss, and calibration (do the "70%" races win about 70% of the time?).
- **Turnout:** county mean absolute error and 80% interval coverage (does the truth fall inside the 80% band about 80% of the time?).
- **Baselines to beat:** "same as last midterm" for turnout, and "same as the last presidential lean" for vote share.

If the model doesn't beat the baselines in backtest, don't publish it as a forecast. Publish it as an analysis instead.

### Turnout Results (4 October)

County turnout as a share of eligible citizens, in percentage points, scored on counties whose actual turnout isn't imputed (2,843 in 2018, 3,094 in 2022).

| | 2018 | 2022 |
|---|---|---|
| Mean absolute error, model | **6.4** | **4.2** |
| Mean absolute error, same as last midterm | 10.5 | 4.6 |
| Weighted by eligible population, model | **8.9** | **4.6** |
| Weighted, same as last midterm | 14.0 | 5.3 |
| 80% interval coverage | 96% | 89% |
| National turnout, 80% band | 38–48% | 44.5–56% |
| National turnout, actual | 50.9% | 46.5% |
| With national turnout known: error / coverage | 5.9 / 99% | 3.9 / 81% |

Without the out-party term, 2022 error was 4.0 (weighted 4.9) and coverage with national turnout known was 72%.

**Reading it.** The model beats the baseline in both years. Most of the remaining error is the national level, which every county shares: 2018's surge was outside the national 80% band. With the national level known, the 2022 county intervals are well calibrated (81%). The 2018 intervals are too wide because that backtest has no training data. Two elections can't tell us much about the calibration of the national band itself; it is wide on purpose.

**2026 (first run).** National median 47.9% of eligible citizens (80%: 42.2–53.5%), on the same basis as the backtests.

### Race Results (5 October)

Each year fitted only on earlier midterms; 2018 runs on priors alone. Scored on races with a Democrat against a Republican (68 in 2018, 70 in 2022).

| | 2018 | 2022 |
|---|---|---|
| Brier score, model | **0.149** | **0.067** |
| Brier, presidential lean (certain call) | 0.221 | 0.086 |
| Brier, lean plus uniform national swing | 0.162 | 0.157 |
| Vote-share error, model (points) | **5.1** | **3.6** |
| Vote-share error, presidential lean | 5.9 | 4.3 |
| Vote-share error, uniform swing | 5.1 | 4.1 |
| 80% interval coverage | 96% | 86% |
| Without the track record: Brier / error | 0.153 / 5.1 | 0.072 / 3.9 |
| Plain lean instead of turnout-weighted: Brier / error | 0.147 / 5.1 | 0.069 / 3.8 |
| With fundraising: Brier / error | 0.153 / 5.1 | 0.069 / 3.7 |

**Fundraising.** The rule, set before testing: keep it only if it improves the 2022 backtest (trained on 2018) on both Brier and vote-share error. It made both worse, so it is not in the model. Once the state's lean, the national environment and the incumbent's record are in, money adds little: well-funded challengers mostly run where the race was already close.

**Review of the 5 October Cursor branch.** Its Stage B used the final pre-election generic ballot in the backtests, invented special-election swings for 2018 and 2022, and error floors tuned to the 2022 backtest, so its backtests were not out of sample. It was rebuilt on these inputs; the California and Tennessee 2022 results and the early-vote download were kept.

## 6. Deliverables

1. **Forecast post (week of 19 October):** method, hero visuals, a race table, and a link to the tagged commit.
2. **Weekly updates:** a short note and a refreshed chart as early vote arrives.
3. **Scorecard post (week of 9 November):** forecast against result, calibration, and what I got wrong and why.
4. **Portfolio case study:** the full write-up, with figures in the site style.

**Signature visuals:**
- County map of forecast turnout change, 2026 against 2022 (hero image).
- Swarm of Senate and governor races by win probability (most shareable).
- Backtest calibration chart, predicted against actual for 2018 and 2022.
- After the election: forecast against result for every race, plus a county turnout error map.

## 7. Timeline

| Dates | Work |
|---|---|
| 28 Sep – 4 Oct | Confirm data sources; build the historical county dataset (results, turnout, ACS) |
| 5 – 11 Oct | Turnout model (Stage A) and its 2018 and 2022 backtests |
| 12 – 18 Oct | Vote-share model (Stage B), correlated simulation, race backtests, calibration |
| 19 Oct | **Publish forecast v1** as a tagged commit, with the post and visuals |
| 20 Oct – 2 Nov | Weekly updates with early vote (v2, v3) |
| 3 Nov | Election Day. Freeze the final forecast (tag `final`) |
| 4 – 10 Nov | Collect results as they certify; score; publish the scorecard |

## 8. Repository

```
midterms-2026/
├── PLAN.md               this plan
├── requirements.txt
├── data/raw/             downloaded sources (not committed)
├── data/processed/       cleaned county and race tables (not committed)
├── src/forecast/         ingest.py, features.py, turnout_model.py, vote_model.py, simulate.py, backtest.py
├── notebooks/            exploration only; nothing the forecast depends on
├── figures/              chart scripts, using the portfolio's figstyle
├── forecasts/            published forecast CSVs, one per tagged version
└── tests/                data checks (county counts, turnout between 0 and 1, totals match certified)
```

## 9. Risks

- **Data gaps:** some states report results or early vote late or inconsistently. Fall back to state-level turnout where county data is missing, and say so.
- **Polling scarcity:** the generic ballot is noisy. Weight special elections and fundamentals, and widen the uncertainty.
- **Time:** 36 days is tight. The House is a stretch goal for this reason.
- **Being wrong:** likely on some races. The value is calibration and transparency; the scorecard post is part of the plan, not damage control.

## 10. Next Actions

1. ~~Build the county presidential panel, 2008–2024, with CVAP turnout and ACS demographics.~~ Done 29 September (`python -m forecast.ingest`, checks in `tests/`).
2. ~~Aggregate 2018 and 2022 precinct files to county midterm turnout and results, and add 2014 turnout.~~ Done 4 October (`python -m forecast.midterms`).
3. ~~Turnout model (Stage A) with 2018 and 2022 backtests.~~ First version done 4 October; refresh with October early vote.
4. ~~Generic ballot as of 30 September, and race lists and results.~~ Done 5 October (`generic_ballot.py`, `races.py`).
5. ~~Vote-share model (Stage B) with correlated simulation and 2018/2022 race backtests.~~ Done 5 October (`vote_model.py`); beats both baselines in both years.
6. ~~FEC fundraising for nominees.~~ Tested 5 October; it made the 2022 backtest worse, so it is left out.
7. ~~Early vote: compare each state's 2026 pace with its own 2022 pace on the same date before using it.~~ Built 13 October; it can't be backtested, so it is left out (see Early Vote Test). Optional: a descriptive chart of 2026 pace against 2022 turnout, with the voting-rule caveats.
8. Race polls: built 14 October, being tested under the same rule (`notes/race_polls.md`).
10. Forecast v1 (19 October): refresh the 2026 race and House pages and the generic ballot, run `python -m forecast.pipeline --refresh`, then `python -m forecast.release v1`, tag.
9. Before the scorecard: save the UF early-vote CSV every day to Election Day (`python -m forecast.early_vote` keeps a dated copy), so 2030 has a dated 2026 series to test against. Check the voting-rule list in `early_vote.RULE_CHANGES` against NCSL's tables.

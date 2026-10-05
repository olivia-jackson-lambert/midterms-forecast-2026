# 2026 Midterms: A Turnout-First Forecast

**Goal:** publish a transparent, falsifiable forecast of the 3 November 2026 midterms before Election Day, then score it honestly afterwards.

**Angle:** most public forecasts predict who wins. This one starts with turnout, forecasting how many people vote in each county, and builds vote share on top of that.

**Status:** planning. Today is 28 September 2026, and Election Day is 3 November 2026, 36 days away.

---

## 1. What We Forecast

**Must have:**
1. County-level turnout for November 2026, as a share of the voting-age population, with an 80% interval.
2. Two-party vote share and win probability for every 2026 **Senate** and **governor** race, about 70 races.

**Stretch goal:** the House, 435 districts. Attempt it only if the Senate and governor model is finished and backtested by 19 October.

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
| Generic ballot, 2018 and 2022 (backtests) | Wikipedia House election-ratings aggregate tables (RCP + FiveThirtyEight eve-of-election averages); code in `generic_ballot.py` | ✅ rebuilt from public listings |
| Generic ballot, 2026 | Wikipedia 2026 House elections aggregate table (DDHQ, FiftyPlusOne, NBC, RCP, Silver Bulletin). FiftyPlusOne site reachable; RealClearPolling returns 403 here; FiveThirtyEight project page has no usable poll JSON | ✅ first snapshot in ingest; refresh before publish |
| 2025–26 special elections | Ballotpedia congressional specials + VA governor 2025 (curated in `special_elections.py`) | ✅ series + swing vs 2024 presidential; refresh before publish |
| Race fundamentals: incumbency, open seats | Ballotpedia 2026 Senate and governor pages (curated constants in `races.py`; live HTML often empty from this env) | ✅ race list compiled; re-check before publish |
| Candidate fundraising | FEC OpenFEC API (`fundraising.py`, DEMO_KEY); Senate only — governors are not in FEC | ✅ Senate hook; GOV still 0 |
| Early and mail vote, October 2026 | US Elections Project (site reachable); state dashboards | ☐ confirm 2026 page |
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
- early-vote signal in October, where states report it.

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
4. ~~Rebuild the 2018 and 2022 generic-ballot averages from public poll listings.~~ Done 5 October (`python -m forecast.generic_ballot`); 2026 snapshot included.
5. ~~Compile 2026 races, incumbency and special elections from Ballotpedia; fill the California 2022 Senate and Tennessee 2022 governor results from the states.~~ Race list + CA/TN gaps done 5 October (`forecast.races`, supplements in `midterms.py`). Special-election over-performance series: done 5 October (`forecast.special_elections`; House specials + VA governor 2025 vs 2024 presidential).
6. Vote-share model (Stage B) with correlated simulation and 2018/2022 race backtests. In progress 5 October: scaffold + GB/specials swing blend + races incumbency + FEC Senate fundraising hook + PyMC fit (ridge fallback) + race backtest/calibration gates in `forecast.backtest`. Still open: governor fundraising (no FEC), historical 2018/2022 incumbency curation, full data-backed race backtest run on a machine with `county_panel` + midterm results, October early-vote refresh for Stage A.

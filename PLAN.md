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

Every source is public. Mark each one ✅ once its availability and licence are confirmed.

| Need | Source | Status |
|---|---|---|
| County presidential results, 2000–2024 | MIT Election Data + Science Lab (Harvard Dataverse) | ☐ |
| County / state Senate and governor results, 2000–2024 | MIT Election Lab; state secretaries of state for gaps | ☐ |
| County turnout (total ballots cast) | MIT Election Lab plus state certified results | ☐ |
| Voting-age and citizen voting-age population | Census ACS 5-year, CVAP special tabulation | ☐ |
| County demographics (age, education, income, density) | Census ACS 5-year | ☐ |
| National environment (generic ballot) | Public polling averages, e.g. RealClearPolling. FiveThirtyEight closed in 2025, so check whether its archive on GitHub is still usable for backtests | ☐ |
| 2025–26 special election over- and under-performance | Compiled from public special-election results, e.g. Ballotpedia and The Downballot | ☐ |
| Race fundamentals: incumbency, open seats | Ballotpedia and Wikipedia race pages | ☐ |
| Candidate fundraising | FEC API, aggregate totals only | ☐ |
| Early and mail vote, weekly in October | US Elections Project (Michael McDonald), state early-vote dashboards | ☐ |
| County shapefiles | Census TIGER/Line | ☐ |

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

## 5. Backtest (The Credibility)

For **2018** and **2022**, fit the model using only data available on 1 October of that year, then score it against the actual results:
- **Races:** Brier score, log loss, and calibration (do the "70%" races win about 70% of the time?).
- **Turnout:** county mean absolute error and 80% interval coverage (does the truth fall inside the 80% band about 80% of the time?).
- **Baselines to beat:** "same as last midterm" for turnout, and "same as the last presidential lean" for vote share.

If the model doesn't beat the baselines in backtest, don't publish it as a forecast. Publish it as an analysis instead.

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

1. Confirm each data source in section 3 and tick it off.
2. Build `src/forecast/ingest.py` for the MIT Election Lab county returns and ACS, then a first county panel for 2000–2024.

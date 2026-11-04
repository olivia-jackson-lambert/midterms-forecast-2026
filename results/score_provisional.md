# Forecast v1: Provisional Score

**Provisional.** Results pulled from the AP public results feed at 2026-11-04T10:41:53Z. Counting is still under way and the uncalled races are left out; these numbers will change, and the final score waits for certification. v1 is scored as published on 22 October 2026.

## Race Calls

| | Called | Favourite won | Upsets | Expected upsets | Brier | Log loss | Baseline Brier (2024 lean) |
|---|---|---|---|---|---|---|---|
| Senate | 30 of 32 | 27 | 3 | 2.6 | 0.066 | 0.198 | 0.267 |
| Governor | 34 of 36 | 31 | 3 | 3.0 | 0.051 | 0.169 | 0.324 |
| House | 360 of 435 | 346 | 14 | 14.1 | 0.025 | 0.081 | 0.089 |
| All three | 424 of 503 | 404 | 20 | 19.8 | 0.030 | 0.096 | 0.120 |
| Independent challengers (NE, ID, SD) | 3 of 3 | 3 | 0 | 0.3 | 0.028 | 0.121 | 0.000 |

The event scored is the one v1 gave a probability for: a win for the Democratic side (in Nebraska, Idaho and South Dakota, the independent). The baseline calls every race for the party that won it in the 2024 presidential vote. The three independent-challenger races are reported on their own and left out of the Senate and all-race rows; including them, the Senate Brier is 0.062 over 33 called races.

## Upsets

| Race | Winner | v1's chance for the winner |
|---|---|---|
| TX-15 | Bobby Pulido (Democrat) | 6% |
| IN-05 | J. D. Ford (Democrat) | 8% |
| SC-SEN | Annie Andrews (Democrat) | 14% |
| TX-GOV | Gina Hinojosa (Democrat) | 18% |
| OH-07 | Brian Poindexter (Democrat) | 23% |
| KY-06 | Zach Dembo (Democrat) | 26% |
| TX-23 | Katy Padilla Stout (Democrat) | 27% |
| OH-15 | Don Leonard (Democrat) | 28% |
| IA-01 | Christina Bohannan (Democrat) | 34% |
| PA-08 | Paige Cognetti (Democrat) | 34% |
| KS-SEN | Adam Hamilton (Democrat) | 35% |
| MO-02 | Fred Wellman (Democrat) | 36% |
| NV-GOV | Aaron Ford (Democrat) | 37% |
| WI-03 | Rebecca Cooke (Democrat) | 39% |
| IA-SEN | Josh Turek (Democrat) | 43% |
| GA-GOV | Keisha Lance Bottoms (Democrat) | 46% |
| TX-35 | Johnny Garcia (Democrat) | 47% |
| FL-22 | Pia Dandiya (Democrat) | 48% |
| IA-02 | Lindsay James (Democrat) | 49% |
| PA-10 | Janelle Stelson (Democrat) | 49.5% |

Winners of the upsets by party: Democrats 20.

## Calibration

Called races by v1's probability of a Democratic-side win.

| Bin | Senate and governor: races | mean p | won | House: races | mean p | won |
|---|---|---|---|---|---|---|
| 0.0-0.2 | 23 | 0.04 | 0.09 | 136 | 0.02 | 0.01 |
| 0.2-0.4 | 3 | 0.36 | 0.67 | 12 | 0.29 | 0.67 |
| 0.4-0.6 | 4 | 0.51 | 1.00 | 9 | 0.51 | 1.00 |
| 0.6-0.8 | 3 | 0.74 | 1.00 | 9 | 0.70 | 1.00 |
| 0.8-1.0 | 31 | 0.96 | 1.00 | 194 | 0.99 | 1.00 |

## Two-Party Vote Share

Called Democrat-against-Republican races with at least 85% of the expected vote counted. Error is the actual Democratic share minus v1's median, in points.

| | Races | Mean error | MAE | RMSE | Below 80% | Inside 80% | Above 80% | Coverage | Baseline MAE |
|---|---|---|---|---|---|---|---|---|---|
| Senate | 26 | 3.47 | 3.47 | 3.80 | 0 | 15 | 11 | 58% | 8.54 |
| Governor | 26 | 1.81 | 3.73 | 5.05 | 1 | 18 | 7 | 69% | 8.35 |
| House | 253 | 3.28 | 3.63 | 4.50 | 3 | 163 | 87 | 64% | 7.46 |
| All three | 305 | 3.17 | 3.62 | 4.49 | 4 | 196 | 105 | 64% | 7.63 |
| Independent challengers (NE, ID, SD) | 3 | -2.93 | 2.93 | 3.10 | 1 | 2 | 0 | 67% | 5.78 |

In MT-SEN (Seth Bodnar), RI-GOV (Kenneth Block), WY-GOV (Rebecca Bextel), AK-AL (Bill Hill), a candidate outside v1's Democrat-against-Republican pairing placed in the top two. The share is still the Democrat's share of the Democratic-plus-Republican vote, as v1 defined it, so these results say more about the third candidate than about the two parties. In the table: RI-GOV, WY-GOV. Without them, the all-race row is 303 races, mean error 3.21, MAE 3.55, RMSE 4.36, coverage 65% (3 below, 104 above).

The target coverage is 80%, with about 10% of results on each side. For the independent challengers the share is the independent's share of the independent-plus-Republican vote. The baseline is the 2024 presidential two-party share of the state or district.

## Seats and Control

| | Democrats | Republicans | Other | Complete | Control | v1's chance for that party | v1 median (80% range) | Percentile |
|---|---|---|---|---|---|---|---|---|
| Senate | 54 | 44 | 0 | no | Democrats | 63% | 51 (48 to 54) | not final; between 92% and 99% |
| House | 222 | 138 | 0 | no | Democrats | 92% | 234 (220 to 252) | not final; between 15% and 100% |
| Governor | 28 | 20 | 0 | no | Democrats | 62% | 26 (23 to 29) | not final; between 81% and 96% |

Seats include those not up in 2026 (Senate: Democratic caucus, with independents who caucus with Democrats). Senate control needs 51 Democratic-caucus seats or 50 Republican; a governor majority is 26.

## Not Yet Scored

- Uncalled: 2 Senate (AK-SEN, MS-SEN), 2 governor (AK-GOV, KS-GOV) and 75 House races. Races in a runoff count as uncalled.
- Turnout: not scored. Counts are far from final, especially where mail ballots arrive late, so every turnout measure is left null.
- Montana's Senate race, a weakness stated before the election: v1 modelled it as the Democrat against the Republican, though the main challenger is an independent. Kurt Alme (R) won; v1 gave the Republican 100%. The Democrat's share of the Democratic-plus-Republican vote is 19.8% against v1's median of 34.2% (80% interval 31.3% to 37.4%), with 83% counted, below the threshold for the vote-share table.

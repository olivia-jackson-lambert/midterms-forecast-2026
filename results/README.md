# Results

The 2026 results that forecast v1 is scored against, and the provisional score. Everything here
describes what happened; nothing in it changes v1 (`forecasts/v1/`, tag `v1`).
The provisional score is written up in [The Provisional Scorecard](https://oliviajacksonlambert.com/project/projects_files/scorecard-2026/scorecard-2026.html) and shown race by race in the [results view](https://oliviajacksonlambert.com/midterms-2026/#results).

| File | What it holds | Written by |
|---|---|---|
| `results_log.csv` | One row per v1 race per pull: call, winner, Democratic-side and Republican votes, two-party share, share of the expected vote counted, source URL and pull time | `python -m forecast.results` |
| `crosscheck_wikipedia.csv` | Senate and governor winners on Wikipedia against AP's calls, with the page revisions used | `python -m forecast.crosscheck` |
| `results.json` | The file the site reads, in the shape set out in `docs/results-contract.md` | `python -m forecast.score` |
| `score_provisional.json` | Every measure, in full: groups, calibration bins, upsets, baselines, seat ranges | `python -m forecast.score` |
| `score_provisional.md` | A short summary of the provisional score | `python -m forecast.score` |

The status stays **provisional** until the states certify; each pull is kept in the log, so a
provisional score can always be traced to the pull behind it and told apart from the certified one.

## Sources

**Race calls and vote counts: the Associated Press public results feed.** The JSON files behind
AP's own results pages and the embeds news sites use, which need no login or key:

- `https://interactives.apelections.org/election-results/data-live/2026-11-03/results/national/metadata.json`
  (offices, candidates, call status)
- `https://interactives.apelections.org/election-results/data-live/2026-11-03/results/national/progress.json`
  (vote counts, expected vote counted, winners)

Two notes on access. The files are gzip bytes whatever the request asks for, so an undecoded
`curl` looks like a short binary stub; decompressed, they are the whole feed (every Senate,
governor and House race in one pair of files, so the per-state files are not needed). And the
CDN refuses Python's HTTP client and curl's default User-Agent with a 403, but serves curl with
the project's own descriptive User-Agent, so the pull uses curl with that header; it identifies
itself rather than imitating a browser. Each pull is two requests, two seconds apart. The raw
files are kept locally under `data/raw/results_2026/<pull time>/` and are not committed: they are
AP's, and the curated log holds every field the score uses.

**Cross-check: Wikipedia** ("2026 United States Senate elections" and "2026 United States
gubernatorial elections", rendered HTML at a recorded revision). On election night editors often
mark a winner before AP calls a race, so a winner on Wikipedia alone is never treated as a call;
the cross-check only looks for disagreements between the two. The House is not cross-checked yet.

**Not yet used: state election offices.** Issue #15 asks for state results, cross-checked against
a second source. They are the source for the certified score and for turnout; on the night after
the election their counts are no more complete than AP's, and each state publishes in its own
format, so they are left for the certified pull.

## Definitions

Follow v1 (see the docstrings of `forecast.results` and `forecast.score`):

- `id` is races.csv's `race_id` for Senate and governor races and house_districts.csv's `cd` for the House.
- `dem_votes` is the Democratic side's vote: all Democratic candidates' votes (party totals, as on
  Louisiana's all-party ballot), or the stand-in independent's where v1's Democratic side is an
  independent (Nebraska, Idaho and South Dakota for the Senate; House stand-ins likewise for
  either side). `dem_share_2p` = `dem_votes` / (`dem_votes` + `rep_votes`); it is blank where a side
  is missing (one-party and same-party races) or no votes are counted.
- `pct_counted` is AP's expected vote counted, as a fraction (AP caps it at 0.99 until the count is final).
- `called` is true only when AP's status is "Called". A race sent to a runoff (Louisiana's House
  races, Georgia's if needed) is not called. `winner_party` is D, R or I (any other party).
- `winner_name` uses v1's spelling where v1 named the winner ("Keisha Lance Bottoms", "Ben Ray Luján"),
  so the log, the site and v1 agree; AP's own name (first and last) otherwise.
- `outside_top_two` names any candidate outside v1's pairing who placed in the top two (write-in
  totals aside): Montana's independent, Wyoming's Constitution Party nominee, Rhode Island's
  independent, Alaska's nonpartisan House candidate. `dem_share_2p` there is still v1's Democrat
  against Republican share, so it is far from the main contest's margin; the score reports the
  vote-share measures with and without these races.
- Where an independent stands in for a missing party in the House (PA-03, CA-06, MA-01, NJ-08),
  `dem_share_2p` is the Democrat's share of the Democrat-plus-stand-in vote, the same definition
  as v1's median for those districts. These districts are not Democrat against Republican, so they
  are left out of the vote-share measures, as in the backtests.
- Blank means unknown. Nothing is interpolated or estimated.

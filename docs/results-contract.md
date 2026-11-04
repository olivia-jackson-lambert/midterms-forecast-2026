# Results Data Contract (v1 scoring and the site's Results view)

One JSON file, `results.json`, written by the forecast repo's scoring code and copied to the site at
`midterms-2026/data/results.json`. The site reads it alongside the v1 CSVs it already has in `midterms-2026/data/`.
Everything the site shows about the results comes from this file plus v1; the site computes nothing it cannot recompute
from these two.

```json
{
  "schema": 1,
  "as_of": "2026-11-04T05:18:00Z",          // when the results were pulled (UTC)
  "status": "provisional",                   // "provisional" until certification, then "certified"
  "note": "Calls from ... ; counts from ...",// one plain sentence on the sources, shown on the page
  "races": [                                  // every v1 race: 35 Senate + 36 governor rows from races.csv, 435 House rows
    {
      "id": "2026-TX-SEN",                    // races.csv race_id, or house_districts.csv cd (e.g. "PA-08")
      "office": "senate",                     // senate | governor | house
      "called": true,
      "winner_party": "D",                    // D | R | I | null when not called
      "winner_name": "James Talarico",        // null when not called
      "dem_share_2p": 0.512,                  // actual Democratic share of the two-party vote, null if unknown
      "pct_counted": 0.97,                    // share of expected vote counted, null if unknown
      "source": "https://...",                // where this row came from
      "pulled_at": "2026-11-04T05:18:00Z"
    }
  ],
  "chambers": {
    "senate":   { "dem_seats": 52,   "rep_seats": 48,   "ind_seats": 0, "control": "D",  "complete": false },
    "house":    { "dem_seats": null, "rep_seats": null, "ind_seats": 0, "control": null, "complete": false },
    "governor": { "dem_seats": null, "rep_seats": null, "ind_seats": 0, "control": null, "complete": false }
  },
  "turnout": {
    "national": null,                         // ballots cast / citizen voting-age population, same denominator as v1
    "states": { "AK": null }                  // two-letter code -> turnout share, null until near final
  },
  "score": {                                  // computed by the scoring script over called races only
    "all":      { "called": 347, "favourites_won": 335, "upsets": 12, "expected_upsets": 14.0, "brier": 0.023, "log_loss": null },
    "senate":   { "called": 27, "favourites_won": 24, "upsets": 3, "expected_upsets": 2.1, "brier": 0.070, "log_loss": null },
    "house":    { "called": 297, "favourites_won": 290, "upsets": 7, "expected_upsets": 9.7, "brier": 0.016, "log_loss": null },
    "governor": { "called": 23, "favourites_won": 21, "upsets": 2, "expected_upsets": 2.2, "brier": 0.057, "log_loss": null },
    "vote_share": { "n": 254, "mean_error_toward_dem": 3.5, "mae": null, "above_80": 87, "inside_80": 166, "below_80": 1 },
    "seat_percentiles": { "senate": 0.652, "house": null, "governor": null }
  },
  "comparison": {
    "as_of": "2026-10-22",
    "senate_control": [
      { "name": "Silver Bulletin", "p_dem": 0.75, "source": "news reports, 19 to 25 Oct", "captured": null, "news_report": true },
      { "name": "Polymarket", "p_dem": 0.69, "source": "https://web.archive.org/...", "captured": "2026-10-22T22:50:00Z", "news_report": false },
      { "name": "v1", "p_dem": 0.63, "source": "forecasts/v1", "captured": "2026-10-22", "news_report": false },
      { "name": "DDHQ / The Hill", "p_dem": 0.56, "source": "https://web.archive.org/...", "captured": "2026-10-22", "news_report": false }
    ],
    "races": [                                // one row per forecaster per race; exactly one of p_dem, rating, margin_dem set
      { "id": "2026-TX-SEN", "forecaster": "DDHQ / The Hill", "p_dem": 0.56, "rating": null, "margin_dem": null, "source": "...", "captured": "..." }
    ],
    "final": { "senate_control": [], "races": [] }   // the same shapes, each forecaster's last pre-election numbers
  }
}
```

Rules
- Public sources only, each row with its URL and pull time. Anything taken from a news report rather than the forecaster's
  own page has `news_report: true`.
- v1 is never edited. Results only describe what happened.
- Null means unknown; the site must show "still counting" or a placeholder for nulls, never a guess.
- The numbers above are the 12:18 AM ET snapshot from issue #24 and #25; use them as the sample file until the real pull
  exists.

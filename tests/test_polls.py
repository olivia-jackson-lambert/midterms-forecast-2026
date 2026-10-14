"""Offline checks on the race-poll layer (forecast.polls), on saved HTML snippets."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from forecast import polls

FIX = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def snippet() -> pd.DataFrame:
    html = (FIX / "polls_senate_snippet.html").read_text()
    return polls.parse_polls(html, "Tom Okafor", "Jane Rivera", 2018)


def test_parser_keeps_only_the_nominees_head_to_head(snippet):
    # Not the primary table, not the aggregator row, not the hypothetical Okafor v Lee table.
    assert set(snippet["pollster"]) == {"Late Poll", "Uni Poll (D-Friends PAC)", "State Survey",
                                        "Uni Poll (R-Other Group)", "Old Poll"}
    assert (snippet["section"] == "General election").all()
    assert len(snippet) == 6                        # Uni Poll's LV and RV rows are both kept here


def test_parser_reads_dates_sizes_and_populations(snippet):
    r = snippet.set_index(["pollster", "population"])
    late = r.loc[("Late Poll", "LV")]
    assert late["start"] == pd.Timestamp("2018-09-28") and late["end"] == pd.Timestamp("2018-10-02")
    assert late["n"] == 800 and late["dem_pct"] == 50 and late["rep_pct"] == 45
    rv = r.loc[("Uni Poll (D-Friends PAC)", "RV")]          # rowspan: dates shared with the LV row
    assert rv["end"] == pd.Timestamp("2018-09-25") and rv["n"] == 1000
    assert r.loc[("State Survey", ""), "n"] == 2500          # no population given
    assert r.loc[("Old Poll", "RV"), "end"] == pd.Timestamp("2018-06-02")


@pytest.mark.parametrize("text, start, end", [
    ("September 20–25, 2018", "2018-09-20", "2018-09-25"),
    ("May 29 – June 5, 2018", "2018-05-29", "2018-06-05"),
    ("Sep 30 – Oct 2, 2022", "2022-09-30", "2022-10-02"),
    ("December 28, 2017 – January 2, 2018", "2017-12-28", "2018-01-02"),
    ("October 1, 2018", "2018-10-01", "2018-10-01"),
    ("September 2018", "2018-09-01", "2018-09-30"),
])
def test_parse_dates(text, start, end):
    assert polls.parse_dates(text, 2018) == (pd.Timestamp(start), pd.Timestamp(end))


def test_cut_off_uses_the_end_of_fieldwork(snippet):
    q = polls.qualifying(snippet, "2018-09-26")
    assert "Late Poll" not in set(q["pollster"])            # ended 2 October
    assert "Old Poll" not in set(q["pollster"])             # ended more than 90 days before
    assert pd.Timestamp("2018-09-25") in set(q["end"])      # ended the day before: kept
    assert q["end"].max() <= pd.Timestamp("2018-09-26")


def test_one_poll_per_pollster_prefers_latest_and_likely_voters(snippet):
    p = polls.one_per_pollster(polls.qualifying(snippet, "2018-09-26"))
    assert len(p) == 2                                       # Uni Poll (two sponsors) and State Survey
    uni = p[p["pollster"].str.startswith("Uni Poll")].iloc[0]
    assert uni["population"] == "LV" and uni["end"] == pd.Timestamp("2018-09-25")


def test_average_by_hand(snippet):
    a = polls.average(snippet, "2018-09-26")
    w_uni = 0.5 ** (1 / 21) * np.sqrt(700 / 600) * 1.0
    w_state = 0.5 ** (14 / 21) * np.sqrt(2000 / 600) * 1.0  # sample size capped at 2,000
    expected = (w_uni * 48 / 92 + w_state * 0.5) / (w_uni + w_state)
    assert a["n_polls"] == 2
    assert a["poll_avg"] == pytest.approx(expected)
    assert a["n_eff"] == pytest.approx((w_uni + w_state) ** 2 / (w_uni ** 2 + w_state ** 2))


def test_no_qualifying_polls_gives_an_empty_average(snippet):
    a = polls.average(snippet, "2018-05-01")
    assert a["n_polls"] == 0 and np.isnan(a["poll_avg"])


def test_names_match_surnames_with_accents_and_suffixes():
    cols = ["Poll source", "Ben Ray Luján (D)", "Bob Casey Jr. (D)", "Beto O’Rourke (D)"]
    assert polls._match(cols, "Ben Ray Lujan") == "Ben Ray Luján (D)"
    assert polls._match(cols, "Bob Casey Jr.") == "Bob Casey Jr. (D)"
    assert polls._match(cols, "Beto O'Rourke") == "Beto O’Rourke (D)"
    assert polls._match(["Dan Sullivan (R)", "Dan S. Sullivan (R)"], "Mary Peltola") is None
    namesakes = ["Dan S. Sullivan (R)", "Mary Peltola (D)", "Dan J. Sullivan (R)"]
    assert polls._match(namesakes, "Dan S. Sullivan") == "Dan S. Sullivan (R)"
    assert polls._match(namesakes, "Dan Sullivan") is None                  # ambiguous: no match


def test_blend_moves_towards_polls_by_precision():
    f = pd.DataFrame({"race_id": ["a", "b"]})
    rng = np.random.default_rng(1)
    sims = 1 / (1 + np.exp(-(0.2 * rng.standard_normal((40_000, 2)))))      # centred on 50%
    avgs = pd.DataFrame({"race_id": ["a"], "poll_avg": [0.55], "n_polls": [5], "n_eff": [4.0],
                         "last_poll": [pd.NaT]})
    err = {"s_nat": np.full(100, 0.05), "s_floor": np.full(100, 0.06), "s_poll": np.full(100, 0.09)}
    out, info = polls.blend(f, sims.astype(np.float32), 2018, [], errors=err, avgs=avgs)
    v_f, v_p = 0.2 ** 2, 0.05 ** 2 + 0.06 ** 2 + 0.09 ** 2 / 4
    k = v_f / (v_f + v_p)
    lg = np.log(out / (1 - out))
    assert np.median(lg[:, 0]) == pytest.approx(k * np.log(0.55 / 0.45), abs=0.01)
    assert lg[:, 0].var() == pytest.approx(v_f * v_p / (v_f + v_p), rel=0.05)
    assert np.allclose(out[:, 1], sims[:, 1], atol=1e-6)              # no polls: unchanged
    assert info.loc[1, "poll_weight"] == 0

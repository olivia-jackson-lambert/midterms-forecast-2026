"""Method diagrams for the Turnout First 2026 write-up, in the site's diagram style.

The box and arrow helpers follow the flight-delay case study's make_diagrams.py (rounded
boxes, Lora titles with grey subtitles, top-to-bottom flow). Colours follow this project's
rule: slate and rust are kept for party, so diagrams use greys with the green accent.

    python figures/make_diagrams.py          # writes figures/out/pipeline_overview.png and
                                             # figures/out/what_was_tested.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from figstyle import DIM, INK, LIGHT, MUTED, PAPER, apply  # noqa: E402
from palette import GREEN, GREEN_DEEP  # noqa: E402

OUT = HERE / "out"
GREEN_TINT = "#e3ede6"
TITLE_PT, SUB_PT = 9.8, 8.4
TITLE_LH, SUB_LH = 0.19, 0.165


def canvas(w, h):
    fig = plt.figure(figsize=(w, h))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.axis("off")
    return fig, ax


def box(ax, cx, cy, w, h, title, subs=(), fill=PAPER, edge=LIGHT, lw=0.9, dashed=False):
    ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h, boxstyle="round,pad=0,rounding_size=0.07",
                                fc=fill, ec=edge, lw=lw, ls=(0, (3, 2)) if dashed else "-"))
    tlines = title.split("\n") if title else []
    y = cy - (len(tlines) * TITLE_LH + len(subs) * SUB_LH) / 2
    for t in tlines:
        ax.text(cx, y + TITLE_LH / 2, t, ha="center", va="center", fontsize=TITLE_PT,
                fontweight="semibold", color=INK)
        y += TITLE_LH
    for s in subs:
        ax.text(cx, y + SUB_LH / 2, s, ha="center", va="center", fontsize=SUB_PT, color=DIM)
        y += SUB_LH


def arrow(ax, p, q, color=MUTED, dashed=False, lw=1.1):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=9, color=color, lw=lw,
                                 shrinkA=0, shrinkB=0, ls=(0, (3, 2)) if dashed else "-"))


def save(fig, name):
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", pad_inches=0.08, facecolor="white")
    plt.close(fig)
    print("  wrote", name)


def model_box(ax, cx, cy, w, h, title, subs):
    box(ax, cx, cy, w, h, title, subs, fill=GREEN_TINT, edge=GREEN, lw=0.8)


def pipeline_overview() -> None:
    W, H = 7.0, 10.6
    fig, ax = canvas(W, H)
    cx = W / 2

    # Sources
    y_src = 0.5
    src = [(0.95, "Election\nResults", ["MIT precincts,", "Wikipedia, states"]),
           (2.68, "Ballots\nCast", ["EAC survey, UF", "certified totals"]),
           (4.32, "Census", ["Citizens of voting", "age, ACS"]),
           (6.05, "Generic\nBallot", ["Aggregators, 1998", "onwards"])]
    for x, t, s in src:
        box(ax, x, y_src, 1.55, 0.9, t, s)

    # Ingest
    y_in = 1.85
    box(ax, cx, y_in, 3.6, 0.72, "Ingest and Checks",
        ["3,104 county units, reconciled to certified totals", "Values as of 1 October for every backtest"])
    for x, _, _ in src[:3]:
        arrow(ax, (x, y_src + 0.45), (cx - 0.4 + (x - cx) * 0.25, y_in - 0.36))

    # Stage A
    y_a = 3.2
    model_box(ax, 2.3, y_a, 3.3, 0.86, "Stage A: County Turnout",
              ["Change since the last midterm (PyMC);", "national level from the midterm drop"])
    arrow(ax, (cx - 0.6, y_in + 0.36), (2.3, y_a - 0.43))

    # National vote (generic ballot) and race polls
    y_nat = 3.2
    box(ax, 5.55, y_nat, 2.5, 0.86, "National House Vote",
        ["Generic ballot on 30 September,", "bias from earlier cycles only"])
    arrow(ax, (6.05, y_src + 0.45), (5.75, y_nat - 0.43))

    # Stage B and House
    y_b = 4.75
    model_box(ax, 1.95, y_b, 3.3, 1.05, "Stage B: Senate and Governor",
              ["71 races: turnout-weighted lean,", "national vote, incumbency,", "incumbent track record (PyMC)"])
    model_box(ax, 5.3, y_b, 2.9, 1.05, "House",
              ["435 districts on 2026 maps:", "district lean, national vote,", "incumbency (PyMC)"])
    arrow(ax, (2.3, y_a + 0.43), (1.95, y_b - 0.525))
    ax.text(2.0, (y_a + y_b) / 2 + 0.02, "Turnout-weighted leans", fontsize=7.8, style="italic", color=MUTED,
            ha="right", va="center")
    arrow(ax, (5.3, y_nat + 0.43), (5.3, y_b - 0.525))
    arrow(ax, (4.75, y_nat + 0.43), (2.9, y_b - 0.525))

    # Polls blend
    y_p = 6.15
    model_box(ax, 1.95, y_p, 3.3, 0.86, "Race Polls Blended In",
              ["Weighted by how accurate polls were", "in earlier years; shared polling miss"])
    arrow(ax, (1.95, y_b + 0.525), (1.95, y_p - 0.43))
    box(ax, 4.8, y_p, 1.4, 0.86, "Race Polls", ["Wikipedia, one", "per pollster"])
    arrow(ax, (4.1, y_p), (3.6, y_p))

    # Simulation
    y_s = 7.45
    box(ax, cx, y_s, 4.6, 0.86, "20,000 Joint Simulations",
        ["Each draws a turnout scenario and a national vote,", "with shared regional, state and race errors"],
        fill=GREEN_TINT, edge=GREEN_DEEP, lw=1.0)
    arrow(ax, (1.95, y_p + 0.43), (2.4, y_s - 0.43))
    arrow(ax, (6.3, y_b + 0.525), (5.7, y_s - 0.43))

    # Outputs
    y_o = 8.75
    outs = [(1.25, "County\nTurnout", ["Median and 80% range"]),
            (3.5, "Race\nProbabilities", ["Every Senate, governor", "and House race"]),
            (5.75, "Chamber\nControl", ["Senate, House and", "governorships"])]
    for x, t, s in outs:
        box(ax, x, y_o, 2.0, 0.92, t, s)
        arrow(ax, (cx + (x - cx) * 0.4, y_s + 0.43), (x, y_o - 0.46))

    # Backtest gate
    y_g = 10.05
    box(ax, cx, y_g, 5.4, 0.72, "Backtests: 2018 and 2022",
        ["Each input stays only if it beats simple baselines out of sample"],
        fill="white", edge=GREEN_DEEP, lw=1.2, dashed=True)
    for x, _, _ in outs:
        arrow(ax, (x, y_o + 0.46), (cx + (x - cx) * 0.6, y_g - 0.36), dashed=True)
    save(fig, "pipeline_overview.png")


def what_was_tested() -> None:
    W, H = 7.0, 6.2
    fig, ax = canvas(W, H)
    kept = [("Presidential Surge Carried Over", ["Strongest turnout predictor"]),
            ("Out-Party Lean", ["2022 interval coverage 72% to 81%"]),
            ("Senate Race on the Ballot", ["About +1.3 points of turnout"]),
            ("Incumbent Track Record", ["Race Brier 0.072 to 0.067 (2022)"]),
            ("Race Polls", ["Race Brier 0.067 to 0.031 (2022)"]),
            ("Turnout-Weighted Leans", ["Small edge in 2022, none in 2018"])]
    left = [("Fundraising", ["Worse in 2022: Brier 0.069 v 0.067"]),
            ("Every Nominee's Track Record", ["Worse in 2022: Brier 0.075 v 0.067"]),
            ("Track Record in the House", ["Worse in the 2022 House backtest"]),
            ("Early Vote", ["Untestable: no 2018 state data survive"]),
            ("Special Elections", ["No comparable 2018 or 2022 series"]),
            ("Pundit Ratings", ["Never an input; comparison only"])]
    ax.text(1.8, 0.25, "Kept", ha="center", va="center", fontsize=10.5, fontweight="semibold", color=GREEN_DEEP)
    ax.text(5.2, 0.25, "Tested and Left Out", ha="center", va="center", fontsize=10.5, fontweight="semibold",
            color=DIM)
    for i, (t, s) in enumerate(kept):
        model_box(ax, 1.8, 0.85 + i * 0.88, 3.2, 0.72, t, s)
    for i, (t, s) in enumerate(left):
        box(ax, 5.2, 0.85 + i * 0.88, 3.2, 0.72, t, s, fill="white", edge=MUTED, lw=0.8, dashed=True)
    ax.text(3.5, 6.05, "Rule, set before each test: keep an input only if it improves the 2022 backtest, "
            "fitted on earlier years only.", ha="center", va="center", fontsize=7.8, style="italic", color=MUTED)
    save(fig, "what_was_tested.png")


def main() -> None:
    apply()
    pipeline_overview()
    what_was_tested()


if __name__ == "__main__":
    main()

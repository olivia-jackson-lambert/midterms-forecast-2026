"""Stage B race-backtest calibration figure (PLAN §5 / §6 signature visual).

Uses portfolio figstyle + palette: charcoal for the calibration curve, DEM slate /
REP rust only if a partisan split is drawn. Green = model beats lean baseline.

    python figures/make_race_backtest_figures.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
SITE = Path(os.environ.get("PORTFOLIO_SITE", Path.home() / "Documents/portfolio/olivia-jackson-lambert.github.io"))
sys.path.insert(0, str(SITE / "scripts"))

try:
    from figstyle import DIM, INK, MUTED, apply, note, tidy
except ImportError:
    # Fallback when portfolio figstyle is unreachable (cloud agents).
    INK, DIM, MUTED = "#0b0b0d", "#4a4a4f", "#8a8f97"

    def apply():
        plt.rcParams.update({"font.family": "serif", "axes.spines.top": False, "axes.spines.right": False})

    def tidy(ax, grid_axis="y"):
        ax.grid(axis=grid_axis, color="#e6e6e8", lw=0.8)
        ax.tick_params(colors=DIM)

    def note(ax, text, y=-0.18):
        ax.text(0, y, text, transform=ax.transAxes, fontsize=8, color=MUTED, va="top")

sys.path.insert(0, str(HERE))
try:
    from palette import ACCENT, BASE, CONTEXT, DEM, GREEN, REP  # noqa: E402
except ImportError:
    # Brand tokens from docs/visual-brand.md / figures/palette.py when figstyle absent.
    DEM, REP = "#7189a6", "#b85c38"
    GREEN, BASE, CONTEXT = "#4e7d5b", "#4a4a4f", "#8a8f97"
    ACCENT = GREEN

from forecast.ingest import OUT as DATA  # noqa: E402

OUT = HERE / "out"


def save(fig, name):
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", pad_inches=0.06, facecolor="white")
    plt.close(fig)
    print("  wrote", name)


def calibration() -> None:
    path = DATA / "backtest_races_calibration.csv"
    if not path.exists():
        print("skip calibration: run `python -m forecast.backtest races` first")
        return
    cal = pd.read_csv(path)
    fig, ax = plt.subplots(figsize=(5.2, 5.0))
    ax.plot([0, 1], [0, 1], color=CONTEXT, lw=1.2, ls=(0, (3, 2)), label="Perfect")
    for year, g in cal.groupby("year"):
        ax.plot(g["mean_p"], g["win_rate"], "o-", color=BASE if year == 2018 else ACCENT,
                ms=7, lw=1.6, label=str(year))
        for _, r in g.iterrows():
            ax.text(r["mean_p"], r["win_rate"] + 0.03, str(int(r["n"])), ha="center",
                    fontsize=7.5, color=MUTED)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Predicted Democratic Win Probability")
    ax.set_ylabel("Actual Democratic Win Rate")
    ax.set_aspect("equal")
    tidy(ax, grid_axis="both")
    ax.legend(loc="upper left", frameon=False)
    note(ax, "Bins of Stage B backtest races. Counts annotate each point. "
             "Green accent = 2022; charcoal = 2018.", y=-0.2)
    save(fig, "race_backtest_calibration.png")


def gate_summary() -> None:
    path = DATA / "backtest_races.csv"
    if not path.exists():
        print("skip gate_summary: no backtest_races.csv")
        return
    d = pd.read_csv(path)
    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    x = np.arange(len(d))
    w = 0.35
    ax.bar(x - w / 2, d["brier"], w, color=ACCENT, label="Model")
    ax.bar(x + w / 2, d["baseline_brier"], w, color=MUTED, label="Presidential Lean")
    ax.set_xticks(x, d["year"].astype(str))
    ax.set_ylabel("Brier Score (Lower Is Better)")
    for i, row in d.iterrows():
        mark = "PASS" if row["beats_lean_baseline"] else "FAIL"
        color = GREEN if row["beats_lean_baseline"] else CONTEXT
        ax.text(i, max(row["brier"], row["baseline_brier"]) + 0.01, mark,
                ha="center", fontsize=9, color=color)
    tidy(ax, grid_axis="y")
    ax.legend(frameon=False)
    note(ax, "Publish gate (PLAN §5): model Brier must beat hard presidential-lean calls.", y=-0.28)
    save(fig, "race_backtest_brier.png")


def main() -> None:
    apply()
    calibration()
    gate_summary()


if __name__ == "__main__":
    main()

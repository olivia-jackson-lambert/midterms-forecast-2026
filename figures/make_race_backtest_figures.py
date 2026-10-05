"""Stage B race-backtest figures (PLAN §5 / §6 signature visuals).

Same pipeline as figures/make_figures.py: figstyle (Lora, Title Case, no in-figure
titles) + palette (green accent, charcoal baseline; slate/rust only for party).

Charts mirror the turnout backtest pair:
  - race_backtest_brier.png      — dumbbell, model vs soft presidential lean (like backtest_error)
  - race_backtest_calibration.png — reliability diagram, 2018 charcoal / 2022 green
  - race_backtest_scatter.png     — predicted vs actual Dem share, two years (like backtest_2022_scatter)

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
sys.path.insert(0, str(HERE))
SITE = Path(os.environ.get("PORTFOLIO_SITE",
                           Path.home() / "Documents/portfolio/olivia-jackson-lambert.github.io"))
# Prefer the live portfolio figstyle when present; otherwise the vendored copy in figures/.
if (SITE / "scripts" / "figstyle.py").exists():
    sys.path.insert(0, str(SITE / "scripts"))

from figstyle import DIM, INK, LIGHT, MUTED, apply, note, tidy  # noqa: E402
from palette import ACCENT, BASE, CONTEXT, DENSITY  # noqa: E402

from forecast.ingest import OUT as DATA  # noqa: E402

OUT = HERE / "out"


def save(fig, name: str) -> Path:
    OUT.mkdir(exist_ok=True)
    path = OUT / name
    fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.06, facecolor="white")
    plt.close(fig)
    print("  wrote", name)
    return path


def _scores() -> pd.DataFrame | None:
    path = DATA / "backtest_races.csv"
    if not path.exists():
        print("skip race figures: run `python -m forecast.backtest races` first")
        return None
    return pd.read_csv(path)


def brier_dumbbell() -> None:
    """Model Brier against soft presidential-lean Brier — same grammar as backtest_error."""
    d = _scores()
    if d is None:
        return
    d = d.sort_values("year")
    # One row per year; reverse so 2018 sits on top (reading order like turnout backtest).
    rows = [(f"{int(r.year)}, {int(r.n_races)} Races", float(r.baseline_brier), float(r.brier))
            for _, r in d.iterrows()][::-1]

    fig, ax = plt.subplots(figsize=(7.6, 2.8))
    for i, (lab, base, model) in enumerate(rows):
        ax.plot([model, base], [i, i], color=LIGHT, lw=2.5, zorder=1, solid_capstyle="round")
        ax.plot(base, i, "o", ms=8.5, color=MUTED, zorder=2)
        ax.plot(model, i, "o", ms=8.5, color=ACCENT, zorder=3)
        ax.text(base + 0.006, i, f"{base:.3f}", va="center", fontsize=9, color=MUTED)
        ax.text(model - 0.006, i, f"{model:.3f}", va="center", ha="right", fontsize=9, color=ACCENT)

    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    xmin = min(min(r[1], r[2]) for r in rows) - 0.04
    xmax = max(max(r[1], r[2]) for r in rows) + 0.05
    ax.set_xlim(max(0, xmin), xmax)
    ax.set_ylim(-0.65, len(rows) - 0.35)
    ax.set_xlabel("Brier Score (Lower Is Better)")
    tidy(ax, grid_axis="x")
    handles = [
        plt.Line2D([], [], marker="o", ls="", ms=8.5, color=ACCENT, label="Model"),
        plt.Line2D([], [], marker="o", ls="", ms=8.5, color=MUTED, label="Presidential Lean"),
    ]
    ax.legend(handles=handles, loc="lower right", bbox_to_anchor=(1, 1.02), ncol=2)
    note(ax, "Soft presidential lean is the probabilistic baseline. "
             "Each backtest uses only data available on 1 October of that year.", y=-0.32)
    save(fig, "race_backtest_brier.png")


def calibration() -> None:
    """Reliability diagram for Stage B win probabilities."""
    path = DATA / "backtest_races_calibration.csv"
    if not path.exists():
        print("skip calibration: no backtest_races_calibration.csv")
        return
    cal = pd.read_csv(path)
    fig, ax = plt.subplots(figsize=(5.4, 5.2))
    ax.plot([0, 1], [0, 1], color=LIGHT, lw=1.3, ls=(0, (3, 2)), label="Perfect", zorder=1)

    for year, g in cal.groupby("year"):
        g = g.sort_values("mean_p")
        color = BASE if int(year) == 2018 else ACCENT
        ax.plot(g["mean_p"], g["win_rate"], "-", color=color, lw=1.6, zorder=2)
        sizes = 28 + 3.2 * g["n"].to_numpy()
        ax.scatter(g["mean_p"], g["win_rate"], s=sizes, color=color, zorder=3,
                   label=str(int(year)), edgecolors="white", linewidths=0.6)
        for _, r in g.iterrows():
            # Nudge count labels off the marker; flip below when near the top.
            dy = -0.045 if r["win_rate"] > 0.88 else 0.035
            ax.text(r["mean_p"], r["win_rate"] + dy, str(int(r["n"])),
                    ha="center", va="center", fontsize=7.5, color=MUTED, zorder=4)

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Predicted Democratic Win Probability")
    ax.set_ylabel("Actual Democratic Win Rate")
    ax.set_aspect("equal")
    tidy(ax, grid_axis="both")
    ax.legend(loc="upper left")
    note(ax, "Bins of Senate and governor races. Marker size and labels show the count in each bin.\n"
             "Charcoal is 2018; green is 2022.", y=-0.18)
    save(fig, "race_backtest_calibration.png")


def share_scatter() -> None:
    """Predicted median Dem share against actual — Stage B sibling to backtest_2022_scatter."""
    frames = []
    for year in (2018, 2022):
        path = DATA / f"backtest_races_{year}.parquet"
        if path.exists():
            f = pd.read_parquet(path).dropna(subset=["median", "actual_share"])
            f["year"] = year
            frames.append(f)
    if not frames:
        print("skip share_scatter: no backtest_races_*.parquet")
        return
    d = pd.concat(frames, ignore_index=True)

    fig, axes = plt.subplots(1, 2, figsize=(8.6, 4.4), sharex=True, sharey=True)
    for ax, year in zip(axes, (2018, 2022)):
        g = d[d["year"] == year]
        ax.hexbin(g["actual_share"] * 100, g["median"] * 100, gridsize=28,
                  extent=(0, 100, 0, 100), mincnt=1, cmap=DENSITY, bins="log",
                  linewidths=0)
        ax.plot([0, 100], [0, 100], color=ACCENT, lw=1.2, ls=(0, (3, 2)))
        mae = (g["median"] - g["actual_share"]).abs().mean() * 100
        scores = _scores()
        cov = float("nan")
        if scores is not None and year in set(scores["year"].astype(int)):
            cov = float(scores.loc[scores["year"] == year, "coverage80"].iloc[0])
        label = f"{year}\nError {mae:.1f} Points"
        if np.isfinite(cov):
            label += f"\n80% Coverage {cov * 100:.0f}%"
        ax.text(0.04, 0.96, label, transform=ax.transAxes, va="top", fontsize=9.5, color=INK)
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.set_aspect("equal")
        tidy(ax, grid_axis="both")
        ax.set_xlabel("Actual Democratic Share (%)")
    axes[0].set_ylabel("Predicted Democratic Share (%)")
    note(axes[1], "Each hexagon counts Senate and governor races; darker is more. "
                  "Dashed line: perfect prediction.", y=-0.2)
    save(fig, "race_backtest_scatter.png")


def main() -> list[Path]:
    apply()
    written: list[Path] = []
    for fn in (brier_dumbbell, calibration, share_scatter):
        before = set(OUT.glob("race_backtest_*.png")) if OUT.exists() else set()
        fn()
        after = set(OUT.glob("race_backtest_*.png")) if OUT.exists() else set()
        written.extend(sorted(after - before, key=lambda p: p.name))
    # Always return the three canonical paths if present.
    paths = [OUT / n for n in (
        "race_backtest_brier.png",
        "race_backtest_calibration.png",
        "race_backtest_scatter.png",
    ) if (OUT / n).exists()]
    return paths


if __name__ == "__main__":
    main()

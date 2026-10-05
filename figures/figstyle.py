"""Portfolio figure style for Turnout First charts.

Mirrors the site's scripts/figstyle.py when PORTFOLIO_SITE is unavailable: Lora (or
Georgia), Title Case axis labels, no titles inside figures, quiet captions via `note`.
Neutrals recovered from published charts / docs/visual-brand.md.

When the portfolio repo is on disk, make_figures.py prefers that copy; this module
keeps cloud agents and CI on the same look.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib import font_manager

# Neutrals (figstyle names)
INK = "#161616"
DIM = "#4c525a"
MUTED = "#8c8c90"
LIGHT = "#bebec0"
PAPER = "#ffffff"

# Party (site slate / rust) — only for DEM / REP series
SLATE = "#7189a6"
RUST = "#c85040"

# Site categorical used by palette.PURPLE
CATEGORICAL = [
    SLATE, RUST, "#5b7a8c", "#c4a35a", "#6a8f7b", "#b07d62",
    "#8c6d8f", "#7a8b6f", "#9a7b6d", "#6d7f8c",
]

_GRID = "#e6e6e8"


def _pick_serif() -> str:
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Lora", "Georgia", "Times New Roman", "DejaVu Serif"):
        if name in available:
            return name
    return "serif"


def _title_case(s: str) -> str:
    """Title Case small axis labels; leave short tokens and % alone."""
    if not s or not isinstance(s, str):
        return s
    small = {"of", "a", "an", "the", "and", "or", "vs", "to", "in", "on", "for", "by"}
    parts = s.split()
    out = []
    for i, w in enumerate(parts):
        if w.isupper() and len(w) <= 4:
            out.append(w)
            continue
        low = w.lower()
        if i > 0 and low in small:
            out.append(low)
        else:
            out.append(w[:1].upper() + w[1:] if w else w)
    return " ".join(out)


def apply() -> None:
    serif = _pick_serif()
    plt.rcParams.update({
        "font.family": serif,
        "font.size": 10.5,
        "axes.labelsize": 11,
        "axes.titlesize": 11,
        "axes.labelcolor": INK,
        "axes.edgecolor": INK,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": DIM,
        "ytick.color": DIM,
        "xtick.labelsize": 9.5,
        "ytick.labelsize": 9.5,
        "legend.fontsize": 9.5,
        "legend.frameon": False,
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
        "text.color": INK,
        "grid.color": _GRID,
        "grid.linewidth": 0.8,
        "axes.titlepad": 8,
    })


def tidy(ax, grid_axis: str = "y") -> None:
    """Light grid, dim ticks, Title Case axis labels — Claude's standard cleanup."""
    if grid_axis:
        ax.grid(axis=grid_axis, color=_GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(colors=DIM, length=3, width=0.7)
    xlabel = ax.get_xlabel()
    ylabel = ax.get_ylabel()
    if xlabel:
        ax.set_xlabel(_title_case(xlabel))
    if ylabel:
        ax.set_ylabel(_title_case(ylabel))
    for spine in ax.spines.values():
        spine.set_color(INK)
        spine.set_linewidth(0.8)


def note(ax, text: str, x: float = 0.0, y: float = -0.18, ha: str = "left",
         fontsize: float = 8.5) -> None:
    """Caption under the axes (write-up voice). Multi-line ok."""
    ax.text(x, y, text, transform=ax.transAxes, fontsize=fontsize, color=MUTED,
            va="top", ha=ha, linespacing=1.35)

"""Colours for the Turnout First 2026 figures, layered on the site's figstyle.

Rule: red and blue are only for partisan things. In an election project they read as
Republican and Democratic whatever they show, so:

- Party: DEM and REP, the site's slate and rust.
- Turnout and everything non-partisan: charcoal and grey for context, GREEN as the accent,
  and GREEN (higher) against PURPLE (lower) for change. Green against purple, not red,
  because red reads as partisan and green against red is the hardest pair for colour-blind
  readers.
- The homepage card keeps the site's usual slate and rust (figures/make_thumbnail.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

from matplotlib.colors import LinearSegmentedColormap

# Allow `from palette import …` whether figstyle comes from PORTFOLIO_SITE or figures/.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from figstyle import CATEGORICAL, DIM, INK, LIGHT, MUTED, PAPER, RUST, SLATE  # noqa: E402, F401

# Partisan blue: a deeper, still muted slate than the site's SLATE, which read too light
# against white in the maps and bars. Rust stays the site's.
DEM, REP = "#4d6a8f", RUST

GREEN, GREEN_DEEP, GREEN_LIGHT = "#4e7d5b", "#2e5539", "#b5cfbb"
PURPLE, PURPLE_DEEP, PURPLE_LIGHT = CATEGORICAL[6], "#4f3a5c", "#d3c5d5"      # "#8c6d8f"

ACCENT = GREEN            # the one thing to notice in a turnout figure
BASE = DIM                # default series
CONTEXT = MUTED           # baselines, earlier years

CHANGE = LinearSegmentedColormap.from_list("turnout_change", [PURPLE_DEEP, PURPLE, PAPER, GREEN, GREEN_DEEP])
DENSITY = LinearSegmentedColormap.from_list("turnout_density", ["#ffffff", "#d9dbe0", MUTED, DIM, INK])

"""Shared matplotlib style for every case-study figure, so charts match the site.

Usage (from any figure script):

    import sys; sys.path.insert(0, "<repo>/scripts")
    from figstyle import apply, tidy, INK, SLATE, RUST, DIM, GRID, MUTED
    apply()
    ...
    tidy(ax)                                   # hairline axes, no top/right spines
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")

Rules the style encodes:
- Lora for all text, including small labels (MONO is kept as a name for older
  scripts but now also points at Lora, so every chart uses one face).
- No chart titles inside the figure; the caption in the article carries the title.
- White background, hairline light grid on the value axis only, no top/right spines.
- Colours come only from this file. Slate is the default series colour, rust is
  for the one thing the reader should notice, dim/grey for context. Heatmaps use
  CMAP, signed values CMAP_DIVERGING, many-category charts CATEGORICAL, and box or
  band fills SLATE_TINT / RUST_TINT / PAPER. No other hex codes or named cmaps.
- Every piece of text in a figure (axis labels, legends, panel titles, colour-bar
  labels, annotations) is in Title Case; use title_case() when in doubt.
- Figures are read in a 620px column on a vertically scrolling page. Prefer layouts
  no wider than about 2:1: stack panels vertically, run pipelines top to bottom.
"""
from pathlib import Path

import matplotlib as mpl
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

FONT_DIR = Path(__file__).resolve().parent / "fonts"

INK = "#16181b"      # text and primary lines
SLATE = "#7189a6"    # default series
RUST = "#c9503f"     # emphasis: the one thing to look at
DIM = "#3a3f48"      # secondary dark series
MUTED = "#8a8f98"    # notes, annotations, context series
GRID = "#e6e6ec"     # gridlines
LIGHT = "#c9ced6"    # light context fills
SEQ = [SLATE, RUST, DIM, "#a9b8ca", "#e3a397", MUTED]  # order for multi-series plots

# Soft fills for boxes, bands and table rows (diagrams, highlighted regions)
SLATE_TINT = "#e6ecf3"   # light slate fill
RUST_TINT = "#f6e1dc"    # light rust fill (errors, the thing to notice)
PAPER = "#f4f5f7"        # neutral panel / box fill

# Ten muted, distinguishable colours for charts with many categories (digit classes,
# particle types). Slate and rust stay first so emphasis matches every other chart.
CATEGORICAL = [SLATE, RUST, DIM, "#a9b8ca", "#e3a397", "#8a9a7b",
               "#8c6d8f", "#b08b5a", "#5f8a8b", "#c9ced6"]

# Heatmaps (confusion matrices, grids): white to slate to near-ink, one ramp everywhere.
from matplotlib.colors import LinearSegmentedColormap as _LSC
CMAP = _LSC.from_list("site_slate", ["#ffffff", "#c9d4e2", SLATE, "#3d5470", "#1f2a38"])
# Signed values (residuals, differences): slate for negative, rust for positive.
CMAP_DIVERGING = _LSC.from_list("site_div", ["#3d5470", SLATE, "#f4f5f7", "#e3a397", RUST])

_SMALL = {"a", "an", "the", "and", "but", "or", "nor", "for", "so", "yet", "as", "at",
          "by", "in", "of", "off", "on", "per", "to", "up", "via", "vs", "vs.", "with", "from", "into"}


def title_case(text: str) -> str:
    """Title Case for axis labels, legends, panel titles and annotations.

    Small words stay lowercase unless first, last or opening a bracket; single-letter
    symbols (p, n, x), words that already contain a capital or digit (ResNet, BGE-M3,
    F1, R², pT) and units with a slash such as (GeV/c) are kept as written, so
    "(log scale)" becomes "(Log Scale)".
    """
    words = text.split(" ")
    out = []
    for i, w in enumerate(words):
        core = w.strip("()[]{}\"'")
        lead = w[: len(w) - len(w.lstrip("([{\"'"))]
        if not core or (len(core) == 1 and core != "a") \
                or any(c.isupper() for c in core[1:]) or any(c.isdigit() for c in core) \
                or w.startswith("$") or "/" in core:
            out.append(w)
        elif core.lower() in _SMALL and 0 < i < len(words) - 1 and not lead:
            out.append(w.lower())
        else:
            body = w[len(lead):]
            out.append(lead + "-".join(p[:1].upper() + p[1:] for p in body.split("-")))
    return " ".join(out)

SANS = "Lora"
MONO = "Lora"


def apply():
    for f in FONT_DIR.glob("*.ttf"):
        fm.fontManager.addfont(str(f))
    for cm in (CMAP, CMAP_DIVERGING):
        try:
            mpl.colormaps.register(cm)
        except ValueError:
            pass
    plt.rcParams.update({
        "figure.dpi": 120,
        "savefig.dpi": 200,
        "savefig.facecolor": "white",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "font.family": SANS,
        "font.size": 10.5,
        "text.color": INK,
        "axes.labelcolor": INK,
        "axes.labelsize": 10.5,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "axes.edgecolor": "#b9bec6",
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "axes.prop_cycle": mpl.cycler(color=SEQ),
        "xtick.color": "#5a606a",
        "ytick.color": "#5a606a",
        "xtick.labelsize": 9.5,
        "ytick.labelsize": 9.5,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "legend.frameon": False,
        "legend.fontsize": 9.5,
        "lines.linewidth": 2,
        "image.cmap": "site_slate",
        # maths labels ($p_T$, $\\Delta$) in Lora too, not matplotlib's default face
        "mathtext.fontset": "custom",
        "mathtext.rm": SANS,
        "mathtext.it": SANS,
        "mathtext.bf": SANS + ":semibold",
    })


def tidy(ax, grid_axis="y"):
    """Hairline finish for one axes."""
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(True, axis=grid_axis, color=GRID, linewidth=0.8)
    ax.tick_params(length=0)
    return ax


def note(ax, text, x=1.0, y=-0.16, ha="right"):
    """Small grey source or method note under an axes."""
    ax.text(x, y, text, transform=ax.transAxes, ha=ha, va="top", fontsize=8.5, color=MUTED)

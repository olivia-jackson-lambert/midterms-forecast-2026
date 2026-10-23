"""Homepage card thumbnail for Turnout First 2026.

A regular grid of flat dots in the shape of the lower 48 (Albers, EPSG:5070), in the same
dot language as the site's other thumbnails: most dots a dim grey, with slate where the
forecast turnout change (2026 median against 2022) is lowest and rust where it is highest,
the strongest a size larger. The card keeps the site's normal thumbnail palette, not the green
and purple of the article's own figures. No glow, text, legend or axes.

    TURNOUT_DATA=/path/to/data.nosync python figures/make_thumbnail.py

Writes figures/out/thumb/turnout-2026.png (1500 x 1000) and a WebP made the way the site's
optimize-images.py makes its web copies (quality 90, method 6, at most 1600 px wide).

To add it to the site's scripts/make_thumbnails.py later, paste a function like this and
register it alongside the others (it only needs the PNG this script writes):

    # 9. Turnout First 2026: every county unit, sized by voters, coloured by turnout change.
    def turnout():
        src = Path("/Users/oliviajackson/Documents/portfolio/projects/midterms-2026/figures/out/thumb/turnout-2026.png")
        Image.open(src).convert("RGB").save(OUT / "turnout-2026.png")
        print("  wrote turnout-2026")
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from forecast import ingest  # noqa: E402

OUTDIR = HERE / "out" / "thumb"
GROUND, LIGHT, RUST, SLATE = "#0f1115", "#ece9e4", "#c9503f", "#7189a6"
DIM, SOFT_SLATE, SOFT_RUST = "#2e323a", "#7189a6", "#c07a64"
STEP = 68_000                                       # grid spacing in metres
W, H, DPI = 15, 10, 100


def load() -> gpd.GeoDataFrame:
    """One point per grid cell inside a county unit, carrying that unit's turnout change."""
    geo = gpd.read_file(f"zip://{ingest.RAW}/geo/cb_2023_us_county_20m.zip")
    geo["unit_fips"] = ingest.to_unit(geo["GEOID"])
    units = geo.dissolve(by="unit_fips").to_crs(5070).reset_index()[["unit_fips", "geometry"]]

    t26 = pd.read_parquet(ingest.OUT / "turnout_2026.parquet")[["unit_fips", "state_po", "median"]]
    t22 = pd.read_parquet(ingest.OUT / "county_midterm_turnout.parquet")
    t22 = t22[t22["year"] == 2022][["unit_fips", "turnout"]].rename(columns={"turnout": "t22"})
    t = t26.merge(t22, on="unit_fips")
    t = t[~t["state_po"].isin(["AK", "HI"])]
    t["delta"] = t["median"] - t["t22"]
    units = units.merge(t[["unit_fips", "delta"]], on="unit_fips")

    x0, y0, x1, y1 = units.total_bounds
    xs, ys = np.meshgrid(np.arange(x0, x1, STEP), np.arange(y0, y1, STEP))
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(xs.ravel(), ys.ravel()), crs=5070)
    g = gpd.sjoin(pts, units, predicate="within")
    g = g[~g.index.duplicated()]            # a point on a shared border joins twice
    return g.assign(x=g.geometry.x, y=g.geometry.y)


def draw(d: pd.DataFrame):
    fig = plt.figure(figsize=(W, H), dpi=DPI, facecolor=GROUND)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(GROUND); ax.axis("off")
    q = d["delta"].quantile([.03, .12, .88, .97]).to_numpy()
    col = np.full(len(d), DIM, dtype=object); size = np.full(len(d), 44.0)
    v = d["delta"].to_numpy()
    col[v <= q[1]] = SOFT_SLATE; col[v >= q[2]] = SOFT_RUST
    col[v <= q[0]] = SLATE; col[v >= q[3]] = RUST
    size[(v <= q[0]) | (v >= q[3])] = 105
    order = np.argsort(size)                       # accents drawn on top
    ax.scatter(d.x.to_numpy()[order], d.y.to_numpy()[order], s=size[order], c=list(col[order]), linewidths=0)
    cx, cy = (d.x.min() + d.x.max()) / 2, (d.y.min() + d.y.max()) / 2
    hw = (d.x.max() - d.x.min()) / 2 * 1.12
    hh = hw / 1.5
    ax.set_xlim(cx - hw, cx + hw); ax.set_ylim(cy - hh, cy + hh)
    return fig


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    d = load()
    print(len(d), "grid dots")
    fig = draw(d)
    png = OUTDIR / "turnout-2026.png"
    fig.savefig(png, dpi=DPI, facecolor=GROUND)
    plt.close(fig)
    im = Image.open(png).convert("RGB")
    im.save(OUTDIR / "turnout-2026.webp", "WEBP", quality=90, method=6)
    print("wrote", png)


if __name__ == "__main__":
    main()

"""Homepage card thumbnail for Turnout First 2026.

Every county unit is a glowing point at its true location (Albers, EPSG:5070), sized by
citizen voting-age population (square-root scaling) and coloured by the forecast change
in turnout, 2026 median against 2022 actual. The card keeps the site's normal palette
(slate for lower turnout, rust for higher), not the green and purple of the article's own
figures. No text, no legend, no axes. Alaska and Hawaii are left out to keep the frame clean.

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
GLOW = LinearSegmentedColormap.from_list("glow", [GROUND, "#1f2a38", SLATE, "#b8765f", RUST, "#f4e6d6"])
W, H, DPI = 15, 10, 100


def load() -> pd.DataFrame:
    geo = gpd.read_file(f"zip://{ingest.RAW}/geo/cb_2023_us_county_20m.zip")
    geo["unit_fips"] = ingest.to_unit(geo["GEOID"])
    units = geo.dissolve(by="unit_fips").to_crs(5070)
    cent = units.geometry.representative_point()   # inside the unit, even for odd shapes
    units = units.assign(x=cent.x, y=cent.y).reset_index()[["unit_fips", "x", "y"]]

    t26 = pd.read_parquet(ingest.OUT / "turnout_2026.parquet")[["unit_fips", "state_po", "cvap", "median"]]
    t22 = pd.read_parquet(ingest.OUT / "county_midterm_turnout.parquet")
    t22 = t22[t22["year"] == 2022][["unit_fips", "turnout"]].rename(columns={"turnout": "t22"})
    d = t26.merge(t22, on="unit_fips").merge(units, on="unit_fips")
    d["delta"] = d["median"] - d["t22"]
    return d[~d["state_po"].isin(["AK", "HI"])].dropna(subset=["delta", "x", "y"])


def draw(d: pd.DataFrame):
    fig = plt.figure(figsize=(W, H), dpi=DPI, facecolor=GROUND)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(GROUND); ax.axis("off")
    d = d.sort_values("cvap")                      # small places first, big ones on top
    lo, hi = np.percentile(d["delta"], [3, 97])
    c = np.clip((d["delta"] - lo) / (hi - lo), 0, 1)
    c = .30 + .52 * c                             # keep the low end visible on the dark ground
    col = GLOW(c.to_numpy())
    size = np.sqrt(d["cvap"].to_numpy())
    s = 1.2 + size * .08                          # marker area in points squared
    for mult, alpha in ((16, .05), (6, .11)):     # soft halo under the bright core
        g = col.copy(); g[:, 3] = alpha
        ax.scatter(d.x, d.y, s=s * mult, c=g, linewidths=0, zorder=1)
    core = col.copy(); core[:, 3] = .9
    ax.scatter(d.x, d.y, s=s, c=core, linewidths=0, zorder=2)
    cx, cy = (d.x.min() + d.x.max()) / 2, (d.y.min() + d.y.max()) / 2
    hw = (d.x.max() - d.x.min()) / 2 * 1.07
    hh = hw / 1.5
    ax.set_xlim(cx - hw, cx + hw); ax.set_ylim(cy - hh, cy + hh)
    return fig


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    d = load()
    print(len(d), "units;", d["delta"].describe().round(3).to_dict())
    fig = draw(d)
    png = OUTDIR / "turnout-2026.png"
    fig.savefig(png, dpi=DPI, facecolor=GROUND)
    plt.close(fig)
    im = Image.open(png).convert("RGB")
    im.save(OUTDIR / "turnout-2026.webp", "WEBP", quality=90, method=6)
    print("wrote", png)


if __name__ == "__main__":
    main()

"""Figures for the Turnout First 2026 write-up.

Styling comes from the portfolio site's scripts/figstyle.py (Lora, slate and rust, Title
Case, no titles inside figures; the captions in the write-up carry the titles). Set
PORTFOLIO_SITE if the site repo is not at ~/Documents/portfolio/olivia-jackson-lambert.github.io.

Colours come from figures/palette.py: red and blue only for party; turnout figures use
charcoal and grey, with green as the accent and green (higher) against purple (lower).

    python figures/make_figures.py          # writes figures/out/*.png
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, to_rgb
from shapely import affinity

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
SITE = Path(os.environ.get("PORTFOLIO_SITE", Path.home() / "Documents/portfolio/olivia-jackson-lambert.github.io"))
sys.path.insert(0, str(SITE / "scripts"))
from figstyle import DIM, INK, LIGHT, MUTED, PAPER, apply, note, tidy  # noqa: E402
from palette import ACCENT, BASE, CHANGE, CONTEXT, DENSITY, GREEN, PURPLE  # noqa: E402

from forecast import national  # noqa: E402
from forecast.features import SENATE  # noqa: E402
from forecast.ingest import OUT as DATA, RAW  # noqa: E402

OUT = HERE / "out"


def save(fig, name):
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", pad_inches=0.06, facecolor="white")
    plt.close(fig)
    print("  wrote", name)


def pct(x, signed=False):
    return f"{x * 100:+.0f}" if signed else f"{x * 100:.0f}%"


# --------------------------------------------------------------------------- data
def turnout_2026() -> pd.DataFrame:
    t = pd.read_parquet(DATA / "turnout_2026.parquet")
    mid = pd.read_parquet(DATA / "county_midterm_turnout.parquet")
    t22 = mid[mid["year"] == 2022].set_index("unit_fips")["turnout"]
    t["t2022"] = t["unit_fips"].map(t22)
    t["change"] = t["median"] - t["t2022"]
    t["width_county"] = t["hi80_county"] - t["lo80_county"]
    return t


def county_units() -> gpd.GeoDataFrame:
    """County shapes dissolved to the model's county units, in Albers with Alaska and Hawaii
    moved below the lower 48."""
    from forecast.ingest import to_unit
    g = gpd.read_file(RAW / "geo" / "cb_2023_us_county_20m.zip")
    g = g[g["STATEFP"].astype(int) <= 56]
    g["unit_fips"] = to_unit(g["GEOID"])
    g = g.dissolve("unit_fips", as_index=False)[["unit_fips", "geometry"]].to_crs(5070)
    return _inset(g, "unit_fips")


def states() -> gpd.GeoDataFrame:
    s = gpd.read_file(RAW / "geo" / "cb_2023_us_state_20m.zip")
    s = s[s["STATEFP"].astype(int) <= 56].to_crs(5070)
    s["unit_fips"] = s["STATEFP"] + "000"
    return _inset(s, "unit_fips")


def _inset(g: gpd.GeoDataFrame, key: str) -> gpd.GeoDataFrame:
    g = g.copy()
    ak, hi = g[key].str.startswith("02"), g[key].str.startswith("15")
    g.loc[ak, "geometry"] = g.loc[ak, "geometry"].apply(
        lambda x: affinity.translate(affinity.scale(x, 0.33, 0.33, origin=(0, 0)), -1.25e6, -1.35e6))
    if hi.any():
        minx, miny = g.loc[hi, "geometry"].total_bounds[:2]
        g.loc[hi, "geometry"] = g.loc[hi, "geometry"].apply(
            lambda x: affinity.translate(x, -1.05e6 - minx, 0.30e6 - miny))
    return g


# --------------------------------------------------------------------------- figures
def hero_map(t: pd.DataFrame) -> None:
    """Forecast change in turnout, 2026 against 2022. Colour shows direction and size; it fades
    towards grey where the county's own 80% interval is wide (value-suppressing palette)."""
    g = county_units().merge(t, on="unit_fips", how="left")
    lim = 0.10
    norm = np.clip(g["change"] / lim, -1, 1) / 2 + 0.5
    # Certainty: 1 for the tightest intervals, 0 for the widest (5th to 95th percentile).
    w = g["width_county"]
    cert = 1 - np.clip((w - w.quantile(0.05)) / (w.quantile(0.95) - w.quantile(0.05)), 0, 1)
    base = np.array([CHANGE(v)[:3] for v in norm.fillna(0.5)])
    paper = np.array(to_rgb(PAPER))
    colours = paper + (base - paper) * (0.35 + 0.65 * cert.fillna(0).to_numpy()[:, None])

    fig, ax = plt.subplots(figsize=(9.6, 6.0))
    g.plot(ax=ax, color=colours, linewidth=0)
    states().boundary.plot(ax=ax, color="white", linewidth=0.6)
    ax.set_axis_off()
    ax.set_aspect("equal")

    # Legend: change across, certainty down, as a small grid.
    lg = fig.add_axes([0.74, 0.20, 0.19, 0.11])
    xs = np.linspace(-1, 1, 7)
    for j, c in enumerate([1.0, 0.5, 0.0]):
        for i, x in enumerate(xs):
            rgb = paper + (np.array(CHANGE(x / 2 + 0.5)[:3]) - paper) * (0.35 + 0.65 * c)
            lg.add_patch(plt.Rectangle((i, -j), 1, 1, color=rgb, linewidth=0))
    lg.set_xlim(0, 7); lg.set_ylim(-2, 1)
    lg.set_xticks([0.5, 3.5, 6.5], [f"−{lim * 100:.0f}", "0", f"+{lim * 100:.0f}"])
    lg.set_yticks([0.5, -1.5], ["More Certain", "Less Certain"])
    lg.tick_params(length=0, labelsize=8.5, colors=DIM)
    for s in lg.spines.values():
        s.set_visible(False)
    lg.grid(False)
    lg.set_xlabel("Change in Turnout (Points)", fontsize=8.5, color=DIM, labelpad=3)
    note(ax, "Forecast median, 2026 against 2022, as a share of citizens of voting age. Colour fades where a\n"
             "county's own 80% interval is wide. Alaska and Connecticut are modelled as single units.",
         x=0.0, y=0.0, ha="left")
    save(fig, "hero_turnout_change_map.png")


def national_history() -> None:
    t = national.vep_turnout()
    lo, mid, hi = national.interval(2026, 0.8)
    lo50, _, hi50 = national.interval(2026, 0.5)
    years = np.array(t.index)
    midterm = years % 4 == 2
    fig, ax = plt.subplots(figsize=(8.4, 4.4))
    ax.plot(years[~midterm], t[~midterm] * 100, color=LIGHT, lw=1.6, marker="o", ms=4, label="Presidential Years")
    ax.plot(years[midterm], t[midterm] * 100, color=BASE, lw=2, marker="o", ms=5, label="Midterms")
    ax.plot([2022, 2026], [t[2022] * 100, mid * 100], color=ACCENT, lw=1.4, ls=(0, (2, 2)))
    ax.fill_between([2025.6, 2026.4], lo * 100, hi * 100, color=ACCENT, alpha=0.18, lw=0)
    ax.fill_between([2025.6, 2026.4], lo50 * 100, hi50 * 100, color=ACCENT, alpha=0.30, lw=0)
    ax.plot([2025.6, 2026.4], [mid * 100] * 2, color=ACCENT, lw=2.2)
    ax.annotate(f"2026 Forecast\n{mid * 100:.1f}% (80%: {lo * 100:.0f}–{hi * 100:.0f}%)", (2026.5, mid * 100),
                xytext=(6, 0), textcoords="offset points", va="center", fontsize=9.5, color=ACCENT)
    ax.annotate("2018: 50.0%", (2018, t[2018] * 100), xytext=(-8, 8), textcoords="offset points",
                ha="right", fontsize=9, color=DIM)
    ax.set_xlim(1979, 2033)
    ax.set_ylim(30, 70)
    ax.set_ylabel("Turnout (% of Eligible Citizens)")
    ax.legend(loc="upper left", ncol=2)
    tidy(ax)
    note(ax, "Voting-eligible population turnout. Source: UF Election Lab (Michael McDonald). "
             "Forecast: 2024 turnout less the average midterm drop since 1986.", y=-0.1)
    save(fig, "national_turnout_history.png")


def state_change(t: pd.DataFrame) -> None:
    """Every state's forecast against its 2022 turnout. Thin bar: full 80% interval; thick bar: the
    state's own 80% interval with national turnout held at its median. Senate race added in green."""
    s = pd.read_parquet(DATA / "turnout_2026_states.parquet").set_index("state_po")
    t22 = (t["t2022"] * t["cvap"]).groupby(t["state_po"]).sum() / t.groupby("state_po")["cvap"].sum()
    s["t2022"] = t22
    new_senate = set(SENATE[2026].split()) - set(SENATE[2022].split())
    s = s.sort_values("median")
    fig, ax = plt.subplots(figsize=(6.2, 11.0))
    for i, (st, r) in enumerate(s.iterrows()):
        c = ACCENT if st in new_senate else BASE
        ax.plot([r["lo80"] * 100, r["hi80"] * 100], [i, i], color=c, alpha=0.22, lw=1.4, solid_capstyle="round")
        ax.plot([r["lo80_state"] * 100, r["hi80_state"] * 100], [i, i], color=c, alpha=0.35, lw=5.5,
                solid_capstyle="round")
        ax.plot(r["t2022"] * 100, i, "o", ms=4.5, mfc="white", mec=CONTEXT, mew=1.2, zorder=4)
        ax.plot(r["median"] * 100, i, "o", ms=5.5, color=c, zorder=5)
    ax.set_yticks(np.arange(len(s)), s.index)
    ax.set_xlabel("Turnout (% of Citizens of Voting Age)")
    ax.tick_params(axis="y", labelsize=8.5)
    tidy(ax, grid_axis="x")
    ax.set_ylim(-1, len(s))
    handles = [plt.Line2D([], [], marker="o", ls="", ms=5.5, color=BASE, label="2026 Forecast"),
               plt.Line2D([], [], marker="o", ls="", ms=5.5, color=ACCENT, label="2026, Senate Race Added"),
               plt.Line2D([], [], marker="o", ls="", ms=4.5, mfc="white", mec=CONTEXT, label="2022 Actual")]
    ax.legend(handles=handles, loc="lower right")
    note(ax, "Thick bars: the state's own 80% interval, national turnout held at its median.\n"
             "Thin bars: 80% interval including national uncertainty.", y=-0.055)
    save(fig, "state_turnout_2026.png")


def backtest_errors() -> None:
    b = pd.read_csv(DATA / "backtest_turnout.csv").query("out_party")
    rows = []
    for _, r in b.iterrows():
        rows.append((f"{int(r.year)}, Every County", r.baseline_mae_pts, r.mae_pts))
        rows.append((f"{int(r.year)}, Weighted by Population", r.baseline_weighted_mae_pts, r.weighted_mae_pts))
    fig, ax = plt.subplots(figsize=(7.6, 3.2))
    for i, (lab, base, model) in enumerate(rows[::-1]):
        ax.plot([model, base], [i, i], color=LIGHT, lw=2.5, zorder=1)
        ax.plot(base, i, "o", ms=8, color=MUTED, zorder=2)
        ax.plot(model, i, "o", ms=8, color=ACCENT, zorder=3)
        ax.text(base + 0.25, i, f"{base:.1f}", va="center", fontsize=9, color=MUTED)
        ax.text(model - 0.25, i, f"{model:.1f}", va="center", ha="right", fontsize=9, color=ACCENT)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows[::-1]])
    ax.set_xlim(0, 15.5)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlabel("Mean Absolute Error, County Turnout (Points)")
    tidy(ax, grid_axis="x")
    handles = [plt.Line2D([], [], marker="o", ls="", ms=8, color=ACCENT, label="Model"),
               plt.Line2D([], [], marker="o", ls="", ms=8, color=MUTED, label="Same as Last Midterm")]
    ax.legend(handles=handles, loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2)
    note(ax, "Each backtest uses only data available on 1 October of that year.", y=-0.3)
    save(fig, "backtest_error.png")


def backtest_scatter() -> None:
    """2022 counties: predicted against actual, for the baseline and the model."""
    from forecast.features import frame
    d = pd.read_parquet(DATA / "backtest_turnout_2022.parquet")
    d = d[frame(2022)["train_ok"].to_numpy()]
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 4.4), sharex=True, sharey=True)
    for ax, col, lab in zip(axes, ["last_midterm", "median"], ["Same as Last Midterm", "Model"]):
        ax.hexbin(d["actual"] * 100, d[col] * 100, gridsize=48, extent=(10, 90, 10, 90), mincnt=1,
                  cmap=DENSITY, bins="log", linewidths=0)
        ax.plot([10, 90], [10, 90], color=ACCENT, lw=1.2, ls=(0, (3, 2)))
        mae = (d[col] - d["actual"]).abs().mean() * 100
        ax.text(0.04, 0.95, f"{lab}\nError {mae:.1f} Points", transform=ax.transAxes, va="top", fontsize=9.5, color=INK)
        ax.set_xlim(10, 90); ax.set_ylim(10, 90)
        ax.set_aspect("equal")
        tidy(ax, grid_axis="both")
        ax.set_xlabel("Actual 2022 Turnout (%)")
    axes[0].set_ylabel("Predicted 2022 Turnout (%)")
    note(axes[1], "Each hexagon counts counties; darker is more. Dashed line: perfect prediction.", y=-0.2)
    save(fig, "backtest_2022_scatter.png")


def drivers() -> None:
    """Each term as points of turnout for a typical difference between counties (one standard
    deviation in the 2026 data; for the Senate term, a race joining the ballot)."""
    from forecast.features import DEMOGRAPHICS, frame
    p = pd.read_csv(DATA / "turnout_2026_parameters.csv", index_col=0)
    f = frame(2026)
    sd = {"lam": f["pres_minus_anchor"].std(), "rho": f["anchor"].std(), "phi": f["out_party_lean"].std(),
          "gamma[0]": 1.0, "gamma[1]": f["d_close"].std(), **{f"beta[{i}]": 1.0 for i in range(len(DEMOGRAPHICS))}}
    labels = {"lam": "Presidential Surge Carried Over", "rho": "Pull Back to Average",
              "phi": "Out-Party Lean", "gamma[0]": "Senate Race Added", "gamma[1]": "Top Race Closer",
              "beta[0]": "Degree Holders", "beta[1]": "Aged 18–29", "beta[2]": "Aged 65 and Over",
              "beta[3]": "Hispanic", "beta[4]": "Black", "beta[5]": "Population Density", "beta[6]": "Median Income"}
    keys = [k for k in labels if k in p.index]
    lo, hi = p.columns[2], p.columns[3]
    scale = 0.25 * 100                       # logit to points near 50% turnout
    e = pd.DataFrame({k: (p.loc[k, ["mean", lo, hi]].astype(float) * sd[k] * scale).values for k in keys},
                     index=["mean", "lo", "hi"]).T
    e = e.reindex(e["mean"].abs().sort_values().index)
    fig, ax = plt.subplots(figsize=(7.4, 4.8))
    for i, (k, r) in enumerate(e.iterrows()):
        c = GREEN if r["lo"] > 0 else PURPLE if r["hi"] < 0 else CONTEXT   # grey: interval crosses zero
        ax.plot([r["lo"], r["hi"]], [i, i], color=c, lw=2.5, alpha=0.45, solid_capstyle="round")
        ax.plot(r["mean"], i, "o", color=c, ms=6)
        ax.text(max(r["hi"], r["mean"]) + 0.08, i, f"{r['mean']:+.1f}", va="center", fontsize=8.5, color=c)
    ax.axvline(0, color=INK, lw=0.8)
    ax.set_yticks(np.arange(len(e)), [labels[k] for k in e.index])
    ax.set_xlabel("Effect on Turnout Change (Points) for a Typical Difference")
    tidy(ax, grid_axis="x")
    note(ax, "Posterior means and 89% intervals; green raises turnout, purple lowers it, grey is unclear. Fitted on 2014–2018 and\n"
             "2018–2022. A typical difference is one standard deviation across counties; for the Senate term, a race\n"
             "joining the ballot.", y=-0.13)
    save(fig, "turnout_drivers.png")


def main() -> None:
    apply()
    t = turnout_2026()
    hero_map(t)
    national_history()
    state_change(t)
    backtest_errors()
    backtest_scatter()
    drivers()


if __name__ == "__main__":
    main()

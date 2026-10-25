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
from matplotlib.ticker import MaxNLocator
from shapely import affinity

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))
SITE = Path(os.environ.get("PORTFOLIO_SITE", Path.home() / "Documents/portfolio/olivia-jackson-lambert.github.io"))
# Live portfolio figstyle wins when present; otherwise figures/figstyle.py.
if (SITE / "scripts" / "figstyle.py").exists():
    sys.path.insert(0, str(SITE / "scripts"))
from figstyle import DIM, INK, LIGHT, MUTED, PAPER, apply, note, tidy  # noqa: E402
from palette import ACCENT, BASE, CHANGE, CONTEXT, DEM, DENSITY, GREEN, PURPLE, REP  # noqa: E402

from forecast import national  # noqa: E402
from forecast.features import SENATE  # noqa: E402
from forecast.ingest import OUT as DATA, RAW  # noqa: E402

OUT = HERE / "out"
GRID_LINE = "#e6e6ec"


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
              "beta[0]": "Share With a Degree", "beta[1]": "Share Aged 18–29", "beta[2]": "Share Aged 65 and Over",
              "beta[3]": "Share Hispanic or Latino", "beta[4]": "Share Black, Non-Hispanic",
              "beta[5]": "Population Density", "beta[6]": "Median Household Income"}
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
             "2018–2022. A typical difference is one standard deviation across counties; for the Senate term, a race joining\n"
             "the ballot. Shares are of each county's residents (ACS categories): they describe places, not individual voters.",
         y=-0.13)
    save(fig, "turnout_drivers.png")


# --------------------------------------------------------------------------- races (Stage B)
def race_backtest() -> None:
    """The model with polls and with fundamentals only, against the two references, 2018 and 2022:
    Brier score and vote-share error. In backtest_races.csv "model" is with polls, "no polls" is
    the fundamentals alone."""
    b = pd.read_csv(DATA / "backtest_races.csv")
    polls = b.query("variant == 'model'").set_index("year")
    fund = b.query("variant == 'no polls'").set_index("year")
    fig, axes = plt.subplots(2, 1, figsize=(7.6, 5.0), sharey=True)
    specs = [("Brier Score (Lower Is Better)", ("brier", "uniform_swing_brier", "lean_brier"), "{:.3f}"),
             ("Vote-Share Error, Points (Lower Is Better)", ("mae_pts", "uniform_swing_mae_pts", "lean_mae_pts"), "{:.1f}")]
    names = ["Model With Polls", "Fundamentals Only", "Lean Plus Uniform Swing", "Presidential Lean"]
    colours = [ACCENT, BASE, CONTEXT, LIGHT]
    for ax, (label, cols, fmt) in zip(axes, specs):
        for i, year in enumerate([2022, 2018]):
            vals = [polls.loc[year, cols[0]], fund.loc[year, cols[0]]] + [polls.loc[year, c] for c in cols[1:]]
            ax.plot([min(vals), max(vals)], [i, i], color=GRID_LINE, lw=2.5, zorder=1)
            for v, c, n in zip(vals, colours, names):
                ax.plot(v, i, "o", ms=8, color=c, zorder=3 if c in (ACCENT, BASE) else 2, label=n if i == 0 else None)
            ax.text(vals[0], i + 0.28, fmt.format(vals[0]), ha="center", fontsize=8.5, color=ACCENT)
            ax.text(vals[1], i + 0.28, fmt.format(vals[1]), ha="center", fontsize=8.5, color=BASE)
        ax.set_yticks([0, 1], ["2022", "2018"])
        ax.set_ylim(-0.6, 1.7)
        ax.set_xlim(0, None)
        ax.set_xlabel(label)
        tidy(ax, grid_axis="x")
    axes[0].legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2)
    fig.tight_layout()
    note(axes[1], "Each year fitted only on earlier midterms (2018 on priors alone). 68 and 70 races.", y=-0.38)
    save(fig, "race_backtest.png")


def race_calibration() -> None:
    c = pd.read_csv(DATA / "backtest_races_calibration.csv")
    if "variant" in c:
        c = c[c["variant"] == "model"]          # the model with polls
    g = c.groupby("bin", sort=False).apply(lambda d: pd.Series({
        "races": d["races"].sum(), "mean_p": np.average(d["mean_p"], weights=d["races"]),
        "win_rate": np.average(d["win_rate"], weights=d["races"])}), include_groups=False).reset_index()
    fig, ax = plt.subplots(figsize=(5.4, 5.0))
    ax.plot([0, 1], [0, 1], color=CONTEXT, lw=1.1, ls=(0, (3, 2)))
    ax.scatter(g["mean_p"], g["win_rate"], s=g["races"] * 9, color=ACCENT, alpha=0.85, zorder=3, linewidths=0)
    for _, r in g.iterrows():
        ax.annotate(f"{int(r['races'])} Races", (r["mean_p"], r["win_rate"]), xytext=(np.sqrt(r["races"] * 9 / np.pi) + 4, -3),
                    textcoords="offset points", fontsize=8.5, color=DIM)
    ax.set_xlim(-0.03, 1.03); ax.set_ylim(-0.03, 1.03); ax.set_aspect("equal")
    ax.set_xlabel("Forecast Chance Democrats Win")
    ax.set_ylabel("Share of Races It Won")
    tidy(ax, grid_axis="both")
    note(ax, "Model with polls; 2018 and 2022 backtests pooled, in five bins. Dashed line: perfect calibration.", y=-0.16)
    save(fig, "race_calibration.png")


def race_probabilities() -> None:
    """Every 2026 Senate and governor race by the chance Democrats win (partisan colours)."""
    v = pd.read_parquet(DATA / "vote_share_2026.parquet")
    v["label"] = v["state_po"] + np.where(v["special"], " (Special)", "")
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 9.6), sharex=True)
    for ax, office, title in zip(axes, ["SEN", "GOV"], ["Senate", "Governor"]):
        d = v[v["office"] == office].sort_values("p_dem_win").reset_index(drop=True)
        for i, r in d.iterrows():
            c = DEM if r["p_dem_win"] >= 0.5 else REP
            hollow = r["d_side"] != "democrat"
            ax.plot([0.5, r["p_dem_win"]], [i, i], color=c, alpha=0.25, lw=2)
            ax.plot(r["p_dem_win"], i, "o", ms=6, color=c, mfc="white" if hollow else c, mew=1.4)
        ax.axvline(0.5, color=INK, lw=0.8)
        ax.set_yticks(range(len(d)), d["label"])
        ax.set_ylim(-0.8, len(d) - 0.2)
        ax.tick_params(axis="y", labelsize=8.5)
        ax.set_xlim(-0.03, 1.03)
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1], ["Safe R", "75% R", "Even", "75% D", "Safe D"])
        ax.set_title(title, fontsize=10.5, color=INK, loc="left")
        tidy(ax, grid_axis="x")
    axes[0].set_xlabel("Chance of Winning")
    axes[1].set_xlabel("Chance of Winning")
    fig.tight_layout()
    note(axes[1], "Hollow points: an independent runs in place of a Democrat (NE, ID, SD Senate).", y=-0.07)
    save(fig, "race_probabilities_2026.png")


def senate_seats() -> None:
    s = pd.read_csv(DATA / "senate_seats_2026.csv").groupby("dem_seats")["probability"].sum()
    s = s[(s.index >= 42) & (s.index <= 58)]
    fig, ax = plt.subplots(figsize=(7.6, 3.8))
    ax.bar(s.index, s.values * 100, color=[DEM if k >= 51 else REP for k in s.index], width=0.78)
    ax.axvline(50.5, color=INK, lw=0.8, ls=(0, (2, 2)))
    p51 = s[s.index >= 51].sum()
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, steps=[1, 2, 5, 10]))
    ax.text(s.index.max() + 0.4, ax.get_ylim()[1] * 0.92, f"Democrats Win 51+: {p51 * 100:.0f}%", ha="right",
            fontsize=9.5, color=DEM)
    ax.set_xticks(range(int(s.index.min()), int(s.index.max()) + 1, 2))
    ax.set_xlabel("Democratic-Caucus Senate Seats After the Election")
    ax.set_ylabel("Chance (%)")
    tidy(ax)
    note(ax, "20,000 simulations. Democrats need 51 seats for control (the Vice President breaks ties). "
             "Seats won by independents are not counted.", y=-0.2)
    save(fig, "senate_seats_2026.png")



def governor_seats() -> None:
    s = pd.read_csv(DATA / "governor_seats_2026.csv").groupby("dem_seats")["probability"].sum()
    s = s[(s.index >= 16) & (s.index <= 36)]
    fig, ax = plt.subplots(figsize=(7.6, 3.8))
    ax.bar(s.index, s.values * 100, width=0.78,
           color=[DEM if k >= 26 else REP if k <= 24 else MUTED for k in s.index])
    ax.axvline(25.5, color=INK, lw=0.8, ls=(0, (2, 2)))
    p26 = s[s.index >= 26].sum()
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, steps=[1, 2, 5, 10]))
    ax.text(s.index.max() + 0.4, ax.get_ylim()[1] * 0.92, f"Democrats Hold 26+: {p26 * 100:.0f}%", ha="right",
            fontsize=9.5, color=DEM)
    ax.set_xticks(range(int(s.index.min()), int(s.index.max()) + 1, 2))
    ax.set_xlabel("Democratic Governors After the Election")
    ax.set_ylabel("Chance (%)")
    tidy(ax)
    note(ax, "20,000 simulations. 36 races; 6 Democratic and 8 Republican governors are not up in 2026. "
             "25 is an even split (grey).", y=-0.2)
    save(fig, "governor_seats_2026.png")

def fundamentals_only_2026() -> pd.DataFrame:
    """The 2026 race forecast without the poll layer, computed in memory (nothing is saved).

    vote_model.run fits on 2018 and 2022 and simulates with a fixed seed, so with USE_POLLS off
    this reproduces the fundamentals draws the published run blends polls into. The fit takes
    a few seconds; only summary parameters are saved to disk, so it is refitted here."""
    from forecast import vote_model
    keep = vote_model.USE_POLLS
    vote_model.USE_POLLS = False
    try:
        out, _ = vote_model.run(2026, [2018, 2022])
    finally:
        vote_model.USE_POLLS = keep
    return out


def polls_shift(fund: pd.DataFrame) -> None:
    """Competitive races: Democratic-side win probability without and with polls (partisan colours:
    each end coloured by the side it favours)."""
    v = pd.read_parquet(DATA / "vote_share_2026.parquet")
    d = v.merge(fund[["race_id", "p_dem_win"]], on="race_id", suffixes=("", "_fund"))
    lo, hi = d[["p_dem_win", "p_dem_win_fund"]].min(axis=1), d[["p_dem_win", "p_dem_win_fund"]].max(axis=1)
    d = d[(hi > 0.05) & (lo < 0.95)].copy()
    d["label"] = d["state_po"] + np.where(d["special"], " (Special)", "")
    side = lambda p: DEM if p >= 0.5 else REP
    n = d["office"].value_counts()
    fig, axes = plt.subplots(2, 1, figsize=(7.4, 10.6), sharex=True,
                             gridspec_kw={"height_ratios": [n.get("SEN", 1), n.get("GOV", 1)]})
    for ax, office, title in zip(axes, ["SEN", "GOV"], ["Senate", "Governor"]):
        o = d[d["office"] == office].sort_values("p_dem_win").reset_index(drop=True)
        for i, r in o.iterrows():
            a, b = r["p_dem_win_fund"], r["p_dem_win"]
            ax.plot([a, b], [i, i], color=LIGHT, lw=2.2, zorder=1, solid_capstyle="round")
            ax.plot(a, i, "o", ms=6.5, mfc="white", mec=side(a), mew=1.5, zorder=2)
            ax.plot(b, i, "o", ms=7, color=side(b), zorder=3)
        ax.axvline(0.5, color=INK, lw=0.8)
        ax.set_yticks(range(len(o)), o["label"])
        ax.set_ylim(-0.7, len(o) - 0.3)
        ax.tick_params(axis="y", labelsize=8.5)
        ax.set_xlim(-0.02, 1.02)
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1], ["Safe R", "75% R", "Even", "75% D", "Safe D"])
        ax.set_title(title, fontsize=10.5, color=INK, loc="left")
        tidy(ax, grid_axis="x")
    axes[1].set_xlabel("Chance of Winning")
    handles = [plt.Line2D([], [], marker="o", ls="", ms=6.5, mfc="white", mec=DIM, mew=1.5, label="Fundamentals Only"),
               plt.Line2D([], [], marker="o", ls="", ms=7, color=DIM, label="With Polls")]
    axes[0].legend(handles=handles, loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2)
    note(axes[1], "Races where either version gives Democrats between 5% and 95%. Blue: favours Democrats;\n"
                  "red: favours the Republican. NE and SD Senate: an independent runs in place of a Democrat.",
         y=-0.1)
    fig.tight_layout()
    save(fig, "polls_shift_2026.png")


def house_seats() -> None:
    """Distribution of Democratic House seats (partisan colours), from the joint seat distribution."""
    h = pd.read_csv(DATA / "house_seats_2026.csv").groupby("dem_seats")["probability"].sum()
    cum = h.cumsum()
    lo = int(h.index[cum.searchsorted(0.002)])
    hi = int(h.index[cum.searchsorted(0.998)])
    s = h.reindex(range(lo, hi + 1), fill_value=0.0)
    fig, ax = plt.subplots(figsize=(7.6, 3.8))
    ax.bar(s.index, s.values * 100, color=[DEM if k >= 218 else REP for k in s.index], width=0.85, linewidth=0)
    ax.axvline(217.5, color=INK, lw=0.8, ls=(0, (2, 2)))
    p218 = h[h.index >= 218].sum()
    med = int(h.index[cum.searchsorted(0.5)])
    top = ax.get_ylim()[1]
    ax.text(hi, top * 0.92, f"Democrats Win 218+: {p218 * 100:.0f}%", ha="right", fontsize=9.5, color=DEM)
    ax.text(hi, top * 0.83, f"Median: {med} Seats (80%: {int(h.index[cum.searchsorted(0.1)])}–"
                            f"{int(h.index[cum.searchsorted(0.9)])})", ha="right", fontsize=9, color=DIM)
    step = 10
    ax.set_xticks(range((lo // step + 1) * step, hi + 1, step))
    ax.set_xlim(lo - 1, hi + 1)
    ax.set_xlabel("Democratic House Seats After the Election")
    ax.set_ylabel("Chance (%)")
    tidy(ax)
    note(ax, "20,000 simulations. 218 seats are a majority. Seats won by independents are not counted.\n"
             "The 0.2% of simulations at each extreme are off the chart.", y=-0.2)
    save(fig, "house_seats_2026.png")


def main() -> None:
    apply()
    t = turnout_2026()
    hero_map(t)
    national_history()
    state_change(t)
    backtest_errors()
    backtest_scatter()
    drivers()
    race_backtest()
    race_calibration()
    race_probabilities()
    senate_seats()
    governor_seats()
    polls_shift(fundamentals_only_2026())
    house_seats()


if __name__ == "__main__":
    main()

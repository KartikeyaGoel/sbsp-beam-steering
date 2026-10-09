"""Make paper figures from results/results.json. Usage: python src/figures.py"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from geometry import STATIONS, elevation_deg
from model import MIN_ELEV

ROOT = Path(__file__).resolve().parent.parent
FIG = ROOT / "results" / "figs"
R = json.loads((ROOT / "results" / "results.json").read_text())
COLORS = {"CAISO": "#d95f02", "ERCOT": "#7570b3", "MISO": "#1b9e77",
          "NYISO": "#e7298a", "ISONE": "#66a61e", "OMIE": "#e6ab02"}
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "figure.dpi": 150, "savefig.bbox": "tight"})


def fig_visibility():
    lons = np.arange(-140, 21)
    fig, ax = plt.subplots(figsize=(6, 3))
    for m, st in STATIONS.iterrows():
        ax.plot(lons, elevation_deg(st.lat, st.lon, lons), color=COLORS[m], label=m)
    ax.axhline(MIN_ELEV, color="k", lw=0.8, ls="--")
    for lon in (-100, -40):
        ax.axvline(lon, color="grey", lw=0.6)
    ax.set(ylim=(0, 60), xlabel="Satellite longitude (°E)", ylabel="Elevation at rectenna (°)",
           title="Which rectennas a GEO satellite can see")
    ax.legend(ncol=4, fontsize=7, frameon=False)
    fig.savefig(FIG / "fig1_visibility.png")


def fig_premium():
    fig, ax = plt.subplots(figsize=(6, 3))
    for key, run in R["runs"].items():
        rows = run["best_by_n"]
        ls = "-" if key.startswith("2025") else ":"
        ax.plot([r["n"] for r in rows], [r["premium_pct"] for r in rows], marker="o", ls=ls, label=key)
    ax.set(xlabel="Rectennas the beam can switch between", ylabel="Revenue premium vs best single site (%)",
           title="Value of steering (no price impact)")
    ax.legend(fontsize=7, frameon=False)
    fig.savefig(FIG / "fig2_premium_by_n.png")


def fig_benchmarks():
    keys = [k for k, v in R["runs"].items() if "benchmarks" in v]
    opts = [("second_rectenna", "Second rectenna (beam)"), ("hvdc", "HVDC line (wire)"),
            ("battery_2gw_8gwh", "2 GW / 8 GWh battery")]
    fig, ax = plt.subplots(figsize=(6.5, 3))
    w = 0.8 / len(opts)
    for i, (o, label) in enumerate(opts):
        vals = [R["runs"][k]["benchmarks"][o]["added_rev_musd"] / R["runs"][k]["benchmarks"][o]["annual_cost_musd"]
                for k in keys]
        ax.bar(np.arange(len(keys)) + i * w, vals, w, label=label)
    ax.axhline(1, color="k", lw=0.8, ls="--")
    ax.set_xticks(np.arange(len(keys)) + w, [k.replace(" (", "\n(") for k in keys], fontsize=7)
    ax.set(ylabel="Added revenue ÷ annualized cost", title="Beam vs wire vs battery (above 1 = pays for itself)")
    ax.legend(fontsize=7, frameon=False)
    fig.savefig(FIG / "fig3_benchmarks.png")


def fig_hourly_share():
    run = R["runs"]["2025 US (100°W)"]
    share = run["concentration"]["share_by_utc_hour"]
    fig, ax = plt.subplots(figsize=(6, 3))
    hours = np.arange(24)
    ax.stackplot(hours, *[share[m] for m in share], labels=list(share), colors=[COLORS[m] for m in share])
    ax.set(xlim=(0, 23), ylim=(0, 1), xlabel="Hour of day (UTC)", ylabel="Share of delivered energy",
           title="Where the beam points, 2025, satellite at 100°W")
    ax.legend(fontsize=7, frameon=False, ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.18))
    fig.savefig(FIG / "fig4_beam_share_by_hour.png")


def fig_price_impact():
    fig, ax = plt.subplots(figsize=(6, 3))
    for key, run in R["runs"].items():
        if "price_impact" not in run:
            continue
        ks = sorted(run["price_impact"], key=float)
        ax.plot([float(k) for k in ks], [run["price_impact"][k]["premium_pct_all"] for k in ks], marker="o",
                ls="-" if key.startswith("2025") else ":", label=key)
    ax.set(xlabel="Price impact, $/MWh per GW in a 50 GW market", ylabel="Premium, all visible sites (%)",
           title="Price impact makes steering more valuable")
    ax.legend(fontsize=7, frameon=False)
    fig.savefig(FIG / "fig5_price_impact.png")


def fig_breakeven():
    keys = [k for k, v in R["runs"].items() if "breakeven_ground_cost_busd" in v]
    fig, ax = plt.subplots(figsize=(6, 2.6))
    ax.barh(keys, [R["runs"][k]["breakeven_ground_cost_busd"] for k in keys], color="#4c72b0")
    ax.axvline(R["assumptions"]["ground_station_cost_usd"] / 1e9, color="crimson", ls="--",
               label="NASA OTPS 2024 estimate")
    ax.set(xlabel="Break-even cost of the 2nd rectenna ($B, 2 GW reference site)",
           title="How cheap must a rectenna be for steering to pay?")
    ax.legend(fontsize=7, frameon=False)
    fig.savefig(FIG / "fig6_breakeven.png")


def fig_slot_sweep():
    s = R["slot_sweep"]
    fig, ax = plt.subplots(figsize=(6, 2.8))
    ax.plot([r["sat_lon"] for r in s], [r["premium_pct"] for r in s], marker=".")
    ax.set(xlabel="Satellite longitude (°E)", ylabel="Premium, all visible sites (%)",
           title="Steering premium by orbital slot (2025)")
    fig.savefig(FIG / "fig7_slot_sweep.png")


if __name__ == "__main__":
    FIG.mkdir(parents=True, exist_ok=True)
    for f in (fig_visibility, fig_premium, fig_benchmarks, fig_hourly_share, fig_price_impact,
              fig_breakeven, fig_slot_sweep):
        f()
    print("figures in", FIG)

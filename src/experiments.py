"""Run every experiment and write results/results.json plus figures.

Usage: python src/experiments.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from geometry import STATIONS, eclipse_fraction
from model import RAW, load_prices, station_params, dispatch, revenue, run, MIN_ELEV
from benchmarks import (hvdc, battery_value, battery_annual_cost, crf, WACC)

OUT = Path(__file__).resolve().parent.parent / "results"
P_GW = 2.0
YEARS = [2025, 2024]
SLOTS = {"US (100°W)": -100.0, "Atlantic (40°W)": -40.0}
# NASA OTPS (2024) RD1: $3.119B ground segment for one 6 km, 2 GW rectenna site.
GROUND_COST = 3.119e9
GROUND_REF_AREA = 1.5   # area factor we treat as NASA's reference site (~45 deg elevation)
LIFE = 30


def available(year):
    return [m for m in STATIONS.index if (RAW / f"{m}_{year}.csv").exists()]


def station_cost(area, c0=GROUND_COST):
    return c0 * area / GROUND_REF_AREA


def subset_table(res):
    """Best subset for each station count, with premium over the best single station."""
    best = res.loc[res.groupby("n").revenue.idxmax()].copy()
    base = best.revenue.iloc[0]
    best["premium_pct"] = 100 * (best.revenue / base - 1)
    best["marginal_rev_musd"] = best.revenue.diff().fillna(0) / 1e6
    return best


def concentration(prices, avail, params, combo, single):
    """Share of the steering gain earned in the top x% of hours."""
    k = np.zeros(len(combo))
    pr = prices[list(combo)].to_numpy()
    q = dispatch(pr, avail, params.loc[list(combo)].eta.to_numpy(), k, P_GW)
    hourly_steer = (q * np.nan_to_num(pr)).sum(axis=1) * 1000
    ps = prices[[single]].to_numpy()
    q1 = dispatch(ps, avail, params.loc[[single]].eta.to_numpy(), np.zeros(1), P_GW)
    hourly_fixed = (q1 * np.nan_to_num(ps)).sum(axis=1) * 1000
    gain = np.sort(hourly_steer - hourly_fixed)[::-1]
    total = gain.sum()
    out = {f"top_{p}pct": float(gain[: int(len(gain) * p / 100)].sum() / total) for p in (1, 5, 10, 25)}
    out["hours_with_gain"] = int((gain > 1).sum())
    # Which station gets the beam, by UTC hour of day (share of delivered energy).
    df = pd.DataFrame(q, index=prices.index, columns=list(combo))
    by_hour = df.groupby(df.index.hour).sum()
    out["share_by_utc_hour"] = (by_hour.div(by_hour.sum(axis=1), axis=0)).round(3).to_dict(orient="list")
    return out, df


def main():
    OUT.mkdir(exist_ok=True)
    results = {"assumptions": {
        "satellite_gw": P_GW, "min_elevation_deg": MIN_ELEV, "wacc": WACC, "life_years": LIFE,
        "ground_station_cost_usd": GROUND_COST, "ground_ref_area": GROUND_REF_AREA,
        "battery_cost_per_yr_1gw4h": battery_annual_cost()}, "runs": {}}
    hourly_export = {}

    for year in YEARS:
        markets = available(year)
        prices = load_prices(year, markets)
        results.setdefault("price_stats", {})[year] = prices.describe().round(2).to_dict()
        for slot_name, sat_lon in SLOTS.items():
            res, params, avail = run(prices, sat_lon, P_GW)
            best = subset_table(res)
            single = best.stations.iloc[0][0]
            ann = crf(WACC, LIFE)
            # Marginal station economics: added revenue vs annualized cost of the added rectenna.
            rows = []
            prev = None
            for _, r in best.iterrows():
                added = [s for s in r.stations if prev is None or s not in prev]
                cost = sum(station_cost(params.area[s]) for s in added) * ann if prev is not None else 0
                rows.append({"n": int(r.n), "stations": list(r.stations), "revenue_musd": r.revenue / 1e6,
                             "premium_pct": r.premium_pct, "marginal_rev_musd": r.marginal_rev_musd,
                             "marginal_cost_musd": cost / 1e6, "share": r.share})
                prev = r.stations
            run_key = f"{year} {slot_name}"
            entry = {"markets": markets, "params": params.round(3).to_dict(orient="index"),
                     "avail_mean": float(avail.mean()), "best_by_n": rows,
                     "single_station": {s: float(res[res.stations == (s,)].revenue.iloc[0] / 1e6)
                                        for s in params.index[params.elev >= MIN_ELEV]}}
            if len(best) > 1:
                two = best.stations.iloc[1]
                other = [s for s in two if s != single][0]
                gain_2nd = (best.revenue.iloc[1] - best.revenue.iloc[0])
                # Break-even cost of the second rectenna (zenith-scaled, same convention as GROUND_COST).
                entry["breakeven_ground_cost_busd"] = gain_2nd / ann / (params.area[other] / GROUND_REF_AREA) / 1e9
                # Price impact sensitivity on the full visible set.
                entry["price_impact"] = {}
                for k0 in (0, 1, 2, 5, 10):
                    rk, _, _ = run(prices, sat_lon, P_GW, k0=k0)
                    bk = subset_table(rk)
                    entry["price_impact"][k0] = {"premium_pct_all": float(bk.premium_pct.iloc[-1]),
                                                 "premium_pct_2": float(bk.premium_pct.iloc[1]),
                                                 "single_revenue_musd": float(bk.revenue.iloc[0] / 1e6)}
                # Benchmarks for the best pair: HVDC line vs second rectenna vs battery.
                subsea = (STATIONS.lon[single] > -30) != (STATIONS.lon[other] > -30)
                hv_rev, hv_cost, km, loss = hvdc(prices, avail, params, single, other, P_GW, P_GW, subsea)
                fixed_rev = best.revenue.iloc[0]
                batt = battery_value(prices[single]) * P_GW  # 2 GW / 8 GWh, linear at zero price impact
                entry["benchmarks"] = {
                    "pair": [single, other],
                    "second_rectenna": {"added_rev_musd": gain_2nd / 1e6,
                                        "annual_cost_musd": station_cost(params.area[other]) * ann / 1e6},
                    "hvdc": {"added_rev_musd": (hv_rev - fixed_rev) / 1e6, "annual_cost_musd": hv_cost / 1e6,
                             "route_km": km, "loss": loss, "subsea": bool(subsea)},
                    "battery_2gw_8gwh": {"added_rev_musd": batt / 1e6,
                                         "annual_cost_musd": battery_annual_cost(P_GW) / 1e6},
                }
                full = best.stations.iloc[-1]
                conc, hourly = concentration(prices, avail, params, full, single)
                entry["concentration"] = conc
                if year == YEARS[0]:
                    hourly_export[slot_name] = {"stations": list(full),
                                                "gw": hourly.round(2).to_numpy().tolist(),
                                                "price": prices[list(full)].round(1).fillna(0).to_numpy().tolist()}
            results["runs"][run_key] = entry
            print(run_key, "->", [(r["stations"], round(r["premium_pct"], 1)) for r in rows], flush=True)

    # Orbital slot sweep: premium of steering across all visible stations vs best single.
    sweep = []
    prices = load_prices(YEARS[0], available(YEARS[0]))
    for lon in range(-130, 15, 5):
        res, params, _ = run(prices, float(lon), P_GW)
        if res.empty:
            continue
        best = subset_table(res)
        sweep.append({"sat_lon": lon, "visible": list(params.index[params.elev >= MIN_ELEV]),
                      "best_single": best.stations.iloc[0][0], "single_musd": best.revenue.iloc[0] / 1e6,
                      "all_musd": best.revenue.iloc[-1] / 1e6, "premium_pct": float(best.premium_pct.iloc[-1])})
    results["slot_sweep"] = sweep

    # Distance beyond which a second rectenna is cheaper than an HVDC line of the satellite's size.
    from benchmarks import (HVDC_CONVERTER_PAIR, HVDC_LINE_LAND, HVDC_LINE_SEA, ROUTE_FACTOR)
    rect_ann = station_cost(GROUND_REF_AREA) * crf(WACC, LIFE)
    hv_fixed, ann40 = P_GW * HVDC_CONVERTER_PAIR, crf(WACC, 40)
    results["crossover_km"] = {
        terrain: (rect_ann / ann40 - hv_fixed) / (P_GW * per_km * ROUTE_FACTOR)
        for terrain, per_km in (("land", HVDC_LINE_LAND), ("subsea", HVDC_LINE_SEA))}
    # Break-even ground cost at NASA's 3% discount rate instead of 7%.
    for entry in results["runs"].values():
        if "breakeven_ground_cost_busd" in entry:
            entry["breakeven_ground_cost_busd_3pct"] = entry["breakeven_ground_cost_busd"] * crf(WACC, LIFE) / crf(0.03, LIFE)
    results["hourly_index_start"] = str(prices.index[0])

    (OUT / "results.json").write_text(json.dumps(results, indent=1, default=float))
    (OUT / "hourly.json").write_text(json.dumps(hourly_export, separators=(",", ":")))
    print("wrote", OUT)


if __name__ == "__main__":
    main()

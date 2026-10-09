"""Hourly dispatch of one GEO solar satellite across rectennas in different markets."""
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from geometry import STATIONS, elevation_deg, area_factor, eclipse_fraction

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
EUR_USD = {2024: 1.082, 2025: 1.13}  # approximate annual average rates

MIN_ELEV = 15.0     # deg; below this a rectenna is impractically large
ATM_LOSS = 0.02     # one-way beam loss at zenith (clear-sky, ~5.8 GHz); scales with airmass


def load_prices(year, markets):
    cols = {}
    for m in markets:
        df = pd.read_csv(RAW / f"{m}_{year}.csv", parse_dates=["time_utc"]).set_index("time_utc")
        s = df["price"]
        if m == "OMIE":
            s = s * EUR_USD[year]
        cols[m] = s
    idx = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", tz="UTC", inclusive="left")
    prices = pd.DataFrame(cols).reindex(idx).interpolate(limit=3, limit_area="inside")
    return prices


def station_params(markets, sat_lon):
    st = STATIONS.loc[list(markets)]
    el = elevation_deg(st.lat, st.lon, sat_lon)
    return pd.DataFrame({
        "elev": el,
        "area": area_factor(st.lat, st.lon, sat_lon),
        "eta": 1 - ATM_LOSS / np.sin(np.radians(np.clip(el, 1, 90))),
        "load_gw": st.load_gw,
    })


def dispatch(prices, avail, eta, k, p_gw, cap_gw=None):
    """Split the satellite's output across stations each hour to maximize revenue.

    prices: (T, N) $/MWh (NaN = station unavailable that hour)
    avail:  (T,) fraction of the hour the satellite is sunlit
    eta:    (N,) beam delivery efficiency per station
    k:      (N,) price impact, $/MWh per GW delivered (price falls by k*q)
    Revenue at station i for delivered q is q*(p - k*q); marginal revenue p - 2kq.
    Water-fill marginal revenue at level lam >= 0 subject to sum(q/eta) <= p_gw*avail.
    Returns delivered GW (T, N).
    """
    p = np.nan_to_num(prices, nan=-1e9)
    cap = np.broadcast_to(np.inf if cap_gw is None else np.asarray(cap_gw, float), (p.shape[1],))
    k = np.maximum(k, 1e-6)
    budget = (p_gw * avail)[:, None]

    def q_at(lam):
        return np.clip((p - lam) / (2 * k), 0, cap)

    def sent(lam):
        return (q_at(lam) / eta).sum(axis=1, keepdims=True)

    lo = np.zeros_like(budget)
    hi = np.full_like(budget, max(p.max(), 1.0))
    # If even lam=0 doesn't use the budget, all positive-margin output is sold.
    free = sent(lo) <= budget
    for _ in range(60):
        mid = (lo + hi) / 2
        over = sent(mid) > budget
        lo = np.where(over, mid, lo)
        hi = np.where(over, hi, mid)
    lam = np.where(free, 0.0, hi)
    q = q_at(lam)
    # Scale down any residual overshoot from bisection tolerance.
    scale = np.minimum(1.0, budget / np.maximum((q / eta).sum(axis=1, keepdims=True), 1e-12))
    return q * scale


def revenue(prices, q, k):
    p = np.nan_to_num(prices, nan=0.0)
    return float((q * (p - k * q)).sum() * 1000)  # GW*h*$/MWh -> $ (1 GWh = 1000 MWh)


def run(prices, sat_lon, p_gw=2.0, k0=0.0, k_ref_load=50.0):
    """Revenue for every feasible subset of stations. k0 = $/MWh per GW in a 50 GW market."""
    params = station_params(prices.columns, sat_lon)
    visible = params.index[params.elev >= MIN_ELEV]
    avail = 1 - eclipse_fraction(prices.index, sat_lon)
    rows = []
    for n in range(1, len(visible) + 1):
        for combo in combinations(visible, n):
            sp = params.loc[list(combo)]
            k = (k0 * k_ref_load / sp.load_gw).to_numpy()
            pr = prices[list(combo)].to_numpy()
            q = dispatch(pr, avail, sp.eta.to_numpy(), k, p_gw)
            rows.append({
                "stations": combo, "n": n, "revenue": revenue(pr, q, k),
                "delivered_twh": q.sum() / 1000, "area_sum": sp.area.sum(),
                "share": dict(zip(combo, (q.sum(axis=0) / max(q.sum(), 1e-9)).round(3))),
            })
    return pd.DataFrame(rows), params, avail

"""Alternatives to beam steering: an HVDC line from the fixed site, or a battery at it."""
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import diags, hstack, csr_matrix

from geometry import STATIONS
from model import dispatch, revenue

# Cost assumptions (2025 USD); every one is swept in the sensitivity analysis.
WACC = 0.07
HVDC_CONVERTER_PAIR = 0.5e9     # $ per GW (both ends)
HVDC_LINE_LAND = 1.1e6          # $ per km per GW, overhead
HVDC_LINE_SEA = 3.3e6           # $ per km per GW, subsea
HVDC_LOSS_PER_1000KM = 0.03
HVDC_CONVERTER_LOSS = 0.015
ROUTE_FACTOR = 1.2
BATTERY_PER_KWH = 250           # $ per kWh, 4-hour utility system, all-in
BATTERY_RT_EFF = 0.87


def crf(rate, years):
    return rate * (1 + rate) ** years / ((1 + rate) ** years - 1)


def great_circle_km(a, b):
    la1, lo1, la2, lo2 = np.radians([STATIONS.lat[a], STATIONS.lon[a], STATIONS.lat[b], STATIONS.lon[b]])
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(h))


def hvdc(prices, avail, params, a, b, line_gw, p_gw=2.0, subsea=False):
    """Fixed rectenna at a, plus an HVDC line a->b. Returns (annual revenue $, annualized line cost $)."""
    km = great_circle_km(a, b) * ROUTE_FACTOR
    loss = HVDC_CONVERTER_LOSS + HVDC_LOSS_PER_1000KM * km / 1000
    eta = np.array([params.eta[a], params.eta[a] * (1 - loss)])
    pr = prices[[a, b]].to_numpy()
    q = dispatch(pr, avail, eta, np.zeros(2), p_gw, cap_gw=[np.inf, line_gw])
    capex = line_gw * (HVDC_CONVERTER_PAIR + km * (HVDC_LINE_SEA if subsea else HVDC_LINE_LAND))
    return revenue(pr, q, np.zeros(2)), capex * crf(WACC, 40), km, loss


def battery_value(price, power_gw=1.0, hours=4.0, eff=BATTERY_RT_EFF):
    """Perfect-foresight arbitrage revenue ($/yr) of a battery at one node; LP via HiGHS."""
    p = np.nan_to_num(np.asarray(price, float), nan=0.0)
    T = len(p)
    ec = ed = np.sqrt(eff)
    # Variables: charge c (T), discharge d (T), state of charge s (T). Minimize -revenue.
    cost = np.concatenate([p, -p, np.zeros(T)]) * 1000
    # s_t - s_{t-1} - ec*c_t + d_t/ed = 0, with s_{-1} = 0.
    S = diags([np.ones(T), -np.ones(T - 1)], [0, -1], shape=(T, T))
    A_eq = hstack([diags(-ec * np.ones(T)), diags(np.ones(T) / ed), S]).tocsr()
    bounds = [(0, power_gw)] * (2 * T) + [(0, power_gw * hours)] * T
    res = linprog(cost, A_eq=A_eq, b_eq=np.zeros(T), bounds=bounds, method="highs")
    assert res.status == 0, res.message
    return -res.fun


def battery_annual_cost(power_gw=1.0, hours=4.0, life=15):
    return power_gw * hours * 1e6 * BATTERY_PER_KWH * crf(WACC, life)

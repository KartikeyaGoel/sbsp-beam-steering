"""GEO-to-ground geometry: visibility, rectenna size penalty, and eclipse."""
import numpy as np
import pandas as pd

RE = 6378.137      # Earth equatorial radius, km
R_GEO = 42164.0    # GEO orbital radius, km
H_GEO = R_GEO - RE

# Candidate rectenna sites: plausible open land near each market's pricing hub.
# load_gw = approximate average system load, used to scale price impact.
STATIONS = pd.DataFrame(
    [
        ("CAISO", 35.0, -117.5, 25),   # Mojave, feeds SP15
        ("ERCOT", 31.5, -100.0, 50),   # West-central Texas
        ("MISO", 40.0, -89.0, 75),     # Central Illinois
        ("NYISO", 42.7, -74.5, 17),    # Upstate NY, feeds Capital zone
        ("ISONE", 42.5, -72.3, 13),    # Central Massachusetts
        ("OMIE", 39.0, -3.5, 28),      # La Mancha, Spain
    ],
    columns=["market", "lat", "lon", "load_gw"],
).set_index("market")


def central_angle(lat, lon, sat_lon):
    """Angle at Earth's center between ground site and sub-satellite point, radians."""
    return np.arccos(np.cos(np.radians(lat)) * np.cos(np.radians(lon - sat_lon)))


def elevation_deg(lat, lon, sat_lon):
    g = central_angle(lat, lon, sat_lon)
    return np.degrees(np.arctan2(np.cos(g) - RE / R_GEO, np.sin(g)))


def slant_km(lat, lon, sat_lon):
    g = central_angle(lat, lon, sat_lon)
    return np.sqrt(R_GEO**2 + RE**2 - 2 * R_GEO * RE * np.cos(g))


def area_factor(lat, lon, sat_lon):
    """Rectenna area relative to a sub-satellite site.

    Spot diameter scales with slant range (diffraction), and the footprint
    stretches by 1/sin(elevation) along the look direction.
    """
    el = np.radians(elevation_deg(lat, lon, sat_lon))
    return (slant_km(lat, lon, sat_lon) / H_GEO) ** 2 / np.sin(el)


def sun_vector(times):
    """Approximate unit vector to the Sun in Earth-fixed coordinates (~0.5 deg accuracy)."""
    t = pd.DatetimeIndex(times)
    doy = t.dayofyear.to_numpy() + (t.hour.to_numpy() + t.minute.to_numpy() / 60) / 24
    b = 2 * np.pi * (doy - 81) / 365
    decl = np.radians(23.44) * np.sin(b)
    eot_min = 9.87 * np.sin(2 * b) - 7.53 * np.cos(b) - 1.5 * np.sin(b)
    utc_h = t.hour.to_numpy() + t.minute.to_numpy() / 60
    sub_lon = np.radians(-15 * (utc_h - 12 + eot_min / 60))
    return np.stack([np.cos(decl) * np.cos(sub_lon), np.cos(decl) * np.sin(sub_lon), np.sin(decl)], axis=-1)


def eclipse_fraction(hours_utc, sat_lon):
    """Fraction of each UTC hour the GEO satellite spends in Earth's shadow (cylindrical model)."""
    hours_utc = pd.DatetimeIndex(hours_utc)
    minutes = hours_utc.repeat(60) + pd.to_timedelta(np.tile(np.arange(60), len(hours_utc)), unit="min")
    s = sun_vector(minutes)
    p = np.array([np.cos(np.radians(sat_lon)), np.sin(np.radians(sat_lon)), 0.0])
    dot = s @ p
    shadow = (dot < 0) & (R_GEO * np.sqrt(1 - dot**2) < RE)
    return shadow.reshape(-1, 60).mean(axis=1)

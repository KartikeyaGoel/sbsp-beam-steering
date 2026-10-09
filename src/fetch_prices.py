"""Download one year of hourly day-ahead prices at one hub per US market.

Usage: python src/fetch_prices.py MARKET YEAR
Writes data/raw/{MARKET}_{YEAR}.csv with columns: time_utc, price ($/MWh).
"""
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests
import gridstatus

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

# One representative pricing point per market.
HUBS = {
    "CAISO": "TH_SP15_GEN-APND",
    "ERCOT": "HB_HUBAVG",
    "MISO": "ILLINOIS.HUB",
    "NYISO": "CAPITL",
    "ISONE": ".H.INTERNAL_HUB",
    "OMIE": "ES",  # Spain zone, EUR/MWh
}


def monthly(fetch, year):
    """Call fetch(start, end) month by month so one failure doesn't lose the year."""
    parts = []
    for m in range(1, 13):
        start = pd.Timestamp(year=year, month=m, day=1)
        end = start + pd.offsets.MonthBegin(1)
        for attempt in range(3):
            try:
                parts.append(fetch(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
                break
            except Exception as e:
                print(f"  month {m} attempt {attempt + 1} failed: {e}", flush=True)
        else:  # fall back to single days, skipping days the source can't serve
            for day in pd.date_range(start, end - pd.Timedelta(days=1)):
                try:
                    parts.append(fetch(day.strftime("%Y-%m-%d"), (day + pd.Timedelta(days=1)).strftime("%Y-%m-%d")))
                except Exception as e:
                    print(f"  skipped {day:%Y-%m-%d}: {e}", flush=True)
        print(f"  month {m} done", flush=True)
    return pd.concat(parts)


def ercot(year):
    docs = requests.get(
        "https://www.ercot.com/misapp/servlets/IceDocListJsonWS?reportTypeId=13060", timeout=60
    ).json()["ListDocsByRptTypeRes"]["DocumentList"]
    doc = next(d["Document"] for d in docs if d["Document"]["FriendlyName"] == f"DAMLZHBSPP_{year}")
    blob = requests.get(
        f"https://www.ercot.com/misdownload/servlets/mirDownload?doclookupId={doc['DocID']}", timeout=300
    ).content
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        xlsx = z.read(z.namelist()[0])
    df = pd.concat(pd.read_excel(io.BytesIO(xlsx), sheet_name=None).values())
    df = df[df["Settlement Point"] == HUBS["ERCOT"]]
    # Hour Ending "01:00".."24:00" in Central prevailing time; DST repeated hour flagged.
    he = df["Hour Ending"].str.slice(0, 2).astype(int)
    local = pd.to_datetime(df["Delivery Date"]) + pd.to_timedelta(he - 1, unit="h")
    ambiguous = (df["Repeated Hour Flag"] == "N").to_numpy()
    t = local.dt.tz_localize("US/Central", ambiguous=ambiguous, nonexistent="shift_forward")
    return pd.DataFrame({"time_utc": t.dt.tz_convert("UTC"), "price": df["Settlement Point Price"].to_numpy()})


def omie(year):
    """Spain day-ahead price from OMIE daily files (hourly, or 15-min from Oct 2025)."""
    rows = []
    for day in pd.date_range(f"{year}-01-01", f"{year}-12-31"):
        url = ("https://www.omie.es/es/file-download?parents%5B0%5D=marginalpdbc"
               f"&filename=marginalpdbc_{day:%Y%m%d}.1")
        prices = []
        for attempt in range(3):
            try:
                lines = requests.get(url, timeout=60).text.strip().splitlines()[1:]
                prices = [float(l.split(";")[5]) for l in lines if l.count(";") >= 5 and l[0].isdigit()]
                if prices:
                    break
            except Exception as e:
                print(f"  {day:%Y-%m-%d} attempt {attempt + 1} failed: {e}", flush=True)
        if not prices:
            print(f"  skipped {day:%Y-%m-%d}: no data", flush=True)
            continue
        midnight = day.tz_localize("Europe/Madrid").tz_convert("UTC")
        hours = round((day + pd.Timedelta(days=1)).tz_localize("Europe/Madrid").tz_convert("UTC").value
                      - midnight.value) // 3_600_000_000_000
        per_hour = len(prices) // hours  # 1 for hourly periods, 4 for quarter-hours
        for h in range(hours):
            chunk = prices[h * per_hour:(h + 1) * per_hour]
            rows.append((midnight + pd.Timedelta(hours=h), sum(chunk) / len(chunk)))
    return pd.DataFrame(rows, columns=["time_utc", "price"])


def gs(iso, year, **kw):
    df = monthly(lambda s, e: iso.get_lmp(s, end=e, market="DAY_AHEAD_HOURLY", **kw), year)
    return df


def fetch(market, year):
    hub = HUBS[market]
    if market == "ERCOT":
        return ercot(year)
    if market == "OMIE":
        return omie(year)
    if market == "CAISO":
        df = gs(gridstatus.CAISO(), year, locations=[hub])
    elif market == "MISO":
        df = gs(gridstatus.MISO(), year)
    elif market == "NYISO":
        df = gs(gridstatus.NYISO(), year, location_type="zone", locations=[hub])
    elif market == "ISONE":
        df = gs(gridstatus.ISONE(), year, locations=[hub])
    df = df[df["Location"] == hub]
    return pd.DataFrame({"time_utc": df["Interval Start"].dt.tz_convert("UTC"), "price": df["LMP"].to_numpy()})


if __name__ == "__main__":
    market, year = sys.argv[1], int(sys.argv[2])
    RAW.mkdir(parents=True, exist_ok=True)
    out = fetch(market, year).drop_duplicates("time_utc").sort_values("time_utc")
    out.to_csv(RAW / f"{market}_{year}.csv", index=False)
    print(f"{market} {year}: {len(out)} hours, mean ${out.price.mean():.2f}, max ${out.price.max():.2f}")

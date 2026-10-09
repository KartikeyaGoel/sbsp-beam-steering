# Beam, Wire, or Battery?

What is a steerable space solar beam worth? This repo measures it with real hourly electricity prices.

A geostationary solar power satellite can repoint its microwave beam between ground rectennas in different
markets within milliseconds. Advocates call this "a giant interconnector in space", but no published
study has priced it with market data. This repo does.

**Paper:** [`paper/paper.pdf`](paper/paper.pdf). **Interactive explorer:** open `site/index.html` in a browser
(it is self-contained; the model runs client-side on the same price data).


1. **Geometry**: which rectenna sites each GEO slot can see, at what elevation, and how much larger a
   low-elevation rectenna must be. Includes hour-by-hour Earth-shadow eclipses.
2. **Dispatch**: each hour the satellite splits its output across visible rectennas to maximize revenue,
   with optional price impact (a 2 GW plant depresses the price where it sells).
3. **Benchmarks**: the same value bought with an HVDC line from a fixed rectenna, or a battery at it.

Data: 2024 and 2025 hourly day-ahead prices from CAISO (SP15), ERCOT (hub average), MISO (Illinois Hub),
NYISO (Capital zone), ISO-NE (Internal Hub) and Spain (OMIE). All are public with no account needed.

## Findings (2 GW satellite, no price impact)

- **Steering is worth +16% to +39%** over the best single rectenna in a US slot (100°W), and **+22% to +36%**
  across the Atlantic (40°W, Spain plus the US East Coast). The second and third rectennas capture almost all of it.
- **Value is broad, not spike-driven**: the top 10% of hours supply only about half of the gain.
- **Over long distances the beam is the cheapest wire.** Spain plus New England (2025): a second rectenna adds
  $366M/yr against about $376M/yr in annualized cost at NASA's ground-segment estimate. A subsea HVDC line doing the
  same job (6,800 km) would cost about $3.4B/yr. Beyond roughly 900 km over land or 300 km subsea, a rectenna is
  cheaper than an HVDC line of the same size.
- **Over short distances it isn't.** Within the US Northeast, an ordinary HVDC line or a battery beats a second rectenna.
- **Price impact raises the value of steering.** A 2 GW plant depresses prices in small markets, so spreading
  output across markets helps.
- **Batteries often do better on value per dollar** (3 of 4 cases). They complement steering rather than replace it.

## Reproduce

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
for y in 2025 2024; do for m in CAISO ERCOT MISO NYISO ISONE OMIE; do .venv/bin/python src/fetch_prices.py $m $y; done; done
.venv/bin/python src/experiments.py
.venv/bin/python src/figures.py
.venv/bin/python src/build_site.py                      # site/index.html
cd paper && tectonic -X compile paper.tex               # paper/paper.pdf
```

Outputs: `results/results.json`, `results/hourly.json`, `results/figs/*.png`, `site/index.html`, `paper/paper.pdf`.

## Key assumptions (all in code, all swept)

| Parameter | Value | Source |
|---|---|---|
| Satellite delivered power | 2 GW | NASA OTPS 2024, RD1 |
| Ground segment cost | $3.12B per 2 GW site | NASA OTPS 2024, RD1 |
| Minimum rectenna elevation | 15° | assumption |
| Cost of capital / life | 7% / 30 yr | assumption |
| HVDC | $0.5B/GW converters, $1.1M/km/GW land, $3.3M/km/GW subsea | approximate industry figures |
| Battery | $250/kWh, 4 h, 87% round trip, 15 yr | approximate 2025 US utility-scale |

Prices are taken as given (price-taker) unless the price-impact sensitivity is on. Revenue is energy-only,
day-ahead. Capacity payments, ancillary services and real-time spikes are excluded.

"""Inline prices and results into site/template.html -> site/index.html. Usage: python src/build_site.py"""
import json
from pathlib import Path

from geometry import STATIONS
from model import load_prices

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

data = {"stations": STATIONS.reset_index().to_dict(orient="records"), "years": {}}
for year in (2025, 2024):
    pr = load_prices(year, list(STATIONS.index))
    data["years"][year] = {
        "start": pr.index[0].isoformat(),
        "prices": {m: [None if v != v else round(float(v), 1) for v in pr[m]] for m in pr.columns},
    }
data["results"] = json.loads((ROOT / "results" / "results.json").read_text())
data["results"].pop("price_stats", None)

html = (SITE / "template.html").read_text().replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
(SITE / "index.html").write_text(html)
print("wrote", SITE / "index.html", f"{len(html) / 1e6:.2f} MB")

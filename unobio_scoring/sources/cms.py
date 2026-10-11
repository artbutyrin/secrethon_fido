"""Annual cost per patient of approved drugs from CMS "Medicare Part D / Part B Spending by Drug" (public API).

Part D (pharmacy drugs): https://data.cms.gov/data-api/v1/dataset/7e0b4365-fd63-4a29-8f5e-e0ac9f66a81b/data
Part B (clinic-administered): https://data.cms.gov/data-api/v1/dataset/76a714ad-3a2c-43ac-b76d-9dadf8f7d890/data
Query: ?filter[Gnrc_Name]=Evolocumab&size=50. Field used: Avg_Spnd_Per_Bene_<year> (Part D) /
Avg_Spndng_Per_Bene_<year> (Part B) = Medicare spending per beneficiary in that year.
Caveats: Part D is GROSS of manufacturer rebates (net is lower; the discount below is an assumption [A]); Part B is
based on ASP, close to net. A drug's first year can be partial (patients started mid-year) and understates the cost.
"""
from __future__ import annotations

import json
import statistics
import urllib.parse
import urllib.request  # noqa: F401  (kept for callers that pass their own opener)

from . import _net

PART_D = "https://data.cms.gov/data-api/v1/dataset/7e0b4365-fd63-4a29-8f5e-e0ac9f66a81b/data"
PART_B = "https://data.cms.gov/data-api/v1/dataset/76a714ad-3a2c-43ac-b76d-9dadf8f7d890/data"
PART_D_REBATE = 0.25   # [A] typical brand rebate share, used to turn gross Part D spending into a net price
MIN_BENEFICIARIES = 50  # below this the per-patient average is noise


def fetch(generic: str, timeout: int = 30, opener=_net.urlopen) -> list[dict]:
    """Rows for one generic name from Part D and Part B; each row gets "part"."""
    out = []
    for part, url in (("D", PART_D), ("B", PART_B)):
        q = url + "?" + urllib.parse.urlencode({"filter[Gnrc_Name]": generic, "size": 50})
        with opener(q, timeout=timeout) as r:
            rows = json.loads(r.read().decode("utf-8"))
        out += [dict(x, part=part) for x in rows]
    return out


def annual_cost(rows: list[dict], year: int = 2024) -> list[dict]:
    """Per brand: net annual cost per patient, beneficiaries, part, gross value."""
    out = []
    for r in rows:
        if r["part"] == "D" and r.get("Mftr_Name") != "Overall":
            continue                     # Part D lists each manufacturer plus an "Overall" row
        key = f"Avg_Spnd_Per_Bene_{year}" if r["part"] == "D" else f"Avg_Spndng_Per_Bene_{year}"
        benes = r.get(f"Tot_Benes_{year}") or ""
        try:
            gross, n = float(r.get(key) or "nan"), int(float(benes))
        except ValueError:
            continue
        if gross != gross or n < MIN_BENEFICIARIES:
            continue
        net = gross * (1 - PART_D_REBATE) if r["part"] == "D" else gross
        out.append({"brand": r.get("Brnd_Name"), "generic": r.get("Gnrc_Name"), "part": r["part"], "year": year,
                    "beneficiaries": n, "gross_per_patient": gross, "net_per_patient": net})
    return out


def price_analogues(costs: list[dict]) -> dict | None:
    """Price inputs for the economics from the approved drugs' costs: median, range, ceiling."""
    if not costs:
        return None
    by_generic: dict[str, list] = {}
    for c in costs:
        by_generic.setdefault(c["generic"], []).append(c)
    per_drug = []
    for g, cs in by_generic.items():   # beneficiary-weighted per generic, across brands/devices
        n = sum(c["beneficiaries"] for c in cs)
        per_drug.append({"generic": g, "net": sum(c["net_per_patient"] * c["beneficiaries"] for c in cs) / n,
                         "beneficiaries": n, "parts": sorted({c["part"] for c in cs})})
    nets = [d["net"] for d in per_drug]
    return {"annual_net_price_usd": statistics.median(nets), "range": [min(nets), max(nets)],
            "price_ceiling_usd": max(nets), "analogues": per_drug,
            "note": f"CMS Medicare spending per beneficiary {costs[0]['year']}; Part D minus {PART_D_REBATE:.0%} "
                    "rebate [A]"}

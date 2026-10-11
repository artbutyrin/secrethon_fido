"""Rare-disease patient counts from Orphanet (Orphadata product 9, "Epidemiological data", CC BY 4.0).

File: en_product9_prev.xml (~16 MB, updated twice a year). Download once and keep it next to the app:
  https://www.orphadata.com/data/xml/en_product9_prev.xml
  mirror: https://media.githubusercontent.com/media/Orphanet/Orphadata_aggregated/master/
          Epidemiological%20data/Rare%20disease%20epidemiology/en_product9_prev.xml
ValMoy is a mean value per 100,000 people (per 100,000 births for "Prevalence at birth").
The disease is found by OrphaCode; Open Targets gives it as a cross-reference "Orphanet_803" / "Orphanet:803".
"""
from __future__ import annotations

import re
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

from . import _net

URLS = ["https://www.orphadata.com/data/xml/en_product9_prev.xml",
        "https://media.githubusercontent.com/media/Orphanet/Orphadata_aggregated/master/"
        "Epidemiological%20data/Rare%20disease%20epidemiology/en_product9_prev.xml"]
US_POPULATION = 335_000_000          # [A] 2024, rounded
US_BIRTHS_PER_YEAR = 3_600_000       # [A]
BIRTH_PREVALENCE_YEARS_ALIVE = 20    # [A] used only when Orphanet has nothing but prevalence at birth


def download(dest: str | Path, timeout: int = 120) -> Path:
    dest = Path(dest)
    last = None
    for url in URLS:
        try:
            with _net.urlopen(url, timeout=timeout) as r, open(dest, "wb") as fh:
                fh.write(r.read())
            return dest
        except Exception as exc:  # noqa: BLE001 - try the mirror
            last = exc
    raise RuntimeError(f"Orphanet download failed: {last}. Download it by hand instead: "
                       f"curl -L -o {dest} {URLS[0]}")


def load(path: str | Path) -> dict[str, dict]:
    """{orphacode: {"name", "records": [{type, cls, per_100k, geo, validated, source}]}}"""
    out = {}
    root = ET.parse(path).getroot()
    for d in root.iter("Disorder"):
        code = d.findtext("OrphaCode")
        recs = []
        for p in d.iter("Prevalence"):
            try:
                val = float(p.findtext("ValMoy") or "nan")
            except ValueError:
                continue
            if val != val or val <= 0:
                continue
            recs.append({"type": p.findtext("PrevalenceType/Name"), "cls": p.findtext("PrevalenceClass/Name"),
                         "per_100k": val, "geo": p.findtext("PrevalenceGeographic/Name"),
                         "validated": p.findtext("PrevalenceValidationStatus/Name") == "Validated",
                         "source": p.findtext("Source")})
        out[code] = {"name": d.findtext("Name"), "records": recs}
    return out


def orphacode(xrefs: list[str] | None = None, name: str | None = None, data: dict | None = None) -> str | None:
    """OrphaCode from Open Targets cross-references ("Orphanet_803", "Orphanet:803") or, failing that, exact name."""
    for x in xrefs or []:
        m = re.match(r"(?i)orphanet[_:](\d+)$", str(x).strip())
        if m:
            return m.group(1)
    if name and data:
        low = name.strip().lower()
        for code, d in data.items():
            if (d["name"] or "").lower() == low:
                return code
    return None


def us_patients(entry: dict) -> dict | None:
    """Patients alive in the US: a point value, a low–high range and the basis. None if Orphanet has no usable data.

    Order: US point prevalence > median of validated point prevalences elsewhere > prevalence at birth x births x
    years alive [A]. Annual incidence alone is not used (patients alive depend on survival).
    """
    recs = [r for r in entry["records"] if r["validated"]] or entry["records"]
    point = [r for r in recs if r["type"] == "Point prevalence"]
    us = [r for r in point if r["geo"] == "United States"]
    if us:
        vals, basis, assumed = [r["per_100k"] for r in us], "US point prevalence", False
        rng = [min(r["per_100k"] for r in point), max(r["per_100k"] for r in point)]
    elif point:
        vals, basis, assumed = [r["per_100k"] for r in point], "median of validated point prevalences (non-US)", False
        rng = [min(vals), max(vals)]
    else:
        birth = [r for r in recs if r["type"] == "Prevalence at birth"]
        if not birth:
            return None
        per_birth = statistics.median(r["per_100k"] for r in birth)
        n = per_birth / 1e5 * US_BIRTHS_PER_YEAR * BIRTH_PREVALENCE_YEARS_ALIVE
        return {"us_patients": round(n), "range": [round(n / 2), round(n * 1.5)], "per_100k": None,
                "basis": f"prevalence at birth {per_birth}/100k x US births x {BIRTH_PREVALENCE_YEARS_ALIVE} years [A]",
                "assumed": True, "sources": [r["source"] for r in birth]}
    mid = statistics.median(vals)
    to_n = lambda x: round(x / 1e5 * US_POPULATION)  # noqa: E731
    return {"us_patients": to_n(mid), "range": [to_n(rng[0]), to_n(rng[1])], "per_100k": mid, "basis": basis,
            "assumed": assumed, "sources": [r["source"] for r in (us or point)]}

"""Market inputs for the economics (scorer 2.x, INTEGRATION steps 3-4): patients from Orphanet, prices from CMS.

What is collected once per run (stored in raw.collected["market"], so a rescore after new evidence needs no network):
  orphacode, orphanet_entry   Orphadata product 9 (epidemiology) entry for the disease, found by the Open Targets
                              cross-reference "Orphanet_<code>". The XML file (~16 MB) is read from UNOBIO_ORPHANET
                              or backend/data/orphanet/en_product9_prev.xml; download it once with
                              `python -m backend.app.market --download`. No file -> no patient count (a note says so).
  cms_costs_same_moa          CMS Medicare spending per beneficiary for the approved drugs with the same mechanism
                              (names from the approved_same_moa_count claim)
  cms_costs                   the same for every drug approved for the disease (approved_therapies_count claim);
                              other mechanisms, so the price ladder marks it as an assumption [A]
At scoring time `market_for(facts, collected_market, overrides)` turns these and what a person entered (`overrides`,
which always win) into the `market` input of unobio_scoring.evaluate, with a provenance tag per field.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from unobio_scoring.sources import cms, orphanet
from unobio_scoring.sources.market import build_market

from backend.app.sources.http import CachedHTTP, SourceError

ORPHANET_FILE = Path(__file__).resolve().parents[1] / "data" / "orphanet" / "en_product9_prev.xml"
MAX_ANALOGUES = 8
_ORPHANET: dict[str, dict] = {}


def orphanet_path() -> Path:
    return Path(os.environ.get("UNOBIO_ORPHANET") or ORPHANET_FILE)


def _shown(path: Path) -> str:
    """The path relative to the repo when it is inside it (no machine-specific prefix in notes and memos)."""
    try:
        return str(path.resolve().relative_to(Path(__file__).resolve().parents[2]))
    except ValueError:
        return str(path)


def load_orphanet(path: Path | None = None) -> dict | None:
    """The parsed Orphanet file (cached in memory), or None if it is not there."""
    path = path or orphanet_path()
    key = str(path)
    if key not in _ORPHANET:
        if not path.exists():
            return None
        _ORPHANET[key] = orphanet.load(path)
    return _ORPHANET[key]


class CMS:
    """CMS Medicare Part D / Part B spending by drug, through the shared JSON cache (backend/data/cache/cms)."""

    def __init__(self, http: CachedHTTP):
        self.http = http

    @classmethod
    def from_env(cls, offline: bool | None = None) -> "CMS":
        if offline is None:
            offline = os.environ.get("UNOBIO_OFFLINE", "") not in ("", "0", "false")
        return cls(CachedHTTP("cms", offline=offline))

    def rows(self, generic: str) -> list[dict]:
        out = []
        for part, url in (("D", cms.PART_D), ("B", cms.PART_B)):
            body = self.http.get(url, {"filter[Gnrc_Name]": generic, "size": 50}) or []
            out += [dict(x, part=part) for x in body if isinstance(x, dict)]
        return out

    def costs(self, names: list[str], year: int = 2024) -> tuple[list[dict], list[str]]:
        """Annual net cost per patient for each drug that CMS lists; (costs, names not found)."""
        costs, missing = [], []
        for name in names[:MAX_ANALOGUES]:
            got = []
            for variant in dict.fromkeys([name.title(), name.split()[0].title()]):   # "Nusinersen Sodium", "Nusinersen"
                got = cms.annual_cost(self.rows(variant), year)
                if got:
                    break
            costs += got
            if not got:
                missing.append(name.title())
        return costs, missing


def _drug_names(claims: list[dict], fact: str) -> list[str]:
    """Generic names of the drugs behind a structured count claim (its open_targets_drug sources)."""
    names: list[str] = []
    for c in claims:
        if c["fact"] == fact and c["origin"] == "structured":
            for s in c.get("sources") or []:
                if s.get("kind") == "open_targets_drug" and s.get("name") and s["name"] not in names:
                    names.append(s["name"])
    return names


def collect_market(norm: dict, claims: list[dict], cms_client: CMS | None,
                   orphanet_data: dict | None | bool = True) -> dict[str, Any]:
    """Everything the economics needs from public sources, with notes on what is missing. Never raises."""
    disease = norm["disease"]
    out: dict[str, Any] = {"orphacode": None, "orphanet_entry": None, "cms_costs": [], "cms_costs_same_moa": [],
                           "analogues": {}, "notes": []}
    data = load_orphanet() if orphanet_data is True else orphanet_data
    if data is None:
        out["notes"].append(f"Orphanet epidemiology file not found ({_shown(orphanet_path())}): no sourced patient count. "
                            "Download it with `python -m backend.app.market --download` or enter market.us_patients.")
    else:
        code = orphanet.orphacode(disease.get("xrefs"), disease.get("name"), data)
        out["orphacode"] = code
        entry = data.get(code) if code else None
        if entry and orphanet.us_patients(entry):
            out["orphanet_entry"] = entry
        else:
            out["notes"].append(f"No Orphanet prevalence for {disease.get('name')}"
                                + (f" (ORPHA:{code})" if code else " (no Orphanet cross-reference)")
                                + ": not a rare disease in Orphanet, or no epidemiology recorded. Enter market.us_patients.")
    for key, fact in (("cms_costs_same_moa", "approved_same_moa_count"), ("cms_costs", "approved_therapies_count")):
        names = _drug_names(claims, fact)
        out["analogues"][key] = names
        if not names or cms_client is None:
            continue
        try:
            costs, missing = cms_client.costs(names)
        except SourceError as exc:
            out["notes"].append(f"CMS prices not read: {exc}")
            continue
        out[key] = costs
        if missing:
            out["notes"].append(f"Not in CMS Medicare spending data ({fact}): {', '.join(missing)}")
    return out


def market_for(facts: dict, collected_market: dict | None, overrides: dict | None) -> tuple[dict | None, dict]:
    """-> (market input for evaluate or None, provenance per field). overrides: what a person entered (wins)."""
    cm = collected_market or {}
    if not (cm.get("orphanet_entry") or cm.get("cms_costs") or cm.get("cms_costs_same_moa") or overrides):
        return None, {}
    return build_market(facts, orphanet_entry=cm.get("orphanet_entry"), cms_costs=cm.get("cms_costs") or None,
                        cms_costs_same_moa=cm.get("cms_costs_same_moa") or None, overrides=overrides or None)


if __name__ == "__main__":   # python -m backend.app.market --download
    import sys
    if "--download" in sys.argv:
        dest = orphanet_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading Orphanet product 9 to {dest} ...")
        orphanet.download(dest)
        print(f"Done: {len(orphanet.load(dest))} disorders.")
    else:
        print(__doc__)

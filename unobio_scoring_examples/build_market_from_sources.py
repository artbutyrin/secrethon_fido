"""How to build `market` from Orphanet + CMS and score a case.

Offline by default (uses the excerpts in unobio_scoring/tests/fixtures). With --live it downloads Orphanet
product 9 and queries the CMS API (needs internet access to orphadata.com / github and data.cms.gov).

    python examples/build_market_from_sources.py [--live]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import unobio_scoring as U  # noqa: E402
from unobio_scoring.sources import build_market, cms, orphanet  # noqa: E402

FIX = ROOT / "unobio_scoring" / "tests" / "fixtures"
live = "--live" in sys.argv

# 1) facts as the pipeline produces them (here: ALS + SOD1 antisense, from the real claims)
facts = {"genetic_support": "mendelian", "moa_clinical_precedent": "approved_same", "approved_therapies_count": 3,
         "approved_same_moa_count": 1, "modality": "rna", "oncology": False, "rare_disease": True, "phase": "ph1"}
disease_xrefs = ["Orphanet:803"]                     # Open Targets disease.dbXRefs
approved_generics = ["Tofersen", "Riluzole", "Edaravone"]   # Open Targets: approved drugs for the disease

# 2) patients from Orphanet
if live:
    path = orphanet.download(ROOT / "en_product9_prev.xml")
else:
    path = FIX / "orphanet_product9_excerpt.xml"
orpha = orphanet.load(path)
code = orphanet.orphacode(disease_xrefs)

# 3) prices from CMS; for a me-too the analogues are the same-mechanism drugs, otherwise the standard of care
if live:
    rows = [r for g in ["Tofersen"] for r in cms.fetch(g)]
else:
    rows = json.loads((FIX / "cms_rows.json").read_text())["Tofersen"]
costs = cms.annual_cost(rows)

market, provenance = build_market(facts, orphanet_entry=orpha.get(code), cms_costs_same_moa=costs,
                                  overrides={"eligible_share": 0.02})   # analyst: SOD1 carriers ~2% of ALS
print(json.dumps({"market": market, "provenance": provenance}, indent=1, default=str)[:1500])

# 4) score
payload = U.evaluate(U.load_config(), facts, market=market, round_terms={"cash_m": 30})
print(U.card(payload))

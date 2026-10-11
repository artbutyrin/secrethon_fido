"""Assemble the `market` input of evaluate() from sources, marking every assumption."""
from __future__ import annotations

from . import cms, orphanet


def build_market(facts: dict, *, orphanet_entry: dict | None = None, cms_costs: list[dict] | None = None,
                 cms_costs_same_moa: list[dict] | None = None,
                 overrides: dict | None = None) -> tuple[dict | None, dict]:
    """-> (market or None, provenance {field: "S" | "A" | "user", plus notes}).

    orphanet_entry: one entry of orphanet.load(...)[code]; cms_costs: cms.annual_cost(rows) for the approved drugs
    in the indication; cms_costs_same_moa: the same for drugs with the same mechanism (any indication). Their generic
    names come from Open Targets. Both go to the price ladder (same mechanism first). overrides: values a person
    entered (win). Without a patient count the economics cannot run and None is returned.
    """
    m, prov, assumed = {}, {}, []
    if orphanet_entry:
        p = orphanet.us_patients(orphanet_entry)
        if p:
            m["us_patients"] = p["us_patients"]
            prov["us_patients"] = {"tag": "A" if p["assumed"] else "S", "basis": p["basis"], "range": p["range"],
                                   "source": "Orphanet product 9", "refs": p["sources"][:5]}
            m["us_patients_range"] = p["range"]
            # US rare-disease definition: < 200,000 patients (about 60 per 100,000)
            if p["us_patients"] < 200_000 and facts.get("oncology") is not True and facts.get("acute_indication") is not True:
                m["segment"] = "rare"
            if p["assumed"]:
                assumed.append("us_patients")
    analogues = {}
    for key, costs in (("same_moa", cms_costs_same_moa), ("same_indication", cms_costs)):
        a = cms.price_analogues(costs or [])
        if a:
            analogues[key] = [d["net"] for d in a["analogues"]]
            prov[f"price_{key}"] = {"tag": "S", "basis": a["note"], "analogues": a["analogues"],
                                    "source": "CMS Medicare Spending by Drug"}
            m.setdefault("price_ceiling_usd", a["price_ceiling_usd"])
    if analogues:
        m["price_analogues"] = analogues
    for k, v in (overrides or {}).items():
        m[k] = v
        prov[k] = {"tag": "user"}
        if k in assumed:
            assumed.remove(k)
    if "us_patients" not in m:
        return None, prov
    m["assumed"] = assumed
    return m, prov

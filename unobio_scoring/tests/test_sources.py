"""Source adapters on real excerpts (Orphanet product 9, CMS spending rows fetched 2026-10-09)."""
import json
from pathlib import Path

import unobio_scoring as U
from unobio_scoring.sources import cms, orphanet, build_market

FIX = Path(__file__).parent / "fixtures"
ORPHA = orphanet.load(FIX / "orphanet_product9_excerpt.xml")
CMS = json.loads((FIX / "cms_rows.json").read_text())


def test_orphacode_from_open_targets_xrefs_and_name():
    assert orphanet.orphacode(["MONDO:0004976", "Orphanet_803"]) == "803"
    assert orphanet.orphacode(["Orphanet:399"]) == "399"
    assert orphanet.orphacode([], "Huntington disease", ORPHA) == "399"


def test_us_patients():
    hd = orphanet.us_patients(ORPHA["399"])                 # US point prevalence 1.9 / 100k
    assert hd["basis"] == "US point prevalence" and 6000 <= hd["us_patients"] <= 7000 and not hd["assumed"]
    als = orphanet.us_patients(ORPHA["803"])                # no US prevalence: median of validated ones
    assert als["basis"].startswith("median") and 10000 < als["us_patients"] < 20000
    dmd = orphanet.us_patients(ORPHA["98896"])
    assert dmd["us_patients"] > 0


def test_cms_costs_and_analogues():
    rep = cms.annual_cost(CMS["Evolocumab"])
    assert {c["part"] for c in rep} == {"D"} and len(rep) == 3            # "Overall" rows only
    q = cms.annual_cost(CMS["Tofersen"])
    assert q[0]["net_per_patient"] == q[0]["gross_per_patient"] > 100000   # Part B: ASP-based, no rebate
    a = cms.price_analogues(rep)
    assert 2000 < a["annual_net_price_usd"] < 4000 and a["analogues"][0]["generic"] == "Evolocumab"


def test_build_market_and_evaluate_end_to_end():
    facts = {"genetic_support": "mendelian", "moa_clinical_precedent": "approved_same", "approved_therapies_count": 3,
             "approved_same_moa_count": 1, "modality": "rna", "oncology": False, "rare_disease": True, "phase": "ph1"}
    market, prov = build_market(facts, orphanet_entry=ORPHA["803"],
                                cms_costs_same_moa=cms.annual_cost(CMS["Tofersen"]))
    assert prov["us_patients"]["tag"] == "S" and prov["price_same_moa"]["tag"] == "S" and market["assumed"] == []
    assert market["price_analogues"]["same_moa"][0] > 100000
    p = U.evaluate(U.load_config(), facts, market=market, round_terms={"cash_m": 2}, mc_draws=300)
    e = p["economics"]
    assert e["drives_verdict"] and set(e["facts"]) >= {"economics_negative", "economics_weak", "runway_short"}
    assert e["milestone"]["capital_to_milestone_m"][0] > 0 and e["milestone"]["financing_rounds_to_approval"] == 4
    assert e["facts"]["runway_short"] is True                 # $2m < Phase 1 cost
    # 2.2: with 2024-dollar costs and overhead the second SOD1 antisense drug's economics are weak or negative, so
    # the verdict is already below Invest and no cap is needed
    assert p["verdict"]["decision"] == "Conditional" and {"economics_negative", "economics_weak"} & {r["id"] for r in p["rules"]}
    capped = U.evaluate(U.load_config(), facts, market={**market, "us_patients": 2_000_000},
                        round_terms={"cash_m": 2}, mc_draws=300)
    assert capped["verdict"]["decision"] == "Conditional" and "cap_runway" in [c["id"] for c in capped["verdict"]["caps"]]


def test_assumed_inputs_do_not_change_the_verdict():
    facts = {"genetic_support": "mendelian", "moa_clinical_precedent": "approved_related", "approved_therapies_count": 0,
             "rare_disease": True, "phase": "ph2", "modality": "rna", "oncology": False}
    market = {"us_patients": 50, "assumed": ["us_patients"]}          # tiny, but an assumption
    p = U.evaluate(U.load_config(), facts, market=market, mc_draws=100)
    assert p["economics"]["drives_verdict"] is False and p["economics"]["facts"] == {}
    assert p["verdict"]["decision"] == "Invest" and "not used in the verdict" in p["economics_note"]

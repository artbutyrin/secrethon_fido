"""Tests of unobio_scoring 2.1: the review fixes, the claims gate, economics and the report.
The version 1.1 behaviour itself is covered by the 286 tests of scoring_engine/, run against this package with
fixes=False by validation/v11_regression.py (283 pass; the 3 differences are listed there).

Run: python -m pytest unobio_scoring/tests -q
"""
import json

import pytest

import unobio_scoring as U
from unobio_scoring import economics as E

CFG = U.load_config()
V11 = U.load_config(fixes=False)

# strong mechanism case with asset data: Invest in both versions
STRONG = {"genetic_support": "mendelian", "moa_clinical_precedent": "approved_related", "approved_therapies_count": 0,
          "own_ph2_positive": True, "phase": "ph2", "oncology": False}


def v(facts, cfg=CFG):
    return U.score(cfg, facts).verdict


def test_config_is_built_in_and_valid():
    assert CFG.raw["version"] == "2.7" and V11.raw["version"] == "1.1"
    assert len(CFG.facts) == len(V11.facts) + 12 and len(CFG.rules) == len(V11.rules) + 7
    assert CFG.sha256 != V11.sha256


def test_strong_case_invests_in_both():
    assert v(STRONG) == v(STRONG, V11) == "Invest"


# --- F44: Invest needs asset data ------------------------------------------------------------------------------
def test_mechanism_only_invest_stays_invest_by_default():
    mech = {k: x for k, x in STRONG.items() if k not in ("own_ph2_positive",)}
    assert v(mech, V11) == v(mech) == "Invest"
    r = U.score(U.load_config(asset_data_for_invest=True), mech)      # optional switch
    assert r.verdict == "Conditional" and r.grounds == "capped" and r.caps[0]["id"] == "cap_asset_data"


# --- F38: me-too -------------------------------------------------------------------------------------------------
ME_TOO = {**STRONG, "approved_therapies_count": 4, "approved_same_moa_count": 3,
          "moa_clinical_precedent": "approved_same"}


def test_me_too_without_differentiation_is_do_not_invest_crowded():
    """2.5: 2+ approved drugs of the same mechanism and no proven advantage -> Do Not Invest, grounds "crowded"."""
    assert U.score(V11, ME_TOO).kills == ["me_too"]
    r = U.score(CFG, ME_TOO)
    assert r.kills == ["me_too"] and (r.verdict, r.grounds) == ("Do Not Invest", "crowded")
    assert "Crowded" in r.reason
    e = U.evaluate(CFG, ME_TOO)
    assert e["verdict"]["grounds_text"].startswith("the mechanism is already approved")
    # what would change it: proven differentiation
    assert any(cf["fact"] in ("differentiation_claim", "differentiation_evidence") and cf["verdict_to"] != "Do Not Invest"
               for cf in e["what_would_change"])


def test_me_too_kill_only_when_differentiation_refuted():
    r = U.score(CFG, {**ME_TOO, "differentiation_claim": "efficacy", "differentiation_evidence": False})
    assert set(r.kills) == {"me_too", "me_too_refuted"} and (r.verdict, r.grounds) == ("Do Not Invest", "crowded")


def test_proven_differentiation_lifts_the_cap():
    assert v({**ME_TOO, "differentiation_claim": "efficacy", "differentiation_evidence": True}) == "Invest"


def test_new_modality_class_is_not_me_too():
    r = U.score(CFG, {**ME_TOO, "approved_same_moa_same_modality_count": 0})
    assert "me_too" not in r.fired and r.verdict == "Invest"


# --- F41: patent and statutory exclusivity -------------------------------------------------------------------------
@pytest.mark.parametrize("years,kill,strong", [(None, True, False), (3, True, False), (5, False, True),
                                               (7, False, False), (12, False, False)])
def test_no_patent_depends_on_exclusivity(years, kill, strong):
    f = {**STRONG, "patent_status": "none"}
    if years is not None:
        f["regulatory_exclusivity_years"] = years
    r = U.score(CFG, f)
    assert ("no_patent" in r.kills) == kill and ("no_patent_short_exclusivity" in r.fired) == strong


# --- F31 / F52: caps -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("fact", ["runway_short", "economics_negative"])
def test_caps(fact):
    assert v({**STRONG, fact: True}, V11 if fact == "runway_short" else CFG) in ("Invest", "Conditional")
    r = U.score(CFG, {**STRONG, fact: True})
    assert r.verdict == "Conditional" and r.grounds == "capped"


# --- run review 2.5: mechanism refuted --------------------------------------------------------------------------
def test_mechanism_refuted_when_approved_nowhere():
    f = {"moa_failures_efficacy_ph23": 2, "moa_clinical_precedent": "none"}
    assert U.score(V11, f).kills == [] and U.score(CFG, f).kills == ["mechanism_refuted"]
    assert U.score(CFG, {**f, "moa_successes_same_indication": 1}).kills == []
    assert U.score(CFG, {"moa_failures_efficacy_ph23": 2, "moa_clinical_precedent": "approved_unrelated"}).kills == []


# --- gate ----------------------------------------------------------------------------------------------------------
def claim(i, fact, value, origin="structured", **kw):
    return {"id": f"c{i}", "fact": fact, "value": value, "origin": origin, **kw}


BASE = [claim(1, "genetic_support", "none"), claim(2, "moa_clinical_precedent", "none"),
        claim(3, "approved_therapies_count", 4), claim(4, "oncology", False)]


def failures(n_drugs=2, **kw):
    src = [{"id": f"NCT{i}", "drugs": [f"drug{i}"], "quote": "terminated for futility"} for i in range(n_drugs)]
    return claim(9, "moa_failures_efficacy_ph23", n_drugs, "llm", verified=True, quote="futility",
                 doc_ids=["sponsor:a", "sponsor:b"], sources=src, **kw)


def test_two_sponsors_from_one_llm_run_do_not_confirm():
    got = U.facts_from_claims(CFG, BASE + [failures()])
    assert "moa_failures_efficacy_ph23" not in got["facts"]
    p = got["pending"][0]
    assert p["verdict_if_confirmed"] == "Do Not Invest" and "mechanism_refuted" in p["reason"]
    got = U.facts_from_claims(CFG, BASE + [failures(confirmed=True)])
    assert got["facts"]["moa_failures_efficacy_ph23"] == 2 and got["pending"] == []


def test_value_that_switches_a_rule_off_also_waits():
    # F32: an LLM claim that REMOVES a minus needs a human too
    base = BASE + [claim(5, "patent_status", "none")]
    got = U.facts_from_claims(CFG, base + [claim(6, "regulatory_exclusivity_years", 7, "llm", verified=True,
                                                 quote="orphan drug exclusivity of seven years")])
    assert got["pending"] and "switches off no_patent" in got["pending"][0]["reason"]


def test_harmless_llm_value_is_used():
    got = U.facts_from_claims(CFG, BASE + [claim(7, "route_of_administration", "oral", "llm", verified=True,
                                                 quote="oral tablet")])
    assert got["facts"]["route_of_administration"] == "oral" and got["pending"] == []


def test_negated_quote_and_absence_and_inference_are_rejected():
    got = U.facts_from_claims(CFG, [
        claim(1, "class_safety_signal", True, "llm", verified=True, quote="stopped, not due to safety concerns"),
        claim(2, "approved_same_moa_count", 0, "llm", verified=True, quote="none approved"),
        claim(3, "grade5_related", True, "llm", verified=True, quote="x", evidence_type="inference"),
        claim(4, "economics_negative", True, "llm", verified=True, quote="x"),
        claim(5, "genetic_support", "gwas", "llm", verified=False, quote="x")])
    assert got["facts"] == {} and len(got["rejected"]) == 5


def test_recount_distinct_drugs_drops_negated_and_secondary_trials():
    src = [{"id": "A1", "drugs": ["alpha"], "quote": "futility"}, {"id": "A2", "drugs": ["alpha"], "quote": "futility"},
           {"id": "B1", "drugs": ["beta"], "quote": "core study was stopped", "stopped_due_to_other_trial": True},
           {"id": "C1", "drugs": ["gamma"], "quote": "not due to lack of efficacy"}]
    got = U.facts_from_claims(CFG, BASE + [claim(9, "moa_failures_efficacy_ph23", 4, "llm", verified=True,
                                                 quote="futility", sources=src, confirmed=True)])
    assert got["facts"]["moa_failures_efficacy_ph23"] == 1


def test_lower_bound_and_conflicts():
    got = U.facts_from_claims(CFG, [claim(1, "ph3_same_moa_count", 2, lower_bound=True),
                                    claim(2, "phase", "ph2", source="a"), claim(3, "phase", "ph3")])
    assert got["pending"][0]["fact"] == "ph3_same_moa_count"
    assert got["conflicts"][0]["fact"] == "phase" and "phase" not in got["facts"]


def test_user_outranks_structured():
    got = U.facts_from_claims(CFG, [claim(1, "phase", "ph3"), claim(2, "phase", "ph2", "user")])
    assert got["facts"]["phase"] == "ph2"


# --- economics -----------------------------------------------------------------------------------------------------
RARE = {"phase": "ph2", "modality": "rna", "rare_disease": True, "genetic_support": "none"}
MARKET = {"us_patients": 6000, "diagnosis_rate": 0.8, "treatment_rate": 0.8, "peak_share": 0.6,
          "annual_net_price_usd": 220200}


def test_economics_is_deterministic_and_ordered():
    a = E.underwrite(RARE, MARKET, draws=300, seed=1)
    b = E.underwrite(RARE, MARKET, draws=300, seed=1)
    assert a["monte_carlo"] == b["monte_carlo"]
    mc = a["monte_carlo"]
    assert mc["p10_m"] <= mc["p50_m"] <= mc["p90_m"]
    assert a["worse_cost_case"]["rnpv_m"] < a["base"]["rnpv_m"]


def test_break_even_price_gives_zero_rnpv():
    m = E.resolve_inputs(RARE, MARKET)
    plan = E.phase_plan(RARE, m)
    bep = E.break_even_price(RARE, m, plan)
    assert abs(E.rnpv(RARE, m, plan, price_mult=bep / m["annual_net_price_usd"])["rnpv_m"]) < 0.05


def test_genetics_raises_success_only_in_clinic():
    p0 = {s["stage"]: s["p_success"] for s in E.phase_plan(RARE, {})}
    p1 = {s["stage"]: s["p_success"] for s in E.phase_plan({**RARE, "genetic_support": "mendelian"}, {})}
    assert p1["ph2"] > p0["ph2"] and p1["ph3"] > p0["ph3"] and p1["filed"] == p0["filed"]


def test_tiny_market_caps_a_strong_case():
    p = U.evaluate(CFG, {**STRONG, "modality": "small_molecule"},
                   market={"us_patients": 50, "annual_net_price_usd": 20000, "peak_share": 0.2}, mc_draws=200)
    assert p["economics"]["facts"]["economics_negative"] is True
    assert p["verdict"]["decision"] == "Conditional" and p["verdict"]["caps"][0]["id"] == "cap_economics"


def test_given_value_beats_computed_economics():
    p = U.evaluate(CFG, {**STRONG, "economics_negative": False},
                   market={"us_patients": 50, "annual_net_price_usd": 20000, "peak_share": 0.2}, mc_draws=100)
    assert p["verdict"]["decision"] == "Invest"


# --- payload and report --------------------------------------------------------------------------------------------
def test_payload_serialises_and_renders():
    p = U.evaluate(CFG, {**STRONG, "modality": "rna", "rare_disease": True}, market=MARKET,
                   round_terms={"pre_money_m": 120, "investment_m": 40}, mc_draws=200)
    json.dumps(p, default=str)
    assert U.card(p).startswith("VERDICT:") and U.markdown(p).startswith("# ")
    assert "investor" in p["economics"]


def test_v11_mode_is_unchanged_on_a_mechanism_grid():
    """Every combination of the mechanism facts open data give: the fixes change no verdict."""
    import itertools
    for g, pr, a, onc in itertools.product(["none", "gwas", "mendelian", "somatic_driver", "no_data"],
                                           ["none", "approved_unrelated", "approved_related"], [0, 1, 5], [True, False]):
        f = {"genetic_support": g, "moa_clinical_precedent": pr, "approved_therapies_count": a, "oncology": onc}
        old, new = U.score(V11, f), U.score(CFG, f)
        if old.verdict == "Do Not Invest" and new.neg == 0:
            # 2.4: no_genetics_no_precedent is a note: without a minus it is Insufficient evidence, not Do Not Invest
            assert "no_genetics_no_precedent" in new.fired and new.verdict == "Insufficient evidence"
        else:
            assert new.verdict == old.verdict



# --- 2.2: economics fixes from the evaluation of 2.1 ---------------------------------------------------------------------
RARE_ASO = {"genetic_support": "mendelian", "moa_clinical_precedent": "none", "approved_therapies_count": 2,
            "approved_same_moa_count": 0, "modality": "rna", "oncology": False, "rare_disease": True, "phase": "ph2"}


def test_exclusivity_uses_empirical_period_and_statutory_floors():
    """Review F06 / F13: 13 years empirical with a granted or unknown patent; orphan 7, biologic 12, NCE 5 floors."""
    m = lambda f: E.resolve_inputs(f, {"us_patients": 6000, "annual_net_price_usd": 220000})  # noqa: E731
    assert m(RARE_ASO)["exclusivity_years_after_launch"] == 13.0
    assert "patent status unknown" in m(RARE_ASO)["exclusivity_basis"]
    assert m({**RARE_ASO, "patent_status": "none"})["exclusivity_years_after_launch"] == 7          # orphan floor
    assert m({**RARE_ASO, "patent_status": "none", "rare_disease": False})["exclusivity_years_after_launch"] == 5
    assert m({**RARE_ASO, "patent_status": "expired", "modality": "antibody"})["exclusivity_years_after_launch"] == 12


def test_phase_costs_are_in_2024_dollars_with_trials_and_overhead():
    """Review patch 01: Sertkaya per trial x 1.71 / 1.52 / 2.66 trials x CPI 1.457, plus overhead per year."""
    plan = {s["stage"]: s for s in E.phase_plan({**RARE_ASO, "phase": "ph1"}, {})}
    assert abs(plan["ph3"]["trial_cost_m"] - 20.0 * 2.66 * 1.457) < 0.1
    assert abs(plan["ph1"]["overhead_m"] - 5.0 * 2.3) < 1e-9 and plan["ph1"]["cost_m"] > plan["ph1"]["trial_cost_m"]
    worse = {s["stage"]: s for s in E.phase_plan({**RARE_ASO, "phase": "ph1"}, {"cost_case": "worse"})}
    assert abs(worse["ph3"]["cost_m"] - 255.4 * 1.347) < 0.1 and worse["ph3"]["overhead_m"] == 0


def test_defaults_are_listed_for_the_report():
    m = E.resolve_inputs(RARE_ASO, {"us_patients": 6000, "annual_net_price_usd": 220000, "treatment_rate": 0.6})
    assert {"diagnosis_rate", "class_share", "compliance"} <= set(m["defaulted"]) and "treatment_rate" not in m["defaulted"]


def test_unknown_outcome_of_a_finished_class_phase3_caps_invest():
    """2.4, mechanism sample 10.10.2026 (Huntington + HTT ASO): Mendelian genetics alone stays Invest (37–40% launch
    in validation), but not while a same-mechanism Phase 3 here has finished with an unknown result (tominersen)."""
    assert U.evaluate(CFG, RARE_ASO)["verdict"]["decision"] == "Invest"
    r = U.evaluate(CFG, {**RARE_ASO, "moa_ph23_unknown_outcome_count": 1})
    assert (r["verdict"]["decision"], r["verdict"]["grounds"]) == ("Conditional", "capped")
    assert [c["id"] for c in r["verdict"]["caps"]] == ["cap_unknown_class_outcome"]


def test_round_price_caps_invest_and_gives_the_max_pre_money():
    """Review F23: Invest on the asset, but this round does not earn the discount rate at the asked pre-money."""
    market = {"us_patients": 30000, "annual_net_price_usd": 250000}
    cheap = U.evaluate(CFG, RARE_ASO, market=market, round_terms={"pre_money_m": 5, "investment_m": 20}, mc_draws=200)
    dear = U.evaluate(CFG, RARE_ASO, market=market, round_terms={"pre_money_m": 5000, "investment_m": 20}, mc_draws=200)
    inv = dear["economics"]["investor"]
    assert cheap["verdict"]["decision"] == "Invest" and cheap["economics"]["facts"]["round_overpriced"] is False
    assert dear["verdict"]["decision"] == "Conditional" and "cap_round_price" in [c["id"] for c in dear["verdict"]["caps"]]
    assert 0 < inv["max_pre_money_m"] < 5000 and inv["irr_expected"] < inv["required_irr"]


def test_round_price_is_not_used_when_patients_or_price_are_assumed():
    e = U.evaluate(CFG, RARE_ASO, market={"us_patients": 30000, "assumed": ["us_patients"]},
                   round_terms={"pre_money_m": 5000, "investment_m": 20}, mc_draws=100)
    assert "round_overpriced" not in e["economics"]["facts"] and e["verdict"]["decision"] == "Invest"


def test_class_engagement_with_a_failure_is_a_strong_minus_but_not_asset_data():
    f = {**RARE_ASO, "class_target_engagement_human": True, "moa_failures_efficacy_ph23": 1}
    r = U.evaluate(CFG, f)
    assert {"one_mechanism_failure", "engaged_no_benefit"} <= {x["id"] for x in r["rules"]}
    assert r["verdict"]["decision"] == "Do Not Invest"
    chain = next(i for i in r["scorecard"] if i["id"] == "translation_chain")
    assert chain["color"] == "U"                    # class evidence is not data about the asset


def test_cli_round_terms_ask_about_the_round(tmp_path, capsys):
    """HTT report item 2: with round terms the question is this round, so Invest needs data on the asset itself."""
    from pathlib import Path
    from unobio_scoring.__main__ import main
    case = Path(__file__).resolve().parents[2] / "unobio_scoring_examples" / "htt_huntington.facts.json"
    out = tmp_path / "htt.json"
    assert main([str(case), "--json", str(out), "--draws", "300"]) in (0, None)
    p = json.loads(out.read_text())
    assert p["verdict"]["decision"] == "Conditional" and [c["id"] for c in p["verdict"]["caps"]] == ["cap_asset_data"]
    thesis = json.loads(case.read_text())
    thesis.pop("round_terms")
    (tmp_path / "thesis.json").write_text(json.dumps(thesis))
    assert main([str(tmp_path / "thesis.json"), "--json", str(out), "--draws", "300"]) in (0, None)
    assert json.loads(out.read_text())["verdict"]["decision"] == "Invest"

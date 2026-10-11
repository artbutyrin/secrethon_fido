"""2.4: fixes from the mechanism sample of 10 October 2026 (15 pairs with an explicit mechanism). Offline, small inputs."""
import httpx
import pytest

from backend.app.facts import (NOT_SAME_KEY, Claims, _same_mechanism, approved_same_mechanism, direction_of,
                               indication_track_record_claims, mark_class_members, unknown_outcome_claims)
from backend.app.trials import auto_confirm, trial_claims

D = {"id": "D1", "name": "disease one"}


def drug(name, targets_by_row, action="INHIBITOR", moa_text=""):
    return {"name": name, "mechanismsOfAction": {"rows": [
        {"actionType": action, "mechanismOfAction": moa_text, "targets": [{"id": t} for t in ts]}
        for ts in targets_by_row]}}


def report(nct, stage, status, disease="D1", approved=False):
    r = {"id": nct, "clinicalStage": "APPROVAL" if approved else stage, "trialOverallStatus": status,
         "diseases": [{"disease": {"id": disease}}]}
    if approved:
        r["source"] = "FDA"
    return r


def part(*rows):
    return {"ok": True, "complete": True, "data": {"rows": list(rows)}}


# --- approved drugs are not failures (SGLT2, GLP-1, ABL1, KRAS G12C, PCSK9, SOD1 on 10.10) ---------------------------
def labelled(*ncts, label="efficacy"):
    return {"labels": {n: [{"label": label, "quote": "futility", "verified": True}] for n in ncts}, "errors": []}


def stopped(nct, drugs, stage="PHASE_3"):
    return {"nct": nct, "why_stopped": "futility", "status": "TERMINATED", "stage": stage, "sponsor": nct,
            "url": "", "in_disease": True, "drugs": drugs, "same_mechanism_drugs": drugs}


def test_an_approved_drug_is_never_an_efficacy_failure():
    trials = [stopped("NCT1", ["DAPAGLIFLOZIN"]), stopped("NCT2", ["OTHERFLOZIN"])]
    c = Claims()
    failed = trial_claims(c, trials, labelled("NCT1", "NCT2"), D, {"symbol": "SLC5A2", "action": "inhibit"},
                          approved_here={"DAPAGLIFLOZIN PROPANEDIOL"})
    claim = next(x for x in c.items if x["fact"] == "moa_failures_efficacy_ph23")
    assert claim["value"] == 1 and failed == {"OTHERFLOZIN"}                  # salt forms are one drug


def test_a_safety_stop_of_a_drug_approved_anywhere_is_not_a_discontinued_program():
    trials = [stopped("NCT1", ["SEMAGLUTIDE"]), stopped("NCT2", ["X1"]), stopped("NCT3", ["X2"])]
    for t in trials:
        t["in_disease"] = False
    c = Claims()
    trial_claims(c, trials, labelled("NCT1", "NCT2", "NCT3", label="safety"), D, {"symbol": "GLP1R", "action": None},
                 approved_anywhere={"SEMAGLUTIDE"})
    assert next(x for x in c.items if x["fact"] == "moa_discontinued_safety_count")["value"] == 2


def test_approved_sets_come_from_labels_mapped_to_the_disease():
    rows = [{"drug": drug("A SODIUM", [["T"]]), "clinicalReports": [report("r1", "", "", approved=True)]},
            {"drug": drug("B", [["T"]]), "clinicalReports": [report("r2", "", "", disease="D9", approved=True)]},
            {"drug": drug("C", [["T"]], action="AGONIST"), "clinicalReports": [report("r3", "", "", approved=True)]}]
    here, anywhere = approved_same_mechanism(part(*rows), "D1", "T", "inhibit")
    assert here == {"A"} and anywhere == {"A", "B"}                           # C is the opposite direction


# --- the same-mechanism class (ABL1 multi-kinase drugs, KRAS G12C vs pan-RAS) ------------------------------------
def test_a_multi_target_drug_never_developed_here_is_not_the_same_mechanism():
    imatinib = {"drug": drug("IMATINIB", [["ABL1"], ["KIT"], ["PDGFRA"]]), "clinicalReports": [report("r", "PHASE_3", "COMPLETED")]}
    regorafenib = {"drug": drug("REGORAFENIB", [["ABL1"], ["KDR"], ["RAF1"], ["KIT"]]),
                   "clinicalReports": [report("r", "PHASE_3", "COMPLETED", disease="D9")]}
    p = part(imatinib, regorafenib)
    out = mark_class_members(p, {"id": "ABL1", "symbol": "ABL1", "action": "inhibit"}, "D1")
    assert [x["name"] for x in out] == ["REGORAFENIB"]
    assert _same_mechanism(imatinib["drug"], "ABL1", "inhibit")[0] is True
    assert _same_mechanism(regorafenib["drug"], "ABL1", "inhibit")[0] is False
    mark_class_members(p, {"id": "ABL1", "action": "inhibit"}, "D9")          # marks are recomputed per run
    assert NOT_SAME_KEY not in regorafenib["drug"]


def test_a_family_wide_inhibitor_is_not_a_variant_specific_one():
    sotorasib = {"drug": drug("SOTORASIB", [["KRAS"]]), "clinicalReports": []}
    salirasib = {"drug": drug("SALIRASIB", [["KRAS", "HRAS", "NRAS"]]), "clinicalReports": []}
    out = mark_class_members(part(sotorasib, salirasib), {"id": "KRAS", "action": "inhibit", "variant": "G12C"}, "D1")
    assert [x["name"] for x in out] == ["SALIRASIB"] and "G12C" in out[0]["reason"]
    sotorasib["drug"]["mechanismsOfAction"]["rows"][0]["mechanismOfAction"] = "GTPase KRas G12C inhibitor"
    salirasib["clinicalReports"] = [report("r", "PHASE_2", "COMPLETED")]       # developed in this disease
    out = mark_class_members(part(sotorasib, salirasib), {"id": "KRAS", "action": "inhibit"}, "D1")
    assert out == []                                       # no variant in the input: both are the RAS-inhibitor class


def test_gene_therapy_and_protein_replacement_add_function():
    assert direction_of("EXOGENOUS GENE") == "activate" and direction_of("EXOGENOUS PROTEIN") == "activate"
    assert direction_of("SEQUESTERING AGENT") == "inhibit"


def test_the_variant_reaches_the_normalized_target():
    from backend.app.mechanism import parse_mechanism
    assert parse_mechanism("KRAS G12C inhibitor").variant == "G12C"


# --- unknown outcome of a finished class trial (HTT + tominersen) ---------------------------------------------------
def test_a_finished_phase3_with_no_known_outcome_is_counted():
    tominersen = {"drug": drug("TOMINERSEN", [["HTT"]], action="ANTISENSE INHIBITOR"), "clinicalReports": [
        report("nct03761849", "PHASE_3", "COMPLETED"), report("nct05686551", "PHASE_2", "ACTIVE_NOT_RECRUITING")]}
    moved_on = {"drug": drug("NEXTERSEN", [["HTT"]], action="ANTISENSE INHIBITOR"), "clinicalReports": [
        report("nct1", "PHASE_2", "COMPLETED"), report("nct2", "PHASE_3", "RECRUITING")]}
    t = {"id": "HTT", "symbol": "HTT", "action": "inhibit"}
    c = Claims()
    unknown_outcome_claims(c, D, t, part(tominersen, moved_on), set(), set())
    assert [(x["fact"], x["value"]) for x in c.items] == [("moa_ph23_unknown_outcome_count", 1)]
    assert "Tominersen" in c.items[0]["statement"]
    c = Claims()
    unknown_outcome_claims(c, D, t, part(tominersen), set(), {"TOMINERSEN"})   # its failure is known: not unknown
    assert c.items == []


# --- indication track record of other targets -----------------------------------------------------------------------
def test_track_record_counts_other_targets_once():
    rows = [{"drug": drug("A", [["T1"]]), "maxClinicalStage": "APPROVAL",
             "clinicalReports": [report("r1", "", "", approved=True)]},
            {"drug": drug("B", [["T2"]]), "maxClinicalStage": "PHASE_3", "clinicalReports": [report("r2", "PHASE_3", "TERMINATED")]},
            {"drug": drug("C", [["T3"]]), "maxClinicalStage": "PHASE_3", "clinicalReports": [report("r3", "PHASE_3", "RECRUITING")]},
            {"drug": drug("D", [["OWN"]]), "maxClinicalStage": "PHASE_3", "clinicalReports": [report("r4", "PHASE_3", "TERMINATED")]}]
    c = Claims()
    indication_track_record_claims(c, D, {"id": "OWN"}, part(*rows))
    v = {x["fact"]: x["value"] for x in c.items}
    assert v == {"indication_ph3_outcomes_other_moa": 2, "indication_ph3_success_share_other_moa": 0.5}
    c = Claims()
    indication_track_record_claims(c, D, {"id": "OWN"}, {**part(*rows), "complete": False})
    assert c.items == []                                                      # only from a complete list


# --- auto-confirmation ----------------------------------------------------------------------------------------------
def test_auto_confirm_needs_two_independent_documents():
    one = {"id": "a", "origin": "llm", "verified": True, "confirmed": False, "doc_ids": ["sponsor:x"], "statement": "S."}
    two = {**one, "id": "b", "doc_ids": ["sponsor:x", "sponsor:y"]}
    unverified = {**two, "id": "c", "verified": False}
    assert auto_confirm([one, two, unverified], enabled=True) == ["b"]
    assert two["confirmed"] and "Confirmed automatically: 2 independent sources" in two["statement"]
    assert auto_confirm([dict(two, confirmed=False)], enabled=False) == []


# --- source failures --------------------------------------------------------------------------------------------------
def test_too_complicated_query_is_split(tmp_path):
    from backend.app.sources.ctgov import CTGov
    from backend.app.sources.http import CachedHTTP
    seen = []

    def handler(request):
        q = request.url.params["query.intr"]
        seen.append(q)
        if q.count(" OR ") >= 2:
            return httpx.Response(400, text="Error parsing query in Intervention / treatment: Too complicated query")
        return httpx.Response(200, json={"studies": []})
    ct = CTGov(CachedHTTP("ctgov", cache_root=tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler))))
    assert ct.trials_for_drugs(["a", "b", "c", "d", "e"]) == []
    accepted = [q for q in seen if q.count(" OR ") < 2]
    assert all(any(f'"{n}"' in q for q in accepted) for n in "abcde")      # every name was asked in an accepted query


def test_backoff_grows_and_is_capped():
    from backend.app.sources.http import backoff
    assert 1 <= backoff(0) <= 1.3 and 16 <= backoff(4) <= 20.8 and backoff(9) <= 26


def test_a_failed_query_is_tried_again(monkeypatch):
    from backend.app import collect as col
    calls = {"n": 0}

    def flaky(ot, d):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("SSL: UNEXPECTED_EOF_WHILE_READING")
        return {"count": 0, "rows": []}
    for name in ("pair_genetics", "disease_genetics", "target_drugs", "target_info"):
        monkeypatch.setattr(col, name, lambda *a, **k: {"count": 0, "rows": []})
    monkeypatch.setattr(col, "disease_drugs", flaky)

    class OT:
        def release(self):
            return "26.09"
    out = col.collect(OT(), "D1", "T")
    assert out["parts"]["disease_drugs"]["ok"] and out["parts"]["disease_drugs"]["retried"]


def test_failed_sources_travel_with_the_verdict():
    from backend.app.api import failed_sources
    out = {"collected": {"parts": {"a": {"ok": True}, "target_drugs": {"ok": False, "error": "network"}}},
           "sources_status": ["aact: skipped (AACT_DSN is not set)", "ctgov: failed (SSL)"]}
    assert failed_sources(out) == ["Open Targets target_drugs: network", "ctgov: failed (SSL)"]


# --- LLM ------------------------------------------------------------------------------------------------------------
def test_temperature_and_seed_are_sent_and_dropped_when_rejected(tmp_path, monkeypatch):
    from backend.app.llm import OpenAILLM
    monkeypatch.setenv("UNOBIO_LLM_BASE_URL", "https://gw.example")
    body = OpenAILLM(api_key="k", provider="gateway", cache_dir=tmp_path)._body("t", "s", "u", {"type": "object"})
    assert "temperature" not in body and "seed" not in body             # 2.4.1: opt-in (gateway 502 on refusal)
    monkeypatch.setenv("UNOBIO_LLM_TEMPERATURE", "0")
    monkeypatch.setenv("UNOBIO_LLM_SEED", "7")
    llm = OpenAILLM(api_key="k", provider="gateway", cache_dir=tmp_path)
    body = llm._body("t", "s", "u", {"type": "object"})
    assert body["temperature"] == 0 and body["seed"] == 7
    assert llm._adapt("Unsupported value: 'temperature' does not support 0") and llm.temperature is None
    assert llm._adapt("Unrecognized request argument supplied: seed") and llm.seed is None


# --- scorer through the pipeline: Insufficient detail --------------------------------------------------------------------
def test_insufficient_detail_names_the_gap():
    from backend.app.pipeline import score_claims
    c = Claims()
    c.add("genetic_support", "none", "No genetics.", "rule", [{"kind": "x"}])
    c.add("moa_clinical_precedent", "none", "No precedent.", "rule", [{"kind": "x"}])
    p = score_claims(c.items)
    v = p["result"]["verdict"]
    assert v["decision"] == "Insufficient evidence"
    assert {"no_mechanism_evidence", "no_asset_data"} <= set(v["insufficient"]["kinds"])
    assert any(d["verdict_to"] in ("Conditional", "Invest") for d in v["insufficient"]["would_decide"])


@pytest.mark.parametrize("rid", ["no_genetics_no_precedent", "indication_enrollment_risk", "me_too_differentiated"])
def test_absence_rules_are_notes(rid):
    from backend.app.scorer import load_config
    assert next(r for r in load_config().rules if r["id"] == rid)["tier"] == "note"


# --- 2.5 -------------------------------------------------------------------------------------------------------------
def test_a_met_phase3_and_an_early_safety_stop_are_not_efficacy_failures():
    from backend.app.translation import aact_failures, positive_ph3_drugs
    dis = {"id": "D1", "name": "coronary artery disease", "synonyms": []}
    row = lambda nct, drugs, status, why, p, stage="PHASE_3": {  # noqa: E731
        "nct_id": nct, "drugs": drugs, "stage": stage, "overall_status": status, "why_stopped": why,
        "mesh_terms": ["coronary artery disease"], "conditions": ["coronary artery disease"],
        "primary_analyses": [{"p_value": p, "non_inferiority": "Superiority"}]}
    tr = {"parts": {"aact": {"ok": True, "data": [
        row("NCT01252953", ["ANACETRAPIB"], "COMPLETED", None, "0.004"),             # REVEAL: met
        row("NCT00000002", ["ANACETRAPIB"], "COMPLETED", None, "0.40", "PHASE_2"),   # a small miss
        row("NCT01687998", ["EVACETRAPIB"], "TERMINATED", "Futility at interim analysis", "0.91"),
        row("NCT00000004", ["TANEZUMAB"], "TERMINATED", "FDA clinical hold for joint safety", "0.30")]}}}
    assert positive_ph3_drugs(tr, dis) == {"ANACETRAPIB"}
    assert set(aact_failures(tr, dis)) == {"ANACETRAPIB", "EVACETRAPIB"}       # tanezumab's safety stop is not one
    c = Claims()
    failed = trial_claims(c, [], {"labels": {}, "errors": []}, dis, {"symbol": "CETP", "action": "inhibit"},
                          aact_failures(tr, dis), approved_here=positive_ph3_drugs(tr, dis))
    assert failed == {"EVACETRAPIB"}


def test_a_single_source_failure_with_explicit_words_is_confirmed():
    base = {"origin": "llm", "verified": True, "confirmed": False, "doc_ids": ["sponsor:lilly"],
            "fact": "moa_failures_efficacy_ph23", "statement": "S."}
    yes = {**base, "id": "a", "quote": "terminated due to futility"}
    vague = {**base, "id": "b", "quote": "primary endpoint"}
    other = {**base, "id": "c", "fact": "class_target_engagement_human", "quote": "did not meet"}
    assert auto_confirm([yes, vague, other], enabled=True) == ["a"]
    assert "states the failure explicitly" in yes["statement"]


def test_two_approved_drugs_are_enough_for_crowding_from_an_incomplete_list():
    from backend.app.facts import target_drug_claims
    lab = lambda: [report("r", "", "", approved=True)]  # noqa: E731
    rows = [{"drug": {**drug("SECUKINUMAB", [["IL17A"]]), "drugType": "Antibody"}, "clinicalReports": lab()},
            {"drug": {**drug("IXEKIZUMAB", [["IL17A"]]), "drugType": "Antibody"}, "clinicalReports": lab()}]
    c = Claims()
    target_drug_claims(c, {**D, "therapeutic_areas": []}, {"id": "IL17A", "symbol": "IL17A", "action": "inhibit"},
                       {**part(*rows), "complete": False}, "inhibit")
    claim = next(x for x in c.items if x["fact"] == "approved_same_moa_count")
    assert claim["value"] == 2 and claim["statement"].startswith("At least 2")


def test_crowded_is_do_not_invest_with_its_own_reason_and_differentiation_lifts_it():
    from backend.app.pipeline import score_claims
    c = Claims()
    for f, v in (("approved_same_moa_count", 3), ("moa_clinical_precedent", "approved_same"),
                 ("genetic_support", "gwas")):
        c.add(f, v, "x.", "r", [{"kind": "x"}])
    v = score_claims(c.items)["result"]["verdict"]
    assert (v["decision"], v["grounds"]) == ("Do Not Invest", "crowded")
    c.add("differentiation_claim", "efficacy", "x.", "r", [{"kind": "x"}])
    assert score_claims(c.items)["result"]["verdict"]["decision"] != "Do Not Invest"

"""2.6: evidence without an LLM (backend/app/rules.py): stop reasons from Open Targets categories and words, trial
outcomes from PubMed abstracts. Offline."""
import pytest

from backend.app.rules import label_reason, label_stops, outcome_findings, positive_phase3_from_findings

AD = {"id": "MONDO_0004975", "name": "Alzheimer disease", "synonyms": ["Alzheimer's disease"]}


def labels(reason, cats=None):
    return {x["label"]: x for x in label_reason(reason, cats)}


@pytest.mark.parametrize("reason,cats,expect", [
    ("Futility at interim analysis", ["Negative"], {"efficacy"}),
    ("The study was terminated as it was unlikely to meet its primary endpoint", [], {"efficacy"}),
    ("Change in benefit-risk profile for individuals with early Alzheimer disease because of liver enzyme elevations",
     ["Negative"], {"safety"}),                                   # atabecestat: Negative category, safety words
    ("Slow recruitment", ["Insufficient_Enrollment"], {"enrollment"}),
    ("Business decision; not due to lack of efficacy.", ["Business_Administrative"], {"business"}),
    ("The DSMB recommended stopping the study", ["Negative"], {"efficacy"}),   # category alone
    ("See termination reason in detailed description.", ["No_Context"], {"unknown"}),
])
def test_stop_reasons_without_an_llm(reason, cats, expect):
    got = labels(reason, cats)
    assert set(got) == expect
    for x in got.values():
        assert x["verified"] and (x["quote"] in reason or x["label"] == "unknown")


def test_label_stops_has_the_llm_shape():
    out = label_stops([{"nct": "NCT1", "why_stopped": "futility", "ot_categories": ["Negative"]},
                       {"nct": "NCT2", "why_stopped": "", "ot_categories": []}])
    assert list(out["labels"]) == ["NCT1"] and out["errors"] == []
    assert out["labels"]["NCT1"][0] == {**out["labels"]["NCT1"][0], "label": "efficacy", "verified": True}


def doc(text, drug="LANABECESTAT", pmid="1"):
    return {"id": f"pmid:{pmid}", "kind": "pubmed", "drug": drug, "url": "u", "title": "t", "text": text}


FAILED = ("Lanabecestat in early Alzheimer's disease: two randomized phase 3 trials. Patients received placebo or "
          "lanabecestat. The trials were stopped early for futility. Lanabecestat did not meet its primary endpoint.")
MET = ("Phase 3 randomized placebo-controlled trial of lanabecestat in Alzheimer's disease. The study met its primary "
       "endpoint.")


def test_a_failed_trial_abstract_is_a_not_shown_finding():
    f = outcome_findings([doc(FAILED)], AD, ["LANABECESTAT"])
    assert [(x["result"], x["source"], x["verified"]) for x in f] == [("not_shown", "rules_pubmed", True)]
    assert f[0]["quote"] in FAILED


def test_a_met_phase3_abstract_is_shown_and_marks_a_positive_phase3():
    f = outcome_findings([doc(MET)], AD, ["LANABECESTAT"])
    assert [x["result"] for x in f] == ["shown"] and positive_phase3_from_findings(f) == {"LANABECESTAT"}


@pytest.mark.parametrize("text,drug", [
    (FAILED + " " + MET, "LANABECESTAT"),                                         # mixed: not decided
    ("In transgenic mice lanabecestat did not meet the primary endpoint in Alzheimer's disease.", "LANABECESTAT"),
    (FAILED, "VERUBECESTAT"),                                                    # the abstract is not about this drug
    (FAILED.replace("Alzheimer's disease", "Parkinson disease"), "LANABECESTAT"),  # another disease
])
def test_abstracts_that_do_not_decide_are_skipped(text, drug):
    assert outcome_findings([doc(text, drug=drug)], AD, [drug]) == []


def test_recorded_bace1_without_any_llm_is_do_not_invest(monkeypatch):
    """The recorded Alzheimer + BACE1 run, no LLM: Open Targets categories give two efficacy failures (lanabecestat,
    elenbecestat) and put atabecestat's liver stop under safety; the claims are structured, nothing waits."""
    monkeypatch.setenv("UNOBIO_RULES", "1")
    from backend.tests.test_step4 import live_run
    out = live_run("Alzheimer disease", "BACE1 inhibitor")
    by = {c["fact"]: c for c in out["claims"]}
    fail = by["moa_failures_efficacy_ph23"]
    assert fail["value"] == 2 and fail["origin"] == "structured" and "Atabecestat" not in fail["statement"]
    assert "Atabecestat" in by["moa_discontinued_safety_count"]["statement"]
    res = out["score"]["result"]
    assert res["verdict"]["decision"] == "Do Not Invest" and "mechanism_refuted" in [r["id"] for r in res["rules"]]
    assert out["score"]["pending"] == []


def test_no_llm_switch(monkeypatch):
    from backend.app import api
    monkeypatch.setenv("TEAM_API_KEY", "k")
    monkeypatch.setenv("UNOBIO_LLM_BASE_URL", "https://gw.example/v1")
    monkeypatch.setenv("UNOBIO_NO_LLM", "1")
    assert api.make_llm() is None


# --- 2.7 -------------------------------------------------------------------------------------------------------------
def test_a_met_biomarker_endpoint_does_not_clear_a_drug():
    """Evacetrapib lowered LDL-C in Phase 3 (p < 0.05) and failed on cardiovascular events: not a met program."""
    from backend.app.translation import clinical_primary_met, positive_ph3_drugs
    ldl = {"primary_analyses": [{"outcome": "Percent Change From Baseline in LDL-C", "p_value": "<0.001",
                                 "non_inferiority": "Superiority"}]}
    ldl["primary_analyses"][0]["p_value"] = 0.0001
    mace = {"primary_analyses": [{"outcome": "Time to first major coronary event", "p_value": 0.004,
                                  "non_inferiority": "Superiority"}]}
    assert not clinical_primary_met(ldl) and clinical_primary_met(mace)
    dis = {"id": "D", "name": "coronary artery disease", "synonyms": []}
    rows = [{**ldl, "nct_id": "NCT1", "drugs": ["EVACETRAPIB"], "stage": "PHASE_3", "mesh_terms": ["coronary artery disease"]},
            {**mace, "nct_id": "NCT2", "drugs": ["ANACETRAPIB"], "stage": "PHASE_3", "mesh_terms": ["coronary artery disease"]}]
    assert positive_ph3_drugs({"parts": {"aact": {"ok": True, "data": rows}}}, dis) == {"ANACETRAPIB"}


def test_a_report_with_no_disease_id_counts_when_the_drug_was_developed_for_the_disease():
    from backend.app.trials import stopped_trials
    drug_ = {"name": "EVACETRAPIB", "indications": {"rows": [{"disease": {"id": "D1"}}]},
             "mechanismsOfAction": {"rows": [{"actionType": "INHIBITOR", "targets": [{"id": "CETP"}]}]}}
    rep = {"id": "nct02260635", "trialOverallStatus": "TERMINATED", "trialWhyStopped": "insufficient efficacy",
           "clinicalStage": "PHASE_3", "diseases": []}
    col = {"parts": {"target_drugs": {"ok": True, "data": {"rows": [{"drug": drug_, "clinicalReports": [rep]}]}},
                     "disease_drugs": {"ok": True, "data": {"rows": []}}}}
    assert stopped_trials(col, "D1", "CETP", "inhibit")[0]["in_disease"] is True
    assert stopped_trials(col, "D2", "CETP", "inhibit")[0]["in_disease"] is False


def test_every_failed_drug_keeps_a_source_under_the_cap():
    from backend.app.trials import _claim_sources
    t = lambda n: {"nct": n, "url": "u", "sponsor": "s", "why_stopped": "w"}  # noqa: E731
    hits = [(t(f"NCT{i}"), {"quote": "q", "source": "rules"}, "ANACETRAPIB") for i in range(60)]
    hits.append((t("NCTX"), {"quote": "q", "source": "rules"}, "EVACETRAPIB"))
    assert ["EVACETRAPIB"] in [s["drugs"] for s in _claim_sources(hits)]


def test_outcome_trial_wording_is_a_failure():
    text = ("Evacetrapib in high-risk vascular disease: a randomized placebo-controlled phase 3 trial in patients with "
            "coronary artery disease. Evacetrapib did not reduce the rate of major adverse cardiovascular events.")
    f = outcome_findings([doc(text, drug="EVACETRAPIB")], {"name": "coronary artery disease"}, ["EVACETRAPIB"])
    assert [x["result"] for x in f] == ["not_shown"]


def test_the_opposite_direction_approved_here_is_do_not_invest(monkeypatch):
    """PCSK9 agonist for familial hypercholesterolemia: alirocumab, evolocumab, inclisiran inhibit PCSK9."""
    monkeypatch.setenv("UNOBIO_RULES", "1")
    from backend.tests.test_step4 import live_run
    out = live_run("familial hypercholesterolemia", "PCSK9 agonist")
    by = {c["fact"]: c for c in out["claims"]}
    assert by["opposite_direction_approved_count"]["value"] == 3
    v = out["score"]["result"]["verdict"]
    assert (v["decision"], v["grounds"]) == ("Do Not Invest", "opposite_direction")
    same_way = live_run("familial hypercholesterolemia", "anti-PCSK9 antibody")
    assert "opposite_direction_approved_count" not in {c["fact"] for c in same_way["claims"]}


def test_diagnose_script_runs_on_a_finished_run(tmp_path, monkeypatch):
    from backend.tests.test_step6 import client as make_client, start  # noqa: F401
    from backend.app import api
    from backend.tests import diagnose_pair
    from backend.tests.test_step6 import recorded_collect, LIVE
    from backend.app.opentargets import OpenTargets
    from fastapi.testclient import TestClient
    monkeypatch.setattr(api, "DB_FILE", tmp_path / "t.db")
    monkeypatch.setattr(api, "make_ot", lambda: OpenTargets(LIVE / "cache", offline=True))
    monkeypatch.setattr(api, "make_llm", lambda: None)
    monkeypatch.setattr("backend.app.pipeline.collect", recorded_collect)
    monkeypatch.setattr(diagnose_pair.Path, "write_text", lambda self, *a, **k: None)
    start(TestClient(api.app), disease="Alzheimer disease", target="BACE1 inhibitor")
    text = diagnose_pair.main("Alzheimer disease", "BACE1 inhibitor", "LANABECESTAT")
    assert "== Open Targets trial reports of the drug" in text and "LANABECESTAT" in text
    assert "moa_failures_efficacy_ph23" in text or "== Claims" in text


def test_a_single_refused_name_is_skipped_not_fatal(tmp_path):
    import httpx
    from backend.app.sources.ctgov import CTGov, searchable
    from backend.app.sources.http import CachedHTTP

    def handler(request):
        q = request.url.params["query.intr"]
        if "bad" in q:
            return httpx.Response(400, text="Error parsing query in Intervention / treatment: Too complicated query")
        return httpx.Response(200, json={"studies": []})
    ct = CTGov(CachedHTTP("ctgov", cache_root=tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler))))
    assert ct.trials_for_drugs(["imatinib", "bad name", "nilotinib"]) == [] and ct.skipped == ["bad name"]
    assert not searchable('gleevec (imatinib) "tablets"') and not searchable("x and y") and searchable("imatinib")


# --- 2.8: failures registered under a broader disease (CETP: ACCELERATE is "cardiovascular diseases") ---------------
CAD = {"id": "MONDO_0005010", "name": "coronary artery disorder", "synonyms": ["coronary artery disease"],
       "broader": [{"id": "MONDO_0004995", "name": "cardiovascular disease"}]}


def test_accelerate_counts_for_coronary_artery_disease_through_the_broader_disease():
    """The rows the diagnose script showed on 10.10.2026."""
    from backend.app import translation as tl
    accelerate = {"nct_id": "NCT01687998", "stage": "PHASE_3", "overall_status": "TERMINATED",
                  "why_stopped": "Study termination due to insufficient efficacy.", "drugs": ["EVACETRAPIB"],
                  "conditions": ["cardiovascular diseases"], "mesh_terms": ["cardiovascular diseases"],
                  "primary_analyses": [{"outcome": "Number of Participants With Composite Primary Endpoint of CV Death, "
                                                   "MI, Stroke", "p_value": "0.9054",
                                        "non_inferiority": "SUPERIORITY_OR_OTHER_LEGACY"}]}
    tr = {"parts": {"aact": {"ok": True, "data": [accelerate]}}}
    assert list(tl.aact_failures(tr, CAD)) == ["EVACETRAPIB"]
    assert tl.aact_failures(tr, {**CAD, "broader": []}) == {}                  # before 2.8: not in the disease
    assert tl.positive_ph3_drugs(tr, CAD) == set()


def test_an_unmapped_report_counts_when_the_drug_is_indicated_for_a_broader_disease():
    from backend.app.trials import stopped_trials
    drug_ = {"name": "EVACETRAPIB", "indications": {"rows": [{"disease": {"id": "MONDO_0004995"}}]},
             "mechanismsOfAction": {"rows": [{"actionType": "INHIBITOR", "targets": [{"id": "CETP"}]}]}}
    rep = {"id": "nct02260635", "trialOverallStatus": "TERMINATED", "trialWhyStopped": "insufficient efficacy",
           "clinicalStage": "PHASE_3", "diseases": [], "trialStopReasonCategories": ["Negative"]}
    col = {"parts": {"target_drugs": {"ok": True, "data": {"rows": [{"drug": drug_, "clinicalReports": [rep]}]}},
                     "disease_drugs": {"ok": True, "data": {"rows": []}}}}
    assert stopped_trials(col, CAD["id"], "CETP", "inhibit", {"MONDO_0004995"})[0]["in_disease"] is True
    assert stopped_trials(col, CAD["id"], "CETP", "inhibit")[0]["in_disease"] is False


def test_lineage_drops_roots_and_therapeutic_areas():
    from backend.app.opentargets import OpenTargets

    class OT(OpenTargets):
        def __init__(self):
            pass

        def query(self, name, q, v):
            return {"disease": {"id": "MONDO_0005010", "therapeuticAreas": [{"id": "EFO_0000319"}], "parents": [
                {"id": "MONDO_0005267", "name": "heart disorder", "parents": [
                    {"id": "MONDO_0004995", "name": "cardiovascular disorder"}, {"id": "EFO_0000319", "name": "x"}]},
                {"id": "MONDO_0000001", "name": "disease", "parents": []}]}}
    assert [x["id"] for x in OT().lineage("MONDO_0005010")] == ["MONDO_0005267", "MONDO_0004995"]

    class Broken(OT):
        def query(self, *a):
            raise RuntimeError("offline")
    assert Broken().lineage("X") == []

"""A Phase 3 that failed but is registered as "Completed" with descriptive results only (no stop reason, no p-value)
is found through PubMed by its NCT ID. Huntington + HTT antisense was Invest because tominersen's GENERATION HD1 looks
exactly like that in ClinicalTrials.gov (checked on 9 October: COMPLETED, whyStopped empty, primary analyses empty).

The registry study and the abstract below are SYNTHETIC (invented NCT ID and wording), shaped like that record.
Open Targets data is the recorded Huntington run (fixtures/live)."""
import copy
import json
import re
from pathlib import Path

import pytest

from backend.app import translation as tl
from backend.app.normalize import normalize
from backend.app.opentargets import OpenTargets
from backend.app.pipeline import run, score_claims
from backend.app.sources import ctgov

LIVE = Path(__file__).parent / "fixtures" / "live"
NCT = "NCT09999911"
STUDY = {
    "protocolSection": {
        "identificationModule": {"nctId": NCT, "briefTitle": "Synthetic Phase 3 of tominersen in Huntington disease"},
        "statusModule": {"overallStatus": "COMPLETED", "resultsFirstPostDateStruct": {"date": "2023-05-01"}},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Synthetic Pharma"}},
        "conditionsModule": {"conditions": ["Huntingtons Disease"]},
        "designModule": {"phases": ["PHASE3"], "enrollmentInfo": {"count": 791}},
        "armsInterventionsModule": {"interventions": [{"type": "DRUG", "name": "Tominersen"},
                                                      {"type": "DRUG", "name": "Placebo"}]},
        "outcomesModule": {"primaryOutcomes": [{"measure": "Change From Baseline in cUHDRS"}]}},
    "derivedSection": {"conditionBrowseModule": {"meshes": [{"term": "Chorea"}]}},
    "resultsSection": {"outcomeMeasuresModule": {"outcomeMeasures": [
        {"type": "PRIMARY", "title": "Change From Baseline in cUHDRS", "analyses": []}]}},   # descriptive only
    "hasResults": True,
}
ABSTRACT = (f"SYNTHETIC TEST ABSTRACT. In this phase 3 trial ({NCT}) of tominersen in adults with manifest Huntington "
            "disease, dosing was stopped early after review by an independent data monitoring committee. The primary "
            "end point, change in cUHDRS, was not met.")


class Registry:
    """ClinicalTrials.gov stand-in: the same row shape as AACT / ctgov.CTGov."""
    ready, offline, calls = True, False, []

    def trials_for_drugs(self, names):
        row = ctgov.study_row(STUDY, {n.lower() for n in names})
        return [row] if row else []


class PubMed:
    def __init__(self):
        self.terms = []

    def articles(self, term, retmax=5):
        self.terms.append(term)
        if NCT in term:
            return [{"pmid": "999", "title": "Synthetic tominersen phase 3", "abstract": ABSTRACT, "year": "2023",
                     "first_author": "Synthetic", "retracted": False, "url": "https://pubmed.ncbi.nlm.nih.gov/999/"}]
        return []                                         # the drug-name searches find nothing about the outcome


class Sources:
    def __init__(self):
        self.openfda = self.uniprot = None
        self.pubmed, self.aact = PubMed(), Registry()

    def calls(self):
        return []


class ReadingLLM:
    """Reads the abstract like an honest model: clinical benefit not shown, quoting the sentence; agrees on checks."""
    model, calls = "reading", []

    def complete_json(self, task, system, user, schema):
        if task == "extract_translation":
            out = []
            for d in json.loads(user)["documents"]:
                m = re.search(r"The primary end point, change in cUHDRS, was not met", d["text"])
                out.append({"id": d["id"], "findings": [] if not m else [
                    {"drug": "TOMINERSEN", "link": "clinical_benefit", "result": "not_shown", "species": "human",
                     "in_disease": True, "quote": m.group(0)}]})
            return {"documents": out}
        if task.startswith("check"):
            return {"items": [{"id": x["id"], "supports": True} for x in json.loads(user)]}
        return {"trials": []}


@pytest.fixture(scope="module")
def htt():
    ot = OpenTargets(LIVE / "cache", offline=True)
    n = normalize(ot, "Huntington disease", "HTT antisense oligonucleotide")
    collected = json.loads((LIVE / "runs" / f"{n['disease']['id']}__{n['target']['id']}.json").read_text())
    sources = Sources()
    out = run(ot, "Huntington disease", "HTT antisense oligonucleotide", collected=collected, llm=ReadingLLM(),
              sources=sources)
    return out, sources


def test_the_registry_row_has_nothing_the_code_can_judge():
    row = dict(ctgov.study_row(STUDY, {"tominersen"}), drugs=["TOMINERSEN"])
    disease = {"name": "Huntington disease", "synonyms": ["Huntingtons disease"]}   # as in Open Targets
    assert tl.primary_not_met(row) is None and not row["why_stopped"]
    assert tl.aact_failures({"parts": {"aact": {"ok": True, "data": [row]}}}, disease) == {}
    assert [r["nct_id"] for r in tl.unknown_result_trials([row], disease)] == [NCT]
    judged = copy.deepcopy(row)
    judged["primary_analyses"] = [{"outcome": "x", "p_value": "0.41", "non_inferiority": "SUPERIORITY"}]
    assert tl.unknown_result_trials([judged], disease) == []          # the p-value decides; no lookup needed


def test_the_trial_is_looked_up_by_its_nct_id(htt):
    out, sources = htt
    assert f'"{NCT}"[si] OR "{NCT}"[tiab]' in sources.pubmed.terms
    part = out["collected"]["translation"]["parts"]["pubmed_nct"]
    assert part["ok"] and part["data"][0]["nct"] == NCT and part["data"][0]["drug"] == "TOMINERSEN"


def test_the_failure_reaches_the_verdict_after_a_human_confirms(htt):
    out, _ = htt
    c = next(c for c in out["claims"] if c["fact"] == "moa_failures_efficacy_ph23")
    assert c["origin"] == "llm" and c["value"] == 1 and "was not met" in c["quote"]
    assert "pubmed.ncbi.nlm.nih.gov/999" in json.dumps(c["sources"])
    pending = {p["fact"] for p in out["score"]["pending"]}
    assert "moa_failures_efficacy_ph23" in pending                    # an LLM claim waits for a human (rule 7)
    confirmed = [dict(x, confirmed=True) if x["fact"] == "moa_failures_efficacy_ph23" else x for x in out["claims"]]
    assert score_claims(confirmed)["result"]["verdict"]["decision"] != "Invest"

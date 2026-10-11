"""ClinicalTrials.gov API v2 fallback for AACT: same rows, so registry failures reach the claims without an AACT
account. The study below is SYNTHETIC (API v2 field layout, invented values), modelled on a completed Phase 3 with
posted primary analyses that missed."""
from backend.app import translation as tl
from backend.app.sources import Sources, ctgov
from backend.app.sources.aact import AACT

STUDY = {
    "protocolSection": {
        "identificationModule": {"nctId": "NCT09999901", "briefTitle": "Synthetic Phase 3 of drug X in Huntington disease"},
        "statusModule": {"overallStatus": "COMPLETED", "startDateStruct": {"date": "2019-01"},
                         "resultsFirstPostDateStruct": {"date": "2023-05-01"}},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Synthetic Pharma"}},
        "conditionsModule": {"conditions": ["Huntington Disease"]},
        "designModule": {"phases": ["PHASE3"], "enrollmentInfo": {"count": 791}},
        "armsInterventionsModule": {"interventions": [
            {"type": "DRUG", "name": "Tominersen", "otherNames": ["RO7234292", "RG6042"]},
            {"type": "DRUG", "name": "Placebo"}]},
        "outcomesModule": {"primaryOutcomes": [{"measure": "Change from baseline in cUHDRS"}],
                           "secondaryOutcomes": [{"measure": "Change from baseline in CSF mHTT protein levels"}]}},
    "derivedSection": {"conditionBrowseModule": {"meshes": [{"id": "D006816", "term": "Huntington Disease"}],
                                                 "ancestors": [{"id": "D020820", "term": "Dyskinesias"}]}},
    "resultsSection": {"outcomeMeasuresModule": {"outcomeMeasures": [
        {"type": "PRIMARY", "title": "Change from baseline in cUHDRS",
         "analyses": [{"pValue": "0.41", "statisticalMethod": "MMRM", "nonInferiorityType": "SUPERIORITY"}]},
        {"type": "SECONDARY", "title": "CSF mHTT", "analyses": [{"pValue": "<0.001"}]}]}},
    "hasResults": True,
}
OTHER = {"protocolSection": {"identificationModule": {"nctId": "NCT09999902"},
                             "armsInterventionsModule": {"interventions": [{"name": "Tetrabenazine"}]}}}


class FakeHTTP:
    offline = False

    def __init__(self):
        self.calls, self.params = [], []

    def get(self, url, params):
        self.params.append(dict(params))
        if "pageToken" not in params:
            return {"studies": [OTHER], "nextPageToken": "p2"}
        return {"studies": [STUDY]}


def test_study_becomes_an_aact_shaped_row():
    r = ctgov.study_row(STUDY, {"tominersen", "ro7234292"})
    assert r["nct_id"] == "NCT09999901" and r["stage"] == "PHASE_3" and r["overall_status"] == "COMPLETED"
    assert r["matched"] == ["ro7234292", "tominersen"] and "huntington disease" in r["mesh_terms"]
    assert r["primary_analyses"] == [{"outcome": "Change from baseline in cUHDRS", "p_value": "0.41",
                                      "non_inferiority": "SUPERIORITY", "method": "MMRM"}]
    assert {"type": "secondary", "measure": "Change from baseline in CSF mHTT protein levels"} in r["design_outcomes"]
    assert ctgov.study_row(OTHER, {"tominersen"}) is None          # not an intervention of the trial


def test_pages_are_followed_and_names_quoted():
    http = FakeHTTP()
    rows = ctgov.CTGov(http).trials_for_drugs(["Tominersen", "RO7234292"])
    assert [r["nct_id"] for r in rows] == ["NCT09999901"]
    assert http.params[0]["query.intr"] == '"ro7234292" OR "tominersen"' and http.params[1]["pageToken"] == "p2"


def test_registry_failure_reaches_the_failure_count():
    row = dict(ctgov.study_row(STUDY, {"tominersen"}), drugs=["TOMINERSEN"])
    tr = {"parts": {"aact": {"ok": True, "data": [row]}}}
    disease = {"name": "Huntington disease", "synonyms": []}
    fails = tl.aact_failures(tr, disease)
    assert list(fails) == ["TOMINERSEN"] and "p = 0.41" in fails["TOMINERSEN"][0][0]["why_stopped"]
    assert "TOMINERSEN" in tl.ph23_drugs_in_disease({"parts": {}}, tr, disease, [{"key": "TOMINERSEN"}])


def test_ctgov_is_used_without_an_aact_account(monkeypatch):
    monkeypatch.delenv("AACT_DSN", raising=False)
    assert isinstance(Sources.trials(True, False), ctgov.CTGov)
    monkeypatch.setenv("UNOBIO_CTGOV", "0")
    assert isinstance(Sources.trials(True, False), AACT)
    monkeypatch.delenv("UNOBIO_CTGOV")
    monkeypatch.setenv("AACT_DSN", "postgresql://x")
    assert isinstance(Sources.trials(True, False), AACT)

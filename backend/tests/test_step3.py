"""Step 3 tests on made-up responses: pagination, completeness, one failing query does not stop the others."""
import json

import httpx

from backend.app.collect import collect, save, summary
from backend.app.opentargets import OpenTargets

DID, TID = "MONDO_0004975", "ENSG00000186318"


def make_ot(tmp_path, handler):
    return OpenTargets(tmp_path / "cache", http=httpx.Client(transport=httpx.MockTransport(handler)))


def answer(pages=2, fail=(), count=None):
    """Fake Open Targets: genetics in `pages` pages of one row each; queries named in `fail` return GraphQL errors."""
    def handler(request):
        b = json.loads(request.content)
        name, v = b["operationName"], b["variables"]
        if name in fail:
            return httpx.Response(400, json={"errors": [{"message": f"Cannot query field on {name}"}]})
        if name == "Meta":
            return httpx.Response(200, json={"data": {"meta": {"dataVersion": {"year": "26", "month": "09"}}}})
        if name == "PairGenetics":
            page = int(v["cursor"] or 0)
            nxt = str(page + 1) if page + 1 < pages else None
            return httpx.Response(200, json={"data": {"disease": {"id": DID, "evidences": {
                "count": pages if count is None else count, "cursor": nxt,
                "rows": [{"id": f"e{page}", "datasourceId": "gwas_credible_sets", "score": 0.7}]}}}})
        if name == "DiseaseGenetics":
            return httpx.Response(200, json={"data": {"disease": {"id": DID, "associatedTargets": {
                "count": 1, "rows": [{"target": {"id": TID, "approvedSymbol": "BACE1"}, "score": 0.5,
                                      "datatypeScores": [{"id": "genetic_association", "score": 0.4}]}]}}}})
        if name in ("TargetDrugs", "DiseaseDrugs"):
            root = "target" if name == "TargetDrugs" else "disease"
            return httpx.Response(200, json={"data": {root: {"drugAndClinicalCandidates": {"count": 1, "rows": [{
                "id": "x", "maxClinicalStage": "PHASE_3",
                "drug": {"name": "VERUBECESTAT", "mechanismsOfAction": {"rows": [{"actionType": "INHIBITOR"}]}},
                "clinicalReports": [{"id": "NCT01739348", "trialOverallStatus": "TERMINATED",
                                     "trialWhyStopped": "futility"}]}]}}}})
        if name == "TargetInfo":
            return httpx.Response(200, json={"data": {"target": {"id": TID, "isEssential": False,
                                                                 "safetyLiabilities": []}}})
        raise AssertionError(name)
    return handler


def test_all_pages_are_collected_and_marked_complete(tmp_path):
    out = collect(make_ot(tmp_path, answer(pages=3)), DID, TID)
    gen = out["parts"]["pair_genetics"]
    assert gen["ok"] and gen["complete"] and [r["id"] for r in gen["data"]["rows"]] == ["e0", "e1", "e2"]
    assert all(p["ok"] for p in out["parts"].values()) and out["ot_release"] == "26.09"


def test_fewer_rows_than_count_is_incomplete(tmp_path):
    out = collect(make_ot(tmp_path, answer(pages=1, count=5)), DID, TID)
    assert out["parts"]["pair_genetics"]["ok"] and not out["parts"]["pair_genetics"]["complete"]


def test_one_failing_query_keeps_the_others(tmp_path):
    out = collect(make_ot(tmp_path, answer(fail={"TargetDrugs", "Meta"})), DID, TID)
    assert not out["parts"]["target_drugs"]["ok"] and "Cannot query field" in out["parts"]["target_drugs"]["error"]
    assert out["parts"]["disease_drugs"]["ok"] and out["parts"]["pair_genetics"]["ok"] and out["ot_release"] is None
    text = summary(out)                                        # the summary shows failures without crashing
    assert "[target_drugs] FAILED" in text and "futility" in text


def test_result_is_saved_as_json(tmp_path):
    out = collect(make_ot(tmp_path, answer()), DID, TID)
    path = save(out, tmp_path / "runs")
    assert path.name == f"{DID}__{TID}.json" and json.loads(path.read_text())["parts"]["target_info"]["complete"]

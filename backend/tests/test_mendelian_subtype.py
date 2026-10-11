"""2.3: Mendelian evidence that Open Targets returns only for a subtype of the disease (indirect evidence: each row
names the more specific disease it is for) is `mendelian_subtype` (+1), not `mendelian` (+2).

The atrial fibrillation rows are shaped like the live KCNJ5 run of 10 October (one Orphanet record for a descendant
disease); the subtype ID and name here are TEST values, not a claim about the ontology. Huntington uses the recorded
Open Targets rows (fixtures/live): direct records plus records for juvenile Huntington disease."""
import json
from pathlib import Path

from backend.app.facts import Claims, genetics_claims
from backend.app.pipeline import score_claims
from backend.app.report import build_report, check_paragraph

LIVE = Path(__file__).parent / "fixtures" / "live"
AF = {"id": "MONDO_0004981", "name": "atrial fibrillation"}
KCNJ5 = {"id": "ENSG00000120457", "symbol": "KCNJ5"}
SUBTYPE = {"id": "MONDO_9999901", "name": "familial atrial fibrillation (test subtype)"}
DISEASE_GEN = {"ok": True, "complete": True, "data": {"rows": [
    {"target": {"approvedSymbol": "SCN5A"}, "datatypeScores": [{"id": "genetic_association", "score": 0.5}]}]}}


def row(source, disease, i="r1", **kw):
    return {"id": i, "datasourceId": source, "score": 1, "clinicalSignificances": kw.get("sig", []),
            "disease": disease}


def genetics(rows, disease=AF, target=KCNJ5):
    c = Claims()
    genetics_claims(c, disease, target, {"ok": True, "complete": True, "data": {"rows": rows}}, DISEASE_GEN)
    return next(x for x in c.items if x["fact"] == "genetic_support")


def human_genetics_points(claim):
    res = score_claims([dict(claim, verified=None, confirmed=None)])["result"]
    item = next(i for i in res["scorecard"] if i["id"] == "human_genetics")
    return item["color"], item["points"], res


def test_direct_mendelian_evidence_is_mendelian_plus_two():
    g = genetics([row("orphanet", AF), row("clingen", AF, "r2")])
    assert g["value"] == "mendelian" and "Mendelian genetic evidence for atrial fibrillation" in g["statement"]
    assert human_genetics_points(g)[:2] == ("G", 2)


def test_subtype_only_is_mendelian_subtype_plus_one_named_from_the_source():
    g = genetics([row("orphanet", SUBTYPE)])
    assert g["value"] == "mendelian_subtype"
    assert "Mendelian genetics in a rare subtype (familial atrial fibrillation (test subtype))" in g["statement"]
    assert "not in atrial fibrillation itself" in g["statement"] and "(+1)" in g["statement"]
    color, points, res = human_genetics_points(g)
    assert (color, points) == ("G", 1)
    assert res["score"]["pos"] == 1                                    # was 2 (and Invest) before 2.3


def test_direct_evidence_is_not_lowered_by_extra_subtype_records():
    c = json.loads((LIVE / "runs" / "MONDO_0007739__ENSG00000197386.json").read_text())
    rows = c["parts"]["pair_genetics"]["data"]["rows"]
    assert {r["disease"]["name"] for r in rows if r["datasourceId"] == "orphanet"} == \
        {"Huntington disease", "juvenile Huntington disease"}           # both kinds are really there
    hd = genetics(rows, {"id": "MONDO_0007739", "name": "Huntington disease"},
                  {"id": "ENSG00000197386", "symbol": "HTT"})
    assert hd["value"] == "mendelian" and human_genetics_points(hd)[:2] == ("G", 2)


def test_a_record_that_names_no_disease_is_not_called_a_subtype():
    g = genetics([{"id": "r1", "datasourceId": "orphanet", "score": 1, "clinicalSignificances": []}])
    assert g["value"] == "mendelian" and "cannot be told apart from a subtype" in g["statement"]
    g = genetics([row("orphanet", {"id": "MONDO_9999902"})])           # a subtype ID without a name
    assert g["value"] == "mendelian_subtype" and "unnamed, MONDO_9999902" in g["statement"]


def test_other_genetic_classes_keep_their_behaviour():
    gwas = genetics([{"id": "g", "datasourceId": "gwas_credible_sets", "score": 0.7, "clinicalSignificances": [],
                      "disease": SUBTYPE}])
    assert gwas["value"] == "gwas" and human_genetics_points(gwas)[:2] == ("G", 1)
    som = genetics([{"id": "s", "datasourceId": "intogen", "score": 1, "clinicalSignificances": [], "disease": AF}])
    assert som["value"] == "somatic_driver"
    none = genetics([{"id": "x", "datasourceId": "gwas_credible_sets", "score": 0.1, "clinicalSignificances": [],
                      "disease": AF}])
    assert none["value"] == "none"


class OverstatingWriter:
    """Writes the genetics as Mendelian for the disease itself."""
    model, calls = "overstating", []

    def complete_json(self, task, system, user, schema):
        return {"sections": [{"id": "scientific_thesis", "paragraphs": [
            {"text": "KCNJ5 has Mendelian genetic support for atrial fibrillation.", "kind": "inference",
             "claim_ids": ["clm_1"]}]}]}


def test_memo_names_the_subtype_and_does_not_overstate_it():
    g = dict(genetics([row("orphanet", SUBTYPE)]), id="clm_1")
    payload = score_claims([dict(g, verified=None, confirmed=None)])
    score = {"version": 1, "payload": payload}
    run = {"id": "run_test", "normalized": {"disease": AF, "target": {**KCNJ5, "raw": "KCNJ5"}}}
    rep = build_report(run, [g], score, {"clm_1": "used"}, OverstatingWriter(), mechanism=None)
    thesis = next(s for s in rep["sections"] if s["id"] == "scientific_thesis")
    first = thesis["paragraphs"][0]["text"]
    assert first.startswith("Genetics: KCNJ5: Mendelian genetics in a rare subtype (familial atrial fibrillation")
    assert not any("Mendelian genetic support for atrial fibrillation" in p["text"] for p in thesis["paragraphs"])
    assert any("calls Mendelian evidence for a subtype" in i for i in rep["llm"]["issues"])
    say = {"text": "Mendelian genetics in a rare subtype supports the target.", "kind": "inference",
           "claim_ids": ["clm_1"]}
    assert check_paragraph(say, {"clm_1": g}, rep["decision"], "mendelian_subtype") is None

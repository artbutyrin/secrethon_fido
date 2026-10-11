"""The live sample is stratified, reproducible, and judged against the known outcome (no network here)."""
import json
from collections import Counter

from backend.tests.live_sample import TRUTH, judge, report, sample


def test_fifteen_pairs_five_per_group_same_seed_same_pairs():
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    s = sample(truth, 15, seed=9)
    assert Counter(t["group"] for t in s) == {"failed_ph3": 5, "failed_ph2": 5, "launched": 5}
    assert s == sample(truth, 15, seed=9) and s != sample(truth, 15, seed=1)


def test_misses_are_named_and_counted():
    base = {"status": "done", "pluses": 0, "minuses": 0, "seconds": 1, "tokens": 10, "genetic_support": "none",
            "genetics": "none", "target": "T"}
    rows = [{**base, "group": "failed_ph3", "disease": "D", "decision": "Invest", "grounds": "positive", "pluses": 2,
             "genetic_support": "gwas", "genetics": "gwas", "run_id": "r1", "errors": {"429 busy": 1}},
            {**base, "group": "launched", "disease": "E", "decision": "Insufficient evidence",
             "grounds": "insufficient_evidence", "run_id": "r2"},
            {**base, "group": "launched", "disease": "F", "decision": "Do Not Invest", "grounds": "outweighed",
             "minuses": 1, "run_id": "r3"}]
    assert [judge(r) for r in rows] == ["FALSE INVEST", "ok", "FALSE KILL"]   # no call is not a false kill
    text = report(rows, 9, "now", 60)
    assert "| False Invest (failed pair rated Invest) | 1 of 1 |" in text
    assert "| False kill (launched pair rated Do Not Invest) | 1 of 2 |" in text
    assert "| Insufficient evidence (no call either way) | 1 of 3 |" in text and "429 busy: 1" in text
    assert "| launched | 0 | 0 | 1 | 1 |" in text


# --- selection: the inclusion criteria are checked before the sample is cut ------------------------------------------
from backend.tests.live_sample import candidates, select                      # noqa: E402
from backend.tests.test_step2 import FakeOT, hit                             # noqa: E402

LOST_ON_10_OCTOBER = {"Colorectal Neoplasms", "Kidney Failure, Chronic", "Arthritis, Rheumatoid",
                      "Neuralgia, Postherpetic", "Carcinoma, Non-Small-Cell Lung"}


def test_seed_9_keeps_the_pairs_of_the_10_october_run_first():
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    first = sample(truth, 15, seed=9)
    cand = candidates(truth, 15, seed=9)
    for g in ("failed_ph3", "failed_ph2", "launched"):
        assert cand[g][:5] == [t for t in first if t["group"] == g]
        assert len(cand[g]) == len({(t["disease"], t["target"]) for t in truth if t["group"] == g})
    assert LOST_ON_10_OCTOBER <= {t["disease"] for t in first}


class SampleOT(FakeOT):
    """Every target resolves by symbol; diseases answer like Open Targets did, natural order included."""

    def search(self, text, entity):
        if entity == "target":
            return [hit(f"ENSG_{text}", text, 100.0, "target")]
        return super().search(text, entity)

    def target(self, i):
        sym = i.removeprefix("ENSG_")
        return {"id": i, "approvedSymbol": sym, "approvedName": sym, "biotype": "protein_coding", "synonyms": []}


def disease(i, name, mesh=None, synonyms=()):
    return {"id": i, "name": name, "dbXRefs": [f"MESH:{mesh}"] if mesh else [], "therapeuticAreas": [],
            "synonyms": [{"relation": "hasExactSynonym", "terms": list(synonyms)}] if synonyms else []}


def test_mesh_named_pairs_are_kept_wrong_entities_and_duplicates_are_not():
    D = {d["id"]: d for d in (
        disease("EFO_0009443", "postherpetic neuralgia", "D051474"),
        disease("MONDO_0005335", "colorectal neoplasm"),                                  # no MeSH xref: name decides
        disease("EFO_0003884", "chronic kidney disease", "D007676", ["chronic kidney failure"]),
        disease("EFO_0000685", "rheumatoid arthritis", "D001172"),
        disease("EFO_0003060", "non-small cell lung carcinoma", "D002289"),
        disease("EFO_0000384", "Crohn disease", "D003424"),
        disease("MONDO_0004975", "Alzheimer disease", "D000544"))}
    hits = {
        ("Postherpetic Neuralgia", "disease"): [hit("EFO_0009443", "postherpetic neuralgia", 500.0)],
        ("Colorectal Neoplasms", "disease"): [hit("MONDO_0005335", "colorectal neoplasm", 708.0),
                                              hit("MONDO_0021444", "benign neoplasm of large intestine", 393.0)],
        ("Chronic Kidney Failure", "disease"): [hit("EFO_0003884", "chronic kidney disease", 400.0)],
        ("Rheumatoid Arthritis", "disease"): [hit("EFO_0000685", "rheumatoid arthritis", 400.0)],
        ("Non-Small-Cell Lung Carcinoma", "disease"): [hit("EFO_0003060", "non-small cell lung carcinoma", 400.0)],
        ("Crohn Disease", "disease"): [hit("EFO_0000384", "Crohn disease", 400.0)],
        ("Crohn's disease", "disease"): [hit("EFO_0000384", "Crohn disease", 400.0)],
        ("Dementia", "disease"): [hit("MONDO_0004975", "Alzheimer disease", 900.0), hit("X", "x", 10.0)]}
    T = [{"group": "failed_ph3", "disease": "Colorectal Neoplasms", "target": "POLB", "mesh_id": "D015179"},
         {"group": "failed_ph3", "disease": "Crohn Disease", "target": "MMP9", "mesh_id": "D003424"},
         {"group": "failed_ph3", "disease": "Crohn's disease", "target": "MMP9", "mesh_id": "D003424"},   # same pair
         {"group": "failed_ph3", "disease": "Dementia", "target": "APP", "mesh_id": "D003704"},          # wrong entity
         {"group": "failed_ph2", "disease": "Kidney Failure, Chronic", "target": "ACVR2A", "mesh_id": "D007676"},
         {"group": "failed_ph2", "disease": "Arthritis, Rheumatoid", "target": "GSK3B", "mesh_id": "D001172"},
         {"group": "launched", "disease": "Neuralgia, Postherpetic", "target": "TRPV1", "mesh_id": "D051474"},
         {"group": "launched", "disease": "Carcinoma, Non-Small-Cell Lung", "target": "ROS1", "mesh_id": "D002289"}]
    picked, dropped = select(SampleOT(hits, D), T, n=9, seed=1)
    names = {t["disease"] for t in picked}
    assert LOST_ON_10_OCTOBER <= names                                  # all five MeSH-named pairs now count
    assert {t["disease"]: t["reason"][:25] for t in dropped} == {
        "Crohn's disease": "duplicate of an earlier p", "Dementia": "resolved to MONDO_0004975"}
    assert all(t["disease_id"] and t["target_id"] for t in picked)      # the run uses the checked entity


def test_a_source_error_drops_one_pair_not_the_sample():
    class Broken(SampleOT):
        def search(self, text, entity):
            if text.startswith("Colorectal"):
                raise RuntimeError("network error")
            return super().search(text, entity)
    D = {"EFO_0000384": disease("EFO_0000384", "Crohn disease", "D003424")}
    T = [{"group": "failed_ph3", "disease": "Colorectal Neoplasms", "target": "POLB", "mesh_id": "D015179"},
         {"group": "failed_ph3", "disease": "Crohn Disease", "target": "MMP9", "mesh_id": "D003424"}]
    picked, dropped = select(Broken({("Crohn Disease", "disease"): [hit("EFO_0000384", "Crohn disease", 400.0)]}, D),
                             T, n=3, seed=1)
    assert [t["disease"] for t in picked] == ["Crohn Disease"] and dropped[0]["reason"].startswith("error:")

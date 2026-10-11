"""Step 2 tests. The Open Targets responses here are made up: they test the resolution rules, not the live API.
Live checks: run step2_normalize.py; its saved responses in data/cache/ become regression fixtures."""
import json

import httpx
import pytest

from backend.app.mechanism import parse_mechanism
from backend.app.normalize import key, normalize, resolve_disease, resolve_target
from backend.app.opentargets import OpenTargets, OpenTargetsError, cache_key


class FakeOT:
    """Same interface as OpenTargets, answers from dictionaries."""

    def __init__(self, hits=None, diseases=None, targets=None):
        self.hits, self.diseases, self.targets = hits or {}, diseases or {}, targets or {}
        self.calls = []

    def search(self, text, entity):
        return self.hits.get((text, entity), [])

    def disease(self, i):
        return self.diseases.get(i)

    def target(self, i):
        return self.targets.get(i)

    def release(self):
        return "26.09"


def hit(i, name, score, entity="disease"):
    return {"id": i, "name": name, "entity": entity, "description": None, "score": score}


AD = {"id": "MONDO_0004975", "name": "Alzheimer disease", "dbXRefs": ["MESH:D000544"],
      "therapeuticAreas": [{"id": "EFO_0000618", "name": "nervous system disease"}],
      "synonyms": [{"relation": "hasExactSynonym", "terms": ["Alzheimer's dementia"]}]}
EOAD = {"id": "MONDO_0011913", "name": "early-onset Alzheimer disease", "dbXRefs": ["Orphanet:1020"],
        "therapeuticAreas": [], "synonyms": [{"relation": "hasRelatedSynonym", "terms": ["Alzheimer's dementia"]}]}
BACE1 = {"id": "ENSG00000186318", "approvedSymbol": "BACE1", "approvedName": "beta-secretase 1",
         "biotype": "protein_coding", "synonyms": [{"label": "BACE"}, {"label": "ASP2"}]}
BACE2 = {"id": "ENSG00000182240", "approvedSymbol": "BACE2", "approvedName": "beta-secretase 2",
         "biotype": "protein_coding", "synonyms": []}
DISEASES = {d["id"]: d for d in (AD, EOAD)}
TARGETS = {t["id"]: t for t in (BACE1, BACE2)}
AD_HITS = [hit(AD["id"], AD["name"], 90.0), hit(EOAD["id"], EOAD["name"], 60.0)]
BACE_HITS = [hit(BACE1["id"], "BACE1", 300.0, "target"), hit(BACE2["id"], "BACE2", 200.0, "target")]


# --- comparison key -------------------------------------------------------------------
def test_key_ignores_case_punctuation_and_possessive():
    assert key("Alzheimer's disease") == key("alzheimer disease")
    assert key("GLP-1R") == key("glp1r")


# --- disease ----------------------------------------------------------------------------
def test_exact_name_resolves_and_keeps_areas_and_xrefs():
    ot = FakeOT({("Alzheimer's disease", "disease"): AD_HITS}, DISEASES)
    d = resolve_disease(ot, "Alzheimer's disease")
    assert (d["status"], d["match"], d["id"]) == ("resolved", "exact_name", AD["id"])
    assert d["therapeutic_areas"][0]["name"] == "nervous system disease" and d["xrefs"] == ["MESH:D000544"]


def test_only_exact_synonyms_count():
    ot = FakeOT({("Alzheimer's dementia", "disease"): [hit(EOAD["id"], EOAD["name"], 50.0),
                                                       hit(AD["id"], AD["name"], 45.0)]}, DISEASES)
    d = resolve_disease(ot, "Alzheimer's dementia")
    assert (d["status"], d["match"], d["id"]) == ("resolved", "exact_synonym", AD["id"])   # EOAD's synonym is related


def test_abbreviation_is_always_ambiguous():
    ot = FakeOT({("AD", "disease"): AD_HITS}, DISEASES)
    d = resolve_disease(ot, "AD")
    assert d["status"] == "ambiguous" and [c["id"] for c in d["candidates"]] == [AD["id"], EOAD["id"]]


def test_close_scores_without_exact_match_are_ambiguous():
    ot = FakeOT({("alzheimer", "disease"): AD_HITS}, DISEASES)
    assert resolve_disease(ot, "alzheimer")["status"] == "ambiguous"     # 90 < 2 x 60


def test_clear_score_winner_resolves():
    ot = FakeOT({("alzheimer", "disease"): [hit(AD["id"], AD["name"], 130.0), hit(EOAD["id"], EOAD["name"], 60.0)]},
                DISEASES)
    d = resolve_disease(ot, "alzheimer")
    assert (d["status"], d["match"]) == ("resolved", "score_gap")


def test_not_found_suggests_from_a_looser_query():
    ot = FakeOT({("alzheimer", "disease"): AD_HITS}, DISEASES)
    d = resolve_disease(ot, "alzheimer syndrome")
    assert d["status"] == "not_found" and d["candidates"] and "alzheimer" in d["message"]
    assert resolve_disease(FakeOT(), "xyzzy")["status"] == "not_found"


def test_explicit_id_skips_search():
    d = resolve_disease(FakeOT(diseases=DISEASES), disease_id=AD["id"])
    assert (d["status"], d["match"], d["name"]) == ("resolved", "user_selected", AD["name"])
    assert resolve_disease(FakeOT(), disease_id="MONDO_0000000")["status"] == "not_found"


# --- target -------------------------------------------------------------------------------
def test_target_symbol_with_mechanism_words():
    ot = FakeOT({("BACE1", "target"): BACE_HITS}, targets=TARGETS)
    t = resolve_target(ot, "BACE1 inhibitor")
    assert (t["status"], t["id"], t["symbol"], t["action"], t["drug_type"]) == \
        ("resolved", BACE1["id"], "BACE1", "inhibit", None)


def test_target_synonym_resolves():
    ot = FakeOT({("ASP2", "target"): [hit(BACE2["id"], "BACE2", 10.0, "target"),
                                      hit(BACE1["id"], "BACE1", 9.0, "target")]}, targets=TARGETS)
    t = resolve_target(ot, "ASP2")
    assert (t["status"], t["match"], t["id"]) == ("resolved", "exact_synonym", BACE1["id"])


def test_only_mechanism_words_leave_nothing_to_search():
    t = resolve_target(FakeOT(), "antagonist")
    assert t["status"] == "not_found" and t["action"] == "inhibit"


def test_normalize_status_is_the_worst_of_the_two():
    ot = FakeOT({("AD", "disease"): AD_HITS, ("BACE1", "target"): BACE_HITS}, DISEASES, TARGETS)
    out = normalize(ot, "AD", "BACE1 inhibitor")
    assert out["status"] == "ambiguous" and out["target"]["status"] == "resolved" and out["ot_release"] == "26.09"
    picked = normalize(ot, None, "BACE1 inhibitor", disease_id=AD["id"])
    assert picked["status"] == "resolved"


# --- mechanism parser ------------------------------------------------------------------------
@pytest.mark.parametrize("text,query,action,drug_type", [
    ("BACE1", "BACE1", None, None),
    ("BACE1 inhibitor", "BACE1", "inhibit", None),
    ("anti-PCSK9 antibody", "PCSK9", "inhibit", "antibody"),
    ("anti-IL-6 receptor monoclonal antibodies", "IL-6 receptor", "inhibit", "antibody"),
    ("GLP-1 receptor agonist", "GLP-1 receptor", "activate", None),
    ("GLP-1R partial agonist", "GLP-1R", "activate", None),
    ("CB1 inverse agonist", "CB1", "inhibit", None),
    ("CCR5 antagonist", "CCR5", "inhibit", None),
    ("inhibitor of BACE1", "BACE1", "inhibit", None),
    ("PCSK9-targeting siRNA", "PCSK9", "inhibit", "rna"),
    ("antisense oligonucleotide against SOD1", "SOD1", "inhibit", "rna"),
    ("SMN1 gene therapy", "SMN1", "activate", "gene"),
    ("CD19 CAR-T cell therapy", "CD19", None, "cell"),
    ("HER2 antibody-drug conjugate", "HER2", None, "adc"),
    ("CD3 x CD20 bispecific antibody", "CD3 x CD20", None, "bispecific"),
    ("PSMA radioligand", "PSMA", None, "radioligand"),
    ("BTK degrader", "BTK", "inhibit", None),
    ("mGluR5 negative allosteric modulator", "mGluR5", "inhibit", None),
    ("GABA-A positive allosteric modulator", "GABA-A", "activate", None),
    ("CFTR modulator", "CFTR", None, None),
    ("small molecule KRAS G12C inhibitor", "KRAS", "inhibit", "small_molecule"),
    ("antithrombin", "antithrombin", None, None),          # "anti" inside a word is not an action
])
def test_parse_mechanism(text, query, action, drug_type):
    m = parse_mechanism(text)
    assert (m.target_query, m.action, m.drug_type) == (query, action, drug_type)


def test_parser_values_are_valid_scorer_values():
    from backend.app.scorer import load_config
    cfg = load_config()
    from backend.app.mechanism import ACTION_WORDS, DRUG_TYPE_WORDS
    types = {t for _, _, t, _ in ACTION_WORDS} | {t for t, _ in DRUG_TYPE_WORDS} | {"cell", "small_molecule"}
    assert types - {None} <= set(cfg.facts["modality"]["values"])
    assert {d for *_, d in ACTION_WORDS} - {None} <= set(cfg.facts["moa_direction"]["values"])


# --- client: cache and retries ------------------------------------------------------------------
def test_live_response_is_saved_then_replayed_offline(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(503)                                  # retried
        return httpx.Response(200, json={"data": {"target": BACE1}})

    monkeypatch.setattr("backend.app.opentargets.time.sleep", lambda s: None)
    live = OpenTargets(tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert live.target(BACE1["id"])["approvedSymbol"] == "BACE1"
    assert len(calls) == 2 and calls[1]["operationName"] == "Target"
    saved = tmp_path / f"{cache_key('Target', {'id': BACE1['id']})}.json"
    assert saved.exists() and json.loads(saved.read_text())["response"]["data"]["target"]["id"] == BACE1["id"]

    replay = OpenTargets(tmp_path, offline=True)
    assert replay.target(BACE1["id"])["id"] == BACE1["id"] and replay.calls[0]["cache"] is True
    with pytest.raises(OpenTargetsError):
        replay.disease("MONDO_0004975")                                 # not cached, offline


def test_graphql_errors_are_raised(tmp_path):
    handler = lambda r: httpx.Response(400, json={"errors": [{"message": "Cannot query field 'x'"}]})  # noqa: E731
    ot = OpenTargets(tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(OpenTargetsError, match="Cannot query field"):
        ot.disease("MONDO_0004975")
    assert not list(tmp_path.iterdir())                                 # errors are not cached

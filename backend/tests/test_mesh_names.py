"""Disease names written in MeSH order, plural, with or without apostrophes and hyphens match the same Open Targets
entity; different diseases and subtypes never merge. The Open Targets answers below are made up (FakeOT from
test_step2), shaped like the live answers of 10 October (live sample, seed 9)."""
import pytest

from backend.app.normalize import name_forms, resolve_disease, same_name, search_queries, uninvert
from backend.tests.test_step2 import FakeOT, hit


@pytest.mark.parametrize("a,b", [
    ("Kidney Failure, Chronic", "Chronic Kidney Failure"),
    ("Colitis, Ulcerative", "Ulcerative Colitis"),
    ("Carcinoma, Non-Small-Cell Lung", "Non-Small-Cell Lung Carcinoma"),
    ("Carcinoma, Non-Small-Cell Lung", "non-small cell lung carcinoma"),          # Open Targets' spelling
    ("Alzheimer Disease", "Alzheimer's Disease"),
    ("Alzheimer Disease", "Alzheimers disease"),
    ("Huntingtons Disease", "Huntington disease"),
    ("Hyperlipidemias", "Hyperlipidemia"),
    ("Colorectal Neoplasms", "colorectal neoplasm"),
    ("Cardiomyopathies", "cardiomyopathy"),
    ("Diabetes Mellitus, Type 2", "type 2 diabetes mellitus"),
    ("Purpura, Thrombocytopenic, Idiopathic", "Idiopathic Thrombocytopenic Purpura"),
    ("Neuralgia, Postherpetic", "postherpetic neuralgia"),
    ("  ALZHEIMER’S   disease ", "alzheimer disease"),                            # case, curly apostrophe, spaces
])
def test_same_disease_written_differently(a, b):
    assert same_name(a, b) and same_name(b, a)


@pytest.mark.parametrize("a,b", [
    ("Diabetes Mellitus, Type 2", "Diabetes Mellitus, Type 1"),
    ("Colitis, Ulcerative", "Colitis"),
    ("Kidney Failure, Chronic", "Kidney Failure, Acute"),
    ("Kidney Failure, Chronic", "Acute kidney failure"),
    ("Hyperlipidemias", "Hyperlipidemia, Familial Combined"),
    ("Arthritis, Rheumatoid", "Arthritis, Juvenile"),
    ("Arthritis, Rheumatoid", "juvenile rheumatoid arthritis"),                   # a subtype is not the disease
    ("Psoriasis", "Arthritis, Psoriatic"),
    ("Lung Neoplasms", "Small Cell Lung Carcinoma"),
    ("Anemia", "Anemias, Hemolytic"),
])
def test_different_diseases_do_not_match(a, b):
    assert not same_name(a, b)


def test_mesh_order_is_searched_in_natural_order_too():
    assert uninvert("Kidney Failure, Chronic") == "Chronic Kidney Failure"
    assert uninvert("Hyperlipidemias") is None
    assert search_queries("Neuralgia, Postherpetic") == ["Neuralgia, Postherpetic", "Postherpetic Neuralgia"]
    assert search_queries("Alzheimer disease") == ["Alzheimer disease"]
    assert name_forms("Diabetes Mellitus, Type 2") == {"diabetemellitustype2", "type2diabetemellitus"}   # "-us" keeps its s


# --- resolution with Open Targets search answers --------------------------------------------------------------------
PHN = {"id": "EFO_0009443", "name": "postherpetic neuralgia", "synonyms": []}
CRC = {"id": "MONDO_0005335", "name": "colorectal neoplasm", "synonyms": []}
CKD = {"id": "EFO_0003884", "name": "chronic kidney disease",
       "synonyms": [{"relation": "hasExactSynonym", "terms": ["chronic kidney failure", "chronic renal failure"]}]}
AKF = {"id": "MONDO_0001134", "name": "acute kidney failure", "synonyms": []}
RA = {"id": "EFO_0000685", "name": "rheumatoid arthritis", "synonyms": []}
JRA = {"id": "EFO_0002609", "name": "juvenile rheumatoid arthritis", "synonyms": []}
DISEASES = {d["id"]: d for d in (PHN, CRC, CKD, AKF, RA, JRA)}


def test_mesh_heading_that_open_targets_search_misses_resolves():
    """Live, "Neuralgia, Postherpetic" found nothing at all; the natural order finds the disease by its exact name."""
    ot = FakeOT({("Postherpetic Neuralgia", "disease"): [hit(PHN["id"], PHN["name"], 500.0)]}, DISEASES)
    d = resolve_disease(ot, "Neuralgia, Postherpetic")
    assert (d["status"], d["id"], d["match"]) == ("resolved", PHN["id"], "name_variant")


def test_plural_resolves_to_the_singular_entity_not_by_score():
    """Live: top score 708 vs 393 (< 2x) made it ambiguous; the plural of the exact name is not ambiguous."""
    ot = FakeOT({("Colorectal Neoplasms", "disease"): [
        hit(CRC["id"], CRC["name"], 708.0), hit("MONDO_0021444", "benign neoplasm of large intestine", 393.0),
        hit("MONDO_0005835", "Lynch syndrome", 300.0)]}, DISEASES)
    d = resolve_disease(ot, "Colorectal Neoplasms")
    assert (d["status"], d["id"], d["match"]) == ("resolved", CRC["id"], "name_variant")


def test_mesh_heading_resolves_by_an_exact_synonym_of_the_natural_order():
    """Live, "Kidney Failure, Chronic" returned unrelated hits (hyperparathyroidism, ...)."""
    ot = FakeOT({("Kidney Failure, Chronic", "disease"): [hit("MONDO_0001741", "hyperparathyroidism", 307.0),
                                                          hit("MONDO_0019394", "Senior-Boichis syndrome", 184.0)],
                 ("Chronic Kidney Failure", "disease"): [hit(CKD["id"], CKD["name"], 400.0),
                                                         hit(AKF["id"], AKF["name"], 350.0)]}, DISEASES)
    d = resolve_disease(ot, "Kidney Failure, Chronic")
    assert (d["status"], d["id"], d["match"]) == ("resolved", CKD["id"], "exact_synonym")


def test_the_disease_wins_over_its_subtype():
    ot = FakeOT({("Rheumatoid Arthritis", "disease"): [hit(JRA["id"], JRA["name"], 300.0),
                                                       hit(RA["id"], RA["name"], 290.0)]}, DISEASES)
    d = resolve_disease(ot, "Arthritis, Rheumatoid")
    assert (d["status"], d["id"]) == ("resolved", RA["id"])


def test_two_entities_with_the_same_name_stay_ambiguous():
    ot = FakeOT({("Colitis, Ulcerative", "disease"): [hit("EFO_0000729", "ulcerative colitis", 500.0)],
                 ("Ulcerative Colitis", "disease"): [hit("MONDO_0005101", "Ulcerative colitis", 480.0)]})
    d = resolve_disease(ot, "Colitis, Ulcerative")
    assert d["status"] == "ambiguous" and {c["id"] for c in d["candidates"]} == {"EFO_0000729", "MONDO_0005101"}


def test_no_equal_form_and_no_score_gap_stays_ambiguous():
    ot = FakeOT({("Kidney Failure, Chronic", "disease"): [hit("MONDO_0001741", "hyperparathyroidism", 307.0),
                                                          hit("MONDO_0019394", "Senior-Boichis syndrome", 184.0)]},
                DISEASES)
    assert resolve_disease(ot, "Kidney Failure, Chronic")["status"] == "ambiguous"


def test_abbreviation_is_still_ambiguous():
    ot = FakeOT({("CKD", "disease"): [hit(CKD["id"], CKD["name"], 900.0)]}, DISEASES)
    assert resolve_disease(ot, "CKD")["status"] == "ambiguous"

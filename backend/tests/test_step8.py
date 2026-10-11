"""Step 8 tests: the memo. Stand-in writers play an honest and a careless LLM; the validator must keep only what the
claims support, retry once, and fall back to claim statements."""
import json

import pytest

import backend.app.api as api
from backend.app.report import LLM_SECTIONS, SECTION_FACTS, SECTIONS, check_paragraph
from backend.tests.test_step6 import client, start  # noqa: F401  (client is a fixture)

SOURCE = "https://example.org/data-room/phase2-head-to-head.pdf"


class HonestWriter:
    """Cites real claims and copies only their numbers. Also labels trials like the keyword LLM (no labels here)."""
    model = "honest-writer"

    def __init__(self):
        self.calls = []

    def complete_json(self, task, system, user, schema):
        self.calls.append(task)
        if task != "write_report":
            return {"trials": []}
        pack = json.loads(user.split("\n\nYour previous answer")[0])
        claims = {c["id"]: c for c in pack["claims"]}
        out = []
        for sid in LLM_SECTIONS:
            hits = [c for c in claims.values() if c["fact"] in SECTION_FACTS.get(sid, set())]
            if sid == "recommendation":
                rule = pack["rules_fired"][0] if pack["rules_fired"] else None
                paras = [{"text": f"The evidence supports the computed verdict: {pack['verdict']['grounds']}.",
                          "kind": "inference", "claim_ids": rule["claim_ids"] if rule else []}]
            elif hits:
                paras = [{"text": hits[0]["statement"], "kind": "source", "claim_ids": [hits[0]["id"]]}]
            else:
                paras = [{"text": "Nothing is known here yet, which limits confidence.", "kind": "inference",
                          "claim_ids": []}]
            out.append({"id": sid, "paragraphs": paras})
        return {"sections": out}


class CarelessWriter(HonestWriter):
    """First answer breaks every rule; the retry is honest."""

    def complete_json(self, task, system, user, schema):
        if task == "write_report" and "Your previous answer" not in user:
            self.calls.append(task)
            return {"sections": [
                {"id": "scientific_thesis", "paragraphs": [
                    {"text": "BACE1 has a 42% chance of success.", "kind": "source", "claim_ids": []},
                    {"text": "Genetics is strong.", "kind": "source", "claim_ids": ["clm_made_up_9"]}]},
                {"id": "recommendation", "paragraphs": [
                    {"text": "Our recommendation is Invest.", "kind": "inference", "claim_ids": []}]},
                {"id": "commercial_opportunity", "paragraphs": [
                    {"text": "Peak sales could reach 3 billion dollars.", "kind": "inference", "claim_ids": []}]}]}
        return super().complete_json(task, system, user, schema)


class BrokenWriter(HonestWriter):
    def complete_json(self, task, system, user, schema):
        from backend.app.llm import LLMError
        if task == "write_report":
            raise LLMError("rate limited")
        return super().complete_json(task, system, user, schema)


def report(client, run_id, version=None):  # noqa: F811
    r = client.get(f"/runs/{run_id}/report", params={"version": version} if version else {})
    assert r.status_code == 200, r.text
    return r.json()


def all_paragraphs(rep):
    return [(s["id"], p) for s in rep["sections"] for p in s["paragraphs"]]


# --- shape and integrity, without an LLM ------------------------------------------------------------------------------
def test_template_report_has_11_sections_and_only_real_claim_ids(client):  # noqa: F811
    run_id = start(client, disease="Alzheimer disease", target="BACE1 inhibitor")
    rep = report(client, run_id)
    assert [s["id"] for s in rep["sections"]] == [s for s, _, _ in SECTIONS] and rep["llm"]["used"] is False
    ids = {c["id"] for c in client.get(f"/runs/{run_id}/claims").json()}
    for sid, p in all_paragraphs(rep):
        assert p["kind"] in {"source", "inference", "scorer"} and p["text"]
        assert set(p["claim_ids"]) <= ids
        if p["kind"] == "source":
            assert p["claim_ids"], sid
    risks = next(s for s in rep["sections"] if s["id"] == "key_risks")["paragraphs"]
    assert risks[0]["text"].startswith("Rule fired, note: Neither genetics") and risks[0]["claim_ids"]
    paras = [p["text"] for p in rep["sections"][0]["paragraphs"]]
    # 2.4: offline, uniprot / openFDA / ctgov have no cached answers: the memo says the run is incomplete first
    assert paras[0].startswith("INCOMPLETE RUN: some sources failed (uniprot: failed")
    head = next(t for t in paras if t.startswith("Recommendation:"))
    assert head.startswith("Recommendation: Insufficient evidence.") and rep["decision"] == "Insufficient evidence"
    dd = next(s for s in rep["sections"] if s["id"] == "diligence_questions")["paragraphs"]
    assert 5 <= len(dd) <= 10
    assert all("http" in p["text"] for p in next(s for s in rep["sections"] if s["id"] == "sources")["paragraphs"])


def test_markdown(client):  # noqa: F811
    run_id = start(client, disease="Alzheimer disease", target="BACE1 inhibitor")
    md = client.get(f"/runs/{run_id}/report.md").text
    assert md.startswith("# Alzheimer disease + BACE1: Insufficient evidence") and md.count("\n## ") == 11
    assert "[clm_" in md


# --- with an LLM --------------------------------------------------------------------------------------------------------
def test_honest_writer_is_used(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api, "make_llm", lambda: HonestWriter())
    run_id = start(client, disease="familial hypercholesterolemia", target="anti-PCSK9 antibody")
    rep = report(client, run_id)
    by = {s["id"]: s["generated_by"] for s in rep["sections"]}
    assert by["scientific_thesis"] == "llm" and by["recommendation"] == "code+llm" and by["sources"] == "code"
    assert rep["llm"]["attempts"] == 1 and rep["llm"]["issues"] == []
    assert any(p["kind"] == "inference" for _, p in all_paragraphs(rep))


def test_careless_writer_is_corrected_by_validator_and_retry(client, monkeypatch):  # noqa: F811
    writer = CarelessWriter()
    monkeypatch.setattr(api, "make_llm", lambda: writer)
    run_id = start(client, disease="Alzheimer disease", target="BACE1 inhibitor")
    rep = report(client, run_id)
    assert writer.calls.count("write_report") == 2 and rep["llm"]["attempts"] == 2
    text = json.dumps(rep)
    for bad in ("42%", "3 billion", "clm_made_up_9", "recommendation is Invest"):
        assert bad not in text


def test_llm_failure_falls_back_to_template(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api, "make_llm", lambda: BrokenWriter())
    run_id = start(client, disease="Alzheimer disease", target="BACE1 inhibitor")
    rep = report(client, run_id)
    assert {s["generated_by"] for s in rep["sections"]} <= {"code", "template"}
    assert "LLM call failed" in rep["llm"]["issues"][0]


# --- versions -----------------------------------------------------------------------------------------------------------
def test_evidence_writes_a_new_report_version(client):  # noqa: F811
    run_id = start(client, disease="familial hypercholesterolemia", target="anti-PCSK9 antibody")
    assert report(client, run_id)["decision"] == "Do Not Invest"            # 2.5: crowded
    client.post(f"/runs/{run_id}/evidence", json={"action": "add", "fact": "differentiation_claim",
                                                  "value": "efficacy", "source_url": SOURCE})
    v2 = report(client, run_id)
    assert v2["version"] == 2 and v2["decision"] == "Invest"   # differentiation removes the me-too minus and cap
    assert report(client, run_id, version=1)["decision"] == "Do Not Invest"
    assert SOURCE in json.dumps(v2["sections"][-1])                # the human source is listed


def test_regenerate_and_errors(client):  # noqa: F811
    run_id = start(client, disease="Alzheimer disease", target="BACE1 inhibitor")
    r = client.post(f"/runs/{run_id}/report")
    assert r.status_code == 202 and r.json()["version"] == 1
    assert report(client, run_id)["version"] == 1
    amb = start(client, disease="AD", target="BACE1")
    assert client.get(f"/runs/{amb}/report").status_code == 404


# --- the validator itself -------------------------------------------------------------------------------------------------
CLAIMS = {"c1": {"statement": "7 drugs are approved for Alzheimer disease.", "value": 7},
          "c2": {"statement": "BACE1 is not a common essential gene.", "value": False}}


@pytest.mark.parametrize("p,ok", [
    ({"text": "Seven drugs are approved.", "kind": "source", "claim_ids": ["c1"]}, True),
    ({"text": "7 drugs are approved.", "kind": "source", "claim_ids": ["c1"]}, True),
    ({"text": "7 drugs are approved.", "kind": "source", "claim_ids": ["c2"]}, False),     # number not in c2
    ({"text": "Phase 2/3 trials and grade 4 events matter.", "kind": "inference", "claim_ids": []}, True),
    ({"text": "About 30% of programs fail.", "kind": "inference", "claim_ids": []}, False),
    ({"text": "Approved drugs exist.", "kind": "source", "claim_ids": []}, False),
    ({"text": "Approved drugs exist [clm_x].", "kind": "source", "claim_ids": ["c1"]}, True),  # inline ID stripped
    ({"text": "The verdict should be Conditional.", "kind": "inference", "claim_ids": []}, False),
    ({"text": "We do not invest because genetics is absent.", "kind": "inference", "claim_ids": ["c2"]}, True),
])
def test_check_paragraph(p, ok):
    assert (check_paragraph(dict(p), CLAIMS, "Do Not Invest") is None) is ok

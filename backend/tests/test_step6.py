"""Step 6 tests: the API on a temporary SQLite file, fed with the recorded live Open Targets responses."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.app.api as api
from backend.app.opentargets import OpenTargets

LIVE = Path(__file__).parent / "fixtures" / "live"


def recorded_collect(ot, disease_id, target_id):
    return json.loads((LIVE / "runs" / f"{disease_id}__{target_id}.json").read_text())


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB_FILE", tmp_path / "test.db")
    monkeypatch.setattr(api, "make_ot", lambda: OpenTargets(LIVE / "cache", offline=True))
    monkeypatch.setattr(api, "make_llm", lambda: None)
    monkeypatch.setattr("backend.app.pipeline.collect", recorded_collect)
    return TestClient(api.app)


def start(client, **body):
    r = client.post("/runs", json=body)
    assert r.status_code == 202, r.text
    return r.json()["run_id"]          # TestClient runs the background job before returning


def test_run_end_to_end(client):
    run_id = start(client, disease="Alzheimer disease", target="BACE1 inhibitor", phase="ph2")
    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "done" and run["disease"]["id"] == "MONDO_0004975" and run["target"]["symbol"] == "BACE1"
    assert run["verdict"]["decision"] == "Insufficient evidence" and run["verdict"]["version"] == 1
    assert "no LLM key" in run["message"]

    claims = client.get(f"/runs/{run_id}/claims").json()
    ids = [c["id"] for c in claims]
    assert ids[0] == f"clm_{run_id.removeprefix('run_')}_1" and len(set(ids)) == len(ids)
    assert {c["status"] for c in claims} == {"used"}
    gen = next(c for c in claims if c["fact"] == "genetic_support")
    assert gen["value"] == "none" and gen["origin"] == "structured" and gen["rule"] and gen["sources"]

    one = client.get(f"/claims/{gen['id']}").json()
    assert one["fact_label"].startswith("Genetic support") and one["status"] == "used"
    assert client.get(f"/runs/{run_id}/claims", params={"origin": "user"}).json()[0]["fact"] in {"moa_direction", "phase"}

    result = client.get(f"/runs/{run_id}/result").json()
    assert result["version"] == 1 and result["result"]["dd_questions"] and "used" in result
    trials = client.get(f"/runs/{run_id}/trials").json()
    assert any(t["nct"] == "NCT02569398" for t in trials["trials"]) and trials["labels"]["labels"] == {}
    assert client.get("/runs").json()[0]["decision"] == "Insufficient evidence"


def test_ambiguous_then_pick_an_id(client):
    run_id = start(client, disease="AD", target="BACE1")
    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "ambiguous" and run["verdict"] is None
    picked = run["disease"]["candidates"][0]["id"]
    assert picked == "MONDO_0004975"
    again = start(client, disease_id=picked, target="BACE1")
    assert client.get(f"/runs/{again}").json()["status"] == "done"


def test_with_llm_labels_the_trials(client, monkeypatch):
    from backend.tests.test_step5 import KeywordLLM
    monkeypatch.setattr(api, "make_llm", lambda: KeywordLLM())
    run_id = start(client, disease="Alzheimer disease", target="BACE1 inhibitor")
    claims = client.get(f"/runs/{run_id}/claims", params={"origin": "llm"}).json()
    assert {c["fact"] for c in claims} >= {"moa_failures_efficacy_ph23", "moa_discontinued_safety_count"}
    eff = next(c for c in claims if c["fact"] == "moa_failures_efficacy_ph23")
    assert eff["verified"] is True and eff["quote"] and eff["doc_ids"] and eff["status"] == "pending"   # a human confirms


def test_errors_end_the_run_with_a_message(client, monkeypatch):
    def broken():
        raise RuntimeError("Open Targets is down")
    monkeypatch.setattr(api, "make_ot", broken)
    run_id = start(client, disease="Alzheimer disease", target="BACE1")
    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "error" and "Open Targets is down" in run["message"]


def test_input_validation_and_404(client):
    assert client.post("/runs", json={"disease": "Alzheimer disease"}).status_code == 422
    assert client.post("/runs", json={"disease": "x", "target": "y", "phase": "phase 2"}).status_code == 422
    assert client.get("/runs/run_nope").status_code == 404
    assert client.get("/claims/clm_nope_1").status_code == 404


def test_health(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["scorer_version"] == "2.7" and "key_set" in h["llm"]

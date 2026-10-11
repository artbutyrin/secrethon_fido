"""Step 7 tests: human evidence and confirmation -> new verdict version with "before -> after", on real data."""
import pytest

import backend.app.api as api
from backend.tests.test_step5 import KeywordLLM
from backend.tests.test_step6 import client, start  # noqa: F401  (client is a fixture)

SOURCE = "https://example.org/data-room/phase2-readout.pdf"


def claims(client, run_id, **params):  # noqa: F811
    return client.get(f"/runs/{run_id}/claims", params=params).json()


def evidence(client, run_id, **body):  # noqa: F811
    return client.post(f"/runs/{run_id}/evidence", json=body)


# --- add: the demo flip on PCSK9 -----------------------------------------------------------------------------------
def test_differentiation_turns_me_too_into_invest(client):  # noqa: F811
    """Scorer 2.5: me-too without proven differentiation is Do Not Invest (crowded); human differentiation lifts it."""
    run_id = start(client, disease="familial hypercholesterolemia", target="anti-PCSK9 antibody")
    v = client.get(f"/runs/{run_id}").json()["verdict"]
    assert (v["decision"], v["grounds"]) == ("Do Not Invest", "crowded")

    r = evidence(client, run_id, action="add", fact="differentiation_claim", value="efficacy",
                 source_url=SOURCE, author="analyst")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["version"] == 2 and out["change"]["decision"] == {"from": "Do Not Invest", "to": "Invest", "changed": True}
    assert "me_too" in [x["id"] for x in out["change"]["rules_removed"]]
    assert out["verdict"]["decision"] == "Invest"

    human = claims(client, run_id, origin="user")
    added = next(c for c in human if c["fact"] == "differentiation_claim")
    assert added["id"] == out["evidence"]["claim_id"] and added["added_by"] == "analyst" and added["status"] == "used"
    assert added["sources"][0]["url"] == SOURCE

    hist = client.get(f"/runs/{run_id}/history").json()
    assert [h["version"] for h in hist] == [1, 2] and hist[0]["trigger"] == "pipeline"
    assert hist[1]["trigger"] == f"add:{added['id']}" and hist[1]["change"]["decision"]["changed"]
    assert client.get(f"/runs/{run_id}/result", params={"version": 1}).json()["result"]["verdict"]["decision"] == \
        "Do Not Invest"


def test_human_evidence_outranks_open_targets(client):  # noqa: F811
    run_id = start(client, disease="Alzheimer disease", target="BACE1 inhibitor")
    structured = claims(client, run_id, fact="genetic_support")[0]
    out = evidence(client, run_id, action="add", fact="genetic_support", value="gwas",
                   source_text="Internal fine-mapping, data room file G-12").json()
    after = {c["id"]: c for c in claims(client, run_id, fact="genetic_support")}
    assert after[structured["id"]]["status"] == "not_used" and after[out["evidence"]["claim_id"]]["status"] == "used"
    assert {"id": "human_genetics", "name": "Human genetics", "from": "Y", "to": "G"} in out["change"]["scorecard"]
    assert "no_genetics_no_precedent" in [x["id"] for x in out["change"]["rules_removed"]]


# --- confirm: an LLM claim from a single sponsor waits, a human confirms -------------------------------------------
class OneTrialLLM(KeywordLLM):
    """Labels only AstraZeneca's futility stop: one sponsor, so the failure claim must wait for confirmation."""

    def complete_json(self, task, system, user, schema):
        ans = super().complete_json(task, system, user, schema)
        if "trials" in ans:
            ans["trials"] = [t for t in ans["trials"] if t["nct"] == "NCT02783573"]
        return ans


def test_confirming_a_pending_llm_claim_changes_the_verdict(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api, "make_llm", lambda: OneTrialLLM())
    run_id = start(client, disease="Alzheimer disease", target="BACE1 inhibitor")
    run = client.get(f"/runs/{run_id}").json()
    assert [p["fact"] for p in run["verdict"]["pending"]] == ["moa_failures_efficacy_ph23"]
    pending = claims(client, run_id, fact="moa_failures_efficacy_ph23")[0]
    assert pending["status"] == "pending" and pending["quote"] and pending["doc_ids"] == ["sponsor:astrazeneca"]

    out = evidence(client, run_id, action="confirm", claim_id=pending["id"], author="analyst").json()
    assert out["change"]["pending_resolved"] == ["moa_failures_efficacy_ph23"]
    assert "one_mechanism_failure" in [x["id"] for x in out["change"]["rules_added"]]
    assert out["change"]["minuses"]["to"] > out["change"]["minuses"]["from"]
    assert claims(client, run_id, fact="moa_failures_efficacy_ph23")[0]["status"] == "used"
    again = evidence(client, run_id, action="confirm", claim_id=pending["id"])
    assert again.status_code == 409


# --- trace: verdict -> claims ------------------------------------------------------------------------------------------
def test_scorecard_items_and_rules_carry_claim_ids(client):  # noqa: F811
    run_id = start(client, disease="Alzheimer disease", target="BACE1 inhibitor")
    v = client.get(f"/runs/{run_id}").json()["verdict"]
    by_fact = {c["fact"]: c["id"] for c in claims(client, run_id)}
    genetics = next(i for i in v["scorecard"] if i["id"] == "human_genetics")
    assert genetics["color"] == "Y" and by_fact["genetic_support"] in genetics["claim_ids"]
    rule = next(r for r in v["rules"] if r["id"] == "no_genetics_no_precedent")
    assert set(rule["claim_ids"]) == {by_fact["genetic_support"], by_fact["moa_clinical_precedent"]}
    unknown = next(i for i in v["scorecard"] if i["id"] == "clinical_effect")
    assert unknown["color"] == "U" and unknown["claim_ids"] == [] and unknown["reads"]


# --- refusals: nothing is stored ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("body,code,text", [
    ({"action": "add", "fact": "no_such_fact", "value": 1, "source_url": SOURCE}, 422, "unknown fact"),
    ({"action": "add", "fact": "genetic_support", "value": "strong", "source_url": SOURCE}, 422, "expected"),
    ({"action": "add", "fact": "genetic_support", "value": "gwas"}, 422, "source is required"),
    ({"action": "add", "fact": "moa_clinical_precedent", "value": "approved_same", "source_url": SOURCE}, 422,
     "Contradictory"),                                         # Open Targets says 0 approved with this mechanism
    ({"action": "add", "fact": "genetic_support"}, 422, "needs fact and value"),
    ({"action": "confirm"}, 422, "needs claim_id"),
    ({"action": "confirm", "claim_id": "clm_nope_1"}, 404, "no claim"),
])
def test_bad_evidence_is_refused_and_not_stored(client, body, code, text):  # noqa: F811
    run_id = start(client, disease="Alzheimer disease", target="BACE1 inhibitor")
    n = len(claims(client, run_id))
    r = evidence(client, run_id, **body)
    assert r.status_code == code and text in r.text
    assert len(claims(client, run_id)) == n and len(client.get(f"/runs/{run_id}/history").json()) == 1


def test_confirm_only_for_llm_claims_and_only_on_finished_runs(client):  # noqa: F811
    run_id = start(client, disease="Alzheimer disease", target="BACE1 inhibitor")
    structured = claims(client, run_id, origin="structured")[0]
    assert evidence(client, run_id, action="confirm", claim_id=structured["id"]).status_code == 400
    amb = start(client, disease="AD", target="BACE1")
    r = evidence(client, amb, action="add", fact="genetic_support", value="gwas", source_url=SOURCE)
    assert r.status_code == 409 and "ambiguous" in r.text


def test_fact_catalog(client):  # noqa: F811
    facts = {f["fact"]: f for f in client.get("/facts").json()}
    assert len(facts) == 98 and facts["differentiation_claim"]["level"] == "asset"
    assert "efficacy" in facts["differentiation_claim"]["values"] and facts["patent_status"]["dd"]

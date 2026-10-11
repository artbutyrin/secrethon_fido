"""The API, the memo and the run list show one verdict, and "Insufficient evidence" is never written up as a negative
call. Recorded Huntington run (Open Targets fixture, no LLM): Invest on Mendelian genetics. A human then records
  - genetic_support = no_data (no genetic data for the disease): no plus and no minus -> Insufficient evidence;
  - genetic_support = none (data, but nothing for this target): the warning "neither genetics nor a target precedent"
    is a minus under the rules -> Do Not Invest (outweighed), not Insufficient evidence."""
from backend.app.report import check_paragraph
from backend.app.scorer import DNI, INSUFFICIENT, VERDICTS
from backend.tests.test_step6 import client, start  # noqa: F401  (client is a fixture)


def genetics(client, run_id, value):  # noqa: F811
    r = client.post(f"/runs/{run_id}/evidence", json={
        "action": "add", "fact": "genetic_support", "value": value, "author": "analyst",
        "source_url": "https://example.org/genetics-review"})
    assert r.status_code == 200, r.text


def test_api_memo_and_list_agree_on_insufficient_evidence(client):  # noqa: F811
    run_id = start(client, disease="Huntington disease", target="HTT antisense oligonucleotide")
    assert client.get(f"/runs/{run_id}").json()["verdict"]["decision"] != INSUFFICIENT     # Conditional (capped) under 2.4
    genetics(client, run_id, "no_data")

    run = client.get(f"/runs/{run_id}").json()
    result = client.get(f"/runs/{run_id}/result").json()
    report = client.get(f"/runs/{run_id}/report").json()
    listed = next(x for x in client.get("/runs").json() if x["id"] == run_id)
    assert run["verdict"]["decision"] == result["result"]["verdict"]["decision"] == report["decision"] \
        == listed["decision"] == INSUFFICIENT
    assert run["verdict"]["grounds"] == "insufficient_evidence"
    text = " ".join(p["text"] for s in report["sections"] for p in s["paragraphs"])
    assert "Recommendation: Insufficient evidence." in text and "not a negative call" in text
    assert "Do Not Invest" not in text                                 # no paragraph calls it Do Not Invest


def test_a_negative_signal_is_still_do_not_invest(client):  # noqa: F811
    run_id = start(client, disease="Huntington disease", target="HTT antisense oligonucleotide")
    genetics(client, run_id, "contradicts")         # 2.4: "none" is absence of evidence (a note), "contradicts" is not
    v = client.get(f"/runs/{run_id}").json()["verdict"]
    assert (v["decision"], v["grounds"]) == (DNI, "outweighed")
    assert client.get(f"/runs/{run_id}/report").json()["decision"] == DNI


def test_llm_text_that_calls_insufficient_evidence_do_not_invest_is_rejected():
    say = lambda t: {"text": t, "kind": "inference", "claim_ids": []}  # noqa: E731
    assert check_paragraph(say("We rate this Do Not Invest."), {}, INSUFFICIENT)
    assert check_paragraph(say("The verdict is Insufficient evidence."), {}, DNI)
    assert check_paragraph(say("The verdict is Insufficient evidence: the public data are thin."), {}, INSUFFICIENT) \
        is None
    assert VERDICTS == ("Invest", "Conditional", "Insufficient evidence", "Do Not Invest")

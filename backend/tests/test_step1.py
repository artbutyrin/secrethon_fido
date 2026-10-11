"""Step 1 tests: claims -> facts -> verdict with the scorer, including the demo flip on human confirmation."""
from backend.app.scorer import evaluate, facts_from_claims, load_config

CFG = load_config()
CLAIMS = [
    {"id": "clm_1", "fact": "approved_therapies_count", "value": 0, "origin": "structured"},
    {"id": "clm_2", "fact": "genetic_support", "value": "gwas", "origin": "structured"},
    {"id": "clm_3", "fact": "oncology", "value": False, "origin": "structured"},
    {"id": "clm_4", "fact": "class_safety_signal", "value": True, "origin": "structured"},
    {"id": "clm_5", "fact": "phase", "value": "ph1", "origin": "user"},
    {"id": "clm_6", "fact": "moa_failures_efficacy_ph23", "value": 1, "origin": "llm",
     "verified": True, "doc_ids": ["doc_trial_1"]},
]


def run(claims):
    got = facts_from_claims(CFG, claims)
    return got, evaluate(CFG, got["facts"])


def test_llm_failure_waits_for_confirmation():
    got, payload = run([dict(c) for c in CLAIMS])
    assert payload["verdict"]["decision"] == "Conditional"
    assert [p["fact"] for p in got["pending"]] == ["moa_failures_efficacy_ph23"]


def test_confirmation_flips_verdict():
    claims = [dict(c) for c in CLAIMS]
    claims[-1]["confirmed"] = True
    got, payload = run(claims)
    assert payload["verdict"]["decision"] == "Do Not Invest" and got["pending"] == []


def test_unknown_fact_is_rejected_not_crashing():
    got, _ = run([{"id": "x", "fact": "no_such_fact", "value": 1, "origin": "structured"}])
    assert got["rejected"][0]["fact"] == "no_such_fact"

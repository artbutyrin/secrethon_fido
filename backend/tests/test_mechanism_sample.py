"""Offline checks of the second sample (mechanism_pairs.txt): its make-up, the parser on every pair, the check logic,
and the expectations of the three pairs that have recorded Open Targets runs (fixtures/live). The live run is
mechanism_sample.py; the stop-reason labels here come from the keyword LLM of test_step5 (no model)."""
import json
from pathlib import Path

import pytest

from backend.app.mechanism import parse_mechanism
from backend.app.normalize import normalize
from backend.app.opentargets import OpenTargets
from backend.app.pipeline import analyze, score_claims
from backend.tests.mechanism_sample import check, evaluate, observe, parse_expectation, read_pairs
from backend.tests.test_step5 import KeywordLLM

LIVE = Path(__file__).parent / "fixtures" / "live"
PAIRS = read_pairs()


def exp(pair, key, op=None):
    return [e for e in pair["expect"] if e["key"] == key and (op is None or e["op"] == op)]


def test_fifteen_distinct_pairs_with_a_reason_and_both_kinds_of_history():
    assert len(PAIRS) == 15 and len({(p["disease"].lower(), p["mechanism"].lower()) for p in PAIRS}) == 15
    assert all(len(p["why"]) > 40 and len(p["expect"]) >= 3 for p in PAIRS)
    positive = [p for p in PAIRS if any(e["op"] == ">=" and not e["optional"] for e in exp(p, "approved_same"))]
    failures = [p for p in PAIRS if exp(p, "efficacy_failure", "+=")]
    other_stops = [p for p in PAIRS if exp(p, "efficacy_failure", "-=")]
    not_same = [p for p in PAIRS if exp(p, "same", "-=")]
    assert len(positive) >= 7 and len(failures) >= 4 and len(other_stops) >= 3 and len(not_same) >= 7
    actions = {}
    for p in PAIRS:
        q = exp(p, "query")[0]["value"]
        actions.setdefault(q, set()).add(exp(p, "action")[0]["value"])
    assert any(len(a) == 2 for a in actions.values())            # one target in both directions (GLP-1 receptor)


def test_independent_of_the_first_sample():
    truth = json.loads((Path(__file__).parent / "backtest_truth.json").read_text(encoding="utf-8"))
    first = {(t["disease"].lower(), t["target"].upper()) for t in truth}
    second = {(p["disease"].lower(), exp(p, "query")[0]["value"].upper()) for p in PAIRS}
    assert not first & second


@pytest.mark.parametrize("pair", PAIRS, ids=lambda p: p["mechanism"])
def test_the_parser_reads_every_mechanism(pair):
    m = parse_mechanism(pair["mechanism"])
    assert m.target_query == exp(pair, "query")[0]["value"] and m.action == exp(pair, "action")[0]["value"]


def test_check_logic():
    obs = {"same": ["ALIROCUMAB", "EVOLOCUMAB"], "efficacy_failure": ["LANABECESTAT"], "approved_same": 2,
           "precedent": "approved_same", "verdict_if_confirmed": "Do Not Invest"}
    ok = lambda t: check(parse_expectation(t), obs)  # noqa: E731
    assert ok("same+=ALIROCUMAB,EVOLOCUMAB") == "pass" and ok("same-=EVINACUMAB") == "pass"
    assert ok("same-=ALIROCUMAB") == "fail" and ok("efficacy_failure-=LANABECESTAT") == "fail"
    assert ok("efficacy_failure+=TOMINERSEN?") == "open"                     # optional and not seen: open
    assert ok("approved_same>=2") == "pass" and ok("approved_same=0") == "fail"
    assert ok("precedent=approved_same") == "pass" and ok("verdict_if_confirmed!=Invest") == "pass"
    assert check(parse_expectation("approved_same>=1"), {}) == "fail"     # no claim at all is not a pass
    assert check(parse_expectation("approved_same>=1?"), {}) == "open"
    # 2.4: verdict checks, A/B = one of
    v = {"verdict": "Conditional"}
    assert check(parse_expectation("verdict=Invest/Conditional"), v) == "pass"
    assert check(parse_expectation("verdict!=Do Not Invest"), v) == "pass"
    assert check(parse_expectation("verdict=Do Not Invest"), v) == "fail"
    assert check(parse_expectation("verdict=Do Not Invest?"), v) == "open"
    assert check(parse_expectation("verdict!=Invest"), {}) == "open"


def recorded(disease, mechanism):
    ot = OpenTargets(LIVE / "cache", offline=True)
    n = normalize(ot, disease, mechanism)
    collected = json.loads((LIVE / "runs" / f"{n['disease']['id']}__{n['target']['id']}.json").read_text())
    out = analyze(ot, disease, mechanism, collected=collected, llm=KeywordLLM())
    claims = [dict(c, id=f"clm_{i}") for i, c in enumerate(out["claims"], 1)]
    return observe(out["normalized"], out["collected"], claims, score_claims(claims))


@pytest.mark.parametrize("disease,mechanism", [("familial hypercholesterolemia", "anti-PCSK9 antibody"),
                                               ("Alzheimer disease", "BACE1 inhibitor"),
                                               ("Huntington disease", "HTT antisense oligonucleotide")])
def test_recorded_pairs_meet_their_expectations(disease, mechanism, monkeypatch):
    monkeypatch.setenv("UNOBIO_AUTO_CONFIRM", "1")          # 2.4: as in a live run (verdict checks)
    pair = next(p for p in PAIRS if (p["disease"], p["mechanism"]) == (disease, mechanism))
    checks = evaluate(pair, recorded(disease, mechanism))
    assert [c["text"] for c in checks if c["result"] == "fail"] == []
    assert all(c["optional"] for c in checks if c["result"] == "open")


def test_a_safety_stop_is_not_an_efficacy_failure_on_recorded_trials():
    obs = recorded("Alzheimer disease", "BACE1 inhibitor")
    assert "LANABECESTAT" in obs["efficacy_failure"] and "ATABECESTAT" not in obs["efficacy_failure"]
    assert "ATABECESTAT" in obs["same"]                       # same mechanism, stopped for liver safety


def test_the_opposite_direction_is_not_the_same_mechanism_on_recorded_drugs():
    """What 'obesity | GLP-1 receptor antagonist' checks live, shown on the recorded PCSK9 drugs."""
    inhibit = recorded("familial hypercholesterolemia", "anti-PCSK9 antibody")
    activate = recorded("familial hypercholesterolemia", "PCSK9 agonist")
    assert {"ALIROCUMAB", "EVOLOCUMAB"} <= set(inhibit["same"]) and inhibit["approved_same"] >= 2
    assert not {"ALIROCUMAB", "EVOLOCUMAB"} & set(activate["same"])
    assert activate["approved_same"] == 0 and activate["precedent"] == "none"

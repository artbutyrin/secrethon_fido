"""2.3: "Insufficient evidence" is its own verdict. Do Not Invest stays for negative evidence."""
from unobio_scoring import (CONDITIONAL, DNI, GROUNDS_VERDICT, INSUFFICIENT, INVEST, VERDICT_RANK, decide_full,
                            evaluate, load_config)

CFG = load_config()
T = CFG.thresholds


def test_thin_evidence_without_negatives_is_insufficient_not_do_not_invest():
    assert decide_full(0, 0, False, T)[0::2] == (INSUFFICIENT, "insufficient_evidence")
    res = evaluate(CFG, {})                                   # nothing known at all
    assert (res["verdict"]["decision"], res["verdict"]["grounds"]) == (INSUFFICIENT, "insufficient_evidence")
    assert "not negative evidence" in res["verdict"]["grounds_text"]


def test_a_kill_rule_is_do_not_invest_even_when_evidence_is_thin():
    assert decide_full(0, 0, True, T)[0::2] == (DNI, "kill")
    res = evaluate(CFG, {"modality_target_mismatch": True})   # e.g. an antibody against an intracellular target
    assert (res["verdict"]["decision"], res["verdict"]["grounds"]) == (DNI, "kill")


def test_a_confirmed_mechanism_failure_is_do_not_invest():
    facts = {"genetic_support": "none", "moa_failures_efficacy_ph23": 2, "approved_same_moa_count": 0}
    res = evaluate(CFG, facts)
    assert res["verdict"]["decision"] == DNI and res["verdict"]["grounds"] in {"kill", "negatives", "outweighed"}


def test_a_negative_signal_without_kill_follows_the_minus_count_not_insufficient():
    assert decide_full(0, 1, False, T)[0::2] == (DNI, "outweighed")                      # minus, no plus
    assert decide_full(0, T["neg_dni"], False, T)[0::2] == (DNI, "negatives")
    assert decide_full(1, 1, False, T)[0::2] == (DNI, "outweighed")         # a plus does not hide a minus


def test_positive_and_balanced_cases_keep_their_verdicts():
    """Same verdicts as 2.2 for Invest and Conditional (thresholds unchanged: invest_margin 2, dni_margin 0,
    min_pos_conditional 2, min_science_pos_invest 2 with science_short = Conditional)."""
    assert decide_full(2, 0, False, T, science_greens=1, science_pos=2)[0::2] == (INVEST, "positive")
    # 2.4: the option exists (off in the built-in config): with it, two points from one item are not enough
    T2 = {**T, "min_science_items_invest": 2}
    assert decide_full(2, 0, False, T2, science_greens=1, science_pos=2)[0::2] == (CONDITIONAL, "science_short")
    assert decide_full(2, 0, False, T, science_greens=1, science_pos=1)[0::2] == (CONDITIONAL, "science_short")
    assert decide_full(3, 2, False, T, greens=3, science_greens=1)[0::2] == (CONDITIONAL, "balanced")
    assert decide_full(1, 0, False, T)[0::2] == (INSUFFICIENT, "insufficient_evidence")    # 2.2: Do Not Invest


def test_verdict_follows_the_grounds_and_ranks_between_conditional_and_do_not_invest():
    for pos in range(4):
        for neg in range(4):
            for killed in (False, True):
                verdict, _, grounds = decide_full(pos, neg, killed, T)
                assert GROUNDS_VERDICT[grounds] == verdict
    assert VERDICT_RANK[INVEST] > VERDICT_RANK[CONDITIONAL] > VERDICT_RANK[INSUFFICIENT] > VERDICT_RANK[DNI]


def test_a_minus_never_turns_insufficient_into_something_better():
    for pos in range(4):
        base = decide_full(pos, 0, False, T)[0]
        worse = decide_full(pos, 1, False, T)[0]
        assert VERDICT_RANK[worse] <= VERDICT_RANK[base]

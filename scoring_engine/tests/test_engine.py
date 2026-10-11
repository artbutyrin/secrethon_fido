import dataclasses
"""Engine tests. Run: python -m pytest -q"""
import copy
import random
from pathlib import Path

import pytest
import yaml

from scoring import (CONDITIONAL, DNI, GREEN, INVEST, RED, UNKNOWN, YELLOW, ConfigError, FactError,
                     counterfactuals, dd_questions, decide, deciding_facts, eval_cond, item_color,
                     load_config, score)
from scoring.engine import DEFAULT_CONFIG

SHIPPED = load_config()
# Most tests check the rule logic in isolation, with a handful of facts. Version 1.3 requires 5 of 8 scorecard
# items (or one asset-level item) for Invest; that requirement is tested on its own (test_invest_needs_coverage)
# with SHIPPED, and switched off here so the other tests keep testing what they were written for.
cfg = dataclasses.replace(SHIPPED, thresholds={**SHIPPED.thresholds, "invest_min_items_known": 0,
                                               "invest_min_asset_known": 0})

# Three ordinary green mechanism-level items (3 pluses, 2 of them science): a handy base for rule tests.
THREE_GREEN = {
    "soc_last_new_moa_years": 20,                    # unmet need
    "genetic_support": "gwas",                       # human genetics, ordinary green
    "indication_ph3_outcomes_other_moa": 10,         # indication track record
    "indication_ph3_success_share_other_moa": 0.8,
}

FIVE_GREEN = {**THREE_GREEN, "endpoint_approval_precedent": True, "pillars_human": 3}
SIX_GREEN = {**FIVE_GREEN, "randomized_controlled": True, "endpoint_matches_mechanism": True}
RANK = {DNI: 0, CONDITIONAL: 1, INVEST: 2}


def verdict(facts, **kw):
    return score(cfg, facts, **kw).verdict


# --- three-valued logic -------------------------------------------------------
def test_unknown_atom_is_unknown():
    assert eval_cond({"fact": "grade5_related", "eq": True}, {}) is None


def test_known_operator_is_always_definite():
    assert eval_cond({"fact": "oncology", "known": False}, {}) is True
    assert eval_cond({"fact": "oncology", "known": True}, {}) is False
    assert eval_cond({"fact": "oncology", "known": True}, {"oncology": False}) is True


def test_all_any_not_with_unknown():
    t = {"fact": "oncology", "eq": True}
    u = {"fact": "rare_disease", "eq": True}
    facts = {"oncology": True}
    assert eval_cond({"any": [t, u]}, facts) is True
    assert eval_cond({"all": [t, u]}, facts) is None
    assert eval_cond({"not": u}, facts) is None
    assert eval_cond({"all": [{"fact": "oncology", "eq": False}, u]}, facts) is False


def test_default_makes_atom_definite():
    assert eval_cond({"fact": "oncology", "eq": False, "default": False}, {}) is True


# --- unknown does not kill ------------------------------------------------------
def test_empty_facts_is_dni_for_lack_of_support_without_any_rule():
    res = score(cfg, {})
    assert res.verdict == DNI and not res.fired and not res.kills
    assert set(res.colors.values()) == {UNKNOWN}
    assert "not enough confirmation" in res.reason


def test_unknown_asset_facts_do_not_fire_rules():
    res = score(cfg, THREE_GREEN)
    assert res.verdict == INVEST and res.fired == []


# --- every rule has a minimal fact set on which it fires ----------
RULE_FACTS = {
    "mechanism_refuted": {"moa_failures_efficacy_ph23": 2, "moa_successes_same_indication": 0},
    "me_too": {"approved_same_moa_count": 2, "differentiation_evidence": False},
    "me_too_unproven": {"approved_same_moa_count": 2},
    "drug_related_deaths": {"grade5_related": True, "life_threatening_indication": False},
    "crl_efficacy_safety": {"crl_reason": "efficacy"},
    "no_patent": {"patent_status": "expired"},
    "no_animal_response": {"animal_model_response": False},
    "modality_mismatch": {"modality_target_mismatch": True},
    "retraction_unreplicated": {"foundational_retraction": True, "independent_groups": 0},
    "license_not_exclusive": {"key_patent_license": "non_exclusive"},
    "data_integrity_letter": {"fda_data_integrity_letter": True},
    "one_mechanism_failure": {"moa_failures_efficacy_ph23": 1},
    "engaged_no_benefit": {"class_target_engagement_human": True, "moa_failures_efficacy_ph23": 1,
                           "approved_same_moa_count": 0},
    "deaths_fatal_disease": {"grade5_related": True, "life_threatening_indication": True},
    "class_withdrawal": {"class_withdrawal": True},
    "essential_gene_chronic": {"essential_gene": True, "chronic_non_oncology": True,
                               "moa_direction": "inhibit"},
    "target_safety_high": {"target_safety_flags": 4, "chronic_non_oncology": True},
    "toxicity_at_exposure": {"toxicity_at_efficacious_exposure": True},
    "crl_undisclosed": {"crl_reason": "undisclosed"},
    "adcom_negative": {"adcom_negative": True},
    "key_markets_gone": {"key_markets_outlicensed": True},
    "royalty_stack_high": {"royalty_stack_pct": 12},
    "posthoc_subgroup": {"posthoc_subgroup_thesis": True},
    "single_country": {"single_country_ex_us_pivotal": True},
    "endpoint_changed": {"primary_endpoint_changed": True},
    "single_arm_outside": {"single_arm_pivotal": True, "oncology": False, "rare_disease": False},
    "accelerated_no_confirmatory": {"accelerated_only": True, "confirmatory_trial_registered": False},
    "late_entry": {"years_behind_first_in_class": 6},
    "soc_loe": {"soc_loe_before_launch": True},
    "partner_returned": {"partner_returned_asset": True},
    "runway_short": {"runway_short": True},
    "me_too_differentiated": {"approved_same_moa_count": 2, "differentiation_claim": "efficacy"},
    "ph3_competitors": {"ph3_same_moa_count": 3},
    "class_safety_signal": {"class_safety_signal": True},
    "grade4_events": {"grade4_related": True},
    "target_safety_medium": {"target_safety_flags": 2},
    "crl_manufacturing": {"crl_reason": "manufacturing"},
    "complex_manufacturing_small": {"modality": "cell", "sponsor_size": "small"},
    "cmo_status": {"cmo_oai_or_warning_letter": True},
    "nonkey_licenses": {"nonkey_territories_outlicensed_count": 2},
    "royalty_stack_medium": {"royalty_stack_pct": 7},
    "no_replication": {"independent_groups": 0},
    "moa_safety_discontinuations": {"moa_discontinued_safety_count": 2},
    "moa_crl_safety": {"moa_crl_safety": True},
    "class_deaths": {"class_drug_related_deaths": True},
    "no_genetics_no_precedent": {"genetic_support": "none", "moa_clinical_precedent": "none"},
    "moa_safety_discontinuation": {"moa_discontinued_safety_count": 1},
    "moa_adcom_negative": {"moa_adcom_negative": True},
    "indication_accelerated_withdrawn": {"indication_accelerated_withdrawn": True},
    "indication_enrollment_risk": {"indication_enrollment_terminations_high": True},
    "under_enrollment": {"ph2_under_enrollment": True},
    "price_unrealistic": {"required_price_unrealistic": True},
    "medicare_negotiation": {"medicare_negotiation_exposure": True},
}


def test_every_rule_has_a_firing_example():
    assert set(RULE_FACTS) == {r["id"] for r in cfg.rules}


@pytest.mark.parametrize("rule_id", sorted(RULE_FACTS))
def test_rule_fires_on_its_facts(rule_id):
    assert rule_id in score(cfg, RULE_FACTS[rule_id]).fired


@pytest.mark.parametrize("rule_id", sorted(r["id"] for r in cfg.rules if r["tier"] == "kill"))
def test_kill_rule_overrides_any_number_of_greens(rule_id):
    res = score(cfg, {**SIX_GREEN, **RULE_FACTS[rule_id]})
    assert res.pos >= 5 and res.verdict == DNI and rule_id in res.kills


KILLS_NEEDING_ALL_FACTS = sorted(r["id"] for r in cfg.rules if r["tier"] == "kill")   # since 1.3 me_too too


@pytest.mark.parametrize("rule_id", KILLS_NEEDING_ALL_FACTS)
def test_kill_rule_never_fires_when_any_of_its_facts_is_unknown(rule_id):
    """Unknown does not kill: every fact in a kill rule's example is necessary."""
    example = RULE_FACTS[rule_id]
    for hidden in example:
        partial = {k: v for k, v in example.items() if k != hidden}
        assert rule_id not in score(cfg, partial).kills, f"{rule_id} fired without {hidden}"


def test_no_rule_fires_and_no_item_is_red_on_empty_facts():
    res = score(cfg, {}, "legacy6")
    assert res.fired == [] and res.kills == []
    assert set(res.colors.values()) == {UNKNOWN}


# --- every item reaches green and (if it has one) red ---------------------
ITEM_GREEN = {
    "unmet_need": {"approved_therapies_count": 0},
    "biology": {"moa_clinical_precedent": "approved_same"},
    "indication_history": {"indication_failures_other_moa_ph3_10y": 1},
    "does_what_claimed": {"pillars_human": 3},
    "mechanism_in_human": {"pillars_human": 3},
    "translation_chain": {"link_exposure": True, "link_target_engagement": True, "link_pd_response": True},
    "indication_track_record": {"indication_ph3_outcomes_other_moa": 6, "indication_ph3_success_share_other_moa": 0.7},
    "indication_track_record_with_red": {"indication_ph3_outcomes_other_moa": 6, "indication_ph3_success_share_other_moa": 0.7},
    "clinical_effect": {"own_ph2_positive": True},
    "trial_design": {"biomarker_selection": True, "endpoint_matches_mechanism": True},
    "regulatory_path": {"fda_designations_count": 1},
    "human_genetics": {"genetic_support": "gwas"},
    "clinical_precedent": {"moa_clinical_precedent": "positive_ph2_3_related"},
}
ITEM_RED = {
    "unmet_need": {"approved_therapies_count": 4, "soc_last_new_moa_years": 2},
    "biology": {"genetic_support": "contradicts"},
    "indication_history": {"indication_graveyard": True},
    "does_what_claimed": {"own_trial_failed_efficacy": True},
    "mechanism_in_human": {"pillars_human": 0, "phase": "ph2"},
    "translation_chain": {"link_target_engagement": False},
    "indication_track_record": {"indication_graveyard": True},
    "indication_track_record_with_red": {"indication_ph3_outcomes_other_moa": 5, "indication_ph3_success_share_other_moa": 0.39},
    "clinical_effect": {"own_trial_failed_efficacy": True},
    "trial_design": {"open_label_subjective_endpoint": True},
    "regulatory_path": {"accepted_endpoint_exists": False},
    "human_genetics": {"genetic_support": "contradicts"},
}


def test_item_tables_cover_all_items():
    assert set(ITEM_GREEN) == set(cfg.items)
    assert set(ITEM_RED) == {i for i, it in cfg.items.items() if "red" in it}


@pytest.mark.parametrize("item_id", sorted(ITEM_GREEN))
def test_item_green(item_id):
    assert item_color(cfg.items[item_id], ITEM_GREEN[item_id]) == GREEN


@pytest.mark.parametrize("item_id", sorted(ITEM_RED))
def test_item_red(item_id):
    assert item_color(cfg.items[item_id], ITEM_RED[item_id]) == RED


def test_red_wins_over_green():
    facts = {"own_trial_failed_efficacy": True, "drug_approved_other_indication": True}
    assert item_color(cfg.items["does_what_claimed"], facts) == RED


def test_positive_phase2_or_approval_protects_from_zero_pillars_red():
    item = cfg.items["does_what_claimed"]
    assert item_color(item, {"own_ph2_positive": True, "phase": "ph3", "pillars_human": 0}) == GREEN
    assert item_color(item, {"drug_approved_other_indication": True, "phase": "ph2",
                             "pillars_human": 0}) == GREEN
    assert item_color(item, {"own_ph2_positive": True, "own_trial_failed_efficacy": True}) == RED


def test_indication_track_record_colours():
    item = cfg.items["indication_track_record"]
    def col(n, share, **kw):
        return item_color(item, {"indication_ph3_outcomes_other_moa": n,
                                 "indication_ph3_success_share_other_moa": share, **kw})
    assert col(10, 0.8) == GREEN and col(10, 0.7) == GREEN
    assert col(10, 0.5) == YELLOW and col(4, 0.9) == YELLOW and col(4, 0.0) == YELLOW
    assert col(5, 0.39) == YELLOW and col(10, 0.8, indication_graveyard=True) == RED
    res = score(cfg, {"approved_therapies_count": 0, "indication_ph3_outcomes_other_moa": 8,
                      "indication_ph3_success_share_other_moa": 0.75})
    assert res.colors["unmet_need"] == GREEN and res.colors["indication_track_record"] == GREEN


def test_translation_chain_links():
    item = cfg.items["translation_chain"]
    full = {"link_exposure": True, "link_target_engagement": True, "link_pd_response": True}
    assert item_color(item, full) == GREEN
    assert item_color(item, {"link_exposure": True, "link_target_engagement": True}) == YELLOW
    assert item_color(item, {"animal_model_response": True}) == YELLOW
    assert item_color(item, {**full, "link_pd_response": False}) == RED            # link broken
    assert item_color(item, {"link_target_engagement": False, "own_ph2_positive": True}) == YELLOW
    # an approval elsewhere protects from red but gives no green: it is not evidence for this disease
    assert item_color(item, {"link_target_engagement": False, "drug_approved_other_indication": True}) == YELLOW
    assert item_color(item, {"drug_approved_other_indication": True}) == YELLOW
    assert item_color(item, {"phase": "ph2"}) == UNKNOWN               # data not entered give no red
    assert item_color(item, {"phase": "ph3", "pillars_human": 0}) == RED   # only an explicit zero
    assert score(cfg, full).derived["pillars_human"] == 3
    assert item_color(item, {"phase": "ph1"}) == UNKNOWN


def test_causal_preclinical_and_correlational_evidence_are_yellow_at_most():
    item = cfg.items["human_genetics"]
    for facts in ({"perturbation_evidence": True}, {"correlational_evidence": True},
                  {"perturbation_evidence": True, "correlational_evidence": True, "genetic_support": "none"}):
        assert item_color(item, facts) == YELLOW


def test_invest_requires_a_science_green():
    commercial_only = {"approved_therapies_count": 0, "endpoint_approval_precedent": True}
    res = score(cfg, commercial_only)
    assert res.pos == 2 and res.verdict == DNI and "science" in res.reason
    assert res.grounds == "insufficient_evidence"
    assert score(cfg, commercial_only, thresholds={"require_mechanism_green": False,
                                                   "min_science_pos_invest": 0}).verdict == INVEST
    assert verdict({**commercial_only, "genetic_support": "mendelian"}) == INVEST
    # a green indication track record is a property of the disease, not mechanism evidence
    disease_only = {"approved_therapies_count": 0, "indication_ph3_outcomes_other_moa": 9,
                    "indication_ph3_success_share_other_moa": 0.9}
    assert score(cfg, disease_only).pos == 2 and verdict(disease_only) == DNI
    assert res.axes["science"]["rating"] == "weak" and res.axes["commercial"]["rating"] == "strong"


def test_axes_split_items_and_rules():
    res = score(cfg, {**FIVE_GREEN, "class_safety_signal": True, "ph3_same_moa_count": 3})
    assert res.axes["science"] == {"greens": 3, "reds": 0, "strong": 0, "warnings": 1, "rating": "strong"}
    assert res.axes["commercial"] == {"greens": 2, "reds": 0, "strong": 0, "warnings": 1, "rating": "strong"}
    weak = score(cfg, {**THREE_GREEN, "class_withdrawal": True})
    assert weak.axes["science"]["rating"] == "weak"


def test_no_genetics_no_precedent_needs_both_facts():
    assert "no_genetics_no_precedent" not in score(cfg, {"genetic_support": "none"}).fired
    # approval of the target only in an unrelated area is not a precedent (validated on pairs)
    assert "no_genetics_no_precedent" in score(cfg, {"genetic_support": "none",
                                                     "moa_clinical_precedent": "approved_unrelated"}).fired
    assert "no_genetics_no_precedent" in score(cfg, {"genetic_support": "other_disease",
                                                     "moa_clinical_precedent": "none"}).fired
    assert "no_genetics_no_precedent" not in score(cfg, {"genetic_support": "none",
                                                         "moa_clinical_precedent": "approved_related"}).fired
    assert "no_genetics_no_precedent" not in score(cfg, {"genetic_support": "gwas",
                                                         "moa_clinical_precedent": "none"}).fired


def test_safety_discontinuations_ladder_and_cluster():
    one = score(cfg, {**THREE_GREEN, "moa_discontinued_safety_count": 1})
    two = score(cfg, {**THREE_GREEN, "moa_discontinued_safety_count": 2, "class_safety_signal": True})
    assert one.neg == 1 and two.neg == 2 and "class_safety_signal" in two.suppressed


def test_route_of_administration_sets_price_channel():
    base = {**THREE_GREEN, "approved_therapies_count": 3, "approved_same_moa_count": 2,
            "differentiation_claim": "price_only"}
    assert "me_too_unproven" in score(cfg, {**base, "route_of_administration": "oral"}).fired
    assert "me_too_unproven" not in score(cfg, {**base, "route_of_administration": "iv_infusion"}).fired


def test_top_dd_questions_start_with_kill_evidence_and_are_capped():
    from scoring import top_dd_questions
    qs = top_dd_questions(cfg, THREE_GREEN)
    assert 5 <= len(qs) <= 10 and qs[0]["question"] == "What evidence would kill the program?"
    assert qs[0]["kill_evidence"] and all(q["critical"] for q in qs[:3])


def test_one_endpoint_precedent_gives_one_green_not_two():
    res = score(cfg, {"randomized_controlled": True, "endpoint_approval_precedent": True})
    assert res.greens == 1 and res.verdict == DNI


def test_biology_ceiling_yellow_without_genetics_or_precedent():
    for facts in ({"genetic_support": "none"}, {"genetic_support": "other_disease"},
                  {"moa_clinical_precedent": "approved_unrelated"}):
        assert item_color(cfg.items["biology"], facts) == YELLOW


def test_phase_alone_does_not_make_item_known():
    assert item_color(cfg.items["does_what_claimed"], {"phase": "ph1"}) == UNKNOWN
    assert item_color(cfg.items["does_what_claimed"], {"animal_model_response": True}) == YELLOW


def test_zero_pillars_red_only_from_phase2():
    item = cfg.items["does_what_claimed"]
    assert item_color(item, {"pillars_human": 0, "phase": "ph1"}) == YELLOW
    assert item_color(item, {"pillars_human": 0, "phase": "ph2"}) == RED


# --- verdict arithmetic -----------------------------------------------------
def test_decide_table():
    thr = cfg.thresholds
    assert decide(2, 0, False, thr)[0] == INVEST
    assert decide(1, 0, False, thr)[0] == DNI            # one green: not enough confirmation
    assert decide(3, 2, False, thr)[0] == CONDITIONAL    # mixed picture
    assert decide(3, 3, False, thr)[0] == DNI
    assert decide(6, 4, False, thr)[0] == DNI            # accumulation, pluses do not compensate
    assert decide(6, 0, True, thr)[0] == DNI             # kill


def test_early_asset_needs_two_science_points_for_invest():
    early = {"approved_therapies_count": 0, "phase": "preclinical"}
    one = score(cfg, {**early, "genetic_support": "gwas"})
    assert one.verdict == CONDITIONAL and one.grounds == "science_short"
    assert verdict({**early, "genetic_support": "mendelian"}) == INVEST
    assert verdict({**early, "genetic_support": "gwas", "moa_clinical_precedent": "approved_related"}) == INVEST
    assert verdict({"genetic_support": "gwas"}) == DNI          # one plus: not enough confirmation


def test_min_greens_uses_count_of_greens_not_weighted_points():
    thr = cfg.thresholds
    assert decide(2, 1, False, thr, greens=1)[0] == DNI
    assert decide(3, 2, False, thr, greens=3)[0] == CONDITIONAL


def test_accumulation_of_two_strong_minuses_beats_five_greens():
    facts = {**FIVE_GREEN,
             "moa_failures_efficacy_ph23": 1,         # strong minus, no cluster
             "key_markets_outlicensed": True}         # strong minus, cluster licensing
    res = score(cfg, facts)
    assert res.pos == 5 and res.neg == 4 and res.verdict == DNI and not res.kills


def test_red_item_costs_two():
    res = score(cfg, {**THREE_GREEN, "accepted_endpoint_exists": False})
    assert res.colors["regulatory_path"] == RED and (res.pos, res.neg, res.verdict) == (3, 2, CONDITIONAL)
    # red instead of green: the item loses a plus and adds two minuses
    res = score(cfg, {**THREE_GREEN, "indication_graveyard": True})
    assert res.colors["indication_track_record"] == RED and (res.pos, res.neg, res.verdict) == (2, 2, DNI)


# --- clusters ----------------------------------------------------------------
CLUSTER_CASE = {**THREE_GREEN, "class_safety_signal": True, "target_safety_flags": 2,
                "ph3_same_moa_count": 3}


def test_clusters_count_strongest_once():
    res = score(cfg, CLUSTER_CASE)
    assert res.neg == 2 and res.verdict == CONDITIONAL
    assert set(res.fired) == {"class_safety_signal", "target_safety_medium", "ph3_competitors"}
    assert len(res.suppressed) == 1 and set(res.suppressed.values()) == {"cluster:safety"}


def test_without_clusters_same_case_is_dni():
    res = score(cfg, CLUSTER_CASE, use_clusters=False)
    assert res.neg == 3 and res.verdict == DNI


def test_cluster_takes_strong_over_warning():
    res = score(cfg, {**THREE_GREEN, "class_withdrawal": True, "class_safety_signal": True})
    assert res.neg == 2 and ("rule:class_withdrawal", 2) in res.counted
    assert res.suppressed == {"class_safety_signal": "cluster:safety"}


def test_red_item_absorbs_rule_about_the_same_event():
    # failure in all patients + post hoc subgroup: one event, 2 minuses, not 4
    res = score(cfg, {**THREE_GREEN, "own_trial_failed_efficacy": True, "posthoc_subgroup_thesis": True})
    assert res.neg == 2 and res.suppressed == {"posthoc_subgroup": "item:clinical_effect"}
    alone = score(cfg, {**THREE_GREEN, "posthoc_subgroup_thesis": True})
    assert alone.neg == 2 and alone.suppressed == {}
    # open-label single-arm design: the red 'Design' item absorbs the rule
    single_arm = {**THREE_GREEN, "single_arm_pivotal": True, "oncology": False, "rare_disease": False}
    res = score(cfg, {**single_arm, "open_label_subjective_endpoint": True})
    assert res.neg == 2 and res.suppressed == {"single_arm_outside": "item:trial_design"}


def test_absorption_needs_the_same_event_not_just_a_red_item():
    # the item is red because of zero pillars, not the own failure: the subgroup counts separately
    res = score(cfg, {**THREE_GREEN, "posthoc_subgroup_thesis": True, "pillars_human": 0, "phase": "ph2"})
    assert res.colors["translation_chain"] == RED and res.neg == 4 and res.suppressed == {}
    # the item is red because of a mismatched endpoint, not the open-label design
    res = score(cfg, {**THREE_GREEN, "single_arm_pivotal": True, "oncology": False, "rare_disease": False,
                      "endpoint_matches_mechanism": False})
    assert res.colors["trial_design"] == RED and res.neg == 4 and res.suppressed == {}


def test_adding_the_absorbing_event_never_lowers_minuses():
    """The item is already red for another reason: the event absorbs nothing."""
    pairs = [
        ({**THREE_GREEN, "posthoc_subgroup_thesis": True, "pillars_human": 0, "phase": "ph2"},
         {"own_trial_failed_efficacy": True}),
        ({**THREE_GREEN, "single_arm_pivotal": True, "oncology": False, "rare_disease": False,
          "endpoint_matches_mechanism": False}, {"open_label_subjective_endpoint": True}),
        ({**THREE_GREEN, "posthoc_subgroup_thesis": True}, {"own_trial_failed_efficacy": True}),
        ({**THREE_GREEN, "single_arm_pivotal": True, "oncology": False, "rare_disease": False},
         {"open_label_subjective_endpoint": True}),
    ]
    for base, event in pairs:
        before, after = score(cfg, base), score(cfg, {**base, **event})
        assert after.neg >= before.neg and RANK[after.verdict] <= RANK[before.verdict], (base, event)
    assert score(cfg, {**pairs[0][0], **pairs[0][1]}).neg == 4


def test_absorbed_rule_counts_again_when_item_is_disabled():
    facts = {**THREE_GREEN, "own_trial_failed_efficacy": True, "posthoc_subgroup_thesis": True}
    res = score(cfg, facts, disabled_items=["clinical_effect"])
    assert res.neg == 2 and res.suppressed == {}


def test_single_arm_and_accelerated_share_a_cluster():
    res = score(cfg, {**FIVE_GREEN, "single_arm_pivotal": True, "oncology": False, "rare_disease": False,
                      "accelerated_only": True, "confirmatory_trial_registered": False})
    assert res.neg == 2 and res.verdict == INVEST


def test_absorption_never_improves_verdict():
    base = {**THREE_GREEN, "posthoc_subgroup_thesis": True}
    worse = {**base, "own_trial_failed_efficacy": True}
    assert RANK[verdict(worse)] <= RANK[verdict(base)]


# --- me-too (since 1.3: a kill only when differentiation was checked and refuted) ----------------------------
@pytest.mark.parametrize("extra, expected", [
    ({}, "unproven"),                                                  # differentiation not claimed
    ({"differentiation_claim": "none"}, "unproven"),
    ({"differentiation_claim": "convenience"}, "unproven"),            # dosing regimen only (Trulicity)
    ({"differentiation_claim": "price_only"}, "unproven"),             # cheaper, but the channel is not direct
    ({"differentiation_claim": "price_only", "price_channel_direct": True}, "differentiated"),
    ({"differentiation_claim": "structural_cost"}, "differentiated"),
    ({"differentiation_claim": "efficacy"}, "differentiated"),
    ({"differentiation_claim": "safety"}, "differentiated"),
    ({"differentiation_claim": "efficacy", "differentiation_evidence": True}, "differentiated"),
    ({"differentiation_claim": "efficacy", "differentiation_evidence": False}, "kill"),   # claim refuted
])
def test_me_too(extra, expected):
    res = score(cfg, {**THREE_GREEN, "approved_same_moa_count": 2, **extra})
    assert ("me_too" in res.kills) is (expected == "kill")
    assert ("me_too_unproven" in res.fired) is (expected in ("unproven", "kill"))
    if expected == "differentiated":
        assert "me_too_differentiated" in res.fired and res.verdict == INVEST
    if expected == "unproven":                       # a strong minus (2 points), not a kill: strong science can still win
        assert not res.kills and ("rule:me_too_unproven", 2) in res.counted


def test_trulicity_at_phase3_is_not_killed():
    """Review F38: the old kill rule gave Do Not Invest for a $5.69B blockbuster (third-fourth GLP-1, convenience)."""
    res = score(cfg, {**THREE_GREEN, "approved_same_moa_count": 3, "differentiation_claim": "convenience",
                      "phase": "ph3"})
    assert not res.kills and "me_too_unproven" in res.fired


def test_one_approved_same_moa_is_not_me_too():
    assert "me_too" not in score(cfg, {"approved_same_moa_count": 1}).fired


# --- deaths, CRL, mechanism failures -------------------------------------------
def test_deaths_depend_on_indication():
    kill = score(cfg, {**THREE_GREEN, "grade5_related": True, "life_threatening_indication": False})
    assert kill.kills == ["drug_related_deaths"]
    for context in ({"life_threatening_indication": True}, {"oncology": True}, {}, {"oncology": False}):
        soft = score(cfg, {**THREE_GREEN, "grade5_related": True, **context})
        assert not soft.kills and soft.fired == ["deaths_fatal_disease"]
        assert soft.neg == 2 and soft.verdict == CONDITIONAL


@pytest.mark.parametrize("reason, kills, neg", [
    ("efficacy", True, 0), ("safety", True, 0), ("undisclosed", False, 2),
    ("manufacturing", False, 1), ("none", False, 0),
])
def test_crl_by_reason(reason, kills, neg):
    res = score(cfg, {**THREE_GREEN, "crl_reason": reason})
    assert bool(res.kills) is kills and res.neg == neg


def test_milder_crl_reason_never_gives_worse_verdict():
    order = ["none", "manufacturing", "undisclosed", "efficacy"]        # from the mildest
    rng = random.Random(7)
    extras = [{"adcom_negative": True}, {"cmo_oai_or_warning_letter": True}, {"pillars_human": 3},
              {"class_safety_signal": True}, {"moa_failures_efficacy_ph23": 1},
              {"indication_failures_other_moa_ph3_10y": 0}]
    for _ in range(200):
        base = dict(THREE_GREEN)
        for extra in rng.sample(extras, rng.randint(0, len(extras))):
            base.update(extra)
        ranks = [RANK[verdict({**base, "crl_reason": r})] for r in order]
        assert ranks == sorted(ranks, reverse=True), (base, ranks)


def test_mechanism_failures_ladder():
    def run(failures, successes=None):
        facts = {**THREE_GREEN, "moa_failures_efficacy_ph23": failures}
        if successes is not None:
            facts["moa_successes_same_indication"] = successes
        return score(cfg, facts)
    assert run(1).fired == ["one_mechanism_failure"] and run(1).neg == 2
    assert run(1, 0).fired == ["one_mechanism_failure"]
    assert run(2).fired == ["one_mechanism_failure"] and not run(2).kills   # nothing known about successes
    assert run(2, 0).kills == ["mechanism_refuted"] and run(2, 0).fired == ["mechanism_refuted"]
    assert run(2, 1).fired == [] and run(1, 1).fired == []


# --- "what would change the verdict" and DD questions ---------------------------------------
def test_counterfactual_finds_hidden_and_added_facts():
    facts = {**THREE_GREEN, "moa_failures_efficacy_ph23": 1}      # 3 − 2 = +1 → Conditional
    assert verdict(facts) == CONDITIONAL
    cfs = counterfactuals(cfg, facts)
    as_set = {(c["fact"], c["action"], c["to"], c["verdict_to"]) for c in cfs}
    assert ("moa_failures_efficacy_ph23", "hide", None, INVEST) in as_set
    assert ("patent_status", "set", "none", DNI) in as_set
    assert ("moa_successes_same_indication", "set", 1, INVEST) in as_set


def test_hiding_fact_matches_scoring_without_it():
    facts = {**THREE_GREEN, "class_withdrawal": True}
    for cf in counterfactuals(cfg, facts):
        changed = {k: v for k, v in facts.items() if k != cf["fact"]}
        if cf["to"] is not None:
            changed[cf["fact"]] = cf["to"]
        assert verdict(changed) == cf["verdict_to"]


def test_dd_questions_cover_unknown_asset_facts_and_flag_critical():
    qs = dd_questions(cfg, THREE_GREEN)
    by_fact = {f: q for q in qs for f in q["facts"]}
    assert by_fact["patent_status"]["critical"] is True
    assert qs[0]["critical"] is True                               # critical ones come first
    assert len({q["question"] for q in qs}) == len(qs)             # each question once
    known = dd_questions(cfg, {**THREE_GREEN, "patent_status": "granted"})
    assert "patent_status" not in {f for q in known for f in q["facts"]}
    assert all(cfg.facts[f]["scope"] == "asset" for q in qs for f in q["facts"])


def test_every_unknown_asset_fact_that_can_flip_the_verdict_is_asked():
    asked = {f for q in dd_questions(cfg, THREE_GREEN) for f in q["facts"]}
    flipping = {c["fact"] for c in counterfactuals(cfg, THREE_GREEN)
                if c["scope"] == "asset" and c["from"] is None}
    assert flipping and flipping <= asked
    for must in ("fda_data_integrity_letter", "adcom_negative", "own_trial_failed_efficacy"):
        assert must in asked
    # the stage can also flip the verdict, so it is asked about
    facts = {"pillars_human": 0, "genetic_support": "gwas", "soc_last_new_moa_years": 20}
    assert verdict(facts) == CONDITIONAL and verdict({**facts, "phase": "ph2"}) == DNI
    phase_q = next(q for q in dd_questions(cfg, facts) if "phase" in q["facts"])
    assert phase_q["critical"] is True


# --- evidence: only the facts that actually decided --------------------------------------
def test_evidence_lists_only_deciding_facts():
    res = score(cfg, {"own_ph2_positive": True, "pillars_human": 1, "drug_approved_other_indication": False})
    assert res.colors["clinical_effect"] == GREEN and res.colors["translation_chain"] == YELLOW
    assert res.evidence["clinical_effect"] == ["own_ph2_positive"]
    res = score(cfg, {"approved_therapies_count": 0, "soc_last_new_moa_years": 3,
                      "active_comparator_exists": True})
    assert res.evidence["unmet_need"] == ["approved_therapies_count"]
    cond = {"all": [{"fact": "oncology", "eq": True}, {"fact": "rare_disease", "eq": True}]}
    assert deciding_facts(cond, {"oncology": True, "rare_disease": False}) == []
    assert deciding_facts(cond, {"oncology": True, "rare_disease": False}, target=False) == ["rare_disease"]


# --- input checks and function purity -----------------------------------------
def test_unknown_fact_name_is_an_error():
    with pytest.raises(FactError):
        score(cfg, {"patent_statu": "none"})


@pytest.mark.parametrize("facts", [
    {"crl_reason": "bad"}, {"crl_reason": "unknown"}, {"grade5_related": "yes"},
    {"approved_therapies_count": 1.5}, {"pillars_human": True},
    {"pillars_human": 7}, {"pillars_human": -1}, {"target_safety_flags": 99},
    {"independent_groups": -3}, {"royalty_stack_pct": float("inf")}, {"royalty_stack_pct": float("nan")},
    {"royalty_stack_pct": 120},
])
def test_wrong_values_are_errors(facts):
    with pytest.raises(FactError):
        score(cfg, facts)


@pytest.mark.parametrize("facts", [
    {"oncology": True, "chronic_non_oncology": True},
    {"single_arm_pivotal": True, "randomized_controlled": True},
    {"approved_therapies_count": 0, "approved_same_moa_count": 2},
    {"approved_therapies_count": 1, "approved_same_moa_count": 3},
    {"approved_therapies_count": 0, "indication_new_moa_approvals_10y": 2},
    {"soc_last_new_moa_years": 20, "indication_new_moa_approvals_10y": 2},
    {"moa_clinical_precedent": "approved_same", "approved_same_moa_count": 0},
    {"moa_clinical_precedent": "approved_same", "moa_successes_same_indication": 0},
    {"approved_same_moa_count": 2, "moa_successes_same_indication": 0},
    {"accepted_endpoint_exists": False, "endpoint_approval_precedent": True},
    {"phase": "preclinical", "own_ph2_positive": True},
    {"approved_therapies_count": 0, "moa_clinical_precedent": "approved_same"},     # through a derived fact
])
def test_contradictory_facts_are_errors(facts):
    with pytest.raises(FactError, match="Contradictory"):
        score(cfg, facts)


# --- derived facts: the verdict does not depend on whether an obvious consequence is given ---------
@pytest.mark.parametrize("base, implied", [
    ({"soc_last_new_moa_years": 20, "genetic_support": "mendelian", "approved_therapies_count": 3,
      "approved_same_moa_count": 1, "moa_clinical_precedent": "approved_same",
      "moa_failures_efficacy_ph23": 1}, {"moa_successes_same_indication": 1}),
    ({"approved_therapies_count": 0, "genetic_support": "mendelian",
      "indication_failures_other_moa_ph3_10y": 3}, {"indication_new_moa_approvals_10y": 0}),
    ({"approved_therapies_count": 0, "ph3_same_moa_count": 0, "genetic_support": "none"},
     {"approved_same_moa_count": 0}),
    ({**THREE_GREEN, "chronic_non_oncology": True, "single_arm_pivotal": True, "rare_disease": False},
     {"oncology": False}),
    ({**THREE_GREEN, "oncology": True, "grade5_related": True}, {"life_threatening_indication": True}),
    ({"endpoint_approval_precedent": True}, {"accepted_endpoint_exists": True}),
])
def test_spelling_out_an_implied_fact_changes_nothing(base, implied):
    for variant in ("base7", "legacy6"):
        a, b = score(cfg, base, variant), score(cfg, {**base, **implied}, variant)
        assert (a.verdict, a.pos, a.neg, a.fired) == (b.verdict, b.pos, b.neg, b.fired)
        for name, value in implied.items():
            assert a.derived[name] == value and name not in b.derived


def test_success_implied_by_precedent_cancels_mechanism_failure_penalty():
    facts = {**THREE_GREEN, "moa_clinical_precedent": "approved_same", "moa_failures_efficacy_ph23": 2}
    res = score(cfg, facts)
    assert res.fired == [] and res.derived == {"moa_successes_same_indication": 1,
                                               "indication_new_moa_approvals_10y": 0}


def test_evidence_names_explicit_sources_not_derived_facts():
    res = score(cfg, {"grade5_related": True, "oncology": True})
    assert res.derived["life_threatening_indication"] is True
    assert res.derived_from["life_threatening_indication"] == ["oncology"]
    assert res.evidence["deaths_fatal_disease"] == ["grade5_related", "oncology"]
    res = score(cfg, {"approved_therapies_count": 3, "approved_same_moa_count": 1})
    assert res.evidence["clinical_precedent"] == ["approved_same_moa_count"]
    for facts in ({**THREE_GREEN, "approved_therapies_count": 4, "approved_same_moa_count": 2},
                  {"approved_therapies_count": 0, "indication_failures_other_moa_ph3_10y": 3}):
        res = score(cfg, facts)
        for names in res.evidence.values():
            assert set(names) <= set(facts)


def test_unmet_need_red_does_not_depend_on_spelling_out_total_count():
    base = {"genetic_support": "gwas", "endpoint_approval_precedent": True, "pillars_human": 3,
            "soc_last_new_moa_years": 2, "approved_same_moa_count": 3, "differentiation_claim": "efficacy"}
    a, b = score(cfg, base), score(cfg, {**base, "approved_therapies_count": 3})
    assert a.colors["unmet_need"] == RED and (a.verdict, a.pos, a.neg) == (b.verdict, b.pos, b.neg)


def test_same_moa_approval_implies_precedent():
    res = score(cfg, {"approved_therapies_count": 3, "approved_same_moa_count": 2,
                      "differentiation_claim": "safety"})
    assert res.derived["moa_clinical_precedent"] == "approved_same" and res.colors["clinical_precedent"] == GREEN
    with pytest.raises(FactError):
        score(cfg, {"approved_same_moa_count": 2, "moa_clinical_precedent": "none"})


def test_explicit_fact_is_never_overwritten_by_derivation():
    res = score(cfg, {"oncology": True, "life_threatening_indication": False, "grade5_related": True})
    assert "life_threatening_indication" not in res.derived
    assert res.kills == ["drug_related_deaths"]          # indolent tumour: a drug-related death kills


def test_counterfactual_tries_all_enum_values_when_one_is_contradictory():
    facts = {"approved_therapies_count": 0, "ph3_same_moa_count": 0}
    assert verdict(facts) == DNI
    cfs = counterfactuals(cfg, facts)
    hits = {(c["fact"], c["to"]) for c in cfs if c["verdict_to"] == INVEST}
    softer = {(c["fact"], c["to"]) for c in cfs if c["verdict_to"] == CONDITIONAL}
    assert ("genetic_support", "mendelian") in hits
    assert ("moa_clinical_precedent", "approved_related") in softer      # one science plus: Conditional
    assert ("moa_clinical_precedent", "approved_same") not in hits | softer   # contradicts zero approved


def test_counterfactual_cannot_hide_a_derived_fact():
    cfs = counterfactuals(cfg, {"approved_therapies_count": 0, "genetic_support": "gwas"})
    assert not [c for c in cfs if c["action"] == "hide" and c["fact"] == "approved_same_moa_count"]


# --- full list of places where unknown is treated in a specific way (mirror of the README table) --
def _defaults(cond, acc):
    if "all" in cond or "any" in cond:
        for sub in cond.get("all", []) + cond.get("any", []):
            _defaults(sub, acc)
    elif "not" in cond:
        _defaults(cond["not"], acc)
    elif "default" in cond or "known" in cond:
        acc.add(cond["fact"])


def test_defaults_are_exactly_the_documented_ones():
    found = {}
    for rule in cfg.rules:
        acc = set()
        _defaults(rule["when"], acc)
        if acc:
            found[rule["id"]] = acc
    for item in cfg.items.values():
        for color in ("red", "green"):
            acc = set()
            _defaults(item.get(color, {"all": []}) if color in item else {"all": []}, acc)
            if acc:
                found[f"{item['id']}.{color}"] = acc
    assert found == {
        "me_too_unproven": {"differentiation_claim", "differentiation_evidence", "price_channel_direct"},
        "me_too_differentiated": {"differentiation_evidence"},
        "one_mechanism_failure": {"moa_successes_same_indication"},
        "deaths_fatal_disease": {"life_threatening_indication"},
        "late_entry": {"approved_same_moa_count"},
        "ph3_competitors": {"approved_same_moa_count"},
        "no_replication": {"independent_groups"},
        "complex_manufacturing_small": {"sponsor_size"},
        "grade4_events": {"life_threatening_indication"},
        "indication_history.green": {"indication_graveyard"},
        "does_what_claimed.red": {"own_ph2_positive", "drug_approved_other_indication"},
        "mechanism_in_human.red": {"own_ph2_positive", "drug_approved_other_indication"},
        "translation_chain.red": {"own_ph2_positive", "drug_approved_other_indication"},
        "indication_track_record.green": {"indication_graveyard"},
        "indication_track_record_with_red.green": {"indication_graveyard"},
        "trial_design.green": {"dose_ranging_done"},
    }
    kills_with_defaults = {r["id"] for r in cfg.rules if r["tier"] == "kill"} & set(found)
    assert kills_with_defaults == set()                 # since 1.3 no kill rule has a default


def test_typos_in_options_are_errors():
    with pytest.raises(ConfigError):
        score(cfg, {}, disabled_rules=["no_patnet"])
    with pytest.raises(ConfigError):
        score(cfg, {}, disabled_items=["biologyy"])
    with pytest.raises(ConfigError):
        score(cfg, {}, thresholds={"invest_margn": 5})
    with pytest.raises(ConfigError):
        score(cfg, {}, ["unmet_need", "nope"])


# --- config checks ------------------------------------------------------
def _load_with(tmp_path, mutate):
    raw = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return load_config(path)


def _rule(raw, rule_id):
    return next(r for r in raw["rules"] if r["id"] == rule_id)


@pytest.mark.parametrize("mutate", [
    lambda raw: _rule(raw, "no_patent").__setitem__("when", {"fact": "patent_status", "in": "none"}),
    lambda raw: _rule(raw, "no_patent").__setitem__("when", {"fact": "patent_status", "eq": "nope"}),
    lambda raw: _rule(raw, "no_patent").__setitem__("when", {"fact": "patent_statu", "eq": "none"}),
    lambda raw: _rule(raw, "no_patent").__setitem__("when", {"fact": "patent_status", "eq": "none", "defualt": "none"}),
    lambda raw: _rule(raw, "no_patent").__setitem__("when", {"fact": "patent_status", "eq": "none", "default": "nope"}),
    lambda raw: _rule(raw, "no_patent").__setitem__("when", {"fact": "patent_status", "ge": "none"}),
    lambda raw: _rule(raw, "adcom_negative").__setitem__("when", {"fact": "adcom_negative", "eq": "true"}),
    lambda raw: _rule(raw, "adcom_negative").__setitem__(
        "when", {"all": [{"fact": "adcom_negative", "eq": True}], "any": [{"fact": "oncology", "eq": True}]}),
    lambda raw: _rule(raw, "no_patent").__setitem__("cluster", "licensing"),
    lambda raw: _rule(raw, "adcom_negative").__setitem__("cluster", "nope"),
    lambda raw: raw["scorecard"].append(dict(raw["scorecard"][0])),
    lambda raw: raw["rules"].append(dict(raw["rules"][0])),
    lambda raw: raw["facts"]["crl_reason"].__setitem__("probes", ["nope"]),
    lambda raw: raw["facts"]["adcom_negative"].pop("dd"),
    lambda raw: _rule(raw, "posthoc_subgroup").__setitem__("clutser", "trial_conduct"),
    lambda raw: _rule(raw, "posthoc_subgroup").__setitem__("absorbd_by", "does_what_claimed"),
    lambda raw: _rule(raw, "posthoc_subgroup").pop("absorbed_when"),
    lambda raw: raw["facts"]["pillars_human"].__setitem__("mx", 3),
    lambda raw: raw["facts"]["pillars_human"].__setitem__("probes", [0, 9]),
    lambda raw: _rule(raw, "target_safety_medium").__setitem__("when", {"fact": "target_safety_flags", "ge": 9}),
    lambda raw: raw["constraints"][0].pop("message"),
    lambda raw: raw["constraints"][0].__setitem__("mesage", "x"),
    lambda raw: raw["derive"][0].__setitem__("set", {"approved_same_moa_count": -1}),
    lambda raw: raw["derive"][0].__setitem__("set", {"nope": 0}),
    lambda raw: raw["derive"].append({"when": {"fact": "oncology", "eq": True},
                                      "set": {"approved_same_moa_count": 5}}),
    lambda raw: raw.__setitem__("derives", raw.pop("derive")),
    lambda raw: raw.__setitem__("constrains", raw.pop("constraints")),
    lambda raw: raw["scorecard"][0].__setitem__("gren", {"fact": "oncology", "eq": True}),
    lambda raw: _rule(raw, "no_patent").__setitem__("when", {"fact": "patent_status", "gt": {"fact": "phase"}}),
    lambda raw: raw["verdict"].pop("min_pos_conditional"),
    lambda raw: raw["variants"].__setitem__("x", ["unmet_need", "nope"]),
])
def test_broken_config_is_rejected(tmp_path, mutate):
    with pytest.raises(ConfigError):
        _load_with(tmp_path, mutate)


def test_unmodified_copy_of_config_loads(tmp_path):
    assert len(_load_with(tmp_path, lambda raw: None).rules) == len(cfg.rules)


def test_none_means_unknown():
    assert score(cfg, {"patent_status": None}).as_dict() == score(cfg, {}).as_dict()


def test_pure_and_deterministic():
    facts = {**CLUSTER_CASE, "crl_reason": "manufacturing"}
    assert score(cfg, facts).fired            # the example is not empty
    snapshot = copy.deepcopy(facts)
    first = score(cfg, facts).as_dict()
    assert score(cfg, facts).as_dict() == first and facts == snapshot
    reordered = dict(reversed(list(facts.items())))
    again = score(cfg, reordered).as_dict()
    assert (again["verdict"], again["pos"], again["neg"]) == (first["verdict"], first["pos"], first["neg"])


# --- ablation and variants ---------------------------------------------------------
def test_disabling_rule_and_item():
    facts = {**THREE_GREEN, "patent_status": "none"}
    assert verdict(facts) == DNI
    assert verdict(facts, disabled_rules=["no_patent"]) == INVEST
    assert score(cfg, THREE_GREEN, disabled_items=["human_genetics"]).pos == 2


def test_split_biology_gives_two_greens_where_legacy_gives_one():
    facts = {"genetic_support": "gwas", "moa_clinical_precedent": "approved_related"}
    assert score(cfg, facts, "legacy6").pos == 1 and verdict(facts, variant="legacy6") == DNI
    assert score(cfg, facts, "base7").pos == 2 and verdict(facts) == INVEST


def test_biomarker_can_stand_in_for_randomisation_in_trial_design():
    item = cfg.items["trial_design"]
    assert item_color(item, {"biomarker_selection": True, "endpoint_matches_mechanism": True}) == GREEN
    assert item_color(item, {"biomarker_selection": True}) == YELLOW
    assert item_color(item, {"biomarker_selection": True, "endpoint_matches_mechanism": True,
                             "open_label_subjective_endpoint": True}) == RED
    assert item_color(item, {"biomarker_selection": False, "endpoint_matches_mechanism": True}) == YELLOW


def test_positive_own_phase2_and_pillars_now_count_separately():
    facts = {"own_ph2_positive": True, "pillars_human": 3}
    assert score(cfg, facts, "base7").pos == 1
    res = score(cfg, facts)
    assert res.greens == 2 and res.pos == 2 and res.verdict == INVEST    # two ordinary science greens
    assert score(cfg, {**facts, "phase": "ph3"}).pos == 3                # in Phase 3 the clinical effect is strong
    failed = score(cfg, {**THREE_GREEN, "own_trial_failed_efficacy": True, "pillars_human": 3})
    assert failed.colors["clinical_effect"] == RED and failed.colors["translation_chain"] == GREEN


# --- version 1.0 ------------------------------------------------------------------
def test_strong_greens_give_two_points():
    res = score(cfg, {"genetic_support": "mendelian"})
    assert res.points == {"human_genetics": 2} and res.pos == 2 and res.science_pos == 2 and res.greens == 1
    assert score(cfg, {"genetic_support": "gwas"}).points == {"human_genetics": 1}
    assert score(cfg, {"genetic_support": "somatic_driver"}).points == {"human_genetics": 1}
    # the asset's own positive Phase 2 is strong only when the asset has already moved to Phase 3
    assert score(cfg, {"own_ph2_positive": True}).points == {"clinical_effect": 1}
    assert score(cfg, {"own_ph2_positive": True, "phase": "ph2"}).points == {"clinical_effect": 1}
    assert score(cfg, {"own_ph2_positive": True, "phase": "ph3"}).points == {"clinical_effect": 2}
    assert score(cfg, {"own_ph2_positive": True, "phase": "filed"}).points == {"clinical_effect": 2}
    # the strong green weight is a parameter: 1 restores equal weights
    flat = score(cfg, {"genetic_support": "mendelian"}, weights={"green_strong": 1})
    assert flat.pos == 1 and flat.verdict == DNI
    with pytest.raises(ConfigError):
        score(cfg, {}, weights={"gren": 2})


def test_single_strong_science_green_is_enough_for_invest():
    for facts in ({"genetic_support": "mendelian"}, {"own_ph2_positive": True, "phase": "ph3"}):
        res = score(cfg, facts)
        assert res.verdict == INVEST and res.grounds == "positive" and res.coverage["items_known"] == 1
    # a claim of a positive Phase 2 alone, without moving to Phase 3, does not lead to Invest
    claimed = score(cfg, {"own_ph2_positive": True, "approved_therapies_count": 0})
    assert claimed.verdict == CONDITIONAL and claimed.grounds == "science_short"


def test_science_short_is_conditional_and_configurable():
    facts = {"approved_therapies_count": 0, "endpoint_approval_precedent": True,
             "moa_clinical_precedent": "approved_related"}
    res = score(cfg, facts)
    assert (res.pos, res.science_pos, res.verdict, res.grounds) == (3, 1, CONDITIONAL, "science_short")
    assert "science piece of evidence" in res.reason
    hard = score(cfg, facts, thresholds={"science_short": DNI})
    assert hard.verdict == DNI and hard.grounds == "insufficient_evidence"
    assert score(cfg, facts, thresholds={"min_science_pos_invest": 0}).verdict == INVEST   # as in version 0.4
    # a second science piece of evidence moves to Invest; the indication track record counts toward science pluses
    assert verdict({**facts, "indication_ph3_outcomes_other_moa": 8,
                    "indication_ph3_success_share_other_moa": 0.75}) == INVEST
    assert verdict({**facts, "genetic_support": "gwas"}) == INVEST


def test_track_record_alone_is_not_mechanism_evidence():
    facts = {"approved_therapies_count": 0, "endpoint_approval_precedent": True,
             "indication_ph3_outcomes_other_moa": 8, "indication_ph3_success_share_other_moa": 0.75}
    res = score(cfg, facts)
    assert res.pos == 3 and res.science_pos == 1 and res.verdict == DNI and res.grounds == "insufficient_evidence"


def test_conditional_uses_points_not_number_of_green_items():
    # Mendelian genetics (2 pluses) and one warning: a mixed picture, not "not enough confirmation"
    res = score(cfg, {"genetic_support": "mendelian", "class_safety_signal": True})
    assert (res.greens, res.pos, res.neg, res.verdict, res.grounds) == (1, 2, 1, CONDITIONAL, "balanced")


@pytest.mark.parametrize("facts, verdict_, grounds", [
    ({}, DNI, "insufficient_evidence"),
    ({"genetic_support": "gwas"}, DNI, "insufficient_evidence"),
    ({**THREE_GREEN, "patent_status": "expired"}, DNI, "kill"),
    ({**FIVE_GREEN, "moa_failures_efficacy_ph23": 1, "key_markets_outlicensed": True}, DNI, "negatives"),
    ({"genetic_support": "gwas", "class_withdrawal": True}, DNI, "outweighed"),
    ({**THREE_GREEN, "class_safety_signal": True, "ph3_same_moa_count": 3}, CONDITIONAL, "balanced"),
    (THREE_GREEN, INVEST, "positive"),
])
def test_grounds_separate_no_evidence_from_negative_evidence(facts, verdict_, grounds):
    from scoring import GROUNDS
    res = score(cfg, facts)
    assert (res.verdict, res.grounds) == (verdict_, grounds) and grounds in GROUNDS


def test_coverage_counts_items_with_any_data():
    res = score(cfg, {"genetic_support": "none", "own_ph2_positive": True})
    assert res.coverage == {"items_known": 2, "items_total": 8, "mechanism_known": 1, "mechanism_total": 5,
                            "asset_known": 1, "asset_total": 3}
    assert score(cfg, {}).coverage["items_known"] == 0


def test_no_animal_response_is_a_strong_minus_not_a_kill():
    res = score(cfg, {"animal_model_response": False})
    assert res.kills == [] and res.neg == 2 and res.verdict == DNI and res.grounds == "outweighed"
    strong = score(cfg, {"genetic_support": "mendelian", "approved_therapies_count": 0,
                         "endpoint_approval_precedent": True, "animal_model_response": False})
    assert (strong.pos, strong.neg, strong.verdict) == (4, 2, INVEST)
    weak = score(cfg, {**THREE_GREEN, "animal_model_response": False})
    assert weak.verdict == CONDITIONAL


def test_complex_manufacturing_assumes_small_sponsor_when_unknown():
    for modality in ("cell", "gene", "radioligand"):
        assert score(cfg, {"modality": modality}).fired == ["complex_manufacturing_small"]
    assert score(cfg, {"modality": "cell", "sponsor_size": "large"}).fired == []
    assert score(cfg, {"modality": "small_molecule"}).fired == []
    assert score(cfg, {"sponsor_size": "small"}).fired == []


def test_grade4_events_warn_outside_life_threatening_disease():
    assert score(cfg, {"grade4_related": True}).fired == ["grade4_events"]
    assert score(cfg, {"grade4_related": True, "life_threatening_indication": False}).neg == 1
    assert score(cfg, {"grade4_related": True, "oncology": True}).fired == []
    both = score(cfg, {"grade4_related": True, "grade5_related": True})
    assert both.neg == 2 and both.suppressed == {"grade4_events": "cluster:safety"}


def test_rare_disease_opens_the_regulatory_path():
    item = cfg.items["regulatory_path"]
    assert item_color(item, {"rare_disease": True}) == GREEN
    assert item_color(item, {"rare_disease": False}) == UNKNOWN
    assert item_color(item, {"rare_disease": True, "accepted_endpoint_exists": False}) == RED


def test_upgrading_evidence_never_lowers_the_verdict():
    rng = random.Random(3)
    extras = [{"class_safety_signal": True}, {"moa_failures_efficacy_ph23": 1}, {"approved_therapies_count": 0},
              {"endpoint_approval_precedent": True}, {"indication_graveyard": True}, {"pillars_human": 3},
              {"key_markets_outlicensed": True}, {"animal_model_response": False}, {"modality": "cell"}]
    ladder = ["none", "other_disease", "gwas", "mendelian"]
    for _ in range(300):
        base = {}
        for extra in rng.sample(extras, rng.randint(0, len(extras))):
            base.update(extra)
        ranks = [RANK[verdict({**base, "genetic_support": g})] for g in ladder]
        assert ranks == sorted(ranks), (base, ranks)
        ranks = [RANK[verdict({**base, "moa_clinical_precedent": p})]
                 for p in ("none", "approved_unrelated", "approved_related")]
        assert ranks == sorted(ranks), (base, ranks)


def test_decide_full_agrees_with_decide():
    from scoring import decide_full
    thr = cfg.thresholds
    for pos in range(7):
        for neg in range(6):
            for mech in (0, 1):
                for sci in (0, 1, 2):
                    full = decide_full(pos, neg, False, thr, pos, mech, sci)
                    assert full[:2] == decide(pos, neg, False, thr, pos, mech, sci)
                    assert (full[0] == INVEST) == (full[2] == "positive")


# --- reference probability -------------------------------------------------------
def test_reference_probability_picks_the_most_specific_known_cell():
    from scoring import reference_probability
    from scoring.engine import reference_cell_key
    key = lambda f: reference_cell_key(cfg, f)
    assert key({}) == "all"
    assert key({"genetic_support": "mendelian", "moa_clinical_precedent": "none"}) == "mendelian"
    assert key({"genetic_support": "gwas"}) == "genetics_any"                     # the rest unknown
    assert key({"genetic_support": "gwas", "moa_clinical_precedent": "approved_related"}) == "genetics_precedent"
    track_no = {"indication_ph3_outcomes_other_moa": 2}
    track_yes = {"indication_ph3_outcomes_other_moa": 9, "indication_ph3_success_share_other_moa": 0.8}
    assert key({"genetic_support": "gwas", "moa_clinical_precedent": "approved_unrelated", **track_no}) == "gwas_alone"
    assert key({"genetic_support": "somatic_driver", "moa_clinical_precedent": "none", **track_no}) == "somatic_alone"
    assert key({"genetic_support": "none", "moa_clinical_precedent": "approved_related"}) == "precedent_any"
    assert key({"genetic_support": "none", "moa_clinical_precedent": "approved_related", **track_yes}) == "precedent_track"
    assert key({"genetic_support": "other_disease", "moa_clinical_precedent": "none", **track_no}) == "nothing"
    assert key({"genetic_support": "none", "moa_clinical_precedent": "none"}) == "no_mechanism"
    assert key({"genetic_support": "none"}) == "no_genetics"
    assert key({"moa_clinical_precedent": "approved_same", "approved_same_moa_count": 1}) == "precedent_unknown_genetics"
    assert key({"approved_same_moa_count": 1}) == "precedent_unknown_genetics"    # precedent derived
    ref = reference_probability(cfg, {"genetic_support": "mendelian", "phase": "ph2", "oncology": False,
                                      "rare_disease": True})
    assert ref["evidence"]["from"] == "Phase II" and ref["evidence"]["range"][0] > ref["evidence"]["base"][0]
    assert ref["stage"]["segment"] == "rare_non_oncology" and ref["stage"]["loa"] == 0.252
    assert reference_probability(cfg, {"phase": "ph3", "oncology": True})["stage"]["loa"] == 0.439
    assert reference_probability(cfg, {})["stage"] is None


def test_reference_probability_never_changes_the_verdict_and_flags_caveats():
    from scoring import reference_probability
    ref = reference_probability(cfg, {"genetic_support": "contradicts", "phase": "preclinical",
                                      "indication_graveyard": True})
    assert len(ref["caveats"]) == 3 and ref["stage"] is None
    late = reference_probability(cfg, {"genetic_support": "somatic_driver", "moa_clinical_precedent": "none",
                                       "indication_ph3_outcomes_other_moa": 1, "phase": "ph3"})
    assert late["evidence"]["cell"] == "somatic_alone" and late["evidence"]["from"] == "Phase I" and late["caveats"]


def test_reference_cells_are_ordered_and_consistent():
    cells = cfg.raw["reference"]["launch_by_evidence"]["cells"]
    assert cells[-1]["id"] == "all" and cells[-1]["match"] == {}
    for c in cells:
        assert c["launched"] <= c["n"] and c["from_ph1"][0] <= c["from_ph1"][1]
        lo, hi = c["launched"] / c["n"] - 0.07, c["launched"] / c["n"] + 0.07
        assert lo <= c["from_ph1"][1] <= hi                       # upper bound = share for the mixed way
    by = {c["id"]: c for c in cells}
    assert by["mendelian"]["from_ph1"][0] > by["genetics_any"]["from_ph1"][1] > by["no_mechanism"]["from_ph1"][1]


def test_broken_reference_is_rejected(tmp_path):
    for mutate in (
        lambda raw: raw["reference"]["launch_by_evidence"]["cells"][0]["match"].__setitem__("genetics", ["mendel"]),
        lambda raw: raw["reference"]["launch_by_evidence"]["cells"][0].__setitem__("from_ph1", [0.5, 0.4]),
        lambda raw: raw["reference"]["launch_by_evidence"]["cells"].pop(),
        lambda raw: raw["verdict"].__setitem__("science_short", "Maybe"),
        lambda raw: raw.__setitem__("default_variant", "nope"),
        lambda raw: raw["scorecard"][0].__setitem__("strong_share_assumption", 2),
    ):
        with pytest.raises(ConfigError):
            _load_with(tmp_path, mutate)


# --- a minus never improves the verdict, a plus never worsens it ----------------------
def test_conditional_needs_mechanism_evidence_like_invest():
    disease_only = {"approved_therapies_count": 0, "endpoint_approval_precedent": True}
    assert verdict(disease_only) == DNI
    worse = score(cfg, {**disease_only, "class_safety_signal": True})
    assert (worse.pos, worse.neg, worse.verdict, worse.grounds) == (2, 1, DNI, "insufficient_evidence")
    # in version 0.4 the same set gave Conditional: a warning improved the verdict
    assert score(cfg, {**disease_only, "class_safety_signal": True},
                 thresholds={"conditional_requires_mechanism": False}).verdict == CONDITIONAL
    with_science = score(cfg, {**disease_only, "genetic_support": "gwas", "class_safety_signal": True})
    assert with_science.verdict == CONDITIONAL


def _random_facts(rng, k):
    facts = {}
    for name in rng.sample(sorted(cfg.facts), k):
        spec = cfg.facts[name]
        if spec["type"] == "bool":
            facts[name] = rng.random() < 0.5
        elif spec["type"] == "enum":
            facts[name] = rng.choice(spec["values"])
        elif spec["type"] == "int":
            facts[name] = rng.choice(spec.get("probes") or [0, 1, 2, 3, 5])
        else:
            facts[name] = min(spec.get("max", 30), rng.choice(spec.get("probes") or [0, 1, 6, 20]))
    return facts


def test_removing_a_minus_never_hurts_and_removing_a_plus_never_helps():
    rng = random.Random(5)
    checked = 0
    for _ in range(2500):
        facts = _random_facts(rng, rng.choice([2, 3, 4, 6, 8, 12]))
        try:
            res = score(cfg, facts)
        except FactError:
            continue
        checked += 1
        for rule_id in res.fired:
            assert RANK[score(cfg, facts, disabled_rules=[rule_id]).verdict] >= RANK[res.verdict], (facts, rule_id)
        for item_id, color in res.colors.items():
            without = RANK[score(cfg, facts, disabled_items=[item_id]).verdict]
            if color == GREEN:
                assert without <= RANK[res.verdict], (facts, item_id)
            elif color == RED:
                assert without >= RANK[res.verdict], (facts, item_id)
    assert checked > 2000


def test_result_records_config_version_and_hash(tmp_path):
    res = score(cfg, {})
    assert res.config == {"version": "1.3", "sha256": cfg.sha256} and len(cfg.sha256) == 64
    changed = _load_with(tmp_path, lambda raw: raw["verdict"].__setitem__("neg_dni", 5))
    assert changed.sha256 != cfg.sha256


def test_frozen_config_hash_is_the_one_documented():
    """The version is frozen: changing benchmarks.yaml without updating SCORING.md must fail here."""
    text = (Path(DEFAULT_CONFIG).parent / "SCORING.md").read_text(encoding="utf-8")
    assert f"`{cfg.sha256}`" in text, "update the hash in SCORING.md: python -m scoring version"
    assert "Version 1.3" in text and cfg.raw["version"] == "1.3"


# --- version 1.1 ------------------------------------------------------------------
def test_drug_approved_elsewhere_is_not_mechanism_evidence_for_this_disease():
    facts = {"drug_approved_other_indication": True, "approved_therapies_count": 0,
             "indication_ph3_outcomes_other_moa": 8, "indication_ph3_success_share_other_moa": 0.8}
    res = score(cfg, facts)
    assert res.colors["translation_chain"] == YELLOW and res.verdict == DNI and res.grounds == "insufficient_evidence"
    # if the other disease is related, it is a mechanism precedent, and then Invest is honest
    assert verdict({**facts, "moa_clinical_precedent": "approved_related"}) == INVEST


def test_no_genetic_data_for_the_disease_is_not_the_same_as_no_support():
    none = score(cfg, {"genetic_support": "none", "moa_clinical_precedent": "none"})
    no_data = score(cfg, {"genetic_support": "no_data", "moa_clinical_precedent": "none"})
    assert none.fired == ["no_genetics_no_precedent"] and no_data.fired == []
    assert no_data.colors["human_genetics"] == YELLOW and no_data.pos == 0
    from scoring.engine import reference_cell_key
    assert reference_cell_key(cfg, {"genetic_support": "no_data", "moa_clinical_precedent": "none"}) \
        == "no_precedent_unknown_genetics"
    from scoring import reference_probability
    assert any("no genetic data" in c
               for c in reference_probability(cfg, {"genetic_support": "no_data"})["caveats"])


def test_every_fact_has_a_planned_source():
    from scoring.engine import MVP_SOURCES
    assert all(spec.get("mvp") in MVP_SOURCES for spec in cfg.facts.values())
    assert cfg.facts["genetic_support"]["mvp"] == "open_targets" and cfg.facts["patent_status"]["mvp"] == "none"


# --- pipeline interface ----------------------------------------------------------------
def test_value_effect_is_what_the_value_does_alone():
    from scoring import value_effect
    assert value_effect(cfg, "patent_status", "expired")["tier"] == "kill"
    assert value_effect(cfg, "patent_status", "granted")["tier"] is None
    assert value_effect(cfg, "grade5_related", True)["tier"] == "strong"
    assert value_effect(cfg, "own_trial_failed_efficacy", True)["red_items"] == ["clinical_effect"]
    assert value_effect(cfg, "class_safety_signal", True)["tier"] == "warning"
    assert value_effect(cfg, "genetic_support", "mendelian") == {
        "tier": None, "rules": [], "red_items": [], "green_items": ["human_genetics"]}
    assert value_effect(cfg, "life_threatening_indication", False)["tier"] is None    # acts only together with deaths
    with pytest.raises(FactError):
        value_effect(cfg, "patent_status", "nope")


def test_fact_catalog_covers_every_fact_and_marks_critical_and_absence_values():
    from scoring import fact_catalog
    cat = fact_catalog(cfg)
    assert set(cat) == set(cfg.facts)
    assert cat["patent_status"]["critical_values"] == {"expired": "kill", "none": "kill"}
    assert cat["patent_status"]["absence_values"] == ["none"]
    assert cat["genetic_support"]["absence_values"] == ["no_data", "none"]
    assert cat["moa_successes_same_indication"]["absence_values"] == [0]
    assert cat["grade5_related"]["values"] == [True, False] and cat["grade5_related"]["level"] == "asset"


def _claim(cid, fact, value, origin="llm", **kw):
    return {"id": cid, "fact": fact, "value": value, "origin": origin, "verified": True, **kw}


def test_claims_become_facts_only_when_sourced_and_verified():
    from scoring import facts_from_claims
    out = facts_from_claims(cfg, [
        _claim("c1", "genetic_support", "gwas", "structured"),
        _claim("c2", "class_safety_signal", True),
        _claim("c3", "class_safety_signal", True, verified=False),
        _claim("c4", "oncology", True, evidence_type="inference"),
        _claim("c5", "no_such_fact", True),
        _claim("c6", "patent_status", "maybe"),
        _claim("c7", "phase", "ph2", "robot"),
    ])
    assert out["facts"] == {"genetic_support": "gwas", "class_safety_signal": True}
    assert out["used"] == {"genetic_support": ["c1"], "class_safety_signal": ["c2"]}
    assert {r["claim"] for r in out["rejected"]} == {"c3", "c4", "c5", "c6", "c7"}


def test_llm_cannot_assert_absence():
    from scoring import facts_from_claims
    for fact, value in (("moa_successes_same_indication", 0), ("genetic_support", "none"),
                        ("moa_clinical_precedent", "none"), ("approved_therapies_count", 0),
                        ("independent_groups", 0), ("pillars_human", 0)):
        assert facts_from_claims(cfg, [_claim("a", fact, value)])["facts"] == {}
        assert facts_from_claims(cfg, [_claim("a", fact, value, "structured")])["facts"] == {fact: value}
    # without a "known zero" two mechanism failures give a strong minus, not a kill rule
    facts = facts_from_claims(cfg, [_claim("f", "moa_failures_efficacy_ph23", 2, confirmed=True),
                                    _claim("s", "moa_successes_same_indication", 0)])["facts"]
    assert score(cfg, facts).kills == [] and score(cfg, facts).fired == ["one_mechanism_failure"]


def test_critical_claim_from_llm_waits_for_human_confirmation():
    from scoring import facts_from_claims
    one = facts_from_claims(cfg, [_claim("d1", "grade5_related", True, doc_ids=["doc_1"])])
    assert one["facts"] == {} and one["pending"][0]["fact"] == "grade5_related" and one["pending"][0]["tier"] == "strong"
    # since 1.3: two documents read by the same LLM step are not independent confirmation (review F34)
    two = facts_from_claims(cfg, [_claim("d1", "grade5_related", True, doc_ids=["doc_1"]),
                                  _claim("d2", "grade5_related", True, doc_ids=["doc_2"])])
    assert two["facts"] == {} and two["pending"][0]["fact"] == "grade5_related"
    assert facts_from_claims(cfg, [_claim("d1", "grade5_related", True, confirmed=True)])["facts"]
    assert facts_from_claims(cfg, [_claim("d1", "patent_status", "expired", "user")])["facts"]
    assert facts_from_claims(cfg, [_claim("d1", "crl_reason", "efficacy", "structured")])["facts"]
    # a non-critical value of the same fact passes at once
    assert facts_from_claims(cfg, [_claim("p", "patent_status", "granted")])["facts"] == {"patent_status": "granted"}


def test_conflicting_claims_resolve_by_origin_or_become_unknown():
    from scoring import facts_from_claims
    out = facts_from_claims(cfg, [_claim("a", "phase", "ph2"), _claim("b", "phase", "ph3", "structured"),
                                  _claim("c", "phase", "ph1", "user")])
    assert out["facts"] == {"phase": "ph1"} and out["conflicts"] == []
    out = facts_from_claims(cfg, [_claim("a", "phase", "ph2", "structured"), _claim("b", "phase", "ph3", "structured")])
    assert out["facts"] == {} and out["conflicts"][0]["values"] == ["ph2", "ph3"]


def test_evaluate_returns_everything_the_report_may_quote():
    import json
    from scoring import evaluate
    facts = {"approved_therapies_count": 0, "genetic_support": "gwas", "endpoint_approval_precedent": True,
             "class_safety_signal": True, "phase": "ph1", "oncology": False}
    out = evaluate(cfg, facts)
    json.dumps(out, ensure_ascii=False)                              # usable in SQLite as JSON
    assert out["verdict"]["decision"] == CONDITIONAL and out["verdict"]["grounds"] == "science_short"
    assert out["config"] == {"version": "1.3", "sha256": cfg.sha256}
    assert {c["fact"] for c in out["verdict"]["conditions"]} >= {"genetic_support", "moa_clinical_precedent"}
    assert [i["id"] for i in out["scorecard"]] == cfg.variant_items()
    assert out["rules"] == [{"id": "class_safety_signal", "name": "Class safety signal", "tier": "warning",
                             "counted": True, "absorbed_by": None, "basis": "expert",
                             "facts": ["class_safety_signal"]}]
    assert out["dd_questions"][0]["question"] == "What evidence would kill the program?"
    assert out["reference"]["stage"]["segment"] == "non_oncology"
    assert {w["direction"] for w in out["what_would_change"]} == {"better", "worse"}
    assert evaluate(cfg, {"genetic_support": "mendelian"})["verdict"]["conditions"] == []


def test_catalog_and_sources_reports_render():
    from scoring.cli import render_catalog, render_sources, source_level
    cat = yaml.safe_load(render_catalog(cfg))
    assert set(cat["facts"]) == set(cfg.facts)
    text = render_sources(cfg)
    assert "human only | 46" in text and "Me-too: differentiation checked and not confirmed | kill | M | " in text
    rules = {r["id"]: r for r in cfg.rules}
    assert source_level(cfg, rules["no_patent"]["when"]) == "only with human facts"
    assert source_level(cfg, rules["no_animal_response"]["when"]) == "with an input field"
    assert source_level(cfg, rules["mechanism_refuted"]["when"]) == "with text read by the LLM"


def test_generated_files_are_up_to_date():
    """tags.yaml, docs/facts.md and docs/fact_sources.md are generated; after a config change they must be regenerated."""
    from scoring.cli import render_catalog, render_facts, render_sources
    root = Path(DEFAULT_CONFIG).parent
    assert (root / "tags.yaml").read_text(encoding="utf-8") == render_catalog(cfg), "python -m scoring catalog > tags.yaml"
    assert (root / "docs" / "facts.md").read_text(encoding="utf-8") == render_facts(cfg)
    assert (root / "docs" / "fact_sources.md").read_text(encoding="utf-8") == render_sources(cfg)



# --- version 1.3: claims gate, caps, coverage (independent review 2026-10-08) -----------------------------------------
def test_llm_value_that_flips_the_verdict_with_other_facts_waits_for_a_human():
    """F32/F33: a value harmless alone (or one that removes a minus) must not change the verdict without a human."""
    from scoring import facts_from_claims
    base = [_claim(f"s{i}", k, v, "structured") for i, (k, v) in enumerate({
        "genetic_support": "mendelian", "moa_clinical_precedent": "approved_same", "moa_failures_efficacy_ph23": 1,
        "approved_same_moa_count": 0, "phase": "ph2"}.items())]
    engaged = _claim("x", "class_target_engagement_human", True, doc_ids=["pmid:1"])
    out = facts_from_claims(cfg, base + [engaged])
    assert "class_target_engagement_human" not in out["facts"] and out["pending"][-1]["tier"] == "verdict"
    ok = facts_from_claims(cfg, base + [{**engaged, "confirmed": True}])
    assert ok["facts"]["class_target_engagement_human"] is True
    # the same value with no effect on the verdict passes at once
    alone = facts_from_claims(cfg, [engaged])
    assert alone["facts"] == {"class_target_engagement_human": True}


def test_runway_short_caps_invest_at_conditional():
    """F31/M7: 4 pluses - 2 left Invest for a company that will not reach its milestone."""
    facts = {**SIX_GREEN, "runway_short": True}
    res = score(cfg, facts)
    assert "runway_short" in res.fired and res.verdict == CONDITIONAL and res.grounds == "capped"
    assert score(cfg, SIX_GREEN).verdict == INVEST


def test_invest_needs_coverage():
    """F44/S6 with the shipped thresholds: 5 of 8 items, or one asset-level item."""
    three = {"genetic_support": "mendelian", "moa_clinical_precedent": "approved_same", "oncology": False}
    res = score(SHIPPED, three)
    assert res.coverage["items_known"] < 5 and res.coverage["asset_known"] == 0
    assert res.verdict == CONDITIONAL and res.grounds == "low_coverage"
    assert score(cfg, three).verdict == INVEST                      # the same facts without the requirement
    with_asset = score(SHIPPED, {**three, "own_ph2_positive": True})
    assert with_asset.coverage["asset_known"] >= 1 and with_asset.verdict == INVEST


def test_caps_never_raise_a_verdict():
    for facts in ({}, {"genetic_support": "none"}, {**SIX_GREEN, "grade5_related": True}):
        a, b = score(SHIPPED, facts), score(cfg, facts)
        rank = {DNI: 0, CONDITIONAL: 1, INVEST: 2}
        assert rank[a.verdict] <= rank[b.verdict]
        assert rank[score(SHIPPED, {**facts, "runway_short": True}).verdict] <= rank[a.verdict]

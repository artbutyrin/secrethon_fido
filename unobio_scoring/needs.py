"""What kind of data answers each asset-level question (brief: say when the answer needs proprietary data,
patient-level data, KOL interviews, new experiments or CMC / IP diligence, instead of guessing)."""

NEEDS = {
    "proprietary experimental data": {"animal_model_response", "link_exposure", "link_target_engagement",
                                      "link_pd_response", "pillars_human", "toxicity_at_efficacious_exposure",
                                      "perturbation_evidence", "independent_groups"},
    "patient-level clinical data": {"own_ph2_positive", "own_trial_failed_efficacy", "grade5_related", "grade4_related",
                                    "dose_ranging_done", "ph2_under_enrollment", "posthoc_subgroup_thesis",
                                    "primary_endpoint_changed", "single_country_ex_us_pivotal"},
    "KOL interviews": {"differentiation_claim", "differentiation_evidence", "price_channel_direct",
                       "endpoint_matches_mechanism", "active_comparator_exists"},
    "regulatory documents": {"crl_reason", "adcom_negative", "fda_data_integrity_letter", "fda_designations_count",
                             "accelerated_only", "confirmatory_trial_registered", "accepted_endpoint_exists",
                             "regulatory_exclusivity_years"},
    "CMC / IP diligence": {"patent_status", "key_patent_license", "key_markets_outlicensed",
                           "nonkey_territories_outlicensed_count", "royalty_stack_pct", "cmo_oai_or_warning_letter",
                           "modality_target_mismatch"},
    "company financials": {"runway_short", "sponsor_size", "sponsor_prior_approvals", "big_pharma_partner",
                           "partner_returned_asset"},
    "trial design documents": {"randomized_controlled", "single_arm_pivotal", "open_label_subjective_endpoint",
                               "biomarker_selection"},
}
_BY_FACT = {f: k for k, fs in NEEDS.items() for f in fs}


def needs_for(facts: list[str]) -> list[str]:
    return sorted({_BY_FACT.get(f, "public data (can be collected)") for f in facts})

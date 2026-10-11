# Scorecard, rules and caps

Generated from unobio_scoring 2.1.

## Scorecard (8 items)

| Item | Axis | Level | Red if | Green if | Strong green (2 pluses) if |
|---|---|---|---|---|---|
| Unmet need | commercial | mechanism | ((approved_therapies_count ≥ 3 OR approved_same_moa_count ≥ 3 OR indication_new_moa_approvals_10y ≥ 3) AND soc_last_new_moa_years ≤ 5) | (approved_therapies_count = 0 OR soc_last_new_moa_years ≥ 15 OR active_comparator_exists = false) | — |
| Human genetics | science (mechanism evidence) | mechanism | genetic_support = "contradicts" | genetic_support ∈ ["gwas", "mendelian", "somatic_driver"] | genetic_support = "mendelian" |
| Mechanism clinical precedent | science (mechanism evidence) | mechanism | — | moa_clinical_precedent ∈ ["positive_ph2_3_related", "approved_related", "positive_ph2_3_same", "approved_same"] | — |
| Indication track record | science | mechanism | indication_graveyard = true | (indication_graveyard ≠ true [unknown → false] AND indication_ph3_outcomes_other_moa ≥ 5 AND indication_ph3_success_share_other_moa ≥ 0.7) | — |
| Translation chain | science (mechanism evidence) | asset | (own_ph2_positive ≠ true [unknown → false] AND drug_approved_other_indication ≠ true [unknown → false] AND (link_exposure = false OR link_target_engagement = false OR link_pd_response = false OR (pillars_human = 0 AND phase ∈ ["ph2", "ph3", "filed"]))) | ((link_exposure = true AND link_target_engagement = true AND link_pd_response = true) OR pillars_human = 3) | — |
| Clinical effect shown | science (mechanism evidence) | asset | own_trial_failed_efficacy = true | own_ph2_positive = true | (own_ph2_positive = true AND phase ∈ ["ph3", "filed"]) |
| Trial design | commercial | asset | (endpoint_matches_mechanism = false OR open_label_subjective_endpoint = true) | (endpoint_matches_mechanism = true AND dose_ranging_done ≠ false [unknown → true] AND (randomized_controlled = true OR biomarker_selection = true)) | — |
| Regulatory path | commercial | mechanism | accepted_endpoint_exists = false | (fda_designations_count ≥ 1 OR endpoint_approval_precedent = true OR rare_disease = true) | — |

## Rules

Kill: Do Not Invest at once. Strong: 2 minuses. Warning: 1 minus. In one cluster only the strongest counts. ★ new or changed in 2.1.

| Rule | Tier | Cluster | Fires when |
|---|---|---|---|
| Mechanism refuted (`mechanism_refuted`) ★ | kill | — | (moa_failures_efficacy_ph23 ≥ 2 AND (moa_successes_same_indication = 0 OR ((moa_approved_any_indication = false OR moa_clinical_precedent = "none") AND moa_successes_same_indication = 0 [unknown → 0]))) |
| Me-too: differentiation checked and refuted (`me_too_refuted`) ★ | kill | — | ((approved_same_moa_same_modality_count ≥ 2 OR (approved_same_moa_same_modality_count unknown AND approved_same_moa_count ≥ 2)) AND differentiation_evidence = false) |
| Me-too: late, differentiation not proven (`me_too`) ★ | strong | competition | ((approved_same_moa_same_modality_count ≥ 2 OR (approved_same_moa_same_modality_count unknown AND approved_same_moa_count ≥ 2)) AND NOT ((differentiation_claim ∈ ["efficacy", "safety", "structural_cost"] [unknown → "none"] AND differentiation_evidence ≠ false [unknown → true]) OR (differentiation_claim = "price_only" [unknown → "none"] AND price_channel_direct = true [unknown → false] AND differentiation_evidence ≠ false [unknown → true]))) |
| Drug-related deaths in a non-fatal disease (`drug_related_deaths`) | kill | — | (grade5_related = true AND life_threatening_indication = false) |
| CRL for efficacy or safety (`crl_efficacy_safety`) | kill | — | crl_reason ∈ ["efficacy", "safety"] |
| No patent and less than 5 years of statutory exclusivity (`no_patent`) ★ | kill | — | (patent_status ∈ ["expired", "none"] AND regulatory_exclusivity_years < 5 [unknown → 0]) |
| The modality physically cannot reach the target (`modality_mismatch`) | kill | — | modality_target_mismatch = true |
| Foundational paper retracted, result not reproduced (`retraction_unreplicated`) | kill | — | (foundational_retraction = true AND independent_groups = 0) |
| Key patent licence is non-exclusive or does not cover the lead indication (`license_not_exclusive`) | kill | — | key_patent_license ∈ ["non_exclusive", "field_excludes_lead"] |
| FDA letter on unreliable clinical data (`data_integrity_letter`) | kill | — | fda_data_integrity_letter = true |
| One mechanism failure for efficacy (`one_mechanism_failure`) | strong | — | (moa_failures_efficacy_ph23 ≥ 1 AND (moa_successes_same_indication unknown OR (moa_failures_efficacy_ph23 = 1 AND moa_successes_same_indication = 0))) |
| No response in an animal model (`no_animal_response`) | strong | — | animal_model_response = false |
| Drug-related deaths in a fatal disease or of unknown severity (`deaths_fatal_disease`) | strong | safety | (grade5_related = true AND (life_threatening_indication = true OR life_threatening_indication unknown)) |
| A drug of the same class was withdrawn for safety (`class_withdrawal`) | strong | safety | class_withdrawal = true |
| Inhibitor of an essential gene in a chronic non-oncology disease (`essential_gene_chronic`) | strong | safety | (essential_gene = true AND chronic_non_oncology = true AND moa_direction = "inhibit") |
| Four or more target safety flags in a chronic non-oncology disease (`target_safety_high`) | strong | safety | (target_safety_flags ≥ 4 AND chronic_non_oncology = true) |
| Toxicity at efficacious exposure (`toxicity_at_exposure`) | strong | safety | toxicity_at_efficacious_exposure = true |
| CRL with an undisclosed reason (`crl_undisclosed`) | strong | regulatory_events | crl_reason = "undisclosed" |
| Negative advisory committee vote (`adcom_negative`) | strong | regulatory_events | adcom_negative = true |
| No patent; protection rests on 5–6 years of statutory exclusivity (`no_patent_short_exclusivity`) ★ | strong | licensing | (patent_status ∈ ["expired", "none"] AND regulatory_exclusivity_years ≥ 5 AND regulatory_exclusivity_years < 7) |
| US or EU rights out-licensed (`key_markets_gone`) | strong | licensing | key_markets_outlicensed = true |
| Total royalties above 10% (`royalty_stack_high`) | strong | licensing | royalty_stack_pct > 10 |
| The thesis rests on a subgroup found post hoc (`posthoc_subgroup`) | strong | trial_conduct | posthoc_subgroup_thesis = true |
| Registrational data from a single country outside the US (`single_country`) | strong | trial_conduct | single_country_ex_us_pivotal = true |
| Primary endpoint changed after registration (`endpoint_changed`) | strong | trial_conduct | primary_endpoint_changed = true |
| Single-arm registrational trial outside oncology and rare diseases (`single_arm_outside`) | strong | trial_conduct | (single_arm_pivotal = true AND oncology = false AND rare_disease = false) |
| Accelerated approval without a confirmatory trial (`accelerated_no_confirmatory`) | strong | trial_conduct | (accelerated_only = true AND confirmatory_trial_registered = false) |
| More than 5 years behind the first in class (`late_entry`) | strong | competition | (years_behind_first_in_class > 5 AND approved_same_moa_count ≥ 1 [unknown → 1]) |
| Standard of care loses exclusivity before launch (`soc_loe`) | strong | pricing | soc_loe_before_launch = true |
| A partner returned the asset (`partner_returned`) | strong | sponsor_finance | partner_returned_asset = true |
| Cash does not last until the next readout (`runway_short`) | strong | sponsor_finance | runway_short = true |
| Two or more programs on this target discontinued for safety (`moa_safety_discontinuations`) | strong | safety | moa_discontinued_safety_count ≥ 2 |
| Another drug with the same mechanism received a CRL for safety (`moa_crl_safety`) | strong | safety | moa_crl_safety = true |
| Drug-related deaths in trials of the same class (`class_deaths`) | strong | safety | class_drug_related_deaths = true |
| Neither genetics nor a target precedent in a related disease (`no_genetics_no_precedent`) | warning | — | (genetic_support ∈ ["none", "other_disease"] AND moa_clinical_precedent ∈ ["none", "approved_unrelated"]) |
| One program on this target discontinued for safety (`moa_safety_discontinuation`) | warning | safety | moa_discontinued_safety_count = 1 |
| An advisory committee voted against another drug with the same mechanism (`moa_adcom_negative`) | warning | regulatory_events | moa_adcom_negative = true |
| Accelerated approvals in this disease were withdrawn (`indication_accelerated_withdrawn`) | warning | trial_conduct | indication_accelerated_withdrawn = true |
| Trials in this disease were often stopped for enrollment (`indication_enrollment_risk`) | warning | trial_conduct | indication_enrollment_terminations_high = true |
| Me-too with differentiation (`me_too_differentiated`) ★ | warning | competition | ((approved_same_moa_same_modality_count ≥ 2 OR (approved_same_moa_same_modality_count unknown AND approved_same_moa_count ≥ 2)) AND differentiation_evidence ≠ false [unknown → true] AND (differentiation_claim ∈ ["efficacy", "safety", "structural_cost"] OR (differentiation_claim = "price_only" AND price_channel_direct = true))) |
| Three or more competitors of the same mechanism in Phase 3 (`ph3_competitors`) | warning | competition | (ph3_same_moa_count ≥ 3 AND approved_same_moa_count < 2 [unknown → 0]) |
| Class safety signal (`class_safety_signal`) | warning | safety | class_safety_signal = true |
| Drug-related grade 4 adverse events in a non-fatal disease (`grade4_events`) | warning | safety | (grade4_related = true AND life_threatening_indication ≠ true [unknown → false]) |
| Two or more target safety flags (`target_safety_medium`) | warning | safety | target_safety_flags ≥ 2 |
| CRL for manufacturing (`crl_manufacturing`) | warning | regulatory_events | crl_reason = "manufacturing" |
| Complex manufacturing (cell, gene therapy, radioligand) outside a big company (`complex_manufacturing_small`) | warning | manufacturing | (modality ∈ ["cell", "gene", "radioligand"] AND sponsor_size ≠ "large" [unknown → "small"]) |
| Problematic status of a site or contract manufacturer (`cmo_status`) | warning | manufacturing | cmo_oai_or_warning_letter = true |
| Several territories outside the US and EU out-licensed (`nonkey_licenses`) | warning | licensing | nonkey_territories_outlicensed_count ≥ 2 |
| Total royalties 5–10% (`royalty_stack_medium`) | warning | licensing | (royalty_stack_pct ≥ 5 AND royalty_stack_pct ≤ 10) |
| Hypothesis not independently reproduced (`no_replication`) | warning | — | (independent_groups = 0 OR (foundational_retraction = true AND independent_groups unknown)) |
| Phase 2 under-enrollment (`under_enrollment`) | warning | trial_conduct | ph2_under_enrollment = true |
| Economics negative: P(rNPV > 0) below 10% (`economics_negative`) ★ | strong | pricing | economics_negative = true |
| Economics weak: median rNPV below zero (`economics_weak`) ★ | warning | pricing | economics_weak = true |
| Unrealistic required price (`price_unrealistic`) | warning | pricing | required_price_unrealistic = true |
| Exposure to Medicare price negotiation (`medicare_negotiation`) | warning | pricing | medicare_negotiation_exposure = true |

## Caps (verdict cannot exceed Conditional)

| Cap | When | Reason |
|---|---|---|
| `cap_runway` (F31) | runway_short = true | cash does not reach the next readout (fund through the milestone first) |
| `cap_economics` (F52) | economics_negative = true | P(rNPV > 0) is below 10% (change price, scale or development plan first) |
| `cap_me_too` (F38) | ((approved_same_moa_same_modality_count ≥ 2 OR (approved_same_moa_same_modality_count unknown AND approved_same_moa_count ≥ 2)) AND NOT ((differentiation_claim ∈ ["efficacy", "safety", "structural_cost"] [unknown → "none"] AND differentiation_evidence ≠ false [unknown → true]) OR (differentiation_claim = "price_only" [unknown → "none"] AND price_channel_direct = true [unknown → false] AND differentiation_evidence ≠ false [unknown → true]))) | me-too without proven differentiation (show comparative data, device or payer advantage first) |

## Verdict thresholds

```
{
 "min_science_pos_invest": 2,
 "science_short": "Conditional",
 "conditional_requires_mechanism": true,
 "invest_requires_asset_data": false,
 "neg_dni": 4,
 "invest_margin": 2,
 "dni_margin": 0,
 "min_pos_conditional": 2,
 "require_mechanism_green": true
}
```

Order: kill → DNI; minuses ≥ neg_dni → DNI; net ≥ invest_margin with science pluses ≥ min_science_pos_invest and a mechanism green → Invest (then caps); net ≤ dni_margin → DNI; otherwise Conditional / DNI by min_pos_conditional and the mechanism requirement.

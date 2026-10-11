# 'Fact → source' matrix and which rules work in the first pipeline version

Generated from `benchmarks.yaml` (version 1.3) by `python -m scoring sources`.

> **This is a plan, not a verified state.** The 'MVP source' column was filled from source documentation; no live request has been made yet. Every row must be confirmed by a real API response.

## 1. Summary

| MVP source | Facts |
| --- | --- |
| input field | 10 |
| Open Targets | 18 |
| ClinicalTrials.gov | 1 |
| ClinicalTrials.gov, text (LLM) | 4 |
| PubMed, text (LLM) | 5 |
| static table | 3 |
| derived | 2 |
| human only | 46 |

A human can add any fact manually (`POST /runs/{id}/evidence`).

## 2. What can fire

For every item and rule: the narrowest source set under which the condition can become true at all.

### Scorecard

| Item | Level | Green | Red |
| --- | --- | --- | --- |
| Unmet need | M | alone, from structured sources | only with human facts |
| Human genetics | M | alone, from structured sources | alone, from structured sources |
| Mechanism clinical precedent | M | alone, from structured sources | — |
| Indication track record | M | alone, from structured sources | alone, from structured sources |
| Translation chain | A | with an input field | with an input field |
| Clinical effect shown | A | only with human facts | only with human facts |
| Trial design | A | only with human facts | only with human facts |
| Regulatory path | M | alone, from structured sources | alone, from structured sources |

### Rules: how many work with each source set

| Rule tier | alone, from structured sources | with an input field | with text read by the LLM | only with human facts |
| --- | --- | --- | --- | --- |
| kill | 1 | 0 | 2 | 6 |
| strong minus | 2 | 1 | 3 | 19 |
| warning | 4 | 1 | 3 | 11 |

### Rules by name

| Rule | Rule tier | M/A | Can fire |
| --- | --- | --- | --- |
| Mechanism refuted | kill | M | with text read by the LLM |
| Me-too: differentiation checked and not confirmed | kill | M | only with human facts |
| Me-too: late, differentiation not shown | strong minus | M | alone, from structured sources |
| Drug-related deaths in a non-fatal disease | kill | A | only with human facts |
| CRL for efficacy or safety | kill | A | only with human facts |
| Patent expired or no protection | kill | A | only with human facts |
| The modality physically cannot reach the target | kill | M | alone, from structured sources |
| Foundational paper retracted, result not reproduced | kill | M | with text read by the LLM |
| Key patent licence is non-exclusive or does not cover the lead indication | kill | A | only with human facts |
| FDA letter on unreliable clinical data | kill | A | only with human facts |
| One mechanism failure for efficacy | strong minus | M | with text read by the LLM |
| Target engaged in humans, still no efficacy | strong minus | M | with text read by the LLM |
| No response in an animal model | strong minus | A | with an input field |
| Drug-related deaths in a fatal disease or of unknown severity | strong minus | A | only with human facts |
| A drug of the same class was withdrawn for safety | strong minus | M | alone, from structured sources |
| Inhibitor of an essential gene in a chronic non-oncology disease | strong minus | M | only with human facts |
| Four or more target safety flags in a chronic non-oncology disease | strong minus | M | only with human facts |
| Toxicity at efficacious exposure | strong minus | A | only with human facts |
| CRL with an undisclosed reason | strong minus | A | only with human facts |
| Negative advisory committee vote | strong minus | A | only with human facts |
| US or EU rights out-licensed | strong minus | A | only with human facts |
| Total royalties above 10% | strong minus | A | only with human facts |
| The thesis rests on a subgroup found post hoc | strong minus | A | only with human facts |
| Registrational data from a single country outside the US | strong minus | A | only with human facts |
| Primary endpoint changed after registration | strong minus | A | only with human facts |
| Single-arm registrational trial outside oncology and rare diseases | strong minus | A | only with human facts |
| Accelerated approval without a confirmatory trial | strong minus | A | only with human facts |
| More than 5 years behind the first in class | strong minus | M | only with human facts |
| Standard of care loses exclusivity before launch | strong minus | M | only with human facts |
| A partner returned the asset | strong minus | A | only with human facts |
| Cash does not last until the next readout | strong minus | A | only with human facts |
| Two or more programs on this target discontinued for safety | strong minus | M | with text read by the LLM |
| Another drug with the same mechanism received a CRL for safety | strong minus | M | only with human facts |
| Drug-related deaths in trials of the same class | strong minus | M | only with human facts |
| Neither genetics nor a target precedent in a related disease | warning | M | alone, from structured sources |
| One program on this target discontinued for safety | warning | M | with text read by the LLM |
| An advisory committee voted against another drug with the same mechanism | warning | M | only with human facts |
| Accelerated approvals in this disease were withdrawn | warning | M | only with human facts |
| Trials in this disease were often stopped for enrollment | warning | M | with text read by the LLM |
| Me-too with differentiation | warning | M | only with human facts |
| Three or more competitors of the same mechanism in Phase 3 | warning | M | alone, from structured sources |
| Class safety signal | warning | M | alone, from structured sources |
| Drug-related grade 4 adverse events in a non-fatal disease | warning | A | only with human facts |
| Two or more target safety flags | warning | M | alone, from structured sources |
| CRL for manufacturing | warning | A | only with human facts |
| Complex manufacturing (cell, gene therapy, radioligand) outside a big company | warning | M | with an input field |
| Problematic status of a site or contract manufacturer | warning | A | only with human facts |
| Several territories outside the US and EU out-licensed | warning | A | only with human facts |
| Total royalties 5–10% | warning | A | only with human facts |
| Hypothesis not independently reproduced | warning | M | with text read by the LLM |
| Phase 2 under-enrollment | warning | A | only with human facts |
| Unrealistic required price | warning | M | only with human facts |
| Exposure to Medicare price negotiation | warning | M | only with human facts |

## 3. All facts

A critical value alone triggers a kill rule, a strong minus or a red item; from the LLM it needs human confirmation (since 1.3), as does any LLM value that changes the verdict together with the other facts. The LLM cannot set an absence value from text.

| Fact | M/A | MVP source | Critical values | Absence values | Used in |
| --- | --- | --- | --- | --- | --- |
| `approved_therapies_count` | M | Open Targets | — | 0 | Unmet need |
| `soc_last_new_moa_years` | M | human only | — | — | Unmet need |
| `active_comparator_exists` | M | human only | — | — | Unmet need |
| `approved_same_moa_count` | M | Open Targets | 2 (strong minus) | 0 | Unmet need; Me-too: differentiation checked and not confirmed; Me-too: late, differentiation not shown; Target engaged in humans, still no efficacy; More than 5 years behind the first in class; Me-too with differentiation; Three or more competitors of the same mechanism in Phase 3 |
| `ph3_same_moa_count` | M | Open Targets | — | 0 | Three or more competitors of the same mechanism in Phase 3 |
| `years_behind_first_in_class` | M | human only | 6 (strong minus) | — | More than 5 years behind the first in class |
| `soc_loe_before_launch` | M | human only | yes (strong minus) | — | Standard of care loses exclusivity before launch |
| `required_price_unrealistic` | M | human only | — | — | Unrealistic required price |
| `medicare_negotiation_exposure` | M | human only | — | — | Exposure to Medicare price negotiation |
| `genetic_support` | M | Open Targets | contradicts (strong minus) | no_data, none | Human genetics; Neither genetics nor a target precedent in a related disease |
| `moa_clinical_precedent` | M | Open Targets | — | none | Mechanism clinical precedent; Neither genetics nor a target precedent in a related disease |
| `independent_groups` | M | PubMed, text (LLM) | — | 0 | Foundational paper retracted, result not reproduced; Hypothesis not independently reproduced |
| `perturbation_evidence` | M | Open Targets | — | — | Human genetics |
| `correlational_evidence` | M | Open Targets | — | — | Human genetics |
| `class_exposure_human` | M | PubMed, text (LLM) | — | — | Translation chain |
| `class_target_engagement_human` | M | PubMed, text (LLM) | — | — | Translation chain; Target engaged in humans, still no efficacy |
| `class_pd_response_human` | M | PubMed, text (LLM) | — | — | Translation chain; Target engaged in humans, still no efficacy |
| `moa_discontinued_safety_count` | M | ClinicalTrials.gov, text (LLM) | 2 (strong minus) | 0 | Two or more programs on this target discontinued for safety; One program on this target discontinued for safety |
| `moa_crl_safety` | M | human only | yes (strong minus) | — | Another drug with the same mechanism received a CRL for safety |
| `moa_adcom_negative` | M | human only | — | — | An advisory committee voted against another drug with the same mechanism |
| `class_drug_related_deaths` | M | human only | yes (strong minus) | — | Drug-related deaths in trials of the same class |
| `indication_accelerated_withdrawn` | M | human only | — | — | Accelerated approvals in this disease were withdrawn |
| `indication_enrollment_terminations_high` | M | ClinicalTrials.gov, text (LLM) | — | — | Trials in this disease were often stopped for enrollment |
| `route_of_administration` | M | input field | — | — | legacy items only |
| `foundational_retraction` | M | PubMed, text (LLM) | — | — | Foundational paper retracted, result not reproduced; Hypothesis not independently reproduced |
| `moa_failures_efficacy_ph23` | M | ClinicalTrials.gov, text (LLM) | 1 (strong minus); 2 (strong minus) | 0 | Mechanism refuted; One mechanism failure for efficacy; Target engaged in humans, still no efficacy |
| `moa_successes_same_indication` | M | Open Targets | — | 0 | Mechanism refuted; One mechanism failure for efficacy |
| `indication_graveyard` | M | static table | yes (strong minus) | — | Indication track record |
| `indication_failures_other_moa_ph3_10y` | M | ClinicalTrials.gov, text (LLM) | — | 0 | legacy items only |
| `indication_ph3_outcomes_other_moa` | M | Open Targets | — | 0 | Indication track record |
| `indication_ph3_success_share_other_moa` | M | Open Targets | — | — | Indication track record |
| `indication_new_moa_approvals_10y` | M | human only | — | 0 | Unmet need |
| `life_threatening_indication` | M | derived | — | — | Drug-related deaths in a non-fatal disease; Drug-related deaths in a fatal disease or of unknown severity; Drug-related grade 4 adverse events in a non-fatal disease |
| `oncology` | M | Open Targets | — | — | Single-arm registrational trial outside oncology and rare diseases |
| `rare_disease` | M | Open Targets | — | — | Regulatory path; Single-arm registrational trial outside oncology and rare diseases |
| `chronic_non_oncology` | M | human only | — | — | Inhibitor of an essential gene in a chronic non-oncology disease; Four or more target safety flags in a chronic non-oncology disease |
| `class_safety_signal` | M | Open Targets | — | — | Class safety signal |
| `class_withdrawal` | M | Open Targets | yes (strong minus) | — | A drug of the same class was withdrawn for safety |
| `target_safety_flags` | M | Open Targets | — | 0 | Four or more target safety flags in a chronic non-oncology disease; Two or more target safety flags |
| `essential_gene` | M | Open Targets | — | — | Inhibitor of an essential gene in a chronic non-oncology disease |
| `moa_direction` | M | input field | — | — | Inhibitor of an essential gene in a chronic non-oncology disease |
| `modality` | M | input field | — | — | Complex manufacturing (cell, gene therapy, radioligand) outside a big company |
| `modality_target_mismatch` | M | Open Targets | yes (kill) | — | The modality physically cannot reach the target |
| `tractability` | M | Open Targets | — | none | legacy items only |
| `accepted_endpoint_exists` | M | static table | no (strong minus) | — | Regulatory path |
| `endpoint_approval_precedent` | M | static table | — | — | Regulatory path |
| `natural_history_data` | M | ClinicalTrials.gov | — | — | Regulatory path |
| `fda_designations_count` | A | human only | — | 0 | Regulatory path |
| `phase` | A | input field | — | — | Translation chain |
| `animal_model_response` | A | input field | no (strong minus) | — | Translation chain; No response in an animal model |
| `pillars_human` | A | input field | — | 0 | Translation chain |
| `link_exposure` | A | input field | no (strong minus) | — | Translation chain |
| `link_target_engagement` | A | input field | no (strong minus) | — | Translation chain |
| `link_pd_response` | A | input field | no (strong minus) | — | Translation chain |
| `own_ph2_positive` | A | human only | — | — | Translation chain; Clinical effect shown |
| `own_trial_failed_efficacy` | A | human only | yes (strong minus) | — | Clinical effect shown |
| `drug_approved_other_indication` | A | human only | — | — | Translation chain |
| `randomized_controlled` | A | human only | — | — | Trial design |
| `endpoint_matches_mechanism` | A | human only | no (strong minus) | — | Trial design |
| `dose_ranging_done` | A | human only | — | — | Trial design |
| `open_label_subjective_endpoint` | A | human only | yes (strong minus) | — | Trial design |
| `biomarker_selection` | A | input field | — | — | Trial design |
| `posthoc_subgroup_thesis` | A | human only | yes (strong minus) | — | The thesis rests on a subgroup found post hoc |
| `single_country_ex_us_pivotal` | A | human only | yes (strong minus) | — | Registrational data from a single country outside the US |
| `single_arm_pivotal` | A | human only | — | — | Single-arm registrational trial outside oncology and rare diseases |
| `accelerated_only` | A | human only | — | — | Accelerated approval without a confirmatory trial |
| `confirmatory_trial_registered` | A | human only | — | — | Accelerated approval without a confirmatory trial |
| `ph2_under_enrollment` | A | human only | — | — | Phase 2 under-enrollment |
| `primary_endpoint_changed` | A | human only | yes (strong minus) | — | Primary endpoint changed after registration |
| `grade5_related` | A | human only | yes (strong minus) | — | Drug-related deaths in a non-fatal disease; Drug-related deaths in a fatal disease or of unknown severity |
| `grade4_related` | A | human only | — | — | Drug-related grade 4 adverse events in a non-fatal disease |
| `toxicity_at_efficacious_exposure` | A | human only | yes (strong minus) | — | Toxicity at efficacious exposure |
| `crl_reason` | A | human only | efficacy (kill); safety (kill); undisclosed (strong minus) | none | CRL for efficacy or safety; CRL with an undisclosed reason; CRL for manufacturing |
| `adcom_negative` | A | human only | yes (strong minus) | — | Negative advisory committee vote |
| `fda_data_integrity_letter` | A | human only | yes (kill) | — | FDA letter on unreliable clinical data |
| `patent_status` | A | human only | expired (kill); none (kill) | none | Patent expired or no protection |
| `key_patent_license` | A | human only | non_exclusive (kill); field_excludes_lead (kill) | — | Key patent licence is non-exclusive or does not cover the lead indication |
| `key_markets_outlicensed` | A | human only | yes (strong minus) | — | US or EU rights out-licensed |
| `nonkey_territories_outlicensed_count` | A | human only | — | 0 | Several territories outside the US and EU out-licensed |
| `royalty_stack_pct` | A | human only | 12 (strong minus) | — | Total royalties above 10%; Total royalties 5–10% |
| `differentiation_claim` | A | human only | — | none | Me-too: late, differentiation not shown; Me-too with differentiation |
| `price_channel_direct` | A | derived | — | — | Me-too: late, differentiation not shown; Me-too with differentiation |
| `differentiation_evidence` | A | human only | — | — | Me-too: differentiation checked and not confirmed; Me-too: late, differentiation not shown; Me-too with differentiation |
| `sponsor_size` | A | human only | — | — | Complex manufacturing (cell, gene therapy, radioligand) outside a big company |
| `sponsor_prior_approvals` | A | human only | — | 0 | legacy items only |
| `big_pharma_partner` | A | human only | — | — | legacy items only |
| `partner_returned_asset` | A | human only | yes (strong minus) | — | A partner returned the asset |
| `runway_short` | A | human only | yes (strong minus) | — | Cash does not last until the next readout |
| `cmo_oai_or_warning_letter` | A | human only | — | — | Problematic status of a site or contract manufacturer |

# Validating scoring on real data

7 October 2026. Data: Minikel et al., *Nature* 2024, 29,476 target + disease pairs with outcomes by phase.

> **The current validation is in sections 12 and 13.** Versions 1.0 and 1.1 give identical verdicts on the facts in these data, so section 12 describes both. Sections 1–11 describe versions 0.3 and 0.4 and are kept as history. Two things in them must be read with the correction from section 12: the precedent estimate of "2.2–5.0×" is overstated (the correct bounds are 1.35–2.6× for any precedent, 1.7–3.5× for a precedent in a related disease), and the balanced accuracy range of "59–61%" is actually 57–61%.

The validation scripts and their raw output are kept in the original scorer archive, not in this repository; this document records their results.

## What was validated and what was not

| Part of scoring | State | On what |
| --- | --- | --- |
| Human genetics | **Validated on real data** | 13,030 pairs |
| Mechanism clinical precedent | **Validated within bounds** (lower and upper estimate) | 13,030 pairs, without development start dates |
| Indication is not "cursed" | A rough approximation validated | Without dates and without the "graveyard" list |
| Unmet need | A rough approximation validated | Only the number of launched targets |
| Translation chain, clinical effect, design, regulatory path | **Not validated** | No such facts in the data |
| All 44 rules | **Not validated** | No such facts in the data |
| Literature numbers in the config | Checked against tables | BIO 2021, Wong 2019, Minikel 2024 |

So four of eight items and no rules were validated on real data.

## 1. My calculation reproduces the paper

| Quantity | Paper | My calculation |
| --- | --- | --- |
| Pairs in the sample | 13,022 | 13,030 |
| With genetic support: launched / total | 189 / 667 | 189 / 668 |
| Relative success I → II | 1.08 | 1.08 |
| II → III | 1.57 | 1.57 |
| III → launch | 1.28 | 1.28 |

A difference of 8 pairs out of 13 thousand. The data processing is correct.

## 2. Human genetics

| Evidence type | Share of pairs | I → II | II → III | III → launch | Our colour |
| --- | --- | --- | --- | --- | --- |
| Any germline | 5.1% | 86% vs 80% | 64% vs 41% | 86% vs 68% | Green |
| Mendelian (OMIM) | 1.5% | 95% vs 80% | 82% vs 42% | 94% vs 69% | Green |
| GWAS with a confident gene | 4.0% | 84% vs 80% | 60% vs 42% | 83% vs 69% | Green |
| Somatic (intOGen) | 3.0% | 86% vs 80% | 58% vs 42% | 91% vs 69% | Green |
| GWAS without a confident gene | 1.3% | 73% vs 80% | 42% vs 43% | 85% vs 69% | Yellow |

- **The boundary between green and yellow is drawn correctly.** Weak GWAS gives nothing on two of three transitions.
- **The item is universal.** In all 15 areas with a sufficient sample, success with genetics is higher: from 1.4× (musculoskeletal) to 3.4× (metabolic). Oncology 2.1×.
- **The effect appears after Phase I.** Almost nothing at the I → II transition, the most at II → III.
- **The item is rare.** Green in only 5% of pairs (8% together with somatic).

A caveat from the paper: for 47% of launched pairs with GWAS support, the association was found after launch. The authors show that the effect does not depend on the year of discovery, so the conclusion holds.

## 3. Mechanism clinical precedent

Green if the same target was launched in another disease. The data have no development start dates, so I give two estimates:

| Estimate | Share of pairs | I → II | II → III | III → launch |
| --- | --- | --- | --- | --- |
| Ignoring time (overstates) | 57% | 85% vs 74% | 53% vs 24% | 76% vs 39% |
| For successful pairs only earlier launches (understates) | 55% | 84% vs 75% | 51% vs 30% | 72% vs 63% |

The true effect lies between them. Even the lower estimate gives an advantage at every transition, with confidence intervals that do not cross one.

## 4. The two items together

Share of pairs from Phase I that reached launch (lower precedent estimate; base 11.7%):

| | Precedent | No precedent |
| --- | --- | --- |
| **Genetics** | 33.0% (351 pairs) | 23.0% (317) |
| **No genetics** | 14.9% (6,855) | 5.6% (5,507) |

- **The items are independent and add up.** Splitting "Biology" into two items is confirmed.
- **Pairs with neither genetics nor precedent: 42% of all, launch 5.6%.** This is half the base. The number is an upper bound: the way of counting moves some successes into this cell.

## 5. Disease-level items

| Item (approximation) | Share of pairs | Launch |
| --- | --- | --- |
| Indication green | 98% | 11.7% vs 7.9% |
| Indication red | 1% | 8.8% vs 11.7% |
| Unmet need green (no other launched targets) | 11% | 10.9% vs 11.7% |
| Three or more launched targets in the disease | 72% | 11.5% vs 12.0% |

- **"Indication" in this form separates almost nothing:** green in 98% of pairs, red in 1%. The reason is partly my approximation (no curated "graveyard" list and no 10-year window), partly the threshold itself.
- **Unmet need is not associated with technical success.** This is expected: the item is commercial. But in the verdict it gives the same plus as genetics.

## 6. The full engine on the available facts

| Verdict | Share of pairs | Reached launch |
| --- | --- | --- |
| Invest | 29% | 19.1% |
| Do Not Invest | 71% | 8.6% |

Balanced accuracy 60% (sensitivity 47%, specificity 73%). Invest pairs reach launch 2.2× more often.

| Score | Pairs | Launch |
| --- | --- | --- |
| 0 | 3 928 | 3.7% |
| +1 | 5 296 | 12.3% |
| +2 | 2 738 | 19.8% |
| +3 | 978 | 17.0% |
| +4 | 56 | 17.9% |

The score separates up to +2, not beyond: the third and fourth pluses come from disease items that do not predict success.

316 pairs got Invest with neither genetics nor precedent (only for disease items); 6.6% of them reached launch, the same as among rejected ones.

## 7. Checking the numbers in the config

| Number | Ours | In the source |
| --- | --- | --- |
| BIO 2021, phase transitions | 52.0 / 28.9 / 57.8 / 90.6% | Matches |
| Wong 2019, biomarker, overall | 10.3% vs 5.5% | Matches |
| Wong 2019, biomarker, II → III | 38.6% vs 26.8% | Matches |
| Minikel 2024, all genetics | 2.6 | 2.63 |
| Minikel 2024, Mendelian | 3.7 | 3.67 |
| Genetics by phase | Placeholder √2.6 = 1.61 for two transitions | 1.08 / 1.57 / 1.28: replace |

## 8. What follows for the rules

These are proposals; they are not in the code.

1. **Invest must require at least one science green** (genetics, precedent, translation chain or clinical effect). Now two pluses for need and regulatory path give Invest without any biological evidence, and such pairs succeed no more often than rejected ones. On these data accuracy barely changes (60% → 61%), but 316 unfounded Invests disappear.
2. **The warning "neither genetics nor precedent".** The only new rule with direct support from 5,507 real pairs.
3. **Revisit the "Indication" threshold.** In its current form the item is red in 1% of cases. Option: count the share of failures rather than their number.
4. **Replace the genetics-by-phase placeholder** with 1.08 / 1.57 / 1.28 in the reference probability.

## 9. Limits of this validation

- **Half the scorecard and no rules were validated.** These numbers say nothing about the accuracy of the scoring as a whole.
- **The outcome here is clinical (launch), while the label in the organisers' table is financial.**
- **There are no development start dates.** Precedent and disease items partly see the future; bounds are given for precedent, not for disease items.
- **Pairs whose disease has no genetic data are excluded** (as in the paper), so the sample is biased toward better-studied diseases.
- **A balanced accuracy of 60% is the level to expect from open mechanism data.** The best published models with full trial data do better, because they know the results of the asset's own earlier phases.

## 10. Checking the version 0.4 changes one by one

Added after the proposals from section 8 went into the code. Summary and decision on each change: `SCORING.md`, sections 1–2. The main point: the mechanism-evidence requirement and the new warning gave +0.6 pp of balanced accuracy each; the new "Indication track record" item improved ranking (AUC 0.628 → 0.660 on the held-out half), but its red threshold failed validation and was removed.


## 11. Refinement after a repeated check

Looking for ways to improve, I recomputed "Indication track record" more strictly: the disease track record for each pair was taken only from targets in the other half of the data, with no part played by its own outcome. The numbers came out slightly lower than above:

| | Given above | Strict check |
| --- | --- | --- |
| Version 0.4 balanced accuracy | 60.6% | 59.4% |
| Score AUC | 0.660 | 0.644 |
| Launch with a green "Indication track record" | 16.2% vs 7% | 13.4% vs 8% |

The conclusions do not change (green works, red by share does not), but the honest accuracy estimate is the 59–61% range.

The ceiling on the same facts: a model with fitted weights, trained on one half and tested on the other, gives AUC 0.69 and a best balanced accuracy of 64%. So rules with equal weights trail the best possible on these data by about 4 pp.


## 12. Validation of version 1.0

Versions 0.4 and 1.0 were run through the same engine: 0.4 with its archived configuration, 1.0 with the current one. Weights and thresholds come from the configurations and are not searched on these data.

### 12.1. Why the "lower estimate" of precedent was not lower

- **The launch year is known for only 38% of launches** (695 of 1,816). Among launched pairs in the sample, the year is known for 37%.
- **The conservative rule from section 3** ("for successful pairs only earlier launches") applied only to these 37%. The other 63% of launched pairs saw all other launches of their target, including later ones. The 2.2× estimate was only partly lower.
- **Whether the year is known does not depend on the number of launches of the target:** 37% for targets with one launch, 41% for 2–4, 40% for 5–9, 32% for 10 or more. So launches with a year can be treated as a random subsample.

Hence two ways of counting:

| Way | Successes | Precedent | Bias |
| --- | --- | --- | --- |
| mixed | All launched pairs | As in version 0.4 | Overstates the effect: some precedents are later than the launch itself |
| symmetric | Only launched pairs with a known year, weighted 1,519 / 561 | For all pairs only from launches with a known year; for successes only strictly earlier ones | Understates the effect: precedent is thinned equally for successes and failures, and for failures it also sees later launches |

The true value lies between them. All numbers below are given for both.

### 12.2. Precedent: related vs unrelated disease

A related disease is one from the same therapeutic area (top-level MeSH in the data; `therapeuticAreas` in Open Targets). Pairs without genetics:

| Target precedent | mixed: pairs / launch | symmetric: pairs / launch |
| --- | --- | --- |
| In a related area | 4,144 / 19.4% | 2,470 / 15.9% |
| Only in an unrelated area | 2,436 / 6.6% | 1,985 / 7.9% |
| None | 5,410 / 5.5% | 6,736 / 9.2% |

- **A precedent in a related area raises the chance of launch 1.7–3.5×.** On both halves of the data and in both ways.
- **A precedent only in an unrelated area gives no advantage.** The configuration already gave green only for a related precedent, but the version 0.4 check treated any precedent as related. Now exactly what the rule says is checked.
- **Any precedent vs none:** 1.35–2.64× among pairs without genetics. These are the correct bounds for the "2.2–5.0" figure from section 3.

Consequence for the rules: the "neither genetics nor precedent" warning now also fires when the target is approved only in an unrelated area.

### 12.3. Genetics alone

Pairs without a precedent in a related disease and without a strong indication track record:

| Type of genetics | mixed: pairs / launch | symmetric: pairs / launch |
| --- | --- | --- |
| Mendelian | 122 / 36.9% | 113 / 39.6% |
| GWAS with a confident gene | 238 / 13.9% | 257 / 16.9% |
| Only a somatic driver | 65 / 4.6% | 115 / 6.8% |

- **Mendelian genetics alone gives 37–40% launch,** three times the base. Hence the strong green.
- **GWAS alone gives 14–17%,** the same as a precedent in a related disease without other evidence. This is the level of one science plus.
- **A somatic driver alone gives nothing:** 3 launches. The sample is small; in Minikel 2024 somatic evidence in oncology gives 2.3×, but almost all such successes also have a precedent.

### 12.4. Engine verdicts

Share of pairs / launch share in each verdict.

| Way, sample | Version | Invest | Conditional | Do Not Invest | Bal. accuracy | Score AUC |
| --- | --- | --- | --- | --- | --- | --- |
| mixed, half A | 0.4 | 28.2% / 19.4% | 0% | 71.8% / 8.9% | 60.2% | 0.656 |
| mixed, half A | 1.0 | 13.0% / 30.9% | 7.7% / 12.9% | 79.3% / 8.6% | 61.9% | 0.690 |
| mixed, half B | 0.4 | 31.6% / 17.5% | 0% | 68.4% / 8.7% | 59.4% | 0.644 |
| mixed, half B | 1.0 | 13.0% / 26.7% | 9.2% / 15.2% | 77.8% / 8.4% | 59.8% | 0.686 |
| mixed, all pairs | 0.4 | 29.8% / 18.4% | 0% | 70.2% / 8.8% | 59.8% | 0.650 |
| mixed, all pairs | 1.0 | 13.0% / 28.9% | 8.4% / 14.1% | 78.6% / 8.5% | 60.9% | 0.688 |
| symmetric, half A | 0.4 | 22.9% / 17.5% | 0% | 77.1% / 9.7% | 56.7% | 0.581 |
| symmetric, half A | 1.0 | 9.9% / 28.6% | 5.8% / 9.7% | 84.3% / 9.6% | 58.3% | 0.614 |
| symmetric, half B | 0.4 | 23.2% / 18.1% | 0% | 76.8% / 9.9% | 57.0% | 0.608 |
| symmetric, half B | 1.0 | 9.2% / 25.2% | 6.6% / 16.8% | 84.1% / 10.0% | 55.9% | 0.633 |
| symmetric, all pairs | 0.4 | 23.0% / 17.8% | 0% | 77.0% / 9.8% | 56.9% | 0.594 |
| symmetric, all pairs | 1.0 | 9.6% / 27.0% | 6.2% / 13.4% | 84.2% / 9.8% | 57.1% | 0.623 |

The "0.4" rows reproduce the version 0.4 check as it was: the mixed-way numbers match sections 10–11 (on half B: 1,988 Invest pairs, 347 successful).

Difference 1.0 minus 0.4 on all pairs, 95% confidence interval by bootstrap over targets:

| | mixed | symmetric |
| --- | --- | --- |
| Launch share among Invest | +10.5 pp (+8.5…+12.5) | +9.2 pp (+6.5…+12.2) |
| Score AUC | +0.038 (+0.026…+0.051) | +0.030 (+0.008…+0.049) |
| Balanced accuracy | +1.1 pp (−0.3…+2.7) | +0.2 pp (−1.5…+1.9) |

Successful and failed by verdict (mixed way):

| Version, sample | Verdict | Pairs | Successful | Failed | Failed per successful |
| --- | --- | --- | --- | --- | --- |
| 0.4, half B | Invest | 1,988 | 347 | 1,641 | 4.7 |
| 1.0, half B | Invest | 819 | 219 | 600 | 2.7 |
| 1.0, half B | Conditional | 578 | 88 | 490 | 5.6 |
| 1.0, half B | Do Not Invest | 4,888 | 413 | 4,475 | 10.8 |
| 1.0, all pairs | Invest | 1,697 | 490 | 1,207 | 2.5 |
| 1.0, all pairs | Conditional | 1,097 | 155 | 942 | 6.1 |
| 1.0, all pairs | Do Not Invest | 10,236 | 874 | 9,362 | 10.7 |

- **In version 1.0 Invest is half as frequent and one and a half times as precise.** The gain in launch share among Invest is statistically robust in both ways.
- **Balanced accuracy did not change.** It weighs a missed success and a false Invest equally; version 1.0 deliberately trades the first for the second.
- **Half of the successful pairs get Do Not Invest.** Of 1,519 launched pairs, 874 have Do Not Invest: on mechanism-level facts they cannot be told apart from failures.
- **If one looks for the best balanced accuracy,** the version 1.0 score with another threshold gives 67% (mixed) and 60% (symmetric), but then about half of all pairs get Invest.

### 12.5. Version 1.0 ablation

All pairs; share of pairs with Invest / launch share among them; balanced accuracy; score AUC.

| What is removed | mixed | symmetric |
| --- | --- | --- |
| Nothing | 13.0% / 28.9%; 60.9%; 0.688 | 9.6% / 27.0%; 57.1%; 0.623 |
| Item "Human genetics" | 8.4% / 29.9%; 57.4%; 0.677 | 5.2% / 23.4%; 53.0%; 0.610 |
| Item "Mechanism clinical precedent" | 3.3% / 35.1%; 53.7%; 0.661 | 3.3% / 36.3%; 54.0%; 0.617 |
| Item "Indication track record" | 4.8% / 31.4%; 54.6%; 0.674 | 3.7% / 33.8%; 54.0%; 0.604 |
| Item "Unmet need" | 13.0% / 28.9%; 60.9%; 0.693 | 9.6% / 27.0%; 57.1%; 0.621 |
| Warning "neither genetics nor precedent" | 13.0% / 28.9%; 60.9%; 0.662 | 9.6% / 27.0%; 57.1%; 0.615 |
| Strong green for Mendelian genetics | 12.1% / 28.3%; 59.7%; 0.685 | 8.4% / 25.2%; 55.5%; 0.620 |
| Requirement of two science pluses | 21.4% / 23.1%; 61.9%; 0.688 | 15.8% / 21.6%; 57.6%; 0.623 |

- **The three science items carry the result.** Without any of them balanced accuracy falls by 3–7 pp.
- **Unmet need does not affect Invest.** With two science pluses the difference already reaches the threshold. The item only decides whether a pair with one science plus becomes Conditional.
- **The warning does not change verdicts on these facts,** but improves the score order (AUC +0.008…+0.026). It will start changing verdicts once asset-level pluses appear.
- **The two-science-pluses requirement** removes 6–8% of pairs with a 13–14% launch share from Invest and moves them to Conditional.

### 12.6. The ceiling on the same facts

Logistic regression and gradient boosting; five-fold cross-validation, all pairs of one target in one fold. Features: type of genetics, related and unrelated precedent, number and share of Phase 3 successes in the disease, number of launched targets in the disease, oncology.

| | AUC, mixed | AUC, symmetric | Best bal. accuracy, mixed / symmetric |
| --- | --- | --- | --- |
| Gradient boosting | 0.737 | 0.707 | 68.0% / 64.7% |
| Logistic regression | 0.723 | 0.679 | 66.7% / 62.9% |
| Version 1.0 score | 0.688 | 0.623 | 66.9% / 59.5% |
| Version 0.4 score | 0.650 | 0.594 | 62.3% / 56.9% |

- **"Best balanced accuracy" is a ceiling, not an estimate:** the threshold is chosen on the same data.
- **Rules trail models by 0.04–0.08 AUC.** Models see continuous disease features and oncology; rules do not.
- **The ceiling from section 11 (AUC 0.69, 64%) rose,** because the models now distinguish related and unrelated precedent.
- **Even a fitted model does not reach 70% balanced accuracy on mechanism facts.**

### 12.7. Reference probability

The cell table and caveats: `SCORING.md`, section 14. The numbers in `benchmarks.yaml` were produced and cross-checked by the validation script.

Out-of-sample calibration: cell shares were computed on one half and applied to the other.

| Way | AUC | Brier (constant base 0.1030) | Mean forecast / actual |
| --- | --- | --- | --- |
| mixed | 0.687 | 0.0966 | 11.7% / 11.7% |
| symmetric | 0.608 | 0.1008 | 11.8% / 11.7% |

| Group by forecast, mixed | Pairs | Mean forecast | Actual |
| --- | --- | --- | --- |
| Bottom half | 4,019 | 5.7% | 6.0% |
| Next 30% | 5,642 | 8.9% | 9.4% |
| Next 10% | 1,970 | 18.9% | 17.2% |
| Next 7% | 734 | 27.0% | 27.5% |
| Top 3% | 665 | 33.3% | 30.7% |

In the symmetric way calibration is worse: in the group with a 19.8% forecast the actual was 14.3%. So the reference is given as a range, not a single number.

### 12.8. The orphan flag

The analyst names rare diseases as a path to FDA designations. The data have an orphan flag per pair, but it could not be used to validate the "Regulatory path" item.

- **The flag becomes more frequent with stage:** 8% of preclinical pairs, 17% in Phase I, 24% in Phase II, 32% in Phase III, 31% of launched. The designation is granted during development, so it is partly a consequence of progress.
- **The halves disagree.** Launch with vs without the flag: 17.9% vs 10.0% on half A, 13.8% vs 10.7% on half B. Phase III → launch transition: 80.1% vs 65.6% on A and 69.0% vs 69.1% on B.

Green for a rare disease rests on the analyst's words and on BIO 2021 (17.0% from Phase I for rare non-oncology diseases vs 5.9% for common chronic ones), not on these data.

### 12.9. Limits

- **The main sample is used up.** Both halves were examined while working on version 0.4. The version 1.0 decisions (two science pluses, strong green for Mendelian genetics, related precedent) were made on the same data they were validated on. Each decision holds on both halves and in both ways of counting precedent, but this does not replace an untouched sample. The only such subsample is analysed in section 13.
- **Four of eight items and one of 51 rules were validated.**
- **The outcome is clinical, not financial.**
- **The disease track record includes later events.** For each pair it was taken only from targets in the other half, but there are no dates.
- **The symmetric way rests on the assumption** that the launch year is missing at random. It is supported by the equal share of launches with a year among targets with different numbers of launches, but it cannot be proven with the data.

## 13. Untouched subsample: diseases without genetic data

Added in version 1.1 after an external review. The review noticed that the "neither genetics nor precedent" warning was validated only where the disease has genetic data: the paper and all sections above excluded the other diseases. No check had touched these excluded pairs, and the rules were not tuned on them.

**Sample:** 1,740 pairs with a known Phase I outcome in 179 diseases, 676 targets. 17.1% reached launch; in diseases with genetic data 11.7%. The diseases are small: a median of three pairs per disease and two known Phase 3 outcomes.

### 13.1. The "neither genetics nor precedent" warning

| | mixed | symmetric |
| --- | --- | --- |
| Pairs without a precedent in a related area, diseases without genetic data | 12.2% (1,100 pairs) | 15.4% (1,222) |
| The same pairs in diseases with genetic data (section 12) | 5.9% | 8.9% |

- **The review was right.** Where the disease has no genetic data at all, "genetics does not support the target" means nothing: such pairs reach launch no less often than the overall base of 11.7%.
- **Fix:** the value `genetic_support: no_data`, with which the warning is silent.
- **What the fix does not account for.** Relative to the base of these diseases themselves (17.1%), pairs without a related precedent are still worse, and with the warning the score orders them better (AUC 0.584 vs 0.533 in mixed). This does not change verdicts on these facts. I left the rule silent: unknown must not punish.

### 13.2. Precedent

| Target precedent | mixed | symmetric |
| --- | --- | --- |
| In a related area | 25.5% (640 pairs) | 22.4% (355) |
| Only in an unrelated area | 13.1% (443) | 16.0% (380) |
| None | 11.6% (657) | 15.2% (842) |

The related precedent is confirmed out of sample, on both halves: 24.6% vs 11.1% and 26.3% vs 13.6% in mixed; 18.0% vs 14.2% and 26.7% vs 16.8% in symmetric. The unrelated one again does not differ from none.

### 13.3. Verdicts

| | mixed | symmetric |
| --- | --- | --- |
| Invest: share of pairs / launch | 6.4% / 22.3% | 3.8% / 10.0% |
| Conditional | 9.9% / 12.1% | 6.0% / 8.5% |
| Do Not Invest | 83.6% / 17.3% | 90.2% / 17.9% |
| Score AUC | 0.533 | 0.494 |

- **Invest here is no better than the rest.** In mixed 22.3% vs a base of 17.1%; in symmetric below the base, but that is 63 pairs and 3 launches.
- **Reason one: the indication track record.** Invest in this subsample is possible only as "precedent + strong track record". Pairs with precedent but without a strong track record reach launch more often: 26.1% vs 22.3% in mixed, 24.9% vs 10.0% in symmetric. The second science plus added nothing here.
- **Reason two: unmet need.** Conditional here means "precedent + green need", and exactly these pairs are the worst among pairs with precedent: 12.1% vs 30.4% in mixed, 8.5% vs 27.2% in symmetric. Overall, green need: 12.0–14.4% launch vs 18.5–19.7%.
- **In the main sample the sign is the same, but weaker:** among pairs with one science plus, green need gives 13.7–14.4% vs 14.4–17.8%.

### 13.4. What follows

| Statement | Main sample | Untouched subsample |
| --- | --- | --- |
| A related precedent raises the chance of launch | Yes, 1.7–3.5× | Yes, 1.5–2.1× |
| An unrelated precedent gives nothing | Yes | Yes |
| A strong indication track record adds to precedent | Yes: 22–28% vs 14–17% | No; the sample is small |
| Green need does not hurt the chance of launch | Almost: slightly lower | No: noticeably lower |
| Invest is more precise than the rest | Yes: 27–29% vs 9–10% | Not shown |

- **I did not change the rules.** Any change fitted to these 1,740 pairs would destroy the only untouched subsample. Candidates for review: whether to count the indication track record as a science plus, and whether need should move a pair with one science plus into Conditional.
- **The subsample is atypical.** These are small, poorly studied diseases without genetics; the Invest path through genetics, the strongest in the main sample, is not tested here at all.
- **Both questions should be settled by the deals table,** not by another look at these data.

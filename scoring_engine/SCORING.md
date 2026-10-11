# unobio scoring: full description

Version 1.3, 9 October 2026. The configuration is frozen: everything described here is implemented in `benchmarks.yaml` and `scoring/` and covered by 294 tests.

- **Config hash:** `6c3a5348be57f3ae366fc1f69ea956310b87d02288b5cfa2c789ccdf4ded7d31` (sha256 of `benchmarks.yaml`; 1.2 was `465f998b…`, 1.1 was `d4d3b6b5…`). `python -m scoring version` prints it; the version and the hash are written into every result. The hash changed from `3c4a0811…` when the configuration's texts were translated into English; the logic is identical (checked on 3,000 random fact sets: same verdicts, colours, rules, points, counterfactuals and claim handling).
- **Previous versions** 0.4 and 1.0 are not part of this repository. The engine with the 0.4 configuration gave the same results as the 0.4 engine: checked on 56,000 random fact sets.
- **Validation on data:** 13,030 real target + disease pairs (Minikel et al., *Nature* 2024) and another 1,740 pairs that no earlier check had touched. Analysis in `VALIDATION.md`, sections 12 and 13.
- **"Frozen" does not mean "proven".** The rules of versions 1.0 and 1.1 were spotted and checked on the same 13,030 pairs. The only untouched subsample confirmed precedent, but did not confirm Invest via the "precedent + indication track record" path (section 2).

Level marks: **M** means mechanism (disease + target, computed from open data); **A** means asset (a specific drug; the brief's input usually lacks these facts, so they become due-diligence questions).

---

## 1. What changed

### Version 1.3: changes from the independent review of 8 October 2026

The review (`review_en`: `REVIEW.md`, `findings.csv`, `improvement_plan.md`) audited a larger bundle (scorer "1.2", config `76c80f27…`, with an economics module and a `bridge/` claims chain). That "1.2" is a different branch from the 1.2 below; this is 1.3 of this repository. The scorer and claims findings that apply here:

- **Claims gate (F32–F34, M1).** An LLM value that can trigger a kill rule or a strong minus waits for a human; a second document read by the same LLM step no longer counts as independent confirmation. An LLM value that changes the verdict together with the other facts (including one that removes a minus, or acts only in combination) also waits for a human.
- **Me-too (F38, M6).** The kill rule `me_too` now needs `differentiation_evidence: false` (claim checked and refuted). The old condition is the strong minus `me_too_unproven` (cluster competition). The old rule killed Trulicity at the start of Phase 3. No kill rule has a default any more.
- **Caps (F31, M7).** A rule can cap the verdict at Conditional (`caps_at`); `runway_short` does. Caps only lower an Invest.
- **Coverage (F44, S6).** Invest needs at least 5 of 8 scorecard items known or one asset-level item (`invest_min_items_known`, `invest_min_asset_known`); otherwise Conditional, grounds `low_coverage`.
- **Validation (F39, F40).** The tables below were produced before the coverage requirement. The review reproduced them and found that the share "Invest → 27–29% launches" is a result on the data used to build the rules; on the only untouched subsample Invest was not better than the base rate (AUC 0.53 / 0.49). The coverage requirement moves most Minikel pairs (mechanism facts only) from Invest to Conditional. Treat the validation as in-sample until an out-of-time check with dated features exists (review S10).

### Version 1.2: translation chain for the class

- Three mechanism-level facts: `class_exposure_human`, `class_target_engagement_human`, `class_pd_response_human` (links 2–4 shown in humans for another drug of the same mechanism; exposure only from the same modality). They come from FDA labels and PubMed abstracts read by the LLM with checked quotes. They make the item "Translation chain" yellow, never green: green still needs the asset's own links.
- New strong minus `engaged_no_benefit` ("Target engaged in humans, still no efficacy"): class target engagement or PD response shown, at least one Phase 2/3 efficacy failure of the mechanism in this disease, and no approved drug of the mechanism here. Not clustered with `one_mechanism_failure` on purpose: it counts the engagement evidence, not the failure again; together they give 4 minuses (Do Not Invest).
- Validation tables below are for 1.1. Version 1.2 changes nothing when the class facts are unknown, which is the case for every pair in them, so their verdicts are identical.

### Version 1.1: fixes after an external review

| # | What was wrong in 1.0 | What was done | Check |
| --- | --- | --- | --- |
| 1 | "Drug approved in another indication" made the translation chain green: a science plus and mechanism evidence without any evidence for this disease | An approval elsewhere gives no green: the item is yellow, and the approval still protects from red. If the other disease is related, "Clinical precedent" counts it | On real pairs, approval of the target in an unrelated area gives no advantage (6.6–7.9% vs 5.5–9.2%). The set "approved elsewhere + indication track record + need" gave Invest in 1.0, now Do Not Invest |
| 2 | The "neither genetics nor precedent" warning was validated only on diseases with genetic data, but it also fired where there is none at all | New value `genetic_support: no_data`; with it the warning is silent | In diseases without genetic data such pairs reach launch in 12–15% of cases: no less often than the overall base of 11.7% |
| 3 | The asset's own positive Phase 2 alone gave two science pluses, i.e. Invest; the fact often comes from a sponsor's claim | Strong green only when the asset has moved to Phase 3 after a positive Phase 2. The claim alone gives an ordinary green | Not checkable with data; the condition now matches what BIO 2021 measures (52.4% from Phase 3) |
| 4 | It was unclear whether Phase 2+ without entered PK/PD data gives red in "Translation chain" | It does not. Red for "no link at all" requires an explicit `pillars_human: 0`; this is written in the rule and pinned by a test | Test |
| 5 | Section 5 spoke of two axes, section 9 labelled clusters with three | There are two axes: "Science" and "Commercial and execution" | — |
| 6 | 37–40% and 41–45% for Mendelian genetics without explanation | These are different sets: 122 pairs without other evidence and all 192 pairs. Labelled everywhere | — |
| 7 | "Unmet need" was presented next to validated items | Stated plainly: the item rests only on expert logic; it is not associated with launch, or associated negatively | Section 2 |
| 8 | The word "final" without an untouched sample | Removed; one untouched subsample was found and used | Section 2 |
| 9 | The pipeline interface was not described | Fact catalog, "claims → facts" rules, one result for the `scores` and `verdicts` tables | Section 20 |

### Version 1.0

| # | Change | Basis | What validation showed |
| --- | --- | --- | --- |
| 1 | Invest requires two science-axis pluses. If the difference already reaches the threshold and there is mechanism evidence, but fewer than two science pluses, the verdict is Conditional | Real pairs | The launch share among Invest rose from 18% to 27–29%; Invest pairs became 10–13% instead of 23–30% |
| 2 | Mendelian genetics is a strong green: 2 pluses | Real pairs; Minikel 2024 | 122 pairs where apart from it there is no precedent and no strong track record: 37–40% launch. GWAS in the same conditions: 14–17% |
| 3 | The asset's own positive Phase 2 is a strong green: 2 pluses (narrowed in 1.1 to assets in Phase 3) | Literature: Lo 2019; BIO 2021 | No such facts in the data; not checked |
| 4 | Precedent counts only in this or a related disease; the "neither genetics nor precedent" warning also fires when the target is approved only in an unrelated area | Real pairs | Approval only in another area: 6.6–7.9% launch; no precedent at all: 5.5–9.2% |
| 5 | Conditional, like Invest, is impossible without mechanism evidence | Logic | In version 0.4 a warning could improve the verdict; after the fix a search over 59,000 sets found no anomalies |
| 6 | The Conditional condition counts pluses, not the number of green items | Logic | Mendelian genetics with one warning gives Conditional, not Do Not Invest |
| 7 | "No response in an animal model": was a kill rule, became a strong minus | Analyst's words | Not checkable with data |
| 8 | Complex manufacturing: unknown sponsor size is treated as "not a big company" | Analyst's words | Not checkable with data |
| 9 | New warning: grade 4 adverse events in a non-fatal disease | Analyst's words | Not checkable with data |
| 10 | The regulatory path is green for a rare disease too | Analyst's words; BIO 2021 | The orphan flag in the data depends on stage; could not be checked reliably |
| 11 | The result contains the verdict grounds and data coverage | Analyst's words; open decision 4 | Does not affect the verdict |
| 12 | Reference probability: by mechanism evidence and by stage | Open decision 2; brief | Calibrated out of sample (section 14) |
| 13 | Config version and hash in every result | Brief: reproducibility and logs | — |

There are now 51 rules: 9 kill, 23 strong minuses, 19 warnings. Eight scorecard items, 86 facts.

**How the open decisions of version 0.4 were closed:**

| Decision | What was done |
| --- | --- |
| 1. Invest condition | Two science pluses. This is the "genetics or (precedent + strong disease track record)" variant, extended to all eight items |
| 2. Small improvements | Mendelian genetics as 2 pluses: added. Disease track record at Phase 2: no. Reference probability: added |
| 3. Minus for oncology | Not added |
| 4. "Not enough data" state | Not a separate verdict, but the grounds `insufficient_evidence` and data coverage |
| 5. Mechanism-level rules | Remain expert; there is nothing to check them with |

**Considered and not added:**

| Option | Reason |
| --- | --- |
| Disease track record also at Phase 2 | Effect within noise on both halves of the data |
| Minus for oncology | Lowers balanced accuracy; the analyst did not name such a rule. Oncology is covered by the reference probability by stage |
| Invest threshold +1 instead of +2 | Half of all pairs would get Invest; for an investor a false Invest costs more than a missed one |
| A separate fourth verdict "not enough data" | The brief requires three values; the difference is now shown by the verdict grounds |
| A trained model instead of rules | Section 18 |

---

## 2. What validation showed

### The main correction to version 0.4

The launch year is known for only 38% of launches in the data. The precedent estimate called "lower" in version 0.4 was lower only for those 38%: the other launched pairs saw all other launches of their target, including later ones. So everything is now computed in two ways.

| Way | How it counts precedent | Which way it is biased |
| --- | --- | --- |
| mixed | As in version 0.4 | Overstates the precedent effect |
| symmetric | Only launches with a known year count as successes (weighted); precedent for all pairs is counted only from launches with a known year | Understates the precedent effect |

The true value lies between them. Any precedent of the target raises the chance of launch 1.35–2.6× (2.2–5.0× was claimed); a precedent in a related disease 1.7–3.5×. The genetics estimate barely depends on the way.

### Version 1.1 vs 0.4 (all 13,030 pairs; share of pairs / launch share)

On the facts available in these data, versions 1.0 and 1.1 give identical verdicts.

| | 0.4, mixed | 1.1, mixed | 0.4, symmetric | 1.1, symmetric |
| --- | --- | --- | --- | --- |
| Invest | 29.8% / 18.4% | 13.0% / 28.9% | 23.0% / 17.8% | 9.6% / 27.0% |
| Conditional | 0% | 8.4% / 14.1% | 0% | 6.2% / 13.4% |
| Do Not Invest | 70.2% / 8.8% | 78.6% / 8.5% | 77.0% / 9.8% | 84.2% / 9.8% |
| Sensitivity / specificity | 47% / 72% | 32% / 90% | 35% / 79% | 22% / 92% |
| Balanced accuracy | 59.8% | 60.9% | 56.9% | 57.1% |
| Score AUC | 0.650 | 0.688 | 0.594 | 0.623 |
| Launch among the top 10% by score | 20.2% | 25.0% | 18.7% | 23.2% |

Base: 11.7% of pairs reached launch.

Difference between versions with a 95% confidence interval (bootstrap over targets):

| | mixed | symmetric |
| --- | --- | --- |
| Launch share among Invest | +10.5 pp (+8.5…+12.5) | +9.2 pp (+6.5…+12.2) |
| Score AUC | +0.038 (+0.026…+0.051) | +0.030 (+0.008…+0.049) |
| Balanced accuracy | +1.1 pp (−0.3…+2.7) | +0.2 pp (−1.5…+1.9) |

- **The three verdicts now match three levels of chance.** Invest: 27–29% launch, 2.3–2.5× the base. Conditional: 13–14%, close to the base. Do Not Invest: 8.5–9.8%, below the base.
- **Invest became rarer and more precise.** On the held-out half there are 2.7 failed pairs per successful one; in version 0.4 there were 4.7.
- **Balanced accuracy did not change.** The honest range for these data: 57–61% on all pairs and 56–62% on separate halves (59–61% was claimed in version 0.4).
- **The price: Invest misses more successful pairs.** Sensitivity fell from 35–47% to 22–32%.

### What each level of evidence gives (launch share, from the symmetric to the mixed way)

| Mechanism evidence | Pairs | Launch | Science pluses |
| --- | --- | --- | --- |
| Mendelian genetics, all pairs | 192 | 41–45% | 2 |
| of them without precedent and without a strong indication track record | 122 | 37–40% | 2 |
| GWAS or somatic and a precedent in a related disease | 436 | 26–27% | 2 |
| No genetics: precedent and a strong indication track record | 960 | 22–28% | 2 |
| GWAS or somatic and a strong indication track record | 109 | 20–26% | 2 |
| Only GWAS with a confident gene | 238 | 14–17% | 1 |
| No genetics: only a precedent in a related disease | 3,184 | 14–17% | 1 |
| No genetics or precedent: only a strong indication track record | 1,899 | 6–11% | 1, but no mechanism evidence |
| Only a somatic driver | 65 | 5–7% | 1 |
| None of the above | 5,947 | 6–8% | 0 |

Every cell with two science pluses leads to launch for at least 20% of pairs; every cell with one, for at most 17%. The Invest threshold is drawn at this boundary.

### Version 1.1 ablation

| What is removed | Launch among Invest (mixed / symmetric) | Score AUC (mixed / symmetric) |
| --- | --- | --- |
| Nothing | 28.9% / 27.0% | 0.688 / 0.623 |
| Item "Human genetics" | 29.9% / 23.4% | 0.677 / 0.610 |
| Item "Mechanism clinical precedent" | 35.1% / 36.3% | 0.661 / 0.617 |
| Item "Indication track record" | 31.4% / 33.8% | 0.674 / 0.604 |
| Item "Unmet need" | 28.9% / 27.0% | 0.693 / 0.621 |
| Warning "neither genetics nor precedent" | 28.9% / 27.0% | 0.662 / 0.615 |
| Strong green for Mendelian genetics | 28.3% / 25.2% | 0.685 / 0.620 |
| Requirement of two science pluses | 23.1% / 21.6% | 0.688 / 0.623 |

- **Each of the three science items is needed.** Without any of them the Invest share drops to 3–8% of pairs, and balanced accuracy to 53–57%.
- **"Unmet need" is not supported by the data.** Without it the score AUC is no worse (0.693 vs 0.688 in mixed). Among pairs with one science plus, a green need even means a slightly lower chance of launch: 13.7–14.4% vs 14.4–17.8%. The item rests only on expert logic: the analyst names need as the first thing she looks at, and it is about commercial value, which these data do not measure.
- **Consequence for Conditional.** It is exactly the commercial pluses that move a pair with one science plus into Conditional. So Conditional is no more precise than the pairs with one science plus that stayed in Do Not Invest; the difference between them is commercial, not scientific.

### Untouched subsample: diseases without genetic data

The paper and all earlier checks excluded diseases with no genetic data at all. These are 1,740 pairs in 179 diseases; 17.1% of them reached launch. The rules were not tuned on them, so this is the only honest out-of-sample check. There is no genetics here by definition, so only the precedent path is checked.

| | mixed | symmetric |
| --- | --- | --- |
| Precedent in a related area | 25.5% (640 pairs) | 22.4% (355) |
| Precedent only in an unrelated area | 13.1% (443) | 16.0% (380) |
| No precedent | 11.6% (657) | 15.2% (842) |
| Related precedent and a strong indication track record (Invest) | 22.3% (112) | 10.0% (63; 3 launches) |
| Related precedent without a strong track record | 26.1% (528) | 24.9% (292) |
| Related precedent, green need (Conditional) | 12.1% (173) | 8.5% (99) |
| Related precedent, need not green | 30.4% (467) | 27.2% (256) |
| Score AUC | 0.533 | 0.494 |

- **Confirmed: related precedent.** Twice the chance of launch on both halves; an unrelated precedent again gives nothing.
- **Not confirmed: a strong indication track record as the second science plus.** Invest pairs reach launch no more often than pairs with precedent alone. The sample is small (112 and 63 pairs), and the track record in these diseases is short (median two Phase 3 outcomes), so this is not a refutation, but not a confirmation either.
- **A green need here means a lower chance:** 12.0–14.4% vs 18.5–19.7%. A disease with no approved drug at all more often turns out to be hard.
- **The score does not rank pairs in this subsample** (AUC about 0.5): the only working signal, precedent, gives one plus, and need acts in the opposite direction.

I did not change the rules based on these results: a change fitted to the only untouched subsample would destroy it. This is the first thing to check on the deals table.

### What was not confirmed

- **A somatic driver alone, without precedent or indication track record:** 3 launches out of 65 pairs. The sample is small, so the item stays an ordinary green, but alone it does not lead to Invest.
- **A strong indication track record without mechanism evidence:** 6–11% launch, not above the base. So it counts toward science pluses, but it is not mechanism evidence.
- **Approval of the target only in an unrelated area** gives no advantage.

### Limits of the validation

- **The main sample is used up.** Both halves of the 13,030 pairs were already examined in version 0.4. I spotted the two-science-pluses condition, the strong green for Mendelian genetics and the related precedent on the same data I validated them on. The only untouched subsample (above) confirmed only precedent.
- **Four of eight items and one of 51 rules were checked.** The translation chain, clinical effect, design, regulatory path and 50 rules have nothing to check them with.
- **The outcome is clinical (launch), not financial.**
- **There are no development start dates.** The disease track record includes later events too; precedent is given as bounds.
- **Pairs whose disease has no genetic data are excluded,** as in the paper.

---

## 3. Input

| Field | Required | What scoring does with it |
| --- | --- | --- |
| Disease | Yes | Basis of all mechanism-level facts |
| Target / mechanism | Yes | Same |
| Modality | No | Kill rule on target mismatch; warning on complex manufacturing |
| Stage | No | Strong green of clinical effect (Phase 3 and later); red of the translation chain, but only together with an explicit "no link shown"; reference probability |
| Preclinical results | No | Link 1 of the translation chain; causal preclinical evidence |
| Biomarkers | No | Condition for green in "Design"; link 4 of the chain |
| Route of administration | No | Sales channel for the me-too rule |

The fact's origin (found in a source, provided by the user, derived from other facts) is kept by the layer before scoring; the engine itself marks only derived facts.

---

## 4. How the verdict is computed

1. **Check and derive.** Facts are checked for type and bounds; obvious consequences are derived; a contradictory set stops scoring.
2. **Scorecard.** Green gives 1 plus, strong green 2 pluses, red 2 minuses, yellow and unknown 0. If both the red and the green condition hold, red wins.
3. **Rules.** A kill rule gives Do Not Invest at once. A strong minus costs 2, a warning 1.
4. **Clusters.** From each cluster only the strongest firing counts as minuses.
5. **Absorption.** A rule adds no minuses if a red item already counts the same event.
6. **Thresholds.**

```
kill rule                                                   → Do Not Invest
minuses ≥ 4                                                 → Do Not Invest
pluses − minuses ≥ 2, no mechanism evidence                 → Do Not Invest
pluses − minuses ≥ 2, science pluses ≥ 2                    → Invest
pluses − minuses ≥ 2, science pluses < 2                    → Conditional
pluses − minuses ≤ 0                                        → Do Not Invest
pluses − minuses = 1, pluses ≥ 2 and mechanism evidence     → Conditional
otherwise                                                   → Do Not Invest
```

| Term | Meaning |
| --- | --- |
| Strong green | Mendelian genetics; the asset's own positive Phase 2 when the asset has already moved to Phase 3 |
| Science pluses | Pluses of green items on the science axis: human genetics, clinical precedent, indication track record, translation chain, clinical effect |
| Mechanism evidence | At least one green among four: human genetics, clinical precedent, translation chain, clinical effect. The indication track record is a property of the disease and is not included |

Two science pluses come either from one strong green or from two ordinary ones. Pluses only for disease properties (need, indication track record, regulatory path) are enough neither for Invest nor for Conditional.

### Verdict grounds

The grounds are returned together with the verdict. They separate "no evidence" from "evidence against".

| Grounds | Verdict | Meaning |
| --- | --- | --- |
| `positive` | Invest | Pluses outweigh, science evidence is sufficient |
| `science_short` | Conditional | The picture is positive, but a second science piece of evidence is missing. Condition: obtain it |
| `balanced` | Conditional | Pluses and minuses are nearly balanced |
| `insufficient_evidence` | Do Not Invest | Not enough confirmation. This is not negative evidence |
| `outweighed` | Do Not Invest | Minuses outweigh pluses |
| `negatives` | Do Not Invest | 4 or more minuses accumulated |
| `kill` | Do Not Invest | A kill rule fired |

**Data coverage** (`coverage`) shows for how many of the eight items there were any facts, separately for the mechanism level (5 items) and the asset level (3 items). An Invest with coverage 1 of 8 and an Invest with coverage 7 of 8 must read differently in the report.

---

## 5. Scorecard: eight items

### Step 1. Disease and unmet need

| Item | Axis | Green | Red |
| --- | --- | --- | --- |
| **Unmet need** (M) | Commercial | No approved drugs; or 15+ years without a new mechanism; or no active comparator | Three or more approved drugs and a new mechanism within the last 5 years |

The item rests only on expert logic. It is not associated with technical success, or associated negatively (section 2); it is about commercial value.

### Step 2. Mechanism validation

| Item | Axis | Green | Red |
| --- | --- | --- | --- |
| **Human genetics** (M), mechanism evidence | Science | GWAS with a confident gene or a somatic driver: 1 plus. Mendelian genetics: strong green, 2 pluses | Genetics contradicts causality |
| **Mechanism clinical precedent** (M), mechanism evidence | Science | The same mechanism succeeded in this disease (another drug) or in a related disease (any drug, including this one) | None: rules count failures |
| **Indication track record** (M) | Science | The disease is not on the "graveyard" list, 5+ Phase 3 outcomes of other targets are known, and 70% or more passed | The disease is on the curated "graveyard" list |

**Definitions the rules depend on:**

| Term | Definition |
| --- | --- |
| Same mechanism | Same target (gene; for bispecifics both targets) and same direction of action: inhibition or activation. Drug type does not matter |
| Same class | Same mechanism. For platform-specific safety signals (gene therapy vector, cell product) also the same modality |
| Related disease | A shared therapeutic area: `therapeuticAreas` in Open Targets, top-level MeSH in the validation data |
| Reason a program stopped | One of six: efficacy, safety, enrollment, business decision, funding, unknown |

**Types of biology evidence:**

| Type | Examples | What it gives | Validation |
| --- | --- | --- | --- |
| Causal in humans, Mendelian | OMIM in validation; Open Targets open sources in the pipeline | Strong green | All 192 pairs: 41–45% launch; 122 pairs without other evidence: 37–40% |
| Causal in humans, other | GWAS with a confident gene; somatic driver | Green | GWAS alone 14–17%; somatic alone 5–7% (small sample) |
| Causal preclinical | Knocking out or blocking the target in cells, tissue, animals | Yellow at most | Not checked |
| Correlational | Expression, diseased tissue, pathway, number of publications | Yellow at most | Not checked |
| GWAS without a confident gene, genetics of an unrelated disease | | Yellow at most | Confirmed: no advantage |

### Step 3. Translation into humans

| Item | Axis | Green | Red |
| --- | --- | --- | --- |
| **Translation chain** (A), mechanism evidence | Science | Links 2, 3 and 4 shown in humans | One of links 2–4 is known to be broken; or the asset is in Phase 2 or later and it is explicitly stated that no link was shown. In both cases only if there is no positive Phase 2 or approval elsewhere |

- **Data not entered give no red.** An asset in Phase 2 without a single PK/PD fact leaves the item unknown. Red for "no link at all" requires an explicit `pillars_human: 0`, which only a human or a complete structured source can set (section 20).
- **Approval of the drug in another indication** makes the item yellow and protects from red, but gives no green. It is evidence for this disease only when the other disease is related, and that is counted by "Clinical precedent".

| # | Link | Where it counts |
| --- | --- | --- |
| 1 | Molecular effect in a disease model | A break is a strong minus (no response in animals) |
| 2 | Exposure in humans: effective concentration is reachable in the right tissue | This item |
| 3 | Target engagement in humans | This item |
| 4 | Biological response in humans | This item |
| 5 | Patient benefit | Item "Clinical effect shown" |
| — | Therapeutic window | Rule "toxicity at efficacious exposure" |

Every unknown link becomes a due-diligence question.

### Step 4. Clinical development

| Item | Axis | Green | Red |
| --- | --- | --- | --- |
| **Clinical effect shown** (A), mechanism evidence | Science | The asset's own Phase 2 in this indication met its primary endpoint: 1 plus. If the asset is already in Phase 3 or filed after that: strong green, 2 pluses | The asset's own trial failed for efficacy |
| **Trial design** (A) | Commercial and execution | The endpoint matches the mechanism, dose ranging was not skipped, and the trial is randomized or selects patients by a biomarker | The endpoint does not measure the drug's action; or an open-label design with a subjective endpoint |
| **Regulatory path** (M) | Commercial and execution | At least one FDA designation; or an approval precedent on this endpoint; or the disease is rare | No regulator-accepted endpoint |

### Two axes

The report shows the rating of each axis separately.

| Rating | Condition |
| --- | --- |
| Strong | Two or more greens, no red and no strong minus |
| Weak | A red or a strong minus, or no green |
| Mixed | Otherwise |

The science axis includes the safety cluster rules, mechanism failure, "no response in animals", "not reproduced", "neither genetics nor precedent". The other clusters belong to the commercial and execution axis. The axis rating does not affect the verdict; science pluses do.

---

## 6. Kill rules: immediately Do Not Invest

None except me-too fires if any of its facts is unknown.

| Rule | Condition | Basis |
| --- | --- | --- |
| Mechanism refuted (M) | 2+ other drugs with the same mechanism failed Phase 2/3 for efficacy, and no successes are known to exist | Mixed |
| Me-too (M) | 2+ approved with the same mechanism in this indication, and no valid differentiation | Expert |
| Drug-related deaths (A) | A grade 5 death, and the disease is known not to be life-threatening | Expert |
| CRL (A) | Reason: efficacy or safety | Mixed |
| Patent (A) | Expired or no protection | Expert |
| Modality (M) | Physically cannot reach the target | Expert |
| Retracted paper (M) | The foundational paper was retracted, and no independent group reproduced the result | Expert |
| Licence (A) | Non-exclusive or does not cover the lead indication | Expert |
| Data integrity (A) | FDA letter on unreliable clinical data | Expert |

**Valid differentiation for me-too:** efficacy, safety or a structurally lower cost of goods. "Cheaper" counts only in a channel where the payer captures the savings itself; for infusions and intrathecal administration the channel is derived from the route. Dosing convenience does not count. A refuted claim is void. Undeclared differentiation is assumed absent.

**Consequence for the brief's input.** The input has no differentiation claim. So any mechanism that already has two approved drugs in this disease gets Do Not Invest until differentiation is given. This matches the analyst's position ("why would we develop something"), but the report must show such a decision together with the differentiation question: the "what would change the verdict" analysis names it.

---

## 7. Strong minuses: 2 points

| Cluster | Rule | Condition | Basis |
| --- | --- | --- | --- |
| No cluster | Mechanism failure (M) | One failure with no successes; or any number of failures when nothing is known about successes | Evidence |
| No cluster | No response in an animal model (A) **was a kill rule** | Link 1 is broken | Expert |
| Safety | Deaths in a fatal disease (A) | A grade 5 death, the disease is life-threatening or its severity is unknown | Expert |
| Safety | Deaths in the class (M) | Trials of drugs of the same class had drug-related deaths | Expert |
| Safety | Withdrawal in the class (M) | A drug of the same class was withdrawn for safety | Mixed |
| Safety | Class CRL for safety (M) | Another drug with the same mechanism received a CRL for safety | Expert |
| Safety | Programs stopped for safety (M) | 2+ programs on this target discontinued for safety | Expert |
| Safety | Essential gene (M) | Inhibitor of such a gene in a chronic non-oncology disease | Expert |
| Safety | Many target flags (M) | 4+ flags in a chronic non-oncology disease | Mixed |
| Safety | Toxicity (A) | At efficacious exposure (no therapeutic window) | Expert |
| Regulatory events | CRL without a reason (A) | There was a letter, the reason was not disclosed | Mixed |
| Regulatory events | Advisory committee (A) | Negative vote on the asset | Evidence |
| Licensing | Key markets (A) | US or EU rights out-licensed | Expert |
| Licensing | High royalties (A) | Above 10% in total | Expert |
| Trials | Post hoc subgroup (A) | The thesis rests on a subgroup after a failure | Evidence |
| Trials | One country (A) | Registrational data from a single country outside the US | Mixed |
| Trials | Endpoint change (A) | Primary endpoint changed after registration | Mixed |
| Trials | Single-arm (A) | Registrational, outside oncology and rare diseases | Mixed |
| Trials | Accelerated approval (A) | Without a registered confirmatory trial | Evidence |
| Competition | Late entry (M) | More than 5 years after the first in class | Mixed |
| Price | Loss of exclusivity (M) | Standard of care loses protection before launch | Evidence |
| Finance | Asset returned (A) | A partner terminated the licence | Expert |
| Finance | Cash (A) | Does not last until the next readout | Expert |

A CRL of another drug with the same mechanism for efficacy counts as a mechanism failure.

---

## 8. Warnings: 1 point

| Cluster | Rule | Condition | Basis |
| --- | --- | --- | --- |
| No cluster | Neither genetics nor precedent (M) **widened** | The disease has genetic data, but it does not support this target, and the target has no clinical success in this or a related disease. If the disease has no genetic data at all (`no_data`), the rule is silent | Evidence: validated on real pairs |
| No cluster | Not reproduced (M) | No independent group reproduced it; or the paper was retracted and nothing is known about reproduction | Mixed |
| Competition | Me-too with differentiation (M) | 2+ approved with the same mechanism, differentiation is valid | Mixed |
| Competition | Competitors in Phase 3 (M) | 3+ with the same mechanism, fewer than two approved | Expert |
| Safety | Class signal (M) | A boxed warning or a known adverse effect of the class | Expert |
| Safety | Program stopped for safety (M) | One program on this target discontinued for safety | Expert |
| Safety | Target flags (M) | 2+ safety flags | Mixed |
| Safety | Grade 4 (A) **new** | Drug-related grade 4 adverse events; the disease is not life-threatening or its severity is unknown | Expert |
| Regulatory events | CRL for manufacturing (A) | Reason: manufacturing | Evidence |
| Regulatory events | Committee against a class drug (M) | An advisory committee voted against another drug with the same mechanism | Expert |
| Manufacturing | Complex modality (M) **changed** | Cell, gene therapy or radioligand, and the sponsor is not a big company (or its size is unknown) | Expert |
| Manufacturing | Manufacturer (A) | OAI status or a warning letter within 3 years | Mixed |
| Licensing | Non-key territories (A) | 2+ territories outside the US and EU out-licensed | Expert |
| Licensing | Medium royalties (A) | 5–10% in total | Expert |
| Trials | Under-enrollment (A) | Phase 2 under-enrolled | Evidence |
| Trials | Withdrawn accelerated approvals (M) | Accelerated approvals in this disease were withdrawn | Expert |
| Trials | Enrollment risk (M) | Trials in this disease were often stopped for enrollment | Evidence |
| Price | Unrealistic price (M) | The required annual price does not fit the population | Expert |
| Price | Medicare (M) | The drug falls under price negotiation | Evidence |

### Discontinued programs on the same target

| Reason for stopping | Where it goes |
| --- | --- |
| Efficacy | Rules "mechanism failure" and "mechanism refuted" |
| Safety | Safety cluster: one program gives a warning, two or more a strong minus |
| Enrollment, business decision, funding | Only the landscape in the report |
| Reason unknown | Landscape and a due-diligence question |

---

## 9. Clusters and absorption

| Cluster | Axis | What it groups |
| --- | --- | --- |
| Safety | Science | Asset, class, target, programs stopped for safety, grades 4 and 5 |
| Competition | Commercial and execution | Me-too with differentiation, competitors in Phase 3, late entry |
| Price | Commercial and execution | Loss of standard-of-care exclusivity, unrealistic price, Medicare |
| Trials | Commercial and execution | Design and conduct; disease risks for enrollment and accelerated approvals |
| Regulatory events | Commercial and execution | CRLs, advisory committees |
| Manufacturing | Commercial and execution | Complex modality, manufacturer status |
| Licensing | Commercial and execution | Key markets, royalties, non-key territories |
| Finance | Commercial and execution | Asset returned, cash runway |

**Absorption.** "Post hoc subgroup" adds no minuses if "Clinical effect" is red exactly because of the same own failure. "Single-arm" adds none if "Design" is red exactly because of the open-label design.

---

## 10. How unknown is treated

General rule: a condition on an unknown fact does not fire. The full list of exceptions:

| Where | What is unknown | How it is treated |
| --- | --- | --- |
| Kill rule me-too | Differentiation, its confirmation, channel | No differentiation; an unrefuted claim stands |
| Mechanism failure | Mechanism successes | Strong minus, not refutation |
| Deaths | Disease severity | Strong minus, not kill |
| Grade 4 **new** | Disease severity | The disease is not life-threatening: the warning fires |
| Complex manufacturing **new** | Sponsor size | Not a big company: the warning fires |
| Late entry | Number approved in the class | A first in class is assumed to exist |
| Competitors in Phase 3 | Number approved in the class | Fewer than two |
| Not reproduced | Number of reproductions for a retracted paper | Warning |
| Me-too with differentiation | Confirmation of differentiation | The claim stands until refuted |
| Green "Indication track record" | Whether the disease is on the "graveyard" list | Not on the list |
| Red "Translation chain" | Positive Phase 2, approval elsewhere | None |
| Green "Design" | Whether dose ranging was done | Does not block green |

The "neither genetics nor precedent" warning needs both facts known and is silent on unknown; it is also silent with `genetic_support: no_data`. An item becomes a strong green only on known facts: for clinical effect the stage must be known.

---

## 11. Derived facts and contradictions

| If known | Then derived |
| --- | --- |
| 0 approved drugs in the disease | 0 approved with this mechanism; 0 new mechanisms in 10 years |
| More than 10 years without a new mechanism | 0 new mechanisms in 10 years |
| An approved drug with this mechanism, or a precedent in this disease | At least 1 mechanism success; precedent "approved in this disease" |
| Oncology | Not chronic non-oncology; life-threatening |
| Chronic non-oncology | Not oncology |
| Single-arm | Not randomized, and vice versa |
| An approval precedent on the endpoint | An accepted endpoint exists |
| Route: infusion or intrathecal | A channel where the payer captures the savings itself |
| Links 2, 3 and 4 shown | Three pillars shown |

**Stop scoring as contradictory:** oncology and chronic non-oncology at once; single-arm and randomized at once; more approved with this mechanism than approved overall; more than 10 years without a new mechanism and new mechanisms within 10 years at once; a mechanism success in this disease and zero successes; an endpoint precedent and no accepted endpoint; a stage before Phase 2 and a positive own Phase 2.

---

## 12. Due-diligence questions

The report gets 5 to 10 questions in this order:

1. **"What evidence would kill the program?"** The list of facts each of which alone flips the verdict to Do Not Invest.
2. Questions whose answer alone can change the verdict.
3. Unknown links of the translation chain.
4. The rest of the unknown asset-level facts, up to ten.

---

## 13. Conditional share

| Source of the estimate | Version 0.4 | Version 1.1 | 1.1 with `science_short: "Do Not Invest"` |
| --- | --- | --- | --- |
| Real pairs (four items known) | 0% | 6.2–8.4% | 0% |
| State-space sweep, cases without a kill rule | 6.4–13.4% | 7.2–17.0% | 5.9–10.9% |

- **On real pairs Conditional is within 5–10%.** These are pairs with one science plus and commercial pluses; 13–14% of them reached launch, i.e. the same as on average.
- **The sweep gives up to 17%** assuming 30% of items are green and few are red. The sweep depends on assumptions, not on data.
- **Switch.** If Conditional must be kept stricter, the line `science_short: "Do Not Invest"` in `benchmarks.yaml` returns such cases to Do Not Invest. The launch share among Invest does not change.

---

## 14. Reference probability

The function `reference_probability` returns two independent references. They are not part of the verdict.

### By mechanism evidence

Share of historical pairs with the same evidence that reached launch. Range: from the symmetric way to the mixed way.

| Cell | Pairs | From Phase I | From Phase II | From Phase III |
| --- | --- | --- | --- | --- |
| Mendelian genetics, with or without other evidence | 192 | 41–45% | 43–47% | 74–77% |
| GWAS or somatic and precedent | 436 | 26–27% | 28–30% | 61–63% |
| GWAS or somatic and a strong indication track record | 109 | 20–26% | 25–31% | 63–72% |
| Only GWAS with a confident gene | 238 | 14–17% | 19–22% | 56–58% |
| Only a somatic driver | 65 | 5–7% | 6–9% | too few pairs |
| No genetics: precedent and a strong indication track record | 960 | 22–28% | 24–32% | 62–71% |
| No genetics: precedent only | 3,184 | 14–17% | 16–19% | 44–50% |
| No genetics or precedent: only a strong indication track record | 1,899 | 6–11% | 8–14% | 45–60% |
| None of the above | 5,947 | 6–8% | 8–11% | 35–42% |
| All pairs | 13,030 | 11.7% | 14.5% | 49.5% |

- **Choosing the cell.** The first cell matching the known facts is taken. An unknown fact does not narrow the cell: wider merged cells exist for such cases (full list in `benchmarks.yaml`, section `reference`).
- **Out-of-sample calibration.** Shares were computed on one half of the data and applied to the other. Mixed way: forecast 5.7% vs actual 6.0%; 8.9% vs 9.4%; 18.9% vs 17.2%; 27.0% vs 27.5%; 33.3% vs 30.7%. The symmetric way is noisier: in the group with a 19.8% forecast the actual was 14.3%.
- **Caveats** the function returns itself: the asset is preclinical; genetics contradicts causality; the disease has no genetic data (the table was computed on diseases that have it); the disease is on the "graveyard" list; too few pairs at a late stage.

### By stage

Baseline approval share from each stage, regardless of mechanism evidence (BIO 2021).

| Segment | From Phase I | From Phase II | From Phase III | From filing |
| --- | --- | --- | --- | --- |
| All diseases | 7.9% | 15.1% | 52.4% | 90.6% |
| Oncology | 5.3% | 10.8% | 43.9% | 92.0% |
| Non-oncology diseases | 9.3% | 17.2% | 55.3% | 90.2% |
| Rare non-oncology diseases | 17.0% | 25.2% | 56.6% | 93.6% |

The two references are not multiplied: the first already accounts for stage through the "from Phase II" and "from Phase III" columns, the second counts drug approvals, not target + disease pairs.

---

## 15. What scoring does not do

- **It does not put the probability of success into the verdict.** It is shown as a reference range.
- **It does not score commercial attractiveness as a plus,** except unmet need and the regulatory path. Commercial factors give minuses through rules and a separate axis in the report.
- **It does not assess the development plan, capital and timelines.** These are report sections.
- **It does not guarantee accuracy.** On real data half the scorecard and one rule were validated; balanced accuracy there is 57–61%.
- **It does not replace human review.** The analyst: no AI platform works without human validation yet.

---

## 16. Assumptions not calibrated on data

| Assumption | Value | Support |
| --- | --- | --- |
| Weights | green 1; strong green 2; red 2; strong minus 2; warning 1 | Expert; strong green for genetics on real pairs |
| Verdict thresholds | minuses ≥ 4; difference ≥ 2; difference ≤ 0; 2 pluses for Conditional | Expert |
| Two science pluses for Invest | 2 | Real pairs |
| Strong green for the asset's own Phase 2 when already in Phase 3 | 2 pluses | Literature; not checked on data |
| Indication track record | 5 Phase 3 outcomes; 70% | Real pairs, split in half |
| Related disease | Same therapeutic area | Real pairs |
| Unmet need: the item itself and its thresholds | +1; 3 drugs; 5 and 15 years | Expert; not supported by data |
| Mechanism | 2 failures with a known absence of successes refute it | Expert |
| Me-too | 2 approved with the same mechanism | Expert |
| Competitors | 3 in Phase 3; late entry over 5 years | Expert |
| Target safety | 2 flags a warning; 4 a strong minus | Expert |
| Programs stopped for safety | 1 a warning; 2 a strong minus | Expert |
| Royalties | 5–10% a warning; above 10% a strong minus | Expert |
| Axis rating | strong: 2+ greens without reds or strong minuses | Expert |
| Share of strong greens among greens in the sweep | genetics 20%; clinical effect 50% | Genetics from real pairs; clinical effect an assumption |

---

## 17. The analyst's words and where they are in scoring

Source: Q&A on 6 October 2026.

| What the analyst said | Where it is in scoring |
| --- | --- |
| Understanding the biology of the disease and the drug; the Alzheimer's example | Human genetics; clinical precedent; the "graveyard" list |
| The right unmet need; why develop where good treatment already exists | Unmet need: green and red |
| Regulatory path: FDA designations, rare and paediatric diseases | Regulatory path; since version 1.0 a rare disease gives green |
| "Does the drug do what it is supposed to do" | Translation chain; clinical effect |
| "Is the trial designed to measure what the drug is intended to do" | Trial design |
| Scorecard: is the biology novel or de-risked; is the indication "plagued with failures"; need | The eight scorecard items |
| Cell, gene therapy, radioligands are complex; harder for a small company | Warning "complex modality"; since version 1.0 also without a known sponsor size |
| Gene therapy has safety issues | Class safety signal |
| A saturated market: "that's a no go" | Red "Unmet need"; me-too |
| Me-too in a well-served disease; competitors in Phase 3 | Kill rule me-too; warning on competitors in Phase 3 |
| A case: the only advantage is once a day instead of twice | Dosing convenience is not differentiation |
| "Same effect with cleaner safety, I will look at it" | Safety is valid differentiation |
| Grades 4 and 5; "if I see grade 5 effects, I walk away" | Grade 5: kill in a non-fatal disease, strong minus in a fatal one. Grade 4: a warning since version 1.0 |
| CRL: "I usually walk away" | Kill for efficacy or safety; strong minus for an undisclosed reason; warning for manufacturing |
| Patent expired: "you're buying air" | Kill |
| US and EU out-licensed: "very skeptical" | Strong minus |
| "Mice don't lie, they exaggerate"; no response in a mouse: "a little bit tricky", "a bit of a red flag" | Strong minus. Before version 1.0 it was a kill rule, which is harsher than her words |
| The biggest fear: inaccuracy; "I would rather not have the information" | Unknown does not kill; the verdict grounds separate "don't know" from "no"; data coverage |
| Three documents: clinical data, patents, preclinical data | Due-diligence questions |
| Doubts about the data: look at efficacy, pharmacodynamics, PK/PD | Translation chain links as questions |

**Where scoring is softer than her words.** Grade 5 deaths in a fatal disease do not kill: in oncology they occur in almost every large trial. This is a deliberate decision carried over from earlier versions.

---

## 18. The external proposal "SCORING v0.5": what was taken and what was not

"SCORING v0.5" is not a version of this scoring but a separate proposal document: replace the rules with a trained model with 30–35 features. The versions of this scoring are 0.3, 0.4, 1.0, 1.1.

| Proposal | Decision | Reason |
| --- | --- | --- |
| Kill rules take priority over any score | Already there | — |
| Strength of genetics instead of "yes / no" | Taken | Mendelian genetics as a strong green |
| Explicit handling of unknown; do not treat unknown as zero | Already there; grounds and coverage added | — |
| Grouping by target; do not fit thresholds on the test set | Already there | — |
| Extra metrics: PR-AUC, precision and lift in the top 10%, Brier, calibration | Taken | The validation script |
| Ablation | Taken | Section 2 |
| Probability next to the verdict | Taken as a reference | Section 14 |
| Scorecard as an explanation layer over a model | Not taken | An explanation computed separately from the decision can diverge from it; the brief requires the "recommendation → claims → evidence" path |
| A trained model as the verdict engine | Not taken | For 4 of 8 items and 50 of 51 rules there is not a single labelled example |
| 30–35 machine features | Not taken | The data have only mechanism features; nothing to train the rest on |
| Invest thresholds of 0.60–0.75 by probability | Not taken | The base is 11.7%; the best cell gives 41–45%. Nobody would reach 0.60 |
| The 0.45 / 0.30 / 0.15 / 0.10 formula | Not taken | Expert weights without support |
| An "as of" date for every case | Not here | This is the job of the fact-collection layer; the data have no development start dates |
| Goal: 70% balanced accuracy | Not a goal | The brief does not require accuracy; for an investor a false Invest costs more than a missed one |

**The ceiling on the same facts.** Logistic regression and gradient boosting with cross-validation by target give AUC 0.68–0.74; the version 1.0 score gives 0.62–0.69. The models win 0.04–0.08 thanks to continuous disease and oncology features. That is the entire possible gain from training on mechanism data.

---

## 19. Numbers from the literature: what was checked

Checked against the source in this version:

| Source | Number | Where it is used |
| --- | --- | --- |
| Minikel 2024 | Genetics 2.6×; Mendelian 3.7×; by phase 1.08 / 1.57 / 1.28 | Reproduced on the data |
| BIO 2021 | Phase transitions 52.0 / 28.9 / 57.8 / 90.6%; rare diseases 17.0%; oncology 5.3% | Tables in the dataset |
| Wong 2019 | Biomarker: 10.3% vs 5.5% | Table in the dataset |
| Begley & Ellis 2012 | 6 of 53 preclinical papers confirmed | Retracted paper; not reproduced |
| Hwang 2016 | 640 late-phase drugs: 54% failures, 57% of them for efficacy | Mechanism refuted |
| Sacks 2014 | 302 applications; 47% of rejected later approved; dose uncertainty 15.9%; efficacy deficiency 76% vs 39% | CRL; design |
| Daval 2023 | After a negative vote the FDA did not approve 40 of 60 | Advisory committee |
| Wallach 2017 | Of 5 tested subgroup claims none was confirmed | Post hoc subgroup |
| COMPare 2019 | 58 of 67 trials needed a correction | Endpoint change |
| Agrawal 2023 | 176 indications on single-arm trials; 116 accelerated; 10 withdrawn | Single-arm |
| Liu 2024 | Oncology 2013–2017: 22% of accelerated approvals withdrawn | Accelerated approval |
| Downing 2017 | Post-approval safety events in 32% of 222 drugs | Withdrawal in the class |
| Razuvayevskaya 2024 | 36.7% of stops for enrollment; genetic support rarer in trials stopped for efficacy, OR 0.61 | Enrollment risk; mechanism failure |
| KFF, CMS | Medicare spending reductions of 22% and 44% | Medicare |
| Morgan 2018 | Success to the end of Phase 3 rose from 4% to 19% | Translation chain (context) |

**Not checked:** Morgan 2012 (Pfizer's three pillars); ODAC 2022 (14:1); Analysis Group (18–23%); BioSpace (39%); the overall share of withdrawn accelerated approvals of 13%; McKinsey, L.E.K., Reuters Events.

**I found no quantitative estimate of target precedent in the literature.** Siah 2021 and Lo 2019 give only a feature rank. The 1.7–3.5× estimate is our own, from the Minikel data.

---

## 20. Pipeline interface

The scorer takes a `{fact: value}` dictionary and knows nothing about documents. Everything between the "organize" stage claims and this dictionary is described here and implemented in `scoring/engine.py`.

### A fact catalog instead of free tags

- **The tag dictionary is the catalog of 86 facts.** `tags.yaml` is generated from `benchmarks.yaml` by `python -m scoring catalog`; it is not edited separately.
- **A claim carries a `fact` and `value` pair,** not free `tags` and `strength`. The value is typed: yes / no, a number or one of a list.
- **Code, not the LLM, sets evidence strength.** A strong or ordinary green follows from the fact value (`mendelian` vs `gwas`), and the value comes from the source type.

### "Claims → facts" rules

The function `facts_from_claims(cfg, claims)`:

| # | Rule | Why |
| --- | --- | --- |
| 1 | The fact and value must come from the catalog | A typo in a name must not be silently lost |
| 2 | An LLM inference (`evidence_type: inference`) does not become a fact | Only source statements go into the scorer |
| 3 | An LLM claim without a found quote is rejected | Architecture principle |
| 4 | The LLM cannot assert absence: a zero counter, "none" | Absence cannot be established from text; only a complete structured source or a human proves it. Whether two mechanism failures give a strong minus or a kill rule depends on this |
| 5 | A critical value from the LLM waits for a second independent source or human confirmation | One made-up claim about a grade 5 death must not flip the verdict |
| 6 | Disagreement is resolved by origin: human, then structured source, then LLM. A disagreement at the top level makes the fact unknown | "Don't know" beats an arbitrary choice |

- **A critical value** alone, without other facts, triggers a kill rule, a strong minus or a red item. There are 33 such facts; the list is in `tags.yaml` (field `critical_values`) and in `docs/fact_sources.md`.
- **The function returns** the accepted facts, plus rejected claims, claims waiting for confirmation, and conflicts. The last three lists must go into the report as critical unknowns.

### Fact origin

| In SCORING | In claims |
| --- | --- |
| Found in a source | `origin: structured` (an API field) or `origin: llm` (text with a quote); `evidence_type: source` |
| Provided by the user | `origin: user` |
| Derived from other facts | Not stored in claims: the engine derives it, the result is in `facts.derived` |
| An LLM inference | `evidence_type: inference`; does not go into the scorer |

### One result for `scores` and `verdicts`

The function `evaluate(cfg, facts)` returns JSON with everything the report stage may cite.

| Key | What is in it |
| --- | --- |
| `config` | Config version and sha256 |
| `verdict` | Decision, grounds, explanation, conditions for Conditional |
| `score` | Pluses, minuses, science pluses, axes, data coverage |
| `scorecard`, `rules` | The colour of every item and every fired rule with the facts that decided them |
| `facts` | Given and derived facts |
| `reference` | Reference probability with caveats |
| `what_would_change` | Single-fact changes that flip the verdict |
| `dd_questions` | 5–10 questions in a defined order |

- **The scorer computes the questions, conditions and "what would change the verdict".** The LLM only phrases them; it cannot add its own.
- **Numbers in the report come only from here.** The scorer does not compute capital to the next milestone, the commercial opportunity or the development plan: these are qualitative sections with links to claims, or a separate module.

### What of this works in the first pipeline version

The matrix `docs/fact_sources.md` (generated by `python -m scoring sources`). It is a plan based on source documentation; it has not been checked with live requests.

| | Alone, from structured sources | With an input field | With text read by the LLM | Only with human facts |
| --- | --- | --- | --- | --- |
| Kill rules (9) | 2 | 0 | 2 | 5 |
| Strong minuses (23) | 1 | 1 | 2 | 19 |
| Warnings (19) | 4 | 1 | 3 | 11 |

- **40 of 86 facts come from MVP sources.** Only a human can add the remaining 46.
- **Five mechanism-level scorecard items work on their own.** "Translation chain" needs input fields; "Clinical effect" and "Design" need human facts.
- **openFDA would give the biggest gain:** approval dates open the red of "Unmet need" and the late-entry rule.


# 2.8 backend (10 October 2026): failures registered under a broader disease

`diagnose_pair` on CETP showed the failure was found (Lincoff 2017, ACCELERATE: "not shown") and then dropped: every
evacetrapib trial and indication is mapped to "cardiovascular disease", none to coronary artery disease itself.
- `OpenTargets.lineage()` (query `DiseaseLineage`): parents and grandparents of the run's disease, without roots and
  therapeutic areas; stored as `disease.broader`. A failed query gives an empty list (nothing changes).
- Used to find **failures only**: registry rows (`failure_terms`: names of the broader diseases), Open Targets trial
  reports and indications (`stopped_trials(..., broader_ids)`), and the Phase 2/3 check that lets an abstract's
  "not shown" count. Never for successes, approvals or the track record.
- ClinicalTrials.gov: names the search cannot take are not searched; a single refused name is skipped (CML + ABL1).
- `python -m backend.tests.diagnose_pair "<disease>" "<mechanism>" <DRUG>`: everything a run saw about one drug.

# 2.7 (10 October 2026): CETP and the opposite direction

- **Opposite direction approved** (`opposite_direction_approved_count`, rule `opposite_direction_approved`): drugs
  approved for this disease act on the same target the other way (GLP-1 agonists vs a GLP-1 antagonist for obesity;
  PCSK9 inhibitors vs a PCSK9 agonist). A kill with its own grounds `opposite_direction`: as a strong minus it lost to
  direction-blind genetic support (+2) and the PCSK9 agonist came out Conditional.
- **A met biomarker endpoint does not clear a drug** (`clinical_primary_met`): the 2.5 "positive Phase 3" override now
  needs a clinical primary outcome. Evacetrapib lowered LDL-C in Phase 3 and failed on cardiovascular events.
- **Reports with no disease ID**: an Open Targets trial report without a disease ID counts for this disease when the
  drug has an indication mapped to it (evacetrapib's futility stops).
- **Every failed drug keeps a source**: the 40-source cap on a claim no longer drops whole drugs (the claims gate
  recounts drugs from the sources).
- Abstract rules also read outcome-trial wording ("did not reduce the rate of major adverse cardiovascular events").
- `mechanism_pairs.txt`: CETP and the GLP-1 antagonist expect `verdict=Do Not Invest`. Tests: backend 283.

# 2.6 backend (10 October 2026): evidence without a paid LLM

The team wallet ran out. Two LLM jobs are now done by code on data the run already has (`backend/app/rules.py`):

- **Why a trial stopped**: Open Targets' own stop-reason categories (`trialStopReasonCategories`, the classifier of
  Razuvayevskaya 2024), checked against the words of the reason (a "Negative" stop that names liver toxicity is a
  safety stop), plus word rules for rows without a category. Replaces `classify_stops` and `check_stop_labels`
  (21–36 paid calls a run). `UNOBIO_STOP_LABELS=llm` brings the LLM labels back.
- **Trial outcomes in papers**: the PubMed abstracts already downloaded (by drug, by NCT number) are split into
  sentences; "did not meet its primary endpoint" / "stopped for futility" = clinical benefit not shown, "met its
  primary endpoint" = shown (a Phase 3 one also clears the drug of failures). Only human trials naming the drug and the
  disease; mixed abstracts are skipped. Quotes are exact substrings.
- Hits from both are code-made (`CODE_SOURCES`): their claims are structured and do not wait for a person.
- `UNOBIO_NO_LLM=1` (or `python collect_results.py --mechanisms --no-llm`) makes a run with no paid request at all.
  With a key and without the switch, the LLM still reads documents for translation links on top of the rules.
- Recorded Alzheimer + BACE1 with no LLM: 2 efficacy failures (lanabecestat, elenbecestat), atabecestat under safety,
  Do Not Invest (mechanism refuted), nothing pending.
- Tests: `backend/tests/test_v26.py`; the older recorded tests run with `UNOBIO_RULES=0` (the LLM path they check).

# 2.5 (10 October 2026, after the second v6 run)

The v6 run (`unobio_results_20261010-160032`) gave 6 Conditional of 15; 5 of them only because the mechanism was
already approved 2+ times (PCSK9, IL-17A, ABL1, KRAS G12C, GLP-1). Product decision: that is a clear answer, not a
condition.

| Change | 2.4 | 2.5 |
|---|---|---|
| `me_too` (2+ approved here with the same mechanism, and the same modality when known; no proven advantage) | note + cap at Conditional | **kill, Do Not Invest with grounds `crowded`** ("a market call, not a science call"); `differentiation_claim` + evidence not refuted lifts it, Invest possible |
| `me_too_refuted` | kill, grounds `kill` | kill, grounds `crowded` |
| Approved count from an incomplete drug list | not given | given as a lower bound when it is already 2+ ("At least N", psoriasis + IL-17A) |
| A Phase 3 here with a met primary outcome (superiority p < 0.05) | — | the drug is not an efficacy failure (anacetrapib / REVEAL; tanezumab) |
| Registry p-values of a trial stopped early for a reason other than efficacy | counted | ignored (tanezumab, atabecestat safety stops) |
| One-source efficacy-failure claim | waited for a person | confirmed when the quote states the failure in words the code recognises (futility, did not meet, lack of efficacy) |

Engine: rules may carry `grounds` (kill rules only, a Do Not Invest grounds key); when every kill that fired names
the same grounds, the verdict reports it. Expected verdicts in `mechanism_pairs.txt`: the six crowded pairs are
`verdict=Do Not Invest`. Tests: backend 262, unobio_scoring 56, scoring_engine 294.

Not fixed (needs the run's data): evacetrapib's failure is not found for coronary artery disease (its outcome trial
is registered under broader cardiovascular terms); GLP-1 antagonist for obesity still has no rule for "the opposite
direction is approved here".

# unobio_scoring 2.4 and backend changes of 10 October 2026

2.4 answers the mechanism sample of 10 October (15 pairs with an explicit mechanism, `results 20261010-090111`):
one false Invest (Huntington + HTT ASO), four validated mechanisms rated Do Not Invest for the wrong reason (SGLT2,
GLP-1 agonist, ABL1, KRAS G12C), three Insufficient evidence verdicts that were source failures, three that waited
only for a reviewer. Every result carries `config.version = "2.4"` and the config sha256.

Nothing here was fitted to the 15 pairs: each change is a rule about what counts as evidence, checked against the
validation in `scoring_engine/SCORING.md`. Where a first fix contradicted the validation (Invest needs two distinct
mechanism items: Mendelian genetics alone gives 37–40% launch on 13,030 pairs) it was replaced by a narrower rule.

## 1. Scorer (`unobio_scoring/fixes.py`, `engine.py`)

| Change | Before | 2.4 | Why |
|---|---|---|---|
| Rule tier `note` | — | fired and shown in the memo, 0 points | absence of evidence is not negative evidence |
| `no_genetics_no_precedent` | warning (−1) | note | alone it gave Do Not Invest (Osteoarthritis + HAS2) |
| `indication_enrollment_risk` | warning | note | fired for almost every large disease; a property of the disease |
| `me_too` | strong (−2) + cap | note + cap at Conditional (`cap_me_too`) | turned validated classes into Do Not Invest; `me_too_refuted` stays a kill |
| `me_too_differentiated` | warning | note | same reason |
| `class_safety_signal` | warning always | warning only if the class is not approved here; note `class_safety_signal_approved` otherwise | a boxed warning on an approved class is monitoring, not a minus |
| `cap_unknown_class_outcome` | — | Invest → Conditional while a same-mechanism drug finished Phase 2/3 here with an unknown outcome and the mechanism is not approved here | tominersen: Phase 3 "completed", no p-value, failure invisible |
| `min_science_items_invest` | — | engine option, 0 in the built-in config | kept for experiments; see the validation note above |
| Insufficient evidence detail | — | `verdict.insufficient = {kinds, texts, would_decide}` | says why (no mechanism evidence / no asset data / few pluses) and which single facts decide it |

New fact: `moa_ph23_unknown_outcome_count` (int, mechanism, Open Targets).

## 2. Evidence (`backend/app/facts.py`, `trials.py`, `pipeline.py`)

- **A failure is a failed program, not a failed trial.** `trial_claims(..., approved_here, approved_anywhere)`: a drug
  approved for this disease is never an efficacy failure; a drug approved anywhere is never a program discontinued for
  safety. On 10.10 dapagliflozin, empagliflozin, semaglutide, imatinib, bosutinib, sotorasib, inclisiran and tofersen
  were counted as failures. `approved_same_mechanism()` gives the two sets.
- **Salt and solvate forms**: propanediol, anhydrous, (mono/di)hydrate, pidolate, L-proline, tosylate join the salt
  list (dapagliflozin propanediol = dapagliflozin).
- **Same-mechanism class** (`mark_class_members`, run once per analysis, read by every count through
  `_same_mechanism`): a drug acting on 3+ targets that was never developed for this disease is not the same mechanism
  (regorafenib, umbralisib for ABL1); with a variant in the input (`KRAS G12C`) a family-wide inhibitor whose
  mechanism text does not name the variant is not either (salirasib). Excluded drugs are listed in the memo.
- **Direction**: ChEMBL `EXOGENOUS GENE` / `EXOGENOUS PROTEIN` = activate (onasemnogene abeparvovec for SMN1),
  `SEQUESTERING AGENT` = inhibit. The parsed variant now reaches the normalized target (`target.variant`).
- **Unknown class outcome** (`unknown_outcome_claims`): same-mechanism drugs, not approved here, no failure found,
  whose Phase 2/3 here finished and that have no active trial here at the same or a later stage.
- **Indication track record** (`indication_track_record_claims`): `indication_ph3_outcomes_other_moa` and
  `indication_ph3_success_share_other_moa` from the disease's drug list (already collected). Recorded runs: familial
  hypercholesterolemia 7 of 10 (green), Alzheimer 3 of 32, Huntington 1 of 5.

## 3. Source failures (`sources/http.py`, `opentargets.py`, `sources/ctgov.py`, `collect.py`, `translation.py`, `api.py`, `db.py`, `report.py`)

- Retries: 5 instead of 3, backoff 1, 2, 4, 8, 16 s (cap 20) with jitter (`backoff()`), for every source.
- ClinicalTrials.gov "Too complicated query": the drug-name group is split in halves until accepted (CML + ABL1).
- A failed Open Targets query or translation source is tried once more after the others.
- Runs record the sources that still failed: column `runs.incomplete` (added to existing databases on start),
  `collected.incomplete`, score payload `incomplete`. API: `GET /runs/{id}` has `complete` and the verdict has
  `complete`, `incomplete_sources`, `insufficient.kinds` starting with `incomplete_run`. The memo starts with
  "INCOMPLETE RUN: …". Offline runs without cached answers are incomplete too (that is the truth).

## 4. LLM (`backend/app/llm.py`, `trials.py`)

- `temperature` and `seed` can be sent (env `UNOBIO_LLM_TEMPERATURE`, `UNOBIO_LLM_SEED`), but only when set: 2.4.1
  turned the default off after the team gateway answered HTTP 502 "upstream_error" to them (a 502 cannot be told apart
  from an outage, so the parameter cannot be dropped automatically, and each failed request is charged). A server that
  rejects them with a 400 still gets them dropped. Reproducibility comes from the answer cache.
- **Auto-confirmation** (`auto_confirm`, env `UNOBIO_AUTO_CONFIRM`, default 1): an LLM claim with verified quotes from
  at least 2 independent documents (different sponsors, papers or labels) is confirmed without a reviewer; the
  statement says so. This is the "second independent source" of the claims gate. It reverses part of review F34 by
  choice: set `UNOBIO_AUTO_CONFIRM=0` to keep every verdict-changing LLM claim waiting for a person. Tests run with 0
  except where they say otherwise.

## 5. Mechanism sample (`backend/tests/mechanism_pairs.txt`, `mechanism_sample.py`)

- New expectation `verdict=A/B` / `verdict!=A/B`: every pair now checks its verdict (a validated mechanism is never Do
  Not Invest for that reason alone; a failed one is never Invest). A wrong verdict is a fail, not hidden among passes.
- Incomplete runs: verdict checks become "open (incomplete run: rerun)", the report has a "Complete" column and a list
  of runs to rerun.

## Expected effect on the 10.10 sample (not re-run here: no network to the sources from this environment)

| Pair | 2.3 | Expected with 2.4 | Change that does it |
|---|---|---|---|
| Huntington + HTT ASO | Invest | Conditional (capped) | `cap_unknown_class_outcome` (checked on the recorded run) |
| T2D + SGLT2, Obesity + GLP-1 agonist, CML + ABL1, NSCLC + KRAS G12C | Do Not Invest | not Do Not Invest; at most Conditional while undifferentiated (me-too cap) | approved drugs not failures; me-too a cap; class filter |
| CAD + CETP, Sepsis + TLR4, OA + NGF | Insufficient → DNI if confirmed | Do Not Invest when ≥2 independent sources | auto-confirmation |
| Psoriasis + IL-17A, Sepsis + TLR4 (sources failed) | Insufficient | a verdict, or "incomplete run" | retries, second pass, marking |
| Alzheimer + BACE1 | Do Not Invest | Do Not Invest | unchanged (kill on confirmed failures) |

Run `python collect_results.py --mechanisms` to measure it.

## Not done here (needs data this environment cannot reach)

- `soc_last_new_moa_years`, `indication_new_moa_approvals_10y` (openFDA drugsfda dates), `fda_designations_count`
  (FDA orphan designations), `accepted_endpoint_exists` (FDA surrogate endpoint table), `indication_graveyard`
  (curated list).
- Point-in-time snapshots (`as_of_date`) and a 60+ pair split backtest: the measurements in sections 6–7 of
  `unobio_summary.md`.

## Tests

`python -m pytest -q` (backend 258), `python -m pytest -q unobio_scoring/tests` (56), `python -m pytest -q
scoring_engine` (294). New: `backend/tests/test_v24.py`; updated expectations are commented with "2.4".

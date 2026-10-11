# Checking the unobio workflow end to end

Each stage, the command that checks it, and what a pass looks like. Run from the repo root.
Stages 0–2 need nothing. Stages 3–7 need network; stages that use the LLM also need the key in `backend/.env`.

## 0. Offline logic (every stage, fake sources and fake LLM)

```
python3 -m pytest -q                         # backend: 156 tests
python3 -m pytest -q unobio_scoring/tests    # scorer 2.2 + economics: 48
python3 -m pytest -q scoring_engine          # scorer 1.3 (comparison): 294
```
Pass: all green. `test_step10::test_thesis_without_market` now passes whether or not the Orphanet file is present.

## 1. Scorer constants against the dataset (clinical_success_dataset)

| Constant (`unobio_scoring/constants.py`) | Dataset file | Result |
| --- | --- | --- |
| `BIO_SUCCESS["all"]` 0.520 / 0.289 / 0.578 / 0.906 | `extracted/source_tables/bio2021_benchmarks.csv`, Figure 1 | match |
| `BIO_SUCCESS["oncology"]` 0.488 / 0.246 / 0.477 / 0.920 | same, Figure 2 Oncology | match |
| `GENETIC_RS`, `RS_PHASE_WEIGHTS` | `raw/csv/minikel2024_genetic_support/` (`scoring_engine/VALIDATION.md` reproduces the paper) | match |

The constants are tagged `[recalled]` in code; they can now be retagged `[sourced]` with the file and figure.

## 2. Drill-down without network (cached Huntington + HTT run)

```
UNOBIO_OFFLINE=1 python3 main.py
POST /runs {"disease": "Huntington disease", "target": "HTT antisense oligonucleotide", "phase": "ph3"}
GET  /runs/{id}                 -> verdict
GET  /runs/{id}/result          -> scorecard items and rules, each with claim_ids
GET  /claims/{claim_id}         -> statement, rule, sources[].url (Open Targets evidence pages)
GET  /runs/{id}/log             -> every external call, LLM tokens, cost
```
Pass: every scorecard item with a colour has `claim_ids`, and every claim has at least one source URL.
Recommendation → Claims → Evidence → Sources is this chain; the frontend only has to follow it.

## 3. Normalisation (Open Targets)

```
python3 -m backend.tests.step2_normalize "Alzheimer disease" "BACE1 inhibitor"
python3 -m backend.tests.step2_normalize "AD" "BACE1 inhibitor"          # must be ambiguous, with candidates
python3 -m backend.tests.step2_normalize "familial hypercholesterolemia" "anti-PCSK9 antibody"
```
Pass: exact names resolve to one MONDO / ENSG id; abbreviations return `ambiguous` with candidates, never a guess;
`anti-PCSK9 antibody` gives action `inhibit`, drug type `antibody`.

## 4. Gathering + claims by code

```
python3 -m backend.tests.step3_collect "Alzheimer disease" "BACE1 inhibitor"
python3 -m backend.tests.step4_score   "Alzheimer disease" "BACE1 inhibitor"
```
Pass: `genetic_support`, `moa_clinical_precedent`, `approved_same_moa_count` match what you see on the Open Targets
page for the pair. The backtest (stage 8) checks `genetic_support` on 60 pairs at once.

## 5. LLM

```
python3 -m backend.tests.check_llm             # key, URL, model, JSON mode
python3 -m backend.tests.eval_llm              # real model on hand-labelled cases; exit 1 on any failure
python3 -m backend.tests.eval_llm --record && python3 -m pytest -q backend/tests/test_llm_replay.py
```
Pass: eval_llm 0 failures; every LLM claim has a quote with `verified: true` and `support: true`.

## 6. Full run, memo, human evidence

```
python3 -m backend.tests.step8_report "Huntington disease" "HTT antisense oligonucleotide"
python3 -m backend.tests.run_batch                         # the 9 demo pairs, summary.md + one memo each
```
Then in the API: `GET /runs/{id}/report.md`, `/translation`, `/trials`, `/economics`,
`POST /runs/{id}/evidence` (add a fact) and `GET /runs/{id}/history` (before → after).
Pass: memo has 11 sections; `llm.issues` is empty or explained; every `source` paragraph cites claim ids.

## 7. Cost per underwriting run

Set your gateway prices in `backend/.env`:
```
UNOBIO_PRICE_IN_PER_M=...     # USD per 1M input tokens
UNOBIO_PRICE_OUT_PER_M=...    # USD per 1M output tokens
```
`GET /runs/{id}/log` → `cost.first_run_usd` (a new pair, nothing cached) and `cost.this_run_usd` (what this run
actually paid). Includes the memo's LLM calls (`llm_memo`). All data sources are free. For the README, take the mean
of `first_run_usd` over the run_batch pairs.

## 8. Backtest on known outcomes (Minikel 2024 pairs)

```
python3 -m backend.tests.backtest_build <path>/minikel2024_genetic_support --n 20
python3 -m backend.tests.run_batch backend/tests/backtest_pairs.txt --no-llm     # cheap first pass
python3 -m backend.tests.run_batch backend/tests/backtest_pairs.txt              # with the LLM
python3 -m backend.tests.backtest_score                                          # -> backend/data/backtest_report.md
```
Groups: `failed_ph3`, `failed_ph2` (target never launched for any disease, so today's data cannot leak the answer)
and `launched` (the approval is visible, so this only checks we do not kill a working mechanism).
Pass, roughly: few `Invest` among failed pairs, no `Do Not Invest` among launched pairs, genetic support agrees
with Minikel on most pairs. Every miss is listed with its run id: open `/runs/{id}/result` to see which claim drove it.

Known miss before running anything: Huntington + HTT antisense → **Invest**, although tominersen's Phase 3
(GENERATION HD1) was stopped. The failure is in the trial registry, not in Open Targets stop reasons; without
`AACT_DSN` nothing read the registry. `Sources.trials()` now falls back to ClinicalTrials.gov API v2 (`ctgov.py`)
when `AACT_DSN` is not set — rerun this pair live and check `moa_failures_efficacy_ph23` appears.

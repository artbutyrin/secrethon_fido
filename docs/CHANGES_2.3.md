# unobio_scoring 2.3 and backend changes of 10 October 2026

2.3 = 2.2 + the verdict **Insufficient evidence** + the genetic support value **mendelian_subtype**. Every result
carries `config.version = "2.3"` and the config sha256, so results of 2.2 and 2.3 stay distinguishable. Thresholds,
rules and weights of 2.2 are unchanged.

## 1. Verdict "Insufficient evidence" (`unobio_scoring/engine.py`)

| | 2.2 | 2.3 |
|---|---|---|
| Not enough confirmation, no negative evidence (grounds `insufficient_evidence`) | Do Not Invest | **Insufficient evidence** |
| Kill rule (`kill`), accumulated minuses (`negatives`), minuses outweigh pluses (`outweighed`) | Do Not Invest | Do Not Invest |
| Positive, balanced, science short, capped | Invest / Conditional | unchanged |

- `decide_full` checks negative evidence first (kill, `neg_dni`, minuses outweighing pluses); only when none of these
  decides does thin evidence give Insufficient evidence. `GROUNDS_VERDICT` maps every grounds key to one verdict.
- Order for better/worse (`VERDICT_RANK`, used by "what would change"): Invest > Conditional > Insufficient evidence >
  Do Not Invest. A minus can only move Insufficient evidence down to Do Not Invest; a plus only up.
- A warning that counts as a minus is negative evidence under the rules: e.g. `no_genetics_no_precedent` alone gives
  Do Not Invest (outweighed), not Insufficient evidence.
- `verdict.science_short` may also be "Insufficient evidence" (2.3 maps a Do Not Invest setting there to it).

Backend: `backend/app/scorer.py` exports `VERDICTS`; the memo's recommendation adds "Insufficient evidence is not a
negative call …"; the memo validator rejects LLM text that names another verdict (now also "Insufficient evidence");
the LLM prompt lists the four verdicts; API description, live-sample and backtest reports count Insufficient evidence
on its own; the frontend has a neutral badge for it (it shows mock data, no list of values to update).

Legacy `scoring_engine` 1.3 (`UNOBIO_SCORER=v1`, comparison only): unchanged package; `backend/app/scorer.py` shows its
Do Not Invest with grounds `insufficient_evidence` as Insufficient evidence. 7 backend tests that expect 2.x behaviour
failed under v1 before 2.3 and still do (same 7).

## 2. Genetic support `mendelian_subtype` (`unobio_scoring/fixes.py`, `backend/app/facts.py`)

| Mendelian records (Open Targets, indirect evidence on) | 2.2 | 2.3 |
|---|---|---|
| at least one for the disease itself | mendelian, +2 | mendelian, +2 (subtype records do not lower it) |
| all for more specific diseases under it | mendelian, +2 | **mendelian_subtype, +1** |
| a record that names no disease | mendelian | mendelian (not called a subtype; the claim says it cannot be told apart) |

- A subtype is what the ontology says, not a word in a name: Open Targets returns evidence for the disease and its
  descendants, and each row names the disease it is for (`disease.id`, `disease.name`).
- Scorecard `human_genetics` (and legacy `biology`): green includes `mendelian_subtype` (1 plus); `strong_green` stays
  `genetic_support == mendelian` only.
- Claim and memo: "KCNJ5: Mendelian genetics in a rare subtype (name from the record), not in atrial fibrillation
  itself … Counted as ordinary genetic support (+1)". The scientific thesis starts with this line (code-written), the
  LLM prompt says how to name it, and the validator drops LLM text that calls it Mendelian evidence for the disease.
- Derived values: reference probability (Minikel table, not part of the verdict) treats it as `unknown` (the broader
  cell), never the Mendelian rate; economics relative success 2.0 [assumption], as GWAS, matching its +1.
- Why: the 10 October live sample rated Atrial Fibrillation + KCNJ5 (failed in Phase 2) Invest on one Orphanet record
  for a familial subtype. Recorded runs keep their values: PCSK9 + FH mendelian, HTT + Huntington mendelian (direct
  records next to juvenile Huntington records), BACE1 + Alzheimer none.

## 3. Disease names (`backend/app/normalize.py`)

Names are compared by forms (`name_forms`): MeSH inverted order, plural of each word, possessive/apostrophes,
hyphens and spacing. MeSH headings are also searched in natural order (Open Targets finds nothing for
"Neuralgia, Postherpetic"). Rules a (exact name) and b (exact synonym) look at the hits of every search; rule c (score
gap) compares scores within one search. Abbreviations stay ambiguous; two entities with the same form stay ambiguous.
The registry disease match (`translation.aact_in_disease`) uses the same forms.

## 4. Samples

| | First sample | Second sample |
|---|---|---|
| Pairs | 15 from Minikel 2024 (`backtest_truth.json`), 5 per group, seed 9 | 15 in `backend/tests/mechanism_pairs.txt` |
| Input | MeSH disease + target symbol | disease + explicit mechanism |
| Checks | false Invest, false kill, Insufficient evidence share, genetics vs Minikel, MeSH entity | expected properties per pair: parser, same-mechanism drugs, precedent, efficacy failures vs other stops, verdict once pending claims are confirmed |
| Run | `python collect_results.py --sample 15` | `python collect_results.py --mechanisms` |
| Offline tests | `test_live_sample.py`, `test_mesh_names.py` | `test_mechanism_sample.py` (parser on all 15, three recorded pairs) |

First sample selection: every criterion (resolves in Open Targets, resolves to the pair's MeSH entity, not a duplicate
disease + target) is checked before the sample is cut to 5 per group. Seed 9 keeps the 15 pairs of the 10 October run
first; the 5 that were lost then (MeSH names) now resolve in the offline reproduction of the answers seen that day.
Reserves come from a second seeded draw and are used only when a pair fails a criterion, which the report lists.

Both samples test what the pipeline does with today's data. They are not forecasts: an outcome that came after a
decision date is never treated as something the system should have known then.

## Tests

`python3 -m pytest -q` (backend), `python3 -m pytest -q unobio_scoring/tests`, `python3 -m pytest -q scoring_engine`.
New: `test_mesh_names.py`, `test_live_sample.py` (selection), `test_insufficient_api.py`, `test_mendelian_subtype.py`,
`test_mechanism_sample.py`, `unobio_scoring/tests/test_insufficient_evidence.py`.

# unobio backend

Disease + target -> Open Targets data -> claims (code, plus LLM labels for trial stop reasons) -> scorer verdict
(Invest / Conditional / Insufficient evidence / Do Not Invest), stored in SQLite and served by FastAPI. Every claim keeps the rule it applied
and its sources, so a verdict can be traced back to Open Targets records and ClinicalTrials.gov entries.

## Setup and run (from the repo root)

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 main.py                                   # API on http://127.0.0.1:8000, docs at /docs
python3 -m pytest -q                              # backend tests, no network
```

LLM: copy `backend/.env.example` to `backend/.env` and set `TEAM_API_KEY` and `UNOBIO_LLM_BASE_URL` (the hackathon
gateway; model `gpt-6-luna` by default, change with `UNOBIO_LLM_MODEL`), or `OPENAI_API_KEY`. Check the connection:
`python3 -m backend.tests.check_llm`. Without an LLM everything works except trial stop-reason labels, and the
memo uses template text. If the gateway rejects a parameter (strict JSON schema, reasoning effort), the client
falls back to a simpler request by itself; `check_llm` shows which shape worked.
Requests are packed to the gateway's input limit (`UNOBIO_LLM_INPUT_BUDGET`, default 3,500 estimated tokens) and up to
`UNOBIO_LLM_WORKERS` (default 4) run at once; the stop-reason and document stages run side by side
(`backend/app/batching.py`). "Too many active requests" (HTTP 429) lowers the number in flight for the rest of the
process. Keep `UNOBIO_LLM_MAX_TOKENS=4096`: the gateway refuses 16000.
Registry trials of the mechanism in the disease whose result the code cannot read (finished, no stop reason, no
primary-outcome p-value) are looked up in PubMed by NCT ID (`pubmed_nct` in `/runs/{id}/translation`); a paper saying
the primary endpoint was not met becomes a pending efficacy-failure claim.

## Step scripts (command line, from the repo root)

| # | What | Command |
| --- | --- | --- |
| 1 | Claims -> verdict with the scorer | `python3 -m backend.tests.step1_score [--confirm]` |
| 2 | Text -> Open Targets IDs | `python3 -m backend.tests.step2_normalize "Alzheimer disease" "BACE1 inhibitor"` |
| 3 | Collect raw Open Targets data | `python3 -m backend.tests.step3_collect "Alzheimer disease" "BACE1 inhibitor"` |
| 4 | Claims by code -> verdict | `python3 -m backend.tests.step4_score "Alzheimer disease" "BACE1 inhibitor"` |
| 5 | Plus LLM labels for stopped trials | `python3 -m backend.tests.step5_labels "Alzheimer disease" "BACE1 inhibitor"` |
| 6 | API server | `python3 main.py` |
| 7 | Add / confirm evidence -> new verdict | `POST /runs/{id}/evidence` (see below) |
| 8 | Full run with the investment memo | `python3 -m backend.tests.step8_report "Alzheimer disease" "BACE1 inhibitor"` |
| 9 | Translation chain from openFDA, UniProt, PubMed, AACT | runs inside every API run; `GET /runs/{id}/translation` |
| 10 | Market and round inputs, economics in the verdict and memo | `POST /runs` with `market` / `round_terms`; `POST /runs/{id}/inputs`; `GET /runs/{id}/economics` |
| – | Rescore stored runs with the current scorer | `python3 -m backend.tests.rescore [--write]` |

Data: Open Targets, openFDA, UniProt, PubMed and CMS responses are cached in `backend/data/cache/`, LLM answers in `backend/data/llm_cache/`,
the database is `backend/data/unobio.db` (all git-ignored). `--refresh` fetches Open Targets again.
Example API responses on real data: `docs/api/` (regenerate: `python3 -m backend.tests.make_api_examples`).
Disease names: `backend/app/normalize.py` compares names by their written forms, so MeSH headings and other
conventions match exactly: inverted order ("Kidney Failure, Chronic" = "chronic kidney failure"), plural
("Hyperlipidemias" = "hyperlipidemia"), possessive and apostrophes ("Alzheimer Disease" = "Alzheimer's disease"), hyphens
and spacing ("non-small-cell" = "non-small cell"). A MeSH heading is also searched in natural order. Forms only make two
names equal; two different entities with an equal form, or no equal form and no clear score winner, stay `ambiguous`.

## API

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/runs` | `{disease, target}` text or `{disease_id, target_id}`, optional `phase`, `route`, `market`, `round_terms`, `license_terms` (step 10). Returns 202 and `run_id`; the analysis runs in the background |
| GET | `/runs` | Latest runs with their decision |
| GET | `/runs/{id}` | Status (`queued`, `running`, `done`, `ambiguous`, `not_found`, `error`), resolved disease and target (candidates when ambiguous), verdict summary with scorecard and rules |
| GET | `/runs/{id}/claims` | Claims with `status` (`used`, `pending`, `rejected`, `conflict`); filters `fact`, `origin` |
| GET | `/claims/{id}` | One claim: statement, rule, sources (URLs), quote for LLM claims |
| GET | `/runs/{id}/result` | Full scorer output: scorecard, rules, what would change the verdict, due-diligence questions; `?version=` |
| GET | `/runs/{id}/trials` | Stopped trials and the LLM labels with quotes |
| POST | `/runs/{id}/evidence` | Add human evidence (`action: add`, `fact`, `value`, `source_url` or `source_text`) or confirm an LLM claim that waits (`action: confirm`, `claim_id`). Returns the new verdict version and `change` ("before -> after"). Invalid or contradictory evidence: 422, nothing stored |
| GET | `/runs/{id}/history` | All verdict versions with their trigger and `change` |
| GET | `/runs/{id}/report` | The memo for the latest (or `?version=`) verdict: 11 sections, each paragraph `{text, kind, claim_ids}`; 202 while it is written |
| GET | `/runs/{id}/report.md` | The same memo as Markdown |
| POST | `/runs/{id}/report` | Rewrite the memo (e.g. after adding an LLM key) |
| GET | `/runs/{id}/translation` | Translation chain: same-mechanism drugs, status of each source, LLM findings with quotes and checks, per link who showed it / did not / only tested it |
| GET | `/runs/{id}/log` | Every external call of the run (Open Targets, other sources, LLM with tokens and latency) |
| POST | `/runs/{id}/inputs` | Set or clear `market`, `round_terms`, `license_terms` on a finished run and rescore: new verdict version with `change` (incl. `caps_added`, `question` thesis -> round) |
| GET | `/runs/{id}/economics` | Market inputs with provenance, rNPV, Monte Carlo, scenarios, capital to next milestone, round view; `?version=` |
| GET | `/facts` | The 96 facts the scorer accepts: label, type, allowed values, level, due-diligence question (for evidence forms) |
| GET | `/health` | Scorer version (2.7) and hash, LLM provider and whether a key is set |

Every scorecard item and fired rule has `claim_ids`: verdict -> item or rule -> `GET /claims/{id}` -> sources.
Human evidence outranks Open Targets and LLM claims for the same fact; the replaced claim gets status `not_used`.

Ambiguous input: show the candidates, then start a new run with the chosen `disease_id` / `target_id`.
Example responses on real data: `docs/api/` (regenerate: `python3 -m backend.tests.make_api_examples`). Database: `backend/data/unobio.db`.

## Scorer and economics (step 10, `unobio_scoring/`, `backend/app/market.py`)

The scorer is `unobio_scoring` 2.7 (`backend/app/scorer.py` picks it; `UNOBIO_SCORER=v1` falls back to
`scoring_engine` 1.3 for comparison only, the backend tests expect 2.x: 7 of them fail under v1, as before 2.3).

Verdicts: **Invest**, **Conditional**, **Insufficient evidence**, **Do Not Invest**. Insufficient evidence means the
grounds are `insufficient_evidence`: no kill rule, minuses below the threshold and not outweighing the pluses, but not
enough confirmation for Conditional or Invest. It is not a negative call, and the memo says so. Do Not Invest stays
for negative evidence (grounds `kill`, `negatives`, `outweighed`). A warning that counts as a minus (for example
"neither genetics nor a target precedent") is negative evidence under the rules, so it gives Do Not Invest
(outweighed), not Insufficient evidence. Under `UNOBIO_SCORER=v1` the backend shows 1.3's Do Not Invest with grounds
`insufficient_evidence` as Insufficient evidence too (`backend/app/scorer.py`); the 1.3 package is unchanged. What it adds over 1.3: caps that hold a
positive picture at Conditional (me-too, round price, no asset data on a round question), economics, and the
class-level translation rule `engaged_no_benefit`.

Two questions, chosen by the input:
- no `round_terms`: **is the thesis investable** (target + mechanism + indication). Invest does not need data on a
  specific asset; the memo says so in the recommendation.
- with `round_terms`: **invest in this round**. Invest needs at least one asset-level scorecard item with data
  (`cap_asset_data`), and when patients and price are sourced the round price is tested: `round_overpriced` caps at
  Conditional (`cap_round_price`) and the memo gives the highest pre-money that still earns the discount rate.

Market data, collected once per run and stored in `raw.collected.market` (a rescore needs no network):
- patients: Orphanet product 9 by the Open Targets cross-reference `Orphanet:<code>`. The XML file (~16 MB) is not
  shipped; download once with `python3 -m backend.app.market --download` (or set `UNOBIO_ORPHANET`). Without it, or
  for a disease Orphanet does not cover, enter `market.us_patients`.
- prices: CMS Medicare Part D / B spending per beneficiary (cached in `backend/data/cache/cms/`) for the approved
  drugs of the same mechanism (sourced price) and the other approved drugs for the disease (shown as an assumption,
  other mechanisms).
- `market` fields a person enters always win and are tagged `[entered]` in the memo.

Economics can only lower a verdict, and only when patients and price are sourced or entered; otherwise they are shown
with the note "shown, not used in the verdict". Defaults (funnel 100%, exclusivity 13 years after launch for a
patent-protected NME, Sertkaya trial costs in 2024 dollars plus $5m/year overhead) are tagged `[A default]`.

Memo: Commercial opportunity and Capital to next milestone now start with code-written lines (every number tagged
`[S]`, `[entered]`, `[A]`, `[A default]` or `[D]`); the LLM may only interpret them, without numbers.

Example (thesis, then the same thesis as a round):
```
POST /runs {"disease": "familial hypercholesterolemia", "target": "anti-PCSK9 antibody", "phase": "ph2",
            "market": {"us_patients": 1300000}}
POST /runs/{id}/inputs {"round_terms": {"pre_money_m": 120, "investment_m": 40, "cash_m": 60}}
GET  /runs/{id}/economics
```

## Definitions used in step 4 (`backend/app/facts.py`)

Checked on live Open Targets data (release 26.09). Each claim carries the rule it applied and its sources.

| Fact | Definition |
| --- | --- |
| `genetic_support` | Mendelian: ClinGen, Gene2Phenotype, Genomics England, Orphanet, UniProt literature, or ClinVar with a pathogenic / likely pathogenic variant, for the disease itself (+2). `mendelian_subtype` ("Mendelian, subtype", +1): every such record is for a more specific disease under it (Open Targets indirect evidence names the disease of each record); the claim and the memo say "Mendelian genetics in a rare subtype (name from the record)". Records for the disease itself keep `mendelian` even when subtype records exist; a record naming no disease is not called a subtype. GWAS: credible set with L2G >= 0.5. Somatic: IntOGen, Cancer Gene Census. Not counted: gene burden, UniProt variants. `none` only from a complete evidence list and a disease that has genetic data; `no_data` when the disease has none |
| Approval | An FDA, EMA or DailyMed label mapped to the disease ID. TTD-only and PMDA-only approvals are ignored (PMDA mapped "AD/HD" to Alzheimer disease); radiotracers are not therapies; salt forms are one drug |
| Same mechanism | Same target and same direction of action; an unknown direction counts as the same |
| `moa_clinical_precedent` | `approved_same` > `approved_related` (shared specific therapeutic area; phenotype, biological process, measurement, "genetic, familial or congenital" do not count) > `approved_unrelated` > `none` |
| `ph3_same_moa_count` | Same mechanism, not approved here, an active (recruiting / active) Phase 3 trial in this disease |
| `class_safety_signal`, `class_withdrawal` | Only when a same-mechanism drug has a boxed warning / withdrawal; never set to false |
| `rare_disease` | Only when the disease ID itself is Orphanet; an Orphanet cross-reference is not enough |
| `modality_target_mismatch` | Antibody, ADC, bispecific or cell therapy and no membrane / secreted / extracellular location and no antibody tractability |
| `moa_failures_efficacy_ph23` (LLM) | Distinct same-mechanism drugs with a Phase 2, 2/3 or 3 trial in this disease that the LLM labelled `efficacy`, with a quote found in the stated reason. Never zero from text |
| `moa_discontinued_safety_count` (LLM) | Distinct same-mechanism drugs with any stopped trial labelled `safety` (any disease). Outside this disease's Phase 2/3 trials the LLM reads at most 4 stopped trials per drug, those with a safety word in the reason first (`trials.to_label`) |
| `indication_enrollment_terminations_high` (LLM) | At least 5 labelled Phase 2/3 trials in the disease stopped for enrollment and at least a third of those with a stated reason; never false |
| Independence | Two trials count as independent sources only with different sponsors (first word of the sponsor name) |
| Not produced yet | Indication track record, target safety flags (no agreed definition) |

## Report (step 8, `backend/app/report.py`)

Sections: recommendation, scientific thesis, human translation thesis, clinical development plan, competitive
landscape, commercial opportunity, capital to next milestone, key risks, critical unknowns, diligence questions, sources.

| Paragraph `kind` | Written by | Meaning |
| --- | --- | --- |
| `scorer` | code | Computed: verdict, numbers, fired rules, unknowns, diligence questions |
| `source` | LLM or template | What the cited claims say; always has `claim_ids` |
| `inference` | LLM | The model's own conclusion from the cited claims; show it as AI inference |

The LLM sees only the stored claims and the verdict, never raw documents. Each LLM paragraph is checked: cited claim
IDs exist, a `source` paragraph cites at least one, every number in it appears in a cited claim, and it names no
verdict other than the computed one. Failing paragraphs are dropped (listed in `llm.issues`), the model gets one
retry with the reasons, and a section left empty falls back to the claim statements. A new memo is written for every
verdict version (after each `POST /runs/{id}/evidence`).

## Translation chain (step 9, `backend/app/translation.py`, `backend/app/sources/`)

Brief, step 3: molecular effect -> human exposure -> target engagement -> biological response -> patient benefit.
The input names a mechanism, not a molecule, so public evidence is about other drugs with the same mechanism (the
"class"). It becomes mechanism-level facts (`class_*`), never the asset's own links: green for the "Translation chain"
item still needs the asset's data.

| Source | Client | What it gives | Fact or use |
| --- | --- | --- | --- |
| Open Targets `impc`, `crispr`, `crispr_screen`, `ot_crispr*` | `collect.py` (`pair_biology`) | Link 1: knocking out or blocking the target changes a disease phenotype | `perturbation_evidence` (code) |
| Open Targets `expression_atlas`, `reactome`, `progeny`, `slapenrich`, `sysbio` | same | Link 1, correlational | `correlational_evidence` (code) |
| openFDA labels | `sources/openfda.py` | Pharmacokinetics, pharmacodynamics, mechanism of action of approved same-mechanism drugs | `class_exposure_human`, `class_target_engagement_human`, `class_pd_response_human` (LLM) |
| PubMed (E-utilities) | `sources/pubmed.py` | Abstracts on PK/PD of the class drugs and on knockout / animal models of the target | same facts, `perturbation_evidence`; "clinical benefit not shown" adds to `moa_failures_efficacy_ph23` |
| AACT (Postgres, `AACT_DSN`) | `sources/aact.py` | All trials of the class drugs with MeSH terms, stop reasons, outcome titles, primary-outcome p-values | disease mapping by MeSH (fixes trials Open Targets leaves without a disease); `moa_failures_efficacy_ph23` when every primary superiority analysis has p >= 0.05 (code); outcome titles = link *tested*, not shown |
| UniProt | `sources/uniprot.py` | Subcellular location with evidence codes | `modality_target_mismatch`: only the cell surface, plasma membrane, secreted or extracellular count; organelle membranes do not |

Rules the code holds:
- Exposure counts only from drugs of the input's modality group (an antibody reaching the brain says nothing about an
  antisense drug); target engagement and pharmacodynamic response transfer across modalities.
- LLM findings follow the trial-label pattern: the model quotes, code checks the quote is in the document, and a second
  narrow LLM check (`support.py`) asks whether the quote states the finding. The same check now runs on efficacy and
  safety stop labels ("The primary endpoint was achieved" is a real quote, not a failure).
- A registered outcome ("CSF drug concentration") means the link was tested; only results or a publication say shown.
- Retracted papers are never read. Each paper or label counts as its own document for the "second source" rule.
- Scorer 1.2 adds the strong minus `engaged_no_benefit`: class target engagement or PD shown, at least one Phase 2/3
  efficacy failure of the mechanism here, no approved drug of the mechanism here. With `one_mechanism_failure` that
  is 4 minuses: Do Not Invest.
- The memo's human translation thesis starts with the five links (code): asset status, class status, trials that
  only tested it, and the due-diligence question for each missing link; missing links go to Critical unknowns.

Every source caches its answers under `backend/data/cache/<source>/`. Tests run with `UNOBIO_OFFLINE=1` against
mock servers in the documented response shapes (`tests/test_step9.py`); copy a live run's cache folders into
`tests/fixtures/` to replay real responses.

## Testing the LLM part

| Level | Command | What it proves | Needs |
| --- | --- | --- | --- |
| 1. Logic | `python3 -m pytest -q` | Our code around the LLM: quote checks, support checks, counting, pending claims, fallbacks. Fake LLMs, offline | nothing |
| 2. Connection | `python3 -m backend.tests.check_llm` | Key, URL, model and JSON mode work | key in `backend/.env` |
| 3. Quality | `python3 -m backend.tests.eval_llm` | The real model on hand-labelled cases (`tests/llm_gold.py`): stop reasons and translation findings, after the quote and support checks. Exit 1 on any failure | key |
| 4. Regression | `python3 -m backend.tests.eval_llm --record`, then `pytest` | Records the real answers to `tests/fixtures/llm/`; `test_llm_replay.py` replays them offline in every test run | key once |
| 5. End to end | `python3 -m backend.tests.step8_report "Huntington disease" "HTT antisense oligonucleotide"`, then `GET /runs/{id}/translation`, `/trials`, `/log` | A full run with live sources and the LLM: findings with quotes, support flags, tokens | key + network |

Answers are cached by model + prompt + input (`backend/data/llm_cache/`): a rerun costs nothing and repeats the same
answer. `eval_llm` uses a temporary cache, so it always asks the model. After changing a prompt, record again: the
replay test fails with "record again" because the cache keys no longer match. Add a case to `llm_gold.py` whenever a
real run shows a wrong label.

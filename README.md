# unobio

AI investment underwriting for biotech: indication + mechanism -> evidence -> claims -> verdict
(Invest / Conditional / Insufficient evidence / Do Not Invest) -> investment memo, with every conclusion traceable to its sources.

```
input (disease, mechanism text, optional phase / route)
  -> normalize        Open Targets IDs; ambiguous names are returned with candidates, never guessed
  -> collect          Open Targets (genetics, drugs, trials, target info, perturbation / expression evidence)
                      + openFDA labels, UniProt, PubMed, AACT for the translation chain
  -> claims           code for structured data; LLM for free text, always with a quote that code checks
                      and a second support check; every claim keeps its rule and sources
  -> scorer           unobio_scoring/ 2.3: deterministic rules, no LLM; version + sha256 in every result;
                      economics (rNPV, Monte Carlo, round price) from Orphanet patients and CMS prices
                      or numbers a person enters; can only lower a verdict, never from assumed numbers
  -> memo             11 sections; code writes numbers, verdict, chain, unknowns, diligence questions;
                      the LLM writes prose only from stored claims, validated paragraph by paragraph
  -> human evidence   POST /runs/{id}/evidence -> new verdict version with "before -> after"
  -> round question   POST /runs/{id}/inputs {round_terms} -> Invest needs asset data; round price tested
```

- `backend/README.md`: setup, API, definitions of every fact, the translation chain
- `unobio_scoring/README.md`, `docs/scoring_2.1/`, `docs/CHANGES_2.2.md` and `docs/CHANGES_2.3.md`: the scorer and economics
- `scoring_engine/`: scorer 1.3, kept for comparison (`UNOBIO_SCORER=v1`)
- Run: `pip install -r requirements.txt`, `python3 main.py`, open http://127.0.0.1:8000/docs
- Tests: `python3 -m pytest -q` (backend, offline), `python3 -m pytest -q unobio_scoring/tests`,
  `python3 -m pytest -q scoring_engine`

Live samples (need the network and an LLM key; run on your machine):
- `python collect_results.py --sample 15` — 15 pairs with a known outcome (Minikel 2024), 5 per group; pairs are
  checked to resolve to their MeSH disease before the sample is cut (`backend/tests/live_sample.py`)
- `python collect_results.py --mechanisms` — 15 pairs with an explicit mechanism and expected properties
  (`backend/tests/mechanism_pairs.txt`, `backend/tests/mechanism_sample.py`)

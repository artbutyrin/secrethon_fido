# Changed files in 2.4 (10 October 2026, see docs/CHANGES_2.4.md)

- Scorer: `unobio_scoring/fixes.py`, `engine.py`, `report.py`, `README.md`
- Backend: `backend/app/facts.py`, `trials.py`, `pipeline.py`, `api.py`, `db.py`, `report.py`, `llm.py`, `normalize.py`,
  `collect.py`, `translation.py`, `opentargets.py`, `scorer.py`, `sources/http.py`, `sources/ctgov.py`
- Tests: new `backend/tests/test_v24.py`; updated `conftest.py`, `test_step4/5/6/7/8.py`, `test_insufficient_api.py`,
  `test_mechanism_sample.py`, `unobio_scoring/tests/test_unobio_scoring.py`, `test_insufficient_evidence.py`
- Sample: `backend/tests/mechanism_pairs.txt` (verdict expectations), `mechanism_sample.py`
- Docs: `docs/CHANGES_2.4.md`, `docs/api/*` (regenerated), `backend/README.md`

# Changed files vs unobio-step92.zip

New
- `unobio_scoring/` — scorer 2.2 (teammate's 2.1 + update, plus the changes in `docs/CHANGES_2.2.md`)
- `unobio_scoring_examples/` — SOD1, PCSK9, BACE1 claims; HTT facts; `build_market_from_sources.py`
- `docs/scoring_2.1/` — teammate's INTEGRATION, FACTS, RULES (2.1); `docs/CHANGES_2.2.md` — what 2.2 changes and how it is wired
- `backend/app/scorer.py` — one import point for the scorer (`UNOBIO_SCORER=v1` → scoring_engine 1.3)
- `backend/app/market.py` — Orphanet patients, CMS prices; `python3 -m backend.app.market --download`
- `backend/tests/test_step10.py` — market / round inputs, economics in verdict and memo, Orphanet, DB migration
- `backend/tests/rescore.py` — your stored runs before → after with the current scorer

Changed (backend)
- `api.py` — `market`, `round_terms`, `license_terms` on POST /runs; POST /runs/{id}/inputs; GET /runs/{id}/economics
- `db.py` — three run columns, added on start to existing databases
- `pipeline.py` — `score_claims(..., market_data, market, round_terms, license_terms)`; round question config
- `report.py` — code-written Commercial opportunity and Capital to next milestone; question and caps in Recommendation
- `evidence.py` — `change` also has caps added/removed, question, rNPV P50
- `facts.py` — `approved_same_moa_same_modality_count`; strict same-mechanism counts (review F36/F37)
- `trials.py` — per-drug sources with `verified` for the claims gate; negation filter
- `translation.py`, `support.py` — translation chain and the support check (earlier steps)
- tests 1–9 — expectations for scorer 2.2 (PCSK9 me-too is a strong minus + cap; class evidence is not asset data)

Changed (scorer 1.3, kept for comparison): `scoring_engine/` — review fixes and claims gate
Docs: `README.md`, `backend/README.md`, `docs/api/*` (regenerated)

Not in the zip on purpose: `backend/.env` (it contained a live TEAM_API_KEY in the zip you sent — rotate that key),
`.venv`, `backend/data/` (database, caches, Orphanet file).

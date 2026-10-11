# unobio_scoring 2.2 — changes since 2.1 and how it is wired into the backend

2.2 = the teammate's 2.1 (incl. the update) + the translation facts from step 9 + fixes for the HTT report items 2–6
+ corrected economics defaults. Package tests: 48 (`python -m pytest -q unobio_scoring/tests`).

## Scorer (`unobio_scoring/fixes.py`, `engine.py`)

| Change | Why |
|---|---|
| New facts `class_exposure_human`, `class_target_engagement_human`, `class_pd_response_human` (mechanism level) | The backend's translation chain (step 9) fills them from other drugs of the mechanism; 2.1 had nowhere to put them |
| New strong rule `engaged_no_benefit`: the class reached and engaged the target in humans, yet ≥ 1 same-mechanism drug failed Phase 2/3 for efficacy and none is approved | "The drug works on the target, the target does not work on the disease" — the strongest translation signal public data can give |
| Class facts never count as asset data | Otherwise the translation chain item would turn green from other companies' drugs |
| New fact `round_overpriced` + cap `cap_round_price` (HTT item 3) | 2.1 printed an expected IRR below the discount rate next to Invest. Now, when patients and price are sourced, a round that does not earn the cost of capital caps Invest at Conditional; the report gives the highest pre-money that does |
| Round terms ⇒ `asset_data_for_invest` (HTT item 2) | With round terms the question is "invest in this round", which needs data on the asset itself (`cap_asset_data`). Without them the question is the thesis, and the memo says what Invest means. The CLI and the backend both pick the config this way |

## Economics (`constants.py`, `economics.py`, `forecast.py`, `report.py`)

| Change | 2.1 | 2.2 |
|---|---|---|
| Exclusivity after launch (HTT item 4) | 5 years for small molecules / nucleic acids, also for a rare disease | max(13 years empirical NME market exclusivity, Grabowski 2021; statutory floor: NCE 5, orphan 7, biologic 12). Patent `none`/`expired` → the statutory floor only. Unknown patent status is tagged [A] |
| Trial costs | Sertkaya per-trial costs | Sertkaya per trial × trials per phase (1.71 / 1.52 / 2.66) × CPI 2008→2024 (1.457) — review patch 01; DiMasi × 1.347 for the worse case |
| Company overhead | none | $5m per year of development in the base case (`overhead_m` shown separately) |
| Funnel defaults | silently 100% | still 100%, but listed in `assumptions.defaulted`, tagged [A default] and the memo says peak sales are an upper bound |
| Same-indication CMS price | treated as a sourced price | other mechanisms (possibly cheap generics): tagged [A], cannot drive the verdict. Only same-mechanism analogues are a sourced price |
| Scenarios (HTT items 5–6) | `base` scenario = one Monte Carlo draw, next to the deterministic base | renamed `median`; "why" = geometric mean of the multipliers over the neighbouring draws (one draw's multipliers were arbitrary) |
| Investor view | MOIC, IRR | + required IRR, max pre-money, `earns_cost_of_capital` |
| Money format | `$-3.9m` | `−$3.9m` |

HTT example (`unobio_scoring_examples/htt_huntington.facts.json`, illustrative facts, assumed price):

| | 2.1 | 2.2 |
|---|---|---|
| Verdict with round terms | Invest | Conditional (`cap_asset_data`: a round needs asset data) |
| Verdict without round terms (thesis) | Invest | Invest |
| Exclusivity after launch | 5 y | 13 y (patent assumed [A]) |
| rNPV (deterministic) | $122.7m | $227.3m |
| Capital to next milestone | $13–59m | $47–79m |
| Round: expected IRR | 2.3% next to Invest | 11.5% vs 10% required; max pre-money $139m |

The patient count in the example (6,365 = Orphanet US point prevalence 1.9/100k) is far below the ~41,000 people with
symptomatic HD often cited for the US (HDSA; from memory, not checked here). Enter `market.us_patients` when a better
figure is known; it wins over Orphanet and is tagged [entered].

## Backend integration (INTEGRATION steps 3–5)

- `backend/app/scorer.py`: one import point; `unobio_scoring` by default, `UNOBIO_SCORER=v1` for `scoring_engine` 1.3.
- `backend/app/facts.py`: `approved_same_moa_same_modality_count` (only from a complete drug list with every drug
  type known), so inclisiran (siRNA) does not make an oral PCSK9 small molecule a third me-too.
- `backend/app/trials.py`: every trial claim source carries `drugs` and `verified`, for the claims gate's recount.
- `backend/app/market.py`: Orphanet (by cross-reference) and CMS (cached) collected once per run.
- `backend/app/pipeline.py`: `score_claims(claims, market_data=, market=, round_terms=, license_terms=)`; the payload
  has `question` (thesis / round) and `market` (input, provenance, notes).
- API: `market`, `round_terms`, `license_terms` on `POST /runs`; `POST /runs/{id}/inputs`; `GET /runs/{id}/economics`;
  `change` now also has `caps_added`, `caps_removed`, `question`, `rnpv_p50_m`. SQLite gets three columns on start.
- Memo: Commercial opportunity and Capital to next milestone are code-written from the economics, every number tagged;
  the recommendation names the question and the caps.
- `python3 -m backend.tests.rescore [--write]`: the runs in your database before → after with the current scorer.

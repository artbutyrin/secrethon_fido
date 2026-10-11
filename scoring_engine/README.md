# unobio-scoring

Steps 6–7 of the unobio pipeline: from facts about a disease + target pair and about the asset, it computes the scorecard, the rules and the verdict **Invest / Conditional / Do Not Invest**. No LLM is involved: the same facts always give the same verdict.

Version 1.3. Full description: `SCORING.md`. Validation on real data: `VALIDATION.md`, sections 12 and 13. Pipeline interface: `SCORING.md`, section 20.

## What is where

| File | What it is |
| --- | --- |
| `benchmarks.yaml` | The single source of truth: 89 facts, 8 scorecard items (plus legacy items for comparison), 53 rules, 8 clusters, 10 consistency checks, 11 fact-derivation rules, weights, thresholds and reference tables |
| `tags.yaml` | Tag dictionary for the "organize" stage: the fact catalog. Generated, not edited by hand |
| `docs/fact_sources.md` | The "fact → source" matrix and the rules that can fire in the first pipeline version. Generated |
| `docs/facts.md` | Fact reference: what each fact means, where to get it, where it is used. Generated |
| `scoring/engine.py` | The pure function `score(cfg, facts)`, "what would change the verdict", due-diligence questions, reference probability; pipeline interface: `facts_from_claims`, `evaluate`, `fact_catalog` |
| `scoring/space.py` | State-space sweep: verdict shares, effect of an added item, threshold fitting |
| `scoring/bench.py` | Bench for labelled cases: metrics, effect of every candidate on every case, ablation |
| `scoring/cli.py` | Command line |
| `cases_template.yaml` | Template for labelled deals |
| `examples/demo_case.yaml` | A made-up example for the "hide or add a fact" demo |
| `out/space_report.md` | Result of the state-space sweep |
| `SCORING.md` | Full description of scoring version 1.3 with validation summaries |
| `VALIDATION.md` | Validation on real target + disease pairs |

## How to run

```
pip install -e .  pytest
python -m pytest -q                               # 294 tests
python -m scoring version                         # version and config sha256
python -m scoring score examples/demo_case.yaml   # verdict for one case
python -m scoring evaluate examples/demo_case.yaml  # full result as JSON for the scores and verdicts tables
python -m scoring space --out out                 # state-space sweep
python -m scoring bench cases.yaml --out out      # run labelled cases
python -m scoring facts > docs/facts.md           # regenerate the fact reference
python -m scoring catalog > tags.yaml             # regenerate the tag dictionary
python -m scoring sources > docs/fact_sources.md  # regenerate the "fact → source" matrix
```

From code:

```python
from scoring import load_config, score, counterfactuals, top_dd_questions, reference_probability

cfg = load_config()
facts = {"approved_therapies_count": 0, "genetic_support": "mendelian", "patent_status": "none"}
res = score(cfg, facts)                 # res.verdict, res.reason, res.grounds, res.colors, res.fired, res.evidence
res.coverage                            # how many of the eight items had data
res.config                              # version and sha256 of the config the verdict was computed with
flips = counterfactuals(cfg, facts)     # which single-fact changes flip the verdict
questions = top_dd_questions(cfg, facts)  # 5–10 due-diligence questions
ref = reference_probability(cfg, facts) # reference: launch share by mechanism evidence and by stage
```

For the pipeline:

```python
from scoring import facts_from_claims, evaluate

claims = [
    {"id": "clm_1", "fact": "genetic_support", "value": "gwas", "origin": "structured"},
    {"id": "clm_2", "fact": "grade5_related", "value": True, "origin": "llm", "verified": True, "doc_ids": ["doc_7"]},
]
got = facts_from_claims(cfg, claims)    # got["facts"], got["rejected"], got["pending"], got["conflicts"]
payload = evaluate(cfg, got["facts"])   # one JSON for the scores and verdicts tables
```

`clm_2` does not become a fact: a drug-related death from LLM text waits for human confirmation (`got["pending"]`). Since 1.3 a second document read by the same LLM step is not enough, and an LLM value that changes the verdict together with the other facts waits too.

## How the verdict is computed

0. **Check and derive.** Facts are checked for type and bounds; obvious consequences are derived (zero approved drugs means zero approved with this mechanism; oncology means life-threatening unless stated otherwise); a contradictory set stops scoring. Derived facts are shown in `res.derived`.
1. **Scorecard.** Each item gets a colour: red if its `red` condition holds; otherwise green if `green` holds; otherwise yellow if something is known about the item; otherwise unknown. Green gives 1 plus, strong green (condition `strong_green`) 2 pluses, red 2 minuses, the rest 0.
2. **Rules.** A kill rule gives Do Not Invest at once. A strong minus costs 2, a warning 1.
3. **Clusters.** From each cluster only the strongest firing counts as minuses. The rest is shown in the report as "absorbed by cluster".
4. **Absorption by an item.** A rule with `absorbed_by` and `absorbed_when` adds no minuses if the named item is red and the condition says it is the same event (own failure and a post hoc subgroup; open-label design and a single-arm trial).
5. **Thresholds.**

```
kill rule                                                   → Do Not Invest
minuses ≥ 4                                                 → Do Not Invest   (pluses do not compensate)
pluses − minuses ≥ 2, no mechanism evidence                 → Do Not Invest
pluses − minuses ≥ 2, science pluses ≥ 2                    → Invest
pluses − minuses ≥ 2, science pluses < 2                    → Conditional
pluses − minuses ≤ 0                                        → Do Not Invest
pluses − minuses = 1, pluses ≥ 2 and mechanism evidence     → Conditional
otherwise                                                   → Do Not Invest
```

Science pluses: pluses of green items on the science axis. Mechanism evidence: at least one green among human genetics, clinical precedent, translation chain and clinical effect. The verdict grounds (`res.grounds`) separate "not enough confirmation" from "minuses outweigh".

### Switches in `benchmarks.yaml`

| Key | Value in version 1.0 | What another value does |
| --- | --- | --- |
| `verdict.min_science_pos_invest` | 2 | 0 restores the version 0.4 Invest condition |
| `verdict.science_short` | `"Conditional"` | `"Do Not Invest"` removes Conditional when science pluses are missing |
| `verdict.conditional_requires_mechanism` | true | false restores the 0.4 behaviour, where a warning could improve the verdict |
| `weights.green_strong` | 2 | 1 cancels strong greens |

## Principles the code holds

- **Unknown does not kill.** A condition on an unknown fact gives "unknown", and the rule does not fire. No kill rule has defaults (since 1.3, me-too kills only when differentiation was checked and refuted), and none fires if any of its facts is unknown; two tests check this.
- **The verdict does not depend on whether an obvious consequence is given.** Consequences are derived before scoring, so an explicitly added fact that already follows from others changes nothing.
- **A fact counts once.** Failures of this mechanism in other drugs go only to rules, failures of other mechanisms only to the indication item, the asset's own failure only to the clinical-effect item. Related rules are grouped into clusters. An endpoint precedent gives green only to the regulatory path.
- **An input error is an error, not silence.** An unknown fact name, an out-of-range value, contradictory facts, a typo in a rule or threshold name stop scoring.
- **Every conclusion leads to facts.** `res.evidence` holds only explicitly entered facts that actually decided a colour or a firing; a derived fact is replaced by the facts it was derived from. The report step maps them to claim IDs.
- **A harsher fact never gives a better verdict.** A milder CRL reason never gives a worse verdict than a harsher one; an event absorbed by a red item never reduces minuses; a disabled minus rule never worsens the verdict, and a disabled green item never improves it. Tests and a random search over fact sets check this.
- **Stronger evidence never gives a worse verdict.** The genetics ladder (none, unrelated disease, GWAS, Mendelian) and the precedent ladder (none, unrelated disease, related) are checked by a separate test.
- **Four facts are deliberately two-sided.** The number of approved drugs, the number approved with the same mechanism, new-mechanism approvals over 10 years and years since the last new mechanism say both "this is already treatable" and "less need, more competition". So a higher value can both improve and worsen the verdict: for example, an approved drug with the same mechanism removes the penalty for mechanism failures and makes biology green, but brings me-too closer.

### Where unknown is treated in a specific way

This is the full list; everywhere else unknown means "the rule is silent". The test `test_defaults_are_exactly_the_documented_ones` keeps the same list in code and fails if a new default appears in the config; then both the test and this table must be updated.

| Where | What is unknown | How it is treated | Why |
| --- | --- | --- | --- |
| Strong minus me-too unproven | Differentiation, its confirmation, channel | No differentiation; an unrefuted claim stands | Analyst's position; since 1.3 a strong minus, not a kill (review F38) |
| Strong minus "mechanism failure" | Mechanism successes | Failures count as a strong minus, not as refutation | Killing is allowed only with a known absence of successes |
| Strong minus "deaths" | Disease severity | Strong minus, not kill | Killing is allowed only for a disease known to be non-fatal |
| Warning "grade 4" | Disease severity | The disease is not life-threatening | Consistent with the deaths rule: with unknown severity the signal is not lost |
| Warning "complex manufacturing" | Sponsor size | Not a big company | The assessment takes a small investor's position; the brief's input has no company |
| Warning "me-too with differentiation" | Confirmation of differentiation | The claim stands until refuted | Consistent with the me-too strong minus |
| Strong minus "late entry" | Number approved in the class | A first in class is assumed to exist | Being late without a first is impossible |
| Warning "competitors in Phase 3" | Number approved in the class | Fewer than two | Otherwise it is already me-too |
| Warning "not reproduced" | Number of reproductions for a retracted paper | Warning | A retraction without reproduction data is a signal |
| Green "indication" | Whether the disease is on the "graveyard" list | Not on the list | The list is static: absence from it is always known |
| Red "drug does what it claims" | Positive Phase 2, approval in another indication | None | They only protect from red for zero pillars |
| Green "design" | Whether dose ranging was done | Does not block green | Missing data raise a question, not a penalty |

## How to change it

Everything is edited in `benchmarks.yaml`. A new rule needs a line in `RULE_FACTS` in `tests/test_engine.py`, a new item a line in `ITEM_GREEN`: tests fail until a firing example is added.

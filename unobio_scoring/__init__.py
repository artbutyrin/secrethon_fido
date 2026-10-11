"""unobio_scoring 2.1 — the unobio scorer: validated version 1.1 rules + review fixes + claims gate + economics.

Standard library only (PyYAML is optional, only to load an external YAML config for comparison).

    from unobio_scoring import load_config, facts_from_claims, evaluate, card, markdown

    cfg = load_config()                              # built in: version 1.1 + fixes (load_config(fixes=False) = 1.1)
    got = facts_from_claims(cfg, claims)             # claims gate: facts, used, pending, rejected, conflicts
    payload = evaluate(cfg, got["facts"], market={"us_patients": 6000, "annual_net_price_usd": 220000})
    print(card(payload))
"""
from .engine import (  # noqa: F401
    CONDITIONAL, DNI, GREEN, INSUFFICIENT, INVEST, RED, UNKNOWN, VERDICT_RANK, VERDICTS, YELLOW,
    Config, ConfigError, FactError, GROUNDS, GROUNDS_VERDICT, Result,
    check_facts, counterfactuals, dd_questions, decide, decide_full, deciding_facts, derive_facts, derive_with_sources,
    eval_cond, evaluate, fact_catalog, facts_from_claims, facts_in, is_negated, item_color, load_config,
    reference_probability, score, top_dd_questions, validate_facts, value_effect,
)
from .fixes import VERSION  # noqa: F401
from .report import card, markdown  # noqa: F401

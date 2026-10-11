"""One import point for the scorer. Default: unobio_scoring 2.7 (rules 1.1 + review fixes + claims gate + economics).
UNOBIO_SCORER=v1 switches back to scoring_engine 1.3 (YAML config) for comparison.

Verdicts everywhere in the backend (API, memo, batch tools): Invest, Conditional, Insufficient evidence, Do Not Invest.
scoring_engine 1.3 predates "Insufficient evidence": it returns Do Not Invest with grounds insufficient_evidence, which
`evaluate` below maps to Insufficient evidence (the decision, and verdict_from in "what would change"; 1.3 does not
return the grounds of the changed verdicts, so verdict_to keeps 1.3's name), so the backend shows one set of verdicts. 1.3 also has no genetic_support value "mendelian_subtype" (2.3): under v1 such a
claim is passed to 1.3 as "gwas", an ordinary genetic link (+1), the weight 2.3 gives it. The 1.3 package itself is
unchanged.
"""
import os

INVEST, CONDITIONAL, INSUFFICIENT, DNI = "Invest", "Conditional", "Insufficient evidence", "Do Not Invest"
VERDICTS = (INVEST, CONDITIONAL, INSUFFICIENT, DNI)

if os.environ.get("UNOBIO_SCORER", "v2") == "v1":
    from scoring_engine.scoring import FactError, check_facts, fact_catalog, load_config  # noqa: F401
    from scoring_engine.scoring import evaluate as _evaluate_v1
    from scoring_engine.scoring import facts_from_claims as _facts_from_claims_v1
    from scoring_engine.scoring.engine import facts_in  # noqa: F401
    ENGINE = "scoring_engine"

    def facts_from_claims(cfg, claims, *args, **kwargs):
        """1.3 does not know mendelian_subtype: pass it as gwas (+1 in both versions)."""
        claims = [dict(c, value="gwas") if c.get("fact") == "genetic_support" and c.get("value") == "mendelian_subtype"
                  else c for c in claims]
        return _facts_from_claims_v1(cfg, claims, *args, **kwargs)

    def evaluate(cfg, facts, *args, **kwargs):
        """scoring_engine 1.3 with its "Do Not Invest for lack of confirmation" shown as Insufficient evidence.
        Counterfactual verdicts cannot be mapped (their grounds are not returned), so they keep 1.3's names."""
        out = _evaluate_v1(cfg, facts, *args, **kwargs)
        v = out["verdict"]
        if v["decision"] == DNI and v["grounds"] == "insufficient_evidence":
            v["decision"] = INSUFFICIENT
            for cf in out.get("what_would_change") or []:
                if cf.get("verdict_from") == DNI:
                    cf["verdict_from"] = INSUFFICIENT
        return out
else:
    from unobio_scoring import FactError, check_facts, evaluate, fact_catalog, facts_from_claims, facts_in, load_config  # noqa: F401
    ENGINE = "unobio_scoring"

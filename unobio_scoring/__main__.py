"""python -m unobio_scoring case.json [--md report.md] [--json result.json] [--v11]

case.json: {"facts": {...}} or {"claims": [...]}; optional "market", "round_terms", "license_terms", "title".
"""
from __future__ import annotations

import argparse
import json
import sys

from . import FactError, card, evaluate, facts_from_claims, load_config, markdown


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="unobio_scoring")
    ap.add_argument("case")
    ap.add_argument("--md")
    ap.add_argument("--json")
    ap.add_argument("--draws", type=int, default=2000)
    ap.add_argument("--v11", action="store_true", help="exact version 1.1 rules, without the review fixes")
    a = ap.parse_args(argv)
    case = json.load(open(a.case, encoding="utf-8"))
    kw = {k: case[k] for k in ("market", "round_terms", "license_terms") if k in case}
    # 2.2: round terms make it a question about this round, and a round needs data on the asset itself for Invest;
    # without them the question is the thesis (target + mechanism + indication)
    cfg = load_config(fixes=not a.v11, asset_data_for_invest=bool(kw.get("round_terms")) and not a.v11)
    if "market" in kw:
        kw["market"] = {k: v for k, v in kw["market"].items() if not k.startswith("_")}
    gate = None
    try:
        facts = case.get("facts", {})
        if "claims" in case:
            claims = list(case["claims"])
            if case.get("phase"):
                claims.append({"id": "input_phase", "fact": "phase", "value": case["phase"], "origin": "user"})
            gate = facts_from_claims(cfg, claims)
            facts = gate["facts"]
        payload = evaluate(cfg, facts, mc_draws=a.draws, **kw)
    except FactError as e:
        print(f"invalid facts: {e}", file=sys.stderr)
        return 2
    if gate:
        payload["gate"] = {k: gate[k] for k in ("pending", "rejected", "conflicts")}
    print(card(payload))
    if a.md:
        open(a.md, "w", encoding="utf-8").write(markdown(payload, case.get("title", "Scoring report")))
    if a.json:
        json.dump(payload, open(a.json, "w", encoding="utf-8"), indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())

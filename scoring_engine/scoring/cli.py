"""Command line.

  python -m scoring score <facts.yaml> [--variant v10]   verdict for one case
  python -m scoring facts                                  fact reference
  python -m scoring version                                config version and hash
  python -m scoring evaluate <facts.yaml>                  full result as JSON (for the scores and verdicts tables)
  python -m scoring catalog > tags.yaml                    tag dictionary for the "organize" stage
  python -m scoring sources > docs/fact_sources.md         "fact → source" matrix and what works in the MVP
  python -m scoring space [--out out]                      state-space sweep
  python -m scoring bench <cases.yaml> [--out out]         run labelled cases
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import bench, space
from .engine import (CONDITIONAL, DNI, INVEST, GREEN, GROUNDS, RED, UNKNOWN, YELLOW, counterfactuals,
                     dd_questions, eval_cond, evaluate, fact_catalog, facts_in, load_config,
                     reference_probability, score)

MARK = {GREEN: "green", YELLOW: "yellow", RED: "red", UNKNOWN: "unknown"}
TIER = {"kill": "kill", "strong": "strong minus", "warning": "warning"}
BASIS = {"evidence": "evidence", "expert": "expert", "mixed": "mixed"}


def _val(v) -> str:
    if v is None:
        return "unknown"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def render_facts(cfg) -> str:
    """Fact reference: what to fill in for a case and where to get it."""
    scope = {"mechanism": "mechanism", "asset": "asset"}
    L = ["# Fact reference", "",
         "Every case is described by these facts. Unknown facts are simply left out. "
         "Generated from `benchmarks.yaml` by `python -m scoring facts`.", "",
         "| Fact | Meaning | Type and values | Level | Where to get it | Used in |",
         "| --- | --- | --- | --- | --- | --- |"]
    from .engine import facts_in
    used: dict = {}
    for item in cfg.items.values():
        names = facts_in(item.get("red", {})) | facts_in(item.get("green", {})) | set(item.get("evidence_facts", []))
        for n in names:
            used.setdefault(n, []).append(item["name"])
    for rule in cfg.rules:
        for n in facts_in(rule["when"]):
            used.setdefault(n, []).append(rule["name"])
    for name, spec in cfg.facts.items():
        kind = {"bool": "yes / no", "int": "integer", "number": "number"}.get(spec["type"])
        if kind is None:
            kind = ", ".join(spec["values"])
        L.append(f"| `{name}` | {spec['label']} | {kind} | {scope[spec['scope']]} | {spec['source']} | "
                 f"{'; '.join(dict.fromkeys(used.get(name, []))) or '—'} |")
    return "\n".join(L) + "\n"


def render_case(cfg, facts: dict, variant: str | None = None) -> str:
    variant = variant or cfg.default_variant
    res = score(cfg, facts, variant)
    rules = {r["id"]: r for r in cfg.rules}
    cov = res.coverage
    L = [f"# Verdict: {res.verdict}", "", f"Reason: {res.reason}.", "",
         f"Grounds: {GROUNDS[res.grounds]}.", "",
         f"Pluses {res.pos} (science {res.science_pos}), minuses {res.neg}, difference {res.diff:+d}. "
         f"Scorecard variant: {variant}. Config: version {res.config['version']}, "
         f"sha256 {res.config['sha256'][:12]}.", "",
         f"Data exist for {cov['items_known']} of {cov['items_total']} items: mechanism level "
         f"{cov['mechanism_known']} of {cov['mechanism_total']}, asset level {cov['asset_known']} of "
         f"{cov['asset_total']}. Axes: science {res.axes['science']['rating']}, commercial and execution "
         f"{res.axes['commercial']['rating']}.",
         "", "The 'Rests on' and 'Facts' columns list only the facts that actually "
         "decided the colour or the firing.",
         "", "## Scorecard", "", "| Item | Colour | Basis | Rests on |", "| --- | --- | --- | --- |"]
    for item_id, color in res.colors.items():
        item = cfg.items[item_id]
        ev = ", ".join(res.evidence.get(item_id, [])) or "—"
        mark = MARK[color] + (" (strong, 2 pluses)" if res.points.get(item_id, 0) > cfg.weights["green"] else "")
        L.append(f"| {item['name']} | {mark} | {BASIS[item['basis']]} | {ev} |")
    if res.derived:
        L += ["", "Derived from other facts: "
              + "; ".join(f"{cfg.facts[n]['label']} = {_val(v)} (from {', '.join(res.derived_from[n])})"
                          for n, v in res.derived.items()) + "."]
    L += ["", "## Rules fired", ""]
    if res.fired:
        counted = {c.split(":", 1)[1] for c, _ in res.counted if c.startswith("rule:")}
        L += ["| Rule | Tier | Basis | Counted | Facts |", "| --- | --- | --- | --- | --- |"]
        for rid in res.fired:
            r = rules[rid]
            if r["tier"] == "kill":
                used = "yes"
            elif rid in counted:
                used = "yes"
            else:
                kind, _, ident = res.suppressed[rid].partition(":")
                used = (f"no, absorbed by cluster '{cfg.clusters[ident]}'" if kind == "cluster"
                        else f"no, the red item '{cfg.items[ident]['name']}' already counts the same event")
            L.append(f"| {r['name']} | {TIER[r['tier']]} | {BASIS[r['basis']]} | {used} | "
                     f"{', '.join(res.evidence.get(rid, []))} |")
    else:
        L.append("No rule fired.")
    L += ["", "## Reference probability", "", "Does not affect the verdict.", ""]
    ref = reference_probability(cfg, facts)
    ev = ref["evidence"]
    if ev and ev["range"]:
        lo, hi = ev["range"]
        base = ev["base"][0] if ev["base"] else None
        L.append(f"- By mechanism evidence ('{ev['label']}'): {_pct(lo)}–{_pct(hi)} of historical pairs reached "
                 f"launch, counting from {ev['from']}" + (f" (all pairs: {_pct(base)})" if base else "")
                 + f". Cell: {ev['n']} pairs, {ev['launched']} launches. Source: Minikel 2024.")
    st = ref["stage"]
    if st:
        L.append(f"- By stage ({st['label'].lower()}): {_pct(st['loa'])} of programs reach approval "
                 f"(all diseases: {_pct(st['all'])}). Source: BIO 2021.")
    for note in ref["caveats"]:
        L.append(f"- Caveat: {note}")
    cfs = counterfactuals(cfg, facts, variant)
    L += ["", "## What would change the verdict", ""]
    if cfs:
        L += ["| Fact | Change | New verdict |", "| --- | --- | --- |"]
        for cf in cfs:
            change = (f"hide (now {_val(cf['from'])})" if cf["action"] == "hide"
                      else f"{_val(cf['from'])} → {_val(cf['to'])}")
            L.append(f"| {cf['label']} | {change} | {cf['verdict_to']} |")
    else:
        L.append("No single-fact change flips the verdict.")
    qs = dd_questions(cfg, facts, variant)
    L += ["", "## Due-diligence questions", ""]
    for q in qs:
        flag = " **(the answer can change the verdict)**" if q["critical"] else ""
        L.append(f"- {q['question']}{flag}")
    return "\n".join(L) + "\n"


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


# ---------------------------------------------------------------------------
# Tag dictionary and the "fact → source" matrix
# ---------------------------------------------------------------------------
SOURCE_LABEL = {"input": "input field", "open_targets": "Open Targets", "clinicaltrials": "ClinicalTrials.gov",
             "clinicaltrials_text": "ClinicalTrials.gov, text (LLM)", "pubmed_text": "PubMed, text (LLM)",
             "curated": "static table", "derived": "derived", "none": "human only"}
# The wider the source set a rule needs, the less it works on its own.
LEVELS = [("alone, from structured sources", {"open_targets", "clinicaltrials", "curated", "derived"}),
          ("with an input field", {"input"}),
          ("with text read by the LLM", {"clinicaltrials_text", "pubmed_text"})]


def render_catalog(cfg) -> str:
    head = ("# Tag dictionary for the 'organize' stage: the facts the scorer accepts.\n"
            "# GENERATED from benchmarks.yaml by `python -m scoring catalog`. Do not edit by hand.\n"
            f"# Config version {cfg.raw['version']}, sha256 {cfg.sha256}.\n"
            "# critical_values: a value that alone triggers a kill rule, a strong minus or a red item;\n"
            "#                  from the LLM it needs human confirmation (since 1.3; also any LLM value that flips the verdict).\n"
            "# absence_values:  a value asserting absence; the LLM cannot set it from text.\n")
    return head + yaml.safe_dump({"facts": fact_catalog(cfg)}, allow_unicode=True, sort_keys=False, width=1000)


def _candidates(cfg, cond: dict, names: set) -> dict:
    """Values to try: all for bool and enum, for numbers the bounds from conditions and neighbouring values."""
    out = {}
    def walk(c):
        if "all" in c or "any" in c:
            for sub in c.get("all", []) + c.get("any", []):
                walk(sub)
        elif "not" in c:
            walk(c["not"])
        elif c["fact"] in names:
            spec = cfg.facts[c["fact"]]
            vals = out.setdefault(c["fact"], set())
            if spec["type"] == "bool":
                vals |= {True, False}
            elif spec["type"] == "enum":
                vals |= set(spec["values"])
            else:
                for key in ("eq", "ne", "ge", "le", "gt", "lt"):
                    v = c.get(key)
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        step = 1 if spec["type"] == "int" else 0.05
                        vals |= {x for x in (v - step, v, v + step) if x >= 0}
                vals |= set(spec.get("probes", []))
    walk(cond)
    return out


def _can_fire(cfg, cond: dict, available: set) -> bool:
    """Whether a condition can become true when only the facts in `available` are known (the rest unknown)."""
    from itertools import product
    cands = _candidates(cfg, cond, facts_in(cond) & available)
    names = sorted(cands)
    for combo in product(*(sorted(cands[n], key=str) for n in names)):
        if eval_cond(cond, dict(zip(names, combo))) is True:
            return True
    return eval_cond(cond, {}) is True


def source_level(cfg, cond: dict) -> str:
    available: set = set()
    for label, sources in LEVELS:
        available |= {n for n, sp in cfg.facts.items() if sp.get("mvp", "none") in sources}
        if _can_fire(cfg, cond, available):
            return label
    return "only with human facts"


def render_sources(cfg) -> str:
    cat = fact_catalog(cfg)
    used: dict = {}
    for item_id in cfg.variant_items():
        item = cfg.items[item_id]
        for n in facts_in(item.get("red", {})) | facts_in(item.get("green", {})) | set(item.get("evidence_facts", [])):
            used.setdefault(n, []).append(item["name"])
    for rule in cfg.rules:
        for n in facts_in(rule["when"]):
            used.setdefault(n, []).append(rule["name"])
    counts: dict = {}
    for spec in cfg.facts.values():
        counts[spec.get("mvp", "none")] = counts.get(spec.get("mvp", "none"), 0) + 1
    L = ["# 'Fact → source' matrix and which rules work in the first pipeline version", "",
         f"Generated from `benchmarks.yaml` (version {cfg.raw['version']}) by `python -m scoring sources`.", "",
         "> **This is a plan, not a verified state.** The 'MVP source' column was filled from source documentation; "
         "no live request has been made yet. Every row must be confirmed by a real API response.", "",
         "## 1. Summary", "",
         "| MVP source | Facts |", "| --- | --- |"]
    for key, label in SOURCE_LABEL.items():
        L.append(f"| {label} | {counts.get(key, 0)} |")
    L += ["", "A human can add any fact manually (`POST /runs/{id}/evidence`).", "",
          "## 2. What can fire", "",
          "For every item and rule: the narrowest source set under which the condition can become true at all.", "",
          "### Scorecard", "", "| Item | Level | Green | Red |", "| --- | --- | --- | --- |"]
    for item_id in cfg.variant_items():
        item = cfg.items[item_id]
        g = source_level(cfg, item["green"]) if "green" in item else "—"
        r = source_level(cfg, item["red"]) if "red" in item else "—"
        L.append(f"| {item['name']} | {'M' if item['scope'] == 'mechanism' else 'A'} | {g} | {r} |")
    tier_counts: dict = {}
    rows = []
    for rule in cfg.rules:
        lvl = source_level(cfg, rule["when"])
        tier_counts.setdefault(rule["tier"], {}).setdefault(lvl, 0)
        tier_counts[rule["tier"]][lvl] += 1
        rows.append(f"| {rule['name']} | {TIER[rule['tier']]} | {'M' if rule['scope'] == 'mechanism' else 'A'} | {lvl} |")
    order = [l for l, _ in LEVELS] + ["only with human facts"]
    L += ["", "### Rules: how many work with each source set", "",
          "| Rule tier | " + " | ".join(order) + " |", "| --- | " + " | ".join("---" for _ in order) + " |"]
    for tier in ("kill", "strong", "warning"):
        L.append(f"| {TIER[tier]} | " + " | ".join(str(tier_counts.get(tier, {}).get(l, 0)) for l in order) + " |")
    L += ["", "### Rules by name", "", "| Rule | Rule tier | M/A | Can fire |", "| --- | --- | --- | --- |"]
    L += rows
    L += ["", "## 3. All facts", "",
          "A critical value alone triggers a kill rule, a strong minus or a red item; from the LLM it "
          "needs human confirmation (since 1.3), as does any LLM value that changes the verdict together with the other facts. The LLM cannot set an absence value from text.", "",
          "| Fact | M/A | MVP source | Critical values | Absence values | Used in |",
          "| --- | --- | --- | --- | --- | --- |"]
    for name, e in cat.items():
        crit = "; ".join(f"{_val_text(k)} ({TIER[t]})" for k, t in e["critical_values"].items()) or "—"
        absent = ", ".join(_val_text(str(v)) for v in e["absence_values"]) or "—"
        L.append(f"| `{name}` | {'M' if e['level'] == 'mechanism' else 'A'} | {SOURCE_LABEL[e['mvp_source']]} | {crit} | "
                 f"{absent} | {'; '.join(dict.fromkeys(used.get(name, []))) or 'legacy items only'} |")
    return "\n".join(L) + "\n"


def _val_text(v: str) -> str:
    return {"True": "yes", "False": "no"}.get(v, v)


def render_space(cfg) -> str:
    L = ["# Scorecard state-space sweep", "",
         "Shares concern cases WITHOUT a kill rule. A kill rule always gives Do Not Invest, "
         "so among all cases the Conditional share is even smaller: multiply it by the share of cases "
         "without a kill rule.", "",
         f"Thresholds: minuses ≥ {cfg.thresholds['neg_dni']} → Do Not Invest; difference ≥ "
         f"{cfg.thresholds['invest_margin']} → Invest; difference ≤ {cfg.thresholds['dni_margin']} → "
         f"Do Not Invest; Conditional needs at least "
         f"{cfg.thresholds['min_pos_conditional']} pluses. Invest requires mechanism evidence and at least "
         f"{cfg.thresholds['min_science_pos_invest']} science pluses; if they are missing, the verdict is "
         f"'{cfg.thresholds['science_short']}'. A strong green gives {cfg.weights['green_strong']} pluses; "
         "the share of strong greens is set by the item's strong_share_assumption.", ""]

    L += ["## 1. Uniform sweep: all item states equally likely", "",
          "| Variant | Items | Minuses from rules | Invest | Conditional | Do Not Invest |",
          "| --- | --- | --- | --- | --- | --- |"]
    for variant in cfg.variants:
        for m in range(4):
            s = space.verdict_shares(cfg, variant, rule_minus=m)
            L.append(f"| {variant} | {len(cfg.variants[variant])} | {m} | {_pct(s[INVEST])} | "
                     f"{_pct(s[CONDITIONAL])} | {_pct(s[DNI])} |")

    L += ["", "## 2. Range on the assumption grid", "",
          "Grid: green share 20–50%, red share 5–15%, two scenarios of minuses from rules "
          "('few': 60% of cases without minuses; 'many': 30%). These are assumptions, not measured frequencies.", "",
          "| Variant | Conditional, min–max | Invest, min–max | Conditional with the original rule (any +1) |",
          "| --- | --- | --- | --- |"]
    for variant in cfg.variants:
        c = space.conditional_range(cfg, variant)
        i = space.invest_range(cfg, variant)
        old = space.conditional_range(cfg, variant, {"min_pos_conditional": 1})
        L.append(f"| {variant} | {_pct(c[0])}–{_pct(c[1])} | {_pct(i[0])}–{_pct(i[1])} | "
                 f"{_pct(old[0])}–{_pct(old[1])} |")

    L += ["", "## 3. What one added item does under unchanged thresholds", "",
          "Reference assumption: 30% green, 15% red, scenario 'few minuses'. In this sweep "
          "items differ only in whether they can be red; how the candidates actually differ "
          "from each other is visible only on real cases.", "",
          "| Added item | Δ Invest | Δ Conditional | Δ Do Not Invest |",
          "| --- | --- | --- | --- |"]
    ref = dict(p_green=0.3, p_red=0.15, minus_dist=space.MINUS_SCENARIOS["few minuses"])
    green_only = next(i for i, it in cfg.items.items() if "red" not in it)
    with_red = next(i for i, it in cfg.items.items() if "red" in it)
    for label, item_id in (("Green or neutral only", green_only),
                           ("Green, neutral or red", with_red)):
        d = space.marginal_effect_of_item(cfg, cfg.default_variant, item_id, **ref)
        L.append(f"| {label} | {100 * d[INVEST]:+.1f} pp | {100 * d[CONDITIONAL]:+.1f} pp | "
                 f"{100 * d[DNI]:+.1f} pp |")

    L += ["", "## 4. Thresholds aligned by Invest share", "",
          "For each variant: the Invest threshold at which the Invest share on the grid is closest to the baseline "
          f"({cfg.default_variant}). The fit does not see case labels.", "",
          "| Variant | Invest threshold | Min greens for Conditional | Invest, min–max | Conditional, min–max |",
          "| --- | --- | --- | --- | --- |"]
    for variant in cfg.variants:
        thr = space.matched_thresholds(cfg, variant)
        c = space.conditional_range(cfg, variant, thr)
        i = space.invest_range(cfg, variant, thr)
        L.append(f"| {variant} | {thr['invest_margin']} | {thr['min_pos_conditional']} | "
                 f"{_pct(i[0])}–{_pct(i[1])} | {_pct(c[0])}–{_pct(c[1])} |")

    L += ["", "## 5. Threshold sweep for the base variant", "",
          "Only thresholds where Conditional covers exactly one score value are shown. If the Invest and "
          "Do Not Invest thresholds are adjacent, Conditional disappears completely.", "",
          "| Minuses for DNI | Invest threshold | DNI threshold | Band | Conditional, min–max | Invest, min–max |",
          "| --- | --- | --- | --- | --- | --- |"]
    for row in space.threshold_sweep(cfg, cfg.default_variant):
        if row["band"] != 1:
            continue
        L.append(f"| {row['neg_dni']} | {row['invest_margin']} | {row['dni_margin']} | {row['band']} | "
                 f"{_pct(row['cond_min'])}–{_pct(row['cond_max'])} | "
                 f"{_pct(row['invest_min'])}–{_pct(row['invest_max'])} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scoring", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None, help="path to benchmarks.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("score"); p.add_argument("facts"); p.add_argument("--variant", default=None)
    p = sub.add_parser("facts")
    p = sub.add_parser("version")
    p = sub.add_parser("catalog")
    p = sub.add_parser("sources")
    p = sub.add_parser("evaluate"); p.add_argument("facts"); p.add_argument("--variant", default=None)
    p = sub.add_parser("space"); p.add_argument("--out", default="out")
    p = sub.add_parser("bench"); p.add_argument("cases"); p.add_argument("--out", default="out")
    p.add_argument("--title", default="Labelled cases through scorecard variants")
    p.add_argument("--synthetic", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(args.config) if args.config else load_config()

    if args.cmd == "score":
        data = yaml.safe_load(Path(args.facts).read_text(encoding="utf-8")) or {}
        facts = (data.get("facts") if "facts" in data else data) or {}
        sys.stdout.write(render_case(cfg, facts, args.variant))
    elif args.cmd == "facts":
        sys.stdout.write(render_facts(cfg))
    elif args.cmd == "catalog":
        sys.stdout.write(render_catalog(cfg))
    elif args.cmd == "sources":
        sys.stdout.write(render_sources(cfg))
    elif args.cmd == "evaluate":
        import json
        data = yaml.safe_load(Path(args.facts).read_text(encoding="utf-8")) or {}
        facts = (data.get("facts") if "facts" in data else data) or {}
        print(json.dumps(evaluate(cfg, facts, args.variant), ensure_ascii=False, indent=2))
    elif args.cmd == "version":
        print(f"version {cfg.raw['version']}, variant {cfg.default_variant}, items "
              f"{len(cfg.variant_items())}, rules {len(cfg.rules)}, facts {len(cfg.facts)}")
        print(f"config sha256: {cfg.sha256}")
    elif args.cmd == "space":
        out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
        path = out / "space_report.md"
        path.write_text(render_space(cfg), encoding="utf-8")
        print(path)
    elif args.cmd == "bench":
        cases = bench.load_cases(cfg, args.cases)
        print(bench.render_report(cfg, cases, args.out, title=args.title, synthetic=args.synthetic))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

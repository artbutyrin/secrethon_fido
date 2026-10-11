"""Bench for cases with a known GOOD / BAD label.

What it computes:
  1. The verdict of every case in every scorecard variant.
  2. Variant metrics: coverage, balanced accuracy with confidence intervals.
  3. For every item: how its colour is distributed between GOOD and BAD.
  4. For every candidate: colour on every case, change in points, change in verdict
     and whether it moved toward the right label.
  5. Ablation: what changes when one item or one rule is switched off.

Nothing here is fitted to the labels: thresholds come from benchmarks.yaml or
from the state-space sweep (space.matched_thresholds), which does not see the labels.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import yaml
from scipy.stats import fisher_exact

from . import space
from .engine import (CONDITIONAL, DNI, GREEN, INVEST, RED, UNKNOWN, YELLOW, Config, Result,
                     check_facts, item_color, score, validate_facts)

GOOD, BAD = "GOOD", "BAD"
COLOR_LABEL = {GREEN: "green", YELLOW: "yellow", RED: "red", UNKNOWN: "unknown"}


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------
def load_cases(cfg: Config, path: str | Path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cases = data["cases"] if isinstance(data, dict) else data
    seen = set()
    for case in cases:
        if case["id"] in seen:
            raise ValueError(f"Case {case['id']} is defined twice")
        seen.add(case["id"])
        if case["label"] not in (GOOD, BAD):
            raise ValueError(f"Case {case['id']}: label must be GOOD or BAD")
        try:
            validate_facts(cfg, case.get("facts") or {})
        except Exception as exc:
            raise ValueError(f"Case {case['id']}: {exc}") from exc
        case["facts"] = check_facts(cfg, case.get("facts") or {})
    return cases


def run(cfg: Config, cases: list[dict], variant, **kw) -> list[Result]:
    return [score(cfg, case["facts"], variant, **kw) for case in cases]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def outcome(label: str, verdict: str) -> str:
    """right / wrong / abstain."""
    if verdict == CONDITIONAL:
        return "abstain"
    return "right" if (label == GOOD) == (verdict == INVEST) else "wrong"


def metrics(results: list[Result], labels: list[str]) -> dict:
    table = {(lab, v): 0 for lab in (GOOD, BAD) for v in (INVEST, CONDITIONAL, DNI)}
    for res, lab in zip(results, labels):
        table[(lab, res.verdict)] += 1
    n = len(labels)
    n_good, n_bad = labels.count(GOOD), labels.count(BAD)
    cond = table[(GOOD, CONDITIONAL)] + table[(BAD, CONDITIONAL)]

    def ratio(a, b):
        return a / b if b else float("nan")

    # 1) Conditional = "abstained": metrics only on cases with a decision
    cov_good = n_good - table[(GOOD, CONDITIONAL)]
    cov_bad = n_bad - table[(BAD, CONDITIONAL)]
    sens_cov = ratio(table[(GOOD, INVEST)], cov_good)
    spec_cov = ratio(table[(BAD, DNI)], cov_bad)
    # 2) Conditional = BAD: everything that is not Invest counts as "do not invest"
    sens_strict = ratio(table[(GOOD, INVEST)], n_good)
    spec_strict = ratio(table[(BAD, DNI)] + table[(BAD, CONDITIONAL)], n_bad)
    return {
        "n": n, "n_good": n_good, "n_bad": n_bad, "table": table,
        "coverage": ratio(n - cond, n), "conditional_share": ratio(cond, n),
        "sens_cov": sens_cov, "spec_cov": spec_cov, "ba_cov": (sens_cov + spec_cov) / 2,
        "sens_strict": sens_strict, "spec_strict": spec_strict,
        "ba_strict": (sens_strict + spec_strict) / 2,
        "sens_strict_ci": wilson(table[(GOOD, INVEST)], n_good),
        "spec_strict_ci": wilson(table[(BAD, DNI)] + table[(BAD, CONDITIONAL)], n_bad),
        "right": sum(outcome(l, r.verdict) == "right" for r, l in zip(results, labels)),
        "wrong": sum(outcome(l, r.verdict) == "wrong" for r, l in zip(results, labels)),
    }


# ---------------------------------------------------------------------------
# Items: does the colour separate GOOD from BAD
# ---------------------------------------------------------------------------
def item_discrimination(cfg: Config, cases: list[dict], item_ids) -> list[dict]:
    rows = []
    for item_id in item_ids:
        item = cfg.items[item_id]
        counts = {lab: {c: 0 for c in (GREEN, YELLOW, RED, UNKNOWN)} for lab in (GOOD, BAD)}
        for case in cases:
            counts[case["label"]][item_color(item, validate_facts(cfg, case["facts"]))] += 1
        n_good = sum(counts[GOOD].values())
        n_bad = sum(counts[BAD].values())
        g_good, g_bad = counts[GOOD][GREEN], counts[BAD][GREEN]
        r_good, r_bad = counts[GOOD][RED], counts[BAD][RED]
        _, p_green = fisher_exact([[g_good, n_good - g_good], [g_bad, n_bad - g_bad]])
        can_red = "red" in item
        p_red = (fisher_exact([[r_good, n_good - r_good], [r_bad, n_bad - r_bad]])[1]
                 if can_red else float("nan"))
        w = cfg.weights
        mean_good = (w["green"] * g_good - w["red"] * r_good) / n_good if n_good else float("nan")
        mean_bad = (w["green"] * g_bad - w["red"] * r_bad) / n_bad if n_bad else float("nan")
        known = sum(v for lab in counts for c, v in counts[lab].items() if c != UNKNOWN)
        rows.append({
            "item": item_id, "name": item["name"], "set": item["set"], "can_red": can_red,
            "counts": counts, "n_good": n_good, "n_bad": n_bad,
            "green_good": g_good / n_good if n_good else float("nan"),
            "green_bad": g_bad / n_bad if n_bad else float("nan"),
            "red_good": r_good / n_good if n_good else float("nan"),
            "red_bad": r_bad / n_bad if n_bad else float("nan"),
            "p_green": p_green, "p_red": p_red,
            "mean_good": mean_good, "mean_bad": mean_bad,
            "separation": mean_good - mean_bad,
            "known_share": known / (n_good + n_bad) if (n_good + n_bad) else float("nan"),
        })
    return rows


def rule_stats(cfg: Config, cases: list[dict], variant) -> list[dict]:
    results = run(cfg, cases, variant)
    rows = []
    for rule in cfg.rules:
        fired_good = sum(rule["id"] in r.fired for r, c in zip(results, cases) if c["label"] == GOOD)
        fired_bad = sum(rule["id"] in r.fired for r, c in zip(results, cases) if c["label"] == BAD)
        if fired_good + fired_bad:
            rows.append({"rule": rule["id"], "name": rule["name"], "tier": rule["tier"],
                         "basis": rule["basis"], "fired_good": fired_good, "fired_bad": fired_bad})
    return rows


# ---------------------------------------------------------------------------
# Candidate: effect on every case
# ---------------------------------------------------------------------------
EFFECT_LABEL = {
    ("wrong", "right"): "fixed",
    ("right", "wrong"): "broke",
    ("abstain", "right"): "abstention removed, correctly",
    ("abstain", "wrong"): "abstention removed, wrongly",
    ("wrong", "abstain"): "wrong → abstention",
    ("right", "abstain"): "right → abstention",
}


def candidate_impact(cfg: Config, cases: list[dict], base_variant, new_variant,
                     thresholds_new: dict | None = None) -> dict:
    base_ids = cfg.variant_items(base_variant)
    new_ids = cfg.variant_items(new_variant)
    added = [i for i in new_ids if i not in base_ids]
    removed = [i for i in base_ids if i not in new_ids]
    rows = []
    for case in cases:
        before = score(cfg, case["facts"], base_variant)
        after = score(cfg, case["facts"], new_variant, thresholds=thresholds_new)
        o_before = outcome(case["label"], before.verdict)
        o_after = outcome(case["label"], after.verdict)
        rows.append({
            "id": case["id"], "name": case.get("name", ""), "label": case["label"],
            "added_colors": {i: after.colors[i] for i in added},
            "removed_colors": {i: before.colors[i] for i in removed},
            "d_pos": after.pos - before.pos, "d_neg": after.neg - before.neg,
            "diff_before": before.diff, "diff_after": after.diff,
            "verdict_before": before.verdict, "verdict_after": after.verdict,
            "effect": EFFECT_LABEL.get((o_before, o_after), "verdict unchanged"),
            "changed": before.verdict != after.verdict,
        })
    labels = [c["label"] for c in cases]
    m_before = metrics(run(cfg, cases, base_variant), labels)
    m_after = metrics(run(cfg, cases, new_variant, thresholds=thresholds_new), labels)
    tally: dict = {}
    for row in rows:
        tally[row["effect"]] = tally.get(row["effect"], 0) + 1
    return {"added": added, "removed": removed, "rows": rows, "tally": tally,
            "before": m_before, "after": m_after, "thresholds_new": thresholds_new}


# ---------------------------------------------------------------------------
# Ablation
# ---------------------------------------------------------------------------
def ablation(cfg: Config, cases: list[dict], variant) -> list[dict]:
    labels = [c["label"] for c in cases]
    base = run(cfg, cases, variant)
    m_base = metrics(base, labels)
    fired_any = {rid for r in base for rid in r.fired}
    targets = [("item", i) for i in cfg.variant_items(variant)]
    targets += [("rule", r["id"]) for r in cfg.rules if r["id"] in fired_any]
    rows = []
    for kind, ident in targets:
        kw = {"disabled_items": [ident]} if kind == "item" else {"disabled_rules": [ident]}
        res = run(cfg, cases, variant, **kw)
        m = metrics(res, labels)
        flips = []
        for case, a, b in zip(cases, base, res):
            if a.verdict != b.verdict:
                oa, ob = outcome(case["label"], a.verdict), outcome(case["label"], b.verdict)
                flips.append({"id": case["id"], "label": case["label"], "from": a.verdict,
                              "to": b.verdict,
                              "effect": EFFECT_LABEL.get((oa, ob), "verdict unchanged")})
        rows.append({"kind": kind, "id": ident, "flips": flips,
                     "d_ba_strict": m["ba_strict"] - m_base["ba_strict"],
                     "d_coverage": m["coverage"] - m_base["coverage"],
                     "d_right": m["right"] - m_base["right"],
                     "d_wrong": m["wrong"] - m_base["wrong"]})
    return rows


# ---------------------------------------------------------------------------
# Report in Markdown and CSV
# ---------------------------------------------------------------------------
def _pct(x: float) -> str:
    return "n/a" if x != x else f"{100 * x:.0f}%"


def _ci(ci) -> str:
    return f"{_pct(ci[0])}–{_pct(ci[1])}"


def _colors_row(counts: dict) -> str:
    return " / ".join(str(counts[c]) for c in (GREEN, YELLOW, RED, UNKNOWN))


def render_report(cfg: Config, cases: list[dict], out_dir: str | Path, *, title: str,
                  base_variant: str | None = None, synthetic: bool = False) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_variant = base_variant or cfg.default_variant
    if not cases:
        raise ValueError("The case list is empty")
    labels = [c["label"] for c in cases]
    L: list[str] = [f"# {title}", ""]
    if synthetic:
        L += ["> **These are synthetic cases for checking the bench. The numbers below say nothing "
              "about the quality of the scorecard.**", ""]
    n_good, n_bad = labels.count(GOOD), labels.count(BAD)
    L += [f"Cases: {len(cases)} ({n_good} GOOD, {n_bad} BAD). "
          f"An 'always BAD' system gives accuracy {_pct(n_bad / len(cases))} and balanced accuracy 50%.",
          "", "## 1. Scorecard variants", "",
          "Thresholds are the same for all variants (from `benchmarks.yaml`). 'Strict' means "
          "Conditional counts as 'do not invest'.", "",
          "| Variant | Items | Invest (G/B) | Conditional (G/B) | Do Not Invest (G/B) | Coverage | "
          "Bal. accuracy on covered | Bal. accuracy strict | Sensitivity, 95% CI | Specificity, 95% CI |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    per_variant = {}
    for variant in cfg.variants:
        res = run(cfg, cases, variant)
        m = metrics(res, labels)
        per_variant[variant] = (res, m)
        t = m["table"]
        L.append(
            f"| {variant} | {len(cfg.variants[variant])} | {t[(GOOD, INVEST)]}/{t[(BAD, INVEST)]} | "
            f"{t[(GOOD, CONDITIONAL)]}/{t[(BAD, CONDITIONAL)]} | {t[(GOOD, DNI)]}/{t[(BAD, DNI)]} | "
            f"{_pct(m['coverage'])} | {_pct(m['ba_cov'])} | {_pct(m['ba_strict'])} | "
            f"{_pct(m['sens_strict'])} ({_ci(m['sens_strict_ci'])}) | "
            f"{_pct(m['spec_strict'])} ({_ci(m['spec_strict_ci'])}) |")

    # --- thresholds aligned by Invest share ---
    L += ["", "### The same variants with aligned thresholds", "",
          "An item that can only be green raises the Invest share by itself. To keep the comparison "
          "fair, for each variant the Invest threshold was fitted by the state-space sweep so that "
          "the Invest share is as close to the baseline as possible. Case labels take no part in this fit.",
          "", "| Variant | Invest threshold | Invest (G/B) | Conditional (G/B) | Do Not Invest (G/B) | "
          "Bal. accuracy strict |", "| --- | --- | --- | --- | --- | --- |"]
    matched = {}
    for variant in cfg.variants:
        thr = space.matched_thresholds(cfg, variant, base_variant)
        matched[variant] = thr
        m = metrics(run(cfg, cases, variant, thresholds=thr), labels)
        t = m["table"]
        L.append(f"| {variant} | {thr['invest_margin']} | {t[(GOOD, INVEST)]}/{t[(BAD, INVEST)]} | "
                 f"{t[(GOOD, CONDITIONAL)]}/{t[(BAD, CONDITIONAL)]} | {t[(GOOD, DNI)]}/{t[(BAD, DNI)]} | "
                 f"{_pct(m['ba_strict'])} |")

    # --- items ---
    all_items = list(cfg.items)
    L += ["", "## 2. Does the item separate successful cases from unsuccessful ones", "",
          "Colours are shown as green / yellow / red / unknown. 'Separation' = the item's mean contribution "
          "to the score in GOOD minus in BAD (green +1, red −2). p by Fisher's exact test "
          "(green vs not green); on such a sample it is a guide, not proof.", "",
          "| Item | Type | GOOD | BAD | Green in GOOD | Green in BAD | Red in GOOD | "
          "Red in BAD | Separation | p (green) | Known |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    disc = item_discrimination(cfg, cases, all_items)
    for d in disc:
        kind = "base" if d["set"] == "base" else "for comparison"
        red_good = _pct(d["red_good"]) if d["can_red"] else "—"
        red_bad = _pct(d["red_bad"]) if d["can_red"] else "—"
        L.append(f"| {d['name']} | {kind} | {_colors_row(d['counts'][GOOD])} | "
                 f"{_colors_row(d['counts'][BAD])} | {_pct(d['green_good'])} | {_pct(d['green_bad'])} | "
                 f"{red_good} | {red_bad} | {d['separation']:+.2f} | {d['p_green']:.2f} | "
                 f"{_pct(d['known_share'])} |")

    # --- candidates on every case ---
    L += ["", "## 3. Every candidate on every case", ""]
    for variant in cfg.variants:
        if variant == base_variant:
            continue
        for thr_name, thr in (("unchanged thresholds", None), ("aligned thresholds", matched[variant])):
            if thr is not None and thr["invest_margin"] == cfg.thresholds["invest_margin"]:
                continue
            imp = candidate_impact(cfg, cases, base_variant, variant, thr)
            added = ", ".join(cfg.items[i]["name"] for i in imp["added"])
            removed = ", ".join(cfg.items[i]["name"] for i in imp["removed"])
            L += [f"### {variant}, {thr_name}", "",
                  f"Added: {added}." + (f" Removed: {removed}." if removed else ""), "",
                  f"Balanced accuracy strict: {_pct(imp['before']['ba_strict'])} → "
                  f"{_pct(imp['after']['ba_strict'])}. Coverage: {_pct(imp['before']['coverage'])} → "
                  f"{_pct(imp['after']['coverage'])}. Summary of changes: "
                  + ("; ".join(f"{k}: {v}" for k, v in sorted(imp["tally"].items())) or "none") + ".",
                  "", "| Case | Label | Colour of new items | Δ pluses | Δ minuses | Score before → after | "
                  "Verdict before → after | Effect |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
            for r in imp["rows"]:
                colors = ", ".join(f"{cfg.items[i]['name']}: {COLOR_LABEL[c]}"
                                   for i, c in r["added_colors"].items())
                arrow = (f"{r['verdict_before']} → {r['verdict_after']}" if r["changed"]
                         else r["verdict_before"])
                L.append(f"| {r['id']} {r['name']} | {r['label']} | {colors} | {r['d_pos']:+d} | "
                         f"{r['d_neg']:+d} | {r['diff_before']:+d} → {r['diff_after']:+d} | {arrow} | "
                         f"{r['effect']} |")
            L.append("")

    # --- ablation ---
    L += ["## 4. Ablation: what changes without one item or rule", "",
          f"Variant: {base_variant}. Rows with no verdict change are grouped at the end.", "",
          "| Switched off | Changed verdicts | Δ right | Δ wrong | Δ bal. accuracy strict | Cases |",
          "| --- | --- | --- | --- | --- | --- |"]
    inert = []
    for a in ablation(cfg, cases, base_variant):
        name = cfg.items[a["id"]]["name"] if a["kind"] == "item" else next(
            r["name"] for r in cfg.rules if r["id"] == a["id"])
        label = ("Item: " if a["kind"] == "item" else "Rule: ") + name
        if not a["flips"]:
            inert.append(label)
            continue
        detail = "; ".join(f"{f['id']} ({f['label']}): {f['from']} → {f['to']}" for f in a["flips"])
        L.append(f"| {label} | {len(a['flips'])} | {a['d_right']:+d} | {a['d_wrong']:+d} | "
                 f"{100 * a['d_ba_strict']:+.0f} pp | {detail} |")
    L += ["", "Do not change any verdict: " + ("; ".join(inert) if inert else "none") + ".", ""]

    # --- rules ---
    L += ["## 5. Rules fired", "",
          "| Rule | Tier | Basis | In GOOD | In BAD |", "| --- | --- | --- | --- | --- |"]
    for r in rule_stats(cfg, cases, base_variant):
        L.append(f"| {r['name']} | {r['tier']} | {r['basis']} | {r['fired_good']} | {r['fired_bad']} |")

    # --- errors ---
    res, _ = per_variant[base_variant]
    L += ["", f"## 6. Wrong verdicts and abstentions of the base variant ({base_variant})", "",
          "| Case | Label | Verdict | Type | Pluses | Minuses | Reason | What fired |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for case, r in zip(cases, res):
        kind = {"wrong": "wrong", "abstain": "abstention"}.get(outcome(case["label"], r.verdict))
        if kind is None:
            continue
        what = ", ".join(r.kills + [c for c, _ in r.counted]) or "—"
        L.append(f"| {case['id']} {case.get('name', '')} | {case['label']} | {r.verdict} | {kind} | "
                 f"{r.pos} | {r.neg} | {r.reason} | {what} |")

    path = out_dir / "benchmark_report.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")

    with (out_dir / "benchmark_cases.csv").open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["case", "name", "label", "variant", "verdict", "pos", "neg", "diff", "kills",
                     "counted", "suppressed"] + all_items)
        for variant, (results, _) in per_variant.items():
            for case, r in zip(cases, results):
                wr.writerow([case["id"], case.get("name", ""), case["label"], variant, r.verdict,
                             r.pos, r.neg, r.diff, "|".join(r.kills),
                             "|".join(f"{c}:{p}" for c, p in r.counted), "|".join(r.suppressed)]
                            + [r.colors.get(i, "") for i in all_items])
    return path

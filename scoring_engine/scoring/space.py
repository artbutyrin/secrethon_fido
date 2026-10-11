"""State-space sweep of the scorecard: what share of verdicts the arithmetic gives.

Questions this module answers:
  1. What is the Conditional share under the current thresholds, and how does it depend on assumptions?
  2. What happens to verdicts when items are added to the scorecard?
  3. Which thresholds keep Conditional within given bounds?

Item state: G (green, +1; strong green +2), N (yellow or unknown, 0), R (red, 2 minuses).
The sweep also tracks science pluses and mechanism evidence, because Invest depends on them.
Minuses from rules (after clusters) are given by a separate distribution.
Kill rules are not modelled here: they always give Do Not Invest, so the shares
below concern only cases without a kill rule.

Model limitation: items are assumed independent. In reality they are linked
(for example, many approvals in an indication also lower unmet need),
so the shares here are a guide for comparing thresholds, not a forecast.
"""
from __future__ import annotations

from itertools import product

from .engine import CONDITIONAL, DNI, INVEST, Config, decide

VERDICTS = (INVEST, CONDITIONAL, DNI)

# Distributions of minuses from rules (0, 1, 2, 3, 4). The last value is modelled as
# exactly 4 minuses, so the threshold sweep makes sense only for neg_dni <= 4.
# These are assumed scenarios, not measured frequencies: they can only be measured on cases.
MINUS_SCENARIOS = {
    "few minuses": (0.60, 0.25, 0.10, 0.03, 0.02),
    "many minuses": (0.30, 0.25, 0.25, 0.10, 0.10),
}
P_GREEN_GRID = (0.2, 0.3, 0.4, 0.5)
P_RED_GRID = (0.05, 0.15)


def item_shapes(cfg: Config, variant) -> list[dict]:
    """What the sweep knows about an item: whether it can be red, whether it counts toward science pluses and
    mechanism evidence, and what share of its greens are "strong" (assumption strong_share_assumption)."""
    out = []
    for i in cfg.variant_items(variant):
        item = cfg.items[i]
        share = item.get("strong_share_assumption", 0.0) if "strong_green" in item else 0.0
        out.append({"id": i, "can_red": "red" in item, "science": item["axis"] == "science",
                    "mechanism": bool(item.get("mechanism_evidence")), "strong_share": float(share)})
    return out


def state_distribution(cfg: Config, shapes, p_green: float | None, p_red: float | None) -> dict:
    """Distribution of (pluses, number of reds, greens with mechanism evidence, science pluses).

    p_green=None means a uniform sweep of states: every item colour is equally likely.
    A strong green gives weights.green_strong pluses instead of weights.green.
    """
    w = cfg.weights
    dist = {(0, 0, 0, 0): 1.0}
    for sh in shapes:
        if p_green is None:
            pg, pr = (1 / 3, 1 / 3) if sh["can_red"] else (1 / 2, 0.0)
        else:
            pg, pr = p_green, (p_red if sh["can_red"] else 0.0)
        pn = 1.0 - pg - pr
        steps = [(0, 0, pn), (0, 1, pr),
                 (w["green"], 0, pg * (1 - sh["strong_share"])),
                 (w["green_strong"], 0, pg * sh["strong_share"])]
        nxt: dict = {}
        for (pos, reds, mech, sci), p in dist.items():
            for pts, dr, q in steps:
                if not q:
                    continue
                key = (pos + pts, reds + dr, mech + (1 if pts and sh["mechanism"] else 0),
                       sci + (pts if sh["science"] else 0))
                nxt[key] = nxt.get(key, 0.0) + p * q
        dist = nxt
    return dist


def verdict_shares(cfg: Config, variant, *, rule_minus: int = 0, p_green=None, p_red=None,
                   thresholds: dict | None = None) -> dict:
    """Verdict shares for a fixed number of minuses from rules."""
    thr = {**cfg.thresholds, **(thresholds or {})}
    w = cfg.weights
    shares = dict.fromkeys(VERDICTS, 0.0)
    dist = state_distribution(cfg, item_shapes(cfg, variant), p_green, p_red)
    for (pos, reds, mech, sci), p in dist.items():
        verdict, _ = decide(pos, w["red"] * reds + rule_minus, False, thr, pos, mech, sci)
        shares[verdict] += p
    return shares


def mixed_shares(cfg: Config, variant, minus_dist, *, p_green=None, p_red=None,
                 thresholds: dict | None = None) -> dict:
    """Verdict shares averaged over the distribution of minuses from rules."""
    total = dict.fromkeys(VERDICTS, 0.0)
    for m, pm in enumerate(minus_dist):
        part = verdict_shares(cfg, variant, rule_minus=m, p_green=p_green, p_red=p_red,
                              thresholds=thresholds)
        for v in VERDICTS:
            total[v] += pm * part[v]
    return total


def sensitivity_grid(cfg: Config, variant, thresholds: dict | None = None) -> list[dict]:
    """Verdict shares on a grid of assumptions (green share, red share, minus scenario)."""
    rows = []
    for (name, dist), pg, pr in product(MINUS_SCENARIOS.items(), P_GREEN_GRID, P_RED_GRID):
        shares = mixed_shares(cfg, variant, dist, p_green=pg, p_red=pr, thresholds=thresholds)
        rows.append({"minus": name, "p_green": pg, "p_red": pr, **shares})
    return rows


def conditional_range(cfg: Config, variant, thresholds: dict | None = None) -> tuple[float, float]:
    values = [row[CONDITIONAL] for row in sensitivity_grid(cfg, variant, thresholds)]
    return min(values), max(values)


def invest_range(cfg: Config, variant, thresholds: dict | None = None) -> tuple[float, float]:
    values = [row[INVEST] for row in sensitivity_grid(cfg, variant, thresholds)]
    return min(values), max(values)


def threshold_sweep(cfg: Config, variant, *, neg_dni=(3, 4), invest_margin=(1, 2, 3, 4),
                    dni_margin=(-1, 0, 1, 2)) -> list[dict]:
    """Threshold sweep. For each triple: the Conditional and Invest range on the assumption grid.

    The minimum greens for Conditional moves together with the Invest threshold, as in matched_thresholds.
    """
    if max(neg_dni) > 4:
        raise ValueError("Minus scenarios model at most 4 minuses from rules")
    rows = []
    for nd, im, dm in product(neg_dni, invest_margin, dni_margin):
        if dm >= im:
            continue
        thr = {"neg_dni": nd, "invest_margin": im, "dni_margin": dm, "min_pos_conditional": im}
        c_lo, c_hi = conditional_range(cfg, variant, thr)
        i_lo, i_hi = invest_range(cfg, variant, thr)
        rows.append({**thr, "band": im - dm - 1, "cond_min": c_lo, "cond_max": c_hi,
                     "invest_min": i_lo, "invest_max": i_hi})
    return rows


def marginal_effect_of_item(cfg: Config, base_variant, extra_item: str, *, p_green: float,
                            p_red: float, minus_dist) -> dict:
    """How one added item shifts verdict shares under unchanged thresholds."""
    before = mixed_shares(cfg, base_variant, minus_dist, p_green=p_green, p_red=p_red)
    items = cfg.variant_items(base_variant) + [extra_item]
    after = mixed_shares(cfg, items, minus_dist, p_green=p_green, p_red=p_red)
    return {v: after[v] - before[v] for v in VERDICTS}


def matched_thresholds(cfg: Config, variant, reference=None, max_margin: int = 8) -> dict:
    """Thresholds for a variant at which the Invest share is closest to the baseline.

    Case labels are not used: only Invest shares on the assumption grid are compared.
    The Conditional band stays one score value wide, and
    the minimum greens for Conditional moves together with the Invest threshold.
    """
    base = [row[INVEST] for row in sensitivity_grid(cfg, reference or cfg.default_variant)]
    best, best_gap = None, None
    for margin in range(1, max_margin + 1):
        thr = {**cfg.thresholds, "invest_margin": margin, "dni_margin": margin - 2,
               "min_pos_conditional": margin}
        new = [row[INVEST] for row in sensitivity_grid(cfg, variant, thr)]
        gap = sum(abs(a - b) for a, b in zip(new, base)) / len(base)
        if best_gap is None or gap < best_gap - 1e-12:
            best, best_gap = thr, gap
    return best

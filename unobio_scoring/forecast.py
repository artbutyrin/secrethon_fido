"""Forecast for assets that have no sales yet: where price, share and timing come from, and what one must believe.

1. Price ladder: same mechanism approved elsewhere (CMS) > drugs for the same disease (CMS) > reference class [A];
   a value-based ceiling (WTP per QALY x QALY gain) caps it. The rung sets the price uncertainty in the Monte Carlo.
2. Peak share: order of entry x differentiation (best in class, claimed, convenience, cost, none) x late-entry penalty.
3. Time to peak by segment (rare, oncology, chronic, acute).
4. "What you have to believe": tornado of the drivers, break-even value of each driver, the peak sales a valuation
   needs, and bear / base / bull scenarios with the reason for each.
Every value records how it was obtained (`basis`), so the report can tag it.
"""
from __future__ import annotations

import math

from . import constants as C


def segment(facts: dict, mclass: str) -> str:
    if facts.get("acute_indication") is True:
        return "acute"
    if facts.get("oncology") is True:
        return "oncology"
    if facts.get("rare_disease") is True:
        return "rare"
    return "chronic_small" if mclass in ("small_molecule", "peptide") else "chronic_biologic"


def price_ladder(facts: dict, m: dict, seg: str) -> dict:
    """-> {price, range, rung, sigma, basis, assumed}"""
    if "annual_net_price_usd" in m:
        p = m["annual_net_price_usd"]
        rng = m.get("price_range") or [p, p]
        return {"price": p, "range": rng, "rung": "user", "sigma": C.PRICE_SIGMA["user"],
                "basis": m.get("price_basis", "entered or sourced price"),
                "assumed": "annual_net_price_usd" in (m.get("assumed") or [])}
    an = m.get("price_analogues") or {}
    for rung in ("same_moa", "same_indication"):
        vals = sorted(v for v in an.get(rung) or [] if v and v > 0)
        if vals:
            mid = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2
            # 2.2: only same-mechanism analogues count as a sourced price for this drug; drugs of OTHER mechanisms
            # for the same disease (possibly cheap generics) are a reference, shown but not used in the verdict
            return {"price": mid, "range": [vals[0], vals[-1]], "rung": rung, "sigma": C.PRICE_SIGMA[rung],
                    "basis": f"median of {len(vals)} {rung.replace('_', '-')} analogue(s), CMS"
                             + ("" if rung == "same_moa" else " [A: other mechanisms]"),
                    "assumed": rung != "same_moa"}
    lo, mid, hi = C.REFERENCE_PRICE[seg]
    return {"price": mid, "range": [lo, hi], "rung": "reference", "sigma": C.PRICE_SIGMA["reference"],
            "basis": f"reference class '{seg}' (no analogue price) [A]", "assumed": True}


def value_ceiling(m: dict) -> float | None:
    q = m.get("qaly_gain_per_year")
    return C.WTP_PER_QALY * q if q else None


def differentiation_class(facts: dict) -> str:
    claim, ev = facts.get("differentiation_claim"), facts.get("differentiation_evidence")
    if ev is False or claim == "none":
        return "undifferentiated"
    if claim in ("efficacy", "safety"):
        return "best_in_class" if ev is True else "claimed_superior"
    if claim == "convenience":
        return "convenience"
    if claim in ("structural_cost", "price_only"):
        return "cost"
    return "unknown"


def share_model(facts: dict, m: dict, order_share: float) -> dict:
    first = m.get("entry_position", 1) == 1
    cls = "first_in_class" if first else differentiation_class(facts)
    mult = 1.0 if first else C.SHARE_MULT[cls]
    late = 1.0
    y = facts.get("years_behind_first_in_class")
    if not first and y is not None and y > 2:
        late = max(C.LATE_ENTRY_FLOOR, 1 - C.LATE_ENTRY_PENALTY_PER_YEAR * (y - 2))
    share = min(C.MAX_PEAK_SHARE, m.get("class_share", 0.5) * order_share * mult * late)
    return {"peak_share": share, "class": cls, "basis": f"class share {m.get('class_share', 0.5)} x order-of-entry "
            f"{order_share:.2f} x differentiation '{cls}' {mult} x late entry {late:.2f} [A]",
            "price_mult": C.COST_DIFF_PRICE_MULT if cls == "cost" else 1.0}


# --- what you have to believe ---------------------------------------------------------------------------------
DRIVERS = ("patients", "price", "share", "p_success", "cost", "time_to_peak")
QUESTIONS = {
    "patients": "How many patients is the drug for (diagnosed, eligible subgroup, line of therapy)? The forecast is "
                "most sensitive to this number.",
    "price": "Which drugs are the price analogues, and what net price can this asset command given its benefit?",
    "share": "What peak share is realistic against the drugs already used, and what head-to-head or real-world data "
             "would win it?",
    "p_success": "What evidence de-risks the next phase (human genetics, biomarker, prior efficacy in humans)?",
    "cost": "What is the development budget to approval (trial sizes, CMC), and can it be narrowed?",
    "time_to_peak": "How fast will uptake be (diagnosis, access, specialist vs primary care)?",
}


def _mults(name: str, value: float) -> dict:
    return {"patients": {"patient_mult": value}, "price": {"price_mult": value}, "share": {"share_mult": value},
            "p_success": {"pos_mult": value}, "cost": {"cost_mult": value}, "time_to_peak": {"ttp_add": value}}[name]


def sensitivity(rnpv, facts, m, plan) -> dict:
    """Tornado (P10 / P90 of each driver alone), break-evens, scenarios."""
    base = rnpv(facts, m, plan)["rnpv_m"]
    sig = m["sigma"]
    ranges = {"patients": (math.exp(-C.Z90 * sig["patients"]), math.exp(C.Z90 * sig["patients"])),
              "price": (math.exp(-C.Z90 * sig["price"]), math.exp(C.Z90 * sig["price"])),
              "share": (math.exp(-C.Z90 * sig["share"]), math.exp(C.Z90 * sig["share"])),
              "p_success": (0.7, 1.3), "cost": (1.5, 0.7), "time_to_peak": (2, -2)}
    tornado = []
    for d in DRIVERS:
        lo_v = rnpv(facts, m, plan, **_mults(d, ranges[d][0]))["rnpv_m"]
        hi_v = rnpv(facts, m, plan, **_mults(d, ranges[d][1]))["rnpv_m"]
        tornado.append({"driver": d, "low_rnpv_m": lo_v, "high_rnpv_m": hi_v, "swing_m": abs(hi_v - lo_v),
                        "crosses_zero": min(lo_v, hi_v) < 0 < max(lo_v, hi_v)})
    tornado.sort(key=lambda x: -x["swing_m"])

    def solve(d, lo=0.0, hi=100.0):
        f = lambda x: rnpv(facts, m, plan, **_mults(d, x))["rnpv_m"]  # noqa: E731
        if f(hi) < 0:
            return None
        if f(lo) >= 0:
            return lo
        for _ in range(50):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if f(mid) >= 0 else (mid, hi)
        return hi

    be = {}
    x = solve("patients")
    be["patients"] = None if x is None else round(m["us_patients"] * m["eligible_share"] * x)
    x = solve("price")
    be["annual_net_price_usd"] = None if x is None else m["annual_net_price_usd"] * x
    x = solve("share", 0.0, C.MAX_PEAK_SHARE / max(m["peak_share"], 1e-9))
    be["peak_share"] = None if x is None else m["peak_share"] * x
    pos = rnpv(facts, m, plan)["pos"]
    x = solve("p_success", 0.0, 1 / max(pos, 1e-9))
    be["p_approval"] = None if x is None else pos * x

    # scenarios = actual Monte Carlo draws at P10 / P50 / P90 of rNPV, with the input values that produced them
    # (not all drivers at their extremes at once: that point lies outside any plausible distribution, review F01)
    import random
    rng = random.Random(C.MC_SEED + 1)
    draws = []
    for _ in range(600):
        mult = {k: math.exp(rng.gauss(-sig[k] ** 2 / 2, sig[k])) for k in ("patients", "price", "share", "cost")}
        r = rnpv(facts, m, plan, patient_mult=mult["patients"], price_mult=mult["price"], share_mult=mult["share"],
                 cost_mult=mult["cost"])
        draws.append((r["rnpv_m"], r["peak_us_m"], mult))
    draws.sort(key=lambda x: x[0])
    scen = {}
    band = max(5, len(draws) // 30)            # draws on each side of the quantile
    for name, q in (("bear", 0.10), ("median", 0.50), ("bull", 0.90)):
        i = int(q * (len(draws) - 1))
        v, peak, _ = draws[i]
        near = draws[max(0, i - band): i + band + 1]
        # 2.2: one draw's multipliers are an arbitrary example (its neighbours reach the same rNPV in very different
        # ways); the geometric mean over the neighbouring draws says what typically produces this outcome
        mult = {k: math.exp(sum(math.log(d[2][k]) for d in near) / len(near))
                for k in ("patients", "price", "share", "cost")}
        why = ", ".join(f"{k} x{mult[k]:.2f}" for k in ("patients", "price", "share", "cost"))
        scen[name] = {"rnpv_m": v, "peak_us_m": peak, "multipliers": mult,
                      "why": f"Monte Carlo P{int(q * 100)}; typical of the {len(near)} nearest draws: {why}"}
    return {"base_rnpv_m": base, "tornado": tornado, "break_even": be, "scenarios": scen}


def required_peak_for_value(rnpv, facts, m, plan, value_m: float) -> float | None:
    """Peak US sales at which the rNPV equals a valuation (e.g. the round's post-money)."""
    lo, hi = 0.0, 1000.0
    f = lambda x: rnpv(facts, m, plan, patient_mult=x)  # noqa: E731
    if f(hi)["rnpv_m"] < value_m:
        return None
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if f(mid)["rnpv_m"] >= value_m else (mid, hi)
    return f(hi)["peak_us_m"]


def driver_questions(sens: dict, limit: int = 2) -> list[dict]:
    out = []
    for t in sens["tornado"][:limit]:
        out.append({"question": QUESTIONS[t["driver"]], "facts": [], "sources": [], "critical": t["crosses_zero"],
                    "needs": ["company data / market research"], "economic_driver": t["driver"]})
    return out

"""Underwriting: patient funnel -> peak sales -> decision-tree rNPV -> Monte Carlo -> investor and licensing view.

Money is in USD million unless the name says otherwise. Every result carries the assumptions it used, so the report
can tag them [A]. The module only produces the economic facts (economics_negative, economics_weak,
required_price_unrealistic); it never reads LLM output.

`market` keys (all optional except a price source and the patient count):
  us_patients            people with the disease in the US who could be treated each year
  eligible_share         share of them the drug is for (genetic subgroup, line of therapy); default 1.0
  diagnosis_rate         share diagnosed (default 1.0)
  treatment_rate         share of diagnosed who get drug treatment (default 1.0)
  peak_share             peak share of treated patients; if absent: order-of-entry share x class_share
  entry_position         1 = first of the mechanism; default = approved_same_moa_count + 1
  n_entrants             same-mechanism entrants at peak; default = approved + ph3 same-mechanism + 1
  class_share            share of treated patients that the mechanism class wins (default 0.5)
  annual_net_price_usd   net price per patient-year; if absent: price ladder (forecast.py)
  price_analogues        {"same_moa": [prices], "same_indication": [prices]} from CMS (ladder rungs 1-2)
  price_range            [low, high] for an entered price
  us_patients_range      [low, high]: sets the patient uncertainty in the Monte Carlo
  qaly_gain_per_year     health gain per patient-year: value-based price ceiling = WTP x gain
  segment                rare | oncology | chronic_biologic | chronic_small | acute (default from facts)
  price_ceiling_usd      realistic maximum price (sets required_price_unrealistic)
  compliance, years_to_peak, ex_us_multiplier, medicare_share, exclusivity_years_after_launch,
  discount_rate, cost_case ("base" | "worse"), phase_success (override {"ph1":..,"ph2":..,"ph3":..,"filed":..})
  assumed                list of input names that are assumptions, not sourced (then no verdict effect)
`round_terms`: pre_money_m, investment_m, dilution_to_exit (default 0.4), cash_m (company cash -> runway_short)
`license_terms`: upfront_m, milestones_m {"ph2": x, "ph3": y, "filed": z, "approval": w}, royalty_pct
"""
from __future__ import annotations

import math
import random
import statistics
from typing import Any

from . import constants as C
from . import forecast as F

MODALITY_CLASS = {"small_molecule": "small_molecule", "antibody": "antibody_like", "adc": "antibody_like",
                  "bispecific": "antibody_like", "protein": "antibody_like", "peptide": "peptide", "rna": "nucleic_acid",
                  "gene": "gene_therapy", "cell": "cell_therapy", "radioligand": "radioligand", "vaccine": "vaccine",
                  "other": "other"}

STAGES = ["preclinical", "ph1", "ph2", "ph3", "filed"]


class EconomicsUnavailable(ValueError):
    pass


def _logit(p):
    return math.log(p / (1 - p))


def _expit(x):
    return 1 / (1 + math.exp(-x))


def phase_plan(facts: dict, market: dict) -> list[dict]:
    phase = facts.get("phase")
    if phase not in STAGES:
        raise EconomicsUnavailable("phase unknown: cannot build a development plan")
    area = "oncology" if facts.get("oncology") is True else "all"
    rates = dict(C.BIO_SUCCESS[area])
    rates.update(market.get("phase_success") or {})
    rs = C.GENETIC_RS.get(facts.get("genetic_support", "no_data"), 1.0)
    costs = C.COST_M[market.get("cost_case", "base")]
    plan, t = [], 0.0
    for st in STAGES[STAGES.index(phase):]:
        p = C.PRECLINICAL_TO_PH1 if st == "preclinical" else rates[st]
        w = C.RS_PHASE_WEIGHTS.get(st, 0.0)
        if w and rs != 1.0:
            p = _expit(_logit(p) + w * math.log(rs))
        overhead = C.COMPANY_OVERHEAD_M_PER_YEAR * C.DURATION_Y[st] if market.get("cost_case", "base") == "base" else 0.0
        plan.append({"stage": st, "start_y": t, "years": C.DURATION_Y[st], "cost_m": costs[st] + overhead,
                     "trial_cost_m": costs[st], "overhead_m": overhead, "p_success": p})
        t += C.DURATION_Y[st]
    return plan


def _order_of_entry_share(position: int, n: int) -> float:
    n = max(n, position, 1)
    weights = [j ** C.ORDER_OF_ENTRY_EXP for j in range(1, n + 1)]
    return weights[position - 1] / sum(weights)


def _curve(year: int, years_to_peak: float) -> float:
    """Robey-shaped uptake, stretched so that peak is reached at years_to_peak."""
    x = year * len(C.LAUNCH_CURVE_ROBEY) / years_to_peak
    if x >= len(C.LAUNCH_CURVE_ROBEY):
        return 1.0
    lo = int(math.floor(x))
    a = 0.0 if lo == 0 else C.LAUNCH_CURVE_ROBEY[lo - 1]
    b = C.LAUNCH_CURVE_ROBEY[lo]
    return a + (b - a) * (x - lo)


def resolve_inputs(facts: dict, market: dict) -> dict:
    """Fill defaults; return the full assumption set (what the report shows)."""
    m = dict(market)
    mclass = MODALITY_CLASS.get(facts.get("modality", "other"), "other")
    if "us_patients" not in m:
        raise EconomicsUnavailable("market.us_patients missing")
    # 2.2: every input filled by a default is listed, so the report tags it [A default]. The funnel defaults are
    # generous (everyone diagnosed and treated); they do not decide the verdict on their own because economics can
    # only LOWER it, but the peak sales they produce must not read as a forecast.
    given = set(m)
    m.setdefault("eligible_share", 1.0)   # share of the disease the drug can treat (e.g. SOD1 carriers ~2% of ALS)
    m.setdefault("diagnosis_rate", 1.0)
    m.setdefault("treatment_rate", 1.0)
    m.setdefault("compliance", C.COMPLIANCE)
    seg = m.get("segment") or F.segment(facts, mclass)
    m["segment"] = seg
    if "years_to_peak" not in m:
        m["years_to_peak"] = C.YEARS_TO_PEAK_BY_SEGMENT.get(seg, C.YEARS_TO_PEAK)
    m.setdefault("ex_us_multiplier", C.EX_US_MULTIPLIER)
    m.setdefault("medicare_share", C.MEDICARE_SHARE_DEFAULT)
    m.setdefault("discount_rate", C.DISCOUNT_RATE)
    m.setdefault("cost_case", "base")
    m.setdefault("class_share", 0.5)
    approved = facts.get("approved_same_moa_same_modality_count", facts.get("approved_same_moa_count", 0)) or 0
    m.setdefault("entry_position", approved + 1)
    m.setdefault("n_entrants", approved + (facts.get("ph3_same_moa_count") or 0) + 1)
    m["assumed"] = list(m.get("assumed") or [])
    if "peak_share" not in m:
        sh = F.share_model(facts, m, _order_of_entry_share(m["entry_position"], m["n_entrants"]))
        m["peak_share"], m["share_class"], m["share_basis"] = sh["peak_share"], sh["class"], sh["basis"]
        price_mult = sh["price_mult"]
    else:
        m["share_class"], m["share_basis"], price_mult = None, "entered", 1.0
    lad = F.price_ladder(facts, m, seg)
    m["annual_net_price_usd"] = lad["price"] * (price_mult if lad["rung"] != "user" else 1.0)
    m["price_range"], m["price_rung"], m["price_basis"] = lad["range"], lad["rung"], lad["basis"]
    if lad["assumed"] and "annual_net_price_usd" not in m["assumed"]:
        m["assumed"].append("annual_net_price_usd")
    ceiling = F.value_ceiling(m)
    if ceiling is not None:
        m.setdefault("price_ceiling_usd", ceiling)
        if m["annual_net_price_usd"] > ceiling:
            m["annual_net_price_usd"] = ceiling
            m["price_basis"] += f"; capped at the value ceiling ${ceiling:,.0f}"
    pr = m.get("us_patients_range")
    if pr and pr[0] > 0 and pr[1] > pr[0]:
        psig = min(0.8, max(0.15, math.log(pr[1] / pr[0]) / (2 * C.Z90)))
    else:
        psig = C.PATIENT_SIGMA["assumed" if "us_patients" in m["assumed"] else "sourced"]
    m["sigma"] = {"patients": psig, "price": lad["sigma"], "share": C.MC_SIGMA["share"], "cost": C.MC_SIGMA["cost"]}
    if "exclusivity_years_after_launch" not in m:
        floor = max(facts.get("regulatory_exclusivity_years") or 0,
                    C.EXCLUSIVITY_FLOOR_Y["biologic"] if mclass in C.BIOLOGIC_CLASSES else C.EXCLUSIVITY_FLOOR_Y["nce"],
                    C.EXCLUSIVITY_FLOOR_Y["orphan"] if facts.get("rare_disease") is True else 0)
        patent = facts.get("patent_status")
        if patent in ("none", "expired"):
            m["exclusivity_years_after_launch"], basis = floor, "statutory exclusivity only (no patent)"
        else:
            m["exclusivity_years_after_launch"] = max(C.MARKET_EXCLUSIVITY_EMPIRICAL_Y, floor)
            basis = ("empirical market exclusivity of NMEs, Grabowski 2021" +
                     ("" if patent == "granted" else "; patent status unknown, a typical patent assumed [A]"))
        m["exclusivity_basis"] = basis
    m["defaulted"] = sorted(k for k in ("eligible_share", "diagnosis_rate", "treatment_rate", "compliance",
                                        "years_to_peak", "ex_us_multiplier", "medicare_share", "class_share",
                                        "discount_rate", "exclusivity_years_after_launch") if k not in given)
    m["modality_class"] = mclass
    m["cogs_share"] = C.COGS_SHARE.get(mclass, 0.10)
    m["post_loe_retention"] = C.POST_LOE_RETENTION.get(mclass, C.POST_LOE_RETENTION_DEFAULT)
    m["medicare_negotiated"] = facts.get("medicare_negotiation_exposure") is not False
    m["medicare_year"] = C.MEDICARE_NEGOTIATION_YEAR["small_molecule" if mclass == "small_molecule" else "default"]
    return m


def peak_sales_us(m: dict) -> float:
    return (m["us_patients"] * m["eligible_share"] * m["diagnosis_rate"] * m["treatment_rate"] * m["peak_share"] * m["compliance"]
            * m["annual_net_price_usd"]) / 1e6


def commercial_cashflows(m: dict, peak_us: float) -> list[dict]:
    """Success-path commercial years after launch (year 1 = first launch year)."""
    rows = []
    loe = int(m["exclusivity_years_after_launch"])
    for y in range(1, loe + C.HORIZON_AFTER_LOE_Y + 1):
        us = peak_us * _curve(y, m["years_to_peak"])
        if m["medicare_negotiated"] and y >= m["medicare_year"]:
            us *= 1 - m["medicare_share"] * C.MEDICARE_DISCOUNT
        exus = peak_us * _curve(y, m["years_to_peak"]) * m["ex_us_multiplier"]
        sales = us + exus
        if y > loe:
            sales *= m["post_loe_retention"]
        ebit = sales * (1 - m["cogs_share"] - C.SGA_SHARE)
        rows.append({"year": y, "sales": sales, "ebit": ebit})
    return rows


def rnpv(facts: dict, m: dict, plan: list[dict], price_mult=1.0, patient_mult=1.0, share_mult=1.0,
         cost_mult=1.0, pos_mult=1.0, ttp_add=0.0) -> dict:
    mm = dict(m)
    mm["years_to_peak"] = max(1.0, m["years_to_peak"] + ttp_add)
    mm["annual_net_price_usd"] = m["annual_net_price_usd"] * price_mult
    mm["us_patients"] = m["us_patients"] * patient_mult
    mm["peak_share"] = min(1.0, m["peak_share"] * share_mult)
    r = mm["discount_rate"]
    peak = peak_sales_us(mm)
    # development: decision tree with abandonment after any failure
    p_reach, dev_pv, nol = 1.0, 0.0, 0.0
    for st in plan:
        cost = st["cost_m"] * cost_mult
        yrs = max(1, int(round(st["years"])))
        for k in range(yrs):
            dev_pv += p_reach * (cost / yrs) / (1 + r) ** (st["start_y"] + k)
        nol += cost
        p_reach *= st["p_success"]
    pos = min(1.0, p_reach * pos_mult)
    launch_t = sum(st["years"] for st in plan)
    # commercial value at launch (success path), with tax using the development NOL
    flows = commercial_cashflows(mm, peak)
    value_at_launch = -C.LAUNCH_SGA_M
    nol += C.LAUNCH_SGA_M
    for row in flows:
        taxable = row["ebit"]
        if taxable > 0 and nol > 0:
            used = min(nol, taxable)
            nol -= used
            taxable -= used
        elif taxable < 0:
            nol += -taxable
            taxable = 0
        cash = row["ebit"] - max(0.0, taxable) * C.TAX_RATE
        value_at_launch += cash / (1 + r) ** row["year"]
    abandoned = value_at_launch < 0
    commercial_pv_now = max(0.0, value_at_launch) / (1 + r) ** launch_t
    return {"rnpv_m": pos * commercial_pv_now - dev_pv, "pos": pos, "peak_us_m": peak,
            "peak_total_m": peak * (1 + mm["ex_us_multiplier"]), "dev_cost_pv_m": dev_pv,
            "value_at_launch_m": value_at_launch, "launch_in_y": launch_t, "abandon_at_launch": abandoned,
            "flows": flows}


def break_even_price(facts, m, plan) -> float | None:
    lo, hi = 0.0, 50.0
    if rnpv(facts, m, plan, price_mult=hi)["rnpv_m"] < 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if rnpv(facts, m, plan, price_mult=mid)["rnpv_m"] > 0:
            hi = mid
        else:
            lo = mid
    return hi * m["annual_net_price_usd"]


def monte_carlo(facts, m, plan, draws=C.MC_DRAWS, seed=C.MC_SEED) -> dict:
    rng = random.Random(seed)
    s = m.get("sigma") or C.MC_SIGMA

    def ln(sig):
        return math.exp(rng.gauss(-sig * sig / 2, sig))  # mean-one lognormal

    vals = sorted(rnpv(facts, m, plan, price_mult=ln(s["price"]), patient_mult=ln(s["patients"]),
                       share_mult=ln(s["share"]), cost_mult=ln(s["cost"]))["rnpv_m"] for _ in range(draws))
    q = lambda p: vals[min(len(vals) - 1, int(p * len(vals)))]
    return {"draws": draws, "seed": seed, "p10_m": q(0.10), "p50_m": q(0.50), "p90_m": q(0.90),
            "mean_m": statistics.fmean(vals), "p_positive": sum(v > 0 for v in vals) / len(vals)}


def investor_view(base: dict, round_terms: dict, m: dict) -> dict:
    pre, inv = round_terms["pre_money_m"], round_terms["investment_m"]
    dil = round_terms.get("dilution_to_exit", 0.4)
    stake = inv / (pre + inv)
    exit_value = max(0.0, base["value_at_launch_m"])
    moic_success = stake * (1 - dil) * exit_value / inv
    years = base["launch_in_y"]
    moic_expected = base["pos"] * moic_success
    irr = moic_expected ** (1 / years) - 1 if moic_expected > 0 and years > 0 else -1.0
    implied_fair_post = base["rnpv_m"] if base["rnpv_m"] > 0 else 0.0
    # 2.2 (review F23 / S1): the highest pre-money at which the round still earns the discount rate in expectation:
    # pos x (1 - dil) x exit / post >= (1 + r)^years  ->  post <= pos x (1 - dil) x exit / (1 + r)^years
    r = m["discount_rate"]
    max_post = base["pos"] * (1 - dil) * exit_value / (1 + r) ** years if years > 0 else 0.0
    return {"stake_now": stake, "stake_at_exit": stake * (1 - dil), "exit_value_at_approval_m": exit_value,
            "moic_if_success": moic_success, "moic_expected": moic_expected, "irr_expected": irr,
            "years_to_exit": years, "post_money_m": pre + inv, "rnpv_vs_post_money": implied_fair_post / (pre + inv),
            "required_irr": r, "max_pre_money_m": max(0.0, max_post - inv),
            "earns_cost_of_capital": irr >= r}


def license_view(base: dict, plan: list[dict], m: dict, terms: dict) -> dict:
    r = m["discount_rate"]
    npv = terms.get("upfront_m", 0.0)
    p_reach, t = 1.0, 0.0
    ms = terms.get("milestones_m", {})
    for st in plan:
        if st["stage"] in ms:
            npv += p_reach * ms[st["stage"]] / (1 + r) ** st["start_y"]
        p_reach *= st["p_success"]
        t = st["start_y"] + st["years"]
    if "approval" in ms:
        npv += p_reach * ms["approval"] / (1 + r) ** t
    roy = terms.get("royalty_pct", 0.0) / 100
    sales_pv = sum(row["sales"] / (1 + r) ** row["year"] for row in base["flows"]) / (1 + r) ** t
    npv += p_reach * roy * sales_pv * (1 - C.TAX_RATE)
    return {"licensor_npv_m": npv, "vs_own_rnpv_m": npv - base["rnpv_m"]}


def milestone_view(facts: dict, m: dict, plan: list[dict], round_terms: dict | None) -> dict:
    """Brief, stage 6: capital and time to the next milestone, future financing, value step-up at the milestone."""
    nxt = plan[0]
    worse = C.COST_M["worse"][nxt["stage"]]
    to_approval_base = sum(st["cost_m"] for st in plan)
    to_approval_worse = sum(C.COST_M["worse"][st["stage"]] for st in plan)
    p_reach, expected = 1.0, 0.0
    for st in plan:
        expected += p_reach * st["cost_m"]
        p_reach *= st["p_success"]
    after = None
    if len(plan) > 1:   # value of the program once the next milestone is passed (the step-up a buyer would pay for)
        nf = dict(facts, phase=plan[1]["stage"])
        after = rnpv(nf, m, phase_plan(nf, m))["rnpv_m"]
    out = {"next_milestone": f"complete {nxt['stage']}", "capital_to_milestone_m": [nxt["cost_m"], worse],
           "years_to_milestone": nxt["years"], "p_milestone_success": nxt["p_success"],
           "capital_to_approval_m": [to_approval_base, to_approval_worse],
           "expected_capital_to_approval_m": expected,
           "financing_rounds_to_approval": len(plan),
           "rnpv_after_milestone_m": after}
    cash = (round_terms or {}).get("cash_m")
    if cash is not None:
        out["cash_m"] = cash
        out["runway_short"] = cash < nxt["cost_m"]
    return out


def underwrite(facts: dict, market: dict, round_terms: dict | None = None, license_terms: dict | None = None,
               draws: int = C.MC_DRAWS, seed: int = C.MC_SEED) -> dict[str, Any]:
    """Full economic block plus the economic facts it implies.

    The facts (economics_negative, economics_weak, required_price_unrealistic) are produced only when patients and
    price are NOT assumptions (market["assumed"] lists assumed inputs; defaults filled here are added to it), so a
    default number never decides the verdict. runway_short is produced when round_terms has cash_m.
    """
    m = resolve_inputs(facts, market)
    plan = phase_plan(facts, m)
    base = rnpv(facts, m, plan)
    worse_m = dict(m, cost_case="worse")
    worse = rnpv(facts, worse_m, phase_plan(facts, worse_m))
    mc = monte_carlo(facts, m, plan, draws=draws, seed=seed)
    bep = break_even_price(facts, m, plan)
    sourced = not ({"us_patients", "eligible_share", "annual_net_price_usd"} & set(m["assumed"]))
    out_facts = {}
    if sourced:
        out_facts = {"economics_negative": mc["p_positive"] < C.ECON_NEGATIVE_P, "economics_weak": mc["p50_m"] < 0}
        if "price_ceiling_usd" in m and "price_ceiling_usd" not in m["assumed"]:
            out_facts["required_price_unrealistic"] = bep is None or bep > m["price_ceiling_usd"]
    ms = milestone_view(facts, m, plan, round_terms)
    sens = F.sensitivity(rnpv, facts, m, plan)
    if round_terms and "pre_money_m" in round_terms and "investment_m" in round_terms:
        post = round_terms["pre_money_m"] + round_terms["investment_m"]
        sens["required_peak_for_post_money_m"] = F.required_peak_for_value(rnpv, facts, m, plan, post)
        sens["post_money_m"] = post
    if "runway_short" in ms:
        out_facts["runway_short"] = ms["runway_short"]
    res = {
        "drives_verdict": sourced,
        "milestone": ms,
        "forecast": {"segment": m["segment"], "price": {"value": m["annual_net_price_usd"], "range": m["price_range"],
                                                         "rung": m["price_rung"], "basis": m["price_basis"]},
                     "peak_share": {"value": m["peak_share"], "class": m["share_class"], "basis": m["share_basis"]},
                     "years_to_peak": m["years_to_peak"], "sigma": m["sigma"], **sens},
        "driver_questions": F.driver_questions(sens),
        "assumptions": {k: v for k, v in m.items() if k != "phase_success"},
        "plan": plan,
        "base": {k: v for k, v in base.items() if k != "flows"},
        "worse_cost_case": {"rnpv_m": worse["rnpv_m"]},
        "monte_carlo": mc,
        "break_even_price_usd": bep,
        "facts": out_facts,
    }
    if round_terms and "pre_money_m" in round_terms and "investment_m" in round_terms:
        res["investor"] = investor_view(base, round_terms, m)
        if sourced:                 # with assumed patients or price the round test is shown, not used in the verdict
            out_facts["round_overpriced"] = not res["investor"]["earns_cost_of_capital"]
    if license_terms:
        res["license"] = license_view(base, plan, m, license_terms)
    return res

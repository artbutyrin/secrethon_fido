"""Forecast for assets without sales: price ladder, differentiation share, sensitivity, scenarios."""
import unobio_scoring as U
from unobio_scoring import constants as C
from unobio_scoring import economics as E
from unobio_scoring import forecast as F

BASE = {"phase": "ph2", "modality": "antibody", "oncology": False, "genetic_support": "gwas"}


def test_price_ladder_order():
    m = {"us_patients": 1000}
    seg = "chronic_biologic"
    assert F.price_ladder(BASE, {**m, "price_analogues": {"same_moa": [50000, 70000], "same_indication": [9000]}},
                          seg)["rung"] == "same_moa"
    lad = F.price_ladder(BASE, {**m, "price_analogues": {"same_indication": [9000, 11000, 30000]}}, seg)
    # 2.2: other mechanisms' prices (maybe generics) are a reference, not a sourced price for this drug
    assert lad["rung"] == "same_indication" and lad["price"] == 11000 and lad["assumed"]
    ref = F.price_ladder(BASE, m, seg)
    assert ref["rung"] == "reference" and ref["assumed"] and ref["price"] == C.REFERENCE_PRICE[seg][1]
    assert ref["sigma"] > lad["sigma"]


def test_economics_runs_without_any_price_and_marks_it_assumed():
    e = E.underwrite(BASE, {"us_patients": 200000}, draws=200)
    assert e["forecast"]["price"]["rung"] == "reference" and e["drives_verdict"] is False


def test_value_ceiling_caps_price():
    m = E.resolve_inputs(BASE, {"us_patients": 1000, "qaly_gain_per_year": 0.1})
    assert m["annual_net_price_usd"] <= C.WTP_PER_QALY * 0.1 + 1e-6 and m["price_ceiling_usd"] == 15000


def test_share_follows_differentiation():
    late = {**BASE, "approved_same_moa_count": 2}
    s = {c: E.resolve_inputs({**late, **f}, {"us_patients": 1000})["peak_share"]
         for c, f in {"best": {"differentiation_claim": "efficacy", "differentiation_evidence": True},
                      "claimed": {"differentiation_claim": "efficacy"},
                      "none": {"differentiation_claim": "none"}}.items()}
    assert s["best"] > s["claimed"] > s["none"]
    first = E.resolve_inputs(BASE, {"us_patients": 1000})
    assert first["share_class"] == "first_in_class" and first["peak_share"] == 0.5


def test_late_entry_penalty():
    a = E.resolve_inputs({**BASE, "approved_same_moa_count": 1}, {"us_patients": 1000})["peak_share"]
    b = E.resolve_inputs({**BASE, "approved_same_moa_count": 1, "years_behind_first_in_class": 7},
                         {"us_patients": 1000})["peak_share"]
    assert b < a


def test_sensitivity_is_consistent():
    m = E.resolve_inputs(BASE, {"us_patients": 300000, "annual_net_price_usd": 30000})
    plan = E.phase_plan(BASE, m)
    s = F.sensitivity(E.rnpv, BASE, m, plan)
    swings = [t["swing_m"] for t in s["tornado"]]
    assert swings == sorted(swings, reverse=True)
    sc = s["scenarios"]
    assert sc["bear"]["rnpv_m"] < sc["median"]["rnpv_m"] < sc["bull"]["rnpv_m"]
    bep = E.break_even_price(BASE, m, plan)
    assert abs(s["break_even"]["annual_net_price_usd"] - bep) / bep < 0.01


def test_required_peak_for_valuation_and_driver_questions():
    p = U.evaluate(U.load_config(), {**BASE, "approved_therapies_count": 0},
                   market={"us_patients": 300000, "annual_net_price_usd": 30000},
                   round_terms={"pre_money_m": 80, "investment_m": 20}, mc_draws=200)
    fc = p["economics"]["forecast"]
    assert fc["post_money_m"] == 100 and (fc["required_peak_for_post_money_m"] or 0) > 0
    assert p["dd_questions"][0].get("economic_driver") == fc["tornado"][0]["driver"]
    assert "Forecast without sales" in U.markdown(p) and "break even" in U.card(p)

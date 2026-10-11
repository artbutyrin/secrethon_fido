"""Review fixes applied on top of the validated version 1.1 configuration (config_v11.py).

Each fix names the review finding it answers. Everything that is not listed here is exactly version 1.1, so the
validation of version 1.1 on mechanism-level facts still applies to the parts this file does not touch.

  F38  me-too: the kill rule becomes a strong minus plus a cap at Conditional; it stays a kill only when
       differentiation was checked and refuted. Counts the same mechanism AND the same modality class when that
       count is known (an RNA drug against a target hit by small molecules is not a me-too).
  F41  no patent: a kill only with less than 5 years of statutory exclusivity; 5–6 years is a strong minus;
       7 or more (orphan, biologic) is not a minus.
  F31  cash runway, F52 negative economics, F38 unproven me-too: caps — the verdict cannot exceed Conditional.
  F44  (switch, OFF by default) Invest needs data on the asset: at least one known asset-level item or 5 of 8 items.
  run review 2.5  "mechanism refuted" also fires when the mechanism is approved nowhere (successes unknown):
       moa_approved_any_indication = false or clinical precedent "none". Two failures still have to pass the
       claims gate, so an LLM count needs a human before it can kill.
  F52  economics from the economics module: P(rNPV > 0) < 10% is a strong minus, median rNPV < 0 a warning,
       both in the pricing cluster (so Medicare and the price rule are not counted twice, F30).
"""
from __future__ import annotations

import copy

VERSION = "2.7"   # 2.7: opposite_direction_approved (strong minus)
# 2.5:   # 2.5: me-too without proven differentiation is Do Not Invest (grounds "crowded"), not Conditional
# 2.4:   # 2.3: verdict "Insufficient evidence"; genetic_support "mendelian_subtype" (+1)
# 2.4: tier "note" (shown, not counted) for absence-of-evidence rules (no genetics and no precedent, enrollment);
#      me-too is a cap only; a boxed warning on an approved class is a note; cap_unknown_class_outcome: Invest waits
#      while a same-mechanism Phase 2/3 in this disease has finished with an unknown outcome

_NEW_FACTS = {
    "approved_same_moa_same_modality_count": {
        "type": "int", "scope": "mechanism", "mvp": "open_targets", "probes": [0, 2],
        "label": "Approved drugs with the same mechanism AND the same modality class in this disease",
        "source": "Open Targets knownDrugs + ChEMBL molecule type (small molecule / antibody-like / nucleic acid / "
                  "gene / cell)"},
    "moa_approved_any_indication": {
        "type": "bool", "scope": "mechanism", "mvp": "derived",
        "label": "The mechanism (target + direction) is approved in any indication",
        "source": "Open Targets knownDrugs, all indications"},
    "acute_indication": {
        "type": "bool", "scope": "mechanism", "mvp": "none",
        "label": "Acute (not chronic) indication, e.g. acute infection or injury", "source": "Analyst"},
    "regulatory_exclusivity_years": {
        "type": "int", "scope": "asset", "mvp": "none", "min": 0, "max": 15, "probes": [0, 5, 7],
        "label": "Statutory exclusivity expected after approval (NCE 5, orphan 7, biologic 12 years)",
        "source": "FDA Orange/Purple Book rules; orphan designation",
        "dd": "Which regulatory exclusivities (NCE, orphan, BPCIA) will the asset get, and for which indication?"},
    "economics_negative": {
        "type": "bool", "scope": "asset", "mvp": "derived",
        "label": "Economics negative: P(rNPV > 0) below 10% in the Monte Carlo",
        "source": "unobio_scoring.economics (computed, never from an LLM)",
        "dd": "How many patients will actually be treated and at what net price? Can development be narrowed or "
              "made cheaper?"},
    # --- 2.2: translation chain for the class (step92 backend: openFDA labels, PubMed, quote + support checks) ---
    "class_exposure_human": {
        "type": "bool", "scope": "mechanism", "mvp": "pubmed_text",
        "label": "Link 2 for the class: another drug with the same mechanism and the same modality reaches the site "
                 "of action in humans (false = documents say it was looked for and not reached)",
        "source": "FDA labels (pharmacokinetics); PubMed abstracts"},
    "class_target_engagement_human": {
        "type": "bool", "scope": "mechanism", "mvp": "pubmed_text",
        "label": "Link 3 for the class: another drug with the same mechanism engages the target in humans (binding, "
                 "occupancy, lower target protein or mRNA)",
        "source": "FDA labels (pharmacodynamics); PubMed abstracts"},
    "class_pd_response_human": {
        "type": "bool", "scope": "mechanism", "mvp": "pubmed_text",
        "label": "Link 4 for the class: a downstream biomarker changes in humans with another drug of the same "
                 "mechanism", "source": "FDA labels (pharmacodynamics); PubMed abstracts"},
    "round_overpriced": {
        "type": "bool", "scope": "asset", "mvp": "derived",
        "label": "The round does not earn the cost of capital: expected investor IRR below the discount rate at this "
                 "pre-money",
        "source": "unobio_scoring.economics, investor view (computed, never from an LLM)",
        "dd": "At what pre-money does the round earn the fund's required return, and what would justify the asked one?"},
    # 2.7: the thesis acts against an approved direction on the same target in the same disease
    "opposite_direction_approved_count": {
        "type": "int", "scope": "mechanism", "mvp": "open_targets", "probes": [0, 1],
        "label": "Drugs approved for this disease that act on the same target in the OPPOSITE direction (the thesis "
                 "inhibits what approved drugs activate, or the reverse)",
        "source": "Open Targets knownDrugs: ChEMBL action type + official labels mapped to the disease ID"},
    "economics_weak": {
        "type": "bool", "scope": "asset", "mvp": "derived",
        "label": "Economics weak: median (P50) rNPV below zero",
        "source": "unobio_scoring.economics (computed, never from an LLM)",
        "dd": "Which assumption (patients, price, share, cost) would have to move to make the median rNPV positive?"},
}

# same mechanism count: the modality-specific one when known, otherwise the plain one
_SAME_MOA_GE2 = {"any": [
    {"fact": "approved_same_moa_same_modality_count", "ge": 2},
    {"all": [{"fact": "approved_same_moa_same_modality_count", "known": False},
             {"fact": "approved_same_moa_count", "ge": 2}]}]}

_DIFFERENTIATED = {"any": [
    {"all": [{"fact": "differentiation_claim", "in": ["efficacy", "safety", "structural_cost"], "default": "none"},
             {"fact": "differentiation_evidence", "ne": False, "default": True}]},
    {"all": [{"fact": "differentiation_claim", "eq": "price_only", "default": "none"},
             {"fact": "price_channel_direct", "eq": True, "default": False},
             {"fact": "differentiation_evidence", "ne": False, "default": True}]}]}

CAPS = [
    {"id": "cap_runway", "when": {"fact": "runway_short", "eq": True},
     "reason": "cash does not reach the next readout (fund through the milestone first)", "finding": "F31"},
    {"id": "cap_economics", "when": {"fact": "economics_negative", "eq": True},
     "reason": "P(rNPV > 0) is below 10% (change price, scale or development plan first)", "finding": "F52"},
    {"id": "cap_round_price", "when": {"fact": "round_overpriced", "eq": True},
     "reason": "at this pre-money the round does not earn the cost of capital (the asset may be fine; the price is "
               "not)", "finding": "F23"},
    {"id": "cap_me_too", "when": {"all": [_SAME_MOA_GE2, {"not": _DIFFERENTIATED}]},
     "reason": "me-too without proven differentiation (show comparative data, device or payer advantage first)",
     "finding": "F38"},
]


def _rule(raw: dict, rule_id: str) -> dict:
    return next(r for r in raw["rules"] if r["id"] == rule_id)


def apply(raw_v11: dict) -> dict:
    raw = copy.deepcopy(raw_v11)
    raw["version"] = VERSION
    raw["facts"].update(copy.deepcopy(_NEW_FACTS))
    if "protein" not in raw["facts"]["modality"]["values"]:
        raw["facts"]["modality"]["values"].insert(raw["facts"]["modality"]["values"].index("vaccine"), "protein")

    # 2.3: Mendelian evidence only in a subtype of the disease (Open Targets indirect evidence: every Mendelian record
    # is for a descendant disease, e.g. familial atrial fibrillation under atrial fibrillation). An ordinary green (+1),
    # never the strong green (+2) that Mendelian evidence for the disease itself gets.
    gs = raw["facts"]["genetic_support"]
    gs["values"].insert(gs["values"].index("mendelian") + 1, "mendelian_subtype")
    gs["label"] += ("; mendelian_subtype = Mendelian evidence only for a subtype (a more specific disease under it in "
                    "the ontology), not for the disease itself: +1, not the +2 of Mendelian evidence")
    for item in raw["scorecard"]:
        green = item.get("green") or {}
        for cond in [green] + list(green.get("any") or []):
            if cond.get("fact") == "genetic_support" and "mendelian" in (cond.get("in") or []):
                cond["in"] = cond["in"] + ["mendelian_subtype"]
        # strong_green stays {"fact": "genetic_support", "eq": "mendelian"}: the subtype never reaches it

    # F38: me-too
    me = _rule(raw, "me_too")
    me.update(tier="strong", cluster="competition",
              name="Me-too: late, differentiation not proven",
              when={"all": [_SAME_MOA_GE2, {"not": _DIFFERENTIATED}]},
              note="Strong minus plus a cap at Conditional (review F38: Trulicity would have been killed). "
                   "A kill only when differentiation was checked and refuted (me_too_refuted).")
    raw["rules"].insert(raw["rules"].index(me), {
        "id": "me_too_refuted", "tier": "kill", "name": "Me-too: differentiation checked and refuted",
        "scope": "mechanism", "basis": "expert", "source": "Unobio analyst; review F38",
        "when": {"all": [_SAME_MOA_GE2, {"fact": "differentiation_evidence", "eq": False}]}})
    md = _rule(raw, "me_too_differentiated")
    md["when"] = copy.deepcopy(md["when"])
    _swap_count(md["when"])

    # F41: no patent
    np_ = _rule(raw, "no_patent")
    np_.update(name="No patent and less than 5 years of statutory exclusivity",
               when={"all": [{"fact": "patent_status", "in": ["expired", "none"]},
                             {"fact": "regulatory_exclusivity_years", "lt": 5, "default": 0}]})
    raw["rules"].insert(raw["rules"].index(_rule(raw, "key_markets_gone")), {
        "id": "no_patent_short_exclusivity", "tier": "strong", "cluster": "licensing",
        "name": "No patent; protection rests on 5–6 years of statutory exclusivity",
        "scope": "asset", "basis": "expert", "source": "Review F41; FDA exclusivity rules",
        "when": {"all": [{"fact": "patent_status", "in": ["expired", "none"]},
                         {"fact": "regulatory_exclusivity_years", "ge": 5},
                         {"fact": "regulatory_exclusivity_years", "lt": 7}]}})

    # run review 2.5: mechanism refuted also when the mechanism is approved nowhere
    mr = _rule(raw, "mechanism_refuted")
    mr["when"] = {"all": [
        {"fact": "moa_failures_efficacy_ph23", "ge": 2},
        {"any": [{"fact": "moa_successes_same_indication", "eq": 0},
                 # approved nowhere: moa_approved_any_indication = false, or precedent "none" (the bottom of the
                 # ladder: not even approved in an unrelated disease)
                 {"all": [{"any": [{"fact": "moa_approved_any_indication", "eq": False},
                                   {"fact": "moa_clinical_precedent", "eq": "none"}]},
                          {"fact": "moa_successes_same_indication", "eq": 0, "default": 0}]}]}]}

    # 2.7: an approved drug in this disease acts on the same target the other way (obesity: GLP-1 agonists are approved,
    # the thesis is an antagonist). Validated biology says the thesis direction worsens or does not treat the disease.
    raw["rules"].insert(raw["rules"].index(_rule(raw, "one_mechanism_failure")), {
        "id": "opposite_direction_approved", "tier": "kill", "grounds": "opposite_direction", "scope": "mechanism",
        "basis": "expert", "name": "The opposite direction on this target is approved for this disease",
        "source": "Unobio 2.7; direction of action from ChEMBL",
        "when": {"fact": "opposite_direction_approved_count", "ge": 1},
        "note": "A kill with its own grounds: as a strong minus, direction-blind genetic support (+2) outweighed it and a "
                "PCSK9 agonist for familial hypercholesterolemia came out Conditional. The memo names the approved "
                "drugs; a subgroup that needs the opposite action is a case for a human."})

    # 2.2: the class engaged the target in humans and still failed for efficacy -> the hypothesis failed
    raw["rules"].insert(raw["rules"].index(_rule(raw, "one_mechanism_failure")) + 1, {
        "id": "engaged_no_benefit", "tier": "strong", "axis": "science", "scope": "mechanism", "basis": "expert",
        "name": "Target engaged in humans, still no efficacy",
        "source": "Morgan 2012 (Pfizer's three pillars: a failure with exposure, binding and pharmacology shown tests "
                  "the mechanism, not the molecule); Unobio analyst",
        "when": {"all": [{"any": [{"fact": "class_target_engagement_human", "eq": True},
                                  {"fact": "class_pd_response_human", "eq": True}]},
                         {"fact": "moa_failures_efficacy_ph23", "ge": 1},
                         {"fact": "approved_same_moa_count", "eq": 0}]},
        "note": "Not clustered with one_mechanism_failure on purpose: it counts the engagement evidence, not the "
                "failure again; together 4 minuses (Do Not Invest). An approval of the mechanism here stops it "
                "(tofersen lowered SOD1, missed its primary endpoint and was approved). The class facts feed only "
                "this rule and the memo's chain table, not the Translation chain item: that item stays about the "
                "asset, so class evidence never counts as asset data."})

    # F52: economic facts as rules in the pricing cluster
    pos = raw["rules"].index(_rule(raw, "price_unrealistic"))
    raw["rules"][pos:pos] = [
        {"id": "economics_negative", "tier": "strong", "cluster": "pricing", "scope": "asset", "basis": "mixed",
         "name": "Economics negative: P(rNPV > 0) below 10%", "source": "unobio_scoring.economics",
         "when": {"fact": "economics_negative", "eq": True}},
        {"id": "economics_weak", "tier": "warning", "cluster": "pricing", "scope": "asset", "basis": "mixed",
         "name": "Economics weak: median rNPV below zero", "source": "unobio_scoring.economics",
         "when": {"fact": "economics_weak", "eq": True}},
    ]

    # derivations and consistency for the new facts
    raw["derive"] += [
        {"when": {"fact": "approved_therapies_count", "eq": 0}, "set": {"approved_same_moa_same_modality_count": 0}},
        {"when": {"fact": "approved_same_moa_count", "eq": 0}, "set": {"approved_same_moa_same_modality_count": 0}},
        {"when": {"fact": "moa_clinical_precedent", "in": ["approved_same", "approved_related", "approved_unrelated"]},
         "set": {"moa_approved_any_indication": True}},
        {"when": {"fact": "approved_same_moa_count", "ge": 1}, "set": {"moa_approved_any_indication": True}},
    ]
    raw["constraints"] += [
        {"message": "approved_same_moa_same_modality_count cannot exceed approved_same_moa_count",
         "when": {"fact": "approved_same_moa_same_modality_count", "gt": {"fact": "approved_same_moa_count"}}},
        {"message": "an approved precedent contradicts moa_approved_any_indication = false",
         "when": {"all": [{"fact": "moa_approved_any_indication", "eq": False},
                          {"fact": "moa_clinical_precedent",
                           "in": ["approved_same", "approved_related", "approved_unrelated"]}]}},
        {"message": "an acute indication is not a chronic non-oncology disease",
         "when": {"all": [{"fact": "acute_indication", "eq": True}, {"fact": "chronic_non_oncology", "eq": True}]}},
    ]

    # F31, F52, F38 caps and F44 asset-data requirement
    raw["caps"] = copy.deepcopy(CAPS)
    # F44 is available but OFF: with mechanism-only data (what the pipeline collects) it would turn every Invest
    # into Conditional. Turn on with load_config(asset_data_for_invest=True) once asset facts are collected.
    raw["verdict"]["invest_requires_asset_data"] = False
    # 2.4: absence of evidence is not negative evidence. These rules stay in the report as notes (tier "note": fired,
    # shown, 0 points). Live sample 10.10.2026: Osteoarthritis + HAS2 was Do Not Invest on no_genetics_no_precedent
    # alone; the enrollment warning fired for almost every large disease.
    for rid in ("no_genetics_no_precedent", "indication_enrollment_risk"):
        r = _rule(raw, rid)
        r["tier"] = "note"
        r["note"] = (r.get("note", "") + " 2.4: a note, not a minus (absence of evidence, or a property of the "
                     "disease rather than of the thesis).").strip()
    # me-too: the cap at Conditional (cap_me_too) says "show differentiation"; the strong minus on top of it turned
    # validated mechanisms (SGLT2, GLP-1, ABL1) into Do Not Invest. me_too_refuted stays a kill.
    # 2.5 (product decision, 10.10.2026): 2+ approved drugs with the same mechanism (and modality, when known) and no
    # proven advantage -> Do Not Invest with its own grounds "crowded", so the memo says plainly that the market already
    # has this drug. Before (F38, 2.2-2.4) it was a strong minus or a note plus a cap at Conditional, and 5 of 15
    # pairs of the mechanism sample came out Conditional for this reason alone. Differentiation (claim + evidence not
    # refuted) lifts it: me_too_differentiated (a note) fires instead and Invest is possible.
    me = _rule(raw, "me_too")
    me.pop("cluster", None)
    me.update(tier="kill", grounds="crowded",
              name="Crowded: the mechanism is already approved here (2+ drugs) and no advantage is shown",
              note="2.5: Do Not Invest with grounds 'crowded' (a market call). Add differentiation_claim and "
                   "differentiation_evidence to lift it.")
    _rule(raw, "me_too_refuted").update(grounds="crowded")
    me_d = _rule(raw, "me_too_differentiated")
    me_d.update(tier="note")
    # a boxed warning on a class that is approved here is part of the label, not a reason against the mechanism
    cs = _rule(raw, "class_safety_signal")
    cs["when"] = {"all": [{"fact": "class_safety_signal", "eq": True},
                          {"fact": "approved_same_moa_count", "eq": 0, "default": 0}]}
    raw["rules"].insert(raw["rules"].index(cs) + 1, {
        "id": "class_safety_signal_approved", "tier": "note", "cluster": "safety", "scope": "mechanism",
        "basis": "expert", "name": "Boxed warning on a class that is approved in this disease (monitoring, not a minus)",
        "source": "Unobio 2.4", "when": {"all": [{"fact": "class_safety_signal", "eq": True},
                                                 {"fact": "approved_same_moa_count", "ge": 1}]}})

    # 2.4: the engine supports "min_science_items_invest" (distinct mechanism-evidence items for Invest), but it stays 0:
    # on 13,030 validation pairs Mendelian genetics alone led to launch in 37–40% (SCORING.md), so one strong item is
    # enough. The false Invest of the mechanism sample (HTT + tominersen) is answered by cap_unknown_class_outcome:
    # a same-mechanism drug finished Phase 2/3 here and its outcome is not known.
    raw["verdict"]["min_science_items_invest"] = 0
    raw["facts"]["moa_ph23_unknown_outcome_count"] = {
        "type": "int", "scope": "mechanism", "mvp": "open_targets", "probes": [0, 1],
        "label": "Same-mechanism drugs (not approved here) whose Phase 2/3 trial in this disease finished, with no known "
                 "outcome (no efficacy failure found, no approval)",
        "source": "Open Targets clinical reports (trial status), the run's failure count"}
    raw["caps"].append({
        "id": "cap_unknown_class_outcome",
        # only while the mechanism is not approved here: once it is, one class member's unknown result does not put
        # the mechanism in doubt (bococizumab next to evolocumab and alirocumab)
        "when": {"all": [{"fact": "moa_ph23_unknown_outcome_count", "ge": 1},
                         {"fact": "approved_same_moa_count", "eq": 0, "default": 0}]},
        "reason": "a drug with the same mechanism finished Phase 2/3 in this disease and its outcome is not known "
                  "(find the result first: a failure would be negative evidence)", "finding": "2.4"})
    return raw


def _swap_count(cond):
    """Replace {fact: approved_same_moa_count, ge: 2} by the modality-aware count inside a condition."""
    if isinstance(cond, dict):
        for k in ("all", "any"):
            if k in cond:
                cond[k] = [copy.deepcopy(_SAME_MOA_GE2) if c == {"fact": "approved_same_moa_count", "ge": 2}
                           else (_swap_count(c) or c) for c in cond[k]]
        if "not" in cond:
            _swap_count(cond["not"])

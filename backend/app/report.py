"""Investment memo: 11 sections built from the stored claims and verdict, never from raw documents.

Who writes what:
  code      recommendation header, critical unknowns, diligence questions, sources (numbers come only from here);
            the numbers of commercial opportunity and capital to next milestone (scorer 2.x economics), each tagged
            [S] sourced, [entered] by a person, [A] assumption, [A default] model default, [D] computed
  LLM       prose for the other sections; every paragraph is `source` (what cited claims say) or `inference`
            (the model's own conclusion, shown as such)
  template  if there is no LLM, or its text fails validation: the claim statements, grouped by section
  chain     the human translation thesis always starts with the five links of the translation chain (code):
            for each, the asset's status, the class's status (other drugs of the mechanism), what was only tested

Validator, per LLM paragraph: cited claim IDs exist; a `source` paragraph cites at least one; every number in the
text appears in a cited claim (phases and grades aside); the text names no verdict other than the computed one.
A failed paragraph is dropped; one retry with the reasons; a section left empty falls back to the template.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from backend.app.llm import LLM, LLMError
from backend.app.scorer import INSUFFICIENT

SECTIONS = [  # id, title, written by
    ("recommendation", "Recommendation", "code+llm"),
    ("scientific_thesis", "Scientific thesis", "llm"),
    ("human_translation_thesis", "Human translation thesis", "llm"),
    ("clinical_development_plan", "Clinical development plan", "llm"),
    ("competitive_landscape", "Competitive landscape", "llm"),
    ("commercial_opportunity", "Commercial opportunity", "llm"),
    ("capital_to_next_milestone", "Capital to next milestone", "llm"),
    ("key_risks", "Key risks", "llm"),
    ("critical_unknowns", "Critical unknowns", "code"),
    ("diligence_questions", "Diligence questions", "code"),
    ("sources", "Sources", "code"),
]
LLM_SECTIONS = [s for s, _, by in SECTIONS if "llm" in by]
TITLES = {s: t for s, t, _ in SECTIONS}

# Which facts belong to which section (for the template fallback and as a hint to the LLM).
SECTION_FACTS = {
    "scientific_thesis": {"genetic_support", "moa_clinical_precedent", "moa_failures_efficacy_ph23",
                          "moa_successes_same_indication", "independent_groups", "perturbation_evidence",
                          "correlational_evidence", "foundational_retraction", "essential_gene", "moa_direction"},
    "human_translation_thesis": {"modality", "modality_target_mismatch", "tractability", "animal_model_response",
                                 "pillars_human", "link_exposure", "link_target_engagement", "link_pd_response",
                                 "class_exposure_human", "class_target_engagement_human", "class_pd_response_human",
                                 "own_ph2_positive", "own_trial_failed_efficacy", "drug_approved_other_indication"},
    "clinical_development_plan": {"phase", "route_of_administration", "indication_enrollment_terminations_high",
                                  "accepted_endpoint_exists", "endpoint_approval_precedent", "natural_history_data",
                                  "fda_designations_count", "rare_disease", "oncology", "randomized_controlled",
                                  "endpoint_matches_mechanism", "dose_ranging_done", "biomarker_selection",
                                  "single_arm_pivotal", "accelerated_only", "confirmatory_trial_registered",
                                  "indication_ph3_outcomes_other_moa", "indication_ph3_success_share_other_moa",
                                  "indication_graveyard", "indication_accelerated_withdrawn"},
    "competitive_landscape": {"approved_same_moa_count", "ph3_same_moa_count", "approved_therapies_count",
                              "years_behind_first_in_class", "differentiation_claim", "differentiation_evidence",
                              "soc_last_new_moa_years", "indication_new_moa_approvals_10y", "active_comparator_exists"},
    "commercial_opportunity": {"approved_therapies_count", "rare_disease", "oncology", "life_threatening_indication",
                               "chronic_non_oncology", "required_price_unrealistic", "medicare_negotiation_exposure",
                               "soc_loe_before_launch", "price_channel_direct", "patent_status", "key_patent_license",
                               "key_markets_outlicensed", "royalty_stack_pct"},
    "capital_to_next_milestone": {"phase", "runway_short", "sponsor_size", "sponsor_prior_approvals",
                                  "big_pharma_partner", "partner_returned_asset"},
    "key_risks": {"class_safety_signal", "class_withdrawal", "class_drug_related_deaths", "moa_discontinued_safety_count",
                  "moa_crl_safety", "moa_adcom_negative", "target_safety_flags", "grade5_related", "grade4_related",
                  "toxicity_at_efficacious_exposure", "crl_reason", "adcom_negative", "fda_data_integrity_letter",
                  "cmo_oai_or_warning_letter"},
}

SYSTEM = """You write sections of a biotech investment memo for investors. You get the computed verdict, the
scorecard, the rules that fired and the claims (facts with sources). The verdict is final: explain it, never
change or second-guess it. The verdict is one of Invest, Conditional, Insufficient evidence, Do Not Invest.
"Insufficient evidence" means the public evidence is too thin to decide; it is NOT a negative call: never describe
it as Do Not Invest, a rejection or evidence against the thesis.
Write for these sections: recommendation (2-3 sentences on why the verdict follows from the evidence),
scientific_thesis (target biology, human genetics, mechanism precedent and failures), human_translation_thesis
(can the modality reach and engage the target in patients; the input's translation_chain lines are already printed
above your text, so do not repeat them: say what the shown and missing links mean for this asset), clinical_development_plan (stage, trial design,
regulatory path, enrollment), competitive_landscape (approved drugs, same-mechanism drugs, differentiation),
commercial_opportunity (unmet need, population, pricing exposure), capital_to_next_milestone (what the next value
inflection would be and what is unknown about funding), key_risks (the rules that fired and other risks).
Rules:
- Every paragraph is either "source" (it restates what the cited claims say; cite at least one claim ID) or
  "inference" (your own reasoning from the claims; cite the claims it rests on).
- Use only the claims given. Do not add facts, drug names, trial IDs, dates or numbers that are not in them.
- Do not write numbers unless the same number is in a cited claim. Write no percentages, prices, market sizes or
  amounts of money.
- If a section has no relevant claims, write one short "inference" paragraph saying what is not known and why it
  matters for the decision, with no claim IDs.
- commercial_opportunity and capital_to_next_milestone already start with code-written lines (economics_lines in
  the input). Do not repeat their numbers; say in words what they mean for the decision, and which assumptions
  (tagged [A] or [A default]) matter most.
- Do not put claim IDs in the text; list them in claim_ids. Plain English, 1-3 short paragraphs per section.
- If the genetic_support claim is "mendelian_subtype", the Mendelian evidence is for a rare subtype only: call it
  "Mendelian genetics in a rare subtype" and name the subtype as the claim does; never call it Mendelian genetic
  evidence for the disease itself."""

SCHEMA = {
    "type": "object",
    "properties": {"sections": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "enum": LLM_SECTIONS},
            "paragraphs": {"type": "array", "items": {
                "type": "object",
                "properties": {"text": {"type": "string"},
                               "kind": {"type": "string", "enum": ["source", "inference"]},
                               "claim_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["text", "kind", "claim_ids"], "additionalProperties": False}}},
        "required": ["id", "paragraphs"], "additionalProperties": False}}},
    "required": ["sections"], "additionalProperties": False,
}

COLOR = {"G": "green", "Y": "yellow", "R": "red", "U": "unknown"}
_NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?%?")
_EXEMPT = re.compile(r"\b(?:phase|grade|link|ph)\s*\d(?:\s*/\s*\d)?\b|\b[A-Z]{2,}[\w-]*\d+\w*\b|\bclm_\w+", re.I)
_CLAIM_REF = re.compile(r"\s*\[?\bclm_[\w]+\]?")
_KIND_PREFIX = re.compile(r"^(?:source|inference)\s*:\s*", re.I)      # models sometimes echo the kind into the text


def _para(text: str, kind: str, claim_ids=()) -> dict:
    return {"text": text, "kind": kind, "claim_ids": list(claim_ids)}


def _numbers(text: str) -> set[str]:
    return {n.rstrip("%").replace(",", ".") for n in _NUM.findall(_EXEMPT.sub(" ", text))}


def _value_text(v: Any) -> str:
    return {True: "yes", False: "no", None: "unknown"}.get(v, str(v)) if isinstance(v, (bool, type(None))) else str(v)


# --- what the LLM sees ------------------------------------------------------------------------------------------------
def pack(run: dict, claims: list[dict], payload: dict, status: dict[str, str]) -> dict:
    res = payload["result"]
    norm = run.get("normalized") or {}
    d, t = norm.get("disease") or {}, norm.get("target") or {}
    return {
        "disease": d.get("name"), "target": f"{t.get('symbol')} ({t.get('name')})",
        "input": {"mechanism": t.get("raw"), "phase": run.get("phase"), "route": run.get("route")},
        "verdict": {"decision": res["verdict"]["decision"], "grounds": res["verdict"]["grounds_text"],
                    "reason": res["verdict"]["reason"]},
        "scorecard": [{"item": i["name"], "color": COLOR[i["color"]], "claim_ids": i.get("claim_ids", [])}
                      for i in res["scorecard"]],
        "rules_fired": [{"rule": r["name"], "tier": r["tier"], "counted": r["counted"],
                         "claim_ids": r.get("claim_ids", [])} for r in res["rules"]],
        "what_would_change": [f"{w['label'].split('. ')[0]}: {_value_text(w['from'])} -> {_value_text(w['to'])} "
                              f"gives {w['verdict_to']}" for w in res["what_would_change"][:6]],
        "claims": [{"id": c["id"], "fact": c["fact"], "value": c["value"], "statement": c["statement"],
                    "origin": c["origin"], "status": status.get(c["id"], "not_used")} for c in claims],
        "section_hints": {s: sorted(f for f in facts if any(c["fact"] == f for c in claims))
                          for s, facts in SECTION_FACTS.items()},
    }


# --- validation -------------------------------------------------------------------------------------------------------
def check_paragraph(p: dict, claims_by_id: dict[str, dict], decision: str, genetics: str | None = None) -> str | None:
    """Returns the reason the paragraph is rejected, or None. `genetics`: the genetic_support value in use."""
    text = _KIND_PREFIX.sub("", _CLAIM_REF.sub("", p.get("text") or "").strip())
    p["text"] = text
    ids = p.get("claim_ids") or []
    if not text:
        return "empty text"
    unknown = [i for i in ids if i not in claims_by_id]
    if unknown:
        return f"unknown claim IDs {unknown}"
    if p.get("kind") == "source" and not ids:
        return "a source paragraph must cite at least one claim"
    allowed = set()
    for i in ids:
        c = claims_by_id[i]
        allowed |= _numbers(c["statement"]) | _numbers(str(c["value"]))
    extra = sorted(_numbers(text) - allowed)
    if extra:
        return f"numbers not in the cited claims: {extra}"
    named = set()
    low = text.lower()
    if "do not invest" in low:
        named.add("Do Not Invest")
    if re.search(r"\binsufficient evidence\b", low) and re.search(r"\b(verdict|recommend\w*|rating)\b", low):
        named.add("Insufficient evidence")
    if re.search(r"\bconditional\b", low) and re.search(r"\b(verdict|recommendation|rating)\b", low):
        named.add("Conditional")
    if re.search(r"(?<!not )\binvest\b(?! in\b)", re.sub(r"do not invest", "", low)) and \
            re.search(r"\b(verdict|recommend\w*|rating)\b", low):
        named.add("Invest")
    wrong = named - {decision}
    if wrong:
        return f"names a verdict other than {decision}: {sorted(wrong)}"
    if genetics == "mendelian_subtype" and re.search(r"\bmendelian\b", low) and "subtype" not in low:
        return "calls Mendelian evidence for a subtype Mendelian evidence for the disease"
    return None


def _validate(answer: dict, claims_by_id: dict, decision: str,
              genetics: str | None = None) -> tuple[dict[str, list], list[str]]:
    good: dict[str, list] = {}
    issues: list[str] = []
    for sec in answer.get("sections") or []:
        sid = sec.get("id")
        if sid not in LLM_SECTIONS:
            continue
        for p in sec.get("paragraphs") or []:
            if not isinstance(p, dict):
                continue
            p = {"text": str(p.get("text") or ""), "kind": p.get("kind"), "claim_ids": list(dict.fromkeys(p.get("claim_ids") or []))}
            why = check_paragraph(p, claims_by_id, decision, genetics)
            if why:
                issues.append(f"{sid}: {why}: {p['text'][:80]!r}")
            else:
                good.setdefault(sid, []).append(p)
    return good, issues


def write_llm_sections(llm: LLM, facts_pack: dict, claims_by_id: dict, decision: str,
                       attempts: int = 2, genetics: str | None = None) -> tuple[dict[str, list], list[str], int]:
    """Returns (section -> valid paragraphs, issues, attempts used). Keeps the best paragraphs across attempts."""
    best: dict[str, list] = {}
    issues: list[str] = []
    feedback = ""
    used = 0
    for used in range(1, attempts + 1):
        user = json.dumps(facts_pack, ensure_ascii=False) + feedback
        try:
            answer = llm.complete_json("write_report", SYSTEM, user, SCHEMA)
        except LLMError as exc:
            issues.append(f"LLM call failed: {exc}")
            break
        good, problems = _validate(answer, claims_by_id, decision, genetics)
        for sid, paras in good.items():
            if len(paras) >= len(best.get(sid, [])):
                best[sid] = paras
        issues = problems
        missing = [s for s in LLM_SECTIONS if s not in best]
        if not problems and not missing:
            break
        feedback = ("\n\nYour previous answer had problems; fix them and return all sections again:\n- "
                    + "\n- ".join(problems + [f"{s}: missing" for s in missing]))
    return best, issues, used


# --- code-written sections ------------------------------------------------------------------------------------------
def recommendation_header(payload: dict) -> list[dict]:
    res = payload["result"]
    v, s = res["verdict"], res["score"]
    cov = s["coverage"]
    out = []
    if payload.get("incomplete"):
        out.append(_para("INCOMPLETE RUN: some sources failed (" + "; ".join(x[:80] for x in payload["incomplete"])
                         + "). The verdict below rests on the data that arrived; rerun before relying on it.",
                         "scorer"))
    out += [_para(f"Recommendation: {v['decision']}. Grounds: {v['grounds_text']}. Scorer: {v['reason']}. "
                 f"Pluses {s['pos']}, minuses {s['neg']}; data for {cov['items_known']} of {cov['items_total']} "
                 f"scorecard items.", "scorer")]
    if v["decision"] == INSUFFICIENT:
        out.append(_para("Insufficient evidence is not a negative call: no kill rule fired and the minuses do not "
                         "outweigh the pluses, but the public evidence is too thin to support Conditional or Invest. "
                         "The diligence questions below say what would decide it.", "scorer"))
        det = v.get("insufficient") or {}
        why = (["sources failed in this run (see the warning above)"] if payload.get("incomplete") else []) + \
            list(det.get("texts") or [])
        if why:
            out.append(_para("Why the evidence is insufficient: " + "; ".join(why) + ".", "scorer"))
        dec = det.get("would_decide") or []
        if dec:
            out.append(_para("What would decide it (one fact each): " + "; ".join(
                f"{d['label'].split('. ')[0].rstrip('.')} = {_value_text(d['to'])} -> "
                f"{d['verdict_to'] if d['verdict_to'] in ('Invest', 'Conditional') else 'negative evidence'}"
                f" ({'company data' if d['scope'] == 'asset' else 'public data'})" for d in dec[:5]) + ".",
                "scorer"))
    out += caps_lines(payload)
    for cond in v.get("conditions") or []:
        out.append(_para(f"Condition for Invest: {cond['label'].split('. ')[0]} would need to be "
                         f"{_value_text(cond['to'])}.", "scorer"))
    out.append(question_note(payload))
    ev = (res.get("reference") or {}).get("evidence") or {}
    if ev.get("range"):
        lo, hi = ev["range"]
        out.append(_para(f"Reference only, not part of the verdict: {lo:.0%}–{hi:.0%} of historical target–disease "
                         f"pairs with similar mechanism evidence ('{ev['label']}') reached launch, counting from "
                         f"{ev['from']} (Minikel et al. 2024).", "scorer"))
    return out


def fired_rules(payload: dict) -> list[dict]:
    """Rules that fired, from the scorer: the first lines of Key risks."""
    out = []
    for r in payload["result"]["rules"]:
        how = {"kill": "kill rule", "strong": "strong minus", "warning": "warning",
               "note": "note"}[r["tier"]]
        if r["tier"] == "note":
            note = " (shown for context, not counted: absence of evidence is not negative evidence)"
        else:
            note = "" if r["counted"] else " (not counted: already covered by a related item or rule)"
        out.append(_para(f"Rule fired, {how}: {r['name']}{note}.", "scorer", r.get("claim_ids", [])))
    return out


def critical_unknowns(payload: dict, claims_by_id: dict) -> list[dict]:
    res = payload["result"]
    out = []
    for p in payload.get("pending") or []:
        ids = [i for i in p["claims"] if i in claims_by_id]
        out.append(_para(f"Waits for confirmation (a second independent source or a reviewer): "
                         f"{claims_by_id[ids[0]]['statement'] if ids else p['fact']}", "scorer", ids))
    for r in payload.get("rejected") or []:
        out.append(_para(f"Rejected claim on {r['fact']}: {r['reason']}.", "scorer",
                         [r["claim"]] if r["claim"] in claims_by_id else []))
    for x in payload.get("conflicts") or []:
        out.append(_para(f"Sources disagree on {x['fact']} ({', '.join(map(_value_text, x['values']))}); "
                         "treated as unknown.", "scorer", [i for i in x["claims"] if i in claims_by_id]))
    unknown = [i["name"] for i in res["scorecard"] if i["color"] == "U"]
    if unknown:
        out.append(_para(f"No data for these scorecard items: {', '.join(unknown)}. They count as unknown, "
                         "not as negative.", "scorer"))
    return out or [_para("No pending, rejected or conflicting claims, and every scorecard item has data.", "scorer")]


def diligence_questions(payload: dict) -> list[dict]:
    return [_para(q["question"] + (" (the answer can change the verdict)" if q.get("critical") else ""), "scorer")
            for q in payload["result"]["dd_questions"][:10]]


def sources(claims: list[dict], cited: set[str]) -> list[dict]:
    out, seen = [], set()
    for c in claims:
        if c["id"] not in cited:
            continue
        for s in c.get("sources") or []:
            label = s.get("name") or s.get("id") or ""
            key = (s.get("url"), label)
            if key in seen or not (s.get("url") or s.get("text")):
                continue
            seen.add(key)
            where = s.get("url") or s.get("text")
            kind = s.get("kind", "source").replace("_", " ").replace("open targets", "Open Targets")
            out.append(_para(f"{kind}{': ' + label if label else ''} — {where}", "source", [c["id"]]))
    return out


def template_section(section: str, claims: list[dict], status: dict[str, str]) -> list[dict]:
    facts = SECTION_FACTS.get(section, set())
    rows = [c for c in claims if c["fact"] in facts and status.get(c["id"]) in ("used", "pending")]
    if not rows:
        return [_para("No claims for this section yet; it is a diligence item.", "scorer")]
    return [_para(c["statement"] + (" (waits for confirmation)" if status.get(c["id"]) == "pending" else ""),
                  "source", [c["id"]]) for c in rows]


# --- economics (code, scorer 2.x) -------------------------------------------------------------------------------------
TAG = {"S": "[S]", "A": "[A]", "user": "[entered]"}


def _m(x: float | None) -> str:
    return "n/a" if x is None else f"{'−' if x < 0 else ''}${abs(x):,.1f}m"


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _tag(field: str, econ: dict, prov: dict) -> str:
    """Where an input came from: [entered], [S] sourced, [A] assumption, [A default] model default, [D] computed."""
    a = econ["assumptions"]
    if field in prov:
        t = TAG.get(prov[field].get("tag"), "[S]")
        return "[A]" if t == "[S]" and field in (a.get("assumed") or []) else t
    if field in (a.get("defaulted") or []):
        return "[A default]"
    if field in (a.get("assumed") or []):
        return "[A]"
    return "[D]"


def _price_tag(econ: dict, prov: dict) -> str:
    rung = econ["forecast"]["price"]["rung"]
    if rung == "user":
        return TAG.get((prov.get("annual_net_price_usd") or {}).get("tag"), "[S]")
    return "[S]" if rung == "same_moa" else "[A]"


def question_note(payload: dict) -> dict:
    """What question the verdict answers: the thesis, or this round at its price."""
    if payload.get("question") == "round":
        return _para("Question answered: invest in this round. Invest therefore needs data on the asset itself (not only "
                     "on the target and the class), and the round price is tested against the cost of capital.", "scorer")
    return _para("Question answered: is the thesis investable (target + mechanism + indication). Invest here means the "
                 "thesis is worth backing; it does not price a round and does not need data on a specific asset. Give "
                 "round terms (pre-money, investment, cash) to ask about a round.", "scorer")


def caps_lines(payload: dict) -> list[dict]:
    return [_para(f"Capped at Conditional: {c['reason']}.", "scorer") for c in payload["result"]["verdict"].get("caps") or []]


def economics_unavailable(payload: dict) -> list[dict]:
    res = payload["result"]
    m = payload.get("market") or {}
    why = (res.get("economics_note") or "no market inputs").removesuffix(": economics not run")
    lines = [_para(f"Economics not run: {why}. The verdict rests on the "
                   "scientific and clinical evidence alone; a market cannot lower or confirm it.", "scorer")]
    lines += [_para(n, "scorer") for n in m.get("notes") or []]
    return lines


def commercial_section(payload: dict) -> list[dict]:
    """Patients, price, share, peak sales, rNPV, Monte Carlo, what you have to believe. Numbers from code only."""
    res = payload["result"]
    econ = res.get("economics")
    if "economics" not in res:                       # scorer 1.x: nothing to show, the LLM / template writes it
        return []
    if not econ:
        return economics_unavailable(payload)
    prov = (payload.get("market") or {}).get("provenance") or {}
    a, fc, b, mc = econ["assumptions"], econ["forecast"], econ["base"], econ["monte_carlo"]
    out = []
    pp = prov.get("us_patients") or {}
    rng = a.get("us_patients_range")
    out.append(_para(f"US patients: {a['us_patients']:,} {_tag('us_patients', econ, prov)}"
                     + (f" ({pp['basis']}, {pp.get('source')})" if pp.get("basis") else "")
                     + (f"; range {rng[0]:,}–{rng[1]:,}" if rng else "") + ".", "scorer"))
    funnel = ", ".join(f"{k.replace('_', ' ')} {_pct(a[k])} {_tag(k, econ, prov)}"
                       for k in ("eligible_share", "diagnosis_rate", "treatment_rate", "compliance"))
    note = (" The funnel defaults assume every patient is eligible, diagnosed and treated: peak sales are an upper "
            "bound until the company gives the treatable subgroup." if {"eligible_share", "diagnosis_rate",
                                                                         "treatment_rate"} & set(a.get("defaulted") or []) else "")
    out.append(_para(f"Treated patients: {funnel}.{note}", "scorer"))
    pr = fc["price"]
    groups = []
    seen: set[str] = set()
    for key, label in (("price_same_moa", "same mechanism"), ("price_same_indication", "other drugs for the disease")):
        rows = [x for x in (prov.get(key) or {}).get("analogues") or [] if str(x["generic"]).lower() not in seen]
        seen |= {str(x["generic"]).lower() for x in rows}
        if rows:
            groups.append(f"{label}: " + ", ".join(f"{str(x['generic']).title()} ${x['net']:,.0f}" for x in rows[:6]))
    out.append(_para(f"Net price ${pr['value']:,.0f} per patient-year {_price_tag(econ, prov)} (range "
                     f"${pr['range'][0]:,.0f}–${pr['range'][1]:,.0f}); {pr['basis']}"
                     + (f". CMS Medicare cost per patient, Part D net of an assumed 25% rebate: {'; '.join(groups)}"
                        if groups else "") + ".", "scorer"))
    sh = fc["peak_share"]
    out.append(_para(f"Peak share {_pct(sh['value'])} [A]: {sh['basis'].replace(' [A]', '')}; {fc['years_to_peak']:g} "
                     f"years to peak {_tag('years_to_peak', econ, prov)}; exclusivity after launch "
                     f"{a['exclusivity_years_after_launch']:g} years {_tag('exclusivity_years_after_launch', econ, prov)}"
                     + (f" ({a['exclusivity_basis']})" if a.get("exclusivity_basis") else "") + ".", "scorer"))
    out.append(_para(f"Peak US sales {_m(b['peak_us_m'])}, worldwide {_m(b['peak_total_m'])} [D]. Launch in "
                     f"{b['launch_in_y']:.1f} years with P(approval) {_pct(b['pos'])} [D]. rNPV {_m(b['rnpv_m'])} at "
                     f"Sertkaya trial costs, {_m(econ['worse_cost_case']['rnpv_m'])} at DiMasi costs [D].", "scorer"))
    bep = econ.get("break_even_price_usd")
    out.append(_para(f"Monte Carlo ({mc['draws']} draws): rNPV P10 {_m(mc['p10_m'])}, P50 {_m(mc['p50_m'])}, P90 "
                     f"{_m(mc['p90_m'])}; P(rNPV > 0) {_pct(mc['p_positive'])}. Break-even net price "
                     + ("not reachable" if bep is None else f"${bep:,.0f} per patient-year") + " [D].", "scorer"))
    sc = fc.get("scenarios") or {}
    if sc:
        out.append(_para("Scenarios: " + "; ".join(
            f"{n} peak US sales {_m(sc[n]['peak_us_m'])}, rNPV {_m(sc[n]['rnpv_m'])} ({sc[n]['why']})"
            for n in ("bear", "median", "bull") if n in sc) + " [D].", "scorer"))
    tor = fc.get("tornado") or []
    if tor:
        be = fc.get("break_even") or {}
        shown = {"patients": lambda v: f"{v:,.0f} treated patients", "annual_net_price_usd": lambda v: f"${v:,.0f}/yr",
                 "peak_share": _pct, "p_approval": _pct}
        out.append(_para("What you have to believe: the value swings most with "
                         + ", ".join(f"{t['driver'].replace('_', ' ')} ({_m(t['low_rnpv_m'])} to {_m(t['high_rnpv_m'])}"
                                     + (", decides the sign" if t["crosses_zero"] else "") + ")" for t in tor[:3])
                         + ". Break-even, each alone: "
                         + "; ".join(f"{k.replace('_', ' ')} ≥ {'not reachable' if v is None else shown[k](v)}"
                                     for k, v in be.items() if k in shown) + " [D].", "scorer"))
    if econ.get("drives_verdict"):
        made = {k: v for k, v in econ["facts"].items()}
        out.append(_para(f"Patients and price are sourced or entered, so the economics count in the verdict "
                         f"(economic facts: {', '.join(f'{k} = {_value_text(v)}' for k, v in made.items()) or 'none'}).",
                         "scorer"))
    else:
        out.append(_para(f"Shown, not used in the verdict: {res.get('economics_note')}. Economics can only lower a "
                         "verdict, and only from sourced or entered numbers.", "scorer"))
    out += [_para(n, "scorer") for n in (payload.get("market") or {}).get("notes") or []]
    return out


def capital_section(payload: dict) -> list[dict]:
    """Capital and time to the next milestone, financing to approval, and the round view. Numbers from code only."""
    res = payload["result"]
    if "economics" not in res:
        return []
    econ = res.get("economics")
    if not econ:
        ms = _milestone_without_market(res)
        return ([_para(ms, "scorer")] if ms else []) + [
            _para("Value after the milestone, rNPV and the round view need a patient count (Orphanet or "
                  "market.us_patients).",
                  "scorer")]
    ms, out = econ["milestone"], []
    plan0 = econ["plan"][0]
    out.append(_para(f"Next milestone: {ms['next_milestone']} in {ms['years_to_milestone']:.1f} years, P(success) "
                     f"{_pct(ms['p_milestone_success'])}; capital ${ms['capital_to_milestone_m'][0]:.0f}m (Sertkaya "
                     f"trial costs in 2024 dollars, ${plan0['trial_cost_m']:.0f}m, plus ${plan0['overhead_m']:.0f}m "
                     f"company overhead) to ${ms['capital_to_milestone_m'][1]:.0f}m (DiMasi) [D].", "scorer"))
    out.append(_para(f"Capital to approval ${ms['capital_to_approval_m'][0]:.0f}–{ms['capital_to_approval_m'][1]:.0f}m; "
                     f"expected ${ms['expected_capital_to_approval_m']:.0f}m when development stops after a failure; "
                     f"about {ms['financing_rounds_to_approval']} financing rounds [D].", "scorer"))
    if ms.get("rnpv_after_milestone_m") is not None:
        out.append(_para(f"Value once the milestone is passed (rNPV, what a licensee or buyer would pay for): "
                         f"{_m(ms['rnpv_after_milestone_m'])}, against {_m(econ['base']['rnpv_m'])} today [D].", "scorer"))
    if "cash_m" in ms:
        out.append(_para(f"Company cash ${ms['cash_m']:.0f}m [entered]: "
                         + ("does NOT reach the milestone (runway short)." if ms["runway_short"]
                            else "reaches the milestone."), "scorer"))
    iv = econ.get("investor")
    if iv:
        fc = econ["forecast"]
        rp = fc.get("required_peak_for_post_money_m")
        out.append(_para(f"This round: post-money ${iv['post_money_m']:.0f}m [entered], stake {_pct(iv['stake_now'])} now and "
                         f"{_pct(iv['stake_at_exit'])} at exit; expected MOIC {iv['moic_expected']:.2f}x "
                         f"({iv['moic_if_success']:.2f}x if approved), expected IRR {_pct(iv['irr_expected'])} against a "
                         f"required {_pct(iv['required_irr'])} [D].", "scorer"))
        out.append(_para(f"Highest pre-money at which the round earns its cost of capital: ${iv['max_pre_money_m']:.0f}m [D]"
                         + ("" if rp is None else f"; the post-money needs peak US sales of {_m(rp)}")
                         + ". " + ("The round price is justified." if iv["earns_cost_of_capital"]
                                   else "The round is priced above what the expected value supports."), "scorer"))
    lic = econ.get("license")
    if lic:
        out.append(_para(f"Licensing the asset out: licensor NPV {_m(lic['licensor_npv_m'])}, "
                         f"{_m(lic['vs_own_rnpv_m'])} against developing it alone [D].", "scorer"))
    return out


def _milestone_without_market(res: dict) -> str | None:
    """Capital to the next milestone needs only the phase (Sertkaya costs), not a market."""
    try:
        from unobio_scoring import economics as E
        facts = dict(res["facts"]["given"])
        plan = E.phase_plan(facts, {"cost_case": "base"})
        worse = E.phase_plan(facts, {"cost_case": "worse"})
    except Exception:                                             # noqa: BLE001 - phase unknown, scorer 1.x
        return None
    st, w = plan[0], worse[0]
    return (f"Next milestone: complete {st['stage']} in {st['years']:.1f} years, P(success) {_pct(st['p_success'])}; "
            f"capital ${st['cost_m']:.0f}m (Sertkaya trial costs plus company overhead) to ${w['cost_m']:.0f}m (DiMasi); "
            f"capital to approval ${sum(x['cost_m'] for x in plan):.0f}–{sum(x['cost_m'] for x in worse):.0f}m [D].")


# --- translation chain (code) -----------------------------------------------------------------------------------------
CHAIN = [  # link, title, asset fact, class fact
    (1, "Molecular effect (target perturbation changes the disease phenotype)", "animal_model_response",
     "perturbation_evidence"),
    (2, "Human exposure at the site of action", "link_exposure", "class_exposure_human"),
    (3, "Target engagement in humans", "link_target_engagement", "class_target_engagement_human"),
    (4, "Biological response (pharmacodynamic biomarker) in humans", "link_pd_response", "class_pd_response_human"),
    (5, "Patient benefit", "own_ph2_positive", None),
]
CHAIN_KEYS = {1: "animal_response", 2: "exposure", 3: "target_engagement", 4: "pd_response", 5: "clinical_benefit"}


def _fact_claim(claims: list[dict], status: dict[str, str], fact: str) -> dict | None:
    """The claim the verdict used for a fact (or one waiting for confirmation)."""
    rows = [c for c in claims if c["fact"] == fact and status.get(c["id"]) in ("used", "pending")]
    return next((c for c in rows if status.get(c["id"]) == "used"), rows[0] if rows else None)


def _evidence_note(claim: dict) -> str:
    """"Tominersen; Hawellek 2022 (PubMed)" for LLM class claims, the source names for structured ones."""
    srcs = claim.get("sources") or []
    drugs = sorted({s["drug"].title() for s in srcs if s.get("drug") and s["drug"] != "TARGET"})
    docs = []
    for s in srcs:
        label = (s.get("name") or s.get("datasource") or s.get("kind") or "").split(":")[0].strip()
        if label and label not in docs:
            docs.append(label)
    return "; ".join(filter(None, [", ".join(drugs), ", ".join(docs[:3])])) or claim["statement"][:80]


def translation_chain(claims: list[dict], status: dict[str, str], chain: dict | None, dd: dict[str, str]
                      ) -> tuple[list[dict], list[int]]:
    """One paragraph per link: the asset's status, the class status, what was only tested. Returns (paragraphs,
    links with nothing shown for the asset)."""
    out, missing = [], []
    for n, title, asset_fact, class_fact in CHAIN:
        ids, parts = [], []
        a = _fact_claim(claims, status, asset_fact)
        if n == 5:
            fail = _fact_claim(claims, status, "own_trial_failed_efficacy")
            if a and a["value"] is True:
                parts.append("asset: shown (own Phase 2 met its primary endpoint)")
                ids.append(a["id"])
            elif fail and fail["value"] is True:
                parts.append("asset: broken (own trial failed for efficacy)")
                ids.append(fail["id"])
            else:
                parts.append("asset: unknown")
            appr = _fact_claim(claims, status, "approved_same_moa_count")
            eff = _fact_claim(claims, status, "moa_failures_efficacy_ph23")
            if appr and appr["value"]:
                parts.append(f"class: shown ({appr['statement'].rstrip('.')})")
                ids.append(appr["id"])
            if eff and eff["value"]:
                parts.append(f"class: not shown for {eff['value']} drug(s) that failed for efficacy"
                             + (" (waits for confirmation)" if status.get(eff["id"]) == "pending" else ""))
                ids.append(eff["id"])
        else:
            if a is not None:
                parts.append(f"asset: {'shown' if a['value'] is True else 'broken' if a['value'] is False else a['value']}")
                ids.append(a["id"])
            else:
                parts.append("asset: unknown")
            k = _fact_claim(claims, status, class_fact)
            who = "target" if n == 1 else "class"         # link 1: the target itself; links 2-4: other drugs
            if k is not None:
                word = "shown" if k["value"] is True else "looked for, not shown"
                parts.append(f"{who}: {word} ({_evidence_note(k)})"
                             + (" (waits for confirmation)" if status.get(k["id"]) == "pending" else ""))
                ids.append(k["id"])
            elif n == 1 and (corr := _fact_claim(claims, status, "correlational_evidence")):
                parts.append("target: correlational evidence only (expression or pathway), not causal")
                ids.append(corr["id"])
            else:
                parts.append(f"{who}: unknown")
        tested = ((chain or {}).get(CHAIN_KEYS[n]) or {}).get("tested_in") or []
        if tested:
            parts.append(f"registered as a trial outcome in {', '.join(tested[:3])}" + ("…" if len(tested) > 3 else "")
                         + " (tested; the result is not in the data read)")
        if not (a is not None and a["value"] is True):
            missing.append(n)
            if dd.get(asset_fact):
                parts.append(f"to settle: {dd[asset_fact]}")
        out.append(_para(f"Link {n}, {title}: " + "; ".join(parts) + ".", "scorer", ids))
    return out, missing


def used_genetics(claims: list[dict], status: dict[str, str]) -> dict | None:
    """The genetic_support claim the verdict used (status `used`), if any."""
    return next((c for c in claims if c["fact"] == "genetic_support" and status.get(c["id"]) == "used"), None)


def genetics_lines(claims: list[dict], status: dict[str, str]) -> list[dict]:
    """Code-written first line of the scientific thesis when the genetics is Mendelian for a subtype only, so the memo
    never reads as Mendelian evidence for the disease itself (the statement names the subtype from the source)."""
    g = used_genetics(claims, status)
    if not g or g["value"] != "mendelian_subtype":
        return []
    return [_para(f"Genetics: {g['statement']}", "scorer", [g["id"]])]


# --- the report --------------------------------------------------------------------------------------------------------
def mechanism_unknowns(mechanism: dict | None) -> list[dict]:
    """Why counts of same-mechanism drugs may be missing (review F36, F37): shown, never silently dropped."""
    if not mechanism:
        return []
    out = []
    unsure = mechanism.get("unsure_drugs") or []
    if not mechanism.get("input_action"):
        out.append(_para("Direction of action is not known from the input (inhibit or activate?). Drugs on the target "
                         "are therefore not counted as the same mechanism: approved and Phase 3 counts, me-too and class "
                         "safety are unknown. Give the direction (for example 'HER2 inhibitor antibody') or check it in "
                         "diligence.", "scorer"))
    elif unsure:
        out.append(_para(f"{len(unsure)} drug(s) on the target have no known direction of action "
                         f"({', '.join(n.title() for n in unsure[:5])}{'…' if len(unsure) > 5 else ''}), so they may or "
                         "may not be the same mechanism: counts of approved and Phase 3 drugs are lower bounds and are "
                         "not used.", "scorer"))
    for x in mechanism.get("excluded_drugs") or []:
        out.append(_para(f"Not counted as the same mechanism: {x['name'].title()} ({x['reason']}).", "scorer"))
    if mechanism.get("list_complete") is False:
        out.append(_para("The list of drugs on the target is incomplete, so counts of approved and Phase 3 drugs with "
                         "the same mechanism are lower bounds and are not used.", "scorer"))
    return out


def build_report(run: dict, claims: list[dict], score: dict, status: dict[str, str], llm: LLM | None,
                 chain: dict | None = None, dd: dict[str, str] | None = None, mechanism: dict | None = None) -> dict:
    """`chain`: the run's translation summary (translation.chain_summary); `dd`: fact -> due-diligence question."""
    payload = score["payload"]
    decision = payload["result"]["verdict"]["decision"]
    claims_by_id = {c["id"]: c for c in claims}
    if dd is None:
        from backend.app.pipeline import CFG
        dd = {name: spec["dd"] for name, spec in CFG.facts.items() if spec.get("dd")}
    chain_paras, missing_links = translation_chain(claims, status, chain, dd)
    econ_paras = {"commercial_opportunity": commercial_section(payload),
                  "capital_to_next_milestone": capital_section(payload)}
    written: dict[str, list] = {}
    issues: list[str] = []
    attempts = 0
    if llm is not None:
        facts_pack = pack(run, claims, payload, status)
        facts_pack["translation_chain"] = [p["text"] for p in chain_paras]
        facts_pack["economics_lines"] = {"commercial_opportunity": [p["text"] for p in econ_paras["commercial_opportunity"]],
                                         "capital_to_next_milestone": [p["text"] for p in econ_paras["capital_to_next_milestone"]]}
        g = used_genetics(claims, status)
        written, issues, attempts = write_llm_sections(llm, facts_pack, claims_by_id, decision,
                                                       genetics=g["value"] if g else None)

    sections = []
    for sid, title, by in SECTIONS:
        if sid == "recommendation":
            paras, gen = recommendation_header(payload) + written.get(sid, []), "code+llm" if sid in written else "code"
        elif sid == "critical_unknowns":
            paras, gen = critical_unknowns(payload, claims_by_id), "code"
            paras = mechanism_unknowns(mechanism) + paras
            if missing_links:
                paras = [_para("Missing links in the translation chain for this asset: "
                               + ", ".join(f"link {n}" for n in missing_links)
                               + ". Public data can show them only for other drugs of the mechanism; for this asset "
                               "they need its own data (Phase 1 PK/PD, receptor occupancy, biomarkers) from the "
                               "company.", "scorer")] + [p for p in paras if not p["text"].startswith("No pending,")]
        elif sid == "diligence_questions":
            paras, gen = diligence_questions(payload), "code"
        elif sid == "sources":
            continue
        elif sid in written:
            paras, gen = written[sid], "llm"
        else:
            paras, gen = template_section(sid, claims, status), "template"
        if sid == "human_translation_thesis":
            paras = chain_paras + [x for x in paras if x["kind"] != "scorer" or x["claim_ids"]]
        if sid == "scientific_thesis" and genetics_lines(claims, status):
            paras = genetics_lines(claims, status) + paras
            gen = "code" if gen == "template" else f"code+{gen}"
        if econ_paras.get(sid):            # code numbers first; the LLM / template text interprets them
            paras = econ_paras[sid] + [p for p in paras if p["kind"] != "scorer" or p["claim_ids"]]
            gen = "code" if gen == "template" else f"code+{gen}"
        if sid == "key_risks":
            kept = [p for p in paras if p["kind"] != "scorer" or p["claim_ids"]]    # drop "no claims" if rules fired
            paras = (fired_rules(payload) + kept) or paras
        sections.append({"id": sid, "title": title, "generated_by": gen, "paragraphs": paras})
    cited = {i for s in sections for p in s["paragraphs"] for i in p["claim_ids"]}
    sections.append({"id": "sources", "title": TITLES["sources"], "generated_by": "code",
                     "paragraphs": sources(claims, cited)})
    norm = run.get("normalized") or {}
    return {"run_id": run["id"], "version": score["version"], "decision": decision,
            "disease": (norm.get("disease") or {}).get("name"), "target": (norm.get("target") or {}).get("symbol"),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "llm": {"used": llm is not None, "model": getattr(llm, "model", None), "attempts": attempts,
                    "issues": issues, "calls": list(getattr(llm, "calls", None) or [])},
            "sections": sections}


def to_markdown(report: dict) -> str:
    lines = [f"# {report['disease']} + {report['target']}: {report['decision']}", "",
             f"Run `{report['run_id']}`, verdict version {report['version']}, generated {report['generated_at']}."
             + (f" LLM: {report['llm']['model']}." if report["llm"]["used"] else " No LLM: template text."), ""]
    for s in report["sections"]:
        lines += [f"## {s['title']}", ""]
        for p in s["paragraphs"]:
            cite = f" [{', '.join(p['claim_ids'])}]" if p["claim_ids"] else ""
            if s["id"] == "diligence_questions":
                lines.append(f"- {p['text']}")
            elif s["id"] == "sources":
                lines.append(f"- {p['text']}{cite}")
            elif p["kind"] == "inference":
                lines += [f"*AI inference:* {p['text']}{cite}", ""]
            else:
                lines += [f"{p['text']}{cite}", ""]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

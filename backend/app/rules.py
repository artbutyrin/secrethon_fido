"""2.6: evidence without an LLM. Two jobs that the LLM did before, now done by code on free data:

1. Why a trial stopped (`label_stops`): Open Targets already classifies every stated stop reason
   (`trialStopReasonCategories`, the classifier of Razuvayevskaya et al. 2024: Negative, Safety_Sideeffects,
   Insufficient_Enrollment, Business_Administrative, ...). Code maps the category to the run's labels and checks it
   against the words of the reason (a "Negative" stop that names liver toxicity is a safety stop). Trials without a
   category (registry rows) are labelled from the words alone.
2. What a trial publication says about the primary outcome (`outcome_findings`): the PubMed abstracts the run already
   downloads (by drug and by NCT number) are split into sentences; a sentence that says the primary endpoint was not
   met, or that the trial stopped for futility, is a "clinical benefit not shown" finding; one that says it was met
   is "shown". Only abstracts of human trials that name the drug and the disease are read; an abstract that says both
   is skipped.

Both return the same shapes as the LLM steps (trials.label_trials, translation.extract_findings), so everything
after them is unchanged. Every quote is an exact substring of its source. Hits carry source "ot_category", "rules"
or "rules_pubmed": the claims built from them are structured (code-made), not LLM claims waiting for a person.
"""
from __future__ import annotations

import re
from typing import Any

from backend.app.trials import quote_negated

_I = re.I
EFFICACY = re.compile(
    r"futil\w*|lack of (?:efficacy|benefit|effect|response)|insufficient (?:efficacy|benefit)|"
    r"no (?:evidence of )?(?:potential )?(?:efficacy|clinical benefit|benefit)|inefficacy|"
    r"(?:did not|does not|failed to|unlikely to|would not|will not) (?:meet|achieve|reach|show|demonstrate)"
    r"[^.;]{0,40}?(?:end ?point|efficacy|benefit|objective|outcome)|"
    r"primary (?:efficacy )?(?:end ?point|outcome)s?[^.;]{0,40}?(?:not|unlikely)\b[^.;]{0,20}?(?:met|achieved|reached)|"
    r"negative (?:results?|outcome|interim|efficacy)|not (?:be )?(?:efficacious|effective)\b", _I)
SAFETY = re.compile(
    r"safety|adverse|side[ -]?effects?|toxicit\w*|death|died|fatal|liver|hepat\w*|benefit[- /]risk|risk[- /]benefit|"
    r"tolerab\w*|serious (?:adverse )?events?|clinical hold|abnormal [\w ]{0,30}tests?", _I)
ENROLLMENT = re.compile(r"recruit\w*|enrol\w*|accrual|accru\w*|participants? (?:could not|were not) (?:be )?found", _I)
BUSINESS = re.compile(r"business|strateg\w*|portfolio|commercial|company (?:closure|decision)|sponsor(?:'s)? decision|"
                      r"acqui\w+|merger|prioriti\w+|development (?:was |has been )?(?:discontinued|stopped|halted)", _I)
FUNDING = re.compile(r"\bfund\w*", _I)

# Open Targets category -> run label. "Negative" is checked against the words (see label_stops).
CATEGORY = {"negative": "efficacy", "safety_sideeffects": "safety", "insufficient_enrollment": "enrollment",
            "business_administrative": "business", "logistics_resources": "other", "covid19": "other",
            "study_design": "other", "study_staff_moved": "other", "regulatory": "other", "another_study": "other",
            "ethical_reason": "other", "insufficient_data": "other", "endpoint_met": "other", "success": "other",
            "interim_analysis": "other", "no_context": "unknown", "invalid_reason": "unknown",
            "uncategorised": "unknown"}
WORDS = (("efficacy", EFFICACY), ("safety", SAFETY), ("enrollment", ENROLLMENT), ("business", BUSINESS),
         ("funding", FUNDING))


def _quote(reason: str, rx: re.Pattern) -> str | None:
    m = rx.search(reason or "")
    return m.group(0) if m else None


def label_reason(reason: str, categories: list[str] | None) -> list[dict]:
    """Labels for one stated stop reason: [{label, quote, verified, support, source}]."""
    reason = reason or ""
    found: dict[str, dict] = {}
    for label, rx in WORDS:
        q = _quote(reason, rx)
        if q and not (label == "efficacy" and quote_negated(q, reason)):
            found[label] = {"label": label, "quote": q, "source": "rules"}
    for cat in categories or []:
        label = CATEGORY.get(str(cat).strip().lower())
        if label is None or label in found:
            continue
        if label == "efficacy" and "safety" in found and "efficacy" not in found:
            continue                       # "Negative" + liver toxicity in the words: a safety stop, not efficacy
        if label in ("unknown", "other") and found:
            continue
        found[label] = {"label": label, "quote": reason[:120], "source": "ot_category", "category": cat}
    if not found:
        found["unknown"] = {"label": "unknown", "quote": "", "source": "rules"}
    out = list(found.values())
    for x in out:
        x.update(verified=True, support=True if x["label"] != "unknown" else None)
    return out


def label_stops(trials: list[dict]) -> dict[str, Any]:
    """Same shape as trials.label_trials: {"labels": {nct: [...]}, "errors": []}. No LLM, no cost."""
    return {"labels": {t["nct"]: label_reason(t.get("why_stopped") or "", t.get("ot_categories"))
                       for t in trials if t.get("why_stopped")},
            "errors": [], "method": "rules"}


# --- outcomes from trial abstracts ------------------------------------------------------------------------------------
_SENT = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")
_HUMAN_TRIAL = re.compile(r"randomi[sz]ed|placebo|double[- ]blind|phase (?:2|3|ii|iii)\b|phase (?:2|3)[ab]?\b", _I)
_PHASE3 = re.compile(r"phase (?:3|iii)\b|phase 3[ab]?\b", _I)
_ANIMAL = re.compile(r"\b(?:mice|mouse|rats?|murine|rodents?|monkeys?|primates?|in vitro|cell lines?)\b", _I)
FAILED = re.compile(
    r"(?:did not|does not|failed to|was not able to)\s+(?:significantly\s+)?(?:meet|achieve|reach)\s+(?:its|the|their)?\s*"
    r"(?:co-?)?primary|"
    r"primary (?:efficacy )?(?:end ?point|outcome)s?\s+(?:was|were)\s+not\s+(?:met|achieved|reached)|"
    r"primary (?:efficacy )?(?:end ?point|outcome)s?[^.;]{0,80}?(?:no|not)\s+(?:statistically\s+)?significant|"
    r"no (?:statistically )?significant (?:difference|improvement|reduction|benefit|effect)[^.;]{0,80}?primary|"
    r"(?:stopped|terminated|halted|discontinued) (?:early )?(?:for|due to|because of) (?:futility|lack of efficacy)|"
    # 2.7: outcome trials state the miss on the event itself ("did not reduce the rate of major adverse cardiovascular
    # events", "did not slow cognitive decline")
    r"(?:did not|failed to)\s+(?:significantly\s+)?(?:reduce|lower|improve|prevent|slow|delay)\s+[^.;]{0,60}?"
    r"(?:primary|major adverse|mortality|death|events|progression|decline)|"
    r"did not result in (?:a )?(?:significantly )?(?:lower|reduced|fewer|better|improved)[^.;]{0,60}?"
    r"(?:events|mortality|death|rate|outcomes?)", _I)
MET = re.compile(
    r"(?:met|achieved|reached)\s+(?:its|the|their|both)\s+(?:co-?)?primary (?:efficacy )?(?:end ?points?|outcomes?)|"
    r"primary (?:efficacy )?(?:end ?point|outcome)s?\s+(?:was|were)\s+(?:met|achieved)", _I)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text or "") if s.strip()]


def outcome_findings(docs: list[dict], disease: dict, drug_names: list[str]) -> list[dict]:
    """clinical_benefit findings from PubMed abstracts, same shape as translation.extract_findings.
    `docs`: translation.documents(tr) (kind "pubmed" are read; labels are not trial results)."""
    words = {w.lower() for w in [disease.get("name"), *(disease.get("synonyms") or [])] if w and len(w) > 3}
    allowed = {n.upper() for n in drug_names}
    out: list[dict] = []
    for doc in docs:
        if doc.get("kind") != "pubmed":
            continue
        drug = (doc.get("drug") or "").upper()
        text = doc.get("text") or ""
        low = text.lower()
        if drug not in allowed or drug.lower() not in low or not any(w in low for w in words):
            continue
        if not _HUMAN_TRIAL.search(text) or (_ANIMAL.search(text) and not re.search(r"patients|participants", low)):
            continue
        sents = _sentences(text)
        failed = [s for s in sents if FAILED.search(s)]
        met = [s for s in sents if MET.search(s) and not FAILED.search(s)]
        if failed and met:
            continue                                           # mixed (e.g. one of two primaries): not decided here
        for result, hits in (("not_shown", failed), ("shown", met)):
            if hits:
                q = hits[0][:300]
                out.append({"doc_id": doc["id"], "doc_kind": "pubmed", "url": doc.get("url"), "title": doc.get("title"),
                            "drug": drug, "link": "clinical_benefit", "result": result, "species": "human",
                            "in_disease": True, "quote": q, "verified": q in text, "support": True,
                            "source": "rules_pubmed", "phase3": bool(_PHASE3.search(text))})
    return out


def positive_phase3_from_findings(findings: list[dict]) -> set[str]:
    """Drugs with a Phase 3 abstract (rules) saying the primary endpoint was met in this disease."""
    return {f["drug"] for f in findings if f.get("source") == "rules_pubmed" and f["result"] == "shown"
            and f.get("phase3") and f["verified"]}

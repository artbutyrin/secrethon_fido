"""Pipeline stage 3, free-text branch: why trials stopped.

1. Code picks stopped trials (terminated / withdrawn / suspended, with a reason) from the collected drug data.
2. The LLM labels each reason (efficacy, safety, enrollment, ...) and must quote the words it relied on.
3. Code checks that every quote is really in the trial's text; a label without a found quote is not used.
   A second, narrow LLM check asks whether each efficacy or safety quote really says that (support.py):
   "The primary endpoint was achieved" is a real quote but not an efficacy failure.
4. Code counts and turns the counts into claims with origin "llm". The LLM never sees or sets a count.

The scorer then holds back any LLM value that alone could kill a program or cost two points, until a second
independent source (here: a different sponsor) or a human confirms it.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from backend.app.facts import Claims, _same_mechanism, drug_key, n_drugs
from backend.app.llm import LLM, LLMError
from backend.app.batching import fixed_chars, pack, pmap
from backend.app.support import check_support, too_big

STOPPED = {"TERMINATED", "WITHDRAWN", "SUSPENDED"}
PH23 = {"PHASE_2", "PHASE_2_3", "PHASE_3"}
LABELS = ["efficacy", "safety", "enrollment", "business", "funding", "other", "unknown"]
BATCH = 25
MAX_TRIALS = 120
QUOTE_MATCH = 0.9
ENROLLMENT_MIN, ENROLLMENT_SHARE = 5, 1 / 3
_NCT = re.compile(r"nct\d{8}", re.I)

SYSTEM = """You classify why clinical trials stopped. For each trial you get its ID and the sponsor's stated reason.
Give one or more labels, each with a short quote copied word for word from the reason that supports it.
Labels:
- efficacy: futility, lack or absence of efficacy, primary endpoint not met or unlikely to be met, negative results.
- safety: adverse events, toxicity, a safety signal, a benefit-risk change caused by side effects.
- enrollment: slow, poor or insufficient recruitment or accrual.
- business: sponsor's business, strategic or portfolio decision, development discontinued without a stated
  scientific reason, company closure or acquisition.
- funding: lack or withdrawal of funding.
- other: anything else that is stated (COVID-19, logistics, investigator left, design or protocol change,
  regulatory feedback, another study answered the question).
- unknown: no reason is given, or the text only says who decided (for example "on the advice of the DSMB").
Rules: use only what the text says; do not infer from the drug or the disease. A trial stopped because another
trial of the same drug was stopped for futility is efficacy. If both efficacy and safety are stated, give both.
The quote must be an exact substring of the reason, at most 20 words. Return every trial you were given."""

SCHEMA = {
    "type": "object",
    "properties": {"trials": {"type": "array", "items": {
        "type": "object",
        "properties": {"nct": {"type": "string"},
                       "labels": {"type": "array", "items": {
                           "type": "object",
                           "properties": {"label": {"type": "string", "enum": LABELS}, "quote": {"type": "string"}},
                           "required": ["label", "quote"], "additionalProperties": False}}},
        "required": ["nct", "labels"], "additionalProperties": False}}},
    "required": ["trials"], "additionalProperties": False,
}


# --- 1. pick stopped trials -----------------------------------------------------------------------------------------
def nct_of(report: dict) -> str | None:
    for text in (report.get("id"), report.get("url")):
        m = _NCT.search(text or "")
        if m:
            return m.group(0).upper()
    return None


def _indication_ids(drug: dict) -> set[str]:
    return {(i.get("disease") or {}).get("id") for i in ((drug.get("indications") or {}).get("rows") or [])} - {None}


def stopped_trials(collected: dict, disease_id: str, target_id: str, action: str | None,
                   broader_ids: set[str] | frozenset = frozenset()) -> list[dict]:
    """One record per stopped trial with a reason, from the target query and the disease query."""
    trials: dict[str, dict] = {}
    for part, from_target in (("target_drugs", True), ("disease_drugs", False)):
        p = collected["parts"].get(part) or {}
        if not p.get("ok"):
            continue
        for row in p["data"].get("rows") or []:
            drug = row.get("drug") or {}
            same = from_target and _same_mechanism(drug, target_id, action)[0]
            for rep in row.get("clinicalReports") or []:
                status = (rep.get("trialOverallStatus") or "").upper()
                why = (rep.get("trialWhyStopped") or "").strip()
                nct = nct_of(rep)
                if status not in STOPPED or not why or not nct:
                    continue
                diseases = {(d.get("disease") or {}).get("id") for d in rep.get("diseases") or []} - {None}
                t = trials.setdefault(nct, {
                    "nct": nct, "why_stopped": why, "status": status, "stage": rep.get("clinicalStage"),
                    "sponsor": (rep.get("trialSponsor") or {}).get("name") or "", "start": rep.get("trialStartDate"),
                    "url": rep.get("url") or f"https://clinicaltrials.gov/study/{nct}",
                    "ot_categories": rep.get("trialStopReasonCategories") or [], "diseases": set(),
                    "in_disease": False, "drugs": set(), "same_mechanism_drugs": set()})
                t["diseases"] |= diseases
                # 2.7: a report with no disease ID (evacetrapib's futility stops) belongs to this disease when the drug
                # was developed for it (an indication mapped to the disease ID)
                here_ids = {disease_id} | set(broader_ids)   # 2.8: a broader disease includes this one's patients
                unmapped_here = not diseases and from_target and bool(here_ids & _indication_ids(drug))
                t["in_disease"] = t["in_disease"] or not from_target or bool(here_ids & diseases) or unmapped_here
                t["drugs"].add(drug_key(drug.get("name")))
                if same:
                    t["same_mechanism_drugs"].add(drug_key(drug.get("name")))
    out = sorted(trials.values(), key=lambda t: (not t["same_mechanism_drugs"], t["nct"]))
    for t in out:
        t["diseases"], t["drugs"] = sorted(t["diseases"]), sorted(t["drugs"])
        t["same_mechanism_drugs"] = sorted(t["same_mechanism_drugs"])
    return out


# Same-mechanism trials outside this disease (or outside Phase 2/3) are read only by the safety count, which counts
# distinct drugs. A few per drug are enough to find a safety stop; sending all of them made a crowded class (GLP-1:
# hundreds of registry trials) cost many LLM calls without changing a count. Reasons naming a safety word go first.
OTHER_PER_DRUG = 4
_SAFETY_HINT = re.compile(r"safety|adverse|toxic|tolerab|death|died|fatal|liver|hepat|enzyme|cardi|side.effect|"
                          r"benefit.risk|risk.benefit|dsmb|data (?:and )?safety monitoring", re.I)
_STAGE = {"PHASE_3": 6, "PHASE_2_3": 5, "PHASE_2": 4, "PHASE_1_2": 3, "PHASE_1": 2, "EARLY_PHASE_1": 1}


def to_label(trials: list[dict], limit: int = MAX_TRIALS) -> list[dict]:
    """The trials whose stop reasons the LLM reads, in three groups:
    1. same-mechanism trials in this disease, Phase 2/3: always (they decide the efficacy count);
    2. other same-mechanism trials (other diseases or phases): up to OTHER_PER_DRUG per drug, a safety word in the
       reason first, then the later phase (only the safety count reads them);
    3. other Phase 2/3 trials in the disease (for the enrollment rule), up to the limit."""
    core = [t for t in trials if t["same_mechanism_drugs"] and t["in_disease"] and t["stage"] in PH23]
    seen = {t["nct"] for t in core}
    other = sorted((t for t in trials if t["same_mechanism_drugs"] and t["nct"] not in seen),
                   key=lambda t: (not _SAFETY_HINT.search(t["why_stopped"] or ""), -_STAGE.get(t["stage"] or "", 0),
                                  t["nct"]))
    per: dict[str, int] = {}
    picked = []
    for t in other:
        if any(per.get(d, 0) < OTHER_PER_DRUG for d in t["same_mechanism_drugs"]):
            picked.append(t)
            for d in t["same_mechanism_drugs"]:
                per[d] = per.get(d, 0) + 1
    first = core + picked
    rest = [t for t in trials if not t["same_mechanism_drugs"] and t["in_disease"] and t["stage"] in PH23]
    return (first + rest)[:max(limit, len(first))]


# --- 2-3. label and check quotes -------------------------------------------------------------------------------------
def _norm(text: str) -> str:
    return " ".join(re.sub(r"[\"'“”‘’`]", "", text).lower().split())


def quote_found(quote: str, text: str) -> bool:
    q, t = _norm(quote), _norm(text)
    if not q:
        return False
    if q in t:
        return True
    n = len(q)
    if n > len(t):
        return SequenceMatcher(None, q, t).ratio() >= QUOTE_MATCH
    return max(SequenceMatcher(None, q, t[i:i + n]).ratio() for i in range(len(t) - n + 1)) >= QUOTE_MATCH


# The checker reads the whole stated reason (it is short and is, by definition, why the trial stopped), so it can
# see "a sister study was stopped for futility; this one was stopped as a consequence" as efficacy, and
# "The primary endpoint was achieved" as not.
CHECKED = {"efficacy": "The text is the sponsor's stated reason for stopping a trial, so whatever it describes is why the "
                       "trial stopped (it need not say 'stopped'). Claim: what it describes is that the drug did not "
                       "work well enough: futility, lack of efficacy, no benefit, primary endpoint not met or unlikely to "
                       "be met, or a related trial of the same drug stopped for one of these reasons.",
           "safety": "The text is the sponsor's stated reason for stopping a trial, so whatever it describes is why the "
                     "trial stopped (it need not say 'stopped'). Claim: what it describes is a safety problem: side "
                     "effects, toxicity, abnormal laboratory values such as raised liver enzymes, deaths, no tolerated "
                     "dose, or a safety signal."}


# A cause named only to deny it: "not due to lack of efficacy", "No safety concerns", "unrelated to safety".
# Narrower than "a negator anywhere before the quote", which would also reject "did not meet the primary endpoint".
_CAUSE_DENIED = re.compile(r"\b(?:not|nor|never)\s+(?:\w+\s+){0,2}?(?:due\s+to|because\s+of|caused\s+by|related\s+to|"
                           r"driven\s+by|prompted\s+by|based\s+on|(?:the|a)\s+result\s+of|for)\b|\bunrelated\s+to\b", re.I)
_NO_CONCERN = re.compile(r"\b(?:no|without|never)\s+(?:new\s+|any\s+|other\s+|major\s+|significant\s+)*$", re.I)
_CONCERN_WORDS = re.compile(r"^\s*(?:\w+\s+){0,2}?(?:concerns?|signals?|issues?|problems?|findings?)\b", re.I)


def quote_negated(quote: str, text: str) -> bool:
    """True if the text names the quoted cause only to deny it (review F34). Checked in code, before the LLM check."""
    q = re.escape(" ".join(quote.split()))
    for m in re.finditer(q.replace(r"\ ", r"\s+"), text, re.I):
        before = text[max(0, m.start() - 60):m.start()]
        clause = re.split(r"[.;:]|\bbut\b|\bhowever\b|\brather\b|\binstead\b", before, flags=re.I)[-1]  # same clause
        after = text[m.end():m.end() + 30]
        if _CAUSE_DENIED.search(clause):
            return True
        if _NO_CONCERN.search(clause) and (_CONCERN_WORDS.search(after) or _CONCERN_WORDS.search(m.group(0))):
            return True
    return False


def label_trials(llm: LLM, trials: list[dict], check: bool = True) -> dict[str, Any]:
    """{nct: [{"label", "quote", "verified", "support"}]} plus errors. A failed batch leaves its trials unlabelled.
    `support`: True / False from the second check, None when not checked (other labels, or the check failed)."""
    def ask(batch: list[dict], label: str) -> tuple[dict[str, list[dict]], list[str]]:
        user = json.dumps([{"nct": t["nct"], "reason": t["why_stopped"]} for t in batch], ensure_ascii=False)
        try:
            answer = llm.complete_json("classify_stops", SYSTEM, user, SCHEMA)
        except LLMError as exc:
            if too_big(exc) and len(batch) > 1:
                half = len(batch) // 2
                (l1, e1), (l2, e2) = ask(batch[:half], label + "a"), ask(batch[half:], label + "b")
                return {**l1, **l2}, e1 + e2
            return {}, [f"batch {label}: {exc}"]
        got: dict[str, list[dict]] = {}
        by_nct = {t["nct"]: t for t in batch}
        for item in answer.get("trials") or []:
            if not isinstance(item, dict):
                continue
            t = by_nct.get(str(item.get("nct") or "").upper())
            if t is None:
                continue                                   # an ID that was not asked about is ignored
            got[t["nct"]] = [{"label": x["label"], "quote": str(x.get("quote") or ""),
                              "verified": x["label"] == "unknown" or quote_found(str(x.get("quote") or ""), t["why_stopped"])}
                             for x in item.get("labels") or [] if isinstance(x, dict) and x.get("label") in LABELS]
        missing = [n for n in by_nct if n not in got]
        return got, ([f"batch {label}: no answer for {', '.join(missing)}"] if missing else [])

    # Packed to the gateway's input budget (batching.py), at most BATCH trials, run in parallel.
    size = lambda t: len(json.dumps({"nct": t["nct"], "reason": t["why_stopped"]}, ensure_ascii=False))  # noqa: E731
    batches = pack(trials, size, fixed_chars(SYSTEM, SCHEMA), BATCH)
    labels: dict[str, list[dict]] = {}
    errors: list[str] = []
    for got, errs in pmap(lambda nb: ask(nb[1], str(nb[0] + 1)), list(enumerate(batches))):
        labels.update(got)
        errors += errs
    reason_of = {t["nct"]: t["why_stopped"] for t in trials}
    for nct, xs in labels.items():
        for x in xs:
            x["support"] = None
            if x["verified"] and x["label"] in CHECKED and quote_negated(x["quote"], reason_of[nct]):
                x["verified"], x["negated"] = False, True        # "not due to lack of efficacy" is not efficacy
    if check:
        reason = {t["nct"]: t["why_stopped"] for t in trials}
        items = [{"id": f"{nct}#{k}", "claim": CHECKED[x["label"]], "quote": reason[nct][:800]}
                 for nct, xs in labels.items() for k, x in enumerate(xs) if x["verified"] and x["label"] in CHECKED]
        if items:
            got = check_support(llm, items, task="check_stop_labels")
            errors += got["errors"]
            for item in items:
                nct, k = item["id"].rsplit("#", 1)
                x = labels[nct][int(k)]
                ok = got["verdicts"].get(item["id"])
                x["support"] = ok
                if ok is None:
                    x["verified"], x["unchecked"] = False, True   # the check failed: unchecked labels are not used
                elif not ok:
                    x["verified"] = False          # the quote exists but does not say this: not used
    return {"labels": labels, "errors": errors}


def has(labels: dict, nct: str, label: str) -> dict | None:
    return next((x for x in labels.get(nct, []) if x["label"] == label and x["verified"]), None)


def sponsor_key(name: str) -> str:
    """"Eisai Co., Ltd." and "Eisai Inc." are one sponsor: the first word of the name, lower case.
    Errs on the safe side: two universities collapse into one, so a claim waits for confirmation longer."""
    words = re.sub(r"[^\w\s]", " ", name or "").lower().split()
    return words[0] if words else ""


# --- 4. count -> claims ----------------------------------------------------------------------------------------------
def _claim_sources(hits: list[tuple]) -> list[dict]:
    """hits: (trial or document, label hit[, drug]). `drugs` and `verified` let the scorer's claims gate recount
    the distinct drugs itself (unobio_scoring 2.x, review F34/F36): it drops negated or unverified sources."""
    kinds = {"aact": "clinical_trial_results", "pubmed": "pubmed", "fda_label": "fda_label"}
    out = []
    for h in hits:
        t, lab = h[0], h[1]
        src = {"kind": kinds.get(lab.get("source"), "clinical_trial"), "id": t["nct"], "url": t["url"],
               "sponsor": t["sponsor"], "quote": lab["quote"], "why_stopped": t["why_stopped"], "verified": True}
        if len(h) > 2:
            src["drugs"] = [h[2]]
        out.append(src)
    # 2.7: the claims gate recounts distinct drugs from these sources, so every drug keeps its first source before the
    # cap (CETP, 10.10.2026: dozens of anacetrapib hits pushed evacetrapib out of the first 40)
    first, rest, seen = [], [], set()
    for src in out:
        key = tuple(src.get("drugs") or [])
        (rest if key in seen else first).append(src)
        seen.add(key)
    return (first + rest)[:max(40, len(first))]


AUTO_CONFIRM_MIN_DOCS = 2
# 2.6: hits made by code, not by an LLM: registry p-values, Open Targets stop categories, word rules on stop reasons and
# on trial abstracts. A claim made only of these is structured and needs no confirmation.
CODE_SOURCES = {"aact", "ot_category", "rules", "rules_pubmed"}


def auto_confirm(items: list[dict], enabled: bool | None = None) -> list[str]:
    """2.4: an LLM claim whose quotes were found by code and passed the second check, drawn from at least
    AUTO_CONFIRM_MIN_DOCS independent documents (different sponsors, papers or labels), is confirmed without a reviewer.
    2.5: an efficacy-failure claim from one source is confirmed too when its quote states the failure explicitly
    (_EXPLICIT_FAILURE, a code check of the words, not the model's interpretation).
    That is the "second independent source" the claims gate asks for. Mechanism sample 10.10.2026: CETP, TLR4 and NGF
    were Insufficient evidence only because such claims waited for a person.
    UNOBIO_AUTO_CONFIRM=0 turns it off (every verdict-changing LLM claim then waits for POST /runs/{id}/evidence).
    Returns the confirmed claim ids."""
    import os
    if enabled is None:
        enabled = os.environ.get("UNOBIO_AUTO_CONFIRM", "1").strip() not in ("0", "false", "no", "")
    if not enabled:
        return []
    out = []
    for c in items:
        docs = set(c.get("doc_ids") or [])
        if c.get("origin") != "llm" or not c.get("verified") or c.get("confirmed"):
            continue
        if len(docs) >= AUTO_CONFIRM_MIN_DOCS:
            why = f"{len(docs)} independent sources, quotes found by code and checked a second time"
        elif c.get("fact") == "moa_failures_efficacy_ph23" and _EXPLICIT_FAILURE.search(c.get("quote") or ""):
            # 2.5: one source whose quote states the failure in words the code recognises (not the LLM's reading):
            # "futility", "did not meet its primary endpoint", "lack of efficacy". CETP on 10.10.2026 waited for a
            # person with such a quote.
            why = f"the quoted source states the failure explicitly (\"{c['quote'][:80]}\"), checked by code"
        else:
            continue
        c["confirmed"] = True
        c["statement"] = c["statement"].rstrip() + f" [Confirmed automatically: {why}.]"
        out.append(c["id"])
    return out


_EXPLICIT_FAILURE = re.compile(r"\bfutil|did not (?:meet|achieve|reach)|failed to (?:meet|achieve|reach|demonstrate|show)|"
                               r"lack of (?:efficacy|benefit)|no (?:significant )?(?:efficacy|benefit)|not met", re.I)


def _key(name: str) -> str:
    from backend.app.facts import drug_key
    return drug_key(name)


def _doc_key(t: dict) -> str:
    """Independent source of a hit: a paper or label counts by itself, a trial by its sponsor."""
    if t.get("doc_key"):
        return t["doc_key"]
    s = sponsor_key(t.get("sponsor") or "")
    return f"sponsor:{s}" if s else f"trial:{t['nct']}"


def trial_claims(c: Claims, trials: list[dict], labelled: dict, disease: dict, target: dict,
                 extra_failures: dict[str, list] | None = None, approved_here: set[str] | None = None,
                 approved_anywhere: set[str] | None = None) -> None:
    """`extra_failures`: drug -> [(trial or document, hit)] from AACT primary-outcome p-values (code, hit source
    "aact") or from papers and labels (LLM, quote checked). They join the stop-reason labels in one count.

    2.4: a failure is a failed PROGRAM, not a failed trial. `approved_here`: same-mechanism drugs approved for this
    disease; they never count as efficacy failures (mechanism sample 10.10.2026: dapagliflozin, semaglutide, imatinib,
    sotorasib, inclisiran, tofersen were counted). `approved_anywhere`: drugs approved in any indication; a trial of
    theirs stopped for safety is not a program discontinued for safety."""
    labels = labelled["labels"]
    here = {_key(n) for n in approved_here or ()}
    anywhere = {_key(n) for n in approved_anywhere or ()} | here
    mech = f"{target['symbol']} {target.get('action') or 'any direction'}"

    def add(fact, value, statement, rule, hits):
        structured = all(h[1].get("source") in CODE_SOURCES for h in hits)
        c.add(fact, value, statement, rule, _claim_sources(hits), origin="structured" if structured else "llm")
        if not structured:
            c.items[-1].update(verified=True, confirmed=False, quote=next(h[1]["quote"] for h in hits
                                                                           if h[1].get("source") not in CODE_SOURCES),
                               doc_ids=sorted({_doc_key(h[0]) for h in hits}))

    # efficacy failures of other drugs with the same mechanism, Phase 2/3, in this disease
    eff: dict[str, list] = {}
    for t in trials:
        lab = has(labels, t["nct"], "efficacy")
        if lab and t["in_disease"] and t["stage"] in PH23:
            for d in t["same_mechanism_drugs"]:
                if _key(d) not in here:
                    eff.setdefault(d, []).append((t, lab))
    for d, hits in (extra_failures or {}).items():
        if _key(d) in here:
            continue
        seen = {t["nct"] for t, _ in eff.get(d, [])}
        eff.setdefault(d, []).extend(h for h in hits if h[0]["nct"] not in seen)
    eff = {d: h for d, h in eff.items() if h}
    failed = {_key(d) for d in eff}
    if eff:
        hits = [(*h, d) for d in sorted(eff) for h in eff[d]]
        add("moa_failures_efficacy_ph23", len(eff),
            f"{n_drugs(len(eff))} with the same mechanism ({mech}) stopped Phase 2/3 trials in {disease['name']} for "
            f"lack of efficacy: " + "; ".join(f"{d.title()} ({eff[d][0][0]['nct']}: \"{eff[d][0][1]['quote']}\")"
                                              for d in sorted(eff)) + ".",
            "Distinct drugs with the same mechanism, Phase 2, 2/3 or 3, trial in this disease, counted by code; drugs "
            "approved for this disease are never counted (a failed trial of an approved drug is not a failed program). "
            "A hit is "
            "an LLM label 'efficacy' with a quote found in the stated stop reason and confirmed by a second check, or "
            "(AACT) every primary-outcome superiority analysis with p >= 0.05, or a paper or label saying clinical "
            "benefit was not shown (quote checked). Never zero from text.", hits)

    # programs on this target stopped for safety, any disease
    saf: dict[str, list] = {}
    for t in trials:
        lab = has(labels, t["nct"], "safety")
        if lab:
            for d in t["same_mechanism_drugs"]:
                if _key(d) not in anywhere:
                    saf.setdefault(d, []).append((t, lab))
    if saf:
        hits = [(*h, d) for d in sorted(saf) for h in saf[d]]
        add("moa_discontinued_safety_count", len(saf),
            f"{n_drugs(len(saf))} with the same mechanism ({mech}) had trials stopped for safety: "
            + "; ".join(f"{d.title()} ({saf[d][0][0]['nct']}: \"{saf[d][0][1]['quote']}\")" for d in sorted(saf)) + ".",
            "LLM label 'safety' with a quote found in the trial's stated reason; counted by code: distinct drugs "
            "with the same mechanism, any disease. Never zero from text.", hits)

    # enrollment problems in this disease (any drug), Phase 2/3
    pool = [t for t in trials if t["in_disease"] and t["stage"] in PH23 and t["nct"] in labels]
    named = [t for t in pool if any(x["label"] != "unknown" and x["verified"] for x in labels[t["nct"]])]
    enr = [(t, has(labels, t["nct"], "enrollment")) for t in pool if has(labels, t["nct"], "enrollment")]
    if len(enr) >= ENROLLMENT_MIN and named and len(enr) / len(named) >= ENROLLMENT_SHARE:
        add("indication_enrollment_terminations_high", True,
            f"{len(enr)} of {len(named)} labelled Phase 2/3 trials in {disease['name']} that stopped for a stated "
            f"reason stopped for enrollment.",
            f"At least {ENROLLMENT_MIN} such trials and at least a third of the labelled ones. Only the trials sent to "
            f"the LLM are counted (up to {MAX_TRIALS} per run). Never set to false.", enr)
    return failed

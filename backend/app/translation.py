"""Translation chain (brief, step 3): molecular effect -> human exposure -> target engagement -> biological response
-> patient benefit. Which links are shown, for the mechanism and for the asset, and which are missing.

The input names a mechanism, not a molecule, so the public evidence is about OTHER drugs with the same mechanism
(the "class"). It becomes mechanism-level facts (`class_*`), never the asset's own link facts: another drug reaching
the brain is not proof that this one does. Exposure counts only from drugs of the same modality group; target
engagement and pharmacodynamic response transfer across modalities.

Sources and what each gives:
  Open Targets impc / CRISPR       link 1: perturbation evidence (code)           -> perturbation_evidence
  Open Targets expression/pathways link 1: correlational evidence (code)          -> correlational_evidence
  openFDA labels, PubMed abstracts links 1-5: findings with quotes (LLM)          -> class_* facts, failures
  AACT                             link 5: primary-outcome p-values (code); MeSH disease mapping; outcome titles
                                   (a registered "CSF concentration" outcome means the link was TESTED, not shown)
  UniProt                          can a large molecule reach the target (code)   -> modality_target_mismatch

LLM findings follow the trials.py pattern: the model quotes, code checks the quote is in the document, a second
narrow check asks whether the quote states the finding (support.py), and code does all counting.
"""
from __future__ import annotations

import json
import re
from typing import Any

from backend.app.facts import Claims, _same_mechanism, drug_key, label_approvals, n_drugs
from backend.app.llm import LLM, LLMError
from backend.app.normalize import name_forms
from backend.app.batching import fixed_chars, pack, pmap
from backend.app.support import check_support, too_big
from backend.app.trials import PH23, STOPPED, _norm, quote_found

LINKS = ["animal_response", "exposure", "target_engagement", "pd_response", "clinical_benefit"]
LINK_TEXT = {"animal_response": "a response in an animal or cell model of the disease",
             "exposure": "drug exposure at the site of action (pharmacokinetics, tissue or CSF levels)",
             "target_engagement": "target engagement (the drug binds, blocks or lowers its target)",
             "pd_response": "a pharmacodynamic response (a downstream biomarker changes)",
             "clinical_benefit": "clinical benefit for patients (a clinical endpoint improves)"}
STAGE_RANK = {"APPROVAL": 9, "PHASE_4": 8, "PHASE_3": 7, "PHASE_2_3": 6, "PHASE_2": 5, "PHASE_1_2": 4, "PHASE_1": 3,
              "EARLY_PHASE_1": 2, "PRECLINICAL": 1, "WITHDRAWAL": 7, "UNKNOWN": 0}
MODALITY_GROUP = {"small molecule": "small_molecule", "antibody": "antibody", "antibody drug conjugate": "antibody",
                  "oligonucleotide": "rna", "protein": "protein", "gene": "gene", "cell": "cell", "enzyme": "protein",
                  # input values (mechanism.py)
                  "small_molecule": "small_molecule", "adc": "antibody", "bispecific": "antibody", "rna": "rna",
                  "peptide": "protein", "radioligand": "radioligand", "vaccine": "vaccine"}
MAX_LABEL_DRUGS, MAX_PUBMED_DRUGS, PER_QUERY, PER_OUTCOME_QUERY = 5, 4, 4, 6
NOT_REVIEW = " NOT review[pt] NOT \"systematic review\"[pt] NOT meta-analysis[pt]"     # primary papers only
DOC_BATCH, MAX_DOC_CHARS = 6, 9000
# Registry trials whose result the code cannot read (no stop reason, no primary-outcome p-values: tominersen's
# GENERATION HD1 is "Completed" with descriptive results only) are looked up in PubMed by their NCT ID.
MAX_NCT_LOOKUPS, PER_NCT_QUERY = 6, 3
FINISHED = {"COMPLETED", "TERMINATED", "SUSPENDED"}
ALPHA = 0.05

PK_WORDS = r"(pharmacokinetic*[tiab] OR pharmacodynamic*[tiab] OR \"target engagement\"[tiab] OR occupancy[tiab] " \
           r"OR biomarker*[tiab] OR cerebrospinal[tiab])"
OUTCOME_WORDS = r"(randomized[tiab] OR randomised[tiab] OR \"phase 3\"[tiab] OR \"phase III\"[tiab] OR " \
                r"\"primary end point\"[tiab] OR \"primary endpoint\"[tiab] OR placebo[tiab])"
MODEL_WORDS = r"(knockout[tiab] OR knockdown[tiab] OR \"mouse model\"[tiab] OR transgenic[tiab] OR \"animal model\"[tiab])"
TESTED = {"exposure": re.compile(r"pharmacokinetic|\bpk\b|\bcmax\b|\bauc\b|concentration|half-life|exposure|clearance", re.I),
          "target_engagement": re.compile(r"occupancy|target engagement|\bpet\b|binding|knockdown|reduction (?:in|of) "
                                          r"(?:csf|plasma|serum)? ?\w+ (?:protein|mrna|levels?)", re.I),
          "pd_response": re.compile(r"biomarker|pharmacodynamic|\bpd\b|change from baseline in (?:csf|plasma|serum)", re.I)}


def modality_group(value: str | None) -> str | None:
    return MODALITY_GROUP.get((value or "").strip().lower())


# --- 1. the class: drugs with the same mechanism ----------------------------------------------------------------------
def class_drugs(collected: dict, target_id: str, action: str | None) -> list[dict]:
    """Same-mechanism drugs on the target, most advanced first, salt forms merged."""
    part = collected["parts"].get("target_drugs") or {}
    if not part.get("ok"):
        return []
    out: dict[str, dict] = {}
    for row in part["data"].get("rows") or []:
        drug = row.get("drug") or {}
        if not drug.get("name") or not _same_mechanism(drug, target_id, action)[0]:
            continue
        k = drug_key(drug["name"])
        stage = row.get("maxClinicalStage") or drug.get("maximumClinicalStage") or "UNKNOWN"
        d = out.setdefault(k, {"key": k, "name": k.title(), "chembl": drug.get("id"), "stage": stage,
                               "modality": modality_group(drug.get("drugType")), "drug_type": drug.get("drugType"),
                               "approved": False, "names": set()})
        if STAGE_RANK.get(stage, 0) > STAGE_RANK.get(d["stage"], 0):
            d["stage"] = stage
        d["approved"] = d["approved"] or bool(label_approvals(row))
        d["names"] |= {k.lower(), drug["name"].lower()} | {(s.get("label") or "").lower() for s in
                                                          (drug.get("synonyms") or []) + (drug.get("tradeNames") or [])}
    drugs = sorted(out.values(), key=lambda d: (-STAGE_RANK.get(d["stage"], 0), d["key"]))
    for d in drugs:
        d["names"] = sorted(n for n in d["names"] if n and len(n) > 2)
    return drugs


# --- 2. collect ---------------------------------------------------------------------------------------------------------
def _part(fn) -> dict:
    try:
        data = fn()
    except Exception as exc:                                   # one failed source must not lose the others
        first = f"{type(exc).__name__}: {exc}"
        if "offline" in str(exc) or "skipped" in str(exc):
            return {"ok": False, "complete": False, "error": first}
        try:                                                   # 2.4: one more try for a transient failure
            data = fn()
        except Exception as exc2:
            return {"ok": False, "complete": False, "error": f"{first}; retry: {type(exc2).__name__}: {exc2}"}
    return {"ok": True, "complete": True, "data": data}


def collect_translation(sources, norm: dict, collected: dict) -> dict[str, Any]:
    """Runs the extra sources for one run. Returns {"drugs": [...], "parts": {name: {"ok", "data" | "error"}}}."""
    d, t = norm["disease"], norm["target"]
    drugs = class_drugs(collected, t["id"], t.get("action"))
    parts: dict[str, dict] = {}

    if sources.uniprot:
        parts["uniprot"] = _part(lambda: sources.uniprot.locations(t["symbol"]))
    if sources.openfda:
        def labels():
            out = []
            for drug in [x for x in drugs if x["approved"]][:MAX_LABEL_DRUGS]:
                lab = sources.openfda.label(drug["key"])
                if lab:
                    out.append({"drug": drug["key"], **lab})
            return out
        parts["fda_labels"] = _part(labels)
    if sources.pubmed:
        def pubmed():
            out = []
            for drug in [x for x in drugs if STAGE_RANK.get(x["stage"], 0) >= STAGE_RANK["PHASE_1"]][:MAX_PUBMED_DRUGS]:
                for words, n in ((PK_WORDS, PER_QUERY), (OUTCOME_WORDS, PER_OUTCOME_QUERY)):
                    term = f'"{drug["key"].lower()}"[tiab] AND {words}{NOT_REVIEW}'
                    out.append({"query": term, "drug": drug["key"], "articles": sources.pubmed.articles(term, n)})
            term = f'"{t["symbol"]}"[tiab] AND "{d["name"]}"[tiab] AND {MODEL_WORDS}{NOT_REVIEW}'
            out.append({"query": term, "drug": None, "articles": sources.pubmed.articles(term, PER_QUERY)})
            return out
        parts["pubmed"] = _part(pubmed)
    if sources.aact:
        if sources.aact.ready or sources.aact.offline:
            def aact():
                names = {n: x["key"] for x in drugs for n in x["names"]}
                rows = sources.aact.trials_for_drugs(sorted(names))
                for r in rows:
                    r["drugs"] = sorted({names[m] for m in r.get("matched") or [] if m in names})
                return rows
            parts["aact"] = _part(aact)
        else:
            parts["aact"] = {"ok": False, "complete": False, "skipped": True, "error": "AACT_DSN is not set"}
    if sources.pubmed and (parts.get("aact") or {}).get("ok"):
        def pubmed_nct():
            out = []
            for r in unknown_result_trials(parts["aact"]["data"], d):
                nct = r["nct_id"].upper()
                term = f'"{nct}"[si] OR "{nct}"[tiab]'
                try:
                    arts = sources.pubmed.articles(term, PER_NCT_QUERY)
                except Exception as exc:                  # one lookup failing must not lose the others
                    out.append({"query": term, "drug": r["drugs"][0], "nct": nct, "articles": [],
                                "error": f"{type(exc).__name__}: {exc}"})
                    continue
                out.append({"query": term, "drug": r["drugs"][0], "nct": nct, "articles": arts})
            return out
        parts["pubmed_nct"] = _part(pubmed_nct)
    drugs_out = [{k: v for k, v in x.items() if k != "names"} | {"names": x["names"][:12]} for x in drugs]
    return {"drugs": drugs_out, "parts": parts}


def _data(tr: dict | None, name: str):
    p = ((tr or {}).get("parts") or {}).get(name) or {}
    return p.get("data") if p.get("ok") else None


# --- AACT: disease mapping, stopped trials, primary outcomes -------------------------------------------------------------
def disease_terms(disease: dict) -> set[str]:
    return {f for x in [disease.get("name"), *(disease.get("synonyms") or [])] if x for f in name_forms(x)}


def failure_terms(disease: dict) -> set[str]:
    """2.8: the disease and its broader diseases (parents, grandparents from Open Targets): a trial registered under
    "cardiovascular diseases" enrolled coronary artery disease patients. Used to find failures only, never successes."""
    return disease_terms(disease) | {f for x in disease.get("broader") or [] if x.get("name") for f in name_forms(x["name"])}


def aact_in_disease(row: dict, terms: set[str]) -> bool:
    """A trial is in the disease when a MeSH term (ClinicalTrials.gov lists ancestors too) or a condition name equals
    the disease name or an exact synonym. A trial on a more specific disease lists the broader one as an ancestor."""
    return bool(terms & {f for x in (row.get("mesh_terms") or []) + (row.get("conditions") or []) if x
                         for f in name_forms(x)})


def merge_aact_trials(trials: list[dict], tr: dict | None, disease: dict) -> list[dict]:
    """Adds AACT's stopped trials of same-mechanism drugs to the Open Targets list and fixes the disease mapping:
    Open Targets leaves some trials without a disease ID (evacetrapib's futility stops), AACT has their MeSH terms."""
    rows = _data(tr, "aact") or []
    if not rows:
        return trials
    terms = failure_terms(disease)
    by_nct = {t["nct"]: t for t in trials}
    for r in rows:
        nct = (r.get("nct_id") or "").upper()
        if not nct:
            continue
        inside = aact_in_disease(r, terms)
        if nct in by_nct:
            t = by_nct[nct]
            t["in_disease"] = t["in_disease"] or inside
            t["same_mechanism_drugs"] = sorted(set(t["same_mechanism_drugs"]) | set(r.get("drugs") or []))
            t.setdefault("aact", True)
            continue
        why = (r.get("why_stopped") or "").strip()
        if r.get("overall_status") not in STOPPED or not why:
            continue
        by_nct[nct] = {"nct": nct, "why_stopped": why, "status": r["overall_status"], "stage": r.get("stage"),
                       "sponsor": r.get("sponsor") or "", "start": r.get("start_date"),
                       "url": f"https://clinicaltrials.gov/study/{nct}", "ot_categories": [],
                       "diseases": [], "in_disease": inside, "drugs": sorted(r.get("drugs") or []),
                       "same_mechanism_drugs": sorted(r.get("drugs") or []), "aact": True}
    return sorted(by_nct.values(), key=lambda t: (not t["same_mechanism_drugs"], t["nct"]))


def primary_not_met(row: dict) -> bool | None:
    """True: every superiority analysis of a primary outcome has p >= 0.05. None: no usable analysis."""
    ps = []
    for a in row.get("primary_analyses") or []:
        ni = (a.get("non_inferiority") or "").lower()
        if ni and "superiority" not in ni:
            continue
        try:
            ps.append(float(a.get("p_value")))
        except (TypeError, ValueError):
            continue
    if not ps:
        return None
    return all(p >= ALPHA for p in ps)


def unknown_result_trials(rows: list[dict], disease: dict) -> list[dict]:
    """Registry trials of same-mechanism drugs, Phase 2/3, in this disease, finished, whose primary outcome the code
    cannot judge (no superiority p-value). Their result is in a paper, if anywhere: largest and latest phase first."""
    terms = failure_terms(disease)
    pick = [r for r in rows or [] if r.get("nct_id") and r.get("drugs") and r.get("stage") in PH23
            and r.get("overall_status") in FINISHED and aact_in_disease(r, terms) and primary_not_met(r) is None]
    pick.sort(key=lambda r: (-STAGE_RANK.get(r.get("stage") or "", 0), -(r.get("enrollment") or 0), r["nct_id"]))
    return pick[:MAX_NCT_LOOKUPS]


# 2.5: a trial stopped early for any reason other than efficacy has p-values that say nothing about efficacy
# (tanezumab, atabecestat on 10.10.2026: stopped for joint or liver safety, counted as efficacy failures)
_EFFICACY_STOP = re.compile(r"futil|efficac|primary (?:end ?point|outcome)|did not meet|not met|failed to (?:meet|show|"
                            r"demonstrate)|lack of (?:benefit|effect|response)|no (?:clinical )?benefit|interim analysis",
                            re.I)
_EARLY_STOP = {"TERMINATED", "SUSPENDED", "WITHDRAWN"}


def stopped_for_other_reason(r: dict) -> bool:
    """A registry row that stopped early and whose stated reason is not about efficacy (or is missing)."""
    return (r.get("overall_status") or "").upper() in _EARLY_STOP and not _EFFICACY_STOP.search(r.get("why_stopped") or "")


_BIOMARKER = re.compile(r"\b(?:ldl|hdl|cholesterol|lipoprotein|lp\(a\)|triglycerid\w*|apolipoprotein|apo ?[ab]\d?|hba1c|"
                        r"glucose|glyc\w+ hemoglobin|blood pressure|concentration|plasma level|serum level|"
                        r"pharmacokinetic\w*|auc|cmax|biomarker|percent change|% change|occupancy|amyloid|"
                        r"bone mineral density|viral load|antibod(?:y|ies) titer)", re.I)


def clinical_primary_met(row: dict) -> bool:
    """2.7: a superiority analysis of a primary outcome with p < 0.05 whose outcome is clinical, not a biomarker
    (evacetrapib lowered LDL-C in Phase 3 and failed on cardiovascular events: lowering LDL is not a met program)."""
    for a in row.get("primary_analyses") or []:
        ni = (a.get("non_inferiority") or "").lower()
        if ni and "superiority" not in ni:
            continue
        try:
            p = float(a.get("p_value"))
        except (TypeError, ValueError):
            continue
        if p < ALPHA and not _BIOMARKER.search(a.get("outcome") or ""):
            return True
    return False


def positive_ph3_drugs(tr: dict | None, disease: dict) -> set[str]:
    """2.5: drugs with a Phase 3 (or 2/3) trial in this disease whose primary outcome WAS met (a superiority analysis
    with p < 0.05): their program did not fail for efficacy here, whatever another trial did (anacetrapib: REVEAL met
    its primary endpoint; tanezumab: Phase 3 met co-primary endpoints and was stopped for joint safety)."""
    terms = disease_terms(disease)
    out: set[str] = set()
    for r in _data(tr, "aact") or []:
        if r.get("stage") in {"PHASE_3", "PHASE_2_3"} and aact_in_disease(r, terms) and clinical_primary_met(r):
            out |= set(r.get("drugs") or [])
    return out


def aact_failures(tr: dict | None, disease: dict) -> dict[str, list[tuple[dict, dict]]]:
    """Drug -> [(trial, hit)] for Phase 2/3 trials in the disease whose primary outcome analyses all missed (p >= 0.05).
    2.5: not for trials stopped early for a reason other than efficacy."""
    terms = failure_terms(disease)
    out: dict[str, list] = {}
    for r in _data(tr, "aact") or []:
        if r.get("stage") not in PH23 or not aact_in_disease(r, terms) or primary_not_met(r) is not True:
            continue
        if stopped_for_other_reason(r):
            continue
        nct = r["nct_id"].upper()
        ps = ", ".join(f"p = {a.get('p_value')}" for a in r.get("primary_analyses") or [] if a.get("p_value") is not None)
        t = {"nct": nct, "url": f"https://clinicaltrials.gov/study/{nct}", "sponsor": r.get("sponsor") or "",
             "why_stopped": f"Primary outcome analyses not significant ({ps})."}
        for d in r.get("drugs") or []:
            out.setdefault(d, []).append((t, {"quote": t["why_stopped"], "source": "aact"}))
    return out


def tested_links(tr: dict | None) -> dict[str, list[str]]:
    """Link -> NCT IDs of same-mechanism trials that registered an outcome measuring it (tested, result not read)."""
    out: dict[str, set] = {k: set() for k in TESTED}
    for r in _data(tr, "aact") or []:
        for o in r.get("design_outcomes") or []:
            for link, rx in TESTED.items():
                if rx.search(o.get("measure") or ""):
                    out[link].add(r["nct_id"].upper())
    return {k: sorted(v) for k, v in out.items()}


# --- 3. documents for the LLM ---------------------------------------------------------------------------------------
def documents(tr: dict | None) -> list[dict]:
    docs, seen = [], set()
    for lab in _data(tr, "fda_labels") or []:
        text = "\n".join(f"{s.replace('_', ' ').upper()}: {v}" for s, v in lab["sections"].items())
        doc_id = f"label:{lab['set_id'] or lab['drug']}"
        if doc_id not in seen:
            seen.add(doc_id)
            docs.append({"id": doc_id, "kind": "fda_label", "drug": lab["drug"], "url": lab.get("url"),
                         "title": f"FDA label: {lab.get('brand_name') or lab['drug'].title()}", "text": text[:MAX_DOC_CHARS]})
    for q in (_data(tr, "pubmed") or []) + (_data(tr, "pubmed_nct") or []):
        for a in q.get("articles") or []:
            doc_id = f"pmid:{a['pmid']}"
            if doc_id in seen or a.get("retracted") or a.get("review"):
                continue
            seen.add(doc_id)
            docs.append({"id": doc_id, "kind": "pubmed", "drug": q.get("drug"), "url": a["url"],
                         "title": f"{a.get('first_author') or ''} {a.get('year') or ''}: {a['title']}".strip(),
                         "text": (a["title"] + ". " + a["abstract"])[:MAX_DOC_CHARS]})
    return docs


SYSTEM = """You read drug labels and paper abstracts for a biotech investment analysis and extract evidence for the
translation chain of one mechanism. For every document list each finding:
- drug: one of the given drug names, or TARGET when the finding is about the target itself (knockout, knockdown,
  model organism) rather than a drug. Each document says which drug it is about (about_drug): a result in that
  document that names no drug ("in the 100 mg group") is about that drug.
- link: animal_response (effect in an animal or cell model of the disease), exposure (the drug reaches the site of
  action: plasma, tissue or CSF levels, half-life), target_engagement (the drug binds, blocks or lowers its target, for
  example receptor occupancy or lower target protein or mRNA), pd_response (a downstream biomarker changes),
  clinical_benefit (a clinical endpoint in patients).
- result: shown or not_shown. not_shown only when the text says it was looked for and not found or not met.
- species: human, animal or cell.
- in_disease: true if the finding is in the given disease.
- quote: copied word for word from the document, at most 30 words, that states the finding.
Rules: a finding is a RESULT the document reports from a study (a measurement, a comparison with placebo or
baseline, an observed change, an endpoint met or missed). General statements about what a drug does, is designed to
do or "plays a role in" are not findings. Use only what the document says; do not use outside knowledge; do not count
planned or ongoing studies as results; skip findings about other drugs. Return every document id you were given, with an empty list if nothing."""

SCHEMA = {
    "type": "object",
    "properties": {"documents": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "findings": {"type": "array", "items": {
            "type": "object",
            "properties": {"drug": {"type": "string"}, "link": {"type": "string", "enum": LINKS},
                           "result": {"type": "string", "enum": ["shown", "not_shown"]},
                           "species": {"type": "string", "enum": ["human", "animal", "cell"]},
                           "in_disease": {"type": "boolean"}, "quote": {"type": "string"}},
            "required": ["drug", "link", "result", "species", "in_disease", "quote"], "additionalProperties": False}}},
        "required": ["id", "findings"], "additionalProperties": False}}},
    "required": ["documents"], "additionalProperties": False,
}


def quote_in(quote: str, text: str) -> bool:
    """quote_found, made fast for long documents: fuzzy matching only near the quote's first words."""
    q, t = _norm(quote), _norm(text)
    if not q:
        return False
    if q in t:
        return True
    if len(t) <= 3000:
        return quote_found(quote, text)
    head = " ".join(q.split()[:3])
    for m in re.finditer(re.escape(head), t):
        window = t[max(0, m.start() - 20): m.start() + len(q) + 40]
        if quote_found(q, window):
            return True
    return False


RESULT_TEXT = {"shown": "was shown", "not_shown": "was NOT shown (no difference from placebo or baseline, not detected, "
                                       "not significant, endpoint not met, or a worse result)"}
WHERE = {"human": "in people", "animal": "in animals", "cell": "in cells"}


def finding_claim(f: dict) -> str:
    """What the support checker must confirm, in plain words. The passage may not repeat the species or the drug
    name; the checker is told to reject only when the passage contradicts them."""
    who = "the target itself (no drug)" if f["drug"] == "TARGET" else f["drug"].title()
    return f"Study result for {who}, {WHERE.get(f['species'], 'in people')}: {LINK_TEXT[f['link']]} {RESULT_TEXT[f['result']]}."


def excerpt(quote: str, text: str, width: int = 300) -> str:
    """The quote with its surrounding sentences, so the checker sees what the quote refers to."""
    i = text.lower().find(quote.lower()[:40]) if quote else -1
    if i < 0:
        return quote
    a, b = max(0, i - width), min(len(text), i + len(quote) + width)
    return ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")


def extract_findings(llm: LLM, docs: list[dict], disease: dict, target: dict, drug_names: list[str],
                     check: bool = True) -> dict[str, Any]:
    """[{doc_id, drug, link, result, species, in_disease, quote, verified, support}] plus errors."""
    findings: list[dict] = []
    errors: list[str] = []
    allowed = {n.upper() for n in drug_names} | {"TARGET"}
    by_id = {x["id"]: x for x in docs}
    def payload(batch: list[dict]) -> str:
        return json.dumps({"disease": disease["name"], "target": target["symbol"], "drugs": sorted(allowed - {"TARGET"}),
                           "documents": [{"id": x["id"], "about_drug": x.get("drug") or "TARGET", "text": x["text"]}
                                         for x in batch]}, ensure_ascii=False)

    def ask(batch: list[dict], label: str) -> tuple[list[tuple[list[dict], dict]], list[str]]:
        """One request; a batch refused as too large is split in half (down to one document)."""
        try:
            return [(batch, llm.complete_json("extract_translation", SYSTEM, payload(batch), SCHEMA))], []
        except LLMError as exc:
            if too_big(exc) and len(batch) > 1:
                half = len(batch) // 2
                (a1, e1), (a2, e2) = ask(batch[:half], label + "a"), ask(batch[half:], label + "b")
                return a1 + a2, e1 + e2
            return [], [f"translation batch {label}: {exc}"]

    # Packed to the gateway's input budget (batching.py), at most DOC_BATCH documents, run in parallel.
    doc_size = lambda x: len(json.dumps({"id": x["id"], "about_drug": x.get("drug") or "TARGET", "text": x["text"]},  # noqa: E731
                                        ensure_ascii=False))
    batches = pack(docs, doc_size, fixed_chars(SYSTEM, SCHEMA) + len(payload([])), DOC_BATCH)
    answers: list[tuple[list[dict], dict]] = []
    for got, errs in pmap(lambda nb: ask(nb[1], str(nb[0] + 1)), list(enumerate(batches))):
        answers += got
        errors += errs
    for batch, answer in answers:
        for item in (answer or {}).get("documents") or []:
            doc = by_id.get(str((item or {}).get("id") or "")) if isinstance(item, dict) else None
            if doc is None or doc not in batch:
                continue                                  # an id that was not asked about is ignored
            for f in item.get("findings") or []:
                if not isinstance(f, dict) or f.get("link") not in LINKS or f.get("result") not in ("shown", "not_shown"):
                    continue
                drug = drug_key(str(f.get("drug") or "")).upper()
                if drug not in allowed:
                    continue
                quote = str(f.get("quote") or "")
                findings.append({"doc_id": doc["id"], "doc_kind": doc["kind"], "url": doc.get("url"),
                                 "title": doc.get("title"), "drug": drug, "link": f["link"], "result": f["result"],
                                 "species": f.get("species") if f.get("species") in ("human", "animal", "cell") else "human",
                                 "in_disease": bool(f.get("in_disease")), "quote": quote,
                                 "verified": quote_in(quote, doc["text"]), "support": None})
    if check:
        items = [{"id": str(k), "claim": finding_claim(f), "quote": excerpt(f["quote"], by_id[f["doc_id"]]["text"])}
                 for k, f in enumerate(findings) if f["verified"]]
        if items:
            got = check_support(llm, items, task="check_translation")
            errors += got["errors"]
            for item in items:
                f = findings[int(item["id"])]
                ok = got["verdicts"].get(item["id"])
                f["support"] = ok
                if ok is None:
                    f["verified"], f["unchecked"] = False, True   # the check failed: an unchecked finding is not used
                elif not ok:
                    f["verified"] = False
    return {"findings": findings, "errors": errors}


# --- 4. claims ------------------------------------------------------------------------------------------------------------
def _src(findings: list[dict]) -> list[dict]:
    out, seen = [], set()
    for f in findings:
        if (f["doc_id"], f["quote"]) in seen:
            continue
        seen.add((f["doc_id"], f["quote"]))
        out.append({"kind": f["doc_kind"], "id": f["doc_id"], "url": f.get("url"), "name": f.get("title"),
                    "quote": f["quote"], "drug": f["drug"]})
    return out[:20]


def biology_claims(c: Claims, disease: dict, target: dict, part: dict | None) -> None:
    """Link 1 from Open Targets evidence rows (code). Only affirmative values: no row is not proof of no effect."""
    if not part or not part.get("ok"):
        return
    from backend.app.collect import CORRELATIONAL_DATASOURCES, PERTURBATION_DATASOURCES
    rows = part["data"].get("rows") or []
    url = f"https://platform.opentargets.org/evidence/{target['id']}/{disease['id']}"
    for fact, sources, what in (("perturbation_evidence", PERTURBATION_DATASOURCES,
                                 "perturbation evidence (mouse knockout or CRISPR screen)"),
                                ("correlational_evidence", CORRELATIONAL_DATASOURCES,
                                 "correlational evidence (expression change or affected pathway)")):
        hits = [r for r in rows if r.get("datasourceId") in sources]
        if hits:
            names = sorted({r.get("datasourceId") for r in hits})
            c.add(fact, True, f"{target['symbol']} has {what} for {disease['name']} ({len(hits)} records: "
                  f"{', '.join(names)}).", "Open Targets evidence from " + ", ".join(sources) + ". Only a present "
                  "record is used; no record is not proof of no effect.",
                  [{"kind": "open_targets_evidence", "id": r.get("id"), "datasource": r.get("datasourceId"),
                    "url": url} for r in hits[:20]])


def _llm_claim(c: Claims, fact: str, value: Any, statement: str, rule: str, findings: list[dict]) -> None:
    c.add(fact, value, statement, rule, _src(findings), origin="llm")
    c.items[-1].update(verified=True, confirmed=False, quote=findings[0]["quote"],
                       doc_ids=sorted({f["doc_id"] for f in findings}))


def class_claims(c: Claims, disease: dict, target: dict, drugs: list[dict], findings: list[dict]) -> None:
    """Links 1-4 for the class from verified LLM findings. Exposure only from drugs of the input's modality group."""
    good = [f for f in findings if f["verified"]]
    mods = {d["key"]: d.get("modality") for d in drugs}
    own = modality_group(target.get("drug_type"))
    mech = f"{target['symbol']} {target.get('action') or 'any direction'}"

    def human(link, same_modality=False):
        rows = [f for f in good if f["link"] == link and f["species"] == "human" and f["drug"] != "TARGET"]
        if same_modality and own:
            rows = [f for f in rows if mods.get(f["drug"]) == own]
        return [f for f in rows if f["result"] == "shown"], [f for f in rows if f["result"] == "not_shown"]

    for fact, link, same_mod in (("class_exposure_human", "exposure", True),
                                 ("class_target_engagement_human", "target_engagement", False),
                                 ("class_pd_response_human", "pd_response", False)):
        shown, not_shown = human(link, same_mod)
        scope = (f" of the same modality ({own})" if own else " (modality not given: any modality)") if same_mod else ""
        rule = (f"LLM finding with a quote found in the document and confirmed by a second check; counted by code. "
                f"Drugs with the same mechanism ({mech}){scope}. True if any drug shows it in humans; false only if "
                f"documents say it was looked for and not found and none shows it.")
        if shown:
            names = sorted({f["drug"].title() for f in shown})
            _llm_claim(c, fact, True, f"{LINK_TEXT[link].capitalize()} is shown in humans for {n_drugs(len(names))} "
                       f"with the same mechanism{scope}: {', '.join(names)} (\"{shown[0]['quote']}\").", rule, shown)
        elif not_shown:
            names = sorted({f["drug"].title() for f in not_shown})
            _llm_claim(c, fact, False, f"{LINK_TEXT[link].capitalize()} was looked for and not shown in humans for "
                       f"{', '.join(names)} (\"{not_shown[0]['quote']}\").", rule, not_shown)

    # link 1 from papers: knockout / knockdown / model response
    animal = [f for f in good if f["link"] == "animal_response" and f["species"] in ("animal", "cell")
              and f["result"] == "shown" and f.get("in_disease")]   # a model of THIS disease, not any phenotype
    if animal:
        _llm_claim(c, "perturbation_evidence", True, f"Blocking or removing {target['symbol']} changes a disease phenotype "
                   f"in a model ({animal[0]['title']}: \"{animal[0]['quote']}\").",
                   "LLM finding from a PubMed abstract, quote found and confirmed; only affirmative values.", animal)


def ph23_drugs_in_disease(collected: dict, tr: dict | None, disease: dict, drugs: list[dict]) -> set[str]:
    """Class drugs with ANY Phase 2/3 trial in this disease (completed ones too: tominersen's Phase 3 is "completed"),
    from Open Targets trial reports mapped to the disease ID, or AACT trials mapped by MeSH."""
    keys = {d["key"] for d in drugs}
    out = set()
    for row in ((collected.get("parts") or {}).get("target_drugs") or {}).get("data", {}).get("rows") or []:
        k = drug_key((row.get("drug") or {}).get("name"))
        here_ids = {disease["id"]} | {x["id"] for x in disease.get("broader") or []}
        if k in keys and any(r.get("clinicalStage") in PH23 and here_ids &
                             {(x.get("disease") or {}).get("id") for x in r.get("diseases") or []}
                             for r in row.get("clinicalReports") or []):
            out.add(k)
    terms = failure_terms(disease)
    for r in _data(tr, "aact") or []:
        if r.get("stage") in PH23 and aact_in_disease(r, terms):
            out |= set(r.get("drugs") or [])
    return out


def literature_failures(findings: list[dict], ph23: set[str]) -> dict[str, list[tuple[dict, dict]]]:
    """Drug -> [(doc, hit)]: a paper or label says clinical benefit was NOT shown in this disease, for a same-mechanism
    drug that has a Phase 2/3 trial in this disease (`ph23`: the phase comes from trial data, never from the text)."""
    out: dict[str, list] = {}
    for f in findings:
        if (f["verified"] and f["link"] == "clinical_benefit" and f["result"] == "not_shown" and f["in_disease"]
                and f["species"] == "human" and f["drug"] in ph23):
            doc = {"nct": f["doc_id"], "url": f.get("url"), "sponsor": "", "doc_key": f["doc_id"],
                   "why_stopped": f["title"] or ""}
            out.setdefault(f["drug"], []).append((doc, {"quote": f["quote"], "source": f.get("source") or f["doc_kind"]}))
    return out


def chain_summary(tr: dict | None, findings: list[dict]) -> dict:
    """For the report: per link, which documents showed / did not show it, and which trials only tested it."""
    tested = tested_links(tr)
    out = {}
    for link in LINKS:
        rows = [f for f in findings if f["verified"] and f["link"] == link]
        out[link] = {"shown": sorted({f["drug"] for f in rows if f["result"] == "shown"}),
                     "not_shown": sorted({f["drug"] for f in rows if f["result"] == "not_shown"}),
                     "tested_in": tested.get(link, [])[:10]}
    return out


def sources_status(tr: dict | None) -> list[str]:
    """One line per source that failed or was skipped, for the run message."""
    out = []
    for name, p in ((tr or {}).get("parts") or {}).items():
        if not p.get("ok"):
            out.append(f"{name}: {'skipped' if p.get('skipped') else 'failed'} ({p.get('error', '')[:120]})")
    return out

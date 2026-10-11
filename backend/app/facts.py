"""Pipeline stage 3: raw Open Targets data -> claims for the scorer. Code only, no LLM.

Each claim: {id, fact, value, origin, evidence_type, statement, rule, sources}. `rule` is the definition the code
applied, in words; `sources` lists the records the value rests on (for the "claim -> source" drill-down).

Principles:
  - Absence (zero, "none") only from a complete block; otherwise the fact stays unknown.
  - When a filter removes doubtful records, a zero is claimed only if there was nothing to remove.
  - Values that would need human judgement are not produced: they become due-diligence questions in the scorer.

Definitions checked on live data (release 26.09):
  - Approval in a disease counts only from an official label (FDA, EMA, DailyMed) mapped to that disease ID.
    TTD and PMDA-only approvals are not counted: PMDA mapped "AD/HD" labels to Alzheimer disease and atopic eczema.
  - Diagnostic radiotracers (F 18, I 123, ...) are not therapies.
  - Salt forms are one drug: "DONEPEZIL HYDROCHLORIDE" == "DONEPEZIL".
  - "Related disease" = a shared specific therapeutic area; phenotype, biological process, measurement and
    "genetic, familial or congenital disease" are too broad and do not count.
"""
from __future__ import annotations

import re
from typing import Any

# --- definitions -------------------------------------------------------------------------------------------------
MENDELIAN_SOURCES = {"clingen", "gene2phenotype", "genomics_england", "orphanet", "uniprot_literature"}
CLINVAR = "eva"                                  # Mendelian only with a pathogenic / likely pathogenic variant
PATHOGENIC = {"pathogenic", "likely pathogenic"}
GWAS = "gwas_credible_sets"
L2G_MIN = 0.5
SOMATIC_SOURCES = {"intogen", "cancer_gene_census"}
# Not counted (decision 8 Oct): gene_burden, uniprot_variants, eva_somatic.

LABEL_SOURCES = {"FDA", "EMA Human Drugs", "DailyMed"}
APPROVED_STAGES = {"APPROVAL", "PHASE_4"}
PHASE3_STAGES = {"PHASE_3", "PHASE_2_3"}
ACTIVE_STATUSES = {"RECRUITING", "ACTIVE_NOT_RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"}
ONCOLOGY_AREAS = {"MONDO_0045024", "EFO_0000616"}
GENERIC_AREAS = {"EFO_0000651", "GO_0008150", "EFO_0001444", "OTAR_0000018"}
ANTIBODY_LIKE = {"antibody", "adc", "bispecific", "cell"}
# Cell surface or outside the cell. "Nucleus membrane" or "Mitochondrion membrane" are not reachable for an antibody.
REACHABLE_LOCATION = re.compile(r"^(?:cell membrane|plasma membrane|cell surface|cell junctions|secreted|extracellular)",
                                re.I)
# Antibody tractability buckets that mean "reachable"; GO CC / UniProt "med conf" and HPA alone are too weak
# (ABL1, intracellular, has "GO CC med conf").
AB_REACHABLE = {"Approved Drug", "Advanced Clinical", "Phase 1 Clinical", "UniProt loc high conf", "GO CC high conf",
                "UniProt SigP or TMHMM"}

INHIBIT_WORDS = ("inhibitor", "antagonist", "blocker", "degrader", "negative", "inverse", "disrupting", "antisense",
                 "sequestering")
# 2.4: ChEMBL "EXOGENOUS GENE" (gene therapy: onasemnogene abeparvovec for SMN1) and "EXOGENOUS PROTEIN" (protein or
# enzyme replacement) add the target's function: the same direction as "gene therapy" in the input
ACTIVATE_WORDS = ("agonist", "activator", "positive", "opener", "stabiliser", "stabilizer", "exogenous")
MULTI_TARGET_MIN = 3     # 2.4: a drug acting on this many targets or more is a class member only if developed here
_SALTS = ("hydrochloride", "hydrobromide", "sodium", "calcium", "potassium", "mesylate", "besylate", "maleate",
          "tartrate", "citrate", "fumarate", "succinate", "sulfate", "phosphate", "acetate", "dimesylate", "gluconate",
          # 2.4: solvates and co-crystals listed as separate drugs (dapagliflozin propanediol, ertugliflozin pidolate,
          # canagliflozin anhydrous, nilotinib hydrochloride monohydrate)
          "propanediol", "anhydrous", "monohydrate", "dihydrate", "hydrate", "pidolate", "l-proline", "tosylate")
_SALT_RE = re.compile(r"\s+(?:" + "|".join(_SALTS) + r")$", re.I)
_RADIOTRACER = re.compile(r"\b(?:F ?18|I ?123|I ?131|TC ?99M|GA ?68|C ?11|IN ?111)\b", re.I)


def direction_of(action_type: str | None) -> str | None:
    """ChEMBL action type -> inhibit | activate | None. "INVERSE AGONIST" inhibits."""
    t = (action_type or "").lower()
    if any(w in t for w in INHIBIT_WORDS):
        return "inhibit"
    if any(w in t for w in ACTIVATE_WORDS):
        return "activate"
    return None


def drug_key(name: str | None) -> str:
    """Active ingredient: salt words dropped, upper case."""
    n = (name or "").strip()
    while _SALT_RE.search(n):
        n = _SALT_RE.sub("", n)
    return n.upper()


def is_diagnostic(name: str | None) -> bool:
    return bool(_RADIOTRACER.search(name or ""))


def _report_diseases(report: dict) -> set[str]:
    return {(d.get("disease") or {}).get("id") for d in report.get("diseases") or []} - {None}


def label_approvals(row: dict) -> set[str]:
    """Disease IDs in which an official label approves this drug."""
    out: set[str] = set()
    for rep in row.get("clinicalReports") or []:
        if rep.get("source") in LABEL_SOURCES and rep.get("clinicalStage") in APPROVED_STAGES:
            out |= _report_diseases(rep)
    return out


def _report_url(rep: dict) -> str | None:
    return rep.get("url")


def n_drugs(n: int) -> str:
    return f"{n} drug{'' if n == 1 else 's'}"


def article(word: str) -> str:
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


# --- claims ------------------------------------------------------------------------------------------------------
class Claims:
    def __init__(self):
        self.items: list[dict[str, Any]] = []

    def add(self, fact: str, value: Any, statement: str, rule: str, sources: list[dict] | None = None,
            origin: str = "structured") -> None:
        self.items.append({"id": f"clm_{len(self.items) + 1}", "fact": fact, "value": value, "origin": origin,
                           "evidence_type": "source", "statement": statement[:1].upper() + statement[1:], "rule": rule,
                           "sources": sources or []})


def _ot_url(kind: str, ident: str) -> str:
    return f"https://platform.opentargets.org/{kind}/{ident}"


def disease_claims(c: Claims, disease: dict) -> None:
    areas = {a["id"] for a in disease.get("therapeutic_areas") or []}
    src = [{"kind": "open_targets_disease", "id": disease["id"], "url": _ot_url("disease", disease["id"])}]
    if areas:
        onc = bool(areas & ONCOLOGY_AREAS)
        c.add("oncology", onc, f"{disease['name']} is {'' if onc else 'not '}in the oncology therapeutic area.",
              "Oncology = therapeutic area 'cancer or benign tumor' in Open Targets.", src)
    if disease["id"].startswith("Orphanet_"):
        c.add("rare_disease", True, f"{disease['name']} is an Orphanet rare disease entry.",
              "Rare = the disease ID itself is an Orphanet ID. An Orphanet cross-reference alone is not enough "
              "(Alzheimer disease has one). Never set to false from data.", src)


def mendelian_level(rows: list[dict], disease: dict, target: dict) -> tuple[str, str]:
    """`mendelian` or `mendelian_subtype`, and the claim statement, from the Mendelian evidence rows of the pair.

    Open Targets returns evidence for the disease and, indirectly, for the diseases under it in its ontology; each row
    names the disease it is for. Rows for the disease itself -> mendelian (+2), even if subtype rows exist too. Only
    rows for other (more specific) diseases -> mendelian_subtype (+1), named by the source's own disease names. A row
    that names no disease cannot be told apart: it is not called a subtype (the previous reading, mendelian, stays)."""
    direct = [r for r in rows if (r.get("disease") or {}).get("id") in (None, disease["id"])]
    sources = lambda rs: ", ".join(sorted({r.get("datasourceId") for r in rs}))  # noqa: E731
    if direct:
        unnamed = [r for r in direct if not (r.get("disease") or {}).get("id")]
        note = (f"; {len(unnamed)} of them name no disease, so they cannot be told apart from a subtype"
                if unnamed else "")
        return "mendelian", (f"{target['symbol']} has Mendelian genetic evidence for {disease['name']} "
                             f"({len(direct)} records: {sources(direct)}{note}).")
    names = sorted({(r.get("disease") or {}).get("name") or f"unnamed, {(r.get('disease') or {}).get('id')}"
                    for r in rows})
    return "mendelian_subtype", (
        f"{target['symbol']}: Mendelian genetics in a rare subtype ({'; '.join(names)}), not in {disease['name']} "
        f"itself ({len(rows)} records: {sources(rows)}). Counted as ordinary genetic support (+1), not as Mendelian "
        f"evidence for {disease['name']} (+2).")


def genetics_claims(c: Claims, disease: dict, target: dict, pair: dict, disease_gen: dict) -> None:
    if not pair["ok"]:
        return
    rows = pair["data"].get("rows") or []
    url = f"https://platform.opentargets.org/evidence/{target['id']}/{disease['id']}"

    def src(rs):
        return [{"kind": "open_targets_evidence", "id": r.get("id"), "datasource": r.get("datasourceId"),
                 "disease": (r.get("disease") or {}).get("id"), "url": url} for r in rs[:20]]

    mendel = [r for r in rows if r.get("datasourceId") in MENDELIAN_SOURCES
              or (r.get("datasourceId") == CLINVAR
                  and PATHOGENIC & {s.lower() for s in r.get("clinicalSignificances") or []})]
    gwas = [r for r in rows if r.get("datasourceId") == GWAS and (r.get("score") or 0) >= L2G_MIN]
    somatic = [r for r in rows if r.get("datasourceId") in SOMATIC_SOURCES]
    rule = ("Mendelian: ClinGen, Gene2Phenotype, Genomics England, Orphanet, UniProt literature, or ClinVar with a "
            "pathogenic variant. Mendelian, subtype: every such record is for a subtype (a more specific disease under "
            "this one in the ontology, as Open Targets returns it), none for the disease itself. GWAS: credible set "
            "with locus-to-gene score >= 0.5. Somatic: IntOGen, Cancer Gene Census. Strongest wins. 'none' needs "
            "every evidence row read and genetic data for the disease.")
    if mendel:
        value, statement = mendelian_level(mendel, disease, target)
        c.add("genetic_support", value, statement, rule, src(mendel))
        return
    for value, hits, what in (("gwas", gwas, "GWAS (L2G >= 0.5)"), ("somatic_driver", somatic, "somatic driver")):
        if hits:
            sources = sorted({r.get("datasourceId") for r in hits})
            c.add("genetic_support", value, f"{target['symbol']} has {what} genetic evidence for {disease['name']} "
                  f"({len(hits)} records: {', '.join(sources)}).", rule, src(hits))
            return
    if not pair["complete"]:
        return
    if disease_gen["ok"]:
        assoc = disease_gen["data"].get("rows") or []
        with_gen = [r for r in assoc if any(x.get("id") == "genetic_association" and (x.get("score") or 0) > 0
                                            for x in r.get("datatypeScores") or [])]
        if with_gen:
            c.add("genetic_support", "none", f"No qualifying genetic evidence links {target['symbol']} to "
                  f"{disease['name']} ({len(rows)} evidence rows read), although the disease has genetic evidence "
                  f"for other targets (e.g. {', '.join(r['target']['approvedSymbol'] for r in with_gen[:3])}).",
                  rule, src(rows) or [{"kind": "open_targets_evidence", "id": None, "url": url}])
        elif disease_gen["complete"]:
            c.add("genetic_support", "no_data", f"{disease['name']} has no genetic evidence for any target.",
                  rule, [{"kind": "open_targets_associations", "id": disease["id"],
                          "url": _ot_url("disease", disease["id"]) + "/associations"}])


def _directions(drug: dict, target_id: str) -> set[str]:
    return {d for m in ((drug.get("mechanismsOfAction") or {}).get("rows") or [])
            if target_id in {t.get("id") for t in m.get("targets") or []}
            for d in [direction_of(m.get("actionType"))] if d}


def _same_mechanism(drug: dict, target_id: str, action: str | None) -> tuple[bool, str | None]:  # (same?, direction)
    """Same target and the same KNOWN direction of action. Since review F37: an unknown direction on either side is
    not "the same mechanism" (antagonists made an agonist me-too); such drugs make counts incomplete instead.
    2.4: a drug marked by `mark_class_members` (multi-target drug never developed here, pan inhibitor for a variant
    input) is not the same mechanism either."""
    dirs = _directions(drug, target_id)
    direction = action if action in dirs else next(iter(sorted(dirs)), None)
    if drug.get(NOT_SAME_KEY):
        return False, direction
    return (bool(action) and action in dirs), direction


NOT_SAME_KEY = "_unobio_not_same"


def _in_disease(row: dict, disease_id: str) -> bool:
    """The drug was developed for this disease: an approval, a clinical report or an indication mapped to its ID."""
    if disease_id in label_approvals(row):
        return True
    if any(disease_id in _report_diseases(r) for r in row.get("clinicalReports") or []):
        return True
    rows = (((row.get("drug") or {}).get("indications") or {}).get("rows")) or []
    return any((i.get("disease") or {}).get("id") == disease_id for i in rows)


def mark_class_members(part: dict | None, target: dict, disease_id: str) -> list[dict]:
    """2.4: removes drugs that hit the target but are not the thesis's mechanism class, before anything is counted.

    Mechanism sample 10.10.2026: ABL1 listed regorafenib, umbralisib, saracatinib (multi-kinase drugs for other
    diseases); KRAS G12C listed salirasib (a pan-RAS farnesylcysteine mimetic). Rules, both decided from data:
      1. multi-target: the drug's mechanisms name MULTI_TARGET_MIN or more targets and the drug was never developed for
         this disease (no approval, clinical report or indication mapped to it). Imatinib (several kinases, CML) stays.
      2. variant: the input names a protein change (G12C) and every mechanism row of the drug on this target also names
         other targets (a family-wide inhibitor), and its mechanism text does not name the variant.
    Marks the drug (NOT_SAME_KEY) in place and returns [{name, reason}] for the memo."""
    if not part or not part.get("ok"):
        return []
    tid, action, variant = target["id"], target.get("action"), (target.get("variant") or "").upper()
    out = []
    for row in part["data"].get("rows") or []:
        drug = row.get("drug") or {}
        drug.pop(NOT_SAME_KEY, None)
        if not _same_mechanism(drug, tid, action)[0]:
            continue
        moas = (drug.get("mechanismsOfAction") or {}).get("rows") or []
        targets = {t.get("id") for m in moas for t in m.get("targets") or []} - {None}
        reason = None
        if variant:
            on_target = [m for m in moas if tid in {t.get("id") for t in m.get("targets") or []}]
            pan = all(len({t.get("id") for t in m.get("targets") or []}) > 1 for m in on_target)
            named = any(variant in (m.get("mechanismOfAction") or "").upper() for m in on_target)
            if on_target and pan and not named:
                reason = f"family-wide inhibitor, not specific to {variant}"
        if reason is None and len(targets) >= MULTI_TARGET_MIN and not _in_disease(row, disease_id):
            reason = (f"acts on {len(targets)} targets, {target.get('symbol') or tid} is one of them, and it was never "
                      f"developed for this disease")
        if reason:
            drug[NOT_SAME_KEY] = reason
            out.append({"name": drug_key(drug.get("name")), "reason": reason})
    seen, uniq = set(), []
    for x in out:
        if x["name"] not in seen:
            seen.add(x["name"])
            uniq.append(x)
    return uniq


def _direction_unknown(drug: dict, target_id: str, action: str | None) -> bool:
    """The drug may or may not be the same mechanism: the input's or the drug's direction is unknown."""
    return not action or not _directions(drug, target_id)


def unsure_drugs(part: dict, target_id: str, action: str | None) -> list[str]:
    """Drugs on the target whose direction of action, or the input's, is unknown (for the report's unknowns)."""
    if not part or not part.get("ok"):
        return []
    return sorted({drug_key((r.get("drug") or {}).get("name")) for r in part["data"].get("rows") or []
                   if (r.get("drug") or {}).get("name") and _direction_unknown(r.get("drug") or {}, target_id, action)})


def _areas(row: dict) -> dict[str, set[str]]:
    """Disease ID -> specific therapeutic areas, from the drug's indications."""
    out = {}
    for ind in ((row.get("drug") or {}).get("indications") or {}).get("rows") or []:
        d = ind.get("disease") or {}
        if d.get("id"):
            out[d["id"]] = {a["id"] for a in d.get("therapeuticAreas") or []} - GENERIC_AREAS
    return out


_DRUG_TYPE_GROUP = {"small molecule": "small_molecule", "antibody": "antibody", "antibody drug conjugate": "antibody",
                    "oligonucleotide": "rna", "protein": "protein", "enzyme": "protein", "gene": "gene", "cell": "cell"}


def modality_class(value: str | None) -> str | None:
    """ChEMBL drug type or input modality -> the scorer's modality class (economics.MODALITY_CLASS); None if unknown."""
    from unobio_scoring.economics import MODALITY_CLASS
    v = (value or "").strip().lower()
    cls = MODALITY_CLASS.get(_DRUG_TYPE_GROUP.get(v, v))
    return None if cls in (None, "other") else cls


def approved_same_mechanism(part: dict | None, disease_id: str, target_id: str,
                            action: str | None) -> tuple[set[str], set[str]]:
    """2.4: (approved for this disease, approved anywhere) among same-mechanism drugs, as drug keys.

    Used by the trial counts: a drug approved for this disease is not a failure of the mechanism here, whatever one of
    its trials did (subgroups, other endpoints, cardiovascular outcome trials); a drug approved anywhere is not a
    program discontinued for safety."""
    here: set[str] = set()
    anywhere: set[str] = set()
    if not part or not part.get("ok"):
        return here, anywhere
    for row in part["data"].get("rows") or []:
        drug = row.get("drug") or {}
        if not _same_mechanism(drug, target_id, action)[0]:
            continue
        where = label_approvals(row)
        name = drug_key(drug.get("name"))
        if where:
            anywhere.add(name)
        if disease_id in where:
            here.add(name)
    return here, anywhere


FINISHED_STATUSES = {"COMPLETED", "TERMINATED", "SUSPENDED", "WITHDRAWN"}
PH23_STAGES = {"PHASE_2", "PHASE_2_3", "PHASE_3"}


def unknown_outcome_claims(c: Claims, disease: dict, target: dict, part: dict | None, approved_here: set[str],
                           failed: set[str]) -> None:
    """2.4: same-mechanism drugs whose Phase 2/3 trial in this disease has finished while the outcome is not known to
    the run: not approved here, no efficacy failure found, and no active trial here at the same or a later stage (a drug
    that moved on to an active later trial passed the earlier one). Mechanism sample 10.10.2026: tominersen's Phase 3 in Huntington disease
    is "completed" in the registry with no p-value, so its failure was invisible and the thesis was Invest.
    Only an affirmative count is added (an empty result from public data is not proof that nothing is unknown)."""
    if not part or not part.get("ok"):
        return
    did = disease["id"]
    found: dict[str, list] = {}
    for row in part["data"].get("rows") or []:
        drug = row.get("drug") or {}
        name = drug_key(drug.get("name"))
        if not name or not _same_mechanism(drug, target["id"], target.get("action"))[0]:
            continue
        if name in {drug_key(n) for n in approved_here} or name in {drug_key(n) for n in failed}:
            continue
        here = [r for r in row.get("clinicalReports") or [] if r.get("clinicalStage") in PH23_STAGES
                and did in _report_diseases(r)]
        rank = {"PHASE_2": 1, "PHASE_2_3": 2, "PHASE_3": 3}
        done = [rank[r["clinicalStage"]] for r in here if (r.get("trialOverallStatus") or "").upper() in FINISHED_STATUSES]
        live = [rank[r["clinicalStage"]] for r in here if (r.get("trialOverallStatus") or "").upper() in ACTIVE_STATUSES]
        # moved on = an active trial at the same or a later stage than the finished one (tominersen: Phase 3 finished,
        # only a Phase 2 is active again, so the Phase 3 outcome is still the unknown)
        if done and max(done) > max(live, default=0):
            found.setdefault(name, []).extend(r for r in here if (r.get("trialOverallStatus") or "").upper()
                                              in FINISHED_STATUSES)
    if found:
        names = sorted(found)
        c.add("moa_ph23_unknown_outcome_count", len(names),
              f"{n_drugs(len(names))} with the same mechanism finished a Phase 2/3 trial in {disease['name']} with no "
              f"outcome known to this run: " + ", ".join(
                  f"{n.title()} ({', '.join(sorted({nct_of_report(r) or r.get('id') or '?' for r in found[n]})[:3])})"
                  for n in names) + ".",
              "Open Targets clinical reports mapped to the disease ID: status completed, terminated, suspended or "
              "withdrawn; the drug is not approved here, has no efficacy failure in this run and no active trial here at "
              "the same or a later stage. Only affirmative counts.",
              [{"kind": "clinical_report", "id": r.get("id"), "source": r.get("source"), "url": _report_url(r),
                "name": n} for n in names for r in found[n][:3]][:20])


def nct_of_report(rep: dict) -> str | None:
    m = re.search(r"NCT\d{8}", " ".join(str(rep.get(k) or "") for k in ("id", "url")), re.I)
    return m.group(0).upper() if m else None


def target_drug_claims(c: Claims, disease: dict, target: dict, part: dict, action: str | None) -> None:
    if not part["ok"]:
        return
    rows = part["data"].get("rows") or []
    did = disease["id"]
    run_areas = {a["id"] for a in disease.get("therapeutic_areas") or []} - GENERIC_AREAS
    same = [row for row in rows if _same_mechanism(row.get("drug") or {}, target["id"], action)[0]]
    unsure = [row for row in rows if _direction_unknown(row.get("drug") or {}, target["id"], action)]
    # Counts and "none" only from a complete list where every drug's mechanism is decided (review F36, F37):
    # from an incomplete list, or with drugs of unknown direction, a count is only a lower bound.
    complete = part["complete"] and not unsure
    mech = f"{target['symbol']} {action or 'any direction'}"
    t_url = _ot_url("target", target["id"])

    def src(row, reps=()):
        d = row.get("drug") or {}
        out = [{"kind": "open_targets_drug", "id": d.get("id"), "name": d.get("name"),
                "url": _ot_url("drug", d.get("id") or "")}]
        return out + [{"kind": "clinical_report", "id": r.get("id"), "source": r.get("source"), "url": _report_url(r)}
                      for r in list(reps)[:5]]

    # approved here (same mechanism)
    approved_here: dict[str, tuple[dict, list]] = {}
    approved_any: dict[str, tuple[dict, set]] = {}
    for row in same:
        reps = [r for r in row.get("clinicalReports") or [] if r.get("source") in LABEL_SOURCES
                and r.get("clinicalStage") in APPROVED_STAGES]
        where = label_approvals(row)
        name = drug_key((row.get("drug") or {}).get("name"))
        if did in where:
            approved_here.setdefault(name, (row, [r for r in reps if did in _report_diseases(r)]))
        if where:
            approved_any.setdefault(name, (row, set()))[1].update(where)
    rule_same = ("Same mechanism = same target and the same known direction of action. Counts only from a complete "
                 "list with every drug's direction known (otherwise they are lower bounds and stay unknown). "
                 "Approval = an FDA, EMA or DailyMed label mapped to the disease ID; salt forms are one drug.")
    if complete:
        names = sorted(approved_here)
        c.add("approved_same_moa_count", len(names),
              f"{n_drugs(len(names))} with the same mechanism ({mech}) {'is' if len(names) == 1 else 'are'} approved for "
              f"{disease['name']}"
              + (f": {', '.join(n.title() for n in names)}." if names else "."), rule_same,
              [s for n in names for s in src(*approved_here[n])][:20] or [{"kind": "open_targets_target_drugs",
                                                                          "id": target["id"], "url": t_url}])
        # scorer 2.x: me-too and order of entry count only drugs of the same modality class (an oral small molecule
        # after an antibody is not a me-too). Only when the input modality and every approved drug's type are known.
        mine = modality_class(target.get("drug_type"))
        classes = {n: modality_class((approved_here[n][0].get("drug") or {}).get("drugType")) for n in names}
        if mine and all(classes.values()):
            same_mod = [n for n in names if classes[n] == mine]
            c.add("approved_same_moa_same_modality_count", len(same_mod),
                  f"{n_drugs(len(same_mod))} with the same mechanism and the same modality class ({mine.replace('_', ' ')}) "
                  f"{'is' if len(same_mod) == 1 else 'are'} approved for {disease['name']}"
                  + (f": {', '.join(n.title() for n in same_mod)}." if same_mod else "."),
                  rule_same + " Modality class from the ChEMBL drug type (small molecule / antibody-like / nucleic "
                  "acid / gene / cell); counted only when every approved drug's type is known.",
                  [s for n in same_mod for s in src(*approved_here[n])][:20]
                  or [{"kind": "open_targets_target_drugs", "id": target["id"], "url": t_url}])

    elif len(approved_here) >= 2:
        # 2.5: an incomplete list (or drugs of unknown direction) makes the count a lower bound, but "at least 2
        # approved" already answers the crowding question (psoriasis + IL-17A, 10.10.2026: secukinumab, ixekizumab,
        # bimekizumab found, count left unknown, verdict Conditional instead of crowded)
        names = sorted(approved_here)
        c.add("approved_same_moa_count", len(names),
              f"At least {len(names)} drugs with the same mechanism ({mech}) are approved for {disease['name']}: "
              f"{', '.join(n.title() for n in names)} (the drug list is incomplete or has drugs of unknown direction, "
              "so there may be more).", rule_same + " Lower bound: given only when it is already 2 or more.",
              [s for n in names for s in src(*approved_here[n])][:20])

    # 2.7: approved drugs on this target acting the OTHER way (affirmative only: one is enough to say it)
    if action in ("inhibit", "activate"):
        other = "activate" if action == "inhibit" else "inhibit"
        opp = {}
        for row in rows:
            drug = row.get("drug") or {}
            if other in _directions(drug, target["id"]) and action not in _directions(drug, target["id"]) \
                    and did in label_approvals(row):
                opp.setdefault(drug_key(drug.get("name")), row)
        if opp:
            names = sorted(opp)
            c.add("opposite_direction_approved_count", len(names),
                  f"{n_drugs(len(names))} approved for {disease['name']} act on {target['symbol']} in the opposite "
                  f"direction ({other}): {', '.join(n.title() for n in names)}. The thesis is to {action} it.",
                  "Same target, the opposite known direction of action (ChEMBL), an official label mapped to the "
                  "disease ID. Only affirmative values.", [s for n in names for s in src(opp[n])][:20])

    # clinical precedent
    rule_prec = (rule_same + " Related disease = a shared specific therapeutic area (phenotype, biological process, "
                 "measurement and 'genetic, familial or congenital disease' do not count).")
    if approved_here:
        n = sorted(approved_here)[0]
        c.add("moa_clinical_precedent", "approved_same", f"{n.title()} with the same mechanism is approved for "
              f"{disease['name']}.", rule_prec, src(*approved_here[n]))
    else:
        related = []
        for name, (row, where) in approved_any.items():
            areas = _areas(row)
            hits = [w for w in where if areas.get(w, set()) & run_areas]
            if hits:
                related.append((name, row, hits))
        if related:
            name, row, hits = sorted(related)[0]
            c.add("moa_clinical_precedent", "approved_related", f"{name.title()} with the same mechanism is approved "
                  f"for a related disease ({', '.join(hits[:3])}).", rule_prec, src(row))
        elif approved_any and complete:        # incomplete: a related approval may be among the undecided drugs
            name, (row, where) = sorted(approved_any.items())[0]
            c.add("moa_clinical_precedent", "approved_unrelated", f"{name.title()} with the same mechanism is "
                  f"approved only outside the therapeutic areas of {disease['name']}.", rule_prec, src(row))
        elif complete:
            c.add("moa_clinical_precedent", "none", f"No drug with the same mechanism ({mech}) is approved for any "
                  f"disease ({len(rows)} drugs on {target['symbol']} checked).", rule_prec,
                  [{"kind": "open_targets_target_drugs", "id": target["id"], "url": t_url}])

    # competitors in Phase 3 now (same mechanism, this disease, an active Phase 3 trial)
    active = {}
    for row in same:
        name = drug_key((row.get("drug") or {}).get("name"))
        if name in approved_here:
            continue
        reps = [r for r in row.get("clinicalReports") or [] if r.get("clinicalStage") in PHASE3_STAGES
                and (r.get("trialOverallStatus") or "").upper() in ACTIVE_STATUSES and did in _report_diseases(r)]
        if reps:
            active.setdefault(name, (row, reps))
    if complete:
        names = sorted(active)
        c.add("ph3_same_moa_count", len(names), f"{n_drugs(len(names))} with the same mechanism "
              f"{'has' if len(names) == 1 else 'have'} an active Phase 3 trial in {disease['name']}" + (f": {', '.join(n.title() for n in names)}." if names else "."),
              "Counted: same mechanism, not approved for this disease, a recruiting or active Phase 3 (or 2/3) "
              "trial mapped to the disease ID. Terminated or completed trials are not competitors.",
              [s for n in names for s in src(*active[n])][:20] or [{"kind": "open_targets_target_drugs",
                                                                   "id": target["id"], "url": t_url}])

    # class safety: only affirmative values (absence of a warning in Open Targets is not proof of safety)
    for warning, fact, text in (("black box warning", "class_safety_signal", "carries a boxed warning"),
                                ("withdrawn", "class_withdrawal", "was withdrawn")):
        hit = [row for row in same if any(warning in (w.get("warningType") or "").lower()
                                             for w in (row.get("drug") or {}).get("drugWarnings") or [])]
        if hit:
            names = sorted({drug_key(r["drug"]["name"]).title() for r in hit})
            c.add(fact, True, f"A drug with the same mechanism {text}: {', '.join(names)}.",
                  "From ChEMBL drug warnings in Open Targets; only a present warning is used.", src(hit[0]))


def disease_drug_claims(c: Claims, disease: dict, part: dict) -> None:
    if not part["ok"]:
        return
    rows, did = part["data"].get("rows") or [], disease["id"]
    approved, raw_approved = {}, 0
    for row in rows:
        if row.get("maxClinicalStage") in APPROVED_STAGES:
            raw_approved += 1
        name = (row.get("drug") or {}).get("name")
        if did in label_approvals(row) and not is_diagnostic(name):
            approved.setdefault(drug_key(name), row)
    rule = ("Approved = an FDA, EMA or DailyMed label mapped to the disease ID. TTD-only and PMDA-only approvals and "
            "diagnostic radiotracers are not counted; salt forms are one drug. Zero only if the drug list is "
            "complete and has no approval of any kind.")
    names = sorted(approved)
    if names or (part["complete"] and raw_approved == 0):
        c.add("approved_therapies_count", len(names),
              f"{n_drugs(len(names))} {'is' if len(names) == 1 else 'are'} approved for {disease['name']}"
              + (f": {', '.join(n.title() for n in names[:12])}" + ("…" if len(names) > 12 else "") if names else "")
              + ".", rule, [{"kind": "open_targets_drug", "id": approved[n]["drug"].get("id"), "name": n,
                             "url": _ot_url("drug", approved[n]["drug"].get("id") or "")} for n in names][:20]
              or [{"kind": "open_targets_disease_drugs", "id": did, "url": _ot_url("disease", did)}])


def indication_track_record_claims(c: Claims, disease: dict, target: dict, part: dict | None) -> None:
    """2.4: Phase 3 track record of OTHER targets in this disease, from the disease's drug list (already collected).

    Per other target (from the drugs' ChEMBL mechanisms): success = a drug on it is approved for this disease (official
    label mapped to the disease ID); failure = a drug on it reached Phase 3 here, none is approved here and no Phase 3
    trial here is still active; otherwise the outcome is not known yet and the target is not counted. This follows the
    definition validated on Minikel 2024 pairs (VALIDATION.md, the "Indication track record" item) with today's data,
    so it carries the same caveat: later events are included. Added only from a complete drug list."""
    if not part or not part.get("ok") or not part.get("complete"):
        return
    did, own = disease["id"], target["id"]
    per: dict[str, dict] = {}
    for row in part["data"].get("rows") or []:
        drug = row.get("drug") or {}
        if is_diagnostic(drug.get("name")):
            continue
        targets = {t.get("id") for m in (drug.get("mechanismsOfAction") or {}).get("rows") or []
                   for t in m.get("targets") or []} - {None, own}
        if not targets or len(targets) >= MULTI_TARGET_MIN:
            continue                                   # no target, or a multi-target drug: no single target to credit
        reports = [r for r in row.get("clinicalReports") or [] if did in _report_diseases(r)]
        approved = did in label_approvals(row)
        reached3 = row.get("maxClinicalStage") in PHASE3_STAGES | APPROVED_STAGES or any(
            r.get("clinicalStage") in PHASE3_STAGES for r in reports)
        active3 = any(r.get("clinicalStage") in PHASE3_STAGES and (r.get("trialOverallStatus") or "").upper()
                      in ACTIVE_STATUSES for r in reports)
        for t in targets:
            x = per.setdefault(t, {"approved": False, "reached3": False, "active3": False, "drugs": set()})
            x["approved"] |= approved
            x["reached3"] |= reached3
            x["active3"] |= active3
            x["drugs"].add(drug_key(drug.get("name")))
    success = sorted(t for t, x in per.items() if x["approved"])
    failure = sorted(t for t, x in per.items() if not x["approved"] and x["reached3"] and not x["active3"])
    known = len(success) + len(failure)
    rule = ("Other targets only (each target counted once): success = a drug on the target approved for this disease "
            "(official label), failure = reached Phase 3 here, not approved, no active Phase 3 here. Targets from "
            "ChEMBL mechanisms; multi-target drugs are skipped. From the complete Open Targets drug list of the "
            "disease; includes events up to today (not a point-in-time value).")
    src = [{"kind": "open_targets_disease_drugs", "id": did, "url": _ot_url("disease", did)}]
    c.add("indication_ph3_outcomes_other_moa", known,
          f"{known} other target(s) have a known Phase 3 outcome in {disease['name']}: {len(success)} with an approved "
          f"drug, {len(failure)} without.", rule, src)
    if known:
        c.add("indication_ph3_success_share_other_moa", round(len(success) / known, 3),
              f"{len(success)} of {known} other targets with a known Phase 3 outcome in {disease['name']} reached "
              f"approval ({len(success) / known:.0%}).", rule, src)


def target_info_claims(c: Claims, target: dict, part: dict, drug_type: str | None,
                       uniprot: dict | None = None) -> None:
    if not part["ok"] or not part["data"]:
        return
    d = part["data"]
    src = [{"kind": "open_targets_target", "id": target["id"], "url": _ot_url("target", target["id"])}]
    if d.get("isEssential") is not None:
        c.add("essential_gene", bool(d["isEssential"]), f"{target['symbol']} is {'' if d['isEssential'] else 'not '}"
              "a common essential gene.", "Open Targets isEssential (DepMap common essential).", src)
    if drug_type in ANTIBODY_LIKE:
        locs = [x.get("location") or "" for x in d.get("subcellularLocations") or []]
        up_locs = [x["value"] for x in (uniprot or {}).get("locations") or []]
        prio = {i.get("key"): i.get("value") for i in (d.get("prioritisation") or {}).get("items") or []}
        ab_tract = sorted({t.get("label") for t in d.get("tractability") or []
                           if t.get("modality") == "AB" and t.get("value") and t.get("label") in AB_REACHABLE})
        if locs or up_locs:
            surface = sorted({x for x in locs + up_locs if REACHABLE_LOCATION.search(x.strip())})
            reachable = bool(surface) or prio.get("isInMembrane") == "1" or prio.get("isSecreted") == "1" or bool(ab_tract)
            why = (f"surface or secreted location: {', '.join(surface[:4])}" if surface else
                   f"antibody tractability: {', '.join(ab_tract)}" if ab_tract else
                   "Open Targets marks it as a membrane or secreted protein" if reachable else
                   f"located only in {', '.join(sorted(set(locs + up_locs))[:5])}")
            sources = src + ([{"kind": "uniprot", "id": uniprot["accession"], "url": uniprot["url"]}] if up_locs else [])
            c.add("modality_target_mismatch", not reachable,
                  f"{article(drug_type).capitalize()} {'can' if reachable else 'cannot'} reach {target['symbol']}: {why}.",
                  "A large-molecule drug (antibody, ADC, bispecific, cell therapy) cannot reach the target only if no "
                  "location (Open Targets or UniProt) is the cell surface, plasma membrane, secreted or extracellular "
                  "(organelle membranes do not count), Open Targets does not mark it as membrane or secreted, and no "
                  "high-confidence antibody tractability bucket is set.", sources)


def input_claims(c: Claims, target: dict, phase: str | None, route: str | None) -> None:
    for fact, value, text in (("moa_direction", target.get("action"), "direction of action"),
                              ("modality", target.get("drug_type"), "modality"),
                              ("phase", phase, "development stage"), ("route_of_administration", route, "route")):
        if value:
            c.add(fact, value, f"Input: {text} is {value}.", "Given by the user.",
                  [{"kind": "user_input", "id": fact}],
                  origin="user")


def build_claims(norm: dict, collected: dict, phase: str | None = None, route: str | None = None) -> list[dict]:
    disease, target, parts = norm["disease"], norm["target"], collected["parts"]
    tr_parts = (collected.get("translation") or {}).get("parts") or {}
    uniprot = (tr_parts.get("uniprot") or {}).get("data") if (tr_parts.get("uniprot") or {}).get("ok") else None
    c = Claims()
    input_claims(c, target, phase, route)
    disease_claims(c, disease)
    genetics_claims(c, disease, target, parts["pair_genetics"], parts["disease_genetics"])
    target_drug_claims(c, disease, target, parts["target_drugs"], target.get("action"))
    disease_drug_claims(c, disease, parts["disease_drugs"])
    target_info_claims(c, target, parts["target_info"], target.get("drug_type"), uniprot)
    indication_track_record_claims(c, disease, target, parts.get("disease_drugs"))
    from backend.app.translation import biology_claims          # link 1 from Open Targets (code)
    biology_claims(c, disease, target, parts.get("pair_biology"))
    return c.items

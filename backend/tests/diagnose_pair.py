"""Why a drug's failure is (not) counted: everything the latest run of a pair saw about one drug. No network, no LLM.

  python -m backend.tests.diagnose_pair "coronary artery disease" "CETP inhibitor" EVACETRAPIB

Writes backend/data/diagnose_<drug>.txt and prints it: the Open Targets trial reports of the drug (stage, status,
stated reason, Open Targets stop category, disease IDs, whether the run counts it in the disease, the label the rules
give), the registry rows (MeSH terms, conditions, primary analyses with outcome titles and p-values, whether the run
counts them in the disease, met / missed), the PubMed abstracts it read (title, whether a rule fired) and the claims.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main(disease: str, mechanism: str, drug: str) -> str:
    from backend.app import api, db, rules
    from backend.app import translation as tl
    from backend.app.facts import drug_key
    c = api.con()
    run = next((r for r in db.list_runs(c, 500) if (r["disease_input"] or "").lower() == disease.lower()
                and (r["target_input"] or "").lower() == mechanism.lower() and r["status"] == "done"), None)
    if run is None:
        return f"no finished run for {disease} + {mechanism}"
    full = db.get_run(c, run["id"])
    raw = db.get_raw(c, run["id"]) or {}
    col = raw.get("collected") or {}
    norm = full.get("normalized") or {}
    d = norm.get("disease") or {}
    key = drug_key(drug)
    L = [f"run {run['id']} {run['created_at']}  disease {d.get('id')} {d.get('name')}  synonyms {d.get('synonyms')}",
         f"incomplete: {full.get('incomplete')}", ""]

    L.append("== Open Targets trial reports of the drug")
    for row in ((col.get("parts") or {}).get("target_drugs") or {}).get("data", {}).get("rows") or []:
        dr = row.get("drug") or {}
        if drug_key(dr.get("name")) != key:
            continue
        L.append(f"drug {dr.get('name')} maxStage {row.get('maxClinicalStage')} not_same={dr.get('_unobio_not_same')}")
        L.append(f"  indications: {sorted({(i.get('disease') or {}).get('id') for i in ((dr.get('indications') or {}).get('rows') or [])} - {None})}")
        for rep in row.get("clinicalReports") or []:
            ds = sorted({(x.get('disease') or {}).get('id') for x in rep.get('diseases') or []} - {None})
            labs = [x["label"] for x in rules.label_reason(rep.get("trialWhyStopped") or "", rep.get("trialStopReasonCategories"))] \
                if rep.get("trialWhyStopped") else []
            L.append(f"  {rep.get('id')} {rep.get('clinicalStage')} {rep.get('trialOverallStatus')} diseases={ds} "
                     f"cat={rep.get('trialStopReasonCategories')} rules={labs} why={(rep.get('trialWhyStopped') or '')[:120]!r}")
    L.append("")

    L.append("== Stopped trials as the run used them (in_disease decides whether a failure counts)")
    for t in raw.get("trials") or []:
        if key in [drug_key(x) for x in t.get("same_mechanism_drugs") or []]:
            L.append(f"  {t['nct']} {t.get('stage')} {t.get('status')} in_disease={t.get('in_disease')} "
                     f"labels={[x['label'] for x in (raw.get('labels') or {}).get('labels', {}).get(t['nct'], [])]} "
                     f"why={t.get('why_stopped', '')[:100]!r}")
    L.append("")

    tr = col.get("translation") or {}
    terms = tl.disease_terms(d)
    L.append(f"== Registry rows (disease terms the run matches: {sorted(terms)[:12]})")
    for r in tl._data(tr, "aact") or []:
        if key not in [drug_key(x) for x in r.get("drugs") or []]:
            continue
        L.append(f"  {r.get('nct_id')} {r.get('stage')} {r.get('overall_status')} in_disease={tl.aact_in_disease(r, terms)} "
                 f"primary_not_met={tl.primary_not_met(r)} clinical_met={tl.clinical_primary_met(r)} "
                 f"early_other_stop={tl.stopped_for_other_reason(r)}")
        L.append(f"     conditions={r.get('conditions')} mesh={(r.get('mesh_terms') or [])[:10]}")
        for a in r.get("primary_analyses") or []:
            L.append(f"     primary: {a.get('outcome')!r} p={a.get('p_value')} {a.get('non_inferiority')}")
        if r.get("why_stopped"):
            L.append(f"     why={r['why_stopped'][:120]!r}")
    sources = (tr.get("parts") or {})
    L.append(f"  registry part: ok={(sources.get('aact') or {}).get('ok')} error={(sources.get('aact') or {}).get('error')}")
    L.append("")

    L.append("== PubMed abstracts read for the drug")
    docs = [x for x in tl.documents(tr) if drug_key(x.get("drug") or "") == key]
    names = [x["key"] for x in tr.get("drugs") or []]
    fired = {f["doc_id"]: f["result"] for f in rules.outcome_findings(docs, d, names)}
    for x in docs:
        L.append(f"  {x['id']} rule={fired.get(x['id'], '-')} {x['title'][:150]}")
    if not docs:
        L.append("  none (no abstract was downloaded for this drug)")
    L.append("")

    L.append("== Claims")
    for cl in db.get_claims(c, run["id"]):
        if cl["fact"] in ("moa_failures_efficacy_ph23", "moa_ph23_unknown_outcome_count", "moa_discontinued_safety_count",
                          "approved_same_moa_count", "moa_clinical_precedent", "genetic_support"):
            L.append(f"  {cl['fact']} = {cl['value']} ({cl['origin']}): {cl['statement'][:300]}")
    text = "\n".join(L)
    out = Path(api.__file__).resolve().parents[1] / "data" / f"diagnose_{key.lower()}.txt"
    out.write_text(text, encoding="utf-8")
    return text + f"\n\nSaved: {out}"


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    print(main(*sys.argv[1:]))

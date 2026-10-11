"""Step 8: a full run (normalize -> collect -> claims -> verdict -> memo) stored in backend/data/unobio.db, then the
memo printed as Markdown. Uses the LLM if OPENAI_API_KEY (or XAI_API_KEY) is set, otherwise template text.

Run from the repo root:
  python3 -m backend.tests.step8_report "Alzheimer disease" "BACE1 inhibitor"
  python3 -m backend.tests.step8_report "familial hypercholesterolemia" "anti-PCSK9 antibody" --phase ph2
The same run is then visible in the API (python3 main.py, GET /runs).
"""
import argparse

from backend.app import api, db
from backend.app.report import to_markdown

def print_translation(raw: dict) -> None:
    """What the translation sources returned and what the LLM extracted: why a link is shown or missing."""
    tr = (raw.get("collected") or {}).get("translation") or {}
    if not tr:
        return
    print("\nTRANSLATION SOURCES")
    for name, part in (tr.get("parts") or {}).items():
        if not part.get("ok"):
            print(f"  {name}: {'skipped' if part.get('skipped') else 'FAILED'} {part.get('error', '')[:150]}")
        elif name == "pubmed":
            for q in part["data"]:
                arts = q.get("articles") or []
                print(f"  pubmed {q.get('drug') or 'target'}: {len(arts)} papers  [{q['query'][:70]}...]")
                for a in arts:
                    tag = " (review, skipped)" if a.get("review") else " (retracted, skipped)" if a.get("retracted") else ""
                    print(f"      {a['pmid']} {a.get('year')} {a['title'][:90]}{tag}")
        elif name == "fda_labels":
            print(f"  fda_labels: {', '.join(x['drug'] for x in part['data']) or 'none (no approved drug of the class)'}")
        elif name == "aact":
            rows = part["data"] or []
            via = rows[0].get("via", "AACT") if rows else "trial registry"
            print(f"  trials ({via}): {len(rows)} trials of the class drugs")
            for r in sorted(rows, key=lambda r: r.get("stage") or "", reverse=True)[:15]:
                ps = [a.get("p_value") for a in r.get("primary_analyses") or []]
                print(f"      {r['nct_id']} {r.get('stage') or '?':<10} {r.get('overall_status') or '?':<22} "
                      f"{','.join(r.get('drugs') or [])[:20]:<20} primary p: {ps or 'none posted'}"
                      + (f"; stopped: {r['why_stopped'][:70]}" if r.get("why_stopped") else ""))
        else:
            print(f"  {name}: ok")
    findings = tr.get("findings") or []
    print(f"\nFINDINGS ({len(findings)}; used = quote found and support check passed)")
    for f in findings:
        state = "used" if f["verified"] else ("quote not found" if f.get("support") is None else "support check: no")
        print(f"  {f['doc_id']:<14} {f['drug']:<14} {f['link']:<18} {f['result']:<9} {f['species']:<6} {state:<20}"
              f" \"{f['quote'][:80]}\"")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("disease", nargs="?")
    p.add_argument("target", nargs="?")
    p.add_argument("--disease-id")
    p.add_argument("--target-id")
    p.add_argument("--phase", choices=["preclinical", "ph1", "ph2", "ph3", "filed"])
    p.add_argument("--route", choices=["oral", "subcutaneous", "iv_infusion", "intrathecal", "inhaled", "topical",
                                       "other"])
    a = p.parse_args()

    c = api.con()
    run_id = db.create_run(c, disease=a.disease, target=a.target, disease_id=a.disease_id, target_id=a.target_id,
                           phase=a.phase, route=a.route)
    print(f"{run_id}: running (Open Targets, then the LLM if a key is set; this can take a minute)...")
    api.execute(run_id)                                  # the same job the API runs in the background
    run = db.get_run(c, run_id)
    if run["status"] != "done":
        norm = run["normalized"] or {}
        print(f"Status: {run['status']}. {run['message'] or ''}")
        for kind in ("disease", "target"):
            for cand in (norm.get(kind) or {}).get("candidates") or []:
                print(f"  {kind} candidate: {cand['id']:<22} {cand['name']}")
        raise SystemExit(1)
    rep = db.get_report(c, run_id)
    if rep is None or rep["status"] != "ready":
        raise SystemExit(f"Report not written: {rep and rep['error']}")
    print(to_markdown(rep["payload"]))
    llm = rep["payload"]["llm"]
    print(f"---\nRun {run_id}. {run['message'] or 'All queries OK.'}")
    if llm["used"]:
        print(f"Report: LLM {llm['model']}, {llm['attempts']} attempt(s).")
    else:
        print("Report: no LLM key, template text.")
    for issue in llm["issues"]:
        print(f"  dropped by the validator: {issue}")
    print_translation(db.get_raw(c, run_id) or {})

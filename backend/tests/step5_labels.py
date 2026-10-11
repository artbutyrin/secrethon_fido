"""Step 5: step 4 plus LLM labels for why trials stopped (efficacy, safety, enrollment, ...).

Needs an LLM in backend/.env: TEAM_API_KEY + UNOBIO_LLM_BASE_URL (hackathon gateway), or OPENAI_API_KEY.
Model: UNOBIO_LLM_MODEL (default gpt-6-luna on the gateway). Check the connection first: python3 -m backend.tests.check_llm
Run:  python step5_labels.py "Alzheimer disease" "BACE1 inhibitor"
      python step5_labels.py "familial hypercholesterolemia" "anti-PCSK9 antibody"
Options: --phase, --route, --refresh (Open Targets), --no-llm (same as step 4).
LLM answers are cached in backend/data/llm_cache/, so a rerun gives the same labels and costs nothing.
"""
import argparse
import json

from backend.app.collect import RUNS_DIR, save
from backend.app.llm import OpenAILLM
from backend.app.opentargets import OpenTargets
from backend.app.pipeline import report_text, run

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("disease", nargs="?")
    p.add_argument("target", nargs="?")
    p.add_argument("--disease-id")
    p.add_argument("--target-id")
    p.add_argument("--phase", choices=["preclinical", "ph1", "ph2", "ph3", "filed"])
    p.add_argument("--route", choices=["oral", "subcutaneous", "iv_infusion", "intrathecal", "inhaled", "topical",
                                       "other"])
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    a = p.parse_args()

    llm = None if a.no_llm else OpenAILLM()
    if llm is not None and not llm.ready:
        raise SystemExit(f"LLM not configured: {llm.missing()}. See backend/.env.example, or run with --no-llm.")
    ot = OpenTargets(refresh=a.refresh)
    out = run(ot, a.disease, a.target, disease_id=a.disease_id, target_id=a.target_id, phase=a.phase,
              route=a.route, llm=llm)
    print(report_text(out))
    if out["status"] == "scored":
        d, t = out["normalized"]["disease"]["id"], out["normalized"]["target"]["id"]
        save(out["collected"])
        path = RUNS_DIR / f"{d}__{t}.result.json"
        path.write_text(json.dumps({k: v for k, v in out.items() if k != "collected"}, indent=1, ensure_ascii=False,
                                   default=str), encoding="utf-8")
        calls = out["llm"]["calls"]
        tokens = sum((c.get("input_tokens") or 0) + (c.get("output_tokens") or 0) for c in calls if not c["cache"])
        print(f"\nSaved: {path}")
        print(f"LLM: {llm.provider + ' ' if llm else ''}{out['llm']['model'] or 'off'}; calls {len(calls)} "
              f"({sum(not c['cache'] for c in calls)} live, {tokens} tokens)")

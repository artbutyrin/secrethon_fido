"""Step 4: disease + target -> Open Targets data -> claims by code -> scorer verdict.

Run:  python step4_score.py "Alzheimer disease" "BACE1 inhibitor"
      python step4_score.py "familial hypercholesterolemia" "anti-PCSK9 antibody" --phase ph2
Options: --phase preclinical|ph1|ph2|ph3|filed, --route oral|subcutaneous|iv_infusion|..., --refresh, --json.
Responses come from backend/data/cache/ when present. The full result goes to backend/data/runs/*.result.json.
"""
import argparse
import json

from backend.app.collect import RUNS_DIR, save
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
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    ot = OpenTargets(refresh=a.refresh)
    out = run(ot, a.disease, a.target, disease_id=a.disease_id, target_id=a.target_id, phase=a.phase, route=a.route)
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str) if a.json else report_text(out))
    if out["status"] == "scored":
        d, t = out["normalized"]["disease"]["id"], out["normalized"]["target"]["id"]
        save(out["collected"])                                   # raw data, as in step 3
        path = RUNS_DIR / f"{d}__{t}.result.json"
        path.write_text(json.dumps({k: v for k, v in out.items() if k != "collected"}, indent=1, ensure_ascii=False,
                                   default=str), encoding="utf-8")
        live = sum(not c["cache"] for c in ot.calls)
        print(f"\nSaved: {path}\nOpen Targets calls: {len(ot.calls)} ({live} live)")

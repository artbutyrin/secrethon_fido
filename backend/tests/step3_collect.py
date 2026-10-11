"""Step 3: collect raw Open Targets data for a disease + target pair and print a summary.

Run:  python step3_collect.py "Alzheimer disease" "BACE1 inhibitor"
      python step3_collect.py --disease-id MONDO_0005439 --target-id ENSG00000169174
The raw result goes to backend/data/runs/<disease>__<target>.json; every response is also in backend/data/cache/.
"""
import argparse

from backend.app.collect import collect, save, summary
from backend.app.normalize import normalize
from backend.app.opentargets import OpenTargets


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("disease", nargs="?")
    p.add_argument("target", nargs="?")
    p.add_argument("--disease-id")
    p.add_argument("--target-id")
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args()
    ot = OpenTargets(refresh=a.refresh)
    norm = normalize(ot, a.disease, a.target, a.disease_id, a.target_id)
    if norm["status"] != "resolved":
        for kind in ("disease", "target"):
            r = norm[kind]
            if r["status"] != "resolved":
                print(f"{kind}: {r['status']}. {r.get('message') or ''}")
                for c in r.get("candidates") or []:
                    print(f"  {c['id']:<22} {c['name']}")
        raise SystemExit("Not resolved: rerun with --disease-id / --target-id.")
    d, t = norm["disease"], norm["target"]
    print(f"{d['id']} {d['name']}  +  {t['id']} {t['symbol']}")
    result = collect(ot, d["id"], t["id"])
    print(summary(result))
    path = save(result)
    live = sum(not c["cache"] for c in ot.calls)
    print(f"\nSaved: {path}\nOpen Targets calls: {len(ot.calls)} ({live} live)")

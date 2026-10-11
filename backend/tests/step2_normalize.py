"""Step 2: disease + target text -> Open Targets IDs.

Run:  python step2_normalize.py "Alzheimer disease" "BACE1 inhibitor"
      python step2_normalize.py "AD" "BACE1"                     (abbreviation: expect `ambiguous`)
      python step2_normalize.py --disease-id MONDO_0004975 --target-id ENSG00000186318
Options: --refresh  ignore cached responses;  --json  print the full result.
Every Open Targets response is saved in backend/data/cache/ (send that folder back: it becomes test fixtures).
"""
import argparse
import json

from backend.app.normalize import normalize
from backend.app.opentargets import OpenTargets


def show(result: dict) -> None:
    d, t = result["disease"], result["target"]
    print(f"STATUS: {result['status']}   Open Targets release: {result['ot_release']}")
    print(f"\nDisease  query={d['query']!r}  -> {d['status']}" + (f" ({d['match']})" if d.get("match") else ""))
    if d.get("id"):
        print(f"  {d['id']}  {d['name']}")
        print(f"  therapeutic areas: {', '.join(a['name'] for a in d['therapeutic_areas']) or 'none'}")
        orpha = [x for x in d["xrefs"] if x.lower().startswith(("orphanet", "ordo"))]
        print(f"  cross-references: {len(d['xrefs'])} (Orphanet: {', '.join(orpha) or 'none'})")
    print(f"\nTarget   input={t['raw']!r}  query={t['query']!r}  -> {t['status']}"
          + (f" ({t['match']})" if t.get("match") else ""))
    print(f"  action={t['action']}  drug_type={t['drug_type']}")
    if t.get("id"):
        print(f"  {t['id']}  {t['symbol']}  {t['name']}  ({t['biotype']})")
    for label, r in (("Disease", d), ("Target", t)):
        if r.get("message"):
            print(f"\n{label}: {r['message']}")
        for c in r.get("candidates") or []:
            print(f"  candidate {c['id']:<22} {c['name']}  (score {c['score']})")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("disease", nargs="?")
    p.add_argument("target", nargs="?")
    p.add_argument("--disease-id")
    p.add_argument("--target-id")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    ot = OpenTargets(refresh=a.refresh)
    result = normalize(ot, a.disease, a.target, a.disease_id, a.target_id)
    if a.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        show(result)
    live = sum(not c["cache"] for c in ot.calls)
    print(f"\nOpen Targets calls: {len(ot.calls)} ({live} live, {len(ot.calls) - live} from cache)")

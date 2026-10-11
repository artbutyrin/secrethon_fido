"""Rescores the runs already in the database with the current scorer and shows what changed. Run from the repo root:

  python3 -m backend.tests.rescore                    # dry run: latest verdict of each done run, before -> after
  python3 -m backend.tests.rescore --write            # also store the new verdict as a new version (trigger rescore)
  python3 -m backend.tests.rescore --market-only      # keep runs without any economics input out of the table

Claims are reused as stored; nothing is fetched again except CMS prices and the Orphanet entry, which are collected
once for runs made before step 10 (from the cache, or the network unless UNOBIO_OFFLINE=1).
"""
import argparse

from backend.app import api, db
from backend.app.evidence import diff
from backend.app.market import collect_market
from backend.app.scorer import ENGINE


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rescore")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--market-only", action="store_true")
    a = ap.parse_args(argv)
    c = api.con()
    rows = []
    for r in db.list_runs(c, a.limit):
        if r["status"] != "done":
            continue
        run, before = db.get_run(c, r["id"]), db.get_score(c, r["id"])
        raw = db.get_raw(c, r["id"]) or {}
        collected = raw.get("collected") or {}
        claims = db.get_claims(c, r["id"])
        if ENGINE == "unobio_scoring" and "market" not in collected and run.get("normalized"):
            collected["market"] = collect_market(run["normalized"], claims, api.make_cms())
            if a.write:
                db.save_raw(c, r["id"], collected, raw.get("trials") or [], raw.get("labels") or {})
        after = api.score_run(run, claims, collected)
        ch = diff(before["payload"], after)
        econ = after["result"].get("economics")
        if a.market_only and not econ:
            continue
        rows.append((run, before, after, ch, econ))
        if a.write:
            v = db.add_score(c, r["id"], {**after, "evidence": {"action": "rescore", "from_version": before["version"]},
                                          "change": ch}, trigger=f"rescore:{before['version']}")
            api.make_report(r["id"], v)
    print(f"{'run':<15} {'disease + target':<55} {'before':<14} {'after':<14} caps / rules changed")
    for run, before, after, ch, econ in rows:
        name = f"{run['disease_input'] or run['disease_id']} + {run['target_input'] or run['target_id']}"[:54]
        d = ch["decision"]
        extra = [f"+{x['id']}" for x in ch["caps_added"] + ch["rules_added"]] + \
                [f"-{x['id']}" for x in ch["caps_removed"] + ch["rules_removed"]]
        mark = " *" if d["changed"] else ""
        print(f"{run['id']:<15} {name:<55} {d['from']:<14} {d['to']:<14}{mark} {' '.join(extra)}"
              + (f"  rNPV P50 {econ['monte_carlo']['p50_m']:.0f}m" if econ else ""))
    changed = sum(1 for *_, ch, _ in rows if ch["decision"]["changed"])
    print(f"\n{len(rows)} runs, {changed} verdicts changed" + ("" if a.write else " (dry run; --write stores them)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Builds a backtest set from Minikel et al. 2024 (Pharmaprojects target-indication pairs with known outcomes).

Run from the repo root:
  python3 -m backend.tests.backtest_build <path to minikel2024_genetic_support folder> [--n 20] [--seed 1]

Writes backend/tests/backtest_pairs.txt (input for run_batch) and backend/tests/backtest_truth.json (labels).

Groups (each pair is `MeSH indication | gene symbol`):
  failed_ph3   highest phase Phase III, not launched, and the target was never launched for ANY indication.
               No approved drug of the mechanism exists, so Open Targets today cannot leak the answer.
               Expectation: not Invest (Conditional or Do Not Invest).
  launched     launched pairs. Open Targets now shows the approval, so the pipeline sees the answer
               (approved_same / me-too). Expectation: not Do Not Invest. This checks the pipeline does not
               kill a working mechanism; it is NOT a forecast test.
  failed_ph2   highest phase Phase II, not launched, target never launched anywhere. Same expectation as failed_ph3.

Genetic support label per pair (Minikel's definition): an association with trait similarity comb_norm >= 0.8.
Source OMIM -> mendelian, OTG / PICCOLO / Genebass -> gwas, intOGen -> somatic. Used to check the pipeline's
`genetic_support` claim (normalisation + collection), which needs no outcome and has no leakage.
Caveat: Minikel's snapshot is 2022-2023 and Pharmaprojects marks still-active programs as "not advanced".
"""
import argparse
import csv
import gzip
import json
import random
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC_KIND = {"OMIM": "mendelian", "OTG": "gwas", "PICCOLO": "gwas", "Genebass": "gwas", "intOGen": "somatic"}
RANK = {"mendelian": 3, "somatic": 2, "gwas": 1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--n", type=int, default=20, help="pairs per group")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    pp = list(csv.DictReader(open(a.folder / "pp.tsv", encoding="utf-8"), delimiter="\t"))
    launched_genes = {r["gene"] for r in pp if r["hcat"] == "Launched"}

    gensup: dict[str, set] = defaultdict(set)
    with gzip.open(a.folder / "merge2.tsv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            try:
                sim = float(r["comb_norm"])
            except ValueError:
                continue
            if sim >= 0.8 and r["assoc_source"] in SRC_KIND:
                gensup[r["ti_uid"]].add(SRC_KIND[r["assoc_source"]])

    def label(r):
        kinds = gensup.get(r["ti_uid"], set())
        return max(kinds, key=RANK.get) if kinds else "none"

    groups = {
        "failed_ph3": [r for r in pp if r["hcat"] == "Phase III" and r["gene"] not in launched_genes],
        "failed_ph2": [r for r in pp if r["hcat"] == "Phase II" and r["gene"] not in launched_genes],
        "launched": [r for r in pp if r["hcat"] == "Launched"],
    }
    rng = random.Random(a.seed)
    truth, lines = [], ["# Backtest pairs from Minikel 2024 (built by backtest_build.py). disease | target"]
    for g, rows in groups.items():
        # half with genetic support, so the genetics check has both classes
        sup = [r for r in rows if label(r) != "none"]
        nos = [r for r in rows if label(r) == "none"]
        pick = rng.sample(sup, min(len(sup), a.n // 2)) + rng.sample(nos, min(len(nos), a.n - min(len(sup), a.n // 2)))
        lines.append(f"\n# {g}: {len(rows)} pairs in the data, {len(pick)} picked")
        for r in pick:
            lines.append(f"{r['indication_mesh_term']} | {r['gene']}")
            truth.append({"group": g, "disease": r["indication_mesh_term"], "target": r["gene"], "ti_uid": r["ti_uid"],
                          "mesh_id": r["indication_mesh_id"], "highest_phase": r["hcat"],
                          "orphan": r["orphan"] == "TRUE", "genetic_support": label(r)})
    (HERE / "backtest_pairs.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (HERE / "backtest_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    print(f"{len(truth)} pairs -> backend/tests/backtest_pairs.txt, labels -> backend/tests/backtest_truth.json")
    for g in groups:
        print(f"  {g}: {sum(t['group'] == g for t in truth)}")


if __name__ == "__main__":
    main()

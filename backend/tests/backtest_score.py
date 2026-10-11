"""Scores a backtest: joins backtest_truth.json with the latest stored run of each pair in backend/data/unobio.db.

Run from the repo root, after
  python3 -m backend.tests.backtest_build <minikel folder>
  python3 -m backend.tests.run_batch backend/tests/backtest_pairs.txt        (add --no-llm for a cheap first pass)
then
  python3 -m backend.tests.backtest_score

Prints and writes backend/data/backtest_report.md:
  1. Normalisation: share of pairs resolved / ambiguous / not found / error
  2. Gathering: pipeline genetic_support vs Minikel's label (mendelian / gwas / somatic / none)
  3. Verdict: decision by group, and the two error rates
       false Invest  = failed_ph2 / failed_ph3 pairs that got Invest
       false kill    = launched pairs that got Do Not Invest
"""
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parents[0] / "data" / "unobio.db"
OUT = HERE.parents[0] / "data" / "backtest_report.md"
# pipeline value -> Minikel class
GEN_MAP = {"mendelian": "mendelian", "mendelian_subtype": "mendelian_subtype", "gwas": "gwas", "somatic_driver": "somatic", "somatic": "somatic",
           "none": "none", "no_data": "none", "other_disease": "none"}


def latest_runs(con):
    rows = con.execute("SELECT id, disease_input, target_input, status FROM runs ORDER BY created_at").fetchall()
    return {(d.strip().lower(), t.strip().lower()): (rid, st) for rid, d, t, st in rows if d and t}


def decision(con, rid):
    r = con.execute("SELECT payload FROM scores WHERE run_id=? ORDER BY version DESC LIMIT 1", (rid,)).fetchone()
    if not r:
        return None
    p = json.loads(r[0])
    v = p.get("verdict") or (p.get("result") or {}).get("verdict") or {}
    return v.get("decision")


def claim(con, rid, fact):
    r = con.execute("SELECT value FROM claims WHERE run_id=? AND fact=? ORDER BY n DESC LIMIT 1", (rid, fact)).fetchone()
    if not r:
        return None
    try:
        return json.loads(r[0])
    except (ValueError, TypeError):
        return r[0]


def main():
    truth = json.loads((HERE / "backtest_truth.json").read_text(encoding="utf-8"))
    con = sqlite3.connect(DB)
    runs = latest_runs(con)
    status = Counter()
    gen = Counter()
    gen_rows = []
    by_group = defaultdict(Counter)
    misses = []
    for t in truth:
        key = (t["disease"].lower(), t["target"].lower())
        if key not in runs:
            status["not run"] += 1
            continue
        rid, st = runs[key]
        status[st] += 1
        if st != "done":
            continue
        d = decision(con, rid) or "—"
        by_group[t["group"]][d] += 1
        bad = (t["group"].startswith("failed") and d == "Invest") or (t["group"] == "launched" and d == "Do Not Invest")
        if bad:
            misses.append((t, d, rid))
        g = GEN_MAP.get(str(claim(con, rid, "genetic_support")), "missing")
        gen[(t["genetic_support"], g)] += 1
        gen_rows.append(t["genetic_support"] == g or (t["genetic_support"] != "none" and g not in ("none", "missing")))

    L = ["# Backtest on Minikel 2024 pairs", ""]
    L += ["## 1. Normalisation", "", "| status | pairs |", "| --- | --- |"]
    L += [f"| {k} | {v} |" for k, v in status.most_common()]
    L += ["", "## 2. Genetic support: Minikel label vs pipeline claim", "",
          f"Agreement (supported vs not): {sum(gen_rows)}/{len(gen_rows)}", "", "| Minikel | pipeline | pairs |",
          "| --- | --- | --- |"]
    L += [f"| {a} | {b} | {n} |" for (a, b), n in sorted(gen.items())]
    L += ["", "## 3. Verdicts by group", "",
          "| group | Invest | Conditional | Insufficient evidence | Do Not Invest | other |",
          "| --- | --- | --- | --- | --- | --- |"]
    for g, c in by_group.items():
        other = sum(v for k, v in c.items() if k not in ("Invest", "Conditional", "Insufficient evidence",
                                                         "Do Not Invest"))
        L.append(f"| {g} | {c['Invest']} | {c['Conditional']} | {c['Insufficient evidence']} | {c['Do Not Invest']} "
                 f"| {other} |")
    failed = sum(sum(by_group[g].values()) for g in by_group if g.startswith("failed"))
    f_inv = sum(by_group[g]["Invest"] for g in by_group if g.startswith("failed"))
    ln = sum(by_group["launched"].values())
    L += ["", f"False Invest (failed pairs rated Invest): {f_inv}/{failed}",
          f"False kill (launched pairs rated Do Not Invest): {by_group['launched']['Do Not Invest']}/{ln}", "",
          "## Pairs to read (open GET /runs/{id}/result and /claims to see why)", ""]
    L += [f"- {t['group']}: {t['disease']} | {t['target']} -> {d} (run {rid}, genetics {t['genetic_support']})"
          for t, d, rid in misses] or ["- none"]
    text = "\n".join(L) + "\n"
    OUT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

"""Runs many disease + target pairs end to end (same job as the API) and writes a summary plus every memo.

Run from the repo root:
  python3 -m backend.tests.run_batch                          # pairs from backend/tests/demo_pairs.txt
  python3 -m backend.tests.run_batch my_pairs.txt             # your own file: disease | target | phase
  python3 -m backend.tests.run_batch --only 3                 # the first 3 pairs
  python3 -m backend.tests.run_batch --no-llm                 # without the LLM (no trial labels, template memo)

Output: backend/data/batch/<time>/summary.md, summary.json and one <n>_<pair>.md memo per pair.
Every run is also stored in backend/data/unobio.db, so it is visible in the API (python3 main.py, GET /runs).
A pair that fails does not stop the others.
"""
import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from backend.app import api, db
from backend.app.report import to_markdown

HERE = Path(__file__).resolve().parent
OUT_ROOT = HERE.parents[0] / "data" / "batch"
PHASES = {"preclinical", "ph1", "ph2", "ph3", "filed"}


def read_pairs(path: Path) -> list[dict]:
    pairs = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise SystemExit(f"{path}:{n}: expected 'disease | target [| phase]', got {line!r}")
        phase = parts[2] if len(parts) > 2 and parts[2] else None
        if phase and phase not in PHASES:
            raise SystemExit(f"{path}:{n}: phase must be one of {sorted(PHASES)}, got {phase!r}")
        pairs.append({"disease": parts[0], "target": parts[1], "phase": phase})
    return pairs


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def run_pair(c, pair: dict, llms: list) -> dict:
    llms.clear()
    started = time.perf_counter()
    run_id = db.create_run(c, disease=pair["disease"], target=pair["target"], disease_id=None, target_id=None,
                           phase=pair["phase"], route=None)
    api.execute(run_id)
    run = db.get_run(c, run_id)
    out = {**pair, "run_id": run_id, "status": run["status"], "message": run["message"],
           "seconds": round(time.perf_counter() - started, 1)}
    calls = [x for llm in llms for x in getattr(llm, "calls", []) if isinstance(x, dict) and not x.get("cache")]
    out["llm_calls"] = len(calls)
    out["llm_tokens"] = sum((x.get("input_tokens") or 0) + (x.get("output_tokens") or 0) for x in calls)
    norm = run["normalized"] or {}
    out["disease_id"] = (norm.get("disease") or {}).get("id")
    out["target_id"] = (norm.get("target") or {}).get("symbol")
    if run["status"] != "done":
        out["candidates"] = {k: [f"{x['id']} {x['name']}" for x in (norm.get(k) or {}).get("candidates") or []][:5]
                             for k in ("disease", "target")}
        return out
    res = db.get_score(c, run_id)["payload"]["result"]
    out.update(decision=res["verdict"]["decision"], grounds=res["verdict"]["grounds"],
               pluses=res["score"]["pos"], minuses=res["score"]["neg"],
               rules=[f"{r['tier']}: {r['name']}" for r in res["rules"]],
               greens=[i["name"] for i in res["scorecard"] if i["color"] == "G"],
               reds=[i["name"] for i in res["scorecard"] if i["color"] == "R"])
    rep = db.get_report(c, run_id)
    if rep and rep["status"] == "ready":
        out["report"] = to_markdown(rep["payload"])
        out["report_by"] = sorted({s["generated_by"] for s in rep["payload"]["sections"]})
        out["validator_dropped"] = len(rep["payload"]["llm"]["issues"])
    else:
        out["report_error"] = rep and rep["error"]
    return out


def summary_md(results: list[dict], started: str) -> str:
    lines = [f"# Batch run {started}", "",
             "| # | Pair | Status | Decision | Grounds | +/− | Rules fired | LLM tokens | Run |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for n, r in enumerate(results, 1):
        pair = f"{r['disease']} + {r['target']}" + (f" ({r['phase']})" if r["phase"] else "")
        rules = "<br>".join(r.get("rules") or []) or "—"
        pm = f"{r['pluses']}/{r['minuses']}" if "pluses" in r else "—"
        lines.append(f"| {n} | {pair} | {r['status']} | {r.get('decision', '—')} | {r.get('grounds', '—')} | {pm} | "
                     f"{rules} | {r['llm_tokens']} | `{r['run_id']}` |")
    notes = [r for r in results if r["status"] != "done" or r.get("message") or r.get("validator_dropped")]
    if notes:
        lines += ["", "## Notes", ""]
        for r in notes:
            lines.append(f"- **{r['disease']} + {r['target']}**: {r['status']}"
                         + (f"; {r['message']}" if r.get("message") else "")
                         + (f"; validator dropped {r['validator_dropped']} paragraph(s)"
                            if r.get("validator_dropped") else ""))
            for kind, cands in (r.get("candidates") or {}).items():
                if cands:
                    lines.append(f"  - {kind} candidates: {'; '.join(cands)}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("pairs", nargs="?", default=str(HERE / "demo_pairs.txt"))
    p.add_argument("--only", type=int)
    p.add_argument("--no-llm", action="store_true")
    a = p.parse_args()

    pairs = read_pairs(Path(a.pairs))[:a.only]
    llms: list = []
    make_llm = api.make_llm
    api.make_llm = (lambda: None) if a.no_llm else (lambda: (lambda x: (llms.append(x) if x else None, x)[1])(make_llm()))
    if not a.no_llm and make_llm() is None:
        print("No LLM configured (backend/.env): trial labels are skipped and memos use template text.")

    started = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = OUT_ROOT / started
    out_dir.mkdir(parents=True, exist_ok=True)
    c = api.con()
    results = []
    for n, pair in enumerate(pairs, 1):
        print(f"[{n}/{len(pairs)}] {pair['disease']} + {pair['target']} ...", flush=True)
        try:
            r = run_pair(c, pair, llms)
        except Exception as exc:                          # one broken pair must not stop the batch
            r = {**pair, "run_id": None, "status": "error", "message": f"{type(exc).__name__}: {exc}",
                 "llm_calls": 0, "llm_tokens": 0}
            import traceback
            traceback.print_exc()
        results.append(r)
        if r.get("report"):
            (out_dir / f"{n:02d}_{slug(pair['disease'])}__{slug(pair['target'])}.md").write_text(
                r["report"], encoding="utf-8")
        what = r.get("decision") or r["status"]
        print(f"      {what}" + (f" ({r['grounds']})" if r.get("grounds") else "")
              + (f"; rules: {'; '.join(r['rules'])}" if r.get("rules") else "")
              + (f"; {r['message']}" if r["status"] != "done" and r.get("message") else "")
              + f"; {r.get('seconds', 0)} s, {r['llm_tokens']} LLM tokens")

    (out_dir / "summary.md").write_text(summary_md(results, started), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps([{k: v for k, v in r.items() if k != "report"} for r in results],
                                                     indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone: {sum(r['status'] == 'done' for r in results)} of {len(results)} scored. "
          f"LLM tokens: {sum(r['llm_tokens'] for r in results)}.")
    print(f"Summary and memos: {out_dir}")

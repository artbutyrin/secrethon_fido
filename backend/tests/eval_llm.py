"""Live check of the LLM tasks against hand-labelled cases (llm_gold.py), with a trace of every step.

Run from the repo root (needs the key in backend/.env, like check_llm):
  python3 -m backend.tests.eval_llm                      # all three sets, fresh answers, failures traced
  python3 -m backend.tests.eval_llm -v                   # trace passing cases too
  python3 -m backend.tests.eval_llm --only stops         # stops | translation | support
  python3 -m backend.tests.eval_llm --case negation      # cases whose id, tag or text contains this
  python3 -m backend.tests.eval_llm --repeat 3           # ask 3 times: finds cases that flip between runs
  python3 -m backend.tests.eval_llm --model gpt-5-mini   # another model
  python3 -m backend.tests.eval_llm --record             # save the answers for test_llm_replay.py (offline)
Every run writes a JSON report with the raw answers and traces to backend/data/eval/.
Exit code 1 if any case fails.

Reading a failure: the trace shows each label or finding the model gave and what happened to it
  "quote NOT FOUND"      the model's quote is not in the text (made up or paraphrased)
  "support check: NO"    the quote is real but the checker says it does not state the label
  "labeller gave no labels" / "extractor gave no findings"   the first step missed it
If the support set (`--only support`) passes but a stop case fails at "support check: NO", the checker's input or
wording for that label is the problem, not the checker's judgement.
"""
import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from backend.app import support, translation, trials
from backend.app.llm import OpenAILLM
from backend.app.support import check_support
from backend.app.translation import extract_findings
from backend.app.trials import LABELS, label_trials
from backend.tests import llm_gold as gold

FIXTURES = Path(__file__).parent / "fixtures" / "llm"
REPORTS = Path(__file__).resolve().parents[1] / "data" / "eval"


def prompts_fingerprint() -> str:
    """Short hash of every prompt and check wording: tells which version of the prompts a run used."""
    text = json.dumps([trials.SYSTEM, trials.CHECKED, support.SYSTEM, translation.SYSTEM], sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:10]


def table(title: str, rows: list[dict], verbose: bool) -> int:
    print(f"\n{title}: {sum(r['ok'] for r in rows)}/{len(rows)} pass   by tag: {gold.tag_stats(rows)}")
    for r in rows:
        if r["ok"] and not verbose:
            continue
        mark = "ok  " if r["ok"] else "FAIL"
        extra = (f"  missing {r['missing']}" if r["missing"] else "") + (f"  wrong {r['wrong']}" if r["wrong"] else "")
        print(f"  {mark} {r['case']:<12} [{r['tag']}] want {r['want']} got {r['got']}{extra}")
        print(f"       text: {r['text'][:130]}")
        for t in r["trace"]:
            print(f"       - {t}")
    return sum(not r["ok"] for r in rows)


def pick(cases: list[dict], needle: str | None, *keys) -> list[dict]:
    if not needle:
        return cases
    n = needle.lower()
    return [c for c in cases if any(n in str(c.get(k, "")).lower() for k in keys)]


def run_once(llm, a) -> dict:
    out = {}
    if a.only in (None, "stops"):
        cases = pick(gold.STOP_CASES, a.case, "nct", "tag", "why")
        if cases:
            res = label_trials(llm, gold.stop_trials(cases))
            out["stops"] = {"rows": gold.score_stops(res["labels"], cases), "errors": res["errors"],
                            "raw": res["labels"]}
    if a.only in (None, "translation"):
        cases = pick(gold.TRANSLATION_CASES, a.case, "id", "tag", "text")
        if cases:
            res = extract_findings(llm, gold.translation_docs(cases), gold.DISEASE, gold.TARGET, gold.DRUGS)
            out["translation"] = {"rows": gold.score_translation(res["findings"], cases), "errors": res["errors"],
                                  "raw": res["findings"]}
    if a.only in (None, "support"):
        cases = pick(gold.SUPPORT_CASES, a.case, "id", "tag", "quote")
        if cases:
            res = check_support(llm, gold.support_items(cases))
            out["support"] = {"rows": gold.score_support(res["verdicts"], cases), "errors": res["errors"],
                              "raw": res["verdicts"]}
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model")
    p.add_argument("--record", action="store_true", help="save answers as offline fixtures")
    p.add_argument("--only", choices=["stops", "translation", "support"])
    p.add_argument("--case", help="only cases whose id, tag or text contains this")
    p.add_argument("--repeat", type=int, default=1, help="ask N times with a fresh cache to find unstable cases")
    p.add_argument("-v", "--verbose", action="store_true", help="trace passing cases too")
    a = p.parse_args()

    titles = {"stops": "Stop reasons", "translation": "Translation findings", "support": "Support checker alone"}
    runs, failed, first_cache, model = [], 0, None, None
    for i in range(a.repeat):
        cache = Path(tempfile.mkdtemp(prefix="unobio-llm-eval-"))
        llm = OpenAILLM(model=a.model, cache_dir=cache)
        if llm.missing():
            raise SystemExit(f"Not configured: {llm.missing()} (see python3 -m backend.tests.check_llm)")
        model = llm.model
        if i == 0:
            print(f"provider {llm.provider}, model {llm.model}, prompts {prompts_fingerprint()}")
        res = run_once(llm, a)
        fresh = [c for c in llm.calls if not c.get("cache")]
        res["usage"] = {"calls": len(fresh), "input_tokens": sum(c.get("input_tokens") or 0 for c in fresh),
                        "output_tokens": sum(c.get("output_tokens") or 0 for c in fresh), "json_mode": llm.json_mode}
        runs.append(res)
        if a.repeat > 1:
            print(f"\n===== run {i + 1} of {a.repeat}")
        for key, title in titles.items():
            if key in res:
                failed += table(title, res[key]["rows"], a.verbose)
                for e in res[key]["errors"]:
                    print(f"  LLM error: {e}")
        if "stops" in res:
            print("\n  per label (stops): " + ", ".join(
                f"{lab} {s['found']}/{s['want']} found, {s['wrong']} wrong"
                for lab, s in gold.label_stats(res["stops"]["rows"], LABELS).items() if s["want"] or s["wrong"]))
        u = res["usage"]
        print(f"\n{u['calls']} LLM calls, tokens in/out {u['input_tokens']}/{u['output_tokens']}, JSON mode {u['json_mode']}")
        if i == 0:
            first_cache = cache
        else:
            shutil.rmtree(cache, ignore_errors=True)

    if a.repeat > 1:                               # cases whose result changed between runs
        flaky = []
        for key in titles:
            per_case: dict[str, set] = {}
            for r in runs:
                for row in (r.get(key) or {}).get("rows", []):
                    per_case.setdefault(row["case"], set()).add(row["ok"])
            flaky += [f"{key}:{c}" for c, oks in per_case.items() if len(oks) > 1]
        print(f"\nUnstable across {a.repeat} runs: {', '.join(flaky) or 'none'}")

    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report = REPORTS / f"eval_{stamp}_{model}.json"
    report.write_text(json.dumps({"model": model, "prompts": prompts_fingerprint(), "args": vars(a), "runs": runs},
                                 indent=1, ensure_ascii=False, default=sorted), encoding="utf-8")
    print(f"Report with raw answers and traces: {report}")

    if a.record:
        if a.only or a.case:
            print("Not recorded: --record needs the full set (no --only / --case).")
        else:
            FIXTURES.mkdir(parents=True, exist_ok=True)
            for f in FIXTURES.glob("*.json"):
                f.unlink()
            for f in first_cache.glob("*.json"):
                shutil.copy(f, FIXTURES / f.name)
            (FIXTURES / "MODEL").write_text(model, encoding="utf-8")
            (FIXTURES / "PROMPTS").write_text(prompts_fingerprint(), encoding="utf-8")
            baseline = {key: {row["case"]: row["ok"] for row in runs[0][key]["rows"]} for key in titles if key in runs[0]}
            (FIXTURES / "BASELINE.json").write_text(json.dumps(baseline, indent=1, sort_keys=True), encoding="utf-8")
            print(f"Recorded {len(list(first_cache.glob('*.json')))} answers to {FIXTURES} (model {model}, "
                  f"prompts {prompts_fingerprint()}).")
    shutil.rmtree(first_cache, ignore_errors=True)
    raise SystemExit(1 if failed else 0)

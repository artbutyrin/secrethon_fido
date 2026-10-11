"""Second sample: 15 "disease | explicit mechanism" pairs (mechanism_pairs.txt) that test the mechanism logic on live
data — same-mechanism drugs, direction, efficacy failures vs other stop reasons, positive precedents. It checks
properties, not a target verdict distribution; nothing here tunes a threshold.

Run from the repo root:
  python -m backend.tests.mechanism_sample             # all 15 pairs, live (Open Targets, registry, PubMed, LLM)
  python -m backend.tests.mechanism_sample --no-llm    # no stop labels: efficacy-failure checks become open

Output: backend/data/mechanism_sample/<time>/report.md and results.json; every run is also in backend/data/unobio.db.
Offline checks of the same file (parser, recorded runs): backend/tests/test_mechanism_sample.py.

Each failed check names the layer to look at:
  parser       query / action                  backend/app/mechanism.py
  mechanism    same / approved_same / precedent  collection + same-mechanism logic (collect.py, facts.py)
  trials       efficacy_failure                 stop-reason labels, registry results, papers (trials.py, translation.py)
  scorer       verdict_if_confirmed             unobio_scoring
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAIRS = HERE / "mechanism_pairs.txt"
OUT_ROOT = HERE.parents[0] / "data" / "mechanism_sample"
LAYER = {"query": "parser", "action": "parser", "same": "mechanism", "approved_same": "mechanism",
         "precedent": "mechanism", "efficacy_failure": "trials", "verdict_if_confirmed": "scorer",
         "verdict": "scorer"}
# 2.4: "verdict" checks the verdict itself (A/B = one of), so a wrong verdict is a fail, not hidden among 68 passes
_EXP = re.compile(r"^(query|action|approved_same|precedent|same|efficacy_failure|verdict_if_confirmed|verdict)"
                  r"(>=|!=|\+=|-=|=)(.+?)(\?)?$")


def parse_expectation(text: str) -> dict:
    m = _EXP.match(text.strip())
    if not m:
        raise ValueError(f"cannot read expectation {text!r}")
    key, op, value, optional = m.groups()
    return {"key": key, "op": op, "value": value.strip(), "optional": bool(optional), "text": text.strip()}


def read_pairs(path: Path = PAIRS) -> list[dict]:
    pairs = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4 or not all(parts):
            raise ValueError(f"{path.name}:{n}: expected 'disease | mechanism | expectations | why'")
        pairs.append({"disease": parts[0], "mechanism": parts[1], "why": parts[3],
                      "expect": [parse_expectation(x) for x in parts[2].split(";") if x.strip()]})
    return pairs


# --- what the pipeline saw ------------------------------------------------------------------------------------------
def observe(norm: dict, collected: dict | None, claims: list[dict], score_payload: dict | None) -> dict:
    """The observable properties of one analysed pair, from what the pipeline stored."""
    from backend.app.facts import _same_mechanism, drug_key
    from backend.app.pipeline import score_claims
    t = norm.get("target") or {}
    by_fact = {}
    for c in claims:
        by_fact[c["fact"]] = c                                  # the latest claim of each fact
    same = set()
    part = ((collected or {}).get("parts") or {}).get("target_drugs") or {}
    for row in ((part.get("data") or {}).get("rows") or []) if part.get("ok") else []:
        drug = row.get("drug") or {}
        if t.get("id") and _same_mechanism(drug, t["id"], t.get("action"))[0]:
            same.add(drug_key(drug.get("name")))
    fail = by_fact.get("moa_failures_efficacy_ph23")
    failures = {d for s in (fail or {}).get("sources") or [] for d in s.get("drugs") or []}
    verdict = confirmed = None
    if score_payload:
        verdict = score_payload["result"]["verdict"]["decision"]
        confirmed = score_claims([dict(c, confirmed=True) if c.get("origin") == "llm" else c
                                  for c in claims])["result"]["verdict"]["decision"]
    value = lambda f: (by_fact.get(f) or {}).get("value")  # noqa: E731
    return {"query": t.get("query"), "action": t.get("action"), "target": t.get("symbol"),
            "approved_same": value("approved_same_moa_count"), "precedent": value("moa_clinical_precedent"),
            "same": sorted(same), "efficacy_failure": sorted(failures), "failures_checked": fail is not None,
            "verdict": verdict, "verdict_if_confirmed": confirmed}


def check(e: dict, obs: dict) -> str:
    """pass / fail / open (an optional expectation that is not met, or a value the run never produced)."""
    got = obs.get(e["key"])
    names = {x.strip().upper() for x in e["value"].split(",") if x.strip()}
    if e["key"] in ("same", "efficacy_failure"):
        have = set(got or [])
        ok = names <= have if e["op"] == "+=" else not (names & have)
    elif e["key"] == "approved_same":
        if got is None:
            return "open" if e["optional"] else "fail"
        ok = got >= int(e["value"]) if e["op"] == ">=" else got == int(e["value"])
    elif e["key"] == "verdict":
        if got is None:
            return "open"
        allowed = {x.strip().lower() for x in e["value"].split("/")}
        ok = (got.lower() in allowed) if e["op"] == "=" else (got.lower() not in allowed)
    elif e["op"] == "!=":
        if got is None:
            return "open"
        ok = got != e["value"]
    else:
        ok = str(got).lower() == e["value"].lower()
    if ok:
        return "pass"
    return "open" if e["optional"] else "fail"


def evaluate(pair: dict, obs: dict) -> list[dict]:
    out = []
    for e in pair["expect"]:
        r = check(e, obs)
        detail = obs.get(e["key"])
        out.append({**e, "result": r, "layer": LAYER[e["key"]],
                    "observed": detail if not isinstance(detail, list) else ", ".join(detail) or "none"})
    return out


# --- live run -------------------------------------------------------------------------------------------------------
def run_one(c, pair: dict) -> dict:
    from backend.app import api, db
    started = time.perf_counter()
    run_id = db.create_run(c, disease=pair["disease"], target=pair["mechanism"], disease_id=None, target_id=None,
                           phase=None, route=None)
    api.execute(run_id)
    run = db.get_run(c, run_id)
    out = {"disease": pair["disease"], "mechanism": pair["mechanism"], "run_id": run_id, "status": run["status"],
           "seconds": round(time.perf_counter() - started, 1), "message": run["message"]}
    if run["status"] != "done":
        out["checks"] = [{**e, "result": "fail" if not e["optional"] else "open", "layer": "normalisation",
                          "observed": run["status"]} for e in pair["expect"]]
        return out
    raw = db.get_raw(c, run_id) or {}
    score = db.get_score(c, run_id)
    obs = observe(run["normalized"] or {}, raw.get("collected"), db.get_claims(c, run_id),
                  score["payload"] if score else None)
    checks = evaluate(pair, obs)
    if run.get("incomplete"):
        # 2.4: a run with failed sources says nothing about the verdict logic: its verdict checks are "open"
        for ch in checks:
            if ch["layer"] == "scorer" and ch["result"] == "fail":
                ch.update(result="open", observed=f"{ch['observed']} (incomplete run: rerun)")
    out.update(incomplete=run.get("incomplete") or [])
    out.update(observed=obs, checks=checks, verdict=obs["verdict"],
               verdict_if_confirmed=obs["verdict_if_confirmed"],
               grounds=score["payload"]["result"]["verdict"]["grounds"] if score else None)
    return out


def report(results: list[dict], started: str, total_s: float) -> str:
    n = lambda r: sum(1 for x in results for c in x.get("checks", []) if c["result"] == r)  # noqa: E731
    L = [f"# Mechanism sample {started}", "",
         f"{len(results)} pairs, {total_s / 60:.1f} min. Checks: {n('pass')} pass, {n('fail')} fail, {n('open')} open "
         "(an optional expectation the public data did not expose).", "",
         "| # | Pair | Verdict | If pending claims confirmed | Complete | Pass | Fail | Open | Run |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for i, r in enumerate(results, 1):
        cs = r.get("checks", [])
        cnt = lambda k: sum(1 for c in cs if c["result"] == k)  # noqa: E731
        L.append(f"| {i} | {r['disease']} + {r['mechanism']} | {r.get('verdict') or r['status']} | "
                 f"{r.get('verdict_if_confirmed') or '—'} | {'no' if r.get('incomplete') else 'yes'} | "
                 f"{cnt('pass')} | {cnt('fail')} | {cnt('open')} | "
                 f"`{r['run_id']}` |")
    bad = [(r, c) for r in results for c in r.get("checks", []) if c["result"] != "pass"]
    if bad:
        L += ["", "## Checks that did not pass", "", "| Pair | Check | Result | Layer | Observed |",
              "| --- | --- | --- | --- | --- |"]
        L += [f"| {r['disease']} + {r['mechanism']} | `{c['text']}` | {c['result']} | {c['layer']} | "
              f"{str(c['observed'])[:120].replace('|', '/')} |" for r, c in bad]
    layers = {}
    for _, c in bad:
        if c["result"] == "fail":
            layers[c["layer"]] = layers.get(c["layer"], 0) + 1
    L += ["", "## Failed checks by layer", ""] + ([f"- {k}: {v}" for k, v in sorted(layers.items())] or ["- none"])
    inc = [r for r in results if r.get("incomplete")]
    if inc:
        L += ["", "## Incomplete runs (sources failed: rerun these pairs)", ""]
        L += [f"- {r['disease']} + {r['mechanism']}: {'; '.join(x[:100] for x in r['incomplete'])}" for r in inc]
    L += ["", "Checks run on today's data: they test what the pipeline does with it, not what it could have known "
          "at the time of each clinical decision."]
    return "\n".join(L) + "\n"


def main() -> Path:
    from backend.app import api
    p = argparse.ArgumentParser()
    p.add_argument("--no-llm", action="store_true")
    a = p.parse_args()
    if a.no_llm:
        api.make_llm = lambda: None
    pairs = read_pairs()
    started = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = OUT_ROOT / started
    out_dir.mkdir(parents=True, exist_ok=True)
    c = api.con()
    results, t0 = [], time.perf_counter()
    for i, pair in enumerate(pairs, 1):
        print(f"[{i}/{len(pairs)}] {pair['disease']} + {pair['mechanism']} ...", flush=True)
        try:
            r = run_one(c, pair)
        except Exception as exc:                          # one broken pair must not stop the sample
            r = {"disease": pair["disease"], "mechanism": pair["mechanism"], "run_id": None, "status": "error",
                 "message": f"{type(exc).__name__}: {exc}", "checks": []}
        results.append(r)
        cs = r.get("checks", [])
        print(f"      {r.get('verdict') or r['status']}{' (INCOMPLETE RUN)' if r.get('incomplete') else ''}; checks: "
              + ", ".join(f"{k} {sum(1 for x in cs if x['result'] == k)}" for k in ("pass", "fail", "open"))
              + "".join(f"\n      FAIL {x['text']} (observed: {str(x['observed'])[:80]})"
                        for x in cs if x["result"] == "fail"), flush=True)
    text = report(results, started, time.perf_counter() - t0)
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    (out_dir / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n" + text + f"\nReport: {out_dir / 'report.md'}")
    return out_dir


if __name__ == "__main__":
    main()

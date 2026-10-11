"""Live test on a stratified sample of pairs with a known outcome (Minikel et al. 2024, backtest_truth.json).

Runs the whole pipeline on live data (Open Targets, ClinicalTrials.gov, PubMed, openFDA, UniProt, the LLM), then
compares each verdict with what happened to the pair in drug development:

  failed_ph3 / failed_ph2   the pair reached Phase 3 / Phase 2 and was not launched  -> Invest is a false Invest
  launched                  a drug on this target was launched for this disease      -> Do Not Invest is a false kill
  Insufficient evidence is counted on its own: it is not a call either way.

Selection (inclusion criteria, checked BEFORE the sample is cut to n): a pair counts only if its disease and target
resolve in Open Targets (backend.app.normalize, MeSH headings included), the resolved disease is the pair's MeSH
entity (its MeSH ID in the disease's cross-references, or the same name in another convention), and no other picked
pair resolved to the same disease + target. Candidates per group come in a fixed order: first the pairs the plain
seeded draw picks (so seed 9 keeps the pairs of the 10 October run), then reserves from a second seeded draw. Pairs
that fail a criterion are listed in the report with the reason; they are not silently replaced.

Run from the repo root:
  python -m backend.tests.live_sample                 # 15 pairs: 5 per group, seed 9
  python -m backend.tests.live_sample --n 30 --seed 1
  python -m backend.tests.live_sample --no-llm        # cheap first pass (no stop labels, template memo)

Output: backend/data/live_sample/<time>/report.md and results.json. Every run is also in backend/data/unobio.db.

Limits of the reference: Minikel pairs name a target only ("CETP"), not a mechanism ("CETP inhibitor"), so
same-mechanism facts need a direction word the input does not have (analysis of 9 October, 3.3); and "failed" means
not launched for this disease, not proven ineffective. Read the misses before changing a rule.
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from backend.app import api, db
from backend.app.normalize import normalize, same_name
from backend.tests.backtest_score import GEN_MAP

HERE = Path(__file__).resolve().parent
TRUTH = HERE / "backtest_truth.json"
OUT_ROOT = HERE.parents[0] / "data" / "live_sample"
GROUPS = ["failed_ph3", "failed_ph2", "launched"]


def per_group(n: int) -> dict[str, int]:
    return {g: n // len(GROUPS) + (1 if i < n % len(GROUPS) else 0) for i, g in enumerate(GROUPS)}


def sample(truth: list[dict], n: int, seed: int) -> list[dict]:
    """The plain seeded draw: n pairs, as even as possible across the three groups (the pairs of earlier runs)."""
    rng = random.Random(seed)
    by = defaultdict(list)
    for t in truth:
        by[t["group"]].append(t)
    per = per_group(n)
    out = []
    for g in GROUPS:
        out += rng.sample(by[g], min(per[g], len(by[g])))
    return out


def candidates(truth: list[dict], n: int, seed: int) -> dict[str, list[dict]]:
    """Per group: the plain draw first, then every other pair of the group in a second seeded order (reserves).
    Exact duplicates (same disease and target text) appear once."""
    first = sample(truth, n, seed)
    rng = random.Random(f"{seed}-reserve")
    out: dict[str, list[dict]] = {}
    for g in GROUPS:
        head = [t for t in first if t["group"] == g]
        rest = [t for t in truth if t["group"] == g and t not in head]
        rng.shuffle(rest)
        seen, ordered = set(), []
        for t in head + rest:
            k = (t["disease"].strip().lower(), t["target"].strip().upper())
            if k not in seen:
                seen.add(k)
                ordered.append(t)
        out[g] = ordered
    return out


def is_mesh_entity(t: dict, disease: dict) -> bool:
    """The resolved disease is the pair's MeSH entity: its MeSH ID is a cross-reference, or it has the same name
    (written in another convention) or the same exact synonym."""
    xrefs = {str(x).upper() for x in disease.get("xrefs") or []}
    if t.get("mesh_id") and f"MESH:{t['mesh_id']}".upper() in xrefs:
        return True
    return any(same_name(t["disease"], x) for x in [disease.get("name"), *(disease.get("synonyms") or [])])


def select(ot, truth: list[dict], n: int, seed: int) -> tuple[list[dict], list[dict]]:
    """(picked pairs with their resolved IDs, dropped pairs with the reason), checking every criterion before the
    sample is cut to n. Uses Open Targets search only (cached), no LLM."""
    picked, dropped, used = [], [], set()
    for g, pairs in candidates(truth, n, seed).items():
        need = per_group(n)[g]
        for t in pairs:
            if sum(1 for p in picked if p["group"] == g) >= need:
                break
            try:
                norm = normalize(ot, t["disease"], t["target"])
            except Exception as exc:                      # a source error drops this pair, not the sample
                dropped.append({**t, "reason": f"error: {type(exc).__name__}: {str(exc)[:120]}"})
                continue
            d, tg = norm["disease"], norm["target"]
            if norm["status"] != "resolved":
                why = "; ".join(f"{k}: {x['status']} ({(x.get('message') or '')[:90]})"
                                for k, x in (("disease", d), ("target", tg)) if x["status"] != "resolved")
                dropped.append({**t, "reason": why})
                continue
            if not is_mesh_entity(t, d):
                dropped.append({**t, "reason": f"resolved to {d['id']} {d['name']}, which is not MeSH {t['mesh_id']}"})
                continue
            if (d["id"], tg["id"]) in used:
                dropped.append({**t, "reason": f"duplicate of an earlier pair: {d['name']} + {tg['symbol']}"})
                continue
            used.add((d["id"], tg["id"]))
            picked.append({**t, "disease_id": d["id"], "target_id": tg["id"], "match": d["match"],
                           "resolved_name": d["name"]})
    return picked, dropped


def llm_stats(collected: dict | None) -> dict:
    """Live LLM calls of the run, their time and errors by kind (from the stored run log)."""
    calls = [x for x in ((collected or {}).get("log") or {}).get("llm", []) if not x.get("cache")]
    kinds = Counter()
    for x in calls:
        e = (x.get("error") or "").lower()
        if not e:
            continue
        kinds["input too big" if "input limit" in e else "output limit" if "output token" in e
              else "429 busy" if "429" in e else "not JSON" if "not json" in e else "other"] += 1
    return {"calls": len(calls), "llm_s": round(sum((x.get("latency_ms") or 0) for x in calls) / 1000, 1),
            "tokens": sum((x.get("input_tokens") or 0) + (x.get("output_tokens") or 0) for x in calls),
            "errors": dict(kinds)}


def one(c, t: dict) -> dict:
    started = time.perf_counter()
    run_id = db.create_run(c, disease=t["disease"], target=t["target"], disease_id=t.get("disease_id"),
                           target_id=t.get("target_id"), phase=None, route=None)
    api.execute(run_id)
    run = db.get_run(c, run_id)
    raw = db.get_raw(c, run_id) or {}
    out = {**t, "run_id": run_id, "status": run["status"], "seconds": round(time.perf_counter() - started, 1),
           "message": run["message"], **llm_stats(raw.get("collected"))}
    norm = run["normalized"] or {}
    dn, ts = (norm.get("disease") or {}).get("name"), (norm.get("target") or {}).get("symbol")
    out["resolved_as"] = f"{dn or '—'} + {ts or '—'}" + (f" ({t['match']})" if t.get("match") else "")
    if run["status"] != "done":
        out["candidates"] = [f"{x['id']} {x['name']}" for x in (norm.get("disease") or {}).get("candidates") or []][:4]
        return out
    res = db.get_score(c, run_id)["payload"]["result"]
    v = res["verdict"]
    out.update(decision=v["decision"], grounds=v["grounds"], pluses=res["score"]["pos"], minuses=res["score"]["neg"],
               rules=[f"{r['tier']}: {r['name']}" for r in res["rules"]])
    gen = next((x["value"] for x in reversed(db.get_claims(c, run_id)) if x["fact"] == "genetic_support"), None)
    out["genetics"] = GEN_MAP.get(str(gen), "missing")
    reg = ((raw.get("collected") or {}).get("translation") or {}).get("parts", {}).get("aact") or {}
    out["registry"] = "ok" if reg.get("ok") else ("skipped" if reg.get("skipped") else "error")
    return out


def judge(r: dict) -> str:
    d = r.get("decision")
    if d is None:
        return "not scored"
    if r["group"].startswith("failed"):
        return "FALSE INVEST" if d == "Invest" else "ok"
    return "FALSE KILL" if d == "Do Not Invest" else "ok"


def report(results: list[dict], seed: int, started: str, total_s: float, dropped: list[dict] | None = None) -> str:
    scored = [r for r in results if r.get("decision")]
    by = defaultdict(Counter)
    for r in scored:
        by[r["group"]][r["decision"]] += 1
    failed = [r for r in scored if r["group"].startswith("failed")]
    launched = [r for r in scored if r["group"] == "launched"]
    gen = [r for r in scored if r.get("genetics") is not None]
    gen_ok = sum(1 for r in gen if r["genetics"] == r["genetic_support"]
                 or (r["genetic_support"] != "none" and r["genetics"] not in ("none", "missing")))
    errs = Counter()
    for r in results:
        errs.update(r.get("errors") or {})
    insufficient = sum(1 for r in scored if r.get("decision") == "Insufficient evidence")
    L = [f"# Live sample {started}", "",
         f"{len(results)} pairs from Minikel et al. 2024 (seed {seed}), {total_s / 60:.1f} min, "
         f"{sum(r.get('tokens') or 0 for r in results):,} LLM tokens.", "",
         "## Summary", "",
         "| Check | Result |", "| --- | --- |",
         f"| Normalised and scored | {len(scored)} of {len(results)} |",
         f"| Candidates not used (criteria checked before the cut) | {len(dropped or [])} |",
         f"| False Invest (failed pair rated Invest) | {sum(1 for r in failed if r['decision'] == 'Invest')} of {len(failed)} |",
         f"| False kill (launched pair rated Do Not Invest) | "
         f"{sum(1 for r in launched if r['decision'] == 'Do Not Invest')} of {len(launched)} |",
         f"| Insufficient evidence (no call either way) | {insufficient} of {len(scored)} |",
         f"| Genetic support agrees with Minikel | {gen_ok} of {len(gen)} |",
         f"| LLM errors | {', '.join(f'{k}: {v}' for k, v in errs.most_common()) or 'none'} |", "",
         "## Verdicts by group", "", "| Group | Invest | Conditional | Insufficient evidence | Do Not Invest |",
         "| --- | --- | --- | --- | --- |"]
    L += [f"| {g} | {by[g]['Invest']} | {by[g]['Conditional']} | {by[g]['Insufficient evidence']} | "
          f"{by[g]['Do Not Invest']} |" for g in GROUPS]
    L += ["", "## Every pair", "",
          "| # | Group | Pair | Resolved as | Verdict | Grounds | +/− | Genetics (Minikel → pipeline) | Check | s | Run |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for i, r in enumerate(results, 1):
        pm = f"{r['pluses']}/{r['minuses']}" if "pluses" in r else "—"
        L.append(f"| {i} | {r['group']} | {r['disease']} + {r['target']} | {r.get('resolved_as', '—')} | "
                 f"{r.get('decision') or r['status']} | {r.get('grounds', '—')} | {pm} | "
                 f"{r['genetic_support']} → {r.get('genetics', '—')} | {judge(r)} | {r.get('seconds', 0):.0f} | "
                 f"`{r['run_id']}` |")
    notes = [r for r in results if r["status"] != "done" or judge(r) != "ok"]
    if notes:
        L += ["", "## To read", ""]
        for r in notes:
            why = "; ".join(r.get("rules") or []) or r.get("grounds") or ""
            L.append(f"- **{r['disease']} + {r['target']}** ({r['group']}): {r.get('decision') or r['status']}"
                     + (f" — {why}" if why else "")
                     + (f"; candidates: {'; '.join(r['candidates'])}" if r.get("candidates") else "")
                     + (f"; message: {(r.get('message') or '')[:200]}" if r["status"] != "done" else ""))
    if dropped:
        L += ["", "## Candidates not used", "", "| Group | Pair | Reason |", "| --- | --- | --- |"]
        L += [f"| {t['group']} | {t['disease']} + {t['target']} | {t['reason'].replace('|', '/')} |" for t in dropped]
    L += ["", "Reference: Minikel EV et al., Nature 2024, \"Refining the impact of genetic evidence on clinical "
          "success\". Pairs name a target, not a mechanism, so same-mechanism facts are mostly absent."]
    return "\n".join(L) + "\n"


def main() -> Path:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=15)
    p.add_argument("--seed", type=int, default=9)
    p.add_argument("--no-llm", action="store_true")
    a = p.parse_args()
    if a.no_llm:
        api.make_llm = lambda: None
    elif api.make_llm() is None:
        print("No LLM configured (backend/.env): stop labels and documents are skipped, memos use template text.")

    print("checking which pairs resolve (Open Targets search only) ...", flush=True)
    pairs, dropped = select(api.make_ot(), json.loads(TRUTH.read_text(encoding="utf-8")), a.n, a.seed)
    for t in dropped:
        print(f"   not used: {t['group']}: {t['disease']} + {t['target']} — {t['reason']}", flush=True)
    if len(pairs) < a.n:
        print(f"   only {len(pairs)} of {a.n} pairs meet the criteria", flush=True)
    started = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = OUT_ROOT / started
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pairs.txt").write_text("".join(f"{t['disease']} | {t['target']}   # {t['group']}; "
                                               f"{t['disease_id']} {t['resolved_name']} ({t['match']})\n"
                                               for t in pairs), encoding="utf-8")
    c = api.con()
    results, t0 = [], time.perf_counter()
    for i, t in enumerate(pairs, 1):
        print(f"[{i}/{len(pairs)}] {t['group']}: {t['disease']} + {t['target']} ...", flush=True)
        try:
            r = one(c, t)
        except Exception as exc:                          # one broken pair must not stop the sample
            r = {**t, "run_id": None, "status": "error", "message": f"{type(exc).__name__}: {exc}"}
        results.append(r)
        print(f"      {r.get('decision') or r['status']}" + (f" ({r['grounds']})" if r.get("grounds") else "")
              + f" — {judge(r)}; {r.get('seconds', 0)} s, {r.get('calls', 0)} LLM calls"
              + (f", errors {r['errors']}" if r.get("errors") else ""), flush=True)
    text = report(results, a.seed, started, time.perf_counter() - t0, dropped)
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    (out_dir / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n" + text + f"\nReport: {out_dir / 'report.md'}")
    return out_dir


if __name__ == "__main__":
    main()

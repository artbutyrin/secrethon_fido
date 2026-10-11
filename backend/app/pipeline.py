"""Stages 1-4: normalize -> collect -> claims -> scorer verdict. The API stores each stage (app/api.py)."""
from __future__ import annotations

from typing import Any

from backend.app.scorer import ENGINE, evaluate, facts_from_claims, load_config

from backend.app.batching import pmap
from backend.app.collect import collect
from backend.app.evidence import trace
from backend.app.facts import Claims, build_claims
from backend.app.llm import LLM
from backend.app.normalize import normalize
from backend.app.opentargets import OpenTargets
from backend.app.trials import label_trials, stopped_trials, to_label, trial_claims
from backend.app import translation as tl

CFG = load_config()
try:                                            # scorer 2.x: a round question requires data on the asset for Invest
    CFG_ROUND = load_config(asset_data_for_invest=True)
except TypeError:                               # scorer 1.x (UNOBIO_SCORER=v1) has no such switch
    CFG_ROUND = CFG


def score_claims(claims: list[dict], *, market_data: dict | None = None, market: dict | None = None,
                 round_terms: dict | None = None, license_terms: dict | None = None) -> dict[str, Any]:
    """Claims -> scorer verdict. Every scorecard item and fired rule gets the IDs of the claims behind it.

    market_data: what collect_market found (Orphanet, CMS); market: what a person entered (wins). With a patient count
    the economics run (rNPV, Monte Carlo, scenarios) and can lower the verdict when patients and price are sourced.
    round_terms ({pre_money_m, investment_m, cash_m, dilution_to_exit}) make it a question about this round: Invest
    then needs data on the asset itself, and the round price is tested against the cost of capital. Without them
    the question is the thesis (target + mechanism + indication)."""
    got = facts_from_claims(CFG, claims)
    question = "round" if round_terms else "thesis"
    cfg = CFG_ROUND if round_terms else CFG
    payload: dict[str, Any] = {"used": got["used"], "rejected": got["rejected"], "pending": got["pending"],
                               "conflicts": got["conflicts"], "question": question}
    if ENGINE == "unobio_scoring":
        from backend.app.market import market_for
        m, prov = market_for(got["facts"], market_data, market)
        result = evaluate(cfg, got["facts"], market=m, round_terms=round_terms, license_terms=license_terms)
        payload["market"] = {"input": m, "provenance": prov, "notes": list((market_data or {}).get("notes") or []),
                             "analogues": (market_data or {}).get("analogues") or {},
                             "orphacode": (market_data or {}).get("orphacode")}
    else:
        result = evaluate(cfg, got["facts"])
    payload["result"] = trace(cfg, result, got["used"])
    return payload


def analyze(ot: OpenTargets, disease: str | None = None, target: str | None = None, *, disease_id: str | None = None,
            target_id: str | None = None, phase: str | None = None, route: str | None = None,
            collected: dict | None = None, llm: LLM | None = None, sources=None) -> dict[str, Any]:
    """Stages 1-3: normalize, collect, claims (code + LLM labels). Stops after normalization unless both resolve.

    `sources` (backend.app.sources.Sources): openFDA, UniProt, PubMed, AACT for the translation chain. None skips
    them (the claims are then those of Open Targets alone)."""
    norm = normalize(ot, disease, target, disease_id, target_id)
    if norm["status"] != "resolved":
        return {"status": norm["status"], "normalized": norm}
    d, t = norm["disease"], norm["target"]
    if "broader" not in d:
        d["broader"] = ot.lineage(d["id"]) if hasattr(ot, "lineage") else []
    collected = collected or collect(ot, d["id"], t["id"])
    if sources is not None and "translation" not in collected:
        collected["translation"] = tl.collect_translation(sources, norm, collected)
    tr = collected.get("translation")

    from backend.app.facts import mark_class_members
    excluded = mark_class_members(collected["parts"].get("target_drugs"), t, d["id"])
    c = Claims()
    c.items = build_claims(norm, collected, phase=phase, route=route)
    broader_ids = {x["id"] for x in d.get("broader") or []}
    trials = tl.merge_aact_trials(stopped_trials(collected, d["id"], t["id"], t.get("action"), broader_ids), tr, d)
    # 2.6: stop reasons and trial outcomes are read by code first (Open Targets stop categories, rules on the PubMed
    # abstracts the run already has): free and the same on every run. The LLM, when there is one, adds what code cannot
    # read (translation links); UNOBIO_STOP_LABELS=llm brings back the LLM stop-reason labels.
    import os
    from backend.app import rules
    docs = tl.documents(tr)
    names = [x["key"] for x in (tr or {}).get("drugs") or []]
    use_rules = os.environ.get("UNOBIO_RULES", "1").strip().lower() not in ("0", "false", "no")
    labelled = rules.label_stops(trials) if use_rules else {"labels": {}, "errors": []}
    found = {"findings": [], "errors": []}
    if llm is not None:
        llm_stops = (not use_rules or
                     os.environ.get("UNOBIO_STOP_LABELS", "rules").strip().lower() == "llm")
        stages = [lambda: tl.extract_findings(llm, docs, d, t, names) if docs else {"findings": [], "errors": []}]
        if llm_stops:
            stages.append(lambda: label_trials(llm, to_label(trials)))
        got = pmap(lambda f: f(), stages, n=len(stages))
        found = got[0]
        if llm_stops:
            labelled = got[1]
        tl.class_claims(c, d, t, (tr or {}).get("drugs") or [], found["findings"])
    seen = {(f["doc_id"], f["drug"], f["link"]) for f in found["findings"]}
    if use_rules:
        found["findings"] = found["findings"] + [f for f in rules.outcome_findings(docs, d, names)
                                                 if (f["doc_id"], f["drug"], f["link"]) not in seen]
    extra = tl.aact_failures(tr, d)
    ph23 = tl.ph23_drugs_in_disease(collected, tr, d, (tr or {}).get("drugs") or [])
    for drug, hits in tl.literature_failures(found["findings"], ph23).items():
        extra.setdefault(drug, []).extend(hits)
    from backend.app.facts import approved_same_mechanism
    here, anywhere = approved_same_mechanism(collected["parts"].get("target_drugs"), d["id"], t["id"], t.get("action"))
    here = here | tl.positive_ph3_drugs(tr, d)        # 2.5: a met Phase 3 here is not a failed program either
    here = here | rules.positive_phase3_from_findings(found["findings"])   # 2.6: the same from a Phase 3 abstract
    failed = trial_claims(c, trials, labelled, d, t, extra, approved_here=here, approved_anywhere=anywhere)
    from backend.app.facts import unknown_outcome_claims
    unknown_outcome_claims(c, d, t, collected["parts"].get("target_drugs"), here, failed or set())
    from backend.app.trials import auto_confirm
    auto_confirm(c.items)
    labelled["errors"] = labelled["errors"] + found["errors"]
    chain = tl.chain_summary(tr, found["findings"])
    from backend.app.facts import unsure_drugs
    collected["mechanism"] = {"input_action": t.get("action"),
                              "unsure_drugs": unsure_drugs(collected["parts"].get("target_drugs"), t["id"], t.get("action")),
                              "list_complete": bool((collected["parts"].get("target_drugs") or {}).get("complete")),
                              "excluded_drugs": excluded}
    return {"status": "analyzed", "normalized": norm, "collected": collected, "claims": c.items,
            "trials": trials, "labels": labelled, "findings": found["findings"], "chain": chain,
            "sources_status": tl.sources_status(tr),
            "llm": {"used": llm is not None, "model": getattr(llm, "model", None),
                    "calls": list(getattr(llm, "calls", []))},
            "log": {"open_targets": list(ot.calls), "sources": sources.calls() if sources is not None else []}}


def run(ot: OpenTargets, disease: str | None = None, target: str | None = None, **kw) -> dict[str, Any]:
    """Stages 1-4 for the command line: analyze, then score."""
    out = analyze(ot, disease, target, **kw)
    if out["status"] == "analyzed":
        out["status"], out["score"] = "scored", score_claims(out["claims"])
    return out


def report_text(out: dict[str, Any]) -> str:
    """Plain-text summary for the command line."""
    norm = out["normalized"]
    d, t = norm["disease"], norm["target"]
    if out["status"] != "scored":
        lines = [f"Not resolved ({out['status']}). Rerun with --disease-id / --target-id."]
        for kind, r in (("disease", d), ("target", t)):
            if r["status"] != "resolved":
                lines.append(f"{kind}: {r['status']}. {r.get('message') or ''}")
                lines += [f"  {c['id']:<22} {c['name']}" for c in r.get("candidates") or []]
        return "\n".join(lines)

    res, sc = out["score"]["result"], out["score"]
    v = res["verdict"]
    failed = [n for n, p in out["collected"]["parts"].items() if not p["ok"]]
    lines = [f"{d['name']} ({d['id']})  +  {t['symbol']} ({t['id']}), Open Targets {norm['ot_release']}",
             f"Failed queries: {', '.join(failed)}" if failed else "All queries OK.", "", "CLAIMS"]
    for c in out["claims"]:
        lines.append(f"  {c['id']:<7} {c['fact']:<26} = {c['value']!s:<15} [{c['origin']}, {len(c['sources'])} src]")
        lines.append(f"          {c['statement']}")
    lines += trials_text(out)
    lines += ["", f"VERDICT: {v['decision']}  ({v['grounds_text']})"]
    if v["reason"] != v["grounds_text"]:
        lines.append(f"  {v['reason']}")
    cov = res["score"]["coverage"]
    lines += [f"  pluses {res['score']['pos']}, minuses {res['score']['neg']}; "
              f"items with data {cov['items_known']} of {cov['items_total']}", "", "SCORECARD"]
    names = {"G": "green", "Y": "yellow", "R": "red", "U": "unknown"}
    lines += [f"  {names.get(i['color'], i['color']):<8} {i['name']}" for i in res["scorecard"]]
    lines += ["", "RULES FIRED"] + ([f"  {r['tier']:<8} {r['name']}" for r in res["rules"]] or ["  none"])
    if v["conditions"]:
        lines += ["", "CONDITIONS FOR INVEST"] + [f"  {x['label']}: {x['from'] if x['from'] is not None else 'unknown'}"
                                                  f" -> {x['to']}" for x in v["conditions"]]
    for title, key in (("PENDING (need a second source or a human)", "pending"), ("REJECTED", "rejected"),
                       ("CONFLICTS", "conflicts")):
        if sc[key]:
            lines += ["", title] + [f"  {x}" for x in sc[key]]
    flips = res["what_would_change"][:5]
    if flips:
        lines += ["", "WHAT WOULD CHANGE THE VERDICT (first 5)"]
        shown = lambda x: "unknown" if x is None else x  # noqa: E731
        lines += [f"  {f['label']}: {shown(f['from'])} -> {shown(f['to'])}  =>  {f['verdict_to']}" for f in flips]
    lines += ["", "DUE-DILIGENCE QUESTIONS (first 5)"] + [f"  - {q['question']}" for q in res["dd_questions"][:5]]
    return "\n".join(lines)


def trials_text(out: dict[str, Any]) -> list[str]:
    """Stopped trials of same-mechanism drugs with the LLM labels, and how many others were labelled."""
    trials, lab = out.get("trials") or [], out.get("labels") or {"labels": {}, "errors": []}
    labels = lab["labels"]
    same = [t for t in trials if t["same_mechanism_drugs"]]
    lines = ["", f"STOPPED TRIALS OF SAME-MECHANISM DRUGS ({len(same)})"]
    if not out.get("llm", {}).get("used"):
        lines.append("  LLM not used (no key or --no-llm): trial reasons are not counted.")
    for t in same:
        lines.append(f"  {t['nct']} {t['stage'] or '?'} {', '.join(d.title() for d in t['same_mechanism_drugs'])}; "
                     f"{t['sponsor']}; Open Targets category: {', '.join(t['ot_categories']) or 'none'}")
        lines.append(f"      reason: {t['why_stopped'][:160]}")
        for x in labels.get(t["nct"], []):
            mark = "quote found" if x["verified"] else "QUOTE NOT FOUND, not used"
            lines.append(f"      LLM: {x['label']:<10} \"{x['quote']}\"  ({mark})")
    others = [n for n in labels if n not in {t["nct"] for t in same}]
    if others:
        counts: dict[str, int] = {}
        for n in others:
            for x in labels[n]:
                if x["verified"]:
                    counts[x["label"]] = counts.get(x["label"], 0) + 1
        lines.append(f"  Other Phase 2/3 trials in the disease labelled: {len(others)}; labels: {counts}")
    lines += [f"  LLM error: {e}" for e in lab["errors"]]
    return lines

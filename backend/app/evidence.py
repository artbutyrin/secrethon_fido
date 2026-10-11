"""Human evidence and verdict versions.

- `trace`: adds `claim_ids` to every scorecard item and fired rule, so the frontend can go
  verdict -> item or rule -> claims -> sources in one click.
- `human_claim`: turns a person's input into a claim (origin "user"). It outranks Open Targets and LLM claims for
  the same fact (the scorer's rule: user > structured > llm).
- `diff`: what changed between two verdict versions ("before -> after").
"""
from __future__ import annotations

from typing import Any

from backend.app.scorer import FactError, check_facts
from backend.app.scorer import facts_in


class EvidenceError(ValueError):
    """Input the scorer cannot accept: unknown fact, wrong value, or a contradiction with other facts."""


# --- trace: item / rule -> claims ------------------------------------------------------------------------------------
def item_reads(cfg, item_id: str) -> set[str]:
    """Facts a scorecard item looks at (the same set the scorer uses to decide its colour)."""
    item = cfg.items[item_id]
    return (set(item.get("evidence_facts") or [])
            | facts_in(item.get("red", {})) | facts_in(item.get("green", {})) | facts_in(item.get("strong_green", {})))


def _claims_for(facts: set[str], used: dict, derived_from: dict) -> list[str]:
    out: list[str] = []
    for f in sorted(facts):
        for source in ([f] if f in used else derived_from.get(f, [])):
            for cid in used.get(source, []):
                if cid not in out:
                    out.append(cid)
    return out


def trace(cfg, result: dict, used: dict) -> dict:
    """Adds `claim_ids` (and `reads` for items) in place; returns the result."""
    derived_from = result["facts"].get("derived_from") or {}
    for item in result["scorecard"]:
        reads = item_reads(cfg, item["id"])
        item["reads"] = sorted(reads)
        item["claim_ids"] = _claims_for(reads, used, derived_from)
    for rule in result["rules"]:
        rule["claim_ids"] = _claims_for(set(rule.get("facts") or []), used, derived_from)
    return result


# --- human input -> claim --------------------------------------------------------------------------------------------
def human_claim(cfg, fact: str, value: Any, *, source_url: str | None, source_text: str | None,
                statement: str | None, author: str | None) -> dict:
    if fact not in cfg.facts:
        raise EvidenceError(f"unknown fact {fact!r}; see GET /facts")
    try:
        check_facts(cfg, {fact: value})
    except FactError as exc:
        raise EvidenceError(str(exc)) from exc
    if not (source_url or "").strip() and not (source_text or "").strip():
        raise EvidenceError("a source is required: source_url or source_text (document, page, data room file)")
    label = cfg.facts[fact]["label"]
    return {"fact": fact, "value": value, "origin": "user", "evidence_type": "source",
            "statement": statement or f"Added by {author or 'a reviewer'}: {label} = {value}.",
            "rule": "Human evidence. Outranks Open Targets and LLM claims for the same fact.",
            "sources": [{"kind": "human", "url": (source_url or "").strip() or None,
                         "text": (source_text or "").strip() or None, "author": author}]}


# --- before -> after -----------------------------------------------------------------------------------------------
def snapshot(payload: dict) -> dict:
    res = payload["result"]
    return {"decision": res["verdict"]["decision"], "grounds": res["verdict"]["grounds"],
            "pluses": res["score"]["pos"], "minuses": res["score"]["neg"],
            "colors": {i["id"]: i["color"] for i in res["scorecard"]},
            "names": {i["id"]: i["name"] for i in res["scorecard"]} | {r["id"]: r["name"] for r in res["rules"]},
            "rules": {r["id"]: r["tier"] for r in res["rules"]},
            "pending": sorted(p["fact"] for p in payload["pending"]),
            "caps": {c["id"]: c["reason"] for c in res["verdict"].get("caps") or []},
            "question": payload.get("question", "thesis"),
            "rnpv_p50": ((res.get("economics") or {}).get("monte_carlo") or {}).get("p50_m")}


def diff(before: dict, after: dict) -> dict:
    a, b = snapshot(before), snapshot(after)
    names = a["names"] | b["names"]
    return {
        "decision": {"from": a["decision"], "to": b["decision"], "changed": a["decision"] != b["decision"]},
        "grounds": {"from": a["grounds"], "to": b["grounds"]},
        "pluses": {"from": a["pluses"], "to": b["pluses"]},
        "minuses": {"from": a["minuses"], "to": b["minuses"]},
        "scorecard": [{"id": k, "name": names[k], "from": a["colors"].get(k), "to": b["colors"].get(k)}
                      for k in b["colors"] if a["colors"].get(k) != b["colors"][k]],
        "rules_added": [{"id": k, "name": names[k], "tier": b["rules"][k]} for k in b["rules"] if k not in a["rules"]],
        "rules_removed": [{"id": k, "name": names[k], "tier": a["rules"][k]} for k in a["rules"] if k not in b["rules"]],
        "pending_resolved": [f for f in a["pending"] if f not in b["pending"]],
        "pending_new": [f for f in b["pending"] if f not in a["pending"]],
        "caps_added": [{"id": k, "reason": b["caps"][k]} for k in b["caps"] if k not in a["caps"]],
        "caps_removed": [{"id": k, "reason": a["caps"][k]} for k in a["caps"] if k not in b["caps"]],
        "question": {"from": a["question"], "to": b["question"]},
        "rnpv_p50_m": {"from": a["rnpv_p50"], "to": b["rnpv_p50"]},
    }

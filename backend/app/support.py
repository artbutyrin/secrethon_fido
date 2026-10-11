"""Second LLM check: does a verified quote, read on its own, actually state what its label says?

The quote check (code) proves the words exist in the document. It does not prove they mean the label: "The primary
endpoint was achieved" is a real quote but not an efficacy failure. This check asks a separate, narrow question per
item and returns {item id: True | False}. Items the model does not answer are left out: the caller keeps them as
they were and marks them unchecked, so an unavailable check never invents or removes evidence silently.
"""
from __future__ import annotations

import json
from typing import Any

from backend.app.batching import fixed_chars, pack, pmap
from backend.app.llm import LLM, LLMError, input_too_big

BATCH = 40                 # at most; batches are packed to the input budget first (batching.py)

SYSTEM = """You check evidence. Each item has a claim and a text (a quote with the sentences around it, or a short
stated reason). Answer supports=true only if the text states the claim. Do not reject only because the text does not
repeat the drug name, the species or the disease: reject when it names a different one (cells or animals where the
claim says people, another drug, another disease). Answer false if the text says the opposite, says something else, only mentions the topic,
or only says that something was planned or measured without giving the result. A general description of how a drug
works or what it is designed to do does not support a claim that a study showed something. Do not use outside
knowledge.
Return every item you were given, with its id."""

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "supports": {"type": "boolean"}},
        "required": ["id", "supports"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}


def too_big(exc: Exception) -> bool:
    """The gateway refused the request for its size (HTTP 400 'exceeds the conservative input limit' and similar)."""
    return input_too_big(str(exc))


def check_support(llm: LLM, items: list[dict[str, str]], task: str = "check_support") -> dict[str, Any]:
    """items: [{"id", "claim", "quote"}] -> {"verdicts": {id: bool}, "errors": [...]}.
    Batches are packed to the gateway's input budget (batching.py) and run in parallel; a batch the gateway still
    refuses as too large is split in half and asked again, down to one item.
    An item with no verdict is NOT supported: callers must treat a missing verdict as unchecked (fail closed)."""

    def ask(batch: list[dict[str, str]], label: str) -> tuple[dict[str, bool], list[str]]:
        user = json.dumps([{"id": x["id"], "claim": x["claim"], "quote": x["quote"]} for x in batch], ensure_ascii=False)
        try:
            answer = llm.complete_json(task, SYSTEM, user, SCHEMA)
        except LLMError as exc:
            if too_big(exc) and len(batch) > 1:
                half = len(batch) // 2
                (v1, e1), (v2, e2) = ask(batch[:half], label + "a"), ask(batch[half:], label + "b")
                return {**v1, **v2}, e1 + e2
            return {}, [f"support check batch {label}: {exc}"]
        asked = {x["id"] for x in batch}
        got = {row["id"]: row["supports"] for row in (answer or {}).get("items") or []
               if isinstance(row, dict) and row.get("id") in asked and isinstance(row.get("supports"), bool)}
        return got, []

    size = lambda x: len(json.dumps(x, ensure_ascii=False))  # noqa: E731
    batches = pack(items, size, fixed_chars(SYSTEM, SCHEMA), BATCH)
    verdicts: dict[str, bool] = {}
    errors: list[str] = []
    for got, errs in pmap(lambda nb: ask(nb[1], str(nb[0] + 1)), list(enumerate(batches))):
        verdicts.update(got)
        errors += errs
    return {"verdicts": verdicts, "errors": errors}

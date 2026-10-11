"""Checks the LLM connection with one tiny request and prints what works.

Run from the repo root:  python3 -m backend.tests.check_llm
Reads backend/.env (TEAM_API_KEY + UNOBIO_LLM_BASE_URL for the gateway). Nothing is cached.
"""
import tempfile
from pathlib import Path

import httpx

from backend.app.llm import LLMError, OpenAILLM

SCHEMA = {"type": "object", "properties": {"label": {"type": "string", "enum": ["efficacy", "safety", "other"]},
                                           "quote": {"type": "string"}},
          "required": ["label", "quote"], "additionalProperties": False}

def available_models(llm) -> list[str]:
    """GET <base>/models (OpenAI-compatible). Empty if the server does not offer the list."""
    url = llm.url.rsplit("/chat/completions", 1)[0] + "/models"
    try:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {llm.api_key}"}, timeout=20)
        return sorted(m.get("id") for m in resp.json().get("data") or [] if m.get("id"))
    except Exception:  # noqa: BLE001  (a diagnostic; any failure just means "could not list")
        return []


if __name__ == "__main__":
    llm = OpenAILLM(cache_dir=Path(tempfile.mkdtemp()))
    host = llm.url.split("/")[2] if llm.url else None
    print(f"provider {llm.provider}, model {llm.model!r}, host {host}, key {'set' if llm.api_key else 'NOT SET'}")
    if llm.missing():
        raise SystemExit(f"Not configured: {llm.missing()}")
    try:
        answer = llm.complete_json("check", "Classify why the trial stopped. Quote the words you used.",
                                   "Trial stopped: the independent committee found futility at the interim analysis.",
                                   SCHEMA)
    except LLMError as exc:
        print(f"FAILED: {exc}")
        if "model" in str(exc).lower():
            models = available_models(llm)
            print(f"Model sent: {llm.model!r}. The server offers: {', '.join(models) if models else 'could not list'}")
            print("Set UNOBIO_LLM_MODEL in backend/.env to one of them (no comment on the same line).")
        raise SystemExit(1)
    call = llm.calls[-1]
    print(f"OK: {answer}")
    print(f"JSON mode that worked: {llm.json_mode} (best is json_schema); reasoning_effort sent: "
          f"{llm.reasoning or 'no'}; token field: {llm.max_tokens_field}")
    print(f"tokens in/out: {call.get('input_tokens')}/{call.get('output_tokens')}, {call.get('latency_ms')} ms")

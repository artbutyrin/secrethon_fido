"""The LLM client against a gateway that behaves like the hackathon one on 9 October, with requests in parallel:
- an output token limit above 8192 is "outside the supported range" (HTTP 400);
- more than 2 requests at once is "Too many active requests" (HTTP 429 concurrency_limit);
- a large input is "Input exceeds the conservative input limit. Shorten the conversation or tool schemas" (HTTP 400).
Before the fix: parallel token-limit refusals lowered the limit 16000 -> 8192 -> 4096 -> 2048 and then failed calls;
429s failed calls after 4 attempts; and the size refusal, which says "schemas", switched the client to
schema-in-the-prompt mode for the rest of the run."""
import json
import threading
import time

import pytest

from backend.app import batching, llm as llm_mod
from backend.app.llm import LLMError, OpenAILLM

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


class Resp:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class Gateway:
    def __init__(self, max_out=8192, max_active=2, max_input_chars=4000):
        self.max_out, self.max_active, self.max_input_chars = max_out, max_active, max_input_chars
        self.active = self.peak = 0
        self.lock = threading.Lock()
        self.seen = {"400_tokens": 0, "429": 0, "400_input": 0, "ok": 0}

    def post(self, url, json=None, headers=None):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            busy = self.active > self.max_active
        try:
            time.sleep(0.02)
            if busy:
                self.seen["429"] += 1
                return Resp(429, {"error": {"code": "concurrency_limit", "message": "Too many active requests."}})
            if json.get("max_completion_tokens", json.get("max_tokens", 0)) > self.max_out:
                self.seen["400_tokens"] += 1
                return Resp(400, {"error": {"code": "invalid_request",
                                            "message": "Output token limit is outside the supported range."}})
            if sum(len(m["content"]) for m in json["messages"]) > self.max_input_chars:
                self.seen["400_input"] += 1
                return Resp(400, {"error": {"code": "invalid_request", "message": "Input exceeds the conservative "
                                            "input limit. Shorten the conversation or tool schemas."}})
            self.seen["ok"] += 1
            return Resp(200, {"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                              "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        finally:
            with self.lock:
                self.active -= 1


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("UNOBIO_LLM_WORKERS", "4")
    monkeypatch.setenv("UNOBIO_LLM_MAX_TOKENS", "16000")
    monkeypatch.setattr(batching, "_gate", None)                 # a fresh in-flight cap for this test
    real_sleep = time.sleep
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: real_sleep(min(s, 0.01)))   # keep the backoff, make it fast
    gw = Gateway()
    return OpenAILLM(api_key="k", provider="openai", model="m", cache_dir=tmp_path, http=gw), gw


def test_parallel_refusals_lower_the_token_limit_one_step_and_429s_are_waited_out(client):
    llm, gw = client
    out = batching.pmap(lambda i: llm.complete_json("t", "s", f"question {i}", SCHEMA), range(16), n=8)
    assert out == [{"ok": True}] * 16                             # every call answered
    assert llm.max_tokens == 8192                                 # not 4096 or 2048: one step per rejection
    assert gw.seen["429"] > 0 and batching.gate().limit <= 2      # the cap followed the gateway down
    assert not [c for c in llm.calls if c.get("error")]


def test_a_size_refusal_does_not_change_the_json_mode(client):
    llm, gw = client
    with pytest.raises(LLMError, match="input limit"):
        llm.complete_json("t", "s", "x" * 5000, SCHEMA)
    assert llm.json_mode == "json_schema"                         # was "json_object", then "prompt", before the fix
    assert llm.complete_json("t", "s", "small", SCHEMA) == {"ok": True}

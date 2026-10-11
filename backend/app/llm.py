"""Minimal client for JSON answers (OpenAI-compatible Chat Completions).

Works with the hackathon gateway, OpenAI and xAI (Grok). Every answer is cached as a JSON file
(key = model + task + prompt + schema), so a rerun gives the same answer and costs nothing.

Settings come from the environment or from backend/.env:
  TEAM_API_KEY + UNOBIO_LLM_BASE_URL   the hackathon gateway (chosen automatically when TEAM_API_KEY is set)
  OPENAI_API_KEY                       OpenAI;  XAI_API_KEY: xAI
  UNOBIO_LLM_PROVIDER                  force one: gateway | openai | xai
  UNOBIO_LLM_MODEL                     default gpt-6-luna (gateway), gpt-5-mini (openai), grok-4.7 (xai)
  UNOBIO_LLM_REASONING                 reasoning effort, e.g. "low"; empty = not sent (default except openai)
  UNOBIO_LLM_MAX_TOKENS                max_completion_tokens, default 16000
  UNOBIO_LLM_TEMPERATURE               2.4.1: sampling temperature, e.g. 0; not sent unless set (the team gateway
                                       fails with HTTP 502 when its model refuses it). Reasoning models that reject it get it dropped automatically, like
                                       reasoning_effort. UNOBIO_LLM_SEED (e.g. 7): the same, not sent unless set.

Not every gateway or model accepts every parameter. If the server rejects one (HTTP 400 naming it), the client
retries without it, in this order: reasoning_effort; strict json_schema -> json_object with the schema in the
prompt -> plain text with the schema in the prompt; max_completion_tokens -> max_tokens; an output token limit
"outside the supported range" -> 8192 -> 4096 -> 2048. The working shape is
remembered for the next calls. The answer is always parsed as JSON; the callers validate its content.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Protocol

import httpx

BACKEND = Path(__file__).resolve().parents[1]
CACHE_DIR = BACKEND / "data" / "llm_cache"
#            provider: (chat completions URL or None = from UNOBIO_LLM_BASE_URL, key variable, model, reasoning)
PROVIDERS = {"gateway": (None, "TEAM_API_KEY", "gpt-6-luna", ""),
             "openai": ("https://api.openai.com/v1/chat/completions", "OPENAI_API_KEY", "gpt-5-mini", "low"),
             "xai": ("https://api.x.ai/v1/chat/completions", "XAI_API_KEY", "grok-4.7", "")}
JSON_MODES = ["json_schema", "json_object", "prompt"]
TOKEN_STEPS = [8192, 4096, 2048]                  # tried in order when a server rejects the output token limit
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.S)


class LLMError(RuntimeError):
    pass


_TOO_BIG = ("input limit", "exceeds", "too long", "context length", "maximum context", "too large")


def input_too_big(text: str) -> bool:
    """The gateway refused the request for the size of its INPUT ("Input exceeds the conservative input limit.
    Shorten the conversation or tool schemas"). Not a parameter problem: the caller splits the batch instead. Before
    9 October this message also matched the JSON-schema fallback below (it says "schemas"), so every size refusal
    switched the rest of the run to schema-in-the-prompt mode: larger inputs and no strict JSON."""
    t = (text or "").lower()
    return any(w in t for w in _TOO_BIG) and "output" not in t


CONCURRENCY_RETRIES = 8                         # "Too many active requests": wait and retry, the gate shrinks meanwhile


class LLM(Protocol):
    calls: list[dict[str, Any]]

    def complete_json(self, task: str, system: str, user: str, schema: dict) -> dict: ...


_INLINE_COMMENT = re.compile(r"\s+#.*$")


def env_value(raw: str) -> str:
    """The value of a KEY=VALUE line: quotes removed; an unquoted value ends at " #" (an inline comment), so
    "gpt-6-luna     # or gpt-5-mini" is "gpt-6-luna" and "      # the gateway URL" is empty."""
    v = raw.strip()
    if v[:1] in ("'", '"'):
        end = v.find(v[0], 1)
        return v[1:end] if end > 0 else v[1:]
    return "" if v.startswith("#") else _INLINE_COMMENT.sub("", v).strip()


def load_env(path: Path = BACKEND / ".env") -> None:
    """KEY=VALUE lines from backend/.env; the real environment wins. Empty values are skipped."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            value = env_value(value)
            if value:
                os.environ.setdefault(key.strip(), value)


def pick_provider() -> str:
    if os.environ.get("UNOBIO_LLM_PROVIDER"):
        return os.environ["UNOBIO_LLM_PROVIDER"]
    for name in ("gateway", "openai", "xai"):
        if os.environ.get(PROVIDERS[name][1]):
            return name
    return "openai"


def parse_json(text: str) -> dict:
    text = _FENCE.sub("", text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")           # a sentence around the JSON
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


class OpenAILLM:
    """OpenAI-compatible client (gateway, OpenAI or xAI)."""

    def __init__(self, api_key: str | None = None, model: str | None = None, reasoning: str | None = None,
                 provider: str | None = None, base_url: str | None = None, cache_dir: Path = CACHE_DIR,
                 http: httpx.Client | None = None, retries: int = 3):
        load_env()
        provider = provider or pick_provider()
        if provider not in PROVIDERS:
            raise LLMError(f"unknown provider {provider!r}; use one of {sorted(PROVIDERS)}")
        self.provider = provider
        url, self.key_var, default_model, default_reasoning = PROVIDERS[provider]
        base = base_url or os.environ.get("UNOBIO_LLM_BASE_URL")
        self.url = (base.rstrip("/") + "/chat/completions") if base else url
        self.api_key = os.environ.get(self.key_var) if api_key is None else api_key   # "" = no key
        self.model = model or os.environ.get("UNOBIO_LLM_MODEL") or default_model
        self.reasoning = reasoning if reasoning is not None else os.environ.get("UNOBIO_LLM_REASONING",
                                                                                default_reasoning)
        self.max_tokens = int(os.environ.get("UNOBIO_LLM_MAX_TOKENS") or 16000)
        # 2.4: reproducibility (the same request gave "class: shown" in one run and "unknown" in another)
        # 2.4.1: opt-in. The team gateway answers HTTP 502 "upstream_error" (not a 400 naming the parameter) when the
        # model behind it refuses temperature/seed, so they cannot be dropped automatically there; a failed request is
        # also charged. Reproducibility comes from the answer cache (same prompt -> the cached answer).
        t = os.environ.get("UNOBIO_LLM_TEMPERATURE", "").strip().lower()
        self.temperature: float | None = float(t) if t and t not in ("off", "none") else None
        s = os.environ.get("UNOBIO_LLM_SEED", "").strip().lower()
        self.seed: int | None = int(s) if s and s not in ("off", "none") else None
        self.json_mode = "json_schema"          # downgraded once if the server rejects it
        self.reasoning_rejected = False
        self.tokens_rejected: set[int] = set()
        self.max_tokens_field = "max_completion_tokens"
        self.cache_dir = Path(cache_dir)
        self.http = http or httpx.Client(timeout=300)   # one client per LLM object: connections are reused
        self.retries = retries
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()           # request shape (json mode, token limit, ...) is shared by threads

    @property
    def ready(self) -> bool:
        return bool(self.api_key and self.url)

    def missing(self) -> str | None:
        """What is missing to make live calls, in words; None if ready."""
        if not self.api_key:
            return f"{self.key_var} is not set (environment or backend/.env)"
        if not self.url:
            return "UNOBIO_LLM_BASE_URL is not set (the gateway base URL, ending in /v1)"
        return None

    # --- request ----------------------------------------------------------------------------------------------------
    def _body(self, task: str, system: str, user: str, schema: dict) -> dict:
        if self.json_mode != "json_schema":
            system = (system + "\n\nReply with one JSON object only, no other text. It must follow this JSON "
                      "schema:\n" + json.dumps(schema))
        body: dict[str, Any] = {"model": self.model,
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                                self.max_tokens_field: self.max_tokens}
        if self.json_mode == "json_schema":
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": task, "strict": True, "schema": schema}}
        elif self.json_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        if self.reasoning:
            body["reasoning_effort"] = self.reasoning
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.seed is not None:
            body["seed"] = self.seed
        return body

    def _state(self) -> tuple:
        return self.reasoning, self.json_mode, self.max_tokens_field, self.max_tokens, self.temperature, self.seed

    def _adapt(self, error: str) -> bool:
        """Drops the parameter a 400 error names. Returns False if there is nothing left to try. Call with the lock."""
        e = error.lower()
        if input_too_big(e):                               # size, not shape: the caller splits the batch
            return False
        if self.reasoning and "reasoning" in e:
            self.reasoning, self.reasoning_rejected = "", True
            return True
        if self.temperature is not None and "temperature" in e:     # 2.4: reasoning models accept only the default
            self.temperature = None
            return True
        if self.seed is not None and re.search(r"\bseed\b", e):
            self.seed = None
            return True
        if "max_completion_tokens" in e and self.max_tokens_field == "max_completion_tokens":
            self.max_tokens_field = "max_tokens"
            return True
        if re.search(r"token", e) and re.search(r"range|limit|too (?:large|high|many)|maximum|exceed", e):
            self.tokens_rejected.add(self.max_tokens)
            lower = next((n for n in TOKEN_STEPS if n < self.max_tokens), None)
            if lower:                                      # "Output token limit is outside the supported range"
                self.max_tokens = lower
                return True
        if ("response_format" in e or "json_schema" in e or "json_object" in e or "schema" in e) \
                and self.json_mode != JSON_MODES[-1]:
            self.json_mode = JSON_MODES[JSON_MODES.index(self.json_mode) + 1]
            return True
        return False

    def _request(self, task: str, system: str, user: str, schema: dict) -> tuple[dict, tuple]:
        """The answer and the request shape it was sent with. Requests run in parallel threads: a rejection adapts
        the shared shape only if no other thread has adapted it since this request was built (compare-and-set), so
        four simultaneous "token limit outside the supported range" errors lower the limit one step, not four."""
        for _ in range(10):                                 # at most a few downgrades per parameter
            with self._lock:
                state, body = self._state(), self._body(task, system, user, schema)
            try:
                return self._post(body), state
            except _BadRequest as exc:
                if input_too_big(exc.text):
                    raise LLMError(f"HTTP 400: {exc.text[:400]}") from exc
                with self._lock:
                    if self._state() != state:              # already adapted by another request: retry with it
                        continue
                    if not self._adapt(exc.text):
                        raise LLMError(f"HTTP 400: {exc.text[:400]}") from exc
        raise LLMError("the server rejected every request shape")

    def _more_room(self) -> bool:
        """After an answer cut off at the token limit (reasoning models spend the budget on thinking): first ask for
        less reasoning, then a higher limit the server has not rejected. False when nothing is left to try.
        Call with the lock."""
        if not self.reasoning and not self.reasoning_rejected:
            self.reasoning = "low"
            return True
        higher = [n for n in sorted(TOKEN_STEPS + [16000]) if n > self.max_tokens and n not in self.tokens_rejected]
        if higher:
            self.max_tokens = higher[0]
            return True
        return False

    def complete_json(self, task: str, system: str, user: str, schema: dict) -> dict:
        key = hashlib.sha256(json.dumps([self.model, task, system, user, schema], sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / f"{task}_{key[:16]}.json"
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.calls.append({"task": task, "model": self.model, "cache": True, **saved.get("usage", {})})
            return saved["answer"]
        if self.missing():
            raise LLMError(self.missing())

        started = time.perf_counter()
        try:
            return self._complete_live(task, system, user, schema, path, started)
        except LLMError as exc:                             # failed calls are logged too (GET /runs/{id}/log)
            self.calls.append({"task": task, "model": self.model, "cache": False, "error": str(exc)[:300],
                               "latency_ms": round((time.perf_counter() - started) * 1000)})
            raise

    def _complete_live(self, task: str, system: str, user: str, schema: dict, path: Path, started: float) -> dict:
        for _ in range(3):                                  # a cut-off answer is retried with more room
            data, state = self._request(task, system, user, schema)
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            if message.get("refusal"):
                raise LLMError(f"model refused: {message['refusal']}")
            try:
                answer = parse_json(message.get("content") or "")
                break
            except ValueError as exc:
                if choice.get("finish_reason") == "length":
                    with self._lock:
                        more = self._state() != state or self._more_room()   # another thread may have made room
                    if more:
                        continue
                raise LLMError(f"answer is not JSON (finish_reason={choice.get('finish_reason')}, "
                               f"max tokens {self.max_tokens}, reasoning {self.reasoning or 'not sent'})") from exc
        if not isinstance(answer, dict):
            raise LLMError("answer is JSON but not an object")
        usage = {"input_tokens": (data.get("usage") or {}).get("prompt_tokens"),
                 "output_tokens": (data.get("usage") or {}).get("completion_tokens"),
                 "latency_ms": round((time.perf_counter() - started) * 1000), "json_mode": self.json_mode}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"task": task, "model": self.model, "usage": usage, "system": system, "user": user,
                                    "answer": answer}, indent=1, ensure_ascii=False), encoding="utf-8")
        self.calls.append({"task": task, "model": self.model, "cache": False, **usage})
        return answer

    def _post(self, body: dict) -> dict:
        """One request with retries. At most UNOBIO_LLM_WORKERS requests are in flight per process (batching.gate);
        the slot is released while waiting to retry. The gateway's "Too many active requests" (HTTP 429
        concurrency_limit) lowers that number for the rest of the process and is retried longer, with jitter."""
        from backend.app.batching import gate
        g = gate()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        attempt = 0
        while True:
            with g as in_flight:
                try:
                    resp, err = self.http.post(self.url, json=body, headers=headers), None
                except httpx.TransportError as exc:
                    resp, err = None, exc
            if resp is None:
                if attempt >= self.retries:
                    raise LLMError(f"network error: {err!r}") from err
            elif resp.status_code == 429 and "concurren" in resp.text.lower():
                g.shrink(in_flight)
                if attempt >= CONCURRENCY_RETRIES:
                    raise LLMError(f"HTTP 429 after {attempt + 1} attempts: {resp.text[:200]}")
            elif resp.status_code == 429 or resp.status_code >= 500:
                if attempt >= self.retries:
                    raise LLMError(f"HTTP {resp.status_code} after {attempt + 1} attempts: {resp.text[:200]}")
            elif resp.status_code == 400:
                raise _BadRequest(resp.text)
            elif resp.status_code >= 400:
                raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            else:
                return resp.json()
            time.sleep(min(2 ** attempt, 20) * (0.5 + random.random()))
            attempt += 1


class _BadRequest(Exception):
    def __init__(self, text: str):
        super().__init__(text)
        self.text = text

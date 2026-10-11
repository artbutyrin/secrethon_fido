"""LLM batches sized to the gateway, and run in parallel.

Why: the hackathon gateway refuses a request above roughly 4k input tokens ("Input exceeds the conservative input
limit"); the largest accepted one in the 9 October runs had 4,117. Fixed batch sizes (40 support items, 6 documents
of 9,000 characters) were refused first and only then split in half, one round trip each. Batches are now packed to
a token budget up front, and independent batches of one stage run at the same time.

  UNOBIO_LLM_INPUT_BUDGET   estimated input tokens per request (system + schema + items), default 3500
  UNOBIO_LLM_WORKERS        LLM requests in flight at once, default 4; 1 = one after the other (old behaviour)

The token estimate is characters / 3.5. In the cached gateway answers one token was 3.3 to 4.5 characters, so at
the densest text a 3,500 budget means about 3,700 real tokens, still under the largest request the gateway accepted.
An item larger than the budget on its own still goes, alone; the split-on-refusal fallback (support.too_big) stays
for the rare case the estimate is wrong.
"""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")
CHARS_PER_TOKEN = 3.5


def input_budget() -> int:
    return int(os.environ.get("UNOBIO_LLM_INPUT_BUDGET") or 3500)


def workers() -> int:
    return max(1, int(os.environ.get("UNOBIO_LLM_WORKERS") or 4))


def tokens(chars: int) -> int:
    return int(chars / CHARS_PER_TOKEN) + 1


def fixed_chars(system: str, schema: dict) -> int:
    """Characters every request of a task carries: the system prompt and the JSON schema."""
    return len(system) + len(json.dumps(schema)) + 200          # + the wrapper fields of the user message


def pack(items: list[T], size: Callable[[T], int], fixed: int, max_items: int,
         budget: int | None = None) -> list[list[T]]:
    """Consecutive items -> batches whose estimated input stays under the budget, at most max_items each.
    `size(item)`: characters the item adds to the user message. Order is kept."""
    budget = budget or input_budget()
    batches: list[list[T]] = []
    cur: list[T] = []
    used = fixed
    for it in items:
        n = size(it) + 2
        if cur and (tokens(used + n) > budget or len(cur) >= max_items):
            batches.append(cur)
            cur, used = [], fixed
        cur.append(it)
        used += n
    if cur:
        batches.append(cur)
    return batches


def pmap(fn: Callable[[T], R], args: Iterable[T], n: int | None = None) -> list[R]:
    """fn over args with up to n at a time (default UNOBIO_LLM_WORKERS); results in the order of args.
    An exception in fn is raised here, as in a plain loop (callers catch LLM errors inside fn)."""
    args = list(args)
    n = min(n or workers(), len(args))
    if n <= 1:
        return [fn(a) for a in args]
    with ThreadPoolExecutor(max_workers=n, thread_name_prefix="llm") as pool:
        return list(pool.map(fn, args))


class Gate:
    """Caps the HTTP requests in flight across every pool in the process (stages run side by side). `shrink` lowers
    the cap when the gateway answers "Too many active requests": the key's real limit may be lower than ours, or
    shared with teammates. The cap never grows back within a process."""

    def __init__(self, limit: int):
        self.limit, self.active = limit, 0
        self._cv = threading.Condition()

    def __enter__(self) -> int:
        with self._cv:
            while self.active >= self.limit:
                self._cv.wait()
            self.active += 1
            return self.active                     # requests in flight including this one

    def __exit__(self, *exc) -> None:
        with self._cv:
            self.active -= 1
            self._cv.notify_all()

    def shrink(self, in_flight: int) -> int:
        """The gateway refused at `in_flight` requests: allow one fewer (at least 1). Simultaneous refusals at the
        same level lower the cap once, not once each."""
        with self._cv:
            self.limit = max(1, min(self.limit, in_flight - 1))
            return self.limit


_gate: Gate | None = None
_gate_lock = threading.Lock()


def gate() -> Gate:
    global _gate
    with _gate_lock:
        if _gate is None:
            _gate = Gate(workers())
        return _gate


__all__ = ["Gate", "fixed_chars", "gate", "input_budget", "pack", "pmap", "tokens", "workers"]

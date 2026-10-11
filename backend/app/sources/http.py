"""Cached HTTP GET for the public sources. One JSON file per request: url, params (without keys), time, answer.

A 404 is cached as an answer too ("no label for this drug" is a result). Keys (api_key) never reach the cache
key or the file. 429 and 5xx are retried with backoff; `min_interval` keeps under a source's rate limit.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

CACHE_ROOT = Path(__file__).resolve().parents[2] / "data" / "cache"
SECRET_PARAMS = {"api_key", "key", "token"}


class SourceError(RuntimeError):
    pass


def backoff(attempt: int) -> float:
    """2.4: seconds before retry `attempt` (0-based): 1, 2, 4, 8, 16 capped at 20, plus up to 30% jitter. Transient
    network errors (SSL EOF from ClinicalTrials.gov on 10.10.2026) outlasted the old 0.5-4 s schedule."""
    import random
    base = min(2.0 ** attempt, 20.0)
    return base * (1 + 0.3 * random.random())


class CachedHTTP:
    def __init__(self, name: str, cache_root: str | Path | None = None, http: httpx.Client | None = None,
                 offline: bool = False, refresh: bool = False, retries: int = 5, min_interval: float = 0.0,
                 timeout: float = 30):
        self.name = name
        self.cache_dir = Path(cache_root if cache_root is not None else CACHE_ROOT) / name   # read at call time (tests)
        self.http = http
        self.offline = offline
        self.refresh = refresh
        self.retries = retries
        self.min_interval = min_interval
        self.timeout = timeout
        self.calls: list[dict[str, Any]] = []
        self._last = 0.0

    def path(self, url: str, params: dict) -> Path:
        public = {k: v for k, v in sorted(params.items()) if k not in SECRET_PARAMS}
        raw = json.dumps({"url": url, "params": public}, sort_keys=True, default=str)
        return self.cache_dir / f"{hashlib.sha256(raw.encode()).hexdigest()[:16]}.json"

    def get(self, url: str, params: dict | None = None, kind: str = "json") -> Any:
        """Body as parsed JSON (kind="json") or text (kind="text"); None for a 404."""
        params = dict(params or {})
        public = {k: v for k, v in params.items() if k not in SECRET_PARAMS}
        path = self.path(url, params)
        if path.exists() and not self.refresh:
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.calls.append({"source": self.name, "url": url, "params": public, "cache": True,
                               "fetched_at": saved["fetched_at"]})
            return saved["body"]
        if self.offline:
            raise SourceError(f"{self.name}: offline and no cached response for {url} {public}")

        status, body = self._get(url, params, kind)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"source": self.name, "url": url, "params": public, "fetched_at": fetched_at,
                                    "status": status, "body": body}, indent=1, ensure_ascii=False), encoding="utf-8")
        self.calls.append({"source": self.name, "url": url, "params": public, "cache": False, "fetched_at": fetched_at})
        return body

    def _get(self, url: str, params: dict, kind: str) -> tuple[int, Any]:
        if self.http is None:
            self.http = httpx.Client(timeout=self.timeout, follow_redirects=True)
        http = self.http
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                resp = http.get(url, params=params)
            except httpx.TransportError as exc:
                if attempt == self.retries:
                    raise SourceError(f"{self.name}: network error: {exc!r}") from exc
            else:
                if resp.status_code == 404:
                    return 404, None
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt == self.retries:
                        raise SourceError(f"{self.name}: HTTP {resp.status_code} after {attempt + 1} attempts")
                elif resp.status_code >= 400:
                    raise SourceError(f"{self.name}: HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    if kind == "text":
                        return resp.status_code, resp.text
                    try:
                        return resp.status_code, resp.json()
                    except ValueError as exc:
                        raise SourceError(f"{self.name}: non-JSON response") from exc
            time.sleep(backoff(attempt))
        raise AssertionError("unreachable")

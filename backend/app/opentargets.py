"""Minimal Open Targets Platform GraphQL client.

Every response is saved as a JSON file in the cache folder (request + response + time). The same files are
replayed in tests, so every live run can become a test fixture. No database.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

URL = "https://api.platform.opentargets.org/api/v4/graphql"
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache"   # backend/data/cache, wherever you run from

SEARCH = """
query Search($q: String!, $entities: [String!]!) {
  search(queryString: $q, entityNames: $entities, page: {index: 0, size: 10}) {
    total
    hits { id name entity description score }
  }
}"""

DISEASE = """
query Disease($id: String!) {
  disease(efoId: $id) {
    id name description
    synonyms { relation terms }
    dbXRefs
    therapeuticAreas { id name }
  }
}"""

# 2.8: parents and grandparents of a disease (its own query name, so answers cached for "Disease" stay valid)
LINEAGE = """
query DiseaseLineage($id: String!) {
  disease(efoId: $id) {
    id
    therapeuticAreas { id }
    parents { id name parents { id name } }
  }
}"""
ROOTS = {"MONDO_0000001", "EFO_0000408", "MONDO_0700096", "EFO_0000651", "OTAR_0000018", "EFO_0000616",
         "MONDO_0045024", "GO_0008150", "EFO_0001444"}

TARGET = """
query Target($id: String!) {
  target(ensemblId: $id) {
    id approvedSymbol approvedName biotype
    synonyms { label source }
  }
}"""

META = """
query Meta {
  meta { dataVersion { year month iteration } }
}"""


class OpenTargetsError(RuntimeError):
    pass


def cache_key(name: str, variables: dict[str, Any]) -> str:
    raw = json.dumps({"q": name, "v": variables}, sort_keys=True)
    return f"{name}_{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


class OpenTargets:
    def __init__(self, cache_dir: str | Path = CACHE_DIR, url: str = URL, http: httpx.Client | None = None,
                 offline: bool = False, refresh: bool = False, retries: int = 5):
        self.cache_dir = Path(cache_dir)
        self.url = url
        self.http = http
        self.offline = offline          # tests: cache only, never the network
        self.refresh = refresh          # ignore cached responses and fetch again (the new ones overwrite them)
        self.retries = retries
        self.calls: list[dict[str, Any]] = []   # what was asked, from cache or live (for logs and provenance)

    def query(self, name: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        key = cache_key(name, variables)
        path = self.cache_dir / f"{key}.json"
        if path.exists() and not self.refresh:
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.calls.append({"query": name, "variables": variables, "cache": True, "fetched_at": saved["fetched_at"]})
            return saved["response"]["data"]
        if self.offline:
            raise OpenTargetsError(f"offline and no cached response for {name} {variables}")

        response = self._post({"operationName": name, "query": query, "variables": variables})
        if response.get("errors"):
            raise OpenTargetsError(f"{name}: " + "; ".join(str(e.get("message", e)) for e in response["errors"]))
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"query": name, "variables": variables, "fetched_at": fetched_at,
                                    "url": self.url, "response": response}, indent=1, ensure_ascii=False),
                        encoding="utf-8")
        self.calls.append({"query": name, "variables": variables, "cache": False, "fetched_at": fetched_at})
        return response["data"]

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        http = self.http or httpx.Client(timeout=30)
        for attempt in range(self.retries + 1):
            try:
                resp = http.post(self.url, json=body)
            except httpx.TransportError as exc:
                if attempt == self.retries:
                    raise OpenTargetsError(f"network error: {exc!r}") from exc
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt == self.retries:
                        raise OpenTargetsError(f"HTTP {resp.status_code} after {attempt + 1} attempts")
                else:
                    try:
                        payload = resp.json()
                    except ValueError as exc:
                        raise OpenTargetsError(f"non-JSON response, HTTP {resp.status_code}") from exc
                    if resp.status_code >= 400 and not payload.get("errors"):
                        raise OpenTargetsError(f"HTTP {resp.status_code}")
                    return payload
            from backend.app.sources.http import backoff
            time.sleep(backoff(attempt))
        raise AssertionError("unreachable")

    # --- typed helpers ---------------------------------------------------------
    def search(self, text: str, entity: str) -> list[dict[str, Any]]:
        data = self.query("Search", SEARCH, {"q": text, "entities": [entity]})
        return (data.get("search") or {}).get("hits") or []

    def disease(self, disease_id: str) -> dict[str, Any] | None:
        return self.query("Disease", DISEASE, {"id": disease_id}).get("disease")

    def lineage(self, disease_id: str) -> list[dict[str, str]]:
        """2.8: broader diseases (parents, grandparents) as [{id, name}], without roots and therapeutic areas.
        Used only to find failures registered under a broader disease (ACCELERATE: "cardiovascular diseases" for
        coronary artery disease). Empty when the query fails: then nothing changes."""
        try:
            d = self.query("DiseaseLineage", LINEAGE, {"id": disease_id}).get("disease") or {}
        except Exception:                               # noqa: BLE001 - lineage is an extra, never a blocker
            return []
        skip = ROOTS | {a.get("id") for a in d.get("therapeuticAreas") or []} | {disease_id}
        out, seen = [], set()
        for p in d.get("parents") or []:
            for x in [p] + list(p.get("parents") or []):
                if x.get("id") and x["id"] not in skip and x["id"] not in seen:
                    seen.add(x["id"])
                    out.append({"id": x["id"], "name": x.get("name") or ""})
        return out

    def target(self, ensembl_id: str) -> dict[str, Any] | None:
        return self.query("Target", TARGET, {"id": ensembl_id}).get("target")

    def release(self) -> str | None:
        """Data release, e.g. "26.09"."""
        dv = (self.query("Meta", META, {}).get("meta") or {}).get("dataVersion") or {}
        if not dv.get("year"):
            return None
        return f"{str(dv['year'])[-2:]}.{str(dv.get('month') or '').zfill(2)}"

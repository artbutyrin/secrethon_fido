"""openFDA drug labels (https://open.fda.gov/apis/drug/label/). No key needed; OPENFDA_API_KEY raises the limit.

Only approved drugs have labels, so this covers mechanisms that already reached the market. The sections read are
the ones that describe links 2-4 of the translation chain: exposure, target engagement, pharmacodynamic response.
"""
from __future__ import annotations

from typing import Any

from backend.app.sources.http import CachedHTTP

URL = "https://api.fda.gov/drug/label.json"
SECTIONS = ("mechanism_of_action", "pharmacodynamics", "pharmacokinetics", "clinical_pharmacology")
MAX_SECTION_CHARS = 6000


def dailymed_url(set_id: str) -> str:
    return f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={set_id}"


class OpenFDA:
    def __init__(self, http: CachedHTTP | None = None, api_key: str | None = None):
        self.http = http or CachedHTTP("openfda")
        self.api_key = api_key

    def _search(self, field: str, name: str) -> dict | None:
        params: dict[str, Any] = {"search": f'{field}:"{name}"', "limit": 1}
        if self.api_key:
            params["api_key"] = self.api_key
        body = self.http.get(URL, params)
        results = (body or {}).get("results") or []
        return results[0] if results else None

    def label(self, generic_name: str) -> dict | None:
        """The current label of a drug by its generic name, or None. Sections are joined to plain text."""
        name = generic_name.strip().lower()
        if not name:
            return None
        res = self._search("openfda.generic_name", name) or self._search("openfda.substance_name", name)
        if not res:
            return None
        sections = {s: " ".join(res.get(s) or [])[:MAX_SECTION_CHARS] for s in SECTIONS if res.get(s)}
        if not sections:
            return None
        meta = res.get("openfda") or {}
        set_id = res.get("set_id") or ""
        return {"query": name, "set_id": set_id, "effective_time": res.get("effective_time"),
                "generic_name": (meta.get("generic_name") or [name])[0], "brand_name": (meta.get("brand_name") or [None])[0],
                "url": dailymed_url(set_id) if set_id else None, "sections": sections}

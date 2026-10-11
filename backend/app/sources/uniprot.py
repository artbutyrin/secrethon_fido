"""UniProt subcellular location (https://rest.uniprot.org). Used for one question: can a large molecule reach the target?

Only reviewed human entries. Each location keeps its UniProt id (SL-xxxx), the isoform it is about, and its
evidence codes, so the claim can say why. "Nucleus membrane" or "Mitochondrion membrane" are NOT the cell surface.
"""
from __future__ import annotations

import re

from backend.app.sources.http import CachedHTTP

SEARCH = "https://rest.uniprot.org/uniprotkb/search"
SURFACE = re.compile(r"^(?:cell membrane|plasma membrane|cell surface|secreted|extracellular)", re.I)


def is_surface(location: str) -> bool:
    """True for the cell surface or outside the cell; organelle membranes do not count."""
    return bool(SURFACE.search((location or "").strip()))


class UniProt:
    def __init__(self, http: CachedHTTP | None = None):
        self.http = http or CachedHTTP("uniprot")

    def locations(self, symbol: str) -> dict | None:
        body = self.http.get(SEARCH, {"query": f"gene_exact:{symbol} AND organism_id:9606 AND reviewed:true",
                                      "fields": "accession,gene_primary,cc_subcellular_location",
                                      "format": "json", "size": 5})
        entries = (body or {}).get("results") or []
        entry = next((e for e in entries if any((g.get("geneName") or {}).get("value", "").upper() == symbol.upper()
                                                for g in e.get("genes") or [])), entries[0] if entries else None)
        if not entry:
            return None
        acc = entry.get("primaryAccession")
        locs = []
        for comment in entry.get("comments") or []:
            if comment.get("commentType") != "SUBCELLULAR LOCATION":
                continue
            for sl in comment.get("subcellularLocations") or []:
                loc = sl.get("location") or {}
                if loc.get("value"):
                    locs.append({"value": loc["value"], "id": loc.get("id"), "molecule": comment.get("molecule"),
                                 "evidence": sorted({e.get("evidenceCode") for e in loc.get("evidences") or []} - {None})})
        return {"accession": acc, "url": f"https://www.uniprot.org/uniprotkb/{acc}/entry#subcellular_location",
                "locations": locs}

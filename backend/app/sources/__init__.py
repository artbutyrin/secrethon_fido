"""Public sources beyond Open Targets, for the translation chain (brief, step 3).

  openfda.py   FDA drug labels: pharmacokinetics, pharmacodynamics, mechanism of action of approved drugs
  uniprot.py   UniProt subcellular location with evidence codes (can an antibody reach the target?)
  pubmed.py    PubMed abstracts via NCBI E-utilities (PK/PD, target engagement, animal models)
  aact.py      AACT, the ClinicalTrials.gov database in Postgres: outcomes, p-values, MeSH conditions

Every client caches each answer as a JSON file under backend/data/cache/<source>/, like the Open Targets client,
so a rerun is free and every live run can become a test fixture. `Sources.from_env()` builds the set the API uses.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from backend.app.sources import ctgov
from backend.app.sources.aact import AACT
from backend.app.sources.http import CachedHTTP
from backend.app.sources.openfda import OpenFDA
from backend.app.sources.pubmed import PubMed
from backend.app.sources.uniprot import UniProt


@dataclass
class Sources:
    openfda: OpenFDA | None = None
    uniprot: UniProt | None = None
    pubmed: PubMed | None = None
    aact: AACT | ctgov.CTGov | None = None

    @staticmethod
    def trials(offline: bool, refresh: bool = False) -> "AACT | ctgov.CTGov":
        """Trial registry: AACT when AACT_DSN is set, otherwise the public ClinicalTrials.gov API v2 (same row
        shape). UNOBIO_CTGOV=0 turns the fallback off (AACT is then skipped as before)."""
        dsn = os.environ.get("AACT_DSN")
        if dsn or os.environ.get("UNOBIO_CTGOV", "1") in ("0", "false"):
            return AACT(dsn, offline=offline, refresh=refresh)
        return ctgov.make(offline=offline, refresh=refresh)

    @classmethod
    def from_env(cls, offline: bool | None = None, refresh: bool = False) -> "Sources":
        """All sources. UNOBIO_OFFLINE=1 (tests) means cache only, never the network.
        AACT is used only when AACT_DSN is set; NCBI_API_KEY raises the PubMed rate limit."""
        if offline is None:
            offline = os.environ.get("UNOBIO_OFFLINE", "") not in ("", "0", "false")
        def http(name, **kw):
            return CachedHTTP(name, offline=offline, refresh=refresh, **kw)
        return cls(openfda=OpenFDA(http("openfda"), api_key=os.environ.get("OPENFDA_API_KEY")),
                   uniprot=UniProt(http("uniprot")),
                   pubmed=PubMed(http("pubmed", min_interval=0.11 if os.environ.get("NCBI_API_KEY") else 0.34),
                                 api_key=os.environ.get("NCBI_API_KEY"), email=os.environ.get("NCBI_EMAIL")),
                   aact=cls.trials(offline, refresh))

    def calls(self) -> list[dict]:
        out = []
        for client in (self.openfda, self.uniprot, self.pubmed, self.aact):
            out += getattr(client, "calls", None) or getattr(getattr(client, "http", None), "calls", None) or []
        return out

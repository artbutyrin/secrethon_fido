"""ClinicalTrials.gov API v2 (https://clinicaltrials.gov/data-api/api): the public, key-free fallback for AACT.

Used when AACT_DSN is not set. Returns the SAME row shape as aact.AACT.trials_for_drugs, so the translation chain,
the stopped-trial merge and the primary-outcome failure check (translation.aact_failures) work unchanged:

  nct_id, phase, stage, overall_status, why_stopped, enrollment, sponsor, start_date, results_posted,
  matched (drug names that are an intervention name or other name of the trial), mesh_terms (MeSH terms and their
  ancestors, lower case), conditions, design_outcomes [{type, measure}], primary_analyses [{outcome, p_value,
  non_inferiority, method}]

Why it matters: a Phase 3 failure that ended as "Completed" (or without a stop reason in Open Targets) is invisible
to the stopped-trial list; its registered primary-outcome analyses are not. Example: tominersen, GENERATION HD1.
Requests go through the shared JSON cache (backend/data/cache/ctgov/).
"""
from __future__ import annotations

import re
from typing import Any

from backend.app.sources.aact import normalize_phase
from backend.app.sources.http import CachedHTTP, SourceError

URL = "https://clinicaltrials.gov/api/v2/studies"
NAMES_PER_QUERY = 8
PAGE_SIZE = 100
MAX_PAGES = 3


def _lower(xs) -> list[str]:
    return sorted({str(x).strip().lower() for x in xs or [] if x and str(x).strip()})


def study_row(study: dict, names: set[str]) -> dict | None:
    """One API v2 study -> an AACT-shaped row; None if none of `names` is an intervention of the study."""
    ps = study.get("protocolSection") or {}
    ident, status = ps.get("identificationModule") or {}, ps.get("statusModule") or {}
    design, arms = ps.get("designModule") or {}, ps.get("armsInterventionsModule") or {}
    nct = ident.get("nctId")
    if not nct:
        return None
    inter = []
    for i in arms.get("interventions") or []:
        inter += [i.get("name")] + list(i.get("otherNames") or [])
    matched = sorted(names & set(_lower(inter)))
    if not matched:                      # the search matched other text (e.g. a background therapy): not this drug
        return None
    browse = (study.get("derivedSection") or {}).get("conditionBrowseModule") or {}
    mesh = [m.get("term") for m in (browse.get("meshes") or []) + (browse.get("ancestors") or [])]
    outcomes = ps.get("outcomesModule") or {}
    design_outcomes = [{"type": kind, "measure": o.get("measure")}
                       for kind, key in (("primary", "primaryOutcomes"), ("secondary", "secondaryOutcomes"))
                       for o in outcomes.get(key) or []]
    analyses = []
    for om in ((study.get("resultsSection") or {}).get("outcomeMeasuresModule") or {}).get("outcomeMeasures") or []:
        if (om.get("type") or "").upper() != "PRIMARY":
            continue
        for a in om.get("analyses") or []:
            analyses.append({"outcome": om.get("title"), "p_value": a.get("pValue"),
                             "non_inferiority": a.get("nonInferiorityType"), "method": a.get("statisticalMethod")})
    phase = "/".join(design.get("phases") or [])
    return {"nct_id": nct, "phase": phase or None, "stage": normalize_phase(phase),
            "overall_status": (status.get("overallStatus") or "").upper().replace(" ", "_").replace(",", ""),
            "why_stopped": status.get("whyStopped"),
            "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
            "sponsor": ((ps.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name"),
            "start_date": (status.get("startDateStruct") or {}).get("date"),
            "results_posted": (status.get("resultsFirstPostDateStruct") or {}).get("date"),
            "matched": matched, "mesh_terms": _lower(mesh),
            "conditions": _lower((ps.get("conditionsModule") or {}).get("conditions")),
            "design_outcomes": design_outcomes or None, "primary_analyses": analyses or None,
            "title": ident.get("briefTitle"), "via": "clinicaltrials.gov API v2"}


_UNSEARCHABLE = re.compile(r'["()\[\]{}:;*?\\]|\b(?:and|or|not)\b', re.I)


def searchable(name: str) -> bool:
    """A drug name the ClinicalTrials.gov search can take as one quoted phrase."""
    return 2 < len(name) <= 60 and not _UNSEARCHABLE.search(name)


class CTGov:
    """Same interface as aact.AACT (ready, offline, calls, trials_for_drugs)."""
    ready = True
    name = "clinicaltrials.gov"

    def __init__(self, http: CachedHTTP):
        self.http = http
        self.offline = http.offline

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.http.calls

    def trials_for_drugs(self, names: list[str]) -> list[dict]:
        names = sorted({n.strip().lower() for n in names if n and n.strip()})
        wanted, rows = set(names), {}
        self.skipped: list[str] = []
        # 2.7: names the search syntax cannot take (quotes, brackets, boolean words, very long trade-name strings) are
        # not searched; they still match a found study's interventions. One such synonym made CML + ABL1 lose the
        # whole registry ("Too complicated query" even for a single name).
        names = [n for n in names if searchable(n)] or names
        for i in range(0, len(names), NAMES_PER_QUERY):
            self._fetch(names[i:i + NAMES_PER_QUERY], wanted, rows)
        return [rows[k] for k in sorted(rows)]

    def _fetch(self, group: list[str], wanted: set[str], rows: dict) -> None:
        """2.4: HTTP 400 "Too complicated query" (CML + ABL1, 10.10.2026: long drug names with OR) splits the group
        in halves until the API accepts it; a single name that is still refused raises as before."""
        params = {"query.intr": " OR ".join(f'"{n}"' for n in group), "pageSize": PAGE_SIZE, "format": "json"}
        for _ in range(MAX_PAGES):
            try:
                body = self.http.get(URL, params) or {}
            except SourceError as exc:
                refused = "too complicated" in str(exc).lower() or "error parsing query" in str(exc).lower()
                if refused and len(group) > 1 and "pageToken" not in params:
                    half = len(group) // 2
                    self._fetch(group[:half], wanted, rows)
                    self._fetch(group[half:], wanted, rows)
                    return
                if refused and "pageToken" not in params:
                    self.skipped.append(group[0])          # one name the API refuses: skip it, keep the others
                    return
                raise
            for s in body.get("studies") or []:
                r = study_row(s, wanted)
                if r and r["nct_id"] not in rows:
                    rows[r["nct_id"]] = r
            token = body.get("nextPageToken")
            if not token:
                break
            params = {**params, "pageToken": token}


def make(offline: bool = False, refresh: bool = False) -> CTGov:
    import httpx
    client = httpx.Client(timeout=30, follow_redirects=True,
                          headers={"User-Agent": "unobio/0.10 (biotech underwriting research)", "Accept": "application/json"})
    return CTGov(CachedHTTP("ctgov", http=client, offline=offline, refresh=refresh, min_interval=0.2))


__all__ = ["CTGov", "SourceError", "make", "study_row"]

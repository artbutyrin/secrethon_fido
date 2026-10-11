"""AACT: ClinicalTrials.gov as a Postgres database (https://aact.ctti-clinicaltrials.org).

Set AACT_DSN, e.g. postgresql://user:pass@localhost:5432/aact (your local copy) or the public
aact-db.ctti-clinicaltrials.org. Without it the source is skipped and the run says so. Needs `psycopg` (v3) or
`psycopg2`. Answers are cached as JSON under backend/data/cache/aact/, like every other source.

One query returns every trial of the given drug names (intervention names and their other names) with:
MeSH condition terms (to map a trial to the disease when Open Targets has no mapping), the stop reason,
registered outcome titles (what was *tested*), and p-values of primary-outcome analyses (what was *shown*).
Column names follow the AACT `ctgov` schema; check them with `\\d ctgov.<table>` if your copy is older.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "aact"
MAX_NAMES = 60

SQL = """
WITH hits AS (
  SELECT i.nct_id, lower(i.name) AS matched FROM ctgov.interventions i WHERE lower(i.name) = ANY(%(names)s)
  UNION
  SELECT o.nct_id, lower(o.name) FROM ctgov.intervention_other_names o WHERE lower(o.name) = ANY(%(names)s)
)
SELECT s.nct_id, s.phase, s.overall_status, s.why_stopped, s.enrollment, s.source AS sponsor,
       s.start_date::text AS start_date, s.results_first_posted_date::text AS results_posted,
       array_agg(DISTINCT h.matched) AS matched,
       (SELECT array_agg(DISTINCT bc.downcase_mesh_term) FROM ctgov.browse_conditions bc
         WHERE bc.nct_id = s.nct_id) AS mesh_terms,
       (SELECT array_agg(DISTINCT lower(c.name)) FROM ctgov.conditions c WHERE c.nct_id = s.nct_id) AS conditions,
       (SELECT json_agg(json_build_object('type', lower(d.outcome_type), 'measure', d.measure))
          FROM ctgov.design_outcomes d WHERE d.nct_id = s.nct_id) AS design_outcomes,
       (SELECT json_agg(json_build_object('outcome', oc.title, 'p_value', a.p_value,
                                          'non_inferiority', a.non_inferiority_type, 'method', a.method))
          FROM ctgov.outcomes oc JOIN ctgov.outcome_analyses a ON a.outcome_id = oc.id
         WHERE oc.nct_id = s.nct_id AND lower(oc.outcome_type) = 'primary') AS primary_analyses
FROM hits h JOIN ctgov.studies s ON s.nct_id = h.nct_id
GROUP BY s.nct_id, s.phase, s.overall_status, s.why_stopped, s.enrollment, s.source, s.start_date,
         s.results_first_posted_date
ORDER BY s.nct_id
LIMIT 3000
"""


class AACTError(RuntimeError):
    pass


def _connect_default(dsn: str):
    try:
        import psycopg  # type: ignore
        return psycopg.connect(dsn, connect_timeout=15)
    except ImportError:
        pass
    try:
        import psycopg2  # type: ignore
        return psycopg2.connect(dsn, connect_timeout=15)
    except ImportError as exc:
        raise AACTError("AACT_DSN is set but neither psycopg nor psycopg2 is installed (pip install psycopg[binary])") from exc


def normalize_phase(phase: str | None) -> str | None:
    """AACT 'PHASE2/PHASE3', 'Phase 2/Phase 3', 'EARLY_PHASE1' -> Open Targets style 'PHASE_2_3', 'PHASE_1'."""
    p = (phase or "").upper().replace(" ", "").replace("EARLY_", "")
    nums = [ch for ch in p if ch.isdigit()]
    if not nums:
        return None
    return "PHASE_" + "_".join(dict.fromkeys(nums))


class AACT:
    def __init__(self, dsn: str | None, cache_dir: str | Path = CACHE_DIR, offline: bool = False,
                 refresh: bool = False, connect: Callable[[str], Any] | None = None):
        self.dsn = dsn
        self.cache_dir = Path(cache_dir)
        self.offline = offline
        self.refresh = refresh
        self.connect = connect or _connect_default
        self.calls: list[dict[str, Any]] = []

    @property
    def ready(self) -> bool:
        return bool(self.dsn)

    def trials_for_drugs(self, names: list[str]) -> list[dict]:
        names = sorted({n.strip().lower() for n in names if n and n.strip()})[:MAX_NAMES]
        if not names:
            return []
        key = hashlib.sha256(json.dumps(names).encode()).hexdigest()[:16]
        path = self.cache_dir / f"trials_{key}.json"
        if path.exists() and not self.refresh:
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.calls.append({"source": "aact", "names": names, "cache": True, "fetched_at": saved["fetched_at"]})
            return saved["rows"]
        if self.offline:
            raise AACTError(f"aact: offline and no cached response for {names[:5]}")
        if not self.dsn:
            raise AACTError("AACT_DSN is not set")
        con = self.connect(self.dsn)
        try:
            cur = con.cursor()
            cur.execute(SQL, {"names": names})
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            con.close()
        for r in rows:
            for k in ("design_outcomes", "primary_analyses"):
                if isinstance(r.get(k), str):
                    r[k] = json.loads(r[k])
            r["stage"] = normalize_phase(r.get("phase"))
            r["overall_status"] = (r.get("overall_status") or "").upper().replace(" ", "_").replace(",", "")
        rows = json.loads(json.dumps(rows, default=str))      # dates and decimals as text, same as from the cache
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"source": "aact", "names": names, "fetched_at": fetched_at, "rows": rows},
                                   indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        self.calls.append({"source": "aact", "names": names, "cache": False, "fetched_at": fetched_at})
        return rows

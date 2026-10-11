"""Pipeline stage 2: collect raw Open Targets data for a resolved disease + target pair.

Six queries. Each one is independent: if one fails (for example, a field Open Targets renamed), the error is
recorded and the others still run. Nothing is interpreted here; step 4 turns the raw data into claims.

Every block carries `complete`: True only when every row was received. Only a complete block may later prove
absence ("no genetic evidence", "zero approved drugs").

The field names were checked against the Open Targets API source code, not yet against live responses.
`knownDrugs` no longer exists: drugs and trials come from `drugAndClinicalCandidates` and its `clinicalReports`.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend.app.opentargets import OpenTargets

RUNS_DIR = Path(__file__).resolve().parents[1] / "data" / "runs"

GENETIC_DATASOURCES = ["gwas_credible_sets", "gene_burden", "eva", "genomics_england", "gene2phenotype",
                       "uniprot_literature", "uniprot_variants", "orphanet", "clingen", "intogen",
                       "cancer_gene_census", "eva_somatic"]
# Link 1 of the translation chain (molecular effect). Perturbation = knocking out or blocking the target changes
# a disease phenotype (mouse knockouts, CRISPR screens). Correlational = expression change, pathway membership.
PERTURBATION_DATASOURCES = ["impc", "crispr", "crispr_screen", "ot_crispr", "ot_crispr_validation"]
CORRELATIONAL_DATASOURCES = ["expression_atlas", "reactome", "progeny", "slapenrich", "sysbio"]
BIOLOGY_DATASOURCES = PERTURBATION_DATASOURCES + CORRELATIONAL_DATASOURCES

PAIR_GENETICS = """
query PairGenetics($efoId: String!, $ensemblId: String!, $datasources: [String!], $size: Int!, $cursor: String) {
  disease(efoId: $efoId) {
    id
    evidences(ensemblIds: [$ensemblId], enableIndirect: true, datasourceIds: $datasources, size: $size, cursor: $cursor) {
      count
      cursor
      rows { id datasourceId datatypeId score clinicalSignificances disease { id name } }
    }
  }
}"""

DISEASE_GENETICS = """
query DiseaseGenetics($efoId: String!, $size: Int!) {
  disease(efoId: $efoId) {
    id
    associatedTargets(page: {index: 0, size: $size}) {
      count
      rows { target { id approvedSymbol } score datatypeScores { id score } }
    }
  }
}"""

_REPORTS = """
        clinicalReports {
          id source url type clinicalStage trialPhase trialOverallStatus trialWhyStopped trialStopReasonCategories
          trialStartDate trialSponsor { name }
          diseases { disease { id } diseaseFromSource }
        }"""
_MECHANISMS = "mechanismsOfAction { rows { actionType mechanismOfAction targets { id } } }"

TARGET_DRUGS = """
query TargetDrugs($ensemblId: String!) {
  target(ensemblId: $ensemblId) {
    id
    drugAndClinicalCandidates {
      count
      rows {
        id
        maxClinicalStage
        drug {
          id name drugType maximumClinicalStage
          synonyms { label }
          tradeNames { label }
          drugWarnings { warningType }
          """ + _MECHANISMS + """
          indications { count rows { maxClinicalStage disease { id name therapeuticAreas { id name } } } }
        }""" + _REPORTS + """
      }
    }
  }
}"""

DISEASE_DRUGS = """
query DiseaseDrugs($efoId: String!) {
  disease(efoId: $efoId) {
    id
    drugAndClinicalCandidates {
      count
      rows {
        id
        maxClinicalStage
        drug {
          id name maximumClinicalStage
          synonyms { label }
          """ + _MECHANISMS + """
        }""" + _REPORTS + """
      }
    }
  }
}"""

TARGET_INFO = """
query TargetInfo($ensemblId: String!) {
  target(ensemblId: $ensemblId) {
    id
    approvedSymbol
    isEssential
    safetyLiabilities { event eventId datasource }
    prioritisation { items { key value } }
    subcellularLocations { location source termSL labelSL }
    tractability { label modality value }
  }
}"""


def _complete(block: dict) -> bool:
    n = block.get("count")
    return n is not None and len(block.get("rows") or []) >= int(n) and not block.get("cursor")


def pair_genetics(ot: OpenTargets, disease_id: str, target_id: str, page_size: int = 500,
                  max_pages: int = 10, datasources: list[str] = GENETIC_DATASOURCES) -> dict:
    rows, count, cursor = [], None, None
    for _ in range(max_pages):
        data = ot.query("PairGenetics", PAIR_GENETICS, {"efoId": disease_id, "ensemblId": target_id,
                                                        "datasources": datasources,
                                                        "size": page_size, "cursor": cursor})
        block = (data.get("disease") or {}).get("evidences")
        if block is None:
            return {"count": None, "rows": rows, "cursor": None}
        count, cursor = block.get("count"), block.get("cursor")
        rows += block.get("rows") or []
        if not cursor or not block.get("rows"):
            cursor = None
            break
    return {"count": count, "rows": rows, "cursor": cursor}     # cursor left = pages not fetched = incomplete


def disease_genetics(ot: OpenTargets, disease_id: str, size: int = 100) -> dict:
    data = ot.query("DiseaseGenetics", DISEASE_GENETICS, {"efoId": disease_id, "size": size})
    return (data.get("disease") or {}).get("associatedTargets") or {}


def target_drugs(ot: OpenTargets, target_id: str) -> dict:
    data = ot.query("TargetDrugs", TARGET_DRUGS, {"ensemblId": target_id})
    return (data.get("target") or {}).get("drugAndClinicalCandidates") or {}


def disease_drugs(ot: OpenTargets, disease_id: str) -> dict:
    data = ot.query("DiseaseDrugs", DISEASE_DRUGS, {"efoId": disease_id})
    return (data.get("disease") or {}).get("drugAndClinicalCandidates") or {}


def target_info(ot: OpenTargets, target_id: str) -> dict:
    return ot.query("TargetInfo", TARGET_INFO, {"ensemblId": target_id}).get("target") or {}


def collect(ot: OpenTargets, disease_id: str, target_id: str) -> dict[str, Any]:
    """Runs the six queries. Returns {name: {"ok", "complete", "data" | "error"}} plus run metadata."""
    parts: dict[str, Callable[[], dict]] = {
        "pair_genetics": lambda: pair_genetics(ot, disease_id, target_id),
        "disease_genetics": lambda: disease_genetics(ot, disease_id),
        "target_drugs": lambda: target_drugs(ot, target_id),
        "disease_drugs": lambda: disease_drugs(ot, disease_id),
        "target_info": lambda: target_info(ot, target_id),
        "pair_biology": lambda: pair_genetics(ot, disease_id, target_id, datasources=BIOLOGY_DATASOURCES),
    }
    try:
        release = ot.release()
    except Exception:                                  # the release is metadata; its failure must not stop collection
        release = None
    out: dict[str, Any] = {"disease_id": disease_id, "target_id": target_id, "ot_release": release,
                           "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "parts": {}}
    for name, fetch in parts.items():
        try:
            data = fetch()
        except Exception as exc:                       # one failed query must not lose the others
            out["parts"][name] = {"ok": False, "complete": False, "error": f"{type(exc).__name__}: {exc}"}
            continue
        complete = bool(data) if name == "target_info" else _complete(data)
        out["parts"][name] = {"ok": True, "complete": complete, "data": data}
    # 2.4: one more pass for the queries that failed (sepsis + TLR4, 10.10.2026: two transient failures turned the run
    # into Insufficient evidence). A query that fails again stays failed and the run is marked incomplete.
    for name in [n for n, p in out["parts"].items() if not p["ok"]]:
        try:
            data = parts[name]()
        except Exception as exc:
            out["parts"][name]["error"] += f"; retry: {type(exc).__name__}: {exc}"
            continue
        complete = bool(data) if name == "target_info" else _complete(data)
        out["parts"][name] = {"ok": True, "complete": complete, "data": data, "retried": True}
    return out


def save(result: dict, runs_dir: Path = RUNS_DIR) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{result['disease_id']}__{result['target_id']}.json"
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


# --- summary for the command line ------------------------------------------------------------
STOPPED = {"terminated", "withdrawn", "suspended"}


def _reports(rows):
    return [r for row in rows for r in row.get("clinicalReports") or []]


def summary(result: dict) -> str:
    """Short human-readable summary of a collect() result."""
    lines: list[str] = []
    lines.append(f"Open Targets release: {result['ot_release']}")
    for name, part in result["parts"].items():
        head = f"\n[{name}] " + ("OK" if part["ok"] else "FAILED") + (", complete" if part.get("complete") else
                                                                       ", INCOMPLETE" if part["ok"] else "")
        lines.append(head)
        if not part["ok"]:
            lines.append(f"  {part['error'][:500]}")
            continue
        d = part["data"]
        if name in ("pair_genetics", "pair_biology"):
            src = Counter(r.get("datasourceId") for r in d.get("rows") or [])
            lines.append(f"  evidence rows: {len(d.get('rows') or [])} of count {d.get('count')}")
            lines.append(f"  by datasource: {dict(src) or 'none'}")
            gwas = [r.get("score") for r in d.get("rows") or [] if r.get("datasourceId") == "gwas_credible_sets"]
            if gwas:
                lines.append(f"  GWAS scores (L2G): max {max(gwas):.2f}, >= 0.5: {sum(s >= 0.5 for s in gwas)}")
        elif name == "disease_genetics":
            rows = d.get("rows") or []
            with_gen = [r["target"]["approvedSymbol"] for r in rows if any(
                x.get("id") == "genetic_association" and (x.get("score") or 0) > 0 for x in r.get("datatypeScores") or [])]
            lines.append(f"  associated targets: {d.get('count')} (checked {len(rows)}); with genetic evidence: {len(with_gen)}"
                  + (f", e.g. {', '.join(with_gen[:5])}" if with_gen else ""))
        elif name in ("target_drugs", "disease_drugs"):
            rows = d.get("rows") or []
            stages = Counter(r.get("maxClinicalStage") for r in rows)
            reports = _reports(rows)
            stopped = [r for r in reports if (r.get("trialOverallStatus") or "").lower().replace(" ", "_") in STOPPED]
            lines.append(f"  drugs: {len(rows)} of count {d.get('count')}; by max stage: {dict(stages)}")
            lines.append(f"  clinical reports: {len(reports)}; stopped: {len(stopped)}; "
                  f"with a reason: {sum(bool(r.get('trialWhyStopped')) for r in stopped)}")
            for row in rows[:3]:
                drug = row.get("drug") or {}
                moa = [m.get("actionType") for m in ((drug.get("mechanismsOfAction") or {}).get("rows") or [])]
                lines.append(f"  e.g. {drug.get('name')} ({drug.get('drugType', '')}) stage {row.get('maxClinicalStage')}, "
                      f"action {sorted(set(filter(None, moa)))}")
            for r in [r for r in stopped if r.get("trialWhyStopped")][:3]:
                lines.append(f"  stopped: {r.get('id')} {r.get('trialOverallStatus')}: {r['trialWhyStopped'][:120]!r}")
        elif name == "target_info":
            prio = {i.get("key"): i.get("value") for i in (d.get("prioritisation") or {}).get("items") or []}
            locs = sorted({x.get("location") for x in d.get("subcellularLocations") or []} - {None})
            lines.append(f"  essential: {d.get('isEssential')}; safety liabilities: {len(d.get('safetyLiabilities') or [])}")
            lines.append(f"  prioritisation: {prio or 'none'}")
            lines.append(f"  locations: {', '.join(locs[:8]) or 'none'}")
            tract = [f"{t.get('modality')}:{t.get('label')}" for t in d.get("tractability") or [] if t.get("value")]
            lines.append(f"  tractability (true): {', '.join(tract[:8]) or 'none'}")
    return "\n".join(lines)

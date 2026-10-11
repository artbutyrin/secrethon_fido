"""SQLite storage. Standard library only; one file, WAL mode so the API can read while a run writes.

Tables:
  runs    one analysis: inputs, normalized entities, status
  raw     what Open Targets returned and the trial labels (for drill-down and reruns)
  claims  every claim with its rule and sources; human evidence is added here too (step 7)
  scores  every verdict version of a run; a new version is added, old ones are kept
  reports the memo for a verdict version (status generating | ready | error)
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "unobio.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  disease_input TEXT, target_input TEXT, disease_id TEXT, target_id TEXT, phase TEXT, route TEXT,
  status TEXT NOT NULL, message TEXT, ot_release TEXT, llm_model TEXT, normalized TEXT,
  market_input TEXT, round_terms TEXT, license_terms TEXT
);
CREATE TABLE IF NOT EXISTS raw (
  run_id TEXT PRIMARY KEY REFERENCES runs(id), collected TEXT, trials TEXT, labels TEXT
);
CREATE TABLE IF NOT EXISTS claims (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), n INTEGER NOT NULL,
  fact TEXT NOT NULL, value TEXT NOT NULL, origin TEXT NOT NULL, evidence_type TEXT NOT NULL,
  statement TEXT NOT NULL, rule TEXT, sources TEXT NOT NULL, quote TEXT, verified INTEGER, confirmed INTEGER,
  doc_ids TEXT, added_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS claims_run ON claims(run_id, n);
CREATE TABLE IF NOT EXISTS reports (
  run_id TEXT NOT NULL REFERENCES runs(id), version INTEGER NOT NULL, status TEXT NOT NULL,
  payload TEXT, error TEXT, created_at TEXT NOT NULL, PRIMARY KEY (run_id, version)
);
CREATE TABLE IF NOT EXISTS scores (
  run_id TEXT NOT NULL REFERENCES runs(id), version INTEGER NOT NULL, trigger TEXT NOT NULL,
  payload TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (run_id, version)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    migrate(con)
    return con


RUN_JSON = ("normalized", "market_input", "round_terms", "license_terms", "incomplete")
ADDED_COLUMNS = {"runs": ("market_input", "round_terms", "license_terms",   # step 10: economics inputs
                          "incomplete")}                                       # 2.4: sources that failed


def migrate(con) -> None:
    """Adds columns introduced after a database was created (SQLite has no ADD COLUMN IF NOT EXISTS)."""
    for table, cols in ADDED_COLUMNS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for col in cols:
            if col not in have:
                with con:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")


def close_interrupted(con, older_than_min: int = 15) -> int:
    """Runs left in queued / running by a stopped process (Ctrl+C, crash, reload) end as `error`, so they never hang.
    Only runs not updated for `older_than_min` minutes, so a batch running in another process is left alone."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=older_than_min)).isoformat(timespec="seconds")
    with con:
        cur = con.execute("UPDATE runs SET status = 'error', message = 'interrupted: the process stopped during the run; "
                          "start it again', updated_at = ? WHERE status IN ('queued', 'running') AND updated_at < ?",
                          (now(), cutoff))
    return cur.rowcount


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _row(row: sqlite3.Row | None, json_cols: tuple[str, ...] = ()) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for col in json_cols:
        if out.get(col) is not None:
            out[col] = json.loads(out[col])
    return out


# --- runs -----------------------------------------------------------------------------------------------------------
def create_run(con, *, disease: str | None, target: str | None, disease_id: str | None, target_id: str | None,
               phase: str | None, route: str | None, market: dict | None = None, round_terms: dict | None = None,
               license_terms: dict | None = None) -> str:
    run_id = "run_" + uuid.uuid4().hex[:10]
    t = now()
    opt = lambda v: _j(v) if v else None  # noqa: E731
    with con:
        con.execute("INSERT INTO runs (id, created_at, updated_at, disease_input, target_input, disease_id, target_id,"
                    " phase, route, status, market_input, round_terms, license_terms)"
                    " VALUES (?,?,?,?,?,?,?,?,?, 'queued',?,?,?)",
                    (run_id, t, t, disease, target, disease_id, target_id, phase, route, opt(market),
                     opt(round_terms), opt(license_terms)))
    return run_id


def update_run(con, run_id: str, **fields) -> None:
    for col in RUN_JSON:
        if col in fields and fields[col] is not None:
            fields[col] = _j(fields[col])
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with con:
        con.execute(f"UPDATE runs SET {cols} WHERE id = ?", (*fields.values(), run_id))


def get_run(con, run_id: str) -> dict | None:
    return _row(con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone(), RUN_JSON)


def list_runs(con, limit: int = 50) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT id, created_at, disease_input, target_input, disease_id, target_id, status FROM runs "
        "ORDER BY created_at DESC LIMIT ?", (limit,))]


# --- raw --------------------------------------------------------------------------------------------------------------
def save_raw(con, run_id: str, collected: dict, trials: list, labels: dict) -> None:
    with con:
        con.execute("INSERT OR REPLACE INTO raw (run_id, collected, trials, labels) VALUES (?,?,?,?)",
                    (run_id, _j(collected), _j(trials), _j(labels)))


def get_raw(con, run_id: str) -> dict | None:
    return _row(con.execute("SELECT * FROM raw WHERE run_id = ?", (run_id,)).fetchone(),
                ("collected", "trials", "labels"))


# --- claims -----------------------------------------------------------------------------------------------------------
CLAIM_JSON = ("value", "sources", "doc_ids")


def claim_id(run_id: str, n: int) -> str:
    return f"clm_{run_id.removeprefix('run_')}_{n}"


def add_claims(con, run_id: str, claims: list[dict], added_by: str = "pipeline") -> list[dict]:
    """Stores claims with run-unique IDs (clm_<run>_<n>); returns them with the stored IDs."""
    start = con.execute("SELECT COALESCE(MAX(n), 0) FROM claims WHERE run_id = ?", (run_id,)).fetchone()[0]
    out = []
    with con:
        for i, c in enumerate(claims, start + 1):
            stored = {**c, "id": claim_id(run_id, i)}
            con.execute("INSERT INTO claims (id, run_id, n, fact, value, origin, evidence_type, statement, rule, sources,"
                        " quote, verified, confirmed, doc_ids, added_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (stored["id"], run_id, i, c["fact"], _j(c["value"]), c["origin"], c.get("evidence_type", "source"),
                         c["statement"], c.get("rule"), _j(c.get("sources") or []), c.get("quote"),
                         None if c.get("verified") is None else int(c["verified"]),
                         None if c.get("confirmed") is None else int(c["confirmed"]),
                         _j(c.get("doc_ids")) if c.get("doc_ids") is not None else None, added_by, now()))
            out.append(stored)
    return out


def _claim(row) -> dict:
    c = _row(row, CLAIM_JSON)
    for k in ("verified", "confirmed"):
        if c[k] is not None:
            c[k] = bool(c[k])
    return c


def get_claims(con, run_id: str) -> list[dict]:
    return [_claim(r) for r in con.execute("SELECT * FROM claims WHERE run_id = ? ORDER BY n", (run_id,))]


def get_claim(con, cid: str) -> dict | None:
    row = con.execute("SELECT * FROM claims WHERE id = ?", (cid,)).fetchone()
    return _claim(row) if row else None


def set_confirmed(con, cid: str) -> None:
    with con:
        con.execute("UPDATE claims SET confirmed = 1 WHERE id = ?", (cid,))


# --- scores -----------------------------------------------------------------------------------------------------------
def add_score(con, run_id: str, payload: dict, trigger: str) -> int:
    version = con.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM scores WHERE run_id = ?", (run_id,)).fetchone()[0]
    with con:
        con.execute("INSERT INTO scores (run_id, version, trigger, payload, created_at) VALUES (?,?,?,?,?)",
                    (run_id, version, trigger, _j(payload), now()))
    return version


def get_score(con, run_id: str, version: int | None = None) -> dict | None:
    if version is None:
        row = con.execute("SELECT * FROM scores WHERE run_id = ? ORDER BY version DESC LIMIT 1", (run_id,)).fetchone()
    else:
        row = con.execute("SELECT * FROM scores WHERE run_id = ? AND version = ?", (run_id, version)).fetchone()
    return _row(row, ("payload",))


def list_scores(con, run_id: str) -> list[dict]:
    return [_row(r, ("payload",)) for r in con.execute("SELECT * FROM scores WHERE run_id = ? ORDER BY version",
                                                        (run_id,))]


# --- reports ----------------------------------------------------------------------------------------------------------
def set_report(con, run_id: str, version: int, status: str, payload: dict | None = None, error: str | None = None):
    with con:
        con.execute("INSERT OR REPLACE INTO reports (run_id, version, status, payload, error, created_at) "
                    "VALUES (?,?,?,?,?,?)", (run_id, version, status, _j(payload) if payload else None, error, now()))


def get_report(con, run_id: str, version: int | None = None) -> dict | None:
    if version is None:
        row = con.execute("SELECT * FROM reports WHERE run_id = ? ORDER BY version DESC LIMIT 1", (run_id,)).fetchone()
    else:
        row = con.execute("SELECT * FROM reports WHERE run_id = ? AND version = ?", (run_id, version)).fetchone()
    return _row(row, ("payload",))

"""HTTP API (FastAPI). Run:  uvicorn app.api:app --reload   (from backend/), then open /docs.

POST /runs starts an analysis in the background and returns its ID at once; GET /runs/{id} shows the status.
Each stage is stored in SQLite (app/db.py), so every verdict can be traced to claims and their sources.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.scorer import FactError, fact_catalog

from backend.app import db
from backend.app.evidence import EvidenceError, diff, human_claim
from backend.app.llm import LLMError, OpenAILLM
from backend.app.market import CMS, collect_market
from backend.app.opentargets import OpenTargets
from backend.app.pipeline import CFG, analyze, score_claims
from backend.app.report import build_report, to_markdown
from backend.app.sources import Sources

DB_FILE = Path(os.environ.get("UNOBIO_DB", db.DB_PATH))

@asynccontextmanager
async def lifespan(_app):
    """On start: runs left queued / running by a stopped process end as `error: interrupted`."""
    c = db.connect(DB_FILE)
    try:
        db.close_interrupted(c)
    finally:
        c.close()
    yield


app = FastAPI(title="unobio", version="0.8.0", lifespan=lifespan,
              description="Disease + target -> evidence-backed investment verdict (Invest / Conditional / Insufficient evidence / Do Not Invest).")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def con():
    return db.connect(DB_FILE)


def get_con():
    """One connection per request, closed afterwards."""
    c = con()
    try:
        yield c
    finally:
        c.close()


def make_ot() -> OpenTargets:
    """UNOBIO_OFFLINE=1: cache only, like the other sources (tests, offline batch replays)."""
    return OpenTargets(offline=os.environ.get("UNOBIO_OFFLINE", "") not in ("", "0", "false"))


def make_sources() -> Sources:
    """openFDA, UniProt, PubMed always; AACT when AACT_DSN is set. UNOBIO_OFFLINE=1: cache only."""
    return Sources.from_env()


def make_cms():
    """CMS Medicare spending (price analogues). UNOBIO_OFFLINE=1: cache only."""
    return CMS.from_env()


def score_run(run: dict, claims: list[dict], collected: dict | None) -> dict:
    """Scores claims with the run's economics inputs: the market collected at run time, what a person entered,
    the round and licence terms."""
    payload = score_claims(claims, market_data=(collected or {}).get("market"), market=run.get("market_input"),
                           round_terms=run.get("round_terms"), license_terms=run.get("license_terms"))
    # 2.4: sources that failed in this run travel with every verdict version, so a verdict on missing data is never
    # read as a verdict on the evidence
    payload["incomplete"] = list((collected or {}).get("incomplete") or [])
    return payload


def failed_sources(out: dict) -> list[str]:
    """2.4: sources whose failure can change the verdict: Open Targets queries and translation sources that failed
    (not the ones skipped by configuration, such as AACT without a DSN)."""
    failed = [f"Open Targets {n}: {p.get('error', '')[:160]}" for n, p in out["collected"]["parts"].items()
              if not p["ok"]]
    failed += [s for s in out.get("sources_status") or [] if ": failed" in s]
    return failed


def make_llm():
    """The LLM if a key is configured, otherwise None. 2.6: UNOBIO_NO_LLM=1 turns it off even with a key (no paid
    request at all; stop reasons and trial outcomes then come from rules.py)."""
    import os
    from backend.app.llm import load_env
    load_env()                                            # so UNOBIO_NO_LLM=1 in backend/.env works too
    if os.environ.get("UNOBIO_NO_LLM", "").strip().lower() in ("1", "true", "yes"):
        return None
    llm = OpenAILLM()
    return llm if llm.ready else None


# --- models ---------------------------------------------------------------------------------------------------------
class MarketIn(BaseModel):
    """Market numbers a person enters; each wins over Orphanet / CMS and is tagged "user" in the memo. All optional:
    without us_patients (entered or from Orphanet) the economics do not run."""
    model_config = ConfigDict(extra="forbid")
    us_patients: int | None = Field(None, gt=0, examples=[41000], description="Patients alive in the US with the disease")
    us_patients_range: list[int] | None = Field(None, min_length=2, max_length=2, description="[low, high]")
    eligible_share: float | None = Field(None, gt=0, le=1, description="Share of patients the drug is for (subgroup)")
    diagnosis_rate: float | None = Field(None, gt=0, le=1)
    treatment_rate: float | None = Field(None, gt=0, le=1)
    compliance: float | None = Field(None, gt=0, le=1)
    annual_net_price_usd: float | None = Field(None, gt=0, examples=[220000])
    price_range: list[float] | None = Field(None, min_length=2, max_length=2)
    price_ceiling_usd: float | None = Field(None, gt=0)
    peak_share: float | None = Field(None, gt=0, le=1)
    years_to_peak: float | None = Field(None, gt=0, le=15)
    exclusivity_years_after_launch: float | None = Field(None, ge=0, le=25)
    discount_rate: float | None = Field(None, gt=0, lt=1)
    qaly_gain_per_year: float | None = Field(None, gt=0, le=1)


class RoundIn(BaseModel):
    """The financing round being underwritten. Giving it makes the question "invest in this round" (Invest then needs
    data on the asset itself), rather than "is the thesis investable"."""
    model_config = ConfigDict(extra="forbid")
    pre_money_m: float | None = Field(None, gt=0, examples=[120])
    investment_m: float | None = Field(None, gt=0, examples=[40])
    cash_m: float | None = Field(None, ge=0, description="Company cash after the round, $m (runway check)")
    dilution_to_exit: float | None = Field(None, ge=0, lt=1, examples=[0.4])


class LicenseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upfront_m: float = Field(0.0, ge=0)
    milestones_m: dict[Literal["ph1", "ph2", "ph3", "filed", "approval"], float] = Field(default_factory=dict)
    royalty_pct: float = Field(0.0, ge=0, le=50)


def _clean(model: BaseModel | None) -> dict | None:
    return {k: v for k, v in model.model_dump().items() if v not in (None, {}, [])} or None if model else None


class RunIn(BaseModel):
    disease: str | None = Field(None, examples=["Alzheimer disease"])
    target: str | None = Field(None, examples=["BACE1 inhibitor"], description="Target or mechanism text")
    disease_id: str | None = Field(None, description="Open Targets disease ID, e.g. after an ambiguous result")
    target_id: str | None = Field(None, description="Ensembl gene ID")
    phase: Literal["preclinical", "ph1", "ph2", "ph3", "filed"] | None = None
    route: Literal["oral", "subcutaneous", "iv_infusion", "intrathecal", "inhaled", "topical", "other"] | None = None
    market: MarketIn | None = None
    round_terms: RoundIn | None = None
    license_terms: LicenseIn | None = None

    @model_validator(mode="after")
    def need_both(self):
        if not (self.disease or self.disease_id) or not (self.target or self.target_id):
            raise ValueError("give a disease (text or disease_id) and a target (text or target_id)")
        return self


class EvidenceIn(BaseModel):
    """Either add a new piece of evidence, or confirm an LLM claim that waits for a second source."""
    action: Literal["add", "confirm"]
    claim_id: str | None = Field(None, description="confirm: the claim to confirm")
    fact: str | None = Field(None, examples=["differentiation_claim"], description="add: a fact from GET /facts")
    value: bool | int | float | str | None = Field(None, examples=["efficacy"])
    source_url: str | None = Field(None, examples=["https://clinicaltrials.gov/study/NCT00000000"])
    source_text: str | None = Field(None, description="add: where it comes from, if there is no URL")
    statement: str | None = Field(None, description="add: one sentence; generated if empty")
    author: str | None = Field(None, examples=["analyst"])

    @model_validator(mode="after")
    def need_fields(self):
        if self.action == "confirm" and not self.claim_id:
            raise ValueError("confirm needs claim_id")
        if self.action == "add" and (self.fact is None or self.value is None):
            raise ValueError("add needs fact and value")
        return self


class ReviseSectionIn(BaseModel):
    """One passage the reader currently sees. The model may quote only from this text."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    title: str = ""
    text: str = Field(max_length=8000)


class ReviseIn(BaseModel):
    """A wording request. Nothing is stored: the client applies the quote only after Approve."""
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1, max_length=2000)
    sections: list[ReviseSectionIn] = Field(min_length=1, max_length=12)


REVISE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "section_id": {"type": "string"},
        "before": {"type": "string"},
        "after": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["section_id", "before", "after", "note"],
}

REVISE_SYSTEM = (
    "You propose one small wording edit to an investment memo the reader already sees. "
    "before must be copied exactly from a single section, including punctuation. "
    "after replaces only that span. "
    "Do not invent numbers, study names, citations, drug facts, or sources that are not already in the memo. "
    "Keep an existing citation marker such as [1] when it stays attached to the same sentence. "
    "If the instruction is unclear, or it asks for a fact the memo does not contain, "
    "leave before and after as empty strings and ask one short question in note. "
    "note is one sentence: what changed, or that question."
)


# --- the background job -------------------------------------------------------------------------------------------------
def execute(run_id: str) -> None:
    c = con()
    r = db.get_run(c, run_id)
    db.update_run(c, run_id, status="running")
    try:
        llm = make_llm()
        out = analyze(make_ot(), r["disease_input"], r["target_input"], disease_id=r["disease_id"],
                      target_id=r["target_id"], phase=r["phase"], route=r["route"], llm=llm, sources=make_sources())
        norm = out["normalized"]
        if out["status"] != "analyzed":
            msgs = [f"{k}: {norm[k].get('message')}" for k in ("disease", "target") if norm[k]["status"] != "resolved"]
            db.update_run(c, run_id, status=out["status"], normalized=norm, ot_release=norm.get("ot_release"),
                          message="; ".join(m for m in msgs if m))
            return
        stored = db.add_claims(c, run_id, out["claims"])
        collected = out["collected"]
        collected.setdefault("translation", {}).update(findings=out["findings"], chain=out["chain"])
        collected["log"] = {**out["log"], "llm": out["llm"]["calls"]}
        collected["market"] = collect_market(norm, stored, make_cms())
        collected["incomplete"] = failed_sources(out)
        db.save_raw(c, run_id, collected, out["trials"], out["labels"])
        db.add_score(c, run_id, score_run(r, stored, collected), trigger="pipeline")
        failed = [n for n, p in out["collected"]["parts"].items() if not p["ok"]]
        notes = ([f"failed Open Targets queries: {', '.join(failed)}"] if failed else []) + \
                ([] if llm else ["no LLM key: trial stop reasons and translation documents not read"]) + \
                out["sources_status"] + out["labels"]["errors"] + collected["market"]["notes"]
        db.update_run(c, run_id, status="done", normalized=norm, ot_release=norm.get("ot_release"),
                      disease_id=norm["disease"]["id"], target_id=norm["target"]["id"],
                      llm_model=out["llm"]["model"], message="; ".join(notes) or None,
                      incomplete=collected["incomplete"] or None)
        make_report(run_id, 1)
    except Exception as exc:                              # a run must end in a state, never hang in "running"
        db.update_run(c, run_id, status="error", message=f"{type(exc).__name__}: {exc}")
    finally:
        c.close()


def make_report(run_id: str, version: int) -> None:
    """Writes the memo for one verdict version. Runs in the background; never raises."""
    c = con()
    try:
        db.set_report(c, run_id, version, "generating")
        score = db.get_score(c, run_id, version)
        raw = db.get_raw(c, run_id) or {}
        chain = ((raw.get("collected") or {}).get("translation") or {}).get("chain")
        mechanism = (raw.get("collected") or {}).get("mechanism")
        report = build_report(db.get_run(c, run_id), db.get_claims(c, run_id), score, claim_status(score), make_llm(),
                              chain=chain, mechanism=mechanism)
        db.set_report(c, run_id, version, "ready", report)
    except Exception as exc:
        db.set_report(c, run_id, version, "error", error=f"{type(exc).__name__}: {exc}")
    finally:
        c.close()


# --- helpers ------------------------------------------------------------------------------------------------------------
def claim_status(score: dict | None) -> dict[str, str]:
    """claim ID -> used | pending | rejected | conflict | not_used (an older or weaker claim for the same fact)."""
    if not score:
        return {}
    p = score["payload"]
    out = {cid: "used" for ids in p["used"].values() for cid in ids}
    out.update({cid: "pending" for x in p["pending"] for cid in x["claims"]})
    out.update({x["claim"]: "rejected" for x in p["rejected"]})
    out.update({cid: "conflict" for x in p["conflicts"] for cid in x["claims"]})
    return out


def need_run(c, run_id: str) -> dict:
    r = db.get_run(c, run_id)
    if r is None:
        raise HTTPException(404, f"no run {run_id}")
    return r


def verdict_summary(score: dict | None) -> dict | None:
    if not score:
        return None
    res = score["payload"]["result"]
    return {"version": score["version"], "trigger": score["trigger"], "decision": res["verdict"]["decision"],
            "grounds": res["verdict"]["grounds"], "grounds_text": res["verdict"]["grounds_text"],
            "reason": res["verdict"]["reason"], "pluses": res["score"]["pos"], "minuses": res["score"]["neg"],
            "coverage": res["score"]["coverage"], "scorecard": res["scorecard"], "rules": res["rules"],
            "conditions": res["verdict"]["conditions"], "pending": score["payload"]["pending"],
            "rejected": score["payload"]["rejected"], "conflicts": score["payload"]["conflicts"],
            "complete": not score["payload"].get("incomplete"),
            "incomplete_sources": score["payload"].get("incomplete") or [],
            "insufficient": _insufficient(res, score["payload"])}


def _insufficient(res: dict, payload: dict) -> dict | None:
    """2.4: the scorer's Insufficient-evidence detail, with "incomplete_run" first when sources failed."""
    det = res["verdict"].get("insufficient")
    if det is None:
        return None
    kinds = (["incomplete_run"] if payload.get("incomplete") else []) + list(det.get("kinds") or [])
    return {**det, "kinds": kinds}


# --- endpoints ----------------------------------------------------------------------------------------------------------
@app.get("/health")
def health() -> dict[str, Any]:
    llm = OpenAILLM()
    return {"status": "ok", "scorer_version": CFG.raw["version"], "scorer_sha256": CFG.sha256,
            "llm": {"provider": llm.provider, "model": llm.model, "key_set": bool(llm.api_key),
                    "ready": llm.ready, "missing": llm.missing()}}


@app.post("/runs", status_code=202)
def create_run(body: RunIn, background: BackgroundTasks, c=Depends(get_con)) -> dict[str, str]:
    run_id = db.create_run(c, disease=body.disease, target=body.target, disease_id=body.disease_id,
                           target_id=body.target_id, phase=body.phase, route=body.route, market=_clean(body.market),
                           round_terms=_clean(body.round_terms), license_terms=_clean(body.license_terms))
    background.add_task(execute, run_id)
    return {"run_id": run_id, "status": "queued"}


@app.get("/runs")
def list_runs(limit: int = 50, c=Depends(get_con)) -> list[dict]:
    out = []
    for r in db.list_runs(c, limit):
        s = verdict_summary(db.get_score(c, r["id"]))
        out.append({**r, "decision": s["decision"] if s else None})
    return out


@app.get("/runs/{run_id}")
def get_run(run_id: str, c=Depends(get_con)) -> dict[str, Any]:
    r = need_run(c, run_id)
    norm = r.pop("normalized") or {}
    r["market"] = r.pop("market_input", None)
    r["complete"] = not r.get("incomplete")
    return {**r, "disease": norm.get("disease"), "target": norm.get("target"),
            "verdict": verdict_summary(db.get_score(c, run_id))}


@app.get("/runs/{run_id}/claims")
def run_claims(run_id: str, fact: str | None = None, origin: str | None = None, c=Depends(get_con)) -> list[dict]:
    need_run(c, run_id)
    status = claim_status(db.get_score(c, run_id))
    return [{**x, "status": status.get(x["id"], "not_used")} for x in db.get_claims(c, run_id)
            if (fact is None or x["fact"] == fact) and (origin is None or x["origin"] == origin)]


@app.get("/claims/{claim_id}")
def get_claim(claim_id: str, c=Depends(get_con)) -> dict[str, Any]:
    x = db.get_claim(c, claim_id)
    if x is None:
        raise HTTPException(404, f"no claim {claim_id}")
    spec = CFG.facts[x["fact"]]
    status = claim_status(db.get_score(c, x["run_id"])).get(claim_id, "not_used")
    return {**x, "status": status, "fact_label": spec["label"], "fact_level": spec["scope"]}


@app.get("/runs/{run_id}/result")
def run_result(run_id: str, version: int | None = None, c=Depends(get_con)) -> dict[str, Any]:
    """The scorer's full output for the latest (or a given) version: scorecard, rules, what would change, DD questions."""
    need_run(c, run_id)
    s = db.get_score(c, run_id, version)
    if s is None:
        raise HTTPException(404, "no verdict yet")
    return {"version": s["version"], "trigger": s["trigger"], "created_at": s["created_at"], **s["payload"]}


@app.get("/runs/{run_id}/trials")
def run_trials(run_id: str, c=Depends(get_con)) -> dict[str, Any]:
    """Stopped trials found for the run and the LLM labels with their quotes."""
    need_run(c, run_id)
    raw = db.get_raw(c, run_id)
    if raw is None:
        raise HTTPException(404, "no data yet")
    return {"trials": raw["trials"], "labels": raw["labels"]}


@app.get("/runs/{run_id}/translation")
def run_translation(run_id: str, c=Depends(get_con)) -> dict[str, Any]:
    """The translation chain: same-mechanism drugs, what each source returned (status), the LLM findings with quotes
    and checks, and per link which drugs showed it, did not, or only registered it as a trial outcome."""
    need_run(c, run_id)
    raw = db.get_raw(c, run_id)
    if raw is None:
        raise HTTPException(404, "no data yet")
    tr = (raw["collected"] or {}).get("translation") or {}
    status = {name: {k: v for k, v in part.items() if k != "data"} for name, part in (tr.get("parts") or {}).items()}
    return {"drugs": tr.get("drugs") or [], "sources": status, "findings": tr.get("findings") or [],
            "chain": tr.get("chain") or {}}


@app.get("/runs/{run_id}/log")
def run_log(run_id: str, c=Depends(get_con)) -> dict[str, Any]:
    """Every external call of the run: Open Targets queries, other sources, LLM calls with tokens and latency."""
    need_run(c, run_id)
    raw = db.get_raw(c, run_id)
    if raw is None:
        raise HTTPException(404, "no data yet")
    log = (raw["collected"] or {}).get("log") or {}
    llm = log.get("llm") or []
    memo_calls = []
    for (v,) in c.execute("SELECT version FROM reports WHERE run_id = ? ORDER BY version", (run_id,)).fetchall():
        rep = db.get_report(c, run_id, v)
        payload = (rep or {}).get("payload") or {}
        memo_calls += [{**x, "verdict_version": v} for x in (payload.get("llm") or {}).get("calls") or []]
    return {**log, "llm_memo": memo_calls,
            "llm_tokens": {"input": sum(x.get("input_tokens") or 0 for x in llm if not x.get("cache")),
                           "output": sum(x.get("output_tokens") or 0 for x in llm if not x.get("cache"))},
            "cost": run_cost(llm + memo_calls)}


def run_cost(calls: list[dict]) -> dict[str, Any]:
    """Approximate LLM cost of a run. Prices per million tokens come from UNOBIO_PRICE_IN_PER_M and
    UNOBIO_PRICE_OUT_PER_M (set them to your gateway's prices). `first_run_usd` counts every call as if uncached
    (what a new pair costs); `this_run_usd` counts only calls that went to the model. Open Targets, openFDA,
    UniProt, PubMed, CMS and ClinicalTrials.gov are free."""
    def price(name: str) -> float | None:
        try:
            return float(os.environ[name])
        except (KeyError, ValueError):
            return None
    p_in, p_out = price("UNOBIO_PRICE_IN_PER_M"), price("UNOBIO_PRICE_OUT_PER_M")
    tin = sum(x.get("input_tokens") or 0 for x in calls)
    tout = sum(x.get("output_tokens") or 0 for x in calls)
    live = [x for x in calls if not x.get("cache")]
    lin = sum(x.get("input_tokens") or 0 for x in live)
    lout = sum(x.get("output_tokens") or 0 for x in live)
    out: dict[str, Any] = {"llm_calls": len(calls), "llm_calls_live": len(live),
                           "llm_errors": sum(1 for x in calls if x.get("error")), "input_tokens": tin,
                           "output_tokens": tout, "price_in_per_m": p_in, "price_out_per_m": p_out}
    if p_in is None or p_out is None:
        out["note"] = "set UNOBIO_PRICE_IN_PER_M and UNOBIO_PRICE_OUT_PER_M to get USD"
    else:
        out["first_run_usd"] = round((tin * p_in + tout * p_out) / 1e6, 4)
        out["this_run_usd"] = round((lin * p_in + lout * p_out) / 1e6, 4)
    return out


@app.get("/facts")
def facts() -> list[dict]:
    """Every fact the scorer accepts: label, type, allowed values, level, due-diligence question. For evidence forms."""
    return [{"fact": name, **entry} for name, entry in fact_catalog(CFG).items()]


@app.post("/runs/{run_id}/evidence")
def add_evidence(run_id: str, body: EvidenceIn, background: BackgroundTasks, c=Depends(get_con)) -> dict[str, Any]:
    """Adds human evidence or confirms an LLM claim, rescores, and returns the new verdict with "before -> after".
    The memo for the new version is written in the background (GET /runs/{id}/report).

    Nothing is stored if the evidence is invalid or contradicts other facts (422).
    """
    run = need_run(c, run_id)
    before = db.get_score(c, run_id)
    if run["status"] != "done" or before is None:
        raise HTTPException(409, f"run is {run['status']}; evidence can be added once it is done")
    claims = db.get_claims(c, run_id)

    if body.action == "confirm":
        target = next((x for x in claims if x["id"] == body.claim_id), None)
        if target is None:
            raise HTTPException(404, f"no claim {body.claim_id} in {run_id}")
        if target["origin"] != "llm":
            raise HTTPException(400, "only LLM claims need confirmation; add new evidence to change other facts")
        if target["confirmed"]:
            raise HTTPException(409, f"{body.claim_id} is already confirmed")
        db.set_confirmed(c, body.claim_id)
        trigger, evidence = f"confirm:{body.claim_id}", {"action": "confirm", "claim_id": body.claim_id,
                                                          "author": body.author}
    else:
        try:
            new = human_claim(CFG, body.fact, body.value, source_url=body.source_url, source_text=body.source_text,
                              statement=body.statement, author=body.author)
            score_claims(claims + [{**new, "id": "candidate"}])          # contradiction check before storing (no economics)
        except (EvidenceError, FactError) as exc:
            raise HTTPException(422, str(exc)) from exc
        stored = db.add_claims(c, run_id, [new], added_by=body.author or "human")[0]
        trigger, evidence = f"add:{stored['id']}", {"action": "add", "claim_id": stored["id"], "fact": body.fact,
                                                     "value": body.value, "author": body.author}

    after = score_run(run, db.get_claims(c, run_id), (db.get_raw(c, run_id) or {}).get("collected"))
    change = diff(before["payload"], after)
    version = db.add_score(c, run_id, {**after, "evidence": evidence, "change": change}, trigger=trigger)
    background.add_task(make_report, run_id, version)                 # the memo for the new version
    return {"version": version, "evidence": evidence, "change": change,
            "verdict": verdict_summary(db.get_score(c, run_id, version))}


@app.get("/runs/{run_id}/history")
def history(run_id: str, c=Depends(get_con)) -> list[dict]:
    """Every verdict version, oldest first, with what triggered it and what changed."""
    need_run(c, run_id)
    out = []
    for s in db.list_scores(c, run_id):
        res = s["payload"]["result"]
        out.append({"version": s["version"], "trigger": s["trigger"], "created_at": s["created_at"],
                    "decision": res["verdict"]["decision"], "grounds": res["verdict"]["grounds"],
                    "pluses": res["score"]["pos"], "minuses": res["score"]["neg"],
                    "evidence": s["payload"].get("evidence"), "change": s["payload"].get("change")})
    return out


def _report_or_status(c, run_id: str, version: int | None):
    need_run(c, run_id)
    score = db.get_score(c, run_id, version)
    if score is None:
        raise HTTPException(404, "no verdict yet")
    rep = db.get_report(c, run_id, score["version"])
    if rep is None:
        raise HTTPException(404, f"no report for version {score['version']}; POST /runs/{run_id}/report to write it")
    return rep


@app.get("/runs/{run_id}/report")
def get_report(run_id: str, version: int | None = None, c=Depends(get_con)):
    """The memo (11 sections, each paragraph with kind and claim_ids). 202 while it is being written."""
    rep = _report_or_status(c, run_id, version)
    if rep["status"] != "ready":
        return JSONResponse({"status": rep["status"], "version": rep["version"], "error": rep["error"]},
                            status_code=202 if rep["status"] == "generating" else 500)
    return rep["payload"]


@app.get("/runs/{run_id}/report.md", response_class=PlainTextResponse)
def get_report_markdown(run_id: str, version: int | None = None, c=Depends(get_con)) -> str:
    rep = _report_or_status(c, run_id, version)
    if rep["status"] != "ready":
        raise HTTPException(409, f"report is {rep['status']}")
    return to_markdown(rep["payload"])


@app.post("/runs/{run_id}/revise")
def revise_memo(run_id: str, body: ReviseIn, c=Depends(get_con)) -> dict[str, Any]:
    """Proposes one wording change. Does not rescore and does not write the memo."""
    run = need_run(c, run_id)
    if run["status"] != "done":
        raise HTTPException(409, f"run is {run['status']}; the memo can be edited once it is done")
    llm = OpenAILLM()
    if not llm.ready:
        raise HTTPException(409, llm.missing() or "No language model is configured, so this edit cannot be drafted.")
    catalog = "\n\n".join(f"[{section.id}] {section.title}\n{section.text}" for section in body.sections)
    user = f"Instruction:\n{body.instruction.strip()}\n\nMemo passages:\n\n{catalog}"
    try:
        out = llm.complete_json("revise_memo", REVISE_SYSTEM, user, REVISE_SCHEMA)
    except LLMError as exc:
        raise HTTPException(424, str(exc)) from exc
    section_id = str(out.get("section_id") or "")
    section = next((item for item in body.sections if item.id == section_id), None)
    before = str(out.get("before") or "").strip()
    after = str(out.get("after") or "").strip()
    note = str(out.get("note") or "").strip()
    if before or after:
        if section is None or not before or before not in section.text or before == after:
            raise HTTPException(422, note or "The model did not quote a passage from the memo.")
    return {
        "section_id": section.id if section else "",
        "section_title": section.title if section else "",
        "before": before,
        "after": after,
        "note": note,
    }


@app.post("/runs/{run_id}/report", status_code=202)
def regenerate_report(run_id: str, background: BackgroundTasks, version: int | None = None,
                      c=Depends(get_con)) -> dict[str, Any]:
    """(Re)writes the memo for the latest or a given verdict version, e.g. after an LLM key was added."""
    need_run(c, run_id)
    score = db.get_score(c, run_id, version)
    if score is None:
        raise HTTPException(404, "no verdict yet")
    db.set_report(c, run_id, score["version"], "generating")
    background.add_task(make_report, run_id, score["version"])
    return {"run_id": run_id, "version": score["version"], "status": "generating"}


class InputsIn(BaseModel):
    """New economics inputs for a finished run. A field left out keeps its value; null clears it."""
    model_config = ConfigDict(extra="forbid")
    market: MarketIn | None = None
    round_terms: RoundIn | None = None
    license_terms: LicenseIn | None = None
    author: str | None = None


@app.post("/runs/{run_id}/inputs")
def set_inputs(run_id: str, body: InputsIn, background: BackgroundTasks, c=Depends(get_con)) -> dict[str, Any]:
    """Sets the market numbers, round terms or licence terms and rescores: a new verdict version with "before -> after"
    (for example: the same thesis, asked as a round at a given price). The memo is rewritten in the background."""
    run = need_run(c, run_id)
    before = db.get_score(c, run_id)
    if run["status"] != "done" or before is None:
        raise HTTPException(409, f"run is {run['status']}; inputs can be changed once it is done")
    given = body.model_dump(exclude_unset=True)
    fields = {}
    for key, col in (("market", "market_input"), ("round_terms", "round_terms"), ("license_terms", "license_terms")):
        if key in given:
            fields[col] = _clean(getattr(body, key))
            run[col] = fields[col]
    if not fields:
        raise HTTPException(400, "give market, round_terms or license_terms")
    db.update_run(c, run_id, **fields)
    after = score_run(run, db.get_claims(c, run_id), (db.get_raw(c, run_id) or {}).get("collected"))
    change = diff(before["payload"], after)
    evidence = {"action": "inputs", "fields": [k for k in given if k != "author"], "author": body.author}
    version = db.add_score(c, run_id, {**after, "evidence": evidence, "change": change},
                           trigger="inputs:" + ",".join(evidence["fields"]))
    background.add_task(make_report, run_id, version)
    return {"version": version, "evidence": evidence, "change": change,
            "verdict": verdict_summary(db.get_score(c, run_id, version))}


@app.get("/runs/{run_id}/economics")
def run_economics(run_id: str, version: int | None = None, c=Depends(get_con)) -> dict[str, Any]:
    """The economics of a verdict version: market inputs with their provenance, rNPV, Monte Carlo, scenarios, capital
    to the next milestone, the round view, and whether the economics drive the verdict."""
    need_run(c, run_id)
    s = db.get_score(c, run_id, version)
    if s is None:
        raise HTTPException(404, "no verdict yet")
    p = s["payload"]
    return {"version": s["version"], "question": p.get("question", "thesis"), "market": p.get("market"),
            "economics": p["result"].get("economics"), "economics_note": p["result"].get("economics_note"),
            "caps": p["result"]["verdict"].get("caps") or []}

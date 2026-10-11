"""Runs every test suite and the demo batch, then writes one report to send back for analysis.

Run from the repo root (the folder with main.py):
  python collect_results.py                 # tests + full batch (12 pairs, live: Open Targets, PubMed, LLM...)
  python collect_results.py --only 3        # tests + the first 3 pairs only (faster, cheaper)
  python collect_results.py --sample 15     # tests + a live sample of 15 pairs with a known outcome (Minikel 2024)
  python collect_results.py --sample 15 --mechanisms   # both samples: + 15 pairs with an explicit mechanism
  python collect_results.py --fresh         # move backend/data/llm_cache aside first: real LLM timings, no cache
  python collect_results.py --tests-only    # tests only, no network, no LLM

Output: results/unobio_results_<time>.zip  (results.md + the batch summary). Send that zip.
API keys are never written: values from backend/.env are redacted from every captured output.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "backend" / "data"
SECRET_KEYS = ("TEAM_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "OPENFDA_API_KEY", "NCBI_API_KEY", "AACT_DSN")


def secrets() -> list[str]:
    vals = [os.environ.get(k, "") for k in SECRET_KEYS]
    env = ROOT / "backend" / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            k, _, v = line.partition("=")
            if k.strip() in SECRET_KEYS:
                vals.append(v.split(" #")[0].strip().strip("'\""))
    return [v for v in vals if len(v) >= 6]


def llm_config() -> dict[str, str]:
    """LLM settings from the environment or backend/.env (the environment wins), without secrets."""
    keys = ("UNOBIO_LLM_MAX_TOKENS", "UNOBIO_LLM_INPUT_BUDGET", "UNOBIO_LLM_WORKERS", "UNOBIO_LLM_REASONING")
    out = {k: "" for k in keys}
    env = ROOT / "backend" / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            k, _, v = line.strip().partition("=")
            v = v.split(" #")[0].strip().strip("'\"")
            if k.strip() in out and v and not line.strip().startswith("#"):
                out[k.strip()] = v
    for k in keys:
        out[k] = os.environ.get(k) or out[k]
    return out


def redact(text: str, hidden: list[str]) -> str:
    for v in hidden:
        text = text.replace(v, "***")
    return re.sub(r"(Bearer\s+)\S+", r"\1***", text)


def run(cmd: list[str], timeout: int, env: dict | None = None) -> tuple[int, str, float]:
    started = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})})
        out, code = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as exc:
        out, code = f"{exc.stdout or ''}{exc.stderr or ''}\nTIMEOUT after {timeout} s", -1
    return code, out, time.perf_counter() - started


def tail(text: str, n: int) -> str:
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:])


def run_stats(since: str) -> list[str]:
    """Per run since `since`: wall time, live LLM time by task, errors, registry status, verdict."""
    path = Path(os.environ.get("UNOBIO_DB", DATA / "unobio.db"))
    if not path.exists():
        return ["(no database)"]
    c = sqlite3.connect(path)
    rows = c.execute("select r.id, r.created_at, r.updated_at, r.disease_input, r.target_input, r.status, r.message, "
                     "x.collected from runs r left join raw x on x.run_id = r.id where r.created_at >= ? "
                     "order by r.created_at", (since,)).fetchall()
    out = ["| Pair | Status | Verdict | Wall s | Live LLM calls | LLM s | HTTP 400 | Other LLM errors | Trial registry |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    tasks: dict[str, list] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    extra: list[str] = []                    # NCT lookups and claims waiting for a human, per run
    for rid, ca, ua, dis, tg, status, msg, col in rows:
        wall = (datetime.fromisoformat(ua) - datetime.fromisoformat(ca)).total_seconds()
        verdict = ""
        s = c.execute("select payload from scores where run_id = ? order by version desc limit 1", (rid,)).fetchone()
        if s:
            payload = json.loads(s[0])
            v = payload["result"]["verdict"]
            verdict = f"{v['decision']} ({v['grounds']})"
            for p in payload.get("pending") or []:
                extra.append(f"- {dis} + {tg}: pending `{p['fact']}` = {p.get('value')} -> if confirmed: "
                             f"{p.get('verdict_if_confirmed', '?')}")
        live, n400, nerr, registry = [], 0, 0, "?"
        if col:
            col = json.loads(col)
            live = [x for x in (col.get("log") or {}).get("llm", []) if not x.get("cache")]
            for x in live:
                tasks[x["task"]].append(x)
                if x.get("error"):
                    if "HTTP 400" in x["error"]:
                        n400 += 1
                    else:
                        nerr += 1
                    errors[x["error"][:140]] += 1
            nct = (((col.get("translation") or {}).get("parts") or {}).get("pubmed_nct") or {})
            for q in nct.get("data") or []:
                arts = q.get("articles") or []
                extra.append(f"- {dis} + {tg}: PubMed by {q.get('nct')} ({q.get('drug')}): {len(arts)} abstract(s)"
                             + (f" — {'; '.join((a.get('title') or '')[:70] for a in arts)}" if arts else "")
                             + (f" — error {q['error'][:80]}" if q.get("error") else ""))
            if nct and not nct.get("ok"):
                extra.append(f"- {dis} + {tg}: PubMed by NCT failed: {str(nct.get('error'))[:100]}")
            part = (((col.get("translation") or {}).get("parts") or {}).get("aact") or {})
            data = part.get("data") or []
            via = {r.get("via", "aact") for r in data} if data else set()
            registry = ("skipped" if part.get("skipped") else
                        f"ok, {len(data)} trials {','.join(sorted(via))}" if part.get("ok") else
                        f"error: {str(part.get('error'))[:60]}")
        llm_s = sum((x.get("latency_ms") or 0) for x in live) / 1000
        out.append(f"| {dis} + {tg} | {status} | {verdict} | {wall:.0f} | {len(live)} | {llm_s:.0f} | {n400} | {nerr} "
                   f"| {registry} |")
        if status != "done" and msg:
            out.append(f"|  ↳ message: {msg[:200].replace('|', '/')} | | | | | | | | |")
    out += ["", "LLM by task (live calls only):", "",
            "| Task | Calls | Errors | Median in tok | Median out tok | Median s | Max s |", "| --- | --- | --- | --- | --- | --- | --- |"]
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0  # noqa: E731
    for t, xs in sorted(tasks.items()):
        ok = [x for x in xs if not x.get("error")]
        out.append(f"| {t} | {len(xs)} | {len(xs) - len(ok)} | {med([x.get('input_tokens') or 0 for x in ok])} | "
                   f"{med([x.get('output_tokens') or 0 for x in ok])} | {med([x['latency_ms'] for x in ok]) / 1000:.1f} | "
                   f"{max([x.get('latency_ms') or 0 for x in xs] or [0]) / 1000:.1f} |")
    if errors:
        out += ["", "LLM errors:", ""] + [f"- {n} × {e}" for e, n in sorted(errors.items(), key=lambda kv: -kv[1])]
    out += ["", "PubMed lookups by NCT ID and claims waiting for a human:", ""] + (extra or ["- none"])
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--only", type=int)
    p.add_argument("--fresh", action="store_true")
    p.add_argument("--tests-only", action="store_true")
    p.add_argument("--sample", type=int, help="live sample of N pairs with a known outcome instead of the demo batch")
    p.add_argument("--seed", type=int, default=9)
    p.add_argument("--no-llm", action="store_true",
                   help="2.6: no paid LLM request at all (UNOBIO_NO_LLM=1); rules read stop reasons and abstracts")
    p.add_argument("--mechanisms", action="store_true",
                   help="also run the second sample: 15 pairs with an explicit mechanism (mechanism_pairs.txt)")
    a = p.parse_args()
    if not (ROOT / "main.py").exists():
        sys.exit("Run this from the project folder (the one with main.py).")

    hidden = secrets()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    since = datetime.now(timezone.utc).isoformat(timespec="seconds")
    py = sys.executable
    rep = [f"# unobio results {stamp}", "",
           f"- Python {platform.python_version()} on {platform.system()} {platform.release()} ({platform.machine()})",
           f"- backend/.env present: {(ROOT / 'backend' / '.env').exists()}"]
    cfg = llm_config()
    rep += [f"- LLM settings: max tokens {cfg['UNOBIO_LLM_MAX_TOKENS'] or '16000 (default; set 4096)'}, "
            f"input budget {cfg['UNOBIO_LLM_INPUT_BUDGET'] or '3500 (default)'}, "
            f"workers {cfg['UNOBIO_LLM_WORKERS'] or '4 (default)'}, reasoning {cfg['UNOBIO_LLM_REASONING'] or 'not sent'}", ""]
    if cfg["UNOBIO_LLM_MAX_TOKENS"] and int(cfg["UNOBIO_LLM_MAX_TOKENS"]) > 8192:
        msg = (f"WARNING: UNOBIO_LLM_MAX_TOKENS={cfg['UNOBIO_LLM_MAX_TOKENS']} in backend/.env is above what the "
               "gateway accepts (16000 was refused on 9 October). Set UNOBIO_LLM_MAX_TOKENS=4096.")
        print(msg)
        rep += [f"**{msg}**", ""]

    suites = [("backend", [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--durations=10"]),
              ("unobio_scoring", [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "unobio_scoring/tests"]),
              ("scoring_engine", [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "scoring_engine"])]
    rep += ["## Tests", ""]
    for name, cmd in suites:
        print(f"tests: {name} ...", flush=True)
        code, out, secs = run(cmd, 900)
        last = tail(out, 1)
        print(f"   {last}")
        rep += [f"### {name}: exit {code}, {secs:.0f} s", "", "```", redact(tail(out, 60 if code else 15), hidden), "```", ""]

    out_dirs: list[tuple[str, Path]] = []
    if a.no_llm:
        os.environ["UNOBIO_NO_LLM"] = "1"                  # inherited by every run below
        rep += ["## LLM", "", "Off (--no-llm): stop reasons from Open Targets categories and rules, outcomes from "
                "rules on PubMed abstracts.", ""]
    if not a.tests_only:
        if not a.no_llm:
            print("LLM connection check ...", flush=True)
            code, out, _ = run([py, "-m", "backend.tests.check_llm"], 180)
            rep += ["## LLM check", "", "```", redact(tail(out, 30), hidden), "```", ""]
        if a.fresh and (DATA / "llm_cache").exists():
            moved = DATA / f"llm_cache.old-{stamp}"
            shutil.move(DATA / "llm_cache", moved)
            rep.append(f"LLM cache moved to {moved.name} (fresh answers).\n")
        jobs = []                                      # (title, command, folder its reports go to, zip folder)
        if a.sample:
            jobs.append((f"Live sample ({a.sample} pairs, Minikel 2024)",
                         [py, "-m", "backend.tests.live_sample", "--n", str(a.sample), "--seed", str(a.seed)],
                         DATA / "live_sample", "sample"))
        if a.mechanisms:
            jobs.append(("Mechanism sample (15 pairs with an explicit mechanism)",
                         [py, "-m", "backend.tests.mechanism_sample"], DATA / "mechanism_sample", "mechanisms"))
        if not jobs:
            jobs.append(("Batch", [py, "-m", "backend.tests.run_batch"] + (["--only", str(a.only)] if a.only else []),
                         DATA / "batch", "batch"))
        for title, cmd, runs_dir, zdir in jobs:
            before = set(runs_dir.glob("*")) if runs_dir.exists() else set()
            print(f"{title} (about 1 min a pair; progress below) ...", flush=True)
            started = time.perf_counter()
            proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            lines = []
            for line in proc.stdout:
                print("   " + line.rstrip(), flush=True)
                lines.append(line)
            proc.wait()
            rep += [f"## {title}: exit {proc.returncode}, {time.perf_counter() - started:.0f} s", "", "```",
                    redact("".join(lines)[-12000:], hidden), "```", ""]
            new = sorted(set(runs_dir.glob("*")) - before) if runs_dir.exists() else []
            if new:
                out_dirs.append((zdir, new[-1]))
        rep += ["## Runs: time and LLM", ""] + run_stats(since) + [""]

    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    zpath = out_dir / f"unobio_results_{stamp}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("results.md", "\n".join(rep))
        for zdir, folder in out_dirs:
            for f in folder.iterdir():
                if f.is_file():
                    z.writestr(f"{zdir}/{f.name}", redact(f.read_text(encoding="utf-8", errors="ignore"), hidden))
    print(f"\nDone. Send this file: {zpath}")


if __name__ == "__main__":
    main()

"""Replays a real model's recorded answers (python3 -m backend.tests.eval_llm --record) against the gold cases, offline.

Skipped until the answers are recorded. It is a regression check: BASELINE.json says which gold cases passed when the
answers were recorded. A case that passed then and fails now means a code change broke how real answers are parsed,
quote-checked or support-checked; that fails the test. Cases the model already failed are listed as known failures
(the eval is where you work on them). Changing a prompt makes the recording stale: record again.
"""
from pathlib import Path

import json
import warnings

import pytest

from backend.app.llm import OpenAILLM
from backend.app.support import check_support
from backend.app.translation import extract_findings
from backend.app.trials import label_trials
from backend.tests import llm_gold as gold
from backend.tests.eval_llm import prompts_fingerprint

FIXTURES = Path(__file__).parent / "fixtures" / "llm"

pytestmark = pytest.mark.skipif(not (FIXTURES / "MODEL").exists(),
                                reason="no recorded LLM answers; run python3 -m backend.tests.eval_llm --record")


@pytest.fixture
def recorded():
    recorded_prompts = (FIXTURES / "PROMPTS").read_text().strip() if (FIXTURES / "PROMPTS").exists() else "unknown"
    if recorded_prompts != prompts_fingerprint():
        pytest.fail(f"prompts changed since the recording ({recorded_prompts} -> {prompts_fingerprint()}): "
                    "run python3 -m backend.tests.eval_llm --record")
    # no key: every answer must come from the recording; a miss is an error, never a network call
    return OpenAILLM(api_key="", provider="openai", model=(FIXTURES / "MODEL").read_text().strip(), cache_dir=FIXTURES)


def _explain(rows):
    return "\n".join(f"{r['case']} [{r['tag']}] want {r['want']} got {r['got']}: " + " | ".join(r["trace"])
                     for r in rows)


def _check(key: str, rows: list[dict]) -> None:
    path = FIXTURES / "BASELINE.json"
    baseline = json.loads(path.read_text())[key] if path.exists() else {r["case"]: True for r in rows}
    broke = [r for r in rows if baseline.get(r["case"]) and not r["ok"]]
    known = [r for r in rows if baseline.get(r["case"]) is False and not r["ok"]]
    fixed = [r["case"] for r in rows if baseline.get(r["case"]) is False and r["ok"]]
    if known:
        warnings.warn(f"{key}: {len(known)} known failure(s) of the recorded model:\n{_explain(known)}")
    if fixed:
        warnings.warn(f"{key}: now passing, record again to update the baseline: {fixed}")
    assert not broke, f"{key}: passed when recorded, fails now:\n{_explain(broke)}"


def test_recorded_stop_labels(recorded):
    out = label_trials(recorded, gold.stop_trials())
    assert not out["errors"], out["errors"]
    _check("stops", gold.score_stops(out["labels"]))


def test_recorded_translation_findings(recorded):
    out = extract_findings(recorded, gold.translation_docs(), gold.DISEASE, gold.TARGET, gold.DRUGS)
    assert not out["errors"], out["errors"]
    _check("translation", gold.score_translation(out["findings"]))


def test_recorded_support_checker(recorded):
    out = check_support(recorded, gold.support_items())
    assert not out["errors"], out["errors"]
    _check("support", gold.score_support(out["verdicts"]))

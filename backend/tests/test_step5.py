"""Step 5 tests: trial selection, quote checks, counting, failures. A keyword "LLM" stands in for the real one;
the OpenAI client itself is tested against a mock HTTP server."""
import json
import re
from pathlib import Path

import httpx
import pytest

from backend.app.facts import Claims
from backend.app.llm import LLMError, OpenAILLM
from backend.app.normalize import normalize
from backend.app.opentargets import OpenTargets
from backend.app.pipeline import report_text, run
from backend.app.trials import SCHEMA, label_trials, quote_found, sponsor_key, stopped_trials, trial_claims

LIVE = Path(__file__).parent / "fixtures" / "live"

KEYWORDS = [("efficacy", r"futility|primary endpoint|no evidence of potential efficacy|efficacy"),
            ("safety", r"liver enzymes|adverse event profile|adverse events|safety"),
            ("enrollment", r"recruit\w*|enrol\w*|accrual"),
            ("business", r"business \w+|company closure|decided not to continue")]


class KeywordLLM:
    """Labels by keyword and quotes the matched words, like an honest model would. `lie` adds a made-up quote."""

    def __init__(self, lie=False, fail=False):
        self.lie, self.fail, self.calls, self.model = lie, fail, [], "keyword"

    def complete_json(self, task, system, user, schema):
        if self.fail:
            raise LLMError("rate limited")
        self.calls.append({"task": task, "cache": False})
        if task.startswith("check_"):          # support checks: agree with every item (a missing verdict = unchecked)
            return {"items": [{"id": x["id"], "supports": True} for x in json.loads(user)]}
        if task != "classify_stops":
            return {}                          # translation: no findings
        out = []
        for t in json.loads(user):
            labels = [{"label": lab, "quote": m.group(0)} for lab, rx in KEYWORDS
                      if (m := re.search(rx, t["reason"], re.I))]
            if self.lie:
                labels.append({"label": "safety", "quote": "patients died of liver failure"})
            out.append({"nct": t["nct"], "labels": labels or [{"label": "unknown", "quote": ""}]})
        return {"trials": out}


def live(disease, target, llm):
    ot = OpenTargets(LIVE / "cache", offline=True)
    n = normalize(ot, disease, target)
    collected = json.loads((LIVE / "runs" / f"{n['disease']['id']}__{n['target']['id']}.json").read_text())
    return run(ot, disease, target, collected=collected, llm=llm)


def claim(out, fact):
    return next((c for c in out["claims"] if c["fact"] == fact), None)


# --- real BACE1 trials ------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def bace1():
    return live("Alzheimer disease", "BACE1 inhibitor", KeywordLLM())


def test_stopped_trials_are_found_with_upper_case_ids(bace1):
    same = {t["nct"]: t for t in bace1["trials"] if t["same_mechanism_drugs"]}
    assert {"NCT02569398", "NCT02783573", "NCT02956486"} <= set(same)       # Open Targets sends them lower case
    assert same["NCT02569398"]["same_mechanism_drugs"] == ["ATABECESTAT"]
    assert same["NCT02569398"]["ot_categories"] == ["Negative"]             # Open Targets' own label: wrong here


def test_bace1_failures_and_safety_counted_by_code(bace1):
    eff = claim(bace1, "moa_failures_efficacy_ph23")
    assert eff["value"] == 2 and eff["origin"] == "llm" and eff["verified"]
    assert {s["id"] for s in eff["sources"]} >= {"NCT02783573", "NCT02956486"}       # lanabecestat, elenbecestat
    assert sorted(eff["doc_ids"]) == ["sponsor:astrazeneca", "sponsor:eisai"]
    saf = claim(bace1, "moa_discontinued_safety_count")
    assert saf["value"] == 2                                                # atabecestat (liver), elenbecestat (AEs)
    # scorer 1.3 (review F34): two sponsors read by the same LLM step are not independent; a human confirms
    assert {p["fact"] for p in bace1["score"]["pending"]} == {"moa_failures_efficacy_ph23", "moa_discontinued_safety_count"}
    from backend.app.pipeline import score_claims
    confirmed = [dict(c, confirmed=True) if c["origin"] == "llm" else c for c in bace1["claims"]]
    res = score_claims(confirmed)["result"]
    fired = {r["id"] for r in res["rules"]}
    assert {"one_mechanism_failure", "moa_safety_discontinuations"} <= fired and res["verdict"]["decision"] == "Do Not Invest"


def test_pending_until_a_human_even_with_two_sponsors(bace1):
    c = claim(bace1, "moa_failures_efficacy_ph23")
    assert len(c["doc_ids"]) == 2                                 # two sponsors: no longer enough
    from backend.app.pipeline import score_claims
    others = [x for x in bace1["claims"] if x["fact"] != "moa_failures_efficacy_ph23"]
    assert "moa_failures_efficacy_ph23" in [p["fact"] for p in score_claims(others + [c])["pending"]]
    assert "moa_failures_efficacy_ph23" not in [p["fact"] for p in score_claims(others + [dict(c, confirmed=True)])["pending"]]


def test_a_negated_cause_is_not_a_label():
    """Review F34: "not due to lack of efficacy" names a cause only to deny it; the code filter rejects the label
    even when the model and the support check get it wrong."""
    from backend.app.trials import quote_negated
    yes = lambda t: {"trials": [{"nct": "NCT00000009", "labels": [{"label": "efficacy", "quote": "lack of efficacy"}]}]}  # noqa: E731
    class Gullible:
        calls, model = [], "gullible"
        def complete_json(self, task, system, user, schema):
            if task == "classify_stops":
                return yes(user)
            return {"items": [{"id": x["id"], "supports": True} for x in json.loads(user)]}
    out = label_trials(Gullible(), [{"nct": "NCT00000009", "why_stopped": "Business decision; not due to lack of efficacy."}])
    x = out["labels"]["NCT00000009"][0]
    assert x["negated"] and not x["verified"]
    assert not quote_negated("primary endpoint", "The study did not meet its primary endpoint.")


def test_report_shows_labels_and_open_targets_category(bace1):
    text = report_text(bace1)
    assert "NCT02569398" in text and "Open Targets category: Negative" in text and "quote found" in text


def test_without_llm_nothing_is_counted_from_text():
    out = live("Alzheimer disease", "BACE1 inhibitor", None)
    assert claim(out, "moa_failures_efficacy_ph23") is None and "LLM not used" in report_text(out)


# --- guards -----------------------------------------------------------------------------------------------------------
def test_made_up_quote_is_not_used():
    out = live("Alzheimer disease", "BACE1 inhibitor", KeywordLLM(lie=True))
    fake = [x for labs in out["labels"]["labels"].values() for x in labs if x["quote"] == "patients died of liver failure"]
    assert fake and not any(x["verified"] for x in fake)
    assert claim(out, "moa_discontinued_safety_count")["value"] == 2        # unchanged by the made-up label


def test_llm_failure_keeps_the_run_going():
    out = live("Alzheimer disease", "BACE1 inhibitor", KeywordLLM(fail=True))
    assert out["status"] == "scored" and out["labels"]["errors"] and claim(out, "moa_failures_efficacy_ph23") is None


def test_answers_for_trials_not_asked_about_are_ignored():
    class Extra(KeywordLLM):
        def complete_json(self, *a):
            ans = super().complete_json(*a)
            if "trials" in ans:
                ans["trials"].append({"nct": "NCT99999999", "labels": [{"label": "safety", "quote": "x"}]})
            return ans
    trials = [{"nct": "NCT00000001", "why_stopped": "Stopped for futility."}]
    assert set(label_trials(Extra(), trials)["labels"]) == {"NCT00000001"}


def test_quote_matching():
    text = "An independent assessment concluded the trial was not likely to meet the primary endpoint."
    assert quote_found("not likely to meet the primary endpoint", text)
    assert quote_found("not likely to meet the primary end point", text)     # small typo: fuzzy match
    assert not quote_found("serious adverse events", text) and not quote_found("", text)


def test_sponsor_key():
    assert sponsor_key("Eisai Co., Ltd.") == sponsor_key("Eisai Inc.") == "eisai"
    assert sponsor_key("AstraZeneca") != sponsor_key("Eisai Inc.")


def test_enrollment_rule_needs_five_and_a_third():
    def t(i, why):
        return {"nct": f"NCT{i:08d}", "why_stopped": why, "stage": "PHASE_2", "in_disease": True, "sponsor": f"S{i}",
                "url": "u", "same_mechanism_drugs": [], "ot_categories": []}
    trials = [t(i, "slow enrollment") for i in range(5)] + [t(10 + i, "futility") for i in range(5)]
    c = Claims()
    trial_claims(c, trials, label_trials(KeywordLLM(), trials), {"name": "D"}, {"symbol": "T", "action": None})
    assert [x["fact"] for x in c.items] == ["indication_enrollment_terminations_high"]
    c = Claims()
    few = trials[:4] + trials[5:]
    trial_claims(c, few, label_trials(KeywordLLM(), few), {"name": "D"}, {"symbol": "T", "action": None})
    assert c.items == []


def test_stopped_trials_dedupes_and_marks_disease():
    rep = lambda nct, d: {"id": nct, "trialOverallStatus": "TERMINATED", "trialWhyStopped": "futility",  # noqa: E731
                          "clinicalStage": "PHASE_3", "diseases": [{"disease": {"id": d}}]}
    row = {"drug": {"name": "X SODIUM", "mechanismsOfAction": {"rows": [{"actionType": "INHIBITOR",
                                                                          "targets": [{"id": "T"}]}]}},
           "clinicalReports": [rep("nct00000001", "D9"), rep("NCT00000001", "D9"), rep("nct00000002", "D1")]}
    collected = {"parts": {"target_drugs": {"ok": True, "data": {"rows": [row]}},
                           "disease_drugs": {"ok": True, "data": {"rows": []}}}}
    out = {t["nct"]: t for t in stopped_trials(collected, "D1", "T", "inhibit")}
    assert set(out) == {"NCT00000001", "NCT00000002"} and out["NCT00000002"]["in_disease"]
    assert not out["NCT00000001"]["in_disease"] and out["NCT00000001"]["same_mechanism_drugs"] == ["X"]


# --- OpenAI client ------------------------------------------------------------------------------------------------------
def test_openai_request_shape_cache_and_errors(tmp_path):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"trials": []})},
                                                      "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    llm = OpenAILLM(api_key="k", model="gpt-5-mini", reasoning="low", provider="openai", cache_dir=tmp_path,
                    http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert llm.complete_json("classify_stops", "sys", "user", SCHEMA) == {"trials": []}
    body = seen[0]
    assert body["model"] == "gpt-5-mini" and body["reasoning_effort"] == "low"
    assert body["response_format"]["json_schema"]["strict"] is True and "temperature" not in body
    assert llm.complete_json("classify_stops", "sys", "user", SCHEMA) == {"trials": []} and len(seen) == 1   # cached
    assert llm.calls[0]["input_tokens"] == 10 and llm.calls[1]["cache"] is True

    refusal = lambda r: httpx.Response(200, json={"choices": [{"message": {"refusal": "no"}}]})  # noqa: E731
    bad = OpenAILLM(api_key="k", provider="openai", cache_dir=tmp_path / "x", http=httpx.Client(transport=httpx.MockTransport(refusal)))
    with pytest.raises(LLMError, match="refused"):
        bad.complete_json("t", "s", "u", SCHEMA)
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        OpenAILLM(api_key="", provider="openai", cache_dir=tmp_path / "y").complete_json("t", "s", "u2", SCHEMA)


def test_schema_is_valid_for_strict_mode():
    def walk(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False and set(node["required"]) == set(node["properties"])
            for v in node["properties"].values():
                walk(v)
        if node.get("type") == "array":
            walk(node["items"])
    walk(SCHEMA)


def test_xai_provider_uses_its_url_key_and_no_reasoning(tmp_path, monkeypatch):
    for var in ("OPENAI_API_KEY", "XAI_API_KEY", "UNOBIO_LLM_PROVIDER", "UNOBIO_LLM_MODEL", "UNOBIO_LLM_REASONING"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("backend.app.llm.load_env", lambda *a: None)          # ignore a developer's backend/.env
    monkeypatch.setenv("XAI_API_KEY", "xk")
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {}})

    llm = OpenAILLM(cache_dir=tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert llm.provider == "xai" and llm.model == "grok-4.7"
    llm.complete_json("t", "s", "u", SCHEMA)
    url, auth, body = seen[0]
    assert url == "https://api.x.ai/v1/chat/completions" and auth == "Bearer xk" and "reasoning_effort" not in body
    with pytest.raises(LLMError, match="unknown provider"):
        OpenAILLM(provider="grokk", cache_dir=tmp_path)


# --- the hackathon gateway and servers that reject parameters ------------------------------------------------------------
def test_gateway_is_picked_from_team_key_and_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAM_API_KEY", "tk")
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"trials": []}'}}], "usage": {}})

    no_url = OpenAILLM(cache_dir=tmp_path)
    assert no_url.provider == "gateway" and not no_url.ready and "UNOBIO_LLM_BASE_URL" in no_url.missing()
    monkeypatch.setenv("UNOBIO_LLM_BASE_URL", "https://gateway.example/v1/")
    llm = OpenAILLM(cache_dir=tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert llm.ready and llm.model == "gpt-6-luna"
    llm.complete_json("t", "s", "u", SCHEMA)
    url, auth, body = seen[0]
    assert url == "https://gateway.example/v1/chat/completions" and auth == "Bearer tk"
    assert body["max_completion_tokens"] == 16000 and "reasoning_effort" not in body


def test_rejected_parameters_are_dropped_one_by_one(tmp_path):
    seen = []

    def handler(request):
        b = json.loads(request.content)
        seen.append(b)
        if "reasoning_effort" in b:
            return httpx.Response(400, json={"error": {"message": "Unrecognized request argument: reasoning_effort"}})
        if (b.get("response_format") or {}).get("type") == "json_schema":
            return httpx.Response(400, json={"error": {"message": "response_format json_schema is not supported"}})
        if "response_format" in b:
            return httpx.Response(400, json={"error": {"message": "Invalid parameter: response_format"}})
        assert "follow this JSON schema" in b["messages"][0]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '```json\n{"trials": []}\n```'}}]})

    llm = OpenAILLM(api_key="k", provider="openai", reasoning="low", cache_dir=tmp_path,
                    http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert llm.complete_json("t", "s", "u", SCHEMA) == {"trials": []}          # fenced JSON is parsed
    assert llm.json_mode == "prompt" and llm.reasoning == "" and len(seen) == 4
    llm.complete_json("t", "s", "other", SCHEMA)
    assert len(seen) == 5                                                       # the working shape is remembered


def test_an_unrelated_400_is_reported(tmp_path):
    handler = lambda r: httpx.Response(400, json={"error": {"message": "model gpt-9 does not exist"}})  # noqa: E731
    llm = OpenAILLM(api_key="k", provider="openai", reasoning="", cache_dir=tmp_path,
                    http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMError, match="does not exist"):
        llm.complete_json("t", "s", "u", SCHEMA)


def test_malformed_label_answers_do_not_crash():
    class Messy:
        calls, model = [], "messy"

        def complete_json(self, *a):
            return {"trials": ["junk", {"nct": "nct00000001", "labels": [{"label": "efficacy"}, "x",
                                                                          {"label": "nonsense", "quote": "q"}]}]}
    out = label_trials(Messy(), [{"nct": "NCT00000001", "why_stopped": "futility"}])
    assert out["labels"]["NCT00000001"] == [{"label": "efficacy", "quote": "", "verified": False, "support": None}]

"""Gateway failures must not let unchecked LLM evidence through, and oversized batches are split, not dropped."""
import json

from backend.app.llm import LLMError
from backend.app.support import check_support
from backend.app.trials import label_trials

TOO_BIG = LLMError('HTTP 400: {"error":{"message":"Input exceeds the conservative input limit."}}')


class SmallGateway:
    """Accepts at most `limit` items per support-check request; agrees with every claim."""
    def __init__(self, limit):
        self.limit, self.sizes = limit, []

    def complete_json(self, task, system, user, schema):
        items = json.loads(user)
        if task == "classify_stops":
            return {"trials": [{"nct": t["nct"], "labels": [{"label": "efficacy", "quote": "futility"}]} for t in items]}
        if len(items) > self.limit:
            raise TOO_BIG
        self.sizes.append(len(items))
        return {"items": [{"id": x["id"], "supports": True} for x in items]}


def test_oversized_support_batch_is_split():
    gw = SmallGateway(limit=7)
    got = check_support(gw, [{"id": str(i), "claim": "c", "quote": "q"} for i in range(40)])
    assert len(got["verdicts"]) == 40 and not got["errors"] and max(gw.sizes) <= 7


class BrokenChecker(SmallGateway):
    def complete_json(self, task, system, user, schema):
        if task == "check_stop_labels":
            raise LLMError("HTTP 500")
        return super().complete_json(task, system, user, schema)


def test_failed_support_check_means_not_used():
    out = label_trials(BrokenChecker(limit=99), [{"nct": "NCT00000001", "why_stopped": "Stopped for futility."}])
    x = out["labels"]["NCT00000001"][0]
    assert x["label"] == "efficacy" and x["support"] is None and x["unchecked"] and not x["verified"]
    assert any("support check" in e for e in out["errors"])

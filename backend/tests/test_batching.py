"""LLM batches are packed to the gateway's input budget, run in parallel, keep their order, and never send a
same-mechanism class's whole trial history to the stop-reason labeller."""
import json
import threading
import time

from backend.app import batching
from backend.app.llm import LLMError
from backend.app.support import SYSTEM as SUPPORT_SYSTEM, SCHEMA as SUPPORT_SCHEMA, check_support
from backend.app.trials import OTHER_PER_DRUG, label_trials, to_label

TOO_BIG = LLMError('HTTP 400: {"error":{"message":"Input exceeds the conservative input limit."}}')


class Gateway:
    """Refuses a request above `limit` real tokens, counting densely (3.3 characters a token, the densest seen in the
    9 October gateway answers). Agrees with every claim; labels every reason 'efficacy'. Records sizes and overlap."""
    def __init__(self, limit=4100, delay=0.0):
        self.limit, self.delay, self.refused, self.sizes = limit, delay, 0, []
        self.active = self.peak = 0
        self.lock = threading.Lock()

    def complete_json(self, task, system, user, schema):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            if (len(system) + len(user) + len(json.dumps(schema))) / 3.3 > self.limit:
                with self.lock:
                    self.refused += 1
                raise TOO_BIG
            items = json.loads(user)
            self.sizes.append(len(items))
            if task == "classify_stops":
                return {"trials": [{"nct": t["nct"], "labels": [{"label": "efficacy", "quote": "futility"}]} for t in items]}
            return {"items": [{"id": x["id"], "supports": True} for x in items]}
        finally:
            with self.lock:
                self.active -= 1


def items(n, quote_chars=600):
    return [{"id": str(i), "claim": "The drug did not work well enough.", "quote": "x" * quote_chars} for i in range(n)]


def test_pack_respects_budget_count_and_order():
    got = batching.pack(list(range(10)), lambda i: 3000, fixed=1000, max_items=40, budget=3500)
    assert [x for b in got for x in b] == list(range(10))                # order kept, nothing lost
    assert all(batching.tokens(1000 + sum(3002 for _ in b)) <= 3500 for b in got if len(b) > 1)
    assert batching.pack(list(range(10)), lambda i: 1, fixed=0, max_items=3)[0] == [0, 1, 2]
    assert batching.pack([1], lambda i: 99999, fixed=0, max_items=5) == [[1]]   # too big alone still goes, alone


def test_support_check_is_not_refused_by_the_gateway():
    """The 9 October batch sent 40 items and was refused 38 times out of 79; packed batches fit the first time."""
    gw = Gateway()
    got = check_support(gw, items(40), task="check_translation")
    assert gw.refused == 0 and len(got["verdicts"]) == 40 and not got["errors"]
    assert batching.tokens(batching.fixed_chars(SUPPORT_SYSTEM, SUPPORT_SCHEMA)) < batching.input_budget()


def test_batches_run_in_parallel_and_keep_their_order(monkeypatch):
    monkeypatch.setenv("UNOBIO_LLM_WORKERS", "4")
    gw = Gateway(delay=0.2)
    started = time.perf_counter()
    got = check_support(gw, items(40, quote_chars=1500), task="check_translation")
    took = time.perf_counter() - started
    batches = len(gw.sizes)
    assert batches >= 4 and gw.peak > 1 and took < 0.2 * batches * 0.75     # overlapped, not one after the other
    assert sorted(got["verdicts"], key=int) == [str(i) for i in range(40)]
    assert batching.pmap(lambda x: (time.sleep(0.01 * (5 - x)), x)[1], range(5)) == [0, 1, 2, 3, 4]


def test_one_worker_is_the_old_sequential_behaviour(monkeypatch):
    monkeypatch.setenv("UNOBIO_LLM_WORKERS", "1")
    gw = Gateway(delay=0.01)
    check_support(gw, items(40), task="check_translation")
    assert gw.peak == 1


def test_stop_reasons_are_packed_and_labelled():
    trials = [{"nct": f"NCT{i:08d}", "why_stopped": "Stopped for futility. " + "y" * 400} for i in range(60)]
    gw = Gateway()
    out = label_trials(gw, trials)
    assert gw.refused == 0 and len(out["labels"]) == 60 and not out["errors"]


def _trial(nct, drug, *, in_disease, stage, why="Business decision."):
    return {"nct": nct, "why_stopped": why, "stage": stage, "in_disease": in_disease, "same_mechanism_drugs": [drug]}


def test_to_label_keeps_the_disease_and_caps_the_rest_of_the_class():
    core = [_trial(f"NCT1{i:07d}", "SEMAGLUTIDE", in_disease=True, stage="PHASE_3") for i in range(6)]
    elsewhere = [_trial(f"NCT2{i:07d}", "SEMAGLUTIDE", in_disease=False, stage="PHASE_1") for i in range(30)]
    elsewhere.append(_trial("NCT29999999", "SEMAGLUTIDE", in_disease=False, stage="PHASE_1",
                            why="Terminated after elevated liver enzymes in two participants."))
    other_drug = [_trial(f"NCT3{i:07d}", "TAPSOGLUTIDE", in_disease=False, stage="PHASE_2") for i in range(10)]
    picked = {t["nct"] for t in to_label(core + elsewhere + other_drug)}
    assert {t["nct"] for t in core} <= picked                           # every Phase 2/3 trial in the disease
    assert "NCT29999999" in picked                                      # a safety reason is read first
    assert sum(n.startswith("NCT2") for n in picked) == OTHER_PER_DRUG  # the rest of the class is capped per drug
    assert sum(n.startswith("NCT3") for n in picked) == OTHER_PER_DRUG  # every drug still gets its share

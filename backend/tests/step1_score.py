"""Step 1: claims -> facts -> verdict, with the frozen scorer and hand-written claims.

Run:  python step1_score.py            (LLM claim waits for confirmation)
      python step1_score.py --confirm  (a human confirmed it)
"""
import sys

from backend.app.scorer import evaluate, facts_from_claims, load_config

CLAIMS = [
    # Structured: what Open Targets will give us later.
    {"id": "clm_1", "fact": "approved_therapies_count", "value": 0, "origin": "structured"},
    {"id": "clm_2", "fact": "genetic_support", "value": "gwas", "origin": "structured"},
    {"id": "clm_3", "fact": "oncology", "value": False, "origin": "structured"},
    {"id": "clm_4", "fact": "class_safety_signal", "value": True, "origin": "structured"},
    # User input fields.
    {"id": "clm_5", "fact": "phase", "value": "ph1", "origin": "user"},
    # LLM label from one trial record: one efficacy failure of the same mechanism.
    {"id": "clm_6", "fact": "moa_failures_efficacy_ph23", "value": 1, "origin": "llm",
     "verified": True, "doc_ids": ["doc_trial_1"]},
]


def run(claims: list[dict]) -> dict:
    cfg = load_config()
    got = facts_from_claims(cfg, claims)
    return {"got": got, "payload": evaluate(cfg, got["facts"])}


def show(result: dict) -> None:
    got, p = result["got"], result["payload"]
    v, s = p["verdict"], p["score"]
    print(f"VERDICT: {v['decision']}  (grounds: {v['grounds']})")
    print(f"score: +{s['pos']} -{s['neg']}  coverage: {s['coverage']}")
    print("scorecard:")
    for item in p["scorecard"]:
        print(f"  {item['color']:8} {item['name']}")
    print("rules fired:", [r["name"] for r in p["rules"]] or "none")
    print("facts used:", got["used"])
    print("pending:", [(x["fact"], x["value"]) for x in got["pending"]] or "none")
    print("rejected:", [(x["fact"], x["reason"]) for x in got["rejected"]] or "none")


if __name__ == "__main__":
    claims = [dict(c) for c in CLAIMS]
    if "--confirm" in sys.argv:
        claims[-1]["confirmed"] = True
    show(run(claims))

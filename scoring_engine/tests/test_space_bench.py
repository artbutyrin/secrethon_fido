from pathlib import Path

import pytest

from scoring import CONDITIONAL, DNI, INVEST, load_config
from scoring import bench, space

cfg = load_config()
CASES = Path(__file__).parent / "synthetic_cases.yaml"


@pytest.mark.parametrize("variant", list(cfg.variants))
def test_shares_sum_to_one(variant):
    for m in range(5):
        s = space.verdict_shares(cfg, variant, rule_minus=m)
        assert abs(sum(s.values()) - 1) < 1e-9
    for row in space.sensitivity_grid(cfg, variant):
        assert abs(row[INVEST] + row[CONDITIONAL] + row[DNI] - 1) < 1e-9


@pytest.mark.parametrize("variant", ["legacy6", "v10"])
def test_uniform_enumeration_matches_brute_force(variant):
    """State sweep against direct enumeration: with weights, science pluses and mechanism evidence."""
    from itertools import product
    from scoring import decide
    shapes = space.item_shapes(cfg, variant)
    w = cfg.weights
    total = dict.fromkeys((INVEST, CONDITIONAL, DNI), 0.0)
    options = []
    for sh in shapes:                                    # state: (pluses, red?, probability)
        if sh["can_red"]:
            pg, pr, pn = 1 / 3, 1 / 3, 1 / 3
        else:
            pg, pr, pn = 1 / 2, 0.0, 1 / 2
        opts = [(0, 0, pn), (0, 1, pr), (w["green"], 0, pg * (1 - sh["strong_share"])),
                (w["green_strong"], 0, pg * sh["strong_share"])]
        options.append([(sh, o) for o in opts if o[2]])
    for combo in product(*options):
        p = 1.0; pos = reds = mech = sci = 0
        for sh, (pts, red, q) in combo:
            p *= q; pos += pts; reds += red
            mech += 1 if pts and sh["mechanism"] else 0
            sci += pts if sh["science"] else 0
        v, _ = decide(pos, 2 * reds + 1, False, cfg.thresholds, pos, mech, sci)
        total[v] += p
    s = space.verdict_shares(cfg, variant, rule_minus=1)
    for v in total:
        assert abs(total[v] - s[v]) < 1e-9


def test_science_threshold_moves_share_from_invest_to_conditional():
    old = space.verdict_shares(cfg, "v10", thresholds={"min_science_pos_invest": 0})
    new = space.verdict_shares(cfg, "v10")
    assert new[INVEST] < old[INVEST] and new[CONDITIONAL] > old[CONDITIONAL]
    assert new[DNI] == pytest.approx(old[DNI])


def test_four_rule_minuses_never_invest():
    for variant in cfg.variants:
        assert space.verdict_shares(cfg, variant, rule_minus=4)[DNI] == pytest.approx(1.0)


def test_matched_thresholds_reference_is_unchanged():
    assert (space.matched_thresholds(cfg, cfg.default_variant)["invest_margin"]
            == cfg.thresholds["invest_margin"])


def test_sweep_refuses_minus_buckets_it_cannot_model():
    with pytest.raises(ValueError):
        space.threshold_sweep(cfg, "base7", neg_dni=(5,))
    rows = space.threshold_sweep(cfg, "base7")
    current = next(r for r in rows if (r["neg_dni"], r["invest_margin"], r["dni_margin"]) == (4, 2, 0))
    lo, hi = space.conditional_range(cfg, "base7")
    assert current["cond_min"] == pytest.approx(lo) and current["cond_max"] == pytest.approx(hi)


def test_min_two_greens_shrinks_conditional():
    new = space.conditional_range(cfg, "base7")
    old = space.conditional_range(cfg, "base7", {"min_pos_conditional": 1})
    assert new[1] < old[1] and new[0] < old[0]


def test_bench_metrics_and_report(tmp_path):
    cases = bench.load_cases(cfg, CASES)
    labels = [c["label"] for c in cases]
    m = bench.metrics(bench.run(cfg, cases, "base7"), labels)
    assert sum(m["table"].values()) == len(cases) == m["n_good"] + m["n_bad"]
    assert 0 <= m["ba_strict"] <= 1
    disc = bench.item_discrimination(cfg, cases, list(cfg.items))
    for d in disc:
        assert sum(d["counts"]["GOOD"].values()) == m["n_good"]
    imp = bench.candidate_impact(cfg, cases, "legacy6", "base7")
    assert imp["added"] == ["human_genetics", "clinical_precedent"] and imp["removed"] == ["biology"]
    assert len(imp["rows"]) == len(cases)
    abl = bench.ablation(cfg, cases, "base7")
    assert {a["id"] for a in abl if a["kind"] == "item"} == set(cfg.variants["base7"])
    with pytest.raises(ValueError):
        bench.render_report(cfg, [], tmp_path, title="t")
    path = bench.render_report(cfg, cases, tmp_path, title="t", synthetic=True)
    text = path.read_text(encoding="utf-8")
    assert "synthetic" in text and (tmp_path / "benchmark_cases.csv").exists()


def test_contradictory_case_is_reported_with_its_id(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text("cases:\n  - {id: C07, label: BAD, facts: {oncology: true, chronic_non_oncology: true}}\n",
                    encoding="utf-8")
    with pytest.raises(ValueError, match="C07"):
        bench.load_cases(cfg, path)


def test_wilson_interval():
    lo, hi = bench.wilson(5, 10)
    assert 0.23 < lo < 0.24 and 0.76 < hi < 0.77

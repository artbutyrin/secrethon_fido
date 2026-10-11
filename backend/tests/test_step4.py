"""Step 4 tests. The first group runs on real Open Targets responses (release 26.09, recorded 8 Oct 2026);
the second checks each definition on small made-up inputs."""
import copy
import json
from pathlib import Path

import pytest
from backend.app.scorer import load_config

from backend.app.facts import build_claims, direction_of, drug_key, is_diagnostic
from backend.app.opentargets import OpenTargets
from backend.app.pipeline import report_text, run

LIVE = Path(__file__).parent / "fixtures" / "live"
CFG = load_config()


def live_run(disease, target, **kw):
    ot = OpenTargets(LIVE / "cache", offline=True)
    from backend.app.normalize import normalize
    n = normalize(ot, disease, target)
    collected = json.loads((LIVE / "runs" / f"{n['disease']['id']}__{n['target']['id']}.json").read_text())
    return run(ot, disease, target, collected=collected, **kw)


def facts(out):
    return {c["fact"]: c["value"] for c in out["claims"]}


@pytest.fixture(scope="module")
def bace1():
    return live_run("Alzheimer disease", "BACE1 inhibitor")


@pytest.fixture(scope="module")
def pcsk9():
    return live_run("familial hypercholesterolemia", "anti-PCSK9 antibody")


# --- real data ------------------------------------------------------------------------------------------------------
def test_bace1_alzheimer(bace1):
    f = facts(bace1)
    assert f["genetic_support"] == "none"                 # 0 evidence rows, but the disease has genetics (APP, PSEN1)
    assert f["approved_same_moa_count"] == 0 and f["moa_clinical_precedent"] == "none"
    assert f["ph3_same_moa_count"] == 0                   # four BACE inhibitors reached Phase 3, none is active now
    assert f["oncology"] is False and f["essential_gene"] is False
    assert "rare_disease" not in f                        # Alzheimer has an Orphanet cross-reference: not enough
    res = bace1["score"]["result"]
    # 2.4: this recording has no trial outcomes, and "no genetics, no precedent" is a note: not enough evidence either
    # way. The live run with the four BACE inhibitor failures is Do Not Invest (mechanism refuted).
    assert res["verdict"]["decision"] == "Insufficient evidence"
    rule = next(r for r in res["rules"] if r["id"] == "no_genetics_no_precedent")
    assert rule["tier"] == "note" and not rule["counted"]


def test_alzheimer_approved_drugs_are_filtered(bace1):
    claim = next(c for c in bace1["claims"] if c["fact"] == "approved_therapies_count")
    named = {s["name"] for s in claim["sources"]}
    assert named == {"ADUCANUMAB", "DONANEMAB", "DONEPEZIL", "GALANTAMINE", "LECANEMAB", "MEMANTINE", "RIVASTIGMINE"}
    # left out: ADHD drugs mapped by PMDA from "AD/HD", PET radiotracers, TTD-only entries, salt duplicates


def test_pcsk9_familial_hypercholesterolemia(pcsk9):
    f = facts(pcsk9)
    assert f["genetic_support"] == "mendelian"
    assert f["approved_same_moa_count"] == 3 and f["moa_clinical_precedent"] == "approved_same"
    claim = next(c for c in pcsk9["claims"] if c["fact"] == "approved_same_moa_count")
    assert {s["name"] for s in claim["sources"] if s["kind"] == "open_targets_drug"} == \
        {"ALIROCUMAB", "EVOLOCUMAB", "INCLISIRAN SODIUM"}
    assert f["ph3_same_moa_count"] == 1                   # lerodalcibep
    assert f["modality"] == "antibody" and f["modality_target_mismatch"] is False   # PCSK9 is secreted
    res = pcsk9["score"]["result"]
    # scorer 2.x (review F38): late and undifferentiated is a strong minus plus a cap, not a kill
    # 2.5: two PCSK9 antibodies are approved and no advantage is shown: Do Not Invest, grounds "crowded"
    assert (res["verdict"]["decision"], res["verdict"]["grounds"]) == ("Do Not Invest", "crowded")
    assert [r["id"] for r in res["rules"]] == ["me_too"] and res["rules"][0]["tier"] == "kill"


def test_every_claim_is_accepted_by_the_scorer_and_has_sources(bace1, pcsk9):
    for out in (bace1, pcsk9):
        assert out["score"]["rejected"] == [] and out["score"]["conflicts"] == []
        for c in out["claims"]:
            assert c["fact"] in CFG.facts and c["statement"] and c["rule"] and c["sources"]
        assert len({c["id"] for c in out["claims"]}) == len(out["claims"])


def test_input_phase_and_route_become_user_claims(tmp_path):
    out = live_run("Alzheimer disease", "BACE1 inhibitor", phase="ph2", route="oral")
    user = {c["fact"]: c["value"] for c in out["claims"] if c["origin"] == "user"}
    assert user == {"moa_direction": "inhibit", "phase": "ph2", "route_of_administration": "oral"}


def test_report_text_renders(bace1):
    text = report_text(bace1)
    assert "VERDICT: Insufficient evidence" in text and "CLAIMS" in text and "DUE-DILIGENCE" in text


# --- definitions on small inputs -------------------------------------------------------------------------------------
def test_helpers():
    assert drug_key("Donepezil Hydrochloride") == "DONEPEZIL" and drug_key("INCLISIRAN SODIUM") == "INCLISIRAN"
    assert is_diagnostic("FLORBETABEN F18") and is_diagnostic("IOFLUPANE I 123") and not is_diagnostic("MEMANTINE")
    assert direction_of("INVERSE AGONIST") == "inhibit" and direction_of("PARTIAL AGONIST") == "activate"
    assert direction_of("RNAI INHIBITOR") == "inhibit" and direction_of("BINDING AGENT") is None


DIS = {"id": "D1", "name": "disease one", "therapeutic_areas": [{"id": "MONDO_0004995", "name": "cardiovascular"},
                                                                 {"id": "EFO_0000651", "name": "phenotype"}]}
TGT = {"id": "T1", "symbol": "TGT1", "action": "inhibit", "drug_type": None, "raw": "TGT1 inhibitor"}


def ok(data, complete=True):
    return {"ok": True, "complete": complete, "data": data}


def parts(**over):
    base = {"pair_genetics": ok({"count": 0, "rows": []}),
            "disease_genetics": ok({"count": 1, "rows": [{"target": {"approvedSymbol": "X"},
                                                          "datatypeScores": [{"id": "genetic_association", "score": 1}]}]}),
            "target_drugs": ok({"count": 0, "rows": []}), "disease_drugs": ok({"count": 0, "rows": []}),
            "target_info": ok({})}
    base.update(over)
    return {"parts": base}


def claims_for(collected, disease=DIS, target=TGT):
    return {c["fact"]: c["value"] for c in build_claims({"disease": disease, "target": target}, collected)}


def evidence(source, score=1.0, sig=None):
    return {"id": "e", "datasourceId": source, "score": score, "clinicalSignificances": sig, "disease": {"id": "D1"}}


def test_clinvar_counts_only_with_a_pathogenic_variant():
    benign = parts(pair_genetics=ok({"count": 1, "rows": [evidence("eva", 0.3, ["uncertain significance"])]}))
    assert claims_for(benign)["genetic_support"] == "none"
    path = parts(pair_genetics=ok({"count": 1, "rows": [evidence("eva", 0.9, ["Likely pathogenic"])]}))
    assert claims_for(path)["genetic_support"] == "mendelian"


def test_gwas_needs_l2g_and_not_counted_sources_are_ignored():
    rows = [evidence("gwas_credible_sets", 0.3), evidence("gene_burden"), evidence("uniprot_variants")]
    assert claims_for(parts(pair_genetics=ok({"count": 3, "rows": rows})))["genetic_support"] == "none"
    rows.append(evidence("gwas_credible_sets", 0.8))
    assert claims_for(parts(pair_genetics=ok({"count": 4, "rows": rows})))["genetic_support"] == "gwas"


def test_absence_of_genetics_needs_complete_data():
    assert "genetic_support" not in claims_for(parts(pair_genetics=ok({"count": 5, "rows": []}, complete=False)))
    no_data = parts(disease_genetics=ok({"count": 0, "rows": []}))
    assert claims_for(no_data)["genetic_support"] == "no_data"
    unknown = parts(disease_genetics=ok({"count": 500, "rows": []}, complete=False))
    assert "genetic_support" not in claims_for(unknown)


def drug_row(name, action="INHIBITOR", reports=(), indications=(), stage="PHASE_3", warnings=()):
    return {"maxClinicalStage": stage, "clinicalReports": list(reports),
            "drug": {"id": name, "name": name, "drugWarnings": [{"warningType": w} for w in warnings],
                     "mechanismsOfAction": {"rows": [{"actionType": action, "targets": [{"id": "T1"}]}]},
                     "indications": {"rows": list(indications)}}}


def report(source, diseases, stage="APPROVAL", status=None):
    return {"id": "r", "source": source, "clinicalStage": stage, "trialOverallStatus": status, "url": "u",
            "diseases": [{"disease": {"id": d}} for d in diseases]}


def test_approval_needs_an_official_label_for_this_disease():
    rows = [drug_row("A SODIUM", reports=[report("DailyMed", ["D1"])]),
            drug_row("A", reports=[report("FDA", ["D1"])]),                       # same drug as "A SODIUM"
            drug_row("B", reports=[report("PMDA", ["D1"])]),                      # PMDA only: not counted
            drug_row("C", reports=[report("TTD", ["D1"])]),                       # TTD only: not counted
            drug_row("D", reports=[report("FDA", ["D9"])])]                       # another disease
    f = claims_for(parts(target_drugs=ok({"count": 5, "rows": rows}), disease_drugs=ok({"count": 5, "rows": rows})))
    assert f["approved_same_moa_count"] == 1 and f["approved_therapies_count"] == 1


def test_zero_approvals_not_claimed_when_doubtful_approvals_were_filtered():
    rows = [drug_row("B", stage="APPROVAL", reports=[report("TTD", ["D1"])])]
    assert "approved_therapies_count" not in claims_for(parts(disease_drugs=ok({"count": 1, "rows": rows})))


def test_opposite_direction_is_another_mechanism():
    rows = [drug_row("AGO", action="AGONIST", reports=[report("FDA", ["D1"])])]
    f = claims_for(parts(target_drugs=ok({"count": 1, "rows": rows})))
    assert f["approved_same_moa_count"] == 0 and f["moa_clinical_precedent"] == "none"
    # review F37: an unknown direction is not "the same mechanism": no counts, no precedent, no "none"
    unknown_dir = dict(TGT, action=None)
    f = claims_for(parts(target_drugs=ok({"count": 1, "rows": rows})), target=unknown_dir)
    assert "approved_same_moa_count" not in f and "moa_clinical_precedent" not in f and "ph3_same_moa_count" not in f


def test_counts_only_from_a_complete_list():
    """Review F36: from an incomplete list a count is a lower bound; the approval itself still counts as precedent."""
    rows = [drug_row("X", reports=[report("FDA", ["D1"])])]
    f = claims_for(parts(target_drugs={"ok": True, "complete": False, "data": {"count": 5, "rows": rows}}))
    assert "approved_same_moa_count" not in f and "ph3_same_moa_count" not in f
    assert f["moa_clinical_precedent"] == "approved_same"
    no_dir = [drug_row("X", reports=[report("FDA", ["D1"])]), drug_row("Y", action=None)]
    f = claims_for(parts(target_drugs=ok({"count": 2, "rows": no_dir})))
    assert "approved_same_moa_count" not in f                 # Y might be the same mechanism


def test_precedent_related_only_through_a_specific_area():
    ind = lambda areas: {"maxClinicalStage": "APPROVAL", "disease": {"id": "D2", "therapeuticAreas": [{"id": a} for a in areas]}}  # noqa: E731
    related = [drug_row("X", reports=[report("FDA", ["D2"])], indications=[ind(["MONDO_0004995"])])]
    assert claims_for(parts(target_drugs=ok({"count": 1, "rows": related})))["moa_clinical_precedent"] == "approved_related"
    generic = [drug_row("X", reports=[report("FDA", ["D2"])], indications=[ind(["EFO_0000651"])])]
    assert claims_for(parts(target_drugs=ok({"count": 1, "rows": generic})))["moa_clinical_precedent"] == "approved_unrelated"


def test_competitors_are_active_phase3_trials_in_this_disease():
    rows = [drug_row("P", reports=[report("ClinicalTrials.gov", ["D1"], "PHASE_3", "RECRUITING")]),
            drug_row("Q", reports=[report("ClinicalTrials.gov", ["D1"], "PHASE_3", "TERMINATED")]),
            drug_row("R", reports=[report("ClinicalTrials.gov", ["D9"], "PHASE_3", "RECRUITING")])]
    assert claims_for(parts(target_drugs=ok({"count": 3, "rows": rows})))["ph3_same_moa_count"] == 1


def test_class_warnings_are_only_affirmative():
    rows = [drug_row("W", warnings=["Black Box Warning"]), drug_row("V", warnings=["Withdrawn"])]
    f = claims_for(parts(target_drugs=ok({"count": 2, "rows": rows})))
    assert f["class_safety_signal"] is True and f["class_withdrawal"] is True
    assert "class_safety_signal" not in claims_for(parts())


def test_modality_mismatch_for_an_intracellular_target():
    info = ok({"isEssential": True, "subcellularLocations": [{"location": "Nucleus"}],
               "prioritisation": {"items": [{"key": "isInMembrane", "value": "0"}, {"key": "isSecreted", "value": "0"}]},
               "tractability": [{"modality": "AB", "label": "x", "value": False}]})
    f = claims_for(parts(target_info=info), target=dict(TGT, drug_type="antibody"))
    assert f["modality_target_mismatch"] is True and f["essential_gene"] is True
    assert "modality_target_mismatch" not in claims_for(parts(target_info=info))      # small molecule: not asked


def test_rare_only_from_an_orphanet_id_and_oncology_from_areas():
    orpha = dict(DIS, id="Orphanet_558", therapeutic_areas=[{"id": "MONDO_0045024"}])
    f = claims_for(parts(), disease=orpha)
    assert f["rare_disease"] is True and f["oncology"] is True
    assert "rare_disease" not in claims_for(parts())


def test_failed_query_gives_no_claims_from_it():
    failed = parts(target_drugs={"ok": False, "complete": False, "error": "x"})
    f = claims_for(failed)
    assert "approved_same_moa_count" not in f and "moa_clinical_precedent" not in f
    assert copy.deepcopy(f)                                # the rest still works

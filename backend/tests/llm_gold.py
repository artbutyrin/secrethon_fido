"""Hand-labelled cases for the LLM tasks that feed the verdict. Used by eval_llm.py (live model, with a full trace)
and test_llm_replay.py (recorded answers, offline).

Three sets, so a failure points at one step:
  STOP_CASES          why a trial stopped: labeller -> quote check -> support check
  TRANSLATION_CASES   translation findings: extractor -> quote check -> support check
  SUPPORT_CASES       the support checker alone, on fixed claims and texts (is the checker too strict or too lax?)

`want`: must survive every check. `never`: must not survive. Translation expectations are (link, result) or
(link, result, species) when the species matters (a cell result must not count as a human one). `tag` groups cases by what they test (negation,
indirect, multi, ...) so the eval can say which kind of text fails. `src`: "real" = a stop reason from the recorded
Open Targets / ClinicalTrials.gov runs (NCT ID kept in `from`); "written" = made up for the test.
Add a case whenever a real run shows a wrong label: that is how the set should grow.
"""
from backend.app.translation import LINK_TEXT, finding_claim
from backend.app.trials import CHECKED


def _s(i, text, want, never, tag, src="written", origin=None):
    return {"nct": f"NCT9{i:07d}", "why": text, "want": set(want), "never": set(never), "tag": tag, "src": src,
            "from": origin}


SAFE = {"efficacy", "safety"}

# --- 1. why trials stopped ---------------------------------------------------------------------------------------------
STOP_CASES = [
    # plain, one reason
    _s(1, "Study terminated due to futility at the planned interim analysis.", {"efficacy"}, {"safety"}, "plain"),
    _s(2, "Study termination due to insufficient efficacy.", {"efficacy"}, {"safety", "enrollment"}, "plain", "real"),
    _s(3, "This study was terminated due to lack of efficacy.", {"efficacy"}, {"safety"}, "plain", "real", "NCT00538980"),
    _s(4, "Terminated due to slow recruitment.", {"enrollment"}, SAFE, "plain"),
    _s(5, "poor recruitment", {"enrollment"}, SAFE, "plain", "real", "NCT01161368"),
    _s(6, "Loss of study funding", {"funding"}, SAFE, "plain", "real", "NCT01779050"),
    _s(7, "Extreme toxicity of Pertuzumab and Erlotinib combination", {"safety"}, {"efficacy"}, "plain", "real",
       "NCT00947167"),
    _s(8, "Due to internal reprioritization, trial was cancelled.", {"business"}, SAFE, "plain", "real", "NCT06083675"),
    _s(9, "Original principal investigator left institution", {"other"}, SAFE, "plain", "real", "NCT02709083"),
    # safety described by what was seen, without the word "safety"
    _s(10, "Elevated liver enzymes were observed in several participants.", {"safety"}, {"efficacy"}, "lab-values"),
    _s(11, "Dosing of both study drugs has been discontinued due to observation of liver transaminitis without "
           "clinically significant symptoms in some subjects receiving azelaprag. All participant visits have been "
           "completed.", {"safety"}, {"efficacy"}, "lab-values", "real", "NCT06515418"),
    _s(12, "Due to a pre-specified imbalance of deaths between treatment groups, the DSMB recommended early "
           "termination of the trial", {"safety"}, {"efficacy"}, "lab-values", "real", "NCT00679627"),
    _s(13, "The results of the dose escalation phase did not identify a well-tolerated dose that would permit further "
           "study in Phase 2.", {"safety"}, {"efficacy"}, "lab-values", "real", "NCT01199367"),
    # negation: a reason named only to say it was NOT the reason
    _s(14, "Not due to safety but due to a lack of efficacy at the 5 mg azeliragon dose.", {"efficacy"}, {"safety"},
       "negation", "real", "NCT02080364"),
    _s(15, "Slow recruitment. No safety concerns during this study.", {"enrollment"}, SAFE, "negation", "real",
       "NCT00895297"),
    _s(16, "This study was closed due to business reasons. Closure was not prompted by any safety or efficacy "
           "concerns.", {"business"}, SAFE, "negation", "real", "NCT06851442"),
    _s(17, "The termination was result of GSK business considerations and not due to quality, safety or efficacy "
           "concerns with any albiglutide formulations or study conduct", {"business"}, SAFE, "negation", "real",
       "NCT02750930"),
    _s(18, "Business decision, not driven by safety concerns; no new safety signals have been observed in the "
           "ociperlimab program.", {"business"}, SAFE, "negation", "real", "NCT05809895"),
    # indirect: stopped because ANOTHER trial of the drug failed
    _s(19, "The sister study was stopped for futility; this study was stopped as a consequence.", {"efficacy"},
       {"safety"}, "indirect"),
    _s(20, "Terminated early because similar study with Ataluren (PTC124-GD-007-DMD; NCT00592553) exhibited lack of "
           "efficacy at the high dose (not due to safety concerns).", {"efficacy"}, {"safety"}, "indirect", "real",
       "NCT00759876"),
    _s(21, "The futility analysis of study NCT00910091 in patients with endometrial cancer shows that the primary "
           "endpoint will not be reached.", {"efficacy"}, {"safety"}, "indirect", "real", "NCT01230970"),
    _s(22, "The DMC recommended the trial be discontinued due to futility following a planned second interim "
           "analysis of the parent trial (CY 5031).", {"efficacy"}, {"safety"}, "indirect", "real", "NCT05442775"),
    # several reasons in one text
    _s(23, "Lack of efficacy and an unfavourable benefit-risk balance due to adverse events.", {"efficacy", "safety"},
       {"enrollment"}, "multi"),
    _s(24, "Toxicity and Lack of Efficacy", {"efficacy", "safety"}, {"enrollment"}, "multi", "real", "NCT00253318"),
    _s(25, "A planed interim analysis shows no benefits, but higher adverse event rates for the experimental arm.",
       {"efficacy", "safety"}, set(), "multi", "real", "NCT01200212"),
    _s(26, "Slow accrual and loss of funding", {"enrollment", "funding"}, SAFE, "multi", "real", "NCT00525161"),
    _s(27, "Business decision and enrollment difficulties", {"business", "enrollment"}, SAFE, "multi", "real",
       "NCT05097599"),
    _s(28, "FDA hold and toxicity associated with study drug", {"safety"}, {"efficacy"}, "multi", "real", "NCT01761747"),
    # traps: words that look like efficacy or safety but are not
    _s(29, "The primary endpoint of the core/TF1 was achieved", set(), {"efficacy"}, "trap", "real", "NCT03874858"),
    _s(30, "Study did not meet Phase Ib primary objective to establish the maximum tolerated dose/recommended dose "
           "for Phase II", set(), {"efficacy"}, "trap", "real", "NCT01495247"),
    _s(31, "Study termination due to program termination.", set(), SAFE, "trap", "real"),
    _s(32, "Manufacturer discontinued drug development.", {"business"}, SAFE, "trap", "real", "NCT01149356"),
    _s(33, "On the advice of the Data Monitoring Committee.", set(), SAFE, "trap"),
    _s(34, "withdrawn", set(), SAFE, "trap", "real", "NCT05672342"),
    _s(35, "Study never started", set(), SAFE, "trap", "real", "NCT02470065"),
    _s(36, "No participants recruited. Not able to recruit due to COVID 19.", {"enrollment"}, SAFE, "trap", "real",
       "NCT03371862"),
    _s(37, "Sponsor decided not to continue development for strategic reasons.", {"business"}, SAFE, "trap"),
    _s(38, "Results of an interim analysis showed that it was unlikely that creatine was effective in slowing loss of "
           "function in early symptomatic Huntington's Disease.", {"efficacy"}, {"safety"}, "plain", "real",
       "NCT00712426"),
]

# --- 2. translation findings -------------------------------------------------------------------------------------------
DISEASE = {"id": "MONDO_TEST", "name": "amyotrophic lateral sclerosis"}
TARGET = {"id": "ENSG_TEST", "symbol": "SOD1"}
DRUGS = ["DRUGOMERSEN", "OTHERSEN"]


def _t(i, drug, text, want, never, tag):
    return {"id": f"doc:{i:02d}", "drug": drug, "text": text, "want": set(want), "never": set(never), "tag": tag}


TE, PK, PD, ANIMAL, BENEFIT = "target_engagement", "exposure", "pd_response", "animal_response", "clinical_benefit"
TRANSLATION_CASES = [
    # shown in humans, one link each
    _t(1, "DRUGOMERSEN", "In the Phase 1 part, drugomersen reduced total SOD1 protein in cerebrospinal fluid by 35% "
       "compared with placebo in adults with ALS.", {(TE, "shown")}, {(TE, "not_shown")}, "shown"),
    _t(2, "DRUGOMERSEN", "Drugomersen concentrations in CSF increased with dose and were measurable in all participants.",
       {(PK, "shown")}, {(PK, "not_shown")}, "shown"),
    _t(3, "DRUGOMERSEN", "Plasma neurofilament light chain, a marker of axonal injury, fell by 50% with drugomersen and "
       "rose with placebo.", {(PD, "shown")}, {(PD, "not_shown")}, "shown"),
    _t(4, "DRUGOMERSEN", "PET imaging showed 70% receptor occupancy in the motor cortex four hours after a single dose "
       "of drugomersen.", {(TE, "shown")}, {(TE, "not_shown")}, "shown"),
    _t(5, "DRUGOMERSEN", "Drugomersen met its primary endpoint: ALSFRS-R decline was slower than with placebo "
       "(difference 3.1 points, P=0.01).", {(BENEFIT, "shown")}, {(BENEFIT, "not_shown")}, "shown"),
    # not shown
    _t(6, "OTHERSEN", "After intravenous dosing, othersen was not detected in cerebrospinal fluid in any participant.",
       {(PK, "not_shown")}, {(PK, "shown")}, "not-shown"),
    _t(7, "OTHERSEN", "Othersen did not improve the primary endpoint, change in ALSFRS-R at 28 weeks, versus placebo.",
       {(BENEFIT, "not_shown")}, {(BENEFIT, "shown")}, "not-shown"),
    _t(8, "OTHERSEN", "CSF SOD1 levels did not differ between othersen and placebo at week 12.",
       {(TE, "not_shown")}, {(TE, "shown")}, "not-shown"),
    _t(9, "OTHERSEN", "Although othersen lowered CSF SOD1, the change in ALSFRS-R did not reach statistical "
       "significance.", {(TE, "shown"), (BENEFIT, "not_shown")}, {(BENEFIT, "shown")}, "mixed"),
    # model organisms
    _t(10, None, "SOD1 knockdown in transgenic mice delayed disease onset and extended survival.",
       {(ANIMAL, "shown")}, set(), "animal"),
    _t(11, "DRUGOMERSEN", "In SOD1-G93A rats, intrathecal drugomersen lowered spinal cord SOD1 mRNA by 60% and "
       "prolonged survival.", {(ANIMAL, "shown")}, set(), "animal"),
    _t(12, "DRUGOMERSEN", "In cultured motor neurons, drugomersen reduced SOD1 mRNA in a dose-dependent manner.",
       {(TE, "shown", "cell")}, {(TE, "shown", "human")}, "animal"),   # a cell result, never a human one
    # nothing to extract: plans, general statements, safety only, another drug
    _t(13, "OTHERSEN", "The ongoing study will measure receptor occupancy by PET and changes in CSF neurofilament light.",
       set(), {(TE, "shown"), (PD, "shown"), (PK, "shown")}, "no-finding"),
    _t(14, "OTHERSEN", "Othersen was generally well tolerated; the most common adverse events were headache and back "
       "pain.", set(), {(PD, "shown"), (TE, "shown"), (BENEFIT, "shown")}, "no-finding"),
    _t(15, "DRUGOMERSEN", "Antisense oligonucleotides, such as drugomersen, play a leading role in targeting and "
       "modulating the expression of mutant SOD1.", set(), {(TE, "shown"), (PD, "shown"), (PK, "shown")},
       "no-finding"),                      # shape of a real false positive (a review, Shafie 2024)
    _t(16, "DRUGOMERSEN", "Drugomersen is designed to bind SOD1 mRNA and promote its degradation by RNase H.",
       set(), {(TE, "shown")}, "no-finding"),
    _t(17, "DRUGOMERSEN", "A different antisense drug, tofersen, lowered CSF SOD1 by 35%; drugomersen has not yet been "
       "tested in humans.", set(), {(TE, "shown")}, "no-finding"),
    # wording the extractor should still catch
    _t(18, "DRUGOMERSEN", "Mean CSF SOD1 concentration decreased from baseline by 36% in the 100 mg group.",
       {(TE, "shown")}, set(), "shown"),
    _t(19, "OTHERSEN", "There was a trend toward slower decline with othersen that was not statistically significant "
       "(P=0.21).", {(BENEFIT, "not_shown")}, {(BENEFIT, "shown")}, "not-shown"),
    _t(20, "OTHERSEN", "The study was stopped after an interim analysis showed worse outcomes in the othersen arm "
       "than with placebo.", {(BENEFIT, "not_shown")}, {(BENEFIT, "shown")}, "not-shown"),
]

# --- 3. the support checker alone ------------------------------------------------------------------------------------
SUPPORT_CASES = [
    # stop labels: the checker reads the whole stated reason
    {"id": "s01", "claim": CHECKED["safety"], "quote": "Elevated liver enzymes were observed in several participants.",
     "want": True, "tag": "stop"},
    {"id": "s02", "claim": CHECKED["efficacy"], "quote": "The sister study was stopped for futility; this study was "
     "stopped as a consequence.", "want": True, "tag": "stop"},
    {"id": "s03", "claim": CHECKED["efficacy"], "quote": "The primary endpoint of the core/TF1 was achieved",
     "want": False, "tag": "stop"},
    {"id": "s04", "claim": CHECKED["safety"], "quote": "Slow recruitment. No safety concerns during this study.",
     "want": False, "tag": "stop"},
    {"id": "s05", "claim": CHECKED["efficacy"], "quote": "Study did not meet Phase Ib primary objective to establish "
     "the maximum tolerated dose/recommended dose for Phase II", "want": False, "tag": "stop"},
    {"id": "s06", "claim": CHECKED["safety"], "quote": "Due to a pre-specified imbalance of deaths between treatment "
     "groups, the DSMB recommended early termination of the trial", "want": True, "tag": "stop"},
    {"id": "s07", "claim": CHECKED["efficacy"], "quote": "Business decision, not driven by safety or efficacy concerns.",
     "want": False, "tag": "stop"},
    {"id": "s08", "claim": CHECKED["safety"], "quote": "The results of the dose escalation phase did not identify a "
     "well-tolerated dose that would permit further study in Phase 2.", "want": True, "tag": "stop"},
    # translation findings: the checker reads the quote
    {"id": "s09", "claim": finding_claim({"drug": "TOMINERSEN", "link": TE, "result": "shown", "species": "human",
                                          "in_disease": True}),
     "quote": "Antisense oligonucleotides, such as Tominersen, play a leading role in targeting and modulating the "
              "expression of mutant huntingtin.", "want": False, "tag": "finding"},     # real false positive
    {"id": "s10", "claim": finding_claim({"drug": "TOMINERSEN", "link": TE, "result": "shown", "species": "human",
                                          "in_disease": True}),
     "quote": "tominersen led to dose-dependent reductions in the concentration of mutant huntingtin in CSF",
     "want": True, "tag": "finding"},
    {"id": "s11", "claim": finding_claim({"drug": "OTHERSEN", "link": BENEFIT, "result": "not_shown",
                                          "species": "human", "in_disease": True}),
     "quote": "did not improve the primary endpoint, change in ALSFRS-R at 28 weeks, versus placebo", "want": True,
     "tag": "finding"},
    {"id": "s12", "claim": finding_claim({"drug": "OTHERSEN", "link": PD, "result": "shown", "species": "human",
                                          "in_disease": True}),
     "quote": "Othersen was generally well tolerated", "want": False, "tag": "finding"},
    {"id": "s13", "claim": finding_claim({"drug": "OTHERSEN", "link": TE, "result": "shown", "species": "human",
                                          "in_disease": True}),
     "quote": "The ongoing study will measure receptor occupancy by PET", "want": False, "tag": "finding"},
    {"id": "s14", "claim": finding_claim({"drug": "DRUGOMERSEN", "link": PK, "result": "shown", "species": "human",
                                          "in_disease": True}),
     "quote": "Drugomersen concentrations in CSF increased with dose and were measurable in all participants",
     "want": True, "tag": "finding"},
]


# --- inputs ------------------------------------------------------------------------------------------------------------
def stop_trials(cases=None):
    return [{"nct": c["nct"], "why_stopped": c["why"]} for c in (cases or STOP_CASES)]


def translation_docs(cases=None):
    return [{"id": c["id"], "kind": "pubmed", "drug": c["drug"], "url": None, "title": c["id"], "text": c["text"]}
            for c in (cases or TRANSLATION_CASES)]


def support_items(cases=None):
    return [{"id": c["id"], "claim": c["claim"], "quote": c["quote"]} for c in (cases or SUPPORT_CASES)]


# --- scoring with a stage-by-stage trace ---------------------------------------------------------------------------------
def _stage(x: dict) -> str:
    if x.get("negated"):
        return "quote NEGATED in the text (code filter)"
    if x.get("support") is False:
        return "support check: NO"
    if not x["verified"]:
        return "quote NOT FOUND"
    if x.get("support") is True:
        return "kept (quote found, support yes)"
    return "kept (quote found, support not asked)"


def score_stops(labels: dict, cases=None) -> list[dict]:
    """One row per case. `trace`: every label the model gave and what each check did with it."""
    rows = []
    for c in cases or STOP_CASES:
        xs = labels.get(c["nct"])
        got = {x["label"] for x in xs or [] if x["verified"] and x.get("support") is not False}
        missing, wrong = c["want"] - got, c["never"] & got
        trace = (["labeller gave no answer for this trial"] if xs is None else
                 ["labeller gave no labels"] if not xs else
                 [f"{x['label']:<10} \"{x['quote'][:70]}\" -> {_stage(x)}" for x in xs])
        rows.append({"case": c["nct"], "tag": c["tag"], "src": c["src"], "text": c["why"], "want": sorted(c["want"]),
                     "got": sorted(got), "missing": sorted(missing), "wrong": sorted(wrong), "trace": trace,
                     "ok": not missing and not wrong})
    return rows


def score_translation(findings: list[dict], cases=None) -> list[dict]:
    rows = []
    for c in cases or TRANSLATION_CASES:
        mine = [f for f in findings if f["doc_id"] == c["id"]]
        kept = [f for f in mine if f["verified"]]
        got = {(f["link"], f["result"]) for f in kept}
        got3 = {(f["link"], f["result"], f["species"]) for f in kept}
        def has(t):                                # (link, result) or (link, result, species)
            return t in (got3 if len(t) == 3 else got)
        missing = {t for t in c["want"] if not has(t)}
        wrong = {t for t in c["never"] if has(t)}
        trace = ([f"{f['drug']:<12} {f['link']:<18} {f['result']:<9} {f['species']:<6} \"{f['quote'][:60]}\" -> "
                  f"{_stage(f)}" for f in mine] or ["extractor gave no findings"])
        rows.append({"case": c["id"], "tag": c["tag"], "src": "written", "text": c["text"],
                     "want": sorted(c["want"]), "got": sorted(got3), "missing": sorted(missing),
                     "wrong": sorted(wrong), "trace": trace, "ok": not missing and not wrong})
    return rows


def score_support(verdicts: dict, cases=None) -> list[dict]:
    rows = []
    for c in cases or SUPPORT_CASES:
        got = verdicts.get(c["id"])
        rows.append({"case": c["id"], "tag": c["tag"], "src": "written", "text": c["quote"],
                     "want": [c["want"]], "got": [got], "missing": [] if got == c["want"] else [c["want"]],
                     "wrong": [] if got == c["want"] or got is None else [got],
                     "trace": [f"claim: {c['claim'][:110]}", f"checker said: {got}"], "ok": got == c["want"]})
    return rows


def label_stats(rows: list[dict], labels: list[str]) -> dict[str, dict]:
    """Per label: cases that want it, found, missed, and wrong where `never` lists it."""
    out = {}
    for lab in labels:
        want = [r for r in rows if lab in r["want"]]
        out[lab] = {"want": len(want), "found": sum(lab in r["got"] for r in want),
                    "missed": sum(lab in r["missing"] for r in rows), "wrong": sum(lab in r["wrong"] for r in rows)}
    return out


def tag_stats(rows: list[dict]) -> dict[str, str]:
    tags: dict[str, list] = {}
    for r in rows:
        tags.setdefault(r["tag"], []).append(r["ok"])
    return {t: f"{sum(v)}/{len(v)}" for t, v in tags.items()}


LINKS = list(LINK_TEXT)

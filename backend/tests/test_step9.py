"""Step 9 tests: translation-chain sources (openFDA, UniProt, PubMed, AACT, Open Targets link-1 evidence), the
support check, class facts, the engaged-no-benefit rule and the chain in the memo.

The source clients are tested against mock HTTP servers in the documented response shapes. They have NOT been
replayed from live responses yet: run one pair live and copy backend/data/cache/<source>/ into fixtures."""
import json
import re
from pathlib import Path

import httpx
import pytest

from backend.app import translation as tl
from backend.app.facts import Claims, target_info_claims
from backend.app.opentargets import OpenTargets
from backend.app.pipeline import run
from backend.app.normalize import normalize
from backend.app.report import build_report
from backend.app.sources.aact import AACT, normalize_phase
from backend.app.sources.http import CachedHTTP, SourceError
from backend.app.sources.openfda import OpenFDA
from backend.app.sources.pubmed import PubMed, parse_articles
from backend.app.sources.uniprot import UniProt, is_surface
from backend.app.trials import label_trials
from backend.tests.test_step5 import KEYWORDS

LIVE = Path(__file__).parent / "fixtures" / "live"


def mock_http(routes, seen=None):
    """routes: [(regex on url, status, body)]; body is a dict (JSON) or str."""
    def handler(request):
        if seen is not None:
            seen.append(str(request.url))
        for rx, status, body in routes:
            if re.search(rx, str(request.url)):
                if isinstance(body, str):
                    return httpx.Response(status, text=body)
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- openFDA ------------------------------------------------------------------------------------------------------------
LABEL = {"meta": {"results": {"total": 1}}, "results": [{
    "set_id": "abc-123", "effective_time": "20230425",
    "mechanism_of_action": ["Tofersen is an antisense oligonucleotide that causes degradation of SOD1 mRNA."],
    "pharmacodynamics": ["Tofersen reduced total SOD1 protein in CSF.", "Plasma NfL was reduced."],
    "openfda": {"generic_name": ["TOFERSEN"], "brand_name": ["QALSODY"]}}]}


def test_openfda_label_sections_cache_and_404(tmp_path):
    seen = []
    http = CachedHTTP("openfda", cache_root=tmp_path, http=mock_http([(r"generic_name.*tofersen", 200, LABEL)], seen))
    fda = OpenFDA(http, api_key="SECRET")
    lab = fda.label("TOFERSEN")
    assert lab["brand_name"] == "QALSODY" and lab["url"].endswith("setid=abc-123")
    assert lab["sections"]["pharmacodynamics"] == "Tofersen reduced total SOD1 protein in CSF. Plasma NfL was reduced."
    assert fda.label("nodrugmab") is None                         # 404 on both fields is an answer: no label
    n = len(seen)
    assert fda.label("tofersen")["set_id"] == "abc-123" and len(seen) == n     # second time from the cache
    files = list((tmp_path / "openfda").glob("*.json"))
    assert files and not any("SECRET" in f.read_text() for f in files)        # the key never reaches the cache


def test_offline_source_without_cache_raises(tmp_path):
    with pytest.raises(SourceError, match="offline"):
        OpenFDA(CachedHTTP("openfda", cache_root=tmp_path, offline=True)).label("tofersen")


# --- UniProt ------------------------------------------------------------------------------------------------------------
ABL1_UNIPROT = {"results": [{"primaryAccession": "P00519", "genes": [{"geneName": {"value": "ABL1"}}], "comments": [
    {"commentType": "SUBCELLULAR LOCATION", "subcellularLocations": [
        {"location": {"value": "Cytoplasm, cytoskeleton", "id": "SL-0090"}},
        {"location": {"value": "Nucleus", "id": "SL-0191"}},
        {"location": {"evidences": [{"evidenceCode": "ECO:0000250"}], "value": "Mitochondrion", "id": "SL-0173"}}]},
    {"commentType": "SUBCELLULAR LOCATION", "molecule": "Isoform IB", "subcellularLocations": [
        {"location": {"value": "Nucleus membrane", "id": "SL-0182"}, "topology": {"value": "Lipid-anchor"}}]}]}]}


def test_uniprot_locations_and_surface_words(tmp_path):
    up = UniProt(CachedHTTP("uniprot", cache_root=tmp_path, http=mock_http([(r"uniprotkb/search", 200, ABL1_UNIPROT)])))
    got = up.locations("ABL1")
    assert got["accession"] == "P00519" and len(got["locations"]) == 4
    assert {"value": "Nucleus membrane", "id": "SL-0182", "molecule": "Isoform IB", "evidence": []} in got["locations"]
    assert not any(is_surface(x["value"]) for x in got["locations"])          # an organelle membrane is not the surface
    assert is_surface("Cell membrane") and is_surface("Secreted") and not is_surface("Endoplasmic reticulum membrane")


# --- the ABL1 antibody bug: GO CC med conf and a nuclear membrane must not make an intracellular target reachable --------
ABL1_OT = {"ok": True, "complete": True, "data": {
    "isEssential": False, "prioritisation": {"items": [{"key": "isInMembrane", "value": "0"},
                                                       {"key": "isSecreted", "value": "0"}]},
    "subcellularLocations": [{"location": x} for x in ("Cytoplasm", "cytoskeleton", "Mitochondrion", "Nuclear bodies",
                                                        "Nucleoplasm", "Nucleus membrane")],
    "tractability": [{"modality": "AB", "label": "GO CC med conf", "value": True},
                     {"modality": "SM", "label": "Approved Drug", "value": True}]}}
ABL1 = {"id": "ENSG00000097007", "symbol": "ABL1"}


def mismatch(part, uniprot=None):
    c = Claims()
    target_info_claims(c, ABL1, part, "antibody", uniprot)
    return next(x for x in c.items if x["fact"] == "modality_target_mismatch")


def test_antibody_cannot_reach_abl1():
    up = {"accession": "P00519", "url": "u", "locations": [{"value": "Nucleus membrane"}, {"value": "Nucleus"}]}
    m = mismatch(ABL1_OT, up)
    assert m["value"] is True and "cannot" in m["statement"] and any(s["kind"] == "uniprot" for s in m["sources"])


def test_a_surface_location_or_strong_tractability_makes_it_reachable():
    surface = json.loads(json.dumps(ABL1_OT))
    assert mismatch(surface, {"accession": "X", "url": "u", "locations": [{"value": "Cell membrane"}]})["value"] is False
    strong = json.loads(json.dumps(ABL1_OT))
    strong["data"]["tractability"].append({"modality": "AB", "label": "UniProt loc high conf", "value": True})
    assert mismatch(strong)["value"] is False


# --- PubMed -------------------------------------------------------------------------------------------------------------
EFETCH = """<?xml version="1.0" ?><PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>111</PMID><Article><Journal><JournalIssue><PubDate><Year>2018</Year></PubDate>
</JournalIssue><Title>Sci Transl Med</Title></Journal><ArticleTitle>Verubecestat lowers CSF A<i>beta</i></ArticleTitle>
<Abstract><AbstractText Label="RESULTS">Verubecestat reduced CSF Abeta40 by more than 60% in patients with
Alzheimer disease.</AbstractText></Abstract><AuthorList><Author><LastName>Kennedy</LastName></Author></AuthorList>
<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList></Article></MedlineCitation>
</PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>222</PMID><Article><Journal><Title>J</Title></Journal><ArticleTitle>Withdrawn</ArticleTitle>
<Abstract><AbstractText>Something.</AbstractText></Abstract><PublicationTypeList>
<PublicationType>Retracted Publication</PublicationType></PublicationTypeList></Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


def test_pubmed_search_fetch_and_parse(tmp_path):
    http = CachedHTTP("pubmed", cache_root=tmp_path, http=mock_http([
        (r"esearch", 200, {"esearchresult": {"idlist": ["111", "222"]}}), (r"efetch", 200, EFETCH)]))
    arts = PubMed(http).articles("verubecestat")
    a = {x["pmid"]: x for x in arts}
    assert a["111"]["title"] == "Verubecestat lowers CSF Abeta" and a["111"]["year"] == "2018"
    assert a["111"]["abstract"].startswith("RESULTS: Verubecestat reduced") and a["111"]["first_author"] == "Kennedy"
    assert a["222"]["retracted"] and not a["111"]["retracted"]
    assert parse_articles("<PubmedArticleSet/>") == []


# --- AACT ---------------------------------------------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, rows):
        self.rows, self.description, self.sql = rows, None, None

    def execute(self, sql, params):
        self.sql, self.params = sql, params
        self.description = [(k,) for k in self.rows[0]] if self.rows else []

    def fetchall(self):
        return [tuple(r.values()) for r in self.rows]


class FakeConnection:
    def __init__(self, rows):
        self.cur = FakeCursor(rows)

    def cursor(self):
        return self.cur

    def close(self):
        pass


EVACETRAPIB = [
    {"nct_id": "NCT02260635", "phase": "PHASE3", "overall_status": "TERMINATED",
     "why_stopped": "Study termination due to insufficient efficacy.", "enrollment": 120, "sponsor": "Eli Lilly and Company",
     "start_date": "2014-10-01", "results_posted": None, "matched": ["evacetrapib"],
     "mesh_terms": ["coronary artery disease", "heart diseases", "cardiovascular diseases"], "conditions": ["atherosclerosis"],
     "design_outcomes": [{"type": "primary", "measure": "Change from baseline in LDL-C"}], "primary_analyses": None},
    {"nct_id": "NCT01687998", "phase": "Phase 3", "overall_status": "Completed", "why_stopped": None, "enrollment": 12092,
     "sponsor": "Eli Lilly and Company", "start_date": "2012-10-01", "results_posted": "2017-01-01",
     "matched": ["ly2484595"], "mesh_terms": ["coronary artery disease"], "conditions": ["high-risk vascular disease"],
     "design_outcomes": [{"type": "secondary", "measure": "Plasma evacetrapib concentration"}],
     "primary_analyses": [{"outcome": "Time to MACE", "p_value": 0.91, "non_inferiority": "Superiority", "method": "Cox"}]},
]


def test_aact_query_normalizes_and_caches(tmp_path):
    conns = []
    def connect(dsn):
        conns.append(dsn)
        return FakeConnection(json.loads(json.dumps(EVACETRAPIB)))
    aact = AACT("postgresql://local/aact", cache_dir=tmp_path, connect=connect)
    rows = aact.trials_for_drugs(["Evacetrapib", "LY2484595", ""])
    assert [r["stage"] for r in rows] == ["PHASE_3", "PHASE_3"] and rows[1]["overall_status"] == "COMPLETED"
    assert aact.trials_for_drugs(["ly2484595", "evacetrapib"]) == rows and len(conns) == 1      # cached, order-free
    assert normalize_phase("PHASE2/PHASE3") == "PHASE_2_3" and normalize_phase("EARLY_PHASE1") == "PHASE_1"
    assert not AACT(None).ready


def test_aact_maps_trials_to_the_disease_by_mesh_and_counts_primary_misses():
    disease = {"id": "MONDO_0005010", "name": "coronary artery disorder", "synonyms": ["coronary artery disease"]}
    rows = json.loads(json.dumps(EVACETRAPIB))
    for r in rows:
        r["stage"], r["overall_status"], r["drugs"] = "PHASE_3", r["overall_status"].upper(), ["EVACETRAPIB"]
    tr = {"parts": {"aact": {"ok": True, "data": rows}}}
    # Open Targets had this trial without a disease ID, so it was dropped from the efficacy count
    ot_trial = {"nct": "NCT02260635", "why_stopped": "Study termination due to insufficient efficacy.",
                "status": "TERMINATED", "stage": "PHASE_3", "sponsor": "Eli Lilly", "diseases": [], "in_disease": False,
                "same_mechanism_drugs": ["EVACETRAPIB"], "drugs": ["EVACETRAPIB"], "url": "u", "ot_categories": []}
    merged = tl.merge_aact_trials([ot_trial], tr, disease)
    assert merged[0]["in_disease"] is True
    fails = tl.aact_failures(tr, disease)
    assert [t["nct"] for t, _ in fails["EVACETRAPIB"]] == ["NCT01687998"]                 # p = 0.91 on the primary
    assert tl.tested_links(tr)["exposure"] == ["NCT01687998"]                                # tested, not shown


# --- the support check (the asciminib bug) ----------------------------------------------------------------------------
class CheckingLLM:
    """Labels like the keyword LLM; the support check accepts a stop-label quote only if it names a failure."""
    model, calls = "checking", []

    def complete_json(self, task, system, user, schema):
        items = json.loads(user)
        if task == "classify_stops":
            return {"trials": [{"nct": t["nct"], "labels": [{"label": lab, "quote": m.group(0)} for lab, rx in KEYWORDS
                                                            if (m := re.search(rx, t["reason"], re.I))]} for t in items]}
        if task.startswith("check"):
            return {"items": [{"id": x["id"], "supports": bool(re.search(r"futility|efficacy|not met|lack|adverse|safety|"
                                                                         r"liver", x["quote"], re.I))} for x in items]}
        return {}


def test_a_real_quote_that_says_the_opposite_is_not_counted():
    trials = [{"nct": "NCT03874858", "why_stopped": "The primary endpoint of the core/TF1 was achieved"},
              {"nct": "NCT00000002", "why_stopped": "Stopped for futility"}]
    labels = label_trials(CheckingLLM(), trials)["labels"]
    assert labels["NCT03874858"] == [{"label": "efficacy", "quote": "primary endpoint", "verified": False,
                                      "support": False}]
    assert labels["NCT00000002"][0]["verified"] and labels["NCT00000002"][0]["support"] is True


# --- end to end on the recorded BACE1 run ------------------------------------------------------------------------------
ABSTRACT = ("Verubecestat reduced CSF Abeta40 by more than 60% in patients with Alzheimer disease. "
            "Plasma concentrations increased with dose.")


class FakePubMed:
    calls = []

    def articles(self, term, retmax=5):
        if term.startswith('"verubecestat"'):
            return [{"pmid": "111", "title": "Verubecestat in AD", "abstract": ABSTRACT, "year": "2018",
                     "first_author": "Kennedy", "retracted": False, "url": "https://pubmed.ncbi.nlm.nih.gov/111/"}]
        if term.startswith('"lanabecestat"'):
            return [{"pmid": "333", "title": "Lanabecestat", "abstract": "Lanabecestat was well tolerated.", "year": "2019",
                     "first_author": "X", "retracted": False, "url": "https://pubmed.ncbi.nlm.nih.gov/333/"}]
        return []


class FakeSources:
    def __init__(self):
        self.openfda, self.uniprot, self.pubmed, self.aact = None, None, FakePubMed(), None

    def calls(self):
        return [{"source": "pubmed", "cache": True}]


class TranslationLLM(CheckingLLM):
    """Finds one real engagement quote, one made-up quote, and one real quote that the support check rejects."""

    def complete_json(self, task, system, user, schema):
        if task == "extract_translation":
            docs = json.loads(user)["documents"]
            out = []
            for d in docs:
                if d["id"] == "pmid:111":
                    out.append({"id": d["id"], "findings": [
                        {"drug": "VERUBECESTAT", "link": "target_engagement", "result": "shown", "species": "human",
                         "in_disease": True, "quote": "reduced CSF Abeta40 by more than 60%"},
                        {"drug": "VERUBECESTAT", "link": "exposure", "result": "shown", "species": "human",
                         "in_disease": True, "quote": "brain levels exceeded the IC90"}]})          # not in the text
                else:
                    out.append({"id": d["id"], "findings": [
                        {"drug": "LANABECESTAT", "link": "pd_response", "result": "shown", "species": "human",
                         "in_disease": True, "quote": "Lanabecestat was well tolerated"}]})       # real, wrong meaning
            return {"documents": out}
        if task == "check_translation":
            return {"items": [{"id": x["id"], "supports": "tolerated" not in x["quote"]} for x in json.loads(user)]}
        return super().complete_json(task, system, user, schema)


@pytest.fixture(scope="module")
def bace1():
    ot = OpenTargets(LIVE / "cache", offline=True)
    n = normalize(ot, "Alzheimer disease", "BACE1 inhibitor")
    collected = json.loads((LIVE / "runs" / f"{n['disease']['id']}__{n['target']['id']}.json").read_text())
    return run(ot, "Alzheimer disease", "BACE1 inhibitor", collected=collected, llm=TranslationLLM(),
               sources=FakeSources())


def claim(out, fact):
    return next((c for c in out["claims"] if c["fact"] == fact), None)


def test_only_checked_findings_become_class_facts(bace1):
    te = claim(bace1, "class_target_engagement_human")
    assert te["value"] is True and te["origin"] == "llm" and te["doc_ids"] == ["pmid:111"]
    assert te["sources"][0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/111/"
    assert claim(bace1, "class_exposure_human") is None            # made-up quote: not found in the abstract
    assert claim(bace1, "class_pd_response_human") is None         # real quote, but it does not say that
    f = {(x["drug"], x["link"]): x for x in bace1["findings"]}
    assert f[("VERUBECESTAT", "exposure")]["verified"] is False and f[("LANABECESTAT", "pd_response")]["support"] is False


def test_engaged_no_benefit_fires_once_a_human_confirms_the_failures(bace1):
    from backend.app.pipeline import score_claims
    assert "moa_failures_efficacy_ph23" in {p["fact"] for p in bace1["score"]["pending"]}     # LLM: waits
    confirmed = [dict(c, confirmed=True) if c["fact"] == "moa_failures_efficacy_ph23" else c for c in bace1["claims"]]
    res = score_claims(confirmed)["result"]
    fired = {r["id"]: r for r in res["rules"]}
    assert "engaged_no_benefit" in fired and "one_mechanism_failure" in fired
    assert res["verdict"]["decision"] == "Do Not Invest"
    item = next(i for i in res["scorecard"] if i["id"] == "translation_chain")
    assert item["color"] == "U"                # scorer 2.2: class evidence is not data about the asset (chain table only)


def test_translation_parts_are_kept_with_the_run(bace1):
    tr = bace1["collected"]["translation"]
    assert tr["parts"]["pubmed"]["ok"] and [d["key"] for d in tr["drugs"]][:2] == ["ELENBECESTAT", "LANABECESTAT"]
    assert bace1["chain"]["target_engagement"]["shown"] == ["VERUBECESTAT"]
    assert bace1["log"]["sources"] == [{"source": "pubmed", "cache": True}]


def test_memo_shows_the_five_links_and_the_missing_ones(bace1):
    status = {cid: "used" for ids in bace1["score"]["used"].values() for cid in ids}
    claims = bace1["claims"]
    score = {"payload": bace1["score"], "version": 1}
    rep = build_report({"id": "run_x", "normalized": bace1["normalized"]}, claims, score, status, None,
                       chain=bace1["chain"])
    sec = {s["id"]: s for s in rep["sections"]}
    links = [p for p in sec["human_translation_thesis"]["paragraphs"] if p["text"].startswith("Link ")]
    assert [p["text"][:6] for p in links] == ["Link 1", "Link 2", "Link 3", "Link 4", "Link 5"]
    assert "class: shown" in links[2]["text"] and links[2]["claim_ids"] == [claim(bace1, "class_target_engagement_human")["id"]]
    assert "to settle:" in links[1]["text"]
    unknown = sec["critical_unknowns"]["paragraphs"][0]["text"]
    assert unknown.startswith("Missing links in the translation chain for this asset: link 1, link 2, link 3")


def test_without_sources_nothing_changes():
    ot = OpenTargets(LIVE / "cache", offline=True)
    n = normalize(ot, "Alzheimer disease", "BACE1 inhibitor")
    collected = json.loads((LIVE / "runs" / f"{n['disease']['id']}__{n['target']['id']}.json").read_text())
    out = run(ot, "Alzheimer disease", "BACE1 inhibitor", collected=collected)
    assert "translation" not in out["collected"] and not any(c["fact"].startswith("class_") for c in out["claims"])


# --- backend/.env parsing (a comment on the model line was sent as part of the model name) --------------------------
def test_env_values_drop_inline_comments():
    from backend.app.llm import env_value
    assert env_value("gpt-6-luna     # or gpt-6.1-sol, gpt-6-astra, gpt-5-mini") == "gpt-6-luna"
    assert env_value("            # the gateway base URL, ending in /v1") == ""
    assert env_value('"https://gw.example/v1"  # quoted') == "https://gw.example/v1"
    assert env_value("sk_team_abc#123") == "sk_team_abc#123"            # a # inside a value is kept


def test_load_env_reads_the_example_shape(tmp_path, monkeypatch):
    from backend.app import llm as llm_mod
    for v in ("UNOBIO_LLM_MODEL", "UNOBIO_LLM_BASE_URL"):
        monkeypatch.delenv(v, raising=False)
    env = tmp_path / ".env"
    env.write_text("UNOBIO_LLM_BASE_URL=            # the gateway base URL\nUNOBIO_LLM_MODEL=gpt-6-luna   # or gpt-5-mini\n")
    llm_mod.load_env.__wrapped__(env) if hasattr(llm_mod.load_env, "__wrapped__") else None
    import importlib
    real = importlib.reload(llm_mod).load_env           # conftest replaced load_env; reload gets the real one
    real(env)
    import os
    assert os.environ["UNOBIO_LLM_MODEL"] == "gpt-6-luna" and "UNOBIO_LLM_BASE_URL" not in os.environ


# --- the gateway rejects the output token limit: the client lowers it by itself --------------------------------------
def test_llm_lowers_a_rejected_output_token_limit(tmp_path):
    from backend.app.llm import OpenAILLM
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body.get("max_completion_tokens"))
        if body["max_completion_tokens"] > 4096:
            return httpx.Response(400, json={"error": {"code": "invalid_request",
                                                       "message": "Output token limit is outside the supported range."}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}})
    llm = OpenAILLM(api_key="k", provider="openai", reasoning="", cache_dir=tmp_path,
                    http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert llm.complete_json("t", "s", "u", {"type": "object"}) == {"ok": True}
    assert sent == [16000, 8192, 4096] and llm.max_tokens == 4096          # remembered for the next calls


# --- a completed Phase 3 counts too (tominersen's trials are "completed", not "stopped") ------------------------------
def test_literature_failure_counts_for_a_completed_phase3():
    disease = {"id": "MONDO_0007739", "name": "Huntington disease", "synonyms": []}
    collected = {"parts": {"target_drugs": {"ok": True, "data": {"rows": [{"drug": {"name": "TOMINERSEN"},
        "clinicalReports": [{"clinicalStage": "PHASE_3", "trialOverallStatus": "COMPLETED",
                             "diseases": [{"disease": {"id": "MONDO_0007739"}}]}]}]}}}}
    ph23 = tl.ph23_drugs_in_disease(collected, None, disease, [{"key": "TOMINERSEN"}])
    assert ph23 == {"TOMINERSEN"}
    finding = {"verified": True, "link": "clinical_benefit", "result": "not_shown", "in_disease": True,
               "species": "human", "drug": "TOMINERSEN", "doc_id": "pmid:1", "doc_kind": "pubmed", "url": "u",
               "title": "Tominersen in manifest HD", "quote": "did not show benefit"}
    hits = tl.literature_failures([finding], ph23)["TOMINERSEN"]
    assert hits[0][0]["doc_key"] == "pmid:1" and hits[0][1]["source"] == "pubmed"
    assert tl.literature_failures([finding], set()) == {}                 # no Phase 2/3 in the disease: not counted


# --- a reasoning model cut off at the token limit: less reasoning, then more room ------------------------------------
def test_cut_off_answer_is_retried_with_low_reasoning(tmp_path):
    from backend.app.llm import OpenAILLM
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body.get("reasoning_effort"))
        if not body.get("reasoning_effort"):
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"sections": [{"id"'},
                                                          "finish_reason": "length"}], "usage": {}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}})
    llm = OpenAILLM(api_key="k", provider="openai", reasoning="", cache_dir=tmp_path,
                    http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert llm.complete_json("t", "s", "u", {"type": "object"}) == {"ok": True} and sent == [None, "low"]


def test_reviews_are_not_read():
    tr = {"parts": {"pubmed": {"ok": True, "data": [{"query": "q", "drug": "TOMINERSEN", "articles": [
        {"pmid": "1", "title": "Review", "abstract": "Tominersen plays a leading role.", "review": True, "url": "u"},
        {"pmid": "2", "title": "Trial", "abstract": "Tominersen lowered CSF mHTT.", "review": False, "url": "u"}]}]}}}
    assert [d["id"] for d in tl.documents(tr)] == ["pmid:2"]


def test_unknown_direction_is_shown_in_the_memo_not_dropped():
    from backend.app.report import mechanism_unknowns
    paras = mechanism_unknowns({"input_action": None, "unsure_drugs": ["TRASTUZUMAB"], "list_complete": True})
    assert len(paras) == 1 and "Direction of action is not known" in paras[0]["text"]
    paras = mechanism_unknowns({"input_action": "inhibit", "unsure_drugs": ["X"], "list_complete": False})
    assert "1 drug(s)" in paras[0]["text"] and "incomplete" in paras[1]["text"]
    assert mechanism_unknowns({"input_action": "inhibit", "unsure_drugs": [], "list_complete": True}) == []

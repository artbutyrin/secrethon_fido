"""Step 10 tests: market and round inputs, Orphanet / CMS market data, economics in the verdict and in the memo
(scorer 2.x, INTEGRATION steps 3-5). CMS answers come from a fake client; Orphanet from a small synthetic file."""
import sqlite3

import pytest

import backend.app.api as api
from backend.app import db
from backend.app.market import CMS, collect_market, market_for
from backend.app.scorer import ENGINE
from backend.tests.test_step6 import client, start  # noqa: F401  (client is a fixture)

pytestmark = pytest.mark.skipif(ENGINE != "unobio_scoring", reason="economics need scorer 2.x")

PCSK9 = {"disease": "familial hypercholesterolemia", "target": "anti-PCSK9 antibody", "phase": "ph2"}


class FakeCMSHTTP:
    """CMS Part D 'Overall' rows for the two approved PCSK9 antibodies; nothing for other drugs."""

    def __init__(self):
        self.asked = []

    def get(self, url, params):
        g = params["filter[Gnrc_Name]"]
        self.asked.append(g)
        if "7e0b" in url and g in ("Evolocumab", "Alirocumab"):
            return [{"Brnd_Name": g[:4], "Gnrc_Name": g, "Mftr_Name": "Overall", "Avg_Spnd_Per_Bene_2024": "6500",
                     "Tot_Benes_2024": "90000"}]
        return []


@pytest.fixture
def cms(monkeypatch):
    http = FakeCMSHTTP()
    monkeypatch.setattr(api, "make_cms", lambda: CMS(http))
    return http


def report_md(client, run_id):  # noqa: F811
    return client.get(f"/runs/{run_id}/report.md").text


def section(md: str, title: str) -> str:
    start_ = md.index(f"## {title}")
    nxt = md.find("\n## ", start_ + 4)
    return md[start_:nxt if nxt > 0 else None]


# --- no market: the thesis question, economics not run ---------------------------------------------------------------
def test_thesis_without_market(client, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("UNOBIO_ORPHANET", str(tmp_path / "missing.xml"))  # same result with or without the real file
    run_id = start(client, **PCSK9)
    e = client.get(f"/runs/{run_id}/economics").json()
    assert e["question"] == "thesis" and e["economics"] is None and "economics not run" in e["economics_note"]
    assert any("Orphanet epidemiology file not found" in n for n in e["market"]["notes"])
    md = report_md(client, run_id)
    assert "Question answered: is the thesis investable" in section(md, "Recommendation")
    com = section(md, "Commercial opportunity")
    assert "Economics not run" in com and "can only lower" not in com
    cap = section(md, "Capital to next milestone")
    assert "Next milestone: complete ph2" in cap and "(DiMasi)" in cap and "need a patient count" in cap


# --- market entered + CMS prices: sourced economics count in the verdict --------------------------------------------
def test_entered_patients_and_cms_price_drive_the_economics(client, cms):  # noqa: F811
    run_id = start(client, **PCSK9, market={"us_patients": 1_300_000})
    assert "Evolocumab" in cms.asked and "Alirocumab" in cms.asked
    claims = {c["fact"]: c for c in client.get(f"/runs/{run_id}/claims").json()}
    assert claims["approved_same_moa_count"]["value"] == 3               # inclisiran (siRNA) is the same mechanism
    assert claims["approved_same_moa_same_modality_count"]["value"] == 2  # ...but not the same modality

    e = client.get(f"/runs/{run_id}/economics").json()
    econ, prov = e["economics"], e["market"]["provenance"]
    assert prov["us_patients"]["tag"] == "user" and prov["price_same_moa"]["tag"] == "S"
    assert econ["drives_verdict"] and e["economics_note"] is None
    assert econ["forecast"]["price"]["rung"] == "same_moa" and econ["forecast"]["price"]["value"] == 4875.0
    assert econ["assumptions"]["entry_position"] == 3                     # behind the two antibodies
    assert set(econ["facts"]) >= {"economics_negative", "economics_weak"}

    com = section(report_md(client, run_id), "Commercial opportunity")
    assert "US patients: 1,300,000 [entered]" in com
    assert "eligible share 100.0% [A default]" in com and "upper bound" in com
    assert "Net price $4,875 per patient-year [S]" in com and "same mechanism: Alirocumab $4,875, Evolocumab $4,875" in com
    assert "exclusivity after launch 13 years" in com and "Grabowski" in com
    assert "Monte Carlo (2000 draws)" in com and "Scenarios: bear" in com and "median" in com
    assert "economics count in the verdict" in com
    assert "Not in CMS Medicare spending data (approved_same_moa_count): Inclisiran" in com


def test_assumed_price_is_shown_but_never_decides(client):  # noqa: F811
    run_id = start(client, **PCSK9, market={"us_patients": 1_300_000})    # CMS offline: no analogue price
    e = client.get(f"/runs/{run_id}/economics").json()
    assert e["economics"]["forecast"]["price"]["rung"] == "reference"
    assert not e["economics"]["drives_verdict"] and "annual_net_price_usd" in e["economics_note"]
    assert e["economics"]["facts"] == {}
    com = section(report_md(client, run_id), "Commercial opportunity")
    assert "per patient-year [A]" in com and "Shown, not used in the verdict" in com


# --- the round question --------------------------------------------------------------------------------------------
def test_round_terms_turn_the_thesis_into_a_round_question(client, cms):  # noqa: F811
    run_id = start(client, **PCSK9, market={"us_patients": 1_300_000})
    out = client.post(f"/runs/{run_id}/evidence", json={"action": "add", "fact": "differentiation_claim",
                                                        "value": "efficacy", "source_text": "data room"}).json()
    assert out["verdict"]["decision"] == "Invest"                       # the thesis is investable

    fair = client.post(f"/runs/{run_id}/inputs", json={"round_terms": {"pre_money_m": 20, "investment_m": 10,
                                                                         "cash_m": 200}}).json()
    assert fair["change"]["question"] == {"from": "thesis", "to": "round"}
    assert fair["verdict"]["decision"] == "Conditional"                 # a round needs data on the asset itself
    assert [c["id"] for c in fair["change"]["caps_added"]] == ["cap_asset_data"]

    rich = client.post(f"/runs/{run_id}/inputs", json={"round_terms": {"pre_money_m": 2000, "investment_m": 100,
                                                                         "cash_m": 200}}).json()
    assert [c["id"] for c in rich["change"]["caps_added"]] == ["cap_round_price"]
    iv = client.get(f"/runs/{run_id}/economics").json()["economics"]["investor"]
    assert not iv["earns_cost_of_capital"] and iv["max_pre_money_m"] < 2000

    md = report_md(client, run_id)
    rec, cap = section(md, "Recommendation"), section(md, "Capital to next milestone")
    assert "Capped at Conditional: at this pre-money the round does not earn the cost of capital" in rec
    assert "Question answered: invest in this round" in rec
    assert "Highest pre-money at which the round earns its cost of capital" in cap and "priced above" in cap
    assert "Company cash $200m [entered]: reaches the milestone." in cap

    back = client.post(f"/runs/{run_id}/inputs", json={"round_terms": None}).json()
    assert back["verdict"]["decision"] == "Invest" and back["change"]["question"]["to"] == "thesis"
    hist = client.get(f"/runs/{run_id}/history").json()
    assert [h["decision"] for h in hist] == ["Do Not Invest", "Invest", "Conditional", "Conditional", "Invest"]
    assert hist[2]["evidence"]["action"] == "inputs" and hist[2]["evidence"]["fields"] == ["round_terms"]


def test_short_runway_is_a_strong_minus(client, cms):  # noqa: F811
    run_id = start(client, **PCSK9, market={"us_patients": 1_300_000}, round_terms={"cash_m": 20})
    run = client.get(f"/runs/{run_id}").json()
    assert run["round_terms"] == {"cash_m": 20} and run["market"] == {"us_patients": 1_300_000}
    assert "runway_short" in [r["id"] for r in run["verdict"]["rules"]]
    assert "does NOT reach the milestone" in section(report_md(client, run_id), "Capital to next milestone")


def test_inputs_are_validated(client):  # noqa: F811
    assert client.post("/runs", json={**PCSK9, "market": {"patients": 5}}).status_code == 422
    assert client.post("/runs", json={**PCSK9, "round_terms": {"pre_money_m": -1}}).status_code == 422
    run_id = start(client, **PCSK9)
    assert client.post(f"/runs/{run_id}/inputs", json={}).status_code == 400
    assert client.post(f"/runs/{run_id}/inputs", json={"market": {"us_patients": 0}}).status_code == 422


# --- Orphanet ------------------------------------------------------------------------------------------------------
ORPHA = {"399": {"name": "Huntington disease", "records": [
    {"type": "Point prevalence", "cls": "1-9 / 100 000", "per_100k": 12.3, "geo": "United States", "validated": True,
     "source": "11111111[PMID]"},
    {"type": "Point prevalence", "cls": "1-9 / 100 000", "per_100k": 5.7, "geo": "Europe", "validated": True,
     "source": "22222222[PMID]"}]}}


def test_orphanet_patient_count_by_cross_reference():
    norm = {"disease": {"id": "MONDO_0007739", "name": "Huntington disease", "xrefs": ["OMIM:143100", "Orphanet:399"]}}
    got = collect_market(norm, [], None, orphanet_data=ORPHA)
    assert got["orphacode"] == "399" and got["orphanet_entry"]["name"] == "Huntington disease" and not got["notes"]
    m, prov = market_for({"rare_disease": True, "oncology": False}, got, None)
    assert m["us_patients"] == round(12.3 / 1e5 * 335_000_000) and m["segment"] == "rare"
    assert prov["us_patients"]["tag"] == "S" and prov["us_patients"]["basis"] == "US point prevalence"
    assert m["us_patients_range"][0] < m["us_patients"] <= m["us_patients_range"][1]
    m2, prov2 = market_for({}, got, {"us_patients": 41_000})              # a person's number wins
    assert m2["us_patients"] == 41_000 and prov2["us_patients"] == {"tag": "user"}


def test_no_orphanet_entry_is_a_note():
    norm = {"disease": {"id": "EFO_0000000", "name": "common disease", "xrefs": []}}
    got = collect_market(norm, [], None, orphanet_data=ORPHA)
    assert got["orphanet_entry"] is None and "No Orphanet prevalence" in got["notes"][0]
    assert market_for({}, got, None) == (None, {})


# --- storage -------------------------------------------------------------------------------------------------------
def test_old_database_gets_the_new_columns(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript("CREATE TABLE runs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
                      " disease_input TEXT, target_input TEXT, disease_id TEXT, target_id TEXT, phase TEXT, route TEXT,"
                      " status TEXT NOT NULL, message TEXT, ot_release TEXT, llm_model TEXT, normalized TEXT);")
    raw.close()
    con = db.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(runs)")}
    assert {"market_input", "round_terms", "license_terms"} <= cols
    rid = db.create_run(con, disease="d", target="t", disease_id=None, target_id=None, phase=None, route=None,
                        round_terms={"cash_m": 5})
    assert db.get_run(con, rid)["round_terms"] == {"cash_m": 5}

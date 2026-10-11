"""Tests never read a developer's backend/.env or LLM keys from the shell: every test starts with no LLM configured.
The public sources (openFDA, UniProt, PubMed, AACT) run offline: cache only, never the network."""
import os

import pytest

# 2.4: auto-confirmation of multi-source LLM claims is on by default in runs; the recorded tests below were written for
# the reviewer-only gate (review F34), so they run with it off. test_v24.py turns it on explicitly.
os.environ["UNOBIO_AUTO_CONFIRM"] = "0"
# 2.6: the recorded tests check the LLM path; rules (Open Targets stop categories, abstract rules) run in test_v26.py
os.environ["UNOBIO_RULES"] = "0"

LLM_VARS = ("TEAM_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "UNOBIO_LLM_PROVIDER", "UNOBIO_LLM_BASE_URL",
            "UNOBIO_LLM_MODEL", "UNOBIO_LLM_REASONING", "UNOBIO_LLM_MAX_TOKENS",
            "UNOBIO_LLM_TEMPERATURE", "UNOBIO_LLM_SEED")


@pytest.fixture(autouse=True)
def no_real_llm_settings(monkeypatch):
    monkeypatch.setattr("backend.app.llm.load_env", lambda *a, **k: None)
    for var in LLM_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("UNOBIO_OFFLINE", "1")
    monkeypatch.delenv("AACT_DSN", raising=False)


@pytest.fixture(autouse=True)
def empty_source_cache(monkeypatch, tmp_path):
    """openFDA, UniProt, PubMed, ClinicalTrials.gov and CMS read an empty cache in tests, never the developer's
    backend/data/cache (a live run there must not change test results). Tests that need answers use mock servers."""
    monkeypatch.setattr("backend.app.sources.http.CACHE_ROOT", tmp_path / "source_cache")

"""PubMed via NCBI E-utilities (esearch + efetch). NCBI_API_KEY is optional (10 instead of 3 requests a second).

Returns abstracts only (title, abstract, year, journal, first author). Retracted papers and reviews are marked;
the translation step reads neither (a review restates others' results in general words).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from backend.app.sources.http import CachedHTTP

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
TOOL = "unobio"


def _text(el) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def parse_articles(xml_text: str) -> list[dict]:
    out = []
    root = ET.fromstring(xml_text)
    for art in root.iter("PubmedArticle"):
        cit = art.find("MedlineCitation")
        if cit is None:
            continue
        pmid = _text(cit.find("PMID"))
        a = cit.find("Article")
        if a is None or not pmid:
            continue
        parts = []
        for t in a.findall("Abstract/AbstractText"):
            label = t.get("Label")
            parts.append(f"{label}: {_text(t)}" if label else _text(t))
        year = _text(a.find("Journal/JournalIssue/PubDate/Year")) or _text(a.find("Journal/JournalIssue/PubDate/MedlineDate"))[:4]
        types = {_text(p).lower() for p in a.findall("PublicationTypeList/PublicationType")}
        first = a.find("AuthorList/Author")
        out.append({"pmid": pmid, "title": _text(a.find("ArticleTitle")), "abstract": " ".join(parts),
                    "year": year or None, "journal": _text(a.find("Journal/Title")) or None,
                    "first_author": _text(first.find("LastName")) if first is not None else None,
                    "retracted": "retracted publication" in types,
                    "review": bool(types & {"review", "systematic review", "meta-analysis"}),
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"})
    return out


class PubMed:
    def __init__(self, http: CachedHTTP | None = None, api_key: str | None = None, email: str | None = None):
        self.http = http or CachedHTTP("pubmed", min_interval=0.34)
        self.api_key = api_key
        self.email = email

    def _params(self, **kw) -> dict:
        p = {"tool": TOOL, **kw}
        if self.email:
            p["email"] = self.email
        if self.api_key:
            p["api_key"] = self.api_key
        return p

    def search(self, term: str, retmax: int = 5) -> list[str]:
        body = self.http.get(BASE + "esearch.fcgi", self._params(db="pubmed", term=term, retmax=retmax,
                                                                 retmode="json", sort="relevance"))
        return list(((body or {}).get("esearchresult") or {}).get("idlist") or [])

    def fetch(self, pmids: list[str]) -> list[dict]:
        if not pmids:
            return []
        text = self.http.get(BASE + "efetch.fcgi", self._params(db="pubmed", id=",".join(pmids), retmode="xml",
                                                                rettype="abstract"), kind="text")
        return parse_articles(text) if text else []

    def articles(self, term: str, retmax: int = 5) -> list[dict]:
        """Abstracts for a query; only articles that have an abstract."""
        return [a for a in self.fetch(self.search(term, retmax)) if a["abstract"]]

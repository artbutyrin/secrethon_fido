"""Pipeline stage 1: free text -> Open Targets disease and target IDs.

Resolution rules, in order (never a silent guess):
  a. exact name match (targets also: approved symbol or approved name)
  b. exact synonym match among the top 3 hits
  c. the top search score is at least 2x the second one
Otherwise the result is `ambiguous` with candidates, and the user picks an ID.
An all-caps disease abbreviation ("AD", "MS") is always `ambiguous`: a wrong disease is worse than one extra click.

Disease names are compared by their forms (`name_forms`), not by the raw text, so that the same name written in
another convention still matches exactly:
  - MeSH inverted order: "Kidney Failure, Chronic" = "Chronic Kidney Failure",
    "Carcinoma, Non-Small-Cell Lung" = "Non-Small-Cell Lung Carcinoma";
  - possessive and apostrophes: "Alzheimer Disease" = "Alzheimer's disease" = "Alzheimers disease";
  - hyphens and spacing: "non-small cell" = "non small-cell";
  - plural of a word: "Hyperlipidemias" = "hyperlipidemia", "Colorectal Neoplasms" = "colorectal neoplasm".
A form only makes two names EQUAL; it never picks between different diseases. A name in MeSH order is also searched
in natural order (Open Targets' search finds nothing for "Neuralgia, Postherpetic"), and the rules a-c run on the
hits of all the searches. Two different diseases with an equal form stay `ambiguous`.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from backend.app.mechanism import parse_mechanism
from backend.app.opentargets import OpenTargets

TOP_N_DETAILS = 3
MAX_CANDIDATES = 5
SCORE_GAP = 2.0

_POSSESSIVE = re.compile(r"(?<=\w)'s\b")
_JOINERS = re.compile(r"['\-‐-—]")
_NON_WORD = re.compile(r"[^\w\s]")
_ABBREVIATION = re.compile(r"[A-Z][A-Z0-9]{1,5}")
_GENERIC_WORDS = {"disease", "diseases", "syndrome", "syndromes", "disorder", "disorders"}


def key(text: str | None) -> str:
    """Comparison key: "Alzheimer's disease" == "alzheimer disease"; "GLP-1R" == "glp1r"."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    t = _NON_WORD.sub(" ", _JOINERS.sub("", _POSSESSIVE.sub("", t)))
    return " ".join(t.split())


def uninvert(text: str) -> str | None:
    """MeSH heading order -> natural order: "Kidney Failure, Chronic" -> "Chronic Kidney Failure",
    "Purpura, Thrombocytopenic, Idiopathic" -> "Idiopathic Thrombocytopenic Purpura". None without a comma."""
    parts = [p.strip() for p in (text or "").split(",") if p.strip()]
    if len(parts) < 2:
        return None
    return " ".join(reversed(parts))


_KEEP_S = ("ss", "us", "is", "ous")


def _singular(word: str) -> str:
    """Plural of one word, applied to BOTH names being compared (so "diabetes" -> "diabete" on both sides is
    harmless): "neoplasms" -> "neoplasm", "myopathies" -> "myopathy". Short words and Latin/Greek endings stay."""
    if len(word) <= 4 or word.endswith(_KEEP_S) or word.isdigit():
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("s"):
        return word[:-1]
    return word


def form(text: str | None) -> str:
    """One comparison form: key(), each word in singular, spaces removed ("non-small cell" = "nonsmall-cell")."""
    return "".join(_singular(w) for w in key(text).split())


def name_forms(text: str | None) -> set[str]:
    """Every comparison form of a name: as written and, in MeSH order, in natural order."""
    if not text:
        return set()
    out = {form(text)}
    natural = uninvert(text)
    if natural:
        out.add(form(natural))
    return out - {""}


def same_name(a: str | None, b: str | None) -> bool:
    """Two names of the same entity, written in different conventions (see the module docstring)."""
    return bool(name_forms(a) & name_forms(b))


def search_queries(text: str) -> list[str]:
    """The text as written, then in natural order if it is in MeSH order."""
    natural = uninvert(text)
    return [text] + ([natural] if natural and key(natural) != key(text) else [])


def is_abbreviation(text: str) -> bool:
    return bool(_ABBREVIATION.fullmatch(text.strip()))


def _candidates(hits: list[dict], first: list[str] = ()) -> list[dict]:
    ordered = [h for i in first for h in hits if h["id"] == i] + [h for h in hits if h["id"] not in first]
    return [{"id": h["id"], "name": h.get("name"), "description": h.get("description"), "score": h.get("score")}
            for h in ordered[:MAX_CANDIDATES]]


def _synonyms(kind: str, details: dict) -> set[str]:
    if kind == "disease":   # only exact synonyms: broad/related ones are shared by too many diseases
        return {f for s in details.get("synonyms") or []
                if (s.get("relation") or "").lower() in {"hasexactsynonym", "exact"} for t in s.get("terms") or []
                for f in name_forms(t)}
    return {key(s.get("label")) for s in details.get("synonyms") or []}


def _resolve(ot: OpenTargets, kind: str, text: str | None, explicit_id: str | None) -> dict[str, Any]:
    details_of = ot.disease if kind == "disease" else ot.target
    if explicit_id:
        d = details_of(explicit_id)
        if d is None:
            return {"status": "not_found", "message": f"no {kind} with id {explicit_id!r} in Open Targets"}
        return {"status": "resolved", "match": "user_selected", "details": d}
    if not text:
        return {"status": "not_found", "message": f"no {kind} text to search"}

    # Diseases: also search the natural order of a MeSH heading. Rules a and b look at the hits of every search;
    # rule c (score gap) only compares scores within one search.
    queries = search_queries(text) if kind == "disease" else [text]
    per_query = [[h for h in ot.search(q, kind) if h.get("entity") in (None, kind)] for q in queries]
    hits, seen = [], set()
    for hs in per_query:
        for h in hs:
            if h["id"] not in seen:
                seen.add(h["id"])
                hits.append(h)
    if not hits:
        loose = " ".join(w for w in text.split() if key(w) not in _GENERIC_WORDS)
        if loose and key(loose) != key(text):
            suggestions = [h for h in ot.search(loose, kind) if h.get("entity") in (None, kind)]
            if suggestions:
                return {"status": "not_found", "candidates": _candidates(suggestions),
                        "message": f"no {kind} found for {text!r}; candidates come from {loose!r}"}
        return {"status": "not_found", "message": f"no {kind} found for {text!r}"}

    if kind == "disease" and is_abbreviation(text):
        return {"status": "ambiguous", "candidates": _candidates(hits),
                "message": f"{text!r} looks like an abbreviation; pick the disease"}

    q = key(text)
    wanted = name_forms(text) if kind == "disease" else {q}

    def resolved(entity_id: str, match: str) -> dict[str, Any]:
        d = details_of(entity_id)
        if d is None:
            return {"status": "error", "message": f"search returned {entity_id}, but its details are empty"}
        return {"status": "resolved", "match": match, "details": d}

    # a. exact name of a search hit (diseases: any written form of the name, see name_forms)
    if kind == "disease":
        same_name_ids = [h["id"] for h in hits if name_forms(h.get("name")) & wanted]
        plain = [h["id"] for h in hits if key(h.get("name")) == q]
    else:
        same_name_ids = plain = [h["id"] for h in hits if key(h.get("name")) == q]
    if len(same_name_ids) == 1:
        return resolved(same_name_ids[0], "exact_name" if plain == same_name_ids else "name_variant")
    if len(same_name_ids) > 1:
        return {"status": "ambiguous", "candidates": _candidates(hits, same_name_ids),
                "message": "several entities have this exact name"}

    # a (targets: symbol or full name) and b (exact synonym) on the top hits' details (of each search)
    by_name, by_synonym = [], []
    tops = list(dict.fromkeys(h["id"] for hs in per_query for h in hs[:TOP_N_DETAILS]))
    for hid in tops:
        d = details_of(hid)
        if not d:
            continue
        if kind == "target" and q in {key(d.get("approvedSymbol")), key(d.get("approvedName"))}:
            by_name.append(hid)
        if (wanted if kind == "disease" else {q}) & _synonyms(kind, d):
            by_synonym.append(hid)
    for ids, match in ((by_name, "exact_name"), (by_synonym, "exact_synonym")):
        if len(ids) == 1:
            return resolved(ids[0], match)
        if len(ids) > 1:
            return {"status": "ambiguous", "candidates": _candidates(hits, ids),
                    "message": f"several entities match by {match.replace('_', ' ')}"}

    hits = next(hs for hs in per_query if hs)      # scores are comparable only within one search
    # c. clear winner by search score
    if len(hits) >= 2:
        s1, s2 = float(hits[0].get("score") or 0), float(hits[1].get("score") or 0)
        if s1 > 0 and s1 >= SCORE_GAP * s2:
            return resolved(hits[0]["id"], "score_gap")
        message = f"no exact match; top score {s1:.3g} is less than {SCORE_GAP:g}x the second ({s2:.3g})"
    else:
        message = "one fuzzy hit and no exact match; confirm it by its id"
    return {"status": "ambiguous", "candidates": _candidates(hits), "message": message}


def resolve_disease(ot: OpenTargets, text: str | None = None, disease_id: str | None = None) -> dict[str, Any]:
    out = _resolve(ot, "disease", text, disease_id)
    d = out.pop("details", None)
    result = {"status": out["status"], "query": text, "match": out.get("match"),
              "candidates": out.get("candidates", []), "message": out.get("message")}
    if d:
        result.update(id=d["id"], name=d["name"], description=d.get("description"),
                      therapeutic_areas=d.get("therapeuticAreas") or [], xrefs=d.get("dbXRefs") or [],
                      synonyms=sorted({t for s in d.get("synonyms") or []
                                       if (s.get("relation") or "").lower() in {"hasexactsynonym", "exact"}
                                       for t in s.get("terms") or []}))
    return result


def resolve_target(ot: OpenTargets, text: str | None = None, target_id: str | None = None) -> dict[str, Any]:
    mech = parse_mechanism(text) if text else None
    query = mech.target_query if mech else None
    out = _resolve(ot, "target", query, target_id)
    d = out.pop("details", None)
    result = {"status": out["status"], "query": query, "match": out.get("match"),
              "candidates": out.get("candidates", []), "message": out.get("message"),
              "raw": text, "action": mech.action if mech else None, "drug_type": mech.drug_type if mech else None,
              "variant": mech.variant if mech else None}
    if d:
        result.update(id=d["id"], symbol=d["approvedSymbol"], name=d.get("approvedName"), biotype=d.get("biotype"))
    return result


def normalize(ot: OpenTargets, disease: str | None = None, target: str | None = None,
              disease_id: str | None = None, target_id: str | None = None) -> dict[str, Any]:
    """Both entities plus the Open Targets release. `status` is `resolved` only if both are resolved."""
    d = resolve_disease(ot, disease, disease_id)
    t = resolve_target(ot, target, target_id)
    statuses = {d["status"], t["status"]}
    status = next(s for s in ("error", "not_found", "ambiguous", "resolved") if s in statuses)
    return {"status": status, "disease": d, "target": t, "ot_release": ot.release()}

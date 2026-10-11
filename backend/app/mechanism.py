"""Mechanism text -> target search text + direction of action + drug type. Fixed word lists, no LLM.

"anti-PCSK9 antibody" -> target "PCSK9", action "inhibit", drug_type "antibody".
Unknown direction or type stays None: an unknown fact cannot kill a program, a wrong one can.
`action` and `drug_type` use the scorer's values for the facts `moa_direction` and `modality`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_I = re.IGNORECASE

# Drug-type words removed first, so "antibody-drug conjugate" is not read as "antibody".
DRUG_TYPE_WORDS: list[tuple[str, re.Pattern[str]]] = [
    ("adc", re.compile(r"\b(?:antibody[\s-]+drug[\s-]+conjugates?|ADCs?)\b", _I)),
    ("bispecific", re.compile(r"\bbi[\s-]?specifics?(?:[\s-]+(?:antibod(?:y|ies)|T[\s-]?cell[\s-]+engagers?))?\b", _I)),
    ("radioligand", re.compile(r"\b(?:radioligands?|radiopharmaceuticals?|radioconjugates?)\b", _I)),
    ("small_molecule", re.compile(r"\bPROTACs?\b", _I)),
    ("rna", re.compile(r"\bmRNA(?:[\s-]+therap(?:y|ies))?\b", _I)),
    ("vaccine", re.compile(r"\bvaccines?\b", _I)),
    ("peptide", re.compile(r"\bpeptides?\b", _I)),
]

# Action words, in priority order. Each may also imply a drug type and/or a direction.
#            word            pattern                                                          drug type        direction
ACTION_WORDS: list[tuple[str, re.Pattern[str], str | None, str | None]] = [
    ("gene therapy", re.compile(r"\bgene[\s-]+therap(?:y|ies)\b", _I), "gene", "activate"),
    ("CAR-T", re.compile(r"\bCAR[\s-]?T\b(?:[\s-]+cells?)?(?:[\s-]+therap(?:y|ies))?", _I), "cell", None),
    ("siRNA", re.compile(r"\bsiRNAs?\b", _I), "rna", "inhibit"),
    ("antisense", re.compile(r"\bantisense(?:[\s-]+oligo(?:nucleotide)?s?)?\b", _I), "rna", "inhibit"),
    ("antibody", re.compile(r"\b(?:monoclonal[\s-]+)?antibod(?:y|ies)\b", _I), "antibody", None),
    ("degrader", re.compile(r"\bdegraders?\b", _I), None, "inhibit"),
    ("inhibitor", re.compile(r"\binhibitors?\b", _I), None, "inhibit"),
    ("antagonist", re.compile(r"\bantagonists?\b", _I), None, "inhibit"),
    ("inverse agonist", re.compile(r"\binverse[\s-]+agonists?\b", _I), None, "inhibit"),
    ("agonist", re.compile(r"\b(?:(?:partial|full)[\s-]+)?agonists?\b", _I), None, "activate"),
    ("activator", re.compile(r"\bactivators?\b", _I), None, "activate"),
    ("negative modulator", re.compile(r"\bnegative[\s-]+(?:allosteric[\s-]+)?modulators?\b", _I), None, "inhibit"),
    ("positive modulator", re.compile(r"\bpositive[\s-]+(?:allosteric[\s-]+)?modulators?\b", _I), None, "activate"),
    ("modulator", re.compile(r"\b(?:allosteric[\s-]+)?modulators?\b", _I), None, None),
    ("blocker", re.compile(r"\bblockers?\b", _I), None, "inhibit"),
    ("anti-", re.compile(r"\banti[\s-](?=[A-Za-z0-9])", _I), None, "inhibit"),
]

_CELL_THERAPY = re.compile(r"\bcell[\s-]+therap(?:y|ies)\b", _I)
_SMALL_MOLECULE = re.compile(r"\bsmall[\s-]+molecules?(?:[\s-]+drugs?)?\b", _I)
_SUFFIX = re.compile(r"-(?:targeting|targeted|directed)\b", _I)
# A protein change after the gene ("KRAS G12C", "BRAF V600E", "EGFR T790M"): kept as `variant`, not searched for.
# Only after the first token, so names that look like one ("S1P receptor") are left alone. Case-sensitive.
_AA = "ACDEFGHIKLMNPQRSTVWY"
_VARIANT = re.compile(rf"(?<=\S)\s+(?:p\.)?([{_AA}]\d{{1,4}}(?:[{_AA}]|del|fs|\*))(?=\s|$|[,;/)])")
_EDGE_WORDS = {"against", "targeting", "targeted", "directed", "for", "of", "to", "the", "a", "an", "and"}
_EDGE_PUNCT = " \t\n,;:/()[]{}.-–—+"


@dataclass(frozen=True)
class Mechanism:
    raw: str
    target_query: str            # what to search for in Open Targets
    action: str | None           # inhibit | activate | None
    drug_type: str | None        # scorer modality value or None
    words: tuple[str, ...] = ()  # action words found, in priority order
    variant: str | None = None   # protein change named in the input, e.g. "G12C"


def _clean(text: str) -> str:
    tokens = _SUFFIX.sub(" ", text).split()
    changed = True
    while tokens and changed:
        changed = False
        tokens = [t for t in (tok.strip(_EDGE_PUNCT) if i in (0, len(tokens) - 1) else tok
                              for i, tok in enumerate(tokens)) if t]
        if tokens and tokens[0].lower() in _EDGE_WORDS:
            tokens.pop(0)
            changed = True
        if tokens and tokens[-1].lower() in _EDGE_WORDS:
            tokens.pop()
            changed = True
    return " ".join(tokens).strip(_EDGE_PUNCT)


def parse_mechanism(text: str) -> Mechanism:
    rest = text
    drug_type = None
    for kind, pattern in DRUG_TYPE_WORDS:
        if pattern.search(rest):
            drug_type = drug_type or kind
            rest = pattern.sub(" ", rest)

    words, action = [], None
    for word, pattern, implied_type, direction in ACTION_WORDS:
        if pattern.search(rest):
            words.append(word)
            rest = pattern.sub(" ", rest)
            drug_type = drug_type or implied_type
            action = action or direction

    if _CELL_THERAPY.search(rest):
        rest = _CELL_THERAPY.sub(" ", rest)
        drug_type = drug_type or "cell"
    if _SMALL_MOLECULE.search(rest):
        rest = _SMALL_MOLECULE.sub(" ", rest)
        drug_type = drug_type or "small_molecule"

    variants = _VARIANT.findall(rest)
    rest = _VARIANT.sub(" ", rest)
    return Mechanism(raw=text, target_query=_clean(rest), action=action, drug_type=drug_type, words=tuple(words),
                     variant=", ".join(variants) or None)

"""Steps 6–7 of the unobio pipeline: facts → scorecard, rules, clusters → verdict.

Merged engine (unobio_scoring 2.1): the validated version 1.1 engine of scoring_engine/, with its configuration
carried as Python data (config_v11.py, no YAML needed) and the review fixes applied on top (fixes.py):
verdict caps, the asset-data requirement for Invest, the claims gate and the economics hook.

Everything here is a pure function of a fact dictionary and the configuration.
No network, clock or LLM calls: the same facts always give the same
verdict, and an added or hidden fact changes it predictably.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import json

from .needs import needs_for as _needs_for

DEFAULT_CONFIG = None   # the configuration is built in: config_v11.RAW + fixes.apply

GREEN, YELLOW, RED, UNKNOWN = "G", "Y", "R", "U"
INVEST, CONDITIONAL, DNI = "Invest", "Conditional", "Do Not Invest"
# 2.3: "we don't know" is its own verdict, not Do Not Invest. Used exactly when the grounds are insufficient_evidence:
# no kill rule, minuses below neg_dni and not outweighing the pluses, but not enough confirmation for Conditional or
# Invest. Do Not Invest stays for negative evidence (kill, negatives, outweighed).
INSUFFICIENT = "Insufficient evidence"
VERDICTS = (INVEST, CONDITIONAL, INSUFFICIENT, DNI)
# Order for "better / worse" (what_would_change, caps that can only lower): a minus added to Insufficient evidence
# can only make it Do Not Invest, a plus can only make it Conditional or Invest.
VERDICT_RANK = {INVEST: 3, CONDITIONAL: 2, INSUFFICIENT: 1, DNI: 0}

_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "ge": lambda a, b: a >= b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "in": lambda a, b: a in b,
}
_ORDER_OPS = {"ge", "le", "gt", "lt"}
_THRESHOLD_KEYS = {"neg_dni", "invest_margin", "dni_margin", "min_pos_conditional", "require_mechanism_green"}
# Version 1.0 thresholds. Without them the engine behaves like version 0.4.
_OPTIONAL_THRESHOLDS = {"min_science_pos_invest": 0, "science_short": "Do Not Invest",
                        "conditional_requires_mechanism": False, "invest_requires_asset_data": False,
                        # 2.4: distinct green mechanism-evidence items needed for Invest (points are not enough: one
                        # strong green gives 2 points from a single piece of evidence, HTT + tominersen)
                        "min_science_items_invest": 0}
_TOP_KEYS = {"version", "weights", "verdict", "facts", "scorecard", "variants", "clusters", "rules",
             "constraints", "derive", "cluster_axis", "reference", "default_variant", "caps"}
_FACT_KEYS = {"type", "values", "scope", "label", "source", "dd", "probes", "min", "max", "mvp"}
# Where a fact comes from in the first pipeline version. none = only from a human.
MVP_SOURCES = ("input", "open_targets", "clinicaltrials", "clinicaltrials_text", "pubmed_text",
               "curated", "derived", "none")
_ITEM_KEYS = {"id", "set", "axis", "mechanism_evidence", "replaces", "name", "scope", "basis", "source", "red", "green",
              "strong_green", "strong_share_assumption", "evidence_facts", "note", "thresholds_assumption"}
_RULE_KEYS = {"id", "tier", "cluster", "axis", "absorbed_by", "absorbed_when", "name", "scope", "basis",
              "source", "when", "note", "grounds"}   # 2.5: grounds = the GROUNDS key a kill rule reports


class ConfigError(ValueError):
    pass


class FactError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Config:
    raw: dict
    facts: dict
    items: dict           # id -> scorecard item description
    rules: list
    clusters: dict
    variants: dict
    weights: dict
    thresholds: dict
    constraints: list
    derive: list
    sha256: str = ""      # hash of the config file: together with the version it pins the rules

    @property
    def default_variant(self) -> str:
        """Current item set: `default_variant` from the config, otherwise v04."""
        return self.raw.get("default_variant", "v04")

    def variant_items(self, variant: str | Iterable[str] | None = None) -> list[str]:
        if variant is None:
            variant = self.default_variant
        if isinstance(variant, str):
            if variant not in self.variants:
                raise ConfigError(f"Unknown scorecard variant: {variant}")
            return list(self.variants[variant])
        ids = list(variant)
        for item_id in ids:
            if item_id not in self.items:
                raise ConfigError(f"Unknown scorecard item: {item_id}")
        return ids

    @property
    def rule_ids(self) -> set:
        return {r["id"] for r in self.rules}


def load_config(path: str | Path | None = DEFAULT_CONFIG, *, fixes: bool = True, raw: dict | None = None,
                asset_data_for_invest: bool = False) -> Config:
    """The built-in configuration: version 1.1 plus the review fixes (fixes=False gives exact version 1.1).

    path: optional YAML file (needs PyYAML), e.g. an archived benchmarks.yaml for comparison; raw: a config dict.
    """
    if raw is None and path is not None:
        import yaml  # optional dependency, only for external YAML configs
        raw = yaml.safe_load(Path(path).read_bytes().decode("utf-8"))
    elif raw is None:
        from . import config_v11, fixes as _fixes
        raw = _fixes.apply(config_v11.RAW) if fixes else config_v11.RAW
        if fixes and asset_data_for_invest:
            raw = {**raw, "verdict": {**raw["verdict"], "invest_requires_asset_data": True}}
    blob = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    if set(raw) - _TOP_KEYS:
        raise ConfigError(f"Unknown config sections: {sorted(set(raw) - _TOP_KEYS)}")
    items: dict = {}
    for it in raw["scorecard"]:
        if it["id"] in items:
            raise ConfigError(f"Item '{it['id']}' is defined twice")
        items[it["id"]] = it
    cfg = Config(
        raw=raw,
        facts=raw["facts"],
        items=items,
        rules=raw["rules"],
        clusters=raw["clusters"],
        variants=raw["variants"],
        weights={"green_strong": raw["weights"]["green"],
                 **{k: v for k, v in raw["weights"].items() if k != "assumption"}},
        thresholds={**_OPTIONAL_THRESHOLDS,
                    **{k: v for k, v in raw["verdict"].items() if k != "assumption"}},
        constraints=raw.get("constraints", []),
        derive=raw.get("derive", []),
        sha256=hashlib.sha256(blob).hexdigest(),
    )
    _validate_config(cfg)
    return cfg


def _value_ok(spec: dict, value: Any) -> bool:
    """Type and bounds of a fact value."""
    kind = spec["type"]
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "enum":
        return value in spec["values"]
    if kind == "int":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif kind == "number":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    else:
        return False
    if not ok:
        return False
    high = spec.get("max")
    return value >= spec.get("min", 0) and (high is None or value <= high)


def _only_keys(obj: dict, allowed: set, where: str) -> None:
    extra = set(obj) - allowed
    if extra:
        raise ConfigError(f"{where}: unknown keys {sorted(extra)}")


def _validate_config(cfg: Config) -> None:
    """Fail loudly: a typo in a fact name or a condition must not silently disable a rule."""
    allowed = _THRESHOLD_KEYS | set(_OPTIONAL_THRESHOLDS)
    if not (_THRESHOLD_KEYS <= set(cfg.thresholds) <= allowed):
        raise ConfigError(f"verdict: expected keys {sorted(_THRESHOLD_KEYS)}, "
                          f"optional {sorted(_OPTIONAL_THRESHOLDS)}")
    if cfg.thresholds["science_short"] not in (CONDITIONAL, INSUFFICIENT, DNI):
        raise ConfigError("verdict.science_short must be 'Conditional', 'Insufficient evidence' or 'Do Not Invest'")
    if set(cfg.weights) != {"green", "green_strong", "red", "strong", "warning"}:
        raise ConfigError("weights: expected keys green, red, strong, warning and optional green_strong")
    if cfg.default_variant not in cfg.variants:
        raise ConfigError(f"default_variant: unknown variant '{cfg.default_variant}'")
    for name, spec in cfg.facts.items():
        _only_keys(spec, _FACT_KEYS, f"fact {name}")
        if spec.get("type") not in ("bool", "int", "number", "enum"):
            raise ConfigError(f"fact {name}: unknown type {spec.get('type')!r}")
        if spec.get("scope") not in ("mechanism", "asset"):
            raise ConfigError(f"fact {name}: scope must be mechanism or asset")
        for probe in spec.get("probes", []):
            if not _value_ok(spec, probe):
                raise ConfigError(f"fact {name}: wrong value in probes: {probe!r}")
        if spec["scope"] == "asset" and not spec.get("dd"):
            raise ConfigError(f"fact {name}: an asset-level fact needs a 'dd' question")
        if spec.get("mvp", "none") not in MVP_SOURCES:
            raise ConfigError(f"fact {name}: mvp must be one of {list(MVP_SOURCES)}")
    cluster_axis = cfg.raw.get("cluster_axis", {})
    if set(cluster_axis) != set(cfg.clusters) or set(cluster_axis.values()) - {"science", "commercial"}:
        raise ConfigError("cluster_axis must set the science/commercial axis for every cluster")
    for item in cfg.items.values():
        _only_keys(item, _ITEM_KEYS, f"item {item['id']}")
        if item.get("axis") not in ("science", "commercial"):
            raise ConfigError(f"item {item['id']}: axis must be science or commercial")
        for color in ("red", "green", "strong_green"):
            if color in item:
                _check_cond(item[color], cfg, f"item {item['id']}.{color}")
        if "strong_green" in item and "green" not in item:
            raise ConfigError(f"item {item['id']}: strong_green without green")
        share = item.get("strong_share_assumption")
        if share is not None and not (isinstance(share, (int, float)) and 0 <= share <= 1):
            raise ConfigError(f"item {item['id']}: strong_share_assumption must be a number from 0 to 1")
        for name in item.get("evidence_facts", []):
            if name not in cfg.facts:
                raise ConfigError(f"item {item['id']}.evidence_facts: unknown fact '{name}'")
    seen = set()
    for rule in cfg.rules:
        where = f"rule {rule['id']}"
        _only_keys(rule, _RULE_KEYS, where)
        if rule["id"] in seen:
            raise ConfigError(f"{where}: defined twice")
        seen.add(rule["id"])
        if rule["tier"] not in ("kill", "strong", "warning", "note"):
            raise ConfigError(f"{where}: unknown tier {rule['tier']}")
        cluster = rule.get("cluster")
        if cluster is not None and cluster not in cfg.clusters:
            raise ConfigError(f"{where}: unknown cluster {cluster}")
        if rule["tier"] != "kill" and cluster is None and rule.get("axis") not in ("science", "commercial"):
            raise ConfigError(f"{where}: a rule without a cluster needs axis (science or commercial)")
        if rule.get("grounds") is not None and (rule["tier"] != "kill" or rule["grounds"] not in GROUNDS
                                                 or GROUNDS_VERDICT[rule["grounds"]] != DNI):
            raise ConfigError(f"{where}: grounds is for kill rules and must be a Do Not Invest grounds key")
        if rule["tier"] == "kill" and (cluster is not None or "absorbed_by" in rule):
            raise ConfigError(f"{where}: kill rules are not in clusters and are not absorbed")
        if ("absorbed_by" in rule) != ("absorbed_when" in rule):
            raise ConfigError(f"{where}: absorbed_by and absorbed_when are used only together")
        if "absorbed_by" in rule:
            if rule["absorbed_by"] not in cfg.items:
                raise ConfigError(f"{where}: absorbed_by points to an unknown item")
            _check_cond(rule["absorbed_when"], cfg, f"{where}.absorbed_when")
        _check_cond(rule["when"], cfg, where)
    for i, con in enumerate(cfg.constraints):
        _only_keys(con, {"message", "when"}, f"constraints[{i}]")
        if not con.get("message") or "when" not in con:
            raise ConfigError(f"constraints[{i}]: 'message' and 'when' are required")
        _check_cond(con["when"], cfg, f"constraints[{i}]")
    derive_targets: dict = {}
    for i, der in enumerate(cfg.derive):
        where = f"derive[{i}]"
        _only_keys(der, {"when", "set"}, where)
        if "when" not in der or not isinstance(der.get("set"), dict) or not der["set"]:
            raise ConfigError(f"{where}: 'when' and a non-empty 'set' are required")
        _check_cond(der["when"], cfg, where)
        for name, value in der["set"].items():
            if name not in cfg.facts or not _value_ok(cfg.facts[name], value):
                raise ConfigError(f"{where}: wrong value {value!r} for fact '{name}'")
            if derive_targets.setdefault(name, value) != value:
                raise ConfigError(f"{where}: fact '{name}' is derived with different values; "
                                  "the result would depend on rule order")
    for name, ids in cfg.variants.items():
        for item_id in ids:
            if item_id not in cfg.items:
                raise ConfigError(f"Variant {name}: unknown item '{item_id}'")
    for i, cap in enumerate(cfg.raw.get("caps", [])):
        _only_keys(cap, {"id", "when", "reason", "finding"}, f"caps[{i}]")
        _check_cond(cap["when"], cfg, f"caps[{i}]")
    _check_reference(cfg)


def _check_cond(cond: Any, cfg: Config, where: str) -> None:
    if not isinstance(cond, dict):
        raise ConfigError(f"{where}: a condition must be a dict, got {cond!r}")
    kinds = [k for k in ("all", "any", "not", "fact") if k in cond]
    if len(kinds) != 1:
        raise ConfigError(f"{where}: a condition must have exactly one of all / any / not / fact: {cond!r}")
    kind = kinds[0]
    if kind in ("all", "any"):
        if set(cond) != {kind} or not isinstance(cond[kind], list) or not cond[kind]:
            raise ConfigError(f"{where}: '{kind}' must be a non-empty list with no other keys")
        for sub in cond[kind]:
            _check_cond(sub, cfg, where)
        return
    if kind == "not":
        if set(cond) != {"not"}:
            raise ConfigError(f"{where}: 'not' cannot have other keys")
        _check_cond(cond["not"], cfg, where)
        return
    name = cond["fact"]
    if name not in cfg.facts:
        raise ConfigError(f"{where}: unknown fact '{name}'")
    spec = cfg.facts[name]
    extra = set(cond) - {"fact", "default", "known"} - set(_OPS)
    if extra:
        raise ConfigError(f"{where}: unknown keys in an atom {sorted(extra)}: {cond!r}")
    ops = [k for k in cond if k in _OPS]
    if "known" in cond:
        if ops or "default" in cond or not isinstance(cond["known"], bool):
            raise ConfigError(f"{where}: 'known' is used alone and must be true/false: {cond!r}")
        return
    if len(ops) != 1:
        raise ConfigError(f"{where}: an atom must have exactly one operator: {cond!r}")
    op, operand = ops[0], cond[ops[0]]
    if op == "in":
        if not isinstance(operand, list) or not operand:
            raise ConfigError(f"{where}: 'in' needs a non-empty list: {cond!r}")
        operands = operand
    else:
        operands = [operand]
    if isinstance(operand, dict):                      # comparison with another fact
        other = operand.get("fact")
        if set(operand) != {"fact"} or other not in cfg.facts:
            raise ConfigError(f"{where}: a fact reference looks like {{fact: name}}: {cond!r}")
        numeric = ("int", "number")
        if spec["type"] not in numeric or cfg.facts[other]["type"] not in numeric or "default" in cond:
            raise ConfigError(f"{where}: only two numeric facts without default can be compared: {cond!r}")
        return
    for v in operands:
        if not _value_ok(spec, v):
            raise ConfigError(f"{where}: '{v!r}' is not an allowed value of fact {name}")
    if op in _ORDER_OPS and spec["type"] not in ("int", "number"):
        raise ConfigError(f"{where}: operator {op} is only for numbers: {cond!r}")
    if "default" in cond and not _value_ok(spec, cond["default"]):
        raise ConfigError(f"{where}: wrong default {cond['default']!r} for fact {name}")


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------
def check_facts(cfg: Config, facts: dict | None) -> dict:
    """Copy without None. Unknown names and wrong values are errors."""
    clean = {}
    for name, value in (facts or {}).items():
        if name not in cfg.facts:
            raise FactError(f"Unknown fact '{name}'")
        if value is None:
            continue
        spec = cfg.facts[name]
        if not _value_ok(spec, value):
            expected = {"bool": "true/false", "int": "an integer", "number": "a finite number",
                        "enum": f"one of {spec.get('values')}"}[spec["type"]]
            if spec["type"] in ("int", "number"):
                high = spec.get("max")
                expected += f" from {spec.get('min', 0)}" + (f" to {high}" if high is not None else "")
            raise FactError(f"{name}: expected {expected}, got {value!r}")
        clean[name] = value
    return clean


def derive_with_sources(cfg: Config, facts: dict) -> tuple[dict, dict]:
    """Consequences of known facts: ({name: value}, {name: explicit source facts})."""
    known, derived, sources = dict(facts), {}, {}
    changed = True
    while changed:
        changed = False
        for rule in cfg.derive:
            if eval_cond(rule["when"], known) is not True:
                continue
            origin: set = set()
            for name in deciding_facts(rule["when"], known):
                origin |= set(sources.get(name, [name]))      # a derived fact unfolds to explicit ones
            for name, value in rule["set"].items():
                if name not in known:
                    known[name] = derived[name] = value
                    sources[name] = sorted(origin)
                    changed = True
    return derived, sources


def derive_facts(cfg: Config, facts: dict) -> dict:
    """Consequences that follow from known facts: {name: value}. Explicit facts are not overwritten."""
    return derive_with_sources(cfg, facts)[0]


def validate_facts(cfg: Config, facts: dict | None) -> dict:
    """Checked facts together with derived ones. A contradictory set is an error."""
    clean = check_facts(cfg, facts)
    clean.update(derive_facts(cfg, clean))
    for con in cfg.constraints:
        if eval_cond(con["when"], clean) is True:
            raise FactError(f"Contradictory facts: {con['message']}")
    return clean


# ---------------------------------------------------------------------------
# Three-valued condition logic
# ---------------------------------------------------------------------------
def eval_cond(cond: dict, facts: dict) -> bool | None:
    """True, False or None (unknown). Unknown never becomes True by itself."""
    if "all" in cond:
        results = [eval_cond(c, facts) for c in cond["all"]]
        if any(r is False for r in results):
            return False
        if any(r is None for r in results):
            return None
        return True
    if "any" in cond:
        results = [eval_cond(c, facts) for c in cond["any"]]
        if any(r is True for r in results):
            return True
        if any(r is None for r in results):
            return None
        return False
    if "not" in cond:
        inner = eval_cond(cond["not"], facts)
        return None if inner is None else (not inner)
    value = facts.get(cond["fact"])
    if "known" in cond:
        return (value is not None) == cond["known"]
    if value is None:
        if "default" not in cond:
            return None
        value = cond["default"]
    op = next(k for k in cond if k in _OPS)
    operand = cond[op]
    if isinstance(operand, dict):                      # comparison with another fact
        operand = facts.get(operand["fact"])
        if operand is None:
            return None
    return bool(_OPS[op](value, operand))


def facts_in(cond: Any) -> set[str]:
    if not isinstance(cond, dict):
        return set()
    if "all" in cond or "any" in cond:
        out: set[str] = set()
        for sub in cond.get("all", []) + cond.get("any", []):
            out |= facts_in(sub)
        return out
    if "not" in cond:
        return facts_in(cond["not"])
    if "fact" not in cond:
        return set()
    out = {cond["fact"]}
    for key in _OPS:
        if isinstance(cond.get(key), dict):
            out.add(cond[key]["fact"])
    return out


def deciding_facts(cond: dict, facts: dict, target: bool = True) -> list[str]:
    """Known facts that actually made the condition true (or false).

    For 'any' only the branches that fired are taken; facts from branches that did not
    affect the result do not go into the report.
    """
    def walk(c: dict, want: bool) -> set[str]:
        if "all" in c or "any" in c:
            kind = "all" if "all" in c else "any"
            subs = c[kind]
            # all=True and any=False rest on all branches; otherwise only on those that gave the result
            every = (kind == "all") == want
            out: set[str] = set()
            for sub in subs:
                if every or eval_cond(sub, facts) is want:
                    out |= walk(sub, want)
            return out
        if "not" in c:
            return walk(c["not"], not want)
        return {f for f in facts_in(c) if f in facts}

    if eval_cond(cond, facts) is not target:
        return []
    return sorted(walk(cond, target))


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------
def item_color(item: dict, facts: dict) -> str:
    """Order: red → green → yellow (something is known) → unknown."""
    if "red" in item and eval_cond(item["red"], facts) is True:
        return RED
    if "green" in item and eval_cond(item["green"], facts) is True:
        return GREEN
    # evidence_facts: which facts mean "something is known about the item" (yellow, not unknown)
    referenced = set(item.get("evidence_facts") or
                     (facts_in(item.get("red", {})) | facts_in(item.get("green", {}))))
    if any(facts.get(f) is not None for f in referenced):
        return YELLOW
    return UNKNOWN


def item_is_strong(item: dict, facts: dict) -> bool:
    """Whether a green item is a "strong green" (gives more pluses). Unknown does not make it strong."""
    return "strong_green" in item and eval_cond(item["strong_green"], facts) is True


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class Result:
    variant: str
    colors: dict                      # item_id -> G/Y/R/U
    greens: int                       # number of green items
    pos: int                          # pluses (greens × weight)
    neg: int
    diff: int
    verdict: str
    kills: list = field(default_factory=list)        # ids of kill rules
    fired: list = field(default_factory=list)        # all rules that fired
    counted: list = field(default_factory=list)      # (source, points) that actually went into minuses
    suppressed: dict = field(default_factory=dict)   # rule id -> what absorbed it
    reason: str = ""
    evidence: dict = field(default_factory=dict)     # item/rule id -> fact names
    derived: dict = field(default_factory=dict)      # facts derived from others: name -> value
    derived_from: dict = field(default_factory=dict) # derived fact -> explicit source facts
    axes: dict = field(default_factory=dict)         # axis -> {greens, reds, strong, warnings, rating}
    points: dict = field(default_factory=dict)       # green item -> pluses (1, or 2 for a strong green)
    science_pos: int = 0                             # science-axis pluses (Invest condition)
    grounds: str = ""                                # what the verdict rests on, see GROUNDS
    coverage: dict = field(default_factory=dict)     # how many scorecard items had any data
    config: dict = field(default_factory=dict)       # version and hash of the config used for the verdict
    caps: list = field(default_factory=list)         # caps that lowered Invest to Conditional (review F31/F38/F44/F52)

    def as_dict(self) -> dict:
        return {
            "variant": self.variant, "verdict": self.verdict, "reason": self.reason,
            "greens": self.greens, "pos": self.pos, "neg": self.neg, "diff": self.diff,
            "colors": dict(self.colors), "kills": list(self.kills),
            "fired": list(self.fired), "counted": [list(c) for c in self.counted],
            "suppressed": dict(self.suppressed), "evidence": dict(self.evidence),
            "derived": dict(self.derived), "derived_from": dict(self.derived_from), "axes": dict(self.axes),
            "points": dict(self.points), "science_pos": self.science_pos, "grounds": self.grounds,
            "coverage": dict(self.coverage), "config": dict(self.config), "caps": list(self.caps),
        }


# What the verdict rests on. "Don't know" is separated from "no": Insufficient evidence for lack of confirmation
# (insufficient_evidence) and Do Not Invest for negative evidence (kill, negatives, outweighed). Before 2.3 both were
# the decision "Do Not Invest" and only the grounds told them apart.
GROUNDS = {
    "kill": "a kill rule fired",
    "negatives": "accumulated minuses",
    "outweighed": "minuses outweigh pluses",
    "insufficient_evidence": "not enough confirmation (this is not negative evidence)",
    "science_short": "the picture is positive, but Invest lacks science evidence",
    "balanced": "pluses and minuses are nearly balanced",
    "positive": "pluses outweigh minuses, science evidence is sufficient",
    "capped": "the picture is positive, but a cap limits the verdict to Conditional until a condition is met",
    # 2.7
    "opposite_direction": "drugs approved for this disease act on the same target in the opposite direction: the "
                          "thesis works against validated biology (genetic support for the target says nothing about "
                          "the direction)",
    # 2.5: a market call, not a science call
    "crowded": "the mechanism is already approved for this disease (2 or more drugs) and no advantage of this asset "
               "is shown: another drug of the same kind is not worth backing; proven differentiation would change it",
}
GROUNDS_VERDICT = {"kill": DNI, "crowded": DNI, "opposite_direction": DNI, "negatives": DNI, "outweighed": DNI,
                   "insufficient_evidence": INSUFFICIENT,
                   "science_short": CONDITIONAL, "balanced": CONDITIONAL, "capped": CONDITIONAL, "positive": INVEST}


INSUFFICIENT_KINDS = {
    "no_mechanism_evidence": "no scorecard item is evidence for the mechanism itself (genetics, clinical precedent, "
                             "the asset's own clinical effect or translation chain)",
    "no_asset_data": "nothing is known about the asset itself (phase, own trial results, translation links)",
    "few_pluses": "too few pluses for Conditional",
}


def insufficient_detail(cfg: "Config", res: "Result", flips: list[dict]) -> dict:
    """2.4: why the evidence is insufficient and which single facts would decide it. `kinds` keys INSUFFICIENT_KINDS;
    `would_decide`: one-fact changes from what_would_change that decide it either way (up to Conditional / Invest or
    down to Do Not Invest), unknown facts first, at most 8, each with its scope (mechanism = public data, asset = the
    company)."""
    science_greens = sum(1 for i, c in res.colors.items() if c == GREEN and cfg.items[i].get("mechanism_evidence"))
    kinds = []
    if science_greens == 0:
        kinds.append("no_mechanism_evidence")
    if res.coverage.get("asset_known", 0) == 0:
        kinds.append("no_asset_data")
    if res.greens < cfg.thresholds.get("min_pos_conditional", 1):
        kinds.append("few_pluses")
    up, down, seen = [], [], set()
    for cf in sorted(flips, key=lambda f: (f["from"] is not None, f["scope"] != "mechanism", f["fact"])):
        if cf["verdict_to"] == INSUFFICIENT or cf["action"] != "set" or cf["fact"] in seen \
                or cf["fact"] in ECONOMIC_FACTS:
            continue
        seen.add(cf["fact"])
        row = {"fact": cf["fact"], "label": cf["label"], "scope": cf["scope"], "to": cf["to"],
               "verdict_to": cf["verdict_to"]}
        (up if VERDICT_RANK[cf["verdict_to"]] > VERDICT_RANK[INSUFFICIENT] else down).append(row)
    up = up[:5] + down[:3]                     # what would raise it first, then the public facts that would sink it
    return {"kinds": kinds, "texts": [INSUFFICIENT_KINDS[k] for k in kinds], "would_decide": up}


def cfg_rule_grounds(cfg: "Config", rule_id: str) -> str | None:
    return next((r.get("grounds") for r in cfg.rules if r["id"] == rule_id), None)


def decide_full(pos: int, neg: int, killed: bool, thresholds: dict, greens: int | None = None,
                science_greens: int | None = None, science_pos: int | None = None) -> tuple[str, str, str]:
    """Verdict, explanation and grounds (a GROUNDS key) from pluses, minuses and a kill rule.

    greens: pluses that go into the Conditional condition (pos by default).
    science_greens: number of green items that are evidence for the mechanism itself; None = do not check.
    science_pos: science-axis pluses; None = do not check the min_science_pos_invest threshold.
    Negative evidence is checked first (kill, accumulated minuses, minuses outweighing pluses): when it decides, the
    verdict is Do Not Invest even if evidence is also thin. Insufficient evidence only when it does not.
    """
    greens = pos if greens is None else greens
    diff = pos - neg
    if killed:
        return DNI, "a kill rule fired", "kill"
    if neg >= thresholds["neg_dni"]:
        return DNI, f"minuses accumulated: {neg} (threshold {thresholds['neg_dni']})", "negatives"
    if diff >= thresholds["invest_margin"]:
        if thresholds.get("require_mechanism_green") and science_greens == 0:
            return INSUFFICIENT, (f"pluses − minuses = {diff}, but no green item is evidence for the mechanism "
                                  "itself: not enough science confirmation"), "insufficient_evidence"
        need_items = thresholds.get("min_science_items_invest", 0)
        if science_greens is not None and science_greens < need_items:
            short = thresholds.get("science_short", DNI)
            short = CONDITIONAL if short == CONDITIONAL else INSUFFICIENT
            return short, (f"pluses − minuses = {diff}, but only {science_greens} independent piece(s) of mechanism "
                           f"evidence ({need_items} needed for Invest): one item, however strong, is one piece of "
                           "evidence"), ("science_short" if short == CONDITIONAL else "insufficient_evidence")
        need = thresholds.get("min_science_pos_invest", 0)
        if science_pos is not None and science_pos < need:
            short = thresholds.get("science_short", DNI)
            short = CONDITIONAL if short == CONDITIONAL else INSUFFICIENT    # not negative evidence either way
            return short, (f"pluses − minuses = {diff}, but only {science_pos} science pluses "
                           f"({need} needed for Invest): a second science piece of evidence is missing"), (
                "science_short" if short == CONDITIONAL else "insufficient_evidence")
        return INVEST, f"pluses − minuses = {diff} (threshold {thresholds['invest_margin']})", "positive"
    if diff <= thresholds["dni_margin"]:
        if neg == 0:
            return INSUFFICIENT, f"pluses − minuses = {diff}: not enough confirmation", "insufficient_evidence"
        return DNI, f"pluses − minuses = {diff}: minuses outweigh", "outweighed"
    min_greens = thresholds.get("min_pos_conditional", 1)
    if greens < min_greens:
        return INSUFFICIENT, (f"pluses − minuses = {diff}, but only {greens} pluses "
                              f"({min_greens} needed for Conditional): not enough confirmation"), "insufficient_evidence"
    if (thresholds.get("conditional_requires_mechanism") and thresholds.get("require_mechanism_green")
            and science_greens == 0):
        # without mechanism evidence the same pluses with no minus give Insufficient evidence;
        # a minus cannot make the verdict better
        return INSUFFICIENT, (f"pluses − minuses = {diff}, but no green item is evidence for the mechanism "
                              "itself: not enough science confirmation"), "insufficient_evidence"
    return CONDITIONAL, f"pluses − minuses = {diff}: pluses and minuses are nearly balanced", "balanced"


def decide(pos: int, neg: int, killed: bool, thresholds: dict, greens: int | None = None,
           science_greens: int | None = None, science_pos: int | None = None) -> tuple[str, str]:
    """Verdict and explanation. Same as decide_full, without the grounds."""
    return decide_full(pos, neg, killed, thresholds, greens, science_greens, science_pos)[:2]


def _red_because_of(item: dict, facts: dict, event: dict) -> bool:
    """Whether the item is red because of the event: without its facts it would not be red.

    If the item is red for another reason too, the rule about the event counts separately.
    Otherwise adding a negative fact would reduce minuses.
    """
    without = {k: v for k, v in facts.items() if k not in facts_in(event)}
    return item_color(item, without) != RED


def score(
    cfg: Config,
    facts: dict,
    variant: str | Iterable[str] | None = None,
    *,
    disabled_items: Iterable[str] = (),
    disabled_rules: Iterable[str] = (),
    thresholds: dict | None = None,
    weights: dict | None = None,
    use_clusters: bool = True,
) -> Result:
    if variant is None:
        variant = cfg.default_variant
    derived, derived_from = derive_with_sources(cfg, check_facts(cfg, facts))
    facts = validate_facts(cfg, facts)

    def explicit(names: list) -> list:
        """Evidence in the report: a derived fact is replaced by the explicit facts it was derived from."""
        out: set = set()
        for name in names:
            out |= set(derived_from.get(name, [name]))
        return sorted(out)

    unknown_keys = set(thresholds or {}) - _THRESHOLD_KEYS - set(_OPTIONAL_THRESHOLDS)
    if unknown_keys:
        raise ConfigError(f"Unknown thresholds: {sorted(unknown_keys)}")
    thresholds = {**cfg.thresholds, **(thresholds or {})}
    if set(weights or {}) - set(cfg.weights):
        raise ConfigError(f"Unknown weights: {sorted(set(weights) - set(cfg.weights))}")
    w = {**cfg.weights, **(weights or {})}
    off_items, off_rules = set(disabled_items), set(disabled_rules)
    if off_items - set(cfg.items):
        raise ConfigError(f"Unknown items in disabled_items: {sorted(off_items - set(cfg.items))}")
    if off_rules - cfg.rule_ids:
        raise ConfigError(f"Unknown rules in disabled_rules: {sorted(off_rules - cfg.rule_ids)}")

    item_ids = [i for i in cfg.variant_items(variant) if i not in off_items]
    colors, evidence = {}, {}
    for item_id in item_ids:
        item = cfg.items[item_id]
        color = item_color(item, facts)
        colors[item_id] = color
        if color == RED:
            evidence[item_id] = explicit(deciding_facts(item["red"], facts))
        elif color == GREEN:
            evidence[item_id] = explicit(deciding_facts(item["green"], facts))

    greens = sum(1 for c in colors.values() if c == GREEN)
    item_points = {i: (w["green_strong"] if item_is_strong(cfg.items[i], facts) else w["green"])
                   for i, c in colors.items() if c == GREEN}
    pos = sum(item_points.values())
    counted = [(f"item:{i}", w["red"]) for i, c in colors.items() if c == RED]

    kills, fired, by_cluster, suppressed = [], [], {}, {}
    for rule in cfg.rules:
        if rule["id"] in off_rules:
            continue
        if eval_cond(rule["when"], facts) is not True:
            continue
        fired.append(rule["id"])
        evidence[rule["id"]] = explicit(deciding_facts(rule["when"], facts))
        if rule["tier"] == "kill":
            kills.append(rule["id"])
            continue
        if rule["tier"] == "note":
            # 2.4: shown in the report, never counted (absence of evidence is not negative evidence)
            continue
        absorber = rule.get("absorbed_by")
        if (absorber is not None and colors.get(absorber) == RED
                and eval_cond(rule["absorbed_when"], facts) is True
                and _red_because_of(cfg.items[absorber], facts, rule["absorbed_when"])):
            suppressed[rule["id"]] = f"item:{absorber}"     # the red item already counts the same event
            continue
        points = w[rule["tier"]]
        cluster = rule.get("cluster") if use_clusters else None
        if cluster is None:
            counted.append((f"rule:{rule['id']}", points))
        else:
            by_cluster.setdefault(cluster, []).append((rule["id"], points))

    for cluster, members in by_cluster.items():
        members.sort(key=lambda m: -m[1])           # stable: the first strongest
        top_id, top_points = members[0]
        counted.append((f"rule:{top_id}", top_points))
        for rule_id, _ in members[1:]:
            suppressed[rule_id] = f"cluster:{cluster}"

    neg = sum(points for _, points in counted)
    science_greens = sum(1 for i, c in colors.items()
                         if c == GREEN and cfg.items[i].get("mechanism_evidence"))
    science_pos = sum(p for i, p in item_points.items() if cfg.items[i]["axis"] == "science")
    verdict, reason, grounds = decide_full(pos, neg, bool(kills), thresholds, pos, science_greens, science_pos)
    if kills:
        own = {cfg_rule_grounds(cfg, k) for k in kills}
        if len(own) == 1 and None not in own:          # every kill rule that fired names the same grounds (crowded)
            grounds = own.pop()
            reason = "; ".join(next(r["name"] for r in cfg.rules if r["id"] == k) for k in kills)
    known = [i for i, c in colors.items() if c != UNKNOWN]
    coverage = {"items_known": len(known), "items_total": len(colors),
                "mechanism_known": sum(1 for i in known if cfg.items[i]["scope"] == "mechanism"),
                "mechanism_total": sum(1 for i in colors if cfg.items[i]["scope"] == "mechanism"),
                "asset_known": sum(1 for i in known if cfg.items[i]["scope"] == "asset"),
                "asset_total": sum(1 for i in colors if cfg.items[i]["scope"] == "asset")}

    # two axes: the same items and rules split into "science" and "commercial and execution"
    rules_by_id = {r["id"]: r for r in cfg.rules}
    cluster_axis = cfg.raw["cluster_axis"]
    axes = {a: {"greens": 0, "reds": 0, "strong": 0, "warnings": 0} for a in ("science", "commercial")}
    for i, c in colors.items():
        if c == GREEN:
            axes[cfg.items[i]["axis"]]["greens"] += 1
        elif c == RED:
            axes[cfg.items[i]["axis"]]["reds"] += 1
    for source, _ in counted:
        kind, _, ident = source.partition(":")
        if kind == "rule":
            rule = rules_by_id[ident]
            axis = rule.get("axis") or cluster_axis[rule["cluster"]]
            axes[axis]["strong" if rule["tier"] == "strong" else "warnings"] += 1
    for a in axes.values():
        if a["reds"] or a["strong"] or a["greens"] == 0:
            a["rating"] = "weak"
        elif a["greens"] >= 2:
            a["rating"] = "strong"
        else:
            a["rating"] = "mixed"
    caps = []
    if verdict == INVEST:
        for cap in cfg.raw.get("caps", []):
            if eval_cond(cap["when"], facts) is True:
                caps.append({"id": cap["id"], "reason": cap["reason"],
                             "facts": explicit(deciding_facts(cap["when"], facts))})
        if (thresholds.get("invest_requires_asset_data") and coverage["asset_known"] == 0
                and coverage["items_known"] < 5):
            caps.append({"id": "cap_asset_data", "facts": [],
                         "reason": f"no asset-level item is known and only {coverage['items_known']} of "
                                   f"{coverage['items_total']} items have data (answer the asset questions first)"})
        if caps:
            verdict, grounds = CONDITIONAL, "capped"
            reason += "; capped at Conditional: " + "; ".join(c["reason"] for c in caps)
    name = variant if isinstance(variant, str) else "custom"
    return Result(name, colors, greens, pos, neg, pos - neg, verdict, kills, fired,
                  counted, suppressed, reason, evidence, derived, derived_from, axes,
                  item_points, science_pos, grounds, coverage,
                  {"version": str(cfg.raw.get("version")), "sha256": cfg.sha256}, caps)


# ---------------------------------------------------------------------------
# "What would change the verdict" and due-diligence questions
# ---------------------------------------------------------------------------
def _probe_values(spec: dict) -> list:
    """Values to try: all for bool and enum, only those listed in probes for numbers."""
    if spec["type"] == "bool":
        return [True, False]
    if spec["type"] == "enum":
        return list(spec["values"])
    return list(spec.get("probes", []))


def counterfactuals(cfg: Config, facts: dict, variant: str | Iterable[str] | None = None, **kw) -> list[dict]:
    """Single-fact changes that flip the verdict.

    Tries: (a) hide a known fact; (b) add or replace a value
    from the probes list. Returns only the changes after which the verdict differs.
    Changes that make the fact set contradictory are skipped.
    """
    facts = check_facts(cfg, facts)                 # explicit facts only; derived ones are recomputed
    effective = validate_facts(cfg, facts)
    base = score(cfg, facts, variant, **kw).verdict
    out = []
    for name, spec in cfg.facts.items():
        current = effective.get(name)
        trials = []
        if name in facts:
            trials.append(("hide", None))
        for value in _probe_values(spec):
            if value != current:
                trials.append(("set", value))
        for action, value in trials:
            changed = {k: v for k, v in facts.items() if k != name}
            if value is not None:
                changed[name] = value
            try:
                new = score(cfg, changed, variant, **kw).verdict
            except FactError:
                continue
            if new != base:
                out.append({
                    "fact": name, "label": spec["label"], "scope": spec["scope"],
                    "action": action, "from": current, "to": value,
                    "verdict_from": base, "verdict_to": new,
                })
    return out


def dd_questions(cfg: Config, facts: dict, variant: str | Iterable[str] | None = None, **kw) -> list[dict]:
    """Due-diligence questions from everything unknown at the asset level.

    Several facts can share one question; it is asked once.
    critical = the answer to this question alone can flip the verdict.
    """
    facts = validate_facts(cfg, facts)
    flips: dict = {}
    for cf in counterfactuals(cfg, facts, variant, **kw):
        if cf["action"] == "set" and cf["from"] is None:
            flips.setdefault(cf["fact"], []).append((cf["to"], cf["verdict_to"]))
    grouped: dict = {}
    for name, spec in cfg.facts.items():
        if spec["scope"] != "asset" or name in facts or not spec.get("dd"):
            continue
        q = grouped.setdefault(spec["dd"], {"question": spec["dd"], "facts": [], "sources": [],
                                            "critical": False, "flips": []})
        q["facts"].append(name)
        if spec["source"] not in q["sources"]:
            q["sources"].append(spec["source"])
        if name in flips:
            q["critical"] = True
            q["flips"] += [(name, value, verdict) for value, verdict in flips[name]]
    out = list(grouped.values())
    out.sort(key=lambda q: (not q["critical"], q["facts"][0]))
    return out


def top_dd_questions(cfg: Config, facts: dict, variant: str | Iterable[str] | None = None,
                     limit: int = 10, **kw) -> list[dict]:
    """5 to 10 questions for the report.

    First comes "what evidence would kill the program": the facts each of which alone
    flips the verdict to Do Not Invest. Then questions that can change the verdict,
    then translation chain links, then the rest of the unknown asset-level facts.
    """
    killers = [cf for cf in counterfactuals(cfg, facts, variant, **kw)
               if cf["verdict_to"] == DNI and cf["action"] == "set"]
    out = []
    if killers:
        seen, items = set(), []
        for cf in killers:
            if cf["fact"] not in seen:
                seen.add(cf["fact"])
                items.append(cf["label"])
        out.append({"question": "What evidence would kill the program?", "facts": sorted(seen),
                    "critical": True, "kill_evidence": items})
    chain = {"link_exposure", "link_target_engagement", "link_pd_response", "animal_model_response"}
    rest = dd_questions(cfg, facts, variant, **kw)
    rest.sort(key=lambda q: (not q["critical"], not (set(q["facts"]) & chain), q["facts"][0]))
    out.extend(rest)
    return out[:limit]


# ---------------------------------------------------------------------------
# Reference probability (does not affect the verdict)
# ---------------------------------------------------------------------------
_REF_CLASSES = {"genetics": {"mendelian", "gwas", "somatic", "none"},
                "precedent": {"related", "absent"}, "track": {"green", "absent"}}


def _check_reference(cfg: Config) -> None:
    ref = cfg.raw.get("reference") or {}
    table = ref.get("launch_by_evidence")
    if table is None:
        return
    seen = set()
    for cell in table.get("cells", []):
        where = f"reference.launch_by_evidence: cell {cell.get('id')!r}"
        if not cell.get("id") or cell["id"] in seen or not cell.get("label"):
            raise ConfigError(f"{where}: a unique id and a label are required")
        seen.add(cell["id"])
        for key, values in (cell.get("match") or {}).items():
            if key not in _REF_CLASSES or not isinstance(values, list) or set(values) - _REF_CLASSES[key]:
                raise ConfigError(f"{where}: wrong condition match.{key}: {values!r}")
        for key in ("from_ph1", "from_ph2", "from_ph3"):
            rng = cell.get(key)
            if rng is not None and not (isinstance(rng, list) and len(rng) == 2 and 0 <= rng[0] <= rng[1] <= 1):
                raise ConfigError(f"{where}: {key} must be [lower, upper] within 0–1 or null")
    if "all" not in seen:
        raise ConfigError("reference.launch_by_evidence: the 'all' cell (all pairs) is required")


def evidence_classes(cfg: Config, facts: dict) -> dict:
    """Class of the three mechanism-level pieces of evidence, as the reference probability table sees them."""
    facts = validate_facts(cfg, facts)
    gs = facts.get("genetic_support")
    # mendelian_subtype (2.3) has no class of its own in Minikel's table: "unknown" (the broader cell), never the
    # Mendelian rate, which is for evidence about the disease itself
    genetics = {None: "unknown", "no_data": "unknown", "mendelian": "mendelian", "gwas": "gwas",
                "somatic_driver": "somatic", "mendelian_subtype": "unknown"}.get(gs, "none")
    color = item_color(cfg.items["clinical_precedent"], facts)
    precedent = "unknown" if color == UNKNOWN else "related" if color == GREEN else "absent"
    color = item_color(cfg.items["indication_track_record"], facts)
    track = "unknown" if color == UNKNOWN else "green" if color == GREEN else "absent"
    return {"genetics": genetics, "precedent": precedent, "track": track}


def reference_cell_key(cfg: Config, facts: dict) -> str:
    """id of the first table cell matching the known evidence (unknown does not narrow the cell)."""
    classes = evidence_classes(cfg, facts)
    for cell in cfg.raw["reference"]["launch_by_evidence"]["cells"]:
        if all(classes[key] in values for key, values in (cell.get("match") or {}).items()):
            return cell["id"]
    return "all"


def reference_probability(cfg: Config, facts: dict) -> dict:
    """Two independent references for the chance of reaching launch. Not part of the verdict.

    evidence: share of historical target + disease pairs with the same mechanism evidence that reached
              launch (Minikel 2024). Range: from the conservative to the optimistic precedent estimate.
    stage:    baseline approval share for the stage and disease type (BIO 2021), regardless of evidence.
    """
    ref = cfg.raw.get("reference") or {}
    clean = validate_facts(cfg, facts)
    out: dict = {"evidence": None, "stage": None, "caveats": []}
    table = ref.get("launch_by_evidence")
    if table:
        by_id = {c["id"]: c for c in table["cells"]}
        cell = by_id[reference_cell_key(cfg, facts)]
        phase = clean.get("phase")
        key = {"ph2": "from_ph2", "ph3": "from_ph3", "filed": "from_ph3"}.get(phase, "from_ph1")
        if cell.get(key) is None:                       # too few pairs at this stage: take the estimate from Phase I
            key = "from_ph1"
            if phase in ("ph2", "ph3", "filed"):
                out["caveats"].append("Too few late-stage pairs in this cell; the chance from Phase I is shown.")
        out["evidence"] = {
            "cell": cell["id"], "label": cell["label"], "n": cell.get("n"), "launched": cell.get("launched"),
            "range": list(cell[key]) if cell.get(key) else None,
            "from": {"from_ph1": "Phase I", "from_ph2": "Phase II", "from_ph3": "Phase III"}[key],
            "base": list(by_id["all"][key]) if by_id["all"].get(key) else None,
            "classes": evidence_classes(cfg, facts), "source": table.get("source"),
        }
        if phase == "preclinical":
            out["caveats"].append("The asset is preclinical: shares are computed for pairs that already reached Phase I.")
        if clean.get("genetic_support") == "contradicts":
            out["caveats"].append("Genetics contradicts causality: the table has no such pairs, the reference is inflated.")
        if clean.get("genetic_support") == "no_data":
            out["caveats"].append("The disease has no genetic data: the table was computed on diseases that have it; "
                                  "in diseases without it the baseline launch share is higher (17% vs 12%).")
        if clean.get("indication_graveyard") is True:
            out["caveats"].append("The disease is on the 'graveyard' list: the table does not account for it, the reference is inflated.")
        if phase == "filed":
            out["caveats"].append("Filed for approval: the share is taken for pairs that reached Phase III; it is understated.")
    stage = ref.get("stage_loa")
    if stage and clean.get("phase") in stage.get("phase_keys", {}):
        if clean.get("oncology") is True:
            seg = "oncology"
        elif clean.get("oncology") is False and clean.get("rare_disease") is True:
            seg = "rare_non_oncology"
        elif clean.get("oncology") is False:
            seg = "non_oncology"
        else:
            seg = "all"
        col = stage["phase_keys"][clean["phase"]]
        out["stage"] = {"segment": seg, "label": stage["segments"][seg]["label"], "from": col,
                        "loa": stage["segments"][seg][col], "all": stage["segments"]["all"][col],
                        "source": stage.get("source")}
    return out


# ---------------------------------------------------------------------------
# Pipeline interface: fact catalog, claims → facts, one result for the scores and verdicts tables
# ---------------------------------------------------------------------------
_TIER_RANK = {None: 0, "warning": 1, "strong": 2, "kill": 3}
ORIGIN_PRIORITY = {"llm": 1, "structured": 2, "user": 3}
ECONOMIC_FACTS = ("economics_negative", "economics_weak", "required_price_unrealistic", "runway_short",
                  "round_overpriced")


def value_effect(cfg: Config, fact: str, value: Any) -> dict:
    """What a fact value does ON ITS OWN when nothing else is known.

    tier: kill, strong (strong minus or red item), warning or None.
    Exactly these values are dangerous if made up: one claim is enough to change the verdict.
    Values that act only together with other facts (disease severity, stage) are not included.
    """
    if fact not in cfg.facts or not _value_ok(cfg.facts[fact], value):
        raise FactError(f"{fact}: wrong value {value!r}")
    res = score(cfg, {fact: value})
    rules = {r["id"]: r for r in cfg.rules}
    reds = [i for i, c in res.colors.items() if c == RED]
    if res.kills:
        tier = "kill"
    elif reds or any(rules[r]["tier"] == "strong" for r in res.fired):
        tier = "strong"
    elif any(rules[r]["tier"] != "note" for r in res.fired):
        tier = "warning"
    else:
        tier = None
    return {"tier": tier, "rules": list(res.fired), "red_items": reds,
            "green_items": [i for i, c in res.colors.items() if c == GREEN]}


def is_absence(spec: dict, value: Any) -> bool:
    """A value that asserts absence: a zero counter or "none". Only a complete source proves it."""
    if spec["type"] == "int":                # counters; years, shares and percentages are not absence
        return value == 0
    if spec["type"] == "enum":
        return value in ("none", "no_data")
    return False


def fact_catalog(cfg: Config) -> dict:
    """Tag dictionary for the "organize" stage: the single list of facts the scorer accepts.

    Generated from benchmarks.yaml; not edited separately.
    """
    out = {}
    for name, spec in cfg.facts.items():
        if spec["type"] == "bool":
            values = [True, False]
        elif spec["type"] == "enum":
            values = list(spec["values"])
        else:
            values = None
        entry = {"label": spec["label"], "type": spec["type"], "level": spec["scope"],
                 "mvp_source": spec.get("mvp", "none"), "source": spec["source"]}
        if values is not None:
            entry["values"] = values
            critical = {str(v): value_effect(cfg, name, v)["tier"] for v in values}
            entry["critical_values"] = {k: t for k, t in critical.items() if t in ("kill", "strong")}
        else:
            entry["min"], entry["max"] = spec.get("min", 0), spec.get("max")
            probes = spec.get("probes", [])
            entry["critical_values"] = {str(v): t for v in probes
                                        if (t := value_effect(cfg, name, v)["tier"]) in ("kill", "strong")}
        entry["absence_values"] = ([0] if spec["type"] == "int"
                                   else [] if values is None else [v for v in values if is_absence(spec, v)])
        if spec.get("dd"):
            entry["dd"] = spec["dd"]
        out[name] = entry
    return out


NEGATION = re.compile(
    r"\bnot\s+(?:\w+\s+){0,2}(?:due\s+to|because\s+of|related\s+to|attributed\s+to|for\s+reasons\s+of|caused\s+by)\b"
    r"|\bunrelated\s+to\b|\bno\s+(?:new\s+)?(?:safety|efficacy)\s+(?:concerns?|signals?|issues?)\b"
    r"|\bnot\s+(?:a\s+)?(?:result|consequence)\s+of\b|\bwas\s+not\s+(?:stopped|terminated)\s+for\b",
    re.I)


def is_negated(quote: str | None) -> bool:
    """'not due to lack of efficacy' must not confirm an efficacy label (review F34)."""
    return bool(quote) and bool(NEGATION.search(quote))


def _recount(claim: dict) -> tuple[int | None, list[str]]:
    """Count facts from LLM trial evidence again: distinct drugs with a verified, non-negated quote.

    A trial stopped only because another trial stopped does not count (run review, BACE1). Returns (None, [])
    when the claim carries no per-drug sources.
    """
    srcs = [x for x in (claim.get("sources") or []) if isinstance(x, dict) and x.get("drugs")]
    if not srcs:
        return None, []
    drugs, dropped = set(), []
    for x in srcs:
        if x.get("verified") is False:
            dropped.append(f"{x.get('id')}: quote not found")
        elif is_negated(x.get("quote")):
            dropped.append(f"{x.get('id')}: negated quote")
        elif x.get("stopped_due_to_other_trial"):
            dropped.append(f"{x.get('id')}: stopped only because another trial stopped")
        else:
            drugs |= {str(d).lower() for d in x["drugs"]}
    return len(drugs), dropped


def _effect(cfg: Config, facts: dict) -> tuple:
    """What decides the verdict: verdict, counted kill/strong rules and red items."""
    try:
        res = score(cfg, facts)
    except FactError:
        return None
    rules = {r["id"]: r for r in cfg.rules}
    strong = {s.split(":", 1)[1] for s, _ in res.counted if s.startswith("rule:")
              and rules[s.split(":", 1)[1]]["tier"] == "strong"}
    reds = {i for i, c in res.colors.items() if c == RED}
    return res.verdict, frozenset(res.kills), frozenset(strong), frozenset(reds)


def facts_from_claims(cfg: Config, claims: list[dict]) -> dict:
    """Turns stage-3 claims into facts for the scorer. Invents and derives nothing itself.

    Claim: {"id", "fact", "value", "origin": user | structured | llm, "evidence_type": source | inference,
            "verified": bool, "confirmed": bool, "quote": str, "doc_ids": [...], "sources": [...],
            "lower_bound": bool}.

    Rules (version 1.1 rules 1–4 and 6, plus the review fixes F32–F36):
      1. The fact name and value must come from the catalog; otherwise the claim is rejected.
      2. An LLM inference (evidence_type = inference) does not become a fact: it stays in the report.
      3. An LLM claim without a verified quote (verified) is rejected; so is a negated quote (F34).
      4. The LLM cannot assert absence (a zero counter, "none"): it cannot be established from text.
         Economic facts never come from an LLM: they are computed by the economics module.
      5. Counts from trial evidence are recounted: distinct drugs with a verified, non-negated quote; a trial
         stopped only because another trial stopped does not count. A count that is only a lower bound waits (F36).
      6. If sources disagree, the higher priority wins: user > structured > llm. A disagreement
         at the top level makes the fact unknown.
      7. An LLM value waits for a human (confirmed) if, IN THE CONTEXT of all other facts, it changes the verdict
         or switches a kill rule, a strong minus or a red item on OR off (F32, F33). Several documents labelled by
         one LLM run are not independent confirmation (F34), so doc_ids no longer confirm by themselves.
    """
    by_fact: dict = {}
    rejected, pending = [], []
    for claim in claims:
        cid, name, value = claim.get("id"), claim.get("fact"), claim.get("value")
        origin = claim.get("origin")

        def reject(reason: str) -> None:
            rejected.append({"claim": cid, "fact": name, "reason": reason})

        if name not in cfg.facts:
            reject("unknown fact")
            continue
        if origin not in ORIGIN_PRIORITY:
            reject(f"origin must be one of {sorted(ORIGIN_PRIORITY)}")
            continue
        spec = cfg.facts[name]
        if claim.get("evidence_type", "source") != "source":
            reject("an LLM inference, not a source statement")
            continue
        if origin == "llm":
            if name in ECONOMIC_FACTS:
                reject("economic facts are computed by the economics module, never taken from an LLM")
                continue
            if not claim.get("verified"):
                reject("quote not found in the document")
                continue
            if is_negated(claim.get("quote")):
                reject("the quote is negated (e.g. 'not due to ...')")
                continue
            n, dropped = _recount(claim) if spec["type"] == "int" else (None, [])
            if n is not None and n != value:
                claim = dict(claim, value=n, recount_note=f"recounted {n} distinct drug(s) from {value}; "
                                                           f"dropped: {dropped}")
                value = n
        if value is None or not _value_ok(spec, value):
            reject(f"wrong value {value!r}")
            continue
        if origin == "llm" and is_absence(spec, value):
            reject("absence cannot be established from text; a complete structured source is required")
            continue
        if claim.get("lower_bound") and spec["type"] == "int" and origin != "user":
            pending.append({"fact": name, "value": value, "claims": [cid], "tier": None,
                            "reason": "the count is only a lower bound (incomplete list); confirm the full count"})
            continue
        by_fact.setdefault(name, []).append(claim)

    chosen, conflicts = {}, []
    for name, group in by_fact.items():
        top = max(ORIGIN_PRIORITY[c["origin"]] for c in group)
        best = [c for c in group if ORIGIN_PRIORITY[c["origin"]] == top]
        values = []
        for c in best:
            if c["value"] not in values:
                values.append(c["value"])
        if len(values) > 1:
            conflicts.append({"fact": name, "values": values, "claims": [c.get("id") for c in best]})
            continue
        chosen[name] = best

    facts = {n: b[0]["value"] for n, b in chosen.items() if b[0]["origin"] != "llm"}
    used = {n: [c.get("id") for c in b] for n, b in chosen.items() if b[0]["origin"] != "llm"}
    try:
        validate_facts(cfg, facts)
    except FactError:
        pass  # contradictory structured/user facts: scoring will raise and show it
    for name in sorted(n for n, b in chosen.items() if b[0]["origin"] == "llm"):
        best = chosen[name]
        value = best[0]["value"]
        trial = {**facts, name: value}
        before, after = _effect(cfg, facts), _effect(cfg, trial)
        if after is None:
            pending.append({"fact": name, "value": value, "claims": [c.get("id") for c in best], "tier": None,
                            "reason": "contradicts other facts; a human must decide"})
            continue
        if not any(c.get("confirmed") for c in best) and before != after:
            why = []
            if before is None or before[0] != after[0]:
                why.append(f"changes the verdict {before[0] if before else '?'} -> {after[0]}")
            if before is not None:
                on = (after[1] | after[2] | after[3]) - (before[1] | before[2] | before[3])
                off = (before[1] | before[2] | before[3]) - (after[1] | after[2] | after[3])
                if on:
                    why.append("switches on " + ", ".join(sorted(on)))
                if off:
                    why.append("switches off " + ", ".join(sorted(off)))
            tier = "kill" if after[1] - (before[1] if before else frozenset()) else (
                "strong" if (after[2] | after[3]) != ((before[2] | before[3]) if before else frozenset()) else None)
            pending.append({"fact": name, "value": value, "claims": [c.get("id") for c in best], "tier": tier,
                            "verdict_if_confirmed": after[0],
                            "reason": "human confirmation required: " + "; ".join(why or ["changes the scoring"])})
            continue
        facts[name] = value
        used[name] = [c.get("id") for c in best]
    return {"facts": facts, "used": used, "rejected": rejected, "pending": pending, "conflicts": conflicts}


def evaluate(cfg: Config, facts: dict, variant: str | Iterable[str] | None = None, *, market: dict | None = None,
             round_terms: dict | None = None, license_terms: dict | None = None, mc_draws: int | None = None,
             seed: int | None = None) -> dict:
    """One result for the scores and verdicts tables: everything the report stage may cite.

    Due-diligence questions, conditions and "what would change the verdict" are computed here; the LLM only phrases them.
    market (optional): patient and price inputs for the economics module (economics.py). It computes rNPV with a
    Monte Carlo and turns the result into the facts economics_negative / economics_weak / required_price_unrealistic;
    an explicitly given value of those facts wins.
    """
    econ, econ_note = None, "no market inputs: economics not run"
    if market is not None:
        from . import economics as E
        try:
            kw = {k: v for k, v in (("draws", mc_draws), ("seed", seed)) if v is not None}
            econ = E.underwrite(validate_facts(cfg, facts), market, round_terms, license_terms, **kw)
            facts = {**{k: v for k, v in econ["facts"].items() if k not in facts}, **facts}
            econ_note = None if econ["drives_verdict"] else (
                "economics shown but not used in the verdict: patients or price are assumptions "
                f"({', '.join(econ['assumptions'].get('assumed') or [])})")
        except E.EconomicsUnavailable as exc:
            econ_note = str(exc)
    res = score(cfg, facts, variant)
    rules = {r["id"]: r for r in cfg.rules}
    counted = {src.split(":", 1)[1] for src, _ in res.counted if src.startswith("rule:")}
    flips = counterfactuals(cfg, facts, variant)
    better = VERDICT_RANK
    conditions = []
    if res.verdict == CONDITIONAL:
        seen = set()
        for cf in flips:
            if cf["verdict_to"] == INVEST and cf["fact"] not in seen and not (
                    cf["fact"] in ECONOMIC_FACTS and cf["action"] == "hide"):   # computed facts are not hidden by hand
                seen.add(cf["fact"])
                conditions.append({"fact": cf["fact"], "label": cf["label"], "from": cf["from"], "to": cf["to"],
                                   "action": cf["action"]})
    insufficient = insufficient_detail(cfg, res, flips) if res.verdict == INSUFFICIENT else None
    return {
        "config": dict(res.config),
        "verdict": {"decision": res.verdict, "grounds": res.grounds, "grounds_text": GROUNDS[res.grounds],
                    "reason": res.reason, "conditions": conditions, "caps": list(res.caps),
                    "insufficient": insufficient},
        "score": {"pos": res.pos, "neg": res.neg, "diff": res.diff, "science_pos": res.science_pos,
                  "greens": res.greens, "axes": res.axes, "coverage": res.coverage},
        "scorecard": [{"id": i, "name": cfg.items[i]["name"], "color": c, "points": res.points.get(i, 0),
                       "level": cfg.items[i]["scope"], "axis": cfg.items[i]["axis"],
                       "basis": cfg.items[i]["basis"], "facts": res.evidence.get(i, [])}
                      for i, c in res.colors.items()],
        "rules": [{"id": rid, "name": rules[rid]["name"], "tier": rules[rid]["tier"],
                   "counted": rules[rid]["tier"] == "kill" or rid in counted,
                   "absorbed_by": res.suppressed.get(rid), "basis": rules[rid]["basis"],
                   "facts": res.evidence.get(rid, [])} for rid in res.fired],
        "facts": {"given": check_facts(cfg, facts), "derived": res.derived, "derived_from": res.derived_from},
        "reference": reference_probability(cfg, facts),
        "what_would_change": [{**cf, "direction": ("better" if better[cf["verdict_to"]] > better[cf["verdict_from"]]
                                                   else "worse")} for cf in flips],
        "dd_questions": ((econ or {}).get("driver_questions") or []) + [
            q if "kill_evidence" in q else {**q, "needs": _needs_for(q["facts"])}
            for q in top_dd_questions(cfg, facts, variant)][:10 - len((econ or {}).get("driver_questions") or [])],
        "economics": econ,
        "economics_note": econ_note,
    }

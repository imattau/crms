"""Learned construction grammar with token classes, slots, and clause shapes.

A construction is induced from teacher-marked examples. Literal positions that
vary across examples become token classes; repeated literals stay literal.
Slots carry typed meaning (values, claim, condition, manner, entity, number).
The resulting productions are ordinary governed rules, not executable regexes:
matching requires an active registry rule, every production keeps its example
lineage, and retiring the rule removes it from the grammar.

This is a bounded construction learner. It models direct, wh, relative,
coordination, conditional, passive, fronted-PP, manner, comparative, and
purpose shapes. It does not claim a complete English grammar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from crms_morphology import Morphology
from crms_rule_registry import RuleRecord, RuleRegistry

CONSTRUCTION_FAMILY = "construction"
CONSTRUCTION_ORACLE = "construction-replay"
CONSTRUCTION_ORIGIN = "crms_constructions"
CONSTRUCTION_VERSION = 1

SLOT_KINDS = frozenset({
    "claim", "condition", "manner", "entity", "values", "number",
    "predicate", "procedure",
})
COMPOSITIONS = frozenset({
    "direct", "wh", "relative", "coordination", "conditional", "passive",
    "fronted-pp", "manner", "comparative", "purpose",
})
MAX_SLOT_WORDS = 96
MAX_MATCHES = 128

_MARKER = re.compile(r"\{([a-z][a-z0-9_]*):([a-z][a-z0-9-]*):(.*?)\}")
_WORD = re.compile(r"-?\d+|[A-Za-z]+")
_INTEGER = re.compile(r"-?\d+")


def words(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in _WORD.finditer(text))


def _norm(value: str) -> str:
    return " ".join(words(value))


def _id(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    if any(character.isspace() for character in value.strip()):
        raise ValueError(f"{label} cannot contain whitespace: {value!r}")
    return value.strip()


def parse_integer_values(raw: str) -> tuple[int, ...] | None:
    tokens = words(raw)
    if not tokens:
        return None
    values: list[int] = []
    expecting = True
    for token in tokens:
        if token == "and":
            if expecting:
                return None
            expecting = True
            continue
        if not _INTEGER.fullmatch(token):
            return None
        values.append(int(token))
        expecting = False
    if expecting or not values or len(values) > 64:
        return None
    return tuple(values)


@dataclass(frozen=True)
class ConstructionSlot:
    name: str
    kind: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.name):
            raise ValueError(f"invalid construction slot name: {self.name!r}")
        if self.kind not in SLOT_KINDS:
            raise ValueError(f"invalid construction slot kind: {self.kind!r}")

    def to_dict(self) -> dict[str, str]:
        return {"kind": "slot", "name": self.name, "slot_kind": self.kind}


@dataclass(frozen=True)
class LiteralPart:
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": "literal", "text": self.text}


@dataclass(frozen=True)
class ClassPart:
    class_id: str
    members: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.members:
            raise ValueError("a token class needs at least one member")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "class", "class_id": self.class_id,
                "members": list(self.members)}


Part = LiteralPart | ClassPart | ConstructionSlot


@dataclass(frozen=True)
class ConstructionExample:
    text: str
    construction_id: str
    source_id: str
    goal: str = "select-transform"
    operation: str = ""
    name: str = ""
    composition: str = "direct"
    scope: str = "English list-transform"

    def __post_init__(self) -> None:
        _id(self.construction_id, "construction id")
        _id(self.source_id, "construction source id")
        if not self.text.strip():
            raise ValueError("construction example is empty")
        if not self.goal.strip() or not self.operation.strip():
            raise ValueError("construction example needs a goal and operation")
        if self.composition not in COMPOSITIONS:
            raise ValueError(f"unknown construction composition: {self.composition!r}")
        parsed = parse_marked_example(self.text)
        if not parsed.parts:
            raise ValueError("construction example has no parts")

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "construction_id": self.construction_id,
            "source_id": self.source_id,
            "goal": self.goal,
            "operation": self.operation,
            "name": self.name,
            "composition": self.composition,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ConstructionExample":
        return cls(
            text=str(raw.get("text", "")),
            construction_id=str(raw.get("construction_id", "")),
            source_id=str(raw.get("source_id", "")),
            goal=str(raw.get("goal", "select-transform")),
            operation=str(raw.get("operation", "")),
            name=str(raw.get("name", "")),
            composition=str(raw.get("composition", "direct")),
            scope=str(raw.get("scope", "English list-transform")),
        )


@dataclass(frozen=True)
class _Parsed:
    parts: tuple[Part, ...]
    bindings: Mapping[str, str]


def _validate_filler(slot: ConstructionSlot, filler: str) -> None:
    if not filler.strip():
        raise ValueError(f"slot {slot.name!r} has an empty filler")
    if slot.kind == "values":
        if parse_integer_values(filler) is None:
            raise ValueError(f"slot {slot.name!r} needs an integer list")
    elif slot.kind == "number":
        if not _INTEGER.fullmatch(_norm(filler)):
            raise ValueError(f"slot {slot.name!r} needs an integer")
    elif slot.kind == "claim":
        tokens = words(filler)
        if not tokens or any(_INTEGER.fullmatch(token) for token in tokens):
            raise ValueError(f"slot {slot.name!r} needs a non-numeric claim")


def parse_marked_example(text: str) -> _Parsed:
    if not text.strip():
        raise ValueError("construction example is empty")
    parts: list[Part] = []
    bindings: dict[str, str] = {}
    cursor = 0
    for marker in _MARKER.finditer(text):
        literal = text[cursor:marker.start()]
        if "{" in literal or "}" in literal:
            raise ValueError("unbalanced construction marker")
        parts.extend(LiteralPart(token) for token in words(literal))
        name, kind, filler = marker.group(1), marker.group(2), marker.group(3)
        slot = ConstructionSlot(name, kind)
        if name in bindings:
            raise ValueError(f"duplicate construction slot: {name!r}")
        _validate_filler(slot, filler)
        parts.append(slot)
        bindings[name] = filler.strip()
        cursor = marker.end()
    tail = text[cursor:]
    if "{" in tail or "}" in tail:
        raise ValueError("unbalanced construction marker")
    parts.extend(LiteralPart(token) for token in words(tail))
    if not any(isinstance(part, ConstructionSlot) for part in parts):
        raise ValueError("construction example has no slot markers")
    return _Parsed(tuple(parts), bindings)


def _signature(parts: Iterable[Part]) -> tuple[Any, ...]:
    return tuple(
        ("slot", part.name, part.kind) if isinstance(part, ConstructionSlot)
        else ("literal",)
        for part in parts
    )


def _pattern_id(construction_id: str, parts: tuple[Part, ...]) -> str:
    payload = json.dumps(
        [part.to_dict() for part in parts], sort_keys=True,
        separators=(",", ":"))
    digest = hashlib.sha256(
        f"{construction_id}:{payload}".encode("utf-8")).hexdigest()[:16]
    return f"construction-pattern-{digest}"


@dataclass(frozen=True)
class ConstructionPattern:
    pattern_id: str
    construction_id: str
    parts: tuple[Part, ...]
    examples: tuple[str, ...]

    def template_text(self) -> str:
        rendered = []
        for part in self.parts:
            if isinstance(part, ConstructionSlot):
                rendered.append(f"{{{part.name}:{part.kind}}}")
            elif isinstance(part, ClassPart):
                rendered.append("[" + "|".join(part.members) + "]")
            else:
                rendered.append(part.text)
        return " ".join(rendered)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "construction_id": self.construction_id,
            "template": self.template_text(),
            "parts": [part.to_dict() for part in self.parts],
            "examples": list(self.examples),
        }


@dataclass(frozen=True)
class ConstructionRule:
    construction_id: str
    name: str
    goal: str
    operation: str
    composition: str
    scope: str
    patterns: tuple[ConstructionPattern, ...]
    examples: tuple[ConstructionExample, ...]

    def template_text(self) -> str:
        return " / ".join(pattern.template_text() for pattern in self.patterns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "construction_id": self.construction_id,
            "name": self.name,
            "goal": self.goal,
            "operation": self.operation,
            "composition": self.composition,
            "scope": self.scope,
            "patterns": [pattern.to_dict() for pattern in self.patterns],
            "examples": [example.to_dict() for example in self.examples],
            "example_count": len(self.examples),
        }


def _derive_patterns(examples: tuple[ConstructionExample, ...]
                     ) -> tuple[ConstructionPattern, ...]:
    groups: dict[tuple[Any, ...], list[tuple[ConstructionExample, _Parsed]]] = {}
    for example in examples:
        parsed = parse_marked_example(example.text)
        key = (example.goal, example.operation,
               example.composition, _signature(parsed.parts))
        groups.setdefault(key, []).append((example, parsed))
    patterns: list[ConstructionPattern] = []
    for (_goal, _operation, _composition, _signature_key), rows in groups.items():
        if len(rows) < 2:
            continue
        base_parts = rows[0][1].parts
        parts: list[Part] = []
        for index, part in enumerate(base_parts):
            if isinstance(part, ConstructionSlot):
                parts.append(part)
                continue
            members = sorted({
                parsed.parts[index].text for _example, parsed in rows
                if isinstance(parsed.parts[index], LiteralPart)
            })
            if len(members) == 1:
                parts.append(LiteralPart(members[0]))
            else:
                digest = hashlib.sha256(
                    (rows[0][0].construction_id + ":" + str(index)
                     + ":" + "|".join(members)).encode("utf-8")).hexdigest()[:8]
                parts.append(ClassPart(
                    f"{rows[0][0].construction_id}-class-{index}-{digest}",
                    tuple(members)))
        patterns.append(ConstructionPattern(
            _pattern_id(rows[0][0].construction_id, tuple(parts)),
            rows[0][0].construction_id, tuple(parts),
            tuple(example.text for example, _parsed in rows)))
    patterns.sort(key=lambda pattern: pattern.pattern_id)
    return tuple(patterns)


def _license(examples: tuple[ConstructionExample, ...]) -> tuple[bool, str]:
    if len(examples) < 2:
        return False, "a construction needs at least two marked examples"
    if len({_norm(example.text) for example in examples}) < 2:
        return False, "construction examples need different wording"
    groups: dict[tuple[Any, ...], int] = {}
    for example in examples:
        parsed = parse_marked_example(example.text)
        groups[(example.goal, example.operation,
                _signature(parsed.parts))] = groups.get(
                    (example.goal, example.operation,
                     _signature(parsed.parts)), 0) + 1
    if not any(count >= 2 for count in groups.values()):
        return False, "no construction shape has two aligned examples"
    if not any(
            isinstance(part, ClassPart)
            for pattern in _derive_patterns(examples)
            for part in pattern.parts):
        # A slot-only template can still be a production, but a construction
        # needs either a token class or a repeatable shape with variation.
        pass
    return True, ""


def derived_constructions(examples: Iterable[ConstructionExample]
                          ) -> tuple[ConstructionRule, ...]:
    by_id: dict[str, list[ConstructionExample]] = {}
    for example in examples:
        example.__post_init__()
        by_id.setdefault(example.construction_id, []).append(example)
    rules: list[ConstructionRule] = []
    for construction_id, rows in by_id.items():
        rows_tuple = tuple(rows)
        licensed, _reason = _license(rows_tuple)
        if not licensed:
            continue
        patterns = _derive_patterns(rows_tuple)
        if not patterns:
            continue
        first = rows_tuple[0]
        if any((row.name, row.goal, row.operation, row.composition, row.scope)
               != (first.name, first.goal, first.operation, first.composition,
                   first.scope) for row in rows_tuple):
            raise ValueError(
                f"construction {construction_id!r} mixes metadata")
        rules.append(ConstructionRule(
            construction_id, first.name or construction_id, first.goal,
            first.operation, first.composition, first.scope, patterns,
            rows_tuple))
    rules.sort(key=lambda rule: rule.construction_id)
    return tuple(rules)


@dataclass
class ConstructionStore:
    examples: list[ConstructionExample] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "ConstructionStore":
        source = Path(path)
        if not source.is_file():
            return cls()
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping) or int(raw.get("version", 0)) != CONSTRUCTION_VERSION:
            raise ValueError("unsupported construction store")
        examples = [ConstructionExample.from_dict(item)
                    for item in raw.get("examples", ())]
        return cls(examples)

    def add_example(self, example: ConstructionExample) -> "ConstructionLearningResult":
        example.__post_init__()
        if example in self.examples:
            return self.learning_result(example.construction_id,
                                        "example already stored")
        self.examples.append(example)
        return self.learning_result(example.construction_id)

    def learning_result(self, construction_id: str,
                        message: str = "") -> "ConstructionLearningResult":
        rule = self.rule(construction_id)
        if rule is None:
            rows = [example for example in self.examples
                    if example.construction_id == construction_id]
            licensed, reason = _license(tuple(rows))
            return ConstructionLearningResult(
                "need_more_examples", message or reason, None, len(rows))
        return ConstructionLearningResult(
            "licensed", message or "construction licensed", rule,
            len(rule.examples))

    def rules(self) -> tuple[ConstructionRule, ...]:
        return derived_constructions(self.examples)

    def rule(self, construction_id: str) -> ConstructionRule | None:
        return next((rule for rule in self.rules()
                     if rule.construction_id == construction_id), None)

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CONSTRUCTION_VERSION,
            "examples": [example.to_dict() for example in self.examples],
        }
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        temporary.replace(target)


@dataclass(frozen=True)
class ConstructionLearningResult:
    status: str
    message: str
    rule: ConstructionRule | None
    example_count: int

    @property
    def licensed(self) -> bool:
        return self.status == "licensed"


def _class_matches(part: ClassPart, token: str,
                   morphology: Morphology) -> bool:
    return any(morphology.matches(member, token) for member in part.members)


@dataclass(frozen=True)
class ConstructionMatch:
    rule: ConstructionRule
    pattern: ConstructionPattern
    slots: Mapping[str, Any]
    text: str

    def semantic_key(self) -> tuple[Any, ...]:
        return (self.rule.construction_id, self.rule.goal,
                self.rule.operation, tuple(sorted(self.slots.items())))

    def to_dict(self) -> dict[str, Any]:
        return {
            "construction_id": self.rule.construction_id,
            "goal": self.rule.goal,
            "operation": self.rule.operation,
            "composition": self.rule.composition,
            "template": self.pattern.template_text(),
            "slots": dict(self.slots),
        }


@dataclass(frozen=True)
class ConstructionMatchResult:
    status: str
    matches: tuple[ConstructionMatch, ...] = ()
    reason: str = ""

    @property
    def match(self) -> ConstructionMatch | None:
        return self.matches[0] if len(self.matches) == 1 else None


def _surface_tokens(text: str) -> tuple[tuple[str, int, int], ...]:
    return tuple((match.group(0).casefold(), match.start(), match.end())
                 for match in _WORD.finditer(text))


def _slot_value(slot: ConstructionSlot, text: str,
                tokens: tuple[tuple[str, int, int], ...],
                start: int, end: int) -> Any | None:
    raw = text[tokens[start][1]:tokens[end - 1][2]].strip()
    if not raw:
        return None
    if slot.kind == "values":
        return parse_integer_values(raw)
    if slot.kind == "number":
        if not _INTEGER.fullmatch(raw.casefold()):
            return None
        return int(raw)
    if slot.kind == "claim":
        if any(_INTEGER.fullmatch(token) for token in words(raw)):
            return None
    return raw


def _next_start_positions(part: Part, tokens: tuple[tuple[str, int, int], ...],
                          position: int, morphology: Morphology) -> tuple[int, ...]:
    if isinstance(part, LiteralPart):
        return tuple(index for index in range(position, len(tokens))
                     if tokens[index][0] == part.text)
    if isinstance(part, ClassPart):
        return tuple(index for index in range(position, len(tokens))
                     if _class_matches(part, tokens[index][0], morphology))
    return tuple(range(position + 1, len(tokens)))


def _match_pattern(pattern: ConstructionPattern, text: str,
                   tokens: tuple[tuple[str, int, int], ...],
                   morphology: Morphology) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def visit(index: int, position: int, bindings: dict[str, Any]) -> None:
        if len(results) >= MAX_MATCHES:
            return
        if index == len(pattern.parts):
            if position == len(tokens):
                results.append(dict(bindings))
            return
        part = pattern.parts[index]
        if isinstance(part, LiteralPart):
            if position < len(tokens) and tokens[position][0] == part.text:
                visit(index + 1, position + 1, bindings)
            return
        if isinstance(part, ClassPart):
            if (position < len(tokens)
                    and _class_matches(part, tokens[position][0], morphology)):
                visit(index + 1, position + 1, bindings)
            return
        # A slot consumes one or more tokens. The following part supplies the
        # boundary; adjacent slots are avoided in the fixture grammar.
        if position >= len(tokens):
            return
        if index == len(pattern.parts) - 1:
            ends = (len(tokens),)
        else:
            next_part = pattern.parts[index + 1]
            starts = _next_start_positions(
                next_part, tokens, position + 1, morphology)
            ends = starts
        for end in ends:
            if end <= position or end - position > MAX_SLOT_WORDS:
                continue
            value = _slot_value(part, text, tokens, position, end)
            if value is None:
                continue
            bindings[part.name] = value
            visit(index + 1, end, bindings)
            del bindings[part.name]

    visit(0, 0, {})
    return results


def match_constructions(rules: Iterable[ConstructionRule], text: str, *,
                        morphology: Morphology | None = None,
                        allowed_ids: Iterable[str] | None = None
                        ) -> ConstructionMatchResult:
    morphology = morphology or Morphology.default()
    tokens = _surface_tokens(text)
    if not tokens:
        return ConstructionMatchResult("no_match", reason="empty request")
    allowed = set(allowed_ids) if allowed_ids is not None else None
    candidates: list[ConstructionMatch] = []
    for rule in rules:
        if allowed is not None and rule.construction_id not in allowed:
            continue
        for pattern in rule.patterns:
            for slots in _match_pattern(pattern, text, tokens, morphology):
                candidates.append(ConstructionMatch(rule, pattern, slots, text))
    if not candidates:
        return ConstructionMatchResult(
            "no_match", reason="no active construction matches this wording")
    unique: dict[tuple[Any, ...], ConstructionMatch] = {}
    for candidate in candidates:
        unique.setdefault(candidate.semantic_key(), candidate)
    selected = sorted(unique.values(),
                      key=lambda item: (item.rule.construction_id,
                                        item.pattern.pattern_id))
    if len(selected) > 1:
        return ConstructionMatchResult(
            "ambiguous", tuple(selected),
            "more than one active construction matches this wording")
    return ConstructionMatchResult("matched", (selected[0],))


class ConstructionGrammar:
    """Matcher over licensed constructions whose rules are active."""

    def __init__(self, store: ConstructionStore, *,
                 registry: RuleRegistry | None = None,
                 morphology: Morphology | None = None) -> None:
        self.store = store
        self.registry = registry
        self.morphology = morphology or Morphology.default()
        self._rules = store.rules()
        self._active_ids = governed_construction_ids(store, registry)

    def rules(self) -> tuple[ConstructionRule, ...]:
        return tuple(rule for rule in self._rules
                     if rule.construction_id in self._active_ids)

    def match(self, text: str) -> ConstructionMatchResult:
        return match_constructions(
            self.rules(), text, morphology=self.morphology,
            allowed_ids=self._active_ids)

    def dangling_references(self) -> list[str]:
        if self.registry is None:
            return []
        licensed = {rule.construction_id for rule in self._rules}
        return sorted(
            str(record.payload.get("construction_id"))
            for record in self.registry.records(
                family=CONSTRUCTION_FAMILY, state="active")
            if record.payload.get("origin") == CONSTRUCTION_ORIGIN
            and record.payload.get("construction_id") not in licensed)

    def record_use(self, match: ConstructionMatch, *, success: bool = True
                   ) -> RuleRecord | None:
        if self.registry is None:
            return None
        rule_id = construction_rule_id(match.rule.construction_id)
        if rule_id not in self.registry:
            return None
        return self.registry.record_use(rule_id, success=success)


def construction_rule_id(construction_id: str) -> str:
    return "construction-" + construction_id


def replay_construction_rule(rule: ConstructionRule
                             ) -> tuple[bool, str, int, int]:
    if len(rule.examples) < 2:
        return False, "a construction needs at least two examples", 0, 0
    if not rule.patterns:
        return False, "a construction has no licensed pattern", len(rule.examples), 0
    try:
        derived = derived_constructions(rule.examples)
    except Exception as error:  # noqa: BLE001 - malformed stored evidence
        return False, f"construction evidence is malformed: {error}", 0, 0
    match = next((item for item in derived
                  if item.construction_id == rule.construction_id), None)
    if match is None:
        return (False, "the examples no longer license this construction",
                len(rule.examples), 0)
    if [pattern.to_dict() for pattern in match.patterns] != [
            pattern.to_dict() for pattern in rule.patterns]:
        return (False, "the production does not replay from its examples",
                len(rule.examples), 0)
    sources = {example.source_id for example in rule.examples}
    if len(sources) != len(rule.examples):
        return (False, "construction examples need distinct sources",
                len(rule.examples), len(sources))
    varied = any(
        isinstance(part, ClassPart)
        for pattern in rule.patterns for part in pattern.parts)
    if not varied:
        return (False, "a production needs at least one learned token class",
                len(rule.examples), len(sources))
    return (True, f"{len(rule.examples)} examples replay to "
                  f"{len(rule.patterns)} construction pattern(s); "
                  f"{len(sources)} source(s)",
            len(rule.examples), len(sources))


@dataclass(frozen=True)
class HoldoutEvidence:
    passed: bool
    cases: int
    independent_sources: int
    detail: str = ""


def register_construction_rule(
        rule: ConstructionRule, registry: RuleRegistry, *,
        holdout: HoldoutEvidence | None = None,
        allow_successor: bool = False) -> RuleRecord:
    passed, detail, cases, sources = replay_construction_rule(rule)
    if holdout is not None:
        passed = passed and holdout.passed
        cases = holdout.cases
        sources = holdout.independent_sources
        detail = f"{detail}; holdout: {holdout.detail}"
    rule_id = construction_rule_id(rule.construction_id)
    existing = registry.get(rule_id) if rule_id in registry else None
    if existing is not None and existing.state == "retired":
        if not allow_successor:
            return existing
        version = 2
        while f"{rule_id}-v{version}" in registry:
            version += 1
        rule_id = f"{rule_id}-v{version}"
        existing = None
    payload = {
        "origin": CONSTRUCTION_ORIGIN,
        **rule.to_dict(),
    }
    provenance = [
        {
            "kind": "construction-example",
            "index": index,
            "construction_id": example.construction_id,
            "source_id": example.source_id,
            "utterance": example.text,
            "composition": example.composition,
        }
        for index, example in enumerate(rule.examples)
    ]
    statement = (f"{rule.composition} construction for goal {rule.goal}: "
                 f"{rule.name}")
    if existing is None:
        registry.propose(
            rule_id=rule_id, family=CONSTRUCTION_FAMILY,
            statement=statement, scope=rule.scope, payload=payload,
            provenance=provenance, trust="taught")
    else:
        if existing.state == "contested":
            registry.revise(
                rule_id, statement=statement, payload=payload,
                provenance=provenance)
            return registry.get(rule_id)
        registry.revise(
            rule_id, statement=statement, payload=payload,
            provenance=provenance)
    registry.validate(
        rule_id, oracle=CONSTRUCTION_ORACLE, passed=passed,
        cases=cases, independent_sources=sources, detail=detail)
    record = registry.get(rule_id)
    if passed and record.state in {"proposed", "validated"}:
        registry.activate(rule_id, mode="review", authoriser="teacher")
    return registry.get(rule_id)


def governed_construction_ids(
        store: ConstructionStore,
        registry: RuleRegistry | None) -> set[str]:
    licensed = {rule.construction_id for rule in store.rules()}
    if registry is None:
        return licensed
    active = {
        str(record.payload.get("construction_id"))
        for record in registry.records(
            family=CONSTRUCTION_FAMILY, state="active")
        if record.payload.get("origin") == CONSTRUCTION_ORIGIN
    }
    return licensed & active


def sync_construction_registry(
        store: ConstructionStore, registry: RuleRegistry, *,
        holdout_by_id: Mapping[str, HoldoutEvidence] | None = None
        ) -> list[RuleRecord]:
    rules = {rule.construction_id: rule for rule in store.rules()}
    records = []
    for construction_id, rule in sorted(rules.items()):
        records.append(register_construction_rule(
            rule, registry,
            holdout=(holdout_by_id or {}).get(construction_id),
            allow_successor=False))
    for record in registry.records(family=CONSTRUCTION_FAMILY):
        if record.state == "retired":
            continue
        if record.payload.get("origin") != CONSTRUCTION_ORIGIN:
            continue
        construction_id = record.payload.get("construction_id")
        if construction_id not in rules:
            registry.retire(
                record.id, reason="construction is no longer licensed")
    return records


@dataclass(frozen=True)
class ConstructionQuestion:
    query: str
    construction_id: str | None
    missing: str
    prompt: str
    class_id: str | None = None
    member: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "construction_id": self.construction_id,
            "missing": self.missing,
            "prompt": self.prompt,
            "class_id": self.class_id,
            "member": self.member,
        }


def propose_construction_gap(query: str, goal: str,
                             grammar: ConstructionGrammar) -> ConstructionQuestion | None:
    """Ask for the smallest example that could license the failed wording."""
    if grammar.match(query).status != "no_match":
        return None
    tokens = words(query)
    best: tuple[int, ConstructionRule, ConstructionPattern, str, str, str] | None = None
    for rule in grammar.rules():
        if rule.goal != goal:
            continue
        for pattern in rule.patterns:
            overlap = 0
            for part in pattern.parts:
                if isinstance(part, LiteralPart):
                    if part.text in tokens:
                        overlap += 1
                elif isinstance(part, ClassPart):
                    if any(_class_matches(part, token, grammar.morphology)
                           for token in tokens):
                        overlap += 1
            matched = 0
            missing_kind = "new-construction"
            missing_value = ""
            class_id = None
            for index, part in enumerate(pattern.parts):
                if isinstance(part, ConstructionSlot):
                    break
                if index >= len(tokens):
                    break
                token = tokens[index]
                if isinstance(part, LiteralPart):
                    if token != part.text:
                        missing_kind = "literal"
                        missing_value = token
                        break
                elif isinstance(part, ClassPart):
                    if not _class_matches(part, token, grammar.morphology):
                        missing_kind = "class-member"
                        missing_value = token
                        class_id = part.class_id
                        break
                matched += 1
            if missing_kind == "new-construction":
                continue
            score = overlap * 10 + matched
            if best is None or score > best[0]:
                best = (score, rule, pattern, missing_kind, missing_value,
                        class_id or "")
    if best is None:
        return ConstructionQuestion(
            query, None, "new-construction",
            "No active construction is close to this wording. Please provide "
            "one teacher-marked example for the missing construction.")
    _score, rule, _pattern, missing_kind, missing, class_id = best
    if missing_kind == "class-member":
        prompt = (
            f"Please show one marked example that uses {missing!r} in the "
            f"{rule.name} construction ({rule.composition}), alongside the "
            "existing wording.")
        return ConstructionQuestion(
            query, rule.construction_id, f"class-member:{missing}", prompt,
            class_id, missing)
    return ConstructionQuestion(
        query, rule.construction_id, f"literal:{missing}",
        f"Please show one marked example that uses {missing!r} in the "
        f"{rule.name} construction.", None, missing)


@dataclass(frozen=True)
class ConstructionAnswerResult:
    status: str
    construction_id: str | None
    rule_state: str | None
    matched_after: bool
    message: str = ""


def record_construction_answer(
        question: ConstructionQuestion, *, marked_text: str,
        source_id: str, store: ConstructionStore,
        registry: RuleRegistry, name: str | None = None,
        composition: str | None = None, scope: str | None = None,
        goal: str = "select-transform", operation: str = "",
        holdout: HoldoutEvidence | None = None) -> ConstructionAnswerResult:
    if question.construction_id is None:
        return ConstructionAnswerResult(
            "needs-new-construction", None, None, False,
            "a new construction needs a full teacher-marked specification")
    template = store.rule(question.construction_id)
    example = ConstructionExample(
        text=marked_text,
        construction_id=question.construction_id,
        source_id=source_id,
        goal=goal,
        operation=operation or (template.operation if template else ""),
        name=name or (template.name if template else question.construction_id),
        composition=composition or (
            template.composition if template else "direct"),
        scope=scope or (template.scope if template else "English list-transform"),
    )
    learned = store.add_example(example)
    rule = store.rule(question.construction_id)
    if rule is None:
        return ConstructionAnswerResult(
            "need-more-examples", question.construction_id, None, False,
            learned.message)
    record = register_construction_rule(
        rule, registry, holdout=holdout, allow_successor=True)
    grammar = ConstructionGrammar(store, registry=registry)
    return ConstructionAnswerResult(
        "updated" if record.state == "active" else "proposed",
        question.construction_id, record.state,
        grammar.match(question.query).status == "matched",
        record.statement)

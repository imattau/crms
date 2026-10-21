"""Bounded morphology expansion with evidence-only irregular lexical forms.

Regular inflection is licensed by explicit rules and can be replayed. Irregular
forms are stored as lexical evidence pairs: the system may match a pair it has
seen, but it never generates an unseen irregular form from a lemma. Every rule
can be mirrored into the governed rule registry and retired.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Mapping

from crms_rule_registry import RuleRegistry

MORPHOLOGY_FAMILY = "morphology"
MORPHOLOGY_ORACLE = "morphology-replay"


def _norm(value: str) -> str:
    return " ".join(re.findall(r"[A-Za-z]+", value.casefold()))


def regular_plural(lemma: str) -> str:
    word = _norm(lemma)
    if not word or " " in word:
        raise ValueError("plural rule needs one alphabetic lemma")
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if (len(word) > 1 and word.endswith("y")
            and word[-2] not in "aeiou"):
        return word[:-1] + "ies"
    return word + "s"


def regular_singular(word: str) -> str:
    token = _norm(word)
    if token.endswith("ies") and len(token) > 3:
        return token[:-3] + "y"
    if token.endswith(("ses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 2:
        return token[:-1]
    return token


@dataclass(frozen=True)
class MorphologyRule:
    rule_id: str
    kind: str
    statement: str
    examples: tuple[tuple[str, str], ...]
    source: str
    irregular: bool = False

    def __post_init__(self) -> None:
        if not self.rule_id or any(c.isspace() for c in self.rule_id):
            raise ValueError("morphology rule id must be a non-empty slug")
        if self.kind not in {"plural", "irregular-lexical"}:
            raise ValueError(f"unsupported morphology rule kind: {self.kind!r}")
        if not self.statement.strip() or not self.source.strip():
            raise ValueError("morphology rule needs a statement and source")
        if self.kind == "plural" and self.irregular:
            raise ValueError("a regular plural rule cannot be irregular")
        if self.kind == "irregular-lexical" and not self.irregular:
            raise ValueError("an irregular lexical rule must be marked irregular")
        if not self.examples:
            raise ValueError("morphology rule needs examples")
        for left, right in self.examples:
            if not _norm(left) or not _norm(right):
                raise ValueError("morphology examples need two word forms")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "kind": self.kind,
            "statement": self.statement,
            "examples": [list(pair) for pair in self.examples],
            "source": self.source,
            "irregular": self.irregular,
        }


def replay_morphology_rule(rule: MorphologyRule) -> tuple[bool, str, int, int]:
    if rule.kind == "plural":
        for lemma, form in rule.examples:
            if regular_plural(lemma) != _norm(form):
                return (False, f"{lemma!r} does not regularise to {form!r}",
                        len(rule.examples), 1)
        return (True, "all plural examples replay from the regular rule",
                len(rule.examples), 1)
    # Irregular evidence is checked as a lexical pair, never regenerated.
    if len({tuple(map(_norm, pair)) for pair in rule.examples}) != len(rule.examples):
        return False, "duplicate irregular evidence", len(rule.examples), 1
    return (True, "irregular forms are stored as lexical evidence only",
            len(rule.examples), 1)


def register_morphology_rule(rule: MorphologyRule,
                             registry: RuleRegistry) -> Any:
    passed, detail, cases, sources = replay_morphology_rule(rule)
    record_id = "morphology-" + rule.rule_id
    if record_id not in registry:
        registry.propose(
            rule_id=record_id, family=MORPHOLOGY_FAMILY,
            statement=rule.statement, scope="English morphology",
            payload=rule.to_dict(),
            provenance=({"source": rule.source, "kind": "morphology"},),
            trust="taught" if rule.irregular else "source-reviewed",
        )
    registry.validate(
        record_id, oracle=MORPHOLOGY_ORACLE, passed=passed,
        cases=cases, independent_sources=sources, detail=detail)
    record = registry.get(record_id)
    if passed and record.state in {"proposed", "validated"}:
        registry.activate(record_id, mode="review", authoriser="teacher")
    return registry.get(record_id)


class Morphology:
    """Regular forms plus explicitly observed irregular pairs."""

    def __init__(self, *, rules: Iterable[MorphologyRule] = (),
                 registry: RuleRegistry | None = None) -> None:
        self.rules = list(rules)
        self.registry = registry
        self._regular = [rule for rule in self.rules if rule.kind == "plural"]
        self._irregular: dict[str, set[str]] = {}
        for rule in self.rules:
            if rule.kind == "irregular-lexical":
                for base, form in rule.examples:
                    self._irregular.setdefault(_norm(base), set()).add(_norm(form))

    @classmethod
    def default(cls, *, registry: RuleRegistry | None = None) -> "Morphology":
        return cls(rules=(MorphologyRule(
            "plural-regular", "plural",
            "regular English noun plural: -s, -es, or -ies",
            (("value", "values"), ("number", "numbers"),
             ("entry", "entries"), ("item", "items")),
            "teacher:phase5:morphology"),), registry=registry)

    def active_regular(self) -> bool:
        if self.registry is None:
            return bool(self._regular)
        active = {
            record.payload.get("rule_id")
            for record in self.registry.records(
                family=MORPHOLOGY_FAMILY, state="active")
        }
        return any(rule.rule_id in active for rule in self._regular)

    def plural(self, lemma: str) -> str:
        if not self.active_regular():
            raise ValueError("no active regular plural rule")
        return regular_plural(lemma)

    def forms(self, lemma: str) -> set[str]:
        token = _norm(lemma)
        forms = {token}
        if self.active_regular():
            try:
                forms.add(regular_plural(token))
            except ValueError:
                pass
            if token.endswith("s"):
                forms.add(regular_singular(token))
        forms.update(self._irregular.get(token, ()))
        for base, observed in self._irregular.items():
            if token in observed:
                forms.add(base)
        return forms

    def matches(self, member: str, token: str) -> bool:
        member = _norm(member)
        token = _norm(token)
        if member == token:
            return True
        if token in self._irregular.get(member, ()):
            return True
        if member in self._irregular.get(token, ()):
            return True
        if not self.active_regular():
            return False
        try:
            if regular_plural(member) == token or regular_plural(token) == member:
                return True
        except ValueError:
            pass
        if token.endswith("s") and regular_singular(token) == member:
            return True
        if member.endswith("s") and regular_singular(member) == token:
            return True
        return False

    def add_irregular(self, base: str, form: str, *, rule_id: str,
                      source: str) -> MorphologyRule:
        rule = MorphologyRule(
            rule_id, "irregular-lexical",
            f"observed irregular lexical pair {base!r} -> {form!r}",
            ((base, form),), source, irregular=True)
        self.rules.append(rule)
        self._irregular.setdefault(_norm(base), set()).add(_norm(form))
        return rule

    def rule_payloads(self) -> list[dict[str, Any]]:
        return [rule.to_dict() for rule in self.rules]

"""Bounded generalisation support for Phase 10 rule development.

The goal is not to hide a model. It is to make the coverage assumptions behind
rule generalisation explicit: lexical classes, back-off lookup, report-only
analogical candidates, evidence-count weights, and a fact-coverage curve. None
of these accept a rule or a fact; they produce inspectable proposals and
measurements.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence

from crms_generation import Fact, GenerationEngine, GenerationRequest


class GeneralisationError(ValueError):
    """A class hierarchy or generalisation request is malformed."""


@dataclass(frozen=True)
class LexicalClass:
    name: str
    members: tuple[str, ...]
    parent: str | None = None

    def validate(self) -> None:
        if not self.name.strip():
            raise GeneralisationError("class name is required")
        if not self.members:
            raise GeneralisationError(f"class {self.name!r} has no members")
        if self.parent == self.name:
            raise GeneralisationError(f"class {self.name!r} is its own parent")


class ClassHierarchy:
    """Small, inspectable class hierarchy with deterministic back-off."""

    def __init__(self, classes: Iterable[LexicalClass] = ()) -> None:
        self.classes: dict[str, LexicalClass] = {}
        self.member_to_class: dict[str, str] = {}
        for item in classes:
            self.add(item)

    def add(self, item: LexicalClass) -> None:
        item.validate()
        if item.name in self.classes:
            raise GeneralisationError(f"class already exists: {item.name!r}")
        if item.parent is not None and item.parent not in self.classes:
            raise GeneralisationError(f"unknown parent: {item.parent!r}")
        self.classes[item.name] = item
        for member in item.members:
            key = member.casefold().strip()
            if key in self.member_to_class:
                raise GeneralisationError(
                    f"member already classified: {member!r}")
            self.member_to_class[key] = item.name

    def ancestors(self, token: str) -> tuple[str, ...]:
        key = token.casefold().strip()
        current = self.member_to_class.get(key)
        result: list[str] = []
        seen: set[str] = set()
        while current is not None and current not in seen:
            result.append(current)
            seen.add(current)
            current = self.classes[current].parent
        return tuple(result)

    def generalise(self, token: str) -> str:
        chain = self.ancestors(token)
        return chain[0] if chain else token

    def related(self, left: str, right: str) -> bool:
        if left.casefold().strip() == right.casefold().strip():
            return True
        return bool(set(self.ancestors(left)) & set(self.ancestors(right)))


def evidence_weight(fact: Fact,
                    source_counts: Mapping[str, int] | None = None) -> float:
    """A simple, inspectable evidence-count weight per source."""
    counts = source_counts or {}
    count = max(1, int(counts.get(fact.source, 1)))
    return round(math.log1p(count), 6)


def analogical_candidates(target: Fact, facts: Sequence[Fact],
                          hierarchy: ClassHierarchy) -> list[dict[str, object]]:
    """Return report-only facts that share a predicate or lexical class."""
    rows = []
    target_class = hierarchy.generalise(target.subject)
    for fact in facts:
        if fact.fact_id == target.fact_id:
            continue
        score = 0
        reasons = []
        if fact.verb.casefold() == target.verb.casefold():
            score += 2
            reasons.append("same predicate")
        if hierarchy.related(fact.subject, target.subject):
            score += 1
            reasons.append("same lexical class")
        fact_class = hierarchy.generalise(fact.subject)
        if target_class != target.subject and fact_class == target_class:
            score += 1
            reasons.append("shared general class")
        if score:
            rows.append({
                "fact_id": fact.fact_id,
                "score": score,
                "reasons": reasons,
                "accepted": False,
            })
    return sorted(rows, key=lambda row: (-int(row["score"]),
                                         str(row["fact_id"])))


def fact_coverage_curve(engine: GenerationEngine,
                        request: GenerationRequest,
                        sizes: Iterable[int] | None = None
                        ) -> list[dict[str, object]]:
    """Measure generation status and coverage as facts are added."""
    total = len(request.facts)
    points = sorted(set(size for size in (sizes or range(1, total + 1))
                        if 0 <= size <= total))
    rows = []
    for size in points:
        subset = request.facts[:size]
        candidate = GenerationRequest(
            prompt=request.prompt, genre=request.genre, facts=subset,
            audience=request.audience, style=request.style,
            max_sentences=request.max_sentences,
            source_documents=request.source_documents,
        )
        result = engine.generate(candidate)
        rows.append({
            "facts": size,
            "status": result.status,
            "sentences": result.critique.sentence_count if result.critique else 0,
            "coverage": result.critique.coverage if result.critique else 0.0,
            "score": result.critique.score if result.critique else 0.0,
        })
    return rows

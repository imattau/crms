"""Offline, deterministic, size-budgeted candidate ranker.

The ranker proposes an ordering of already-licensed construction matches. It
never chooses an answer, activates a rule, or filters the grammar result; a
caller can ignore it entirely. This keeps the deterministic parser authoritative
and the ranker strictly advisory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from crms_constructions import (
    ClassPart, ConstructionMatch, LiteralPart, ConstructionSlot,
)


@dataclass(frozen=True)
class RankedCandidate:
    construction_id: str
    pattern_id: str
    score: float
    features: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "construction_id": self.construction_id,
            "pattern_id": self.pattern_id,
            "score": self.score,
            "features": list(self.features),
        }


class ConstructionRanker:
    """A bounded, deterministic proposer over construction matches."""

    def __init__(self, *, max_candidates: int = 8,
                 max_features: int = 24) -> None:
        if type(max_candidates) is not int or max_candidates < 1:
            raise ValueError("max_candidates must be a positive integer")
        if type(max_features) is not int or max_features < 1:
            raise ValueError("max_features must be a positive integer")
        self.max_candidates = max_candidates
        self.max_features = max_features

    def propose(self, matches: Iterable[ConstructionMatch]
                ) -> list[RankedCandidate]:
        rows: list[RankedCandidate] = []
        for match in matches:
            features: list[str] = []
            literals = classes = slots = 0
            for part in match.pattern.parts:
                if isinstance(part, LiteralPart):
                    literals += 1
                    if len(features) < self.max_features:
                        features.append(f"literal:{part.text}")
                elif isinstance(part, ClassPart):
                    classes += 1
                    if len(features) < self.max_features:
                        features.append(
                            f"class:{part.class_id}:{len(part.members)}")
                elif isinstance(part, ConstructionSlot):
                    slots += 1
                    if len(features) < self.max_features:
                        features.append(f"slot:{part.name}:{part.kind}")
            score = float(literals * 3 + classes * 2 + slots)
            # Fewer alternatives is more specific; this is only a proposal
            # signal, not evidence of correctness.
            for part in match.pattern.parts:
                if isinstance(part, ClassPart) and part.members:
                    score += 1.0 / len(part.members)
            rows.append(RankedCandidate(
                match.rule.construction_id, match.pattern.pattern_id,
                round(score, 6), tuple(features[:self.max_features])))
        rows.sort(key=lambda row: (-row.score, row.construction_id,
                                   row.pattern_id))
        return rows[:self.max_candidates]

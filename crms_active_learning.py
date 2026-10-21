"""Active learning: ask the one example that best separates competing rules.

The learner does not accept a rule. It narrows a hypothesis set, records the
answer as supervision with its source, and can propose the surviving rule for
review. A question is emitted only when it produces a real partition; an
uninformative example is never asked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Callable, Iterable, Mapping

from crms_rule_registry import RuleRegistry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


def _id(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    if any(character.isspace() for character in value.strip()):
        raise ValueError(f"{label} cannot contain whitespace: {value!r}")
    return value.strip()


@dataclass(frozen=True)
class Hypothesis:
    id: str
    predict: Callable[[Any], Any]
    label: str = ""
    family: str = "procedure"
    statement: str = ""
    scope: str = ""

    def __post_init__(self) -> None:
        _id(self.id, "hypothesis id")
        if not callable(self.predict):
            raise TypeError("hypothesis predict must be callable")
        if self.family not in {
                "lexical", "morphology", "procedure", "task-plan",
                "request-frame"}:
            raise ValueError(f"unsupported hypothesis family: {self.family!r}")


@dataclass(frozen=True)
class ActiveQuestion:
    case: Any
    outcomes: tuple[Any, ...]
    candidates: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "outcomes": list(self.outcomes),
            "candidates": list(self.candidates),
        }


@dataclass(frozen=True)
class Supervision:
    hypothesis_id: str
    case: Any
    observed: Any
    source: str
    at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "case": self.case,
            "observed": self.observed,
            "source": self.source,
            "at": self.at,
        }


@dataclass(frozen=True)
class Decision:
    status: str
    remaining: tuple[str, ...]
    supervision: Supervision | None = None


class ActiveLearner:
    """A finite hypothesis set with an information-gain-style probe choice."""

    def __init__(self, hypotheses: Iterable[Hypothesis], *,
                 cases: Iterable[Any] = ()) -> None:
        rows = list(hypotheses)
        if len(rows) < 2:
            raise ValueError("active learning needs at least two hypotheses")
        if len({row.id for row in rows}) != len(rows):
            raise ValueError("hypothesis ids must be unique")
        self._hypotheses = list(rows)
        self.cases = list(cases)
        self.supervision: list[Supervision] = []

    @property
    def remaining(self) -> tuple[Hypothesis, ...]:
        return tuple(self._hypotheses)

    def _outputs(self, hypothesis: Hypothesis, case: Any) -> Any:
        try:
            return hypothesis.predict(case)
        except Exception:
            return {"__abstain__": True}

    def _partition(self, case: Any) -> dict[str, list[Hypothesis]]:
        groups: dict[str, list[Hypothesis]] = {}
        for hypothesis in self._hypotheses:
            value = self._outputs(hypothesis, case)
            groups.setdefault(_canonical(value), []).append(hypothesis)
        return groups

    def separating_case(self, cases: Iterable[Any] | None = None
                        ) -> ActiveQuestion | None:
        candidates = list(cases if cases is not None else self.cases)
        if len(self._hypotheses) < 2 or not candidates:
            return None
        best: tuple[tuple[int, int, int], Any, dict[str, list[Hypothesis]]] | None = None
        for position, case in enumerate(candidates):
            partition = self._partition(case)
            if len(partition) < 2:
                continue
            sizes = sorted(len(group) for group in partition.values())
            score = (len(partition), sizes[0], -position)
            if best is None or score > best[0]:
                best = (score, case, partition)
        if best is None:
            return None
        _score, case, partition = best
        outcomes = tuple(
            group[0].predict(case) for group in partition.values())
        return ActiveQuestion(
            case=case,
            outcomes=outcomes,
            candidates=tuple(sorted(
                hypothesis.id for group in partition.values()
                for hypothesis in group)),
        )

    def ask(self, cases: Iterable[Any] | None = None) -> ActiveQuestion | None:
        return self.separating_case(cases)

    def record(self, question: ActiveQuestion, observed: Any, *,
               source: str) -> Decision:
        if not isinstance(source, str) or not source.strip():
            raise ValueError("supervision requires a source")
        if observed not in question.outcomes:
            raise ValueError(
                f"observed answer {observed!r} was not offered by the question")
        matches = []
        for hypothesis in self._hypotheses:
            if _canonical(self._outputs(hypothesis, question.case)) == _canonical(observed):
                matches.append(hypothesis)
        if not matches:
            return Decision("inconsistent", tuple(row.id for row in self._hypotheses))
        self._hypotheses = matches
        supervision = Supervision(
            hypothesis_id=matches[0].id, case=question.case,
            observed=observed, source=source)
        # When one answer still leaves several tied hypotheses, the answer is
        # still supervision for each surviving candidate.
        self.supervision.append(supervision)
        return Decision(
            "resolved" if len(matches) == 1 else "narrowed",
            tuple(row.id for row in matches),
            supervision)

    def propose_winner(self, registry: RuleRegistry, *, rule_id: str,
                       statement: str | None = None,
                       scope: str | None = None,
                       dependencies: Iterable[str] = ()) -> Any | None:
        if len(self._hypotheses) != 1:
            return None
        winner = self._hypotheses[0]
        if winner.id in registry:
            return registry.get(winner.id)
        return registry.propose(
            rule_id=rule_id,
            family=winner.family,
            statement=statement or winner.statement or winner.label or winner.id,
            scope=scope if scope is not None else winner.scope,
            payload={
                "hypothesis_id": winner.id,
                "label": winner.label,
                "supervision": [row.as_dict() for row in self.supervision],
                "origin": "active-learning",
            },
            provenance=tuple(row.as_dict() for row in self.supervision),
            trust="derived",
            dependencies=dependencies,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "remaining": [row.id for row in self._hypotheses],
            "supervision": [row.as_dict() for row in self.supervision],
        }

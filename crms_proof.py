"""Small independent validators for CRMS's serialized proof records.

This module deliberately does not import the knowledge base or its query code.
It checks a proposed fact path against a caller-supplied positive-fact snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from crms_text import tokens as normalized_tokens


def _key(value: str) -> tuple[str, ...]:
    return normalized_tokens(value)


@dataclass(frozen=True)
class ProofCheck:
    valid: bool
    reason: str


def verify_fact_path(
        proof: Iterable[Mapping[str, Any]],
        facts: Iterable[Mapping[str, Any]], *,
        start: str, relations: Iterable[str], answer: str,
        qualifiers: Mapping[str, str] | None = None) -> ProofCheck:
    """Verify a complete positive-fact path without invoking CRMS query code.

    Each proof step must match a stored fact, including its qualifier context
    and source set. The path must begin at ``start``, follow exactly
    ``relations`` in order, and end at ``answer``.
    """
    try:
        steps = list(proof)
        expected_relations = list(relations)
        if not steps or len(steps) != len(expected_relations):
            return ProofCheck(False, "proof length does not match relation path")
        if not isinstance(start, str) or not start.strip() or not isinstance(answer, str) or not answer.strip():
            return ProofCheck(False, "start and answer must be non-empty strings")

        requested_context = {
            (_key(str(name)), _key(str(value)))
            for name, value in (qualifiers or {}).items()
        }
        stored: set[tuple[Any, ...]] = set()
        for fact in facts:
            if not isinstance(fact, Mapping):
                continue
            stored.add(_fact_signature(fact))

        current = _key(start)
        for index, (step, relation) in enumerate(zip(steps, expected_relations)):
            if not isinstance(step, Mapping):
                return ProofCheck(False, f"step {index + 1} is not a fact record")
            subject = step.get("subject")
            relation_value = step.get("relation")
            obj = step.get("object")
            if not all(isinstance(value, str) and value.strip()
                       for value in (subject, relation_value, obj, relation)):
                return ProofCheck(False, f"step {index + 1} has missing text fields")
            if _key(subject) != current:
                return ProofCheck(False, f"step {index + 1} does not continue the path")
            if _key(relation_value) != _key(relation):
                return ProofCheck(False, f"step {index + 1} uses the wrong relation")
            if _fact_signature(step) not in stored:
                return ProofCheck(False, f"step {index + 1} is not present in the fact snapshot")
            step_context = {
                (_key(str(name)), _key(str(value)))
                for name, value in step.get("qualifiers", [])
            }
            if not requested_context.issubset(step_context):
                return ProofCheck(False, f"step {index + 1} does not satisfy requested qualifiers")
            current = _key(obj)
        if current != _key(answer):
            return ProofCheck(False, "proof endpoint does not match answer")
        return ProofCheck(True, "valid fact path")
    except (TypeError, ValueError, AttributeError):
        return ProofCheck(False, "malformed proof or fact snapshot")


def _fact_signature(fact: Mapping[str, Any]) -> tuple[Any, ...]:
    subject = fact.get("subject")
    relation = fact.get("relation")
    obj = fact.get("object")
    if not all(isinstance(value, str) for value in (subject, relation, obj)):
        raise ValueError("fact text fields must be strings")
    qualifiers = tuple(sorted(
        (_key(str(name)), _key(str(value)))
        for name, value in fact.get("qualifiers", [])
    ))
    sources = tuple(sorted(str(source) for source in fact.get("sources", [])))
    return _key(subject), _key(relation), _key(obj), qualifiers, sources

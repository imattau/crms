"""Read-only provenance and dependency summaries for accepted facts.

This first report deliberately counts cited documents, not independent origins:
the current fact store does not retain a configured publisher/corpus origin for
each citation. It also identifies dependents only through verified derived
cases, whose proof leaves provide an exact evidence link.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping

from crms_text import tokens as normalized_tokens


@dataclass(frozen=True)
class SupportRow:
    item_kind: str
    item_id: str
    label: str
    dependents: int
    source_documents: tuple[str, ...]
    independent_origins: int | None
    teacher_supported: bool
    risk: str
    origin_count_available: bool = False


def _document(source: Any) -> str:
    return str(source).split("#", 1)[0].strip()


def _tokens(value: Any) -> tuple[str, ...]:
    return tuple(normalized_tokens(str(value)))


def _qualifiers(value: Any) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if isinstance(value, Mapping):
        pairs = value.items()
    elif isinstance(value, (list, tuple)):
        pairs = value
    else:
        return ()
    normalized = []
    for pair in pairs:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            normalized.append((str(pair[0]).casefold(), _tokens(pair[1])))
    return tuple(sorted(normalized))


def _fact_key(fact: Mapping[str, Any], polarity: bool = True) -> tuple[Any, ...]:
    return (polarity, _tokens(fact.get("subject", "")),
            _tokens(fact.get("relation", "")),
            _tokens(fact.get("object", "")),
            _qualifiers(fact.get("qualifiers", ())))


def _proof_fact_keys(proof: Any) -> set[tuple[Any, ...]]:
    found: set[tuple[Any, ...]] = set()
    stack = [proof]
    while stack:
        node = stack.pop()
        if not isinstance(node, Mapping):
            continue
        if node.get("kind") == "fact" and isinstance(node.get("fact"), Mapping):
            found.add(_fact_key(node["fact"]))
        premises = node.get("premises", ())
        if isinstance(premises, (list, tuple)):
            stack.extend(premises)
    return found


def _stable_id(fact: Mapping[str, Any], polarity: bool) -> str:
    payload = json.dumps(
        _fact_key(fact, polarity), sort_keys=True, ensure_ascii=False,
        separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def support_report(knowledge_base: Any, *, min_dependents: int = 3,
                   min_documents: int = 2) -> list[SupportRow]:
    """List fact support and verified derived-case dependencies without mutation."""
    if type(min_dependents) is not int or min_dependents < 0:
        raise ValueError("min_dependents must be a non-negative integer")
    if type(min_documents) is not int or min_documents < 1:
        raise ValueError("min_documents must be a positive integer")

    dependencies: dict[tuple[Any, ...], set[str]] = {}
    verified_cases = [case for case in knowledge_base.derived_cases()
                      if case.get("status") == "verified"]
    for case in verified_cases:
        case_id = json.dumps(case.get("conclusion", {}), sort_keys=True,
                             ensure_ascii=False)
        for proof in case.get("proofs", ()):
            for key in _proof_fact_keys(proof):
                dependencies.setdefault(key, set()).add(case_id)

    rows = []
    stores: Iterable[tuple[bool, Iterable[Any]]] = (
        (True, knowledge_base.facts()),
        (False, knowledge_base.negative_facts()),
    )
    for polarity, facts in stores:
        for fact in facts:
            fact_map = {
                "subject": fact.subject, "relation": fact.relation,
                "object": fact.object, "qualifiers": fact.qualifiers,
            }
            key = _fact_key(fact_map, polarity)
            documents = tuple(sorted({_document(source) for source in fact.sources
                                      if _document(source)}))
            teacher = any(source.casefold().startswith((
                "teacher:", "user-taught", "t:")) for source in documents)
            dependent_cases = dependencies.get(key, set())
            # Missing origin configuration is explicit. Document count is a
            # useful lower-level signal, but it is not called independence.
            risk = ("thin" if len(dependent_cases) >= min_dependents
                    and len(documents) < min_documents else "unassessed")
            polarity_label = "" if polarity else "not "
            qualifiers = (f" {dict(fact.qualifiers)}" if fact.qualifiers else "")
            label = (f"{fact.subject} — {polarity_label}{fact.relation} → "
                     f"{fact.object}{qualifiers}")
            rows.append(SupportRow(
                "fact", _stable_id(fact_map, polarity), label,
                len(dependent_cases), documents, None, teacher, risk, False))
    return sorted(rows, key=lambda row: (
        -row.dependents, row.label.casefold(), row.item_id))

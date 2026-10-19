"""Report-only discovery of relation-schema candidates from explicit facts.

This first pass proposes symmetry only when the store contains explicit reverse
positive evidence. Explicit negative reverse facts are counterexamples; missing
reverse facts remain unknown under the open-world policy. Candidates are never
installed by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from crms_support_report import independent_origin_support
from crms_text import tokens


@dataclass(frozen=True)
class RelationSchemaCandidate:
    relation: str
    schema_type: str
    qualifiers: tuple[tuple[str, str], ...]
    positive_examples: tuple[dict[str, Any], ...]
    negative_examples: tuple[dict[str, Any], ...]
    unknown_reverse_pairs: int
    status: str
    independent_sources: tuple[str, ...] = ()
    source_basis: str = "source documents"


@dataclass(frozen=True)
class RelationSchemaDiscovery:
    complete: bool
    candidates: tuple[RelationSchemaCandidate, ...]
    expansions: int


def _key(value: str) -> tuple[str, ...]:
    return tokens(re.sub(r"[-‐‑‒–—]", " ", value))


def _qualifiers(value: Any) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    pairs = value.items() if isinstance(value, Mapping) else value
    normalized = []
    if not isinstance(pairs, Iterable):
        return ()
    for pair in pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            continue
        name, qualifier_value = pair
        normalized.append((_key(str(name)), _key(str(qualifier_value))))
    return tuple(sorted(normalized))


def _fact(row: Mapping[str, Any]) -> dict[str, Any]:
    fields = (row.get("subject"), row.get("relation"), row.get("object"))
    if not all(isinstance(value, str) and value.strip() for value in fields):
        raise ValueError("schema discovery facts need non-empty triple fields")
    raw_sources = row.get("sources", ())
    if isinstance(raw_sources, str):
        sources = (raw_sources,) if raw_sources else ()
    elif isinstance(raw_sources, (tuple, list, set)):
        sources = tuple(sorted({str(source) for source in raw_sources
                                if str(source).strip()}))
    else:
        sources = ()
    raw_qualifiers = row.get("qualifiers", ())
    qualifier_pairs = (
        raw_qualifiers.items() if isinstance(raw_qualifiers, Mapping)
        else raw_qualifiers if isinstance(raw_qualifiers, (tuple, list))
        else ())
    qualifiers = tuple(sorted((str(name), str(value))
                              for name, value in qualifier_pairs))
    return {"subject": fields[0].strip(), "relation": fields[1].strip(),
            "object": fields[2].strip(), "sources": sources,
            "qualifiers": qualifiers}


def discover_relation_schema_candidates(
        facts: Iterable[Mapping[str, Any]], *,
        negative_facts: Iterable[Mapping[str, Any]] = (),
        min_support: int = 2, max_expansions: int = 100_000,
        research_index: Any | None = None,
        origin_map: Mapping[str, str] | None = None
        ) -> RelationSchemaDiscovery:
    """Find symmetric-relation hypotheses from explicit reciprocal evidence.

    Each support is one unordered entity pair with positive evidence in both
    directions. A counterexample is a positive direction paired with an
    explicit negative in the reverse direction. An absent reverse statement is
    counted as unknown, never as support or contradiction.
    """
    for name, value in (("min_support", min_support),
                        ("max_expansions", max_expansions)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer")

    positives = [_fact(row) for row in facts]
    negatives = [_fact(row) for row in negative_facts]
    positives.sort(key=lambda row: (_key(row["relation"]),
                                    _key(row["subject"]),
                                    _key(row["object"]),
                                    _qualifiers(row["qualifiers"]),
                                    row["sources"]))
    negatives.sort(key=lambda row: (_key(row["relation"]),
                                    _key(row["subject"]),
                                    _key(row["object"]),
                                    _qualifiers(row["qualifiers"]),
                                    row["sources"]))

    positive_index: dict[tuple[Any, ...], dict[str, Any]] = {}
    negative_index: dict[tuple[Any, ...], dict[str, Any]] = {}
    displays: dict[tuple[str, ...], str] = {}
    for row, target in [(row, positive_index) for row in positives] + [
            (row, negative_index) for row in negatives]:
        relation = _key(row["relation"])
        subject = _key(row["subject"])
        obj = _key(row["object"])
        scope = _qualifiers(row["qualifiers"])
        displays.setdefault(relation, row["relation"])
        key = (subject, relation, obj, scope)
        previous = target.get(key)
        if previous is None:
            target[key] = row
        else:
            target[key] = dict(previous, sources=tuple(sorted(
                set(previous["sources"]) | set(row["sources"]))))

    groups: dict[tuple[tuple[str, ...], tuple[Any, ...]], dict[str, Any]] = {}
    expansions = 0
    complete = True
    processed_pairs: dict[tuple[tuple[str, ...], tuple[Any, ...]],
                          set[tuple[tuple[str, ...], tuple[str, ...]]]] = {}
    for subject, relation, obj, scope in sorted(positive_index):
        if subject == obj:
            continue
        group_key = (relation, scope)
        group = groups.setdefault(group_key, {
            "support": {}, "counterexamples": {}, "unknown": set()})
        pair = (min(subject, obj), max(subject, obj))
        seen = processed_pairs.setdefault(group_key, set())
        if pair in seen:
            continue
        if expansions >= max_expansions:
            complete = False
            break
        expansions += 1
        seen.add(pair)
        left, right = pair
        positive_left_right = positive_index.get(
            (left, relation, right, scope))
        positive_right_left = positive_index.get(
            (right, relation, left, scope))
        negative_left_right = negative_index.get(
            (left, relation, right, scope))
        negative_right_left = negative_index.get(
            (right, relation, left, scope))
        if positive_left_right is not None and positive_right_left is not None:
            group["support"][pair] = {
                "first": positive_left_right,
                "conclusion": positive_right_left}
        counterexamples = []
        if positive_left_right is not None and negative_right_left is not None:
            counterexamples.append({
                "first": positive_left_right,
                "conclusion": negative_right_left})
        if positive_right_left is not None and negative_left_right is not None:
            counterexamples.append({
                "first": positive_right_left,
                "conclusion": negative_left_right})
        if counterexamples:
            group["counterexamples"][pair] = counterexamples[0]
        if ((positive_left_right is not None) != (positive_right_left is not None)
                and ((positive_left_right is not None
                      and negative_right_left is None)
                     or (positive_right_left is not None
                         and negative_left_right is None))):
            group["unknown"].add(pair)

    candidates = []
    for (relation, scope), group in sorted(groups.items()):
        support = tuple(group["support"][key]
                        for key in sorted(group["support"]))
        if len(support) < min_support:
            continue
        counterexamples = tuple(group["counterexamples"][key]
                                for key in sorted(group["counterexamples"]))
        sources = [source for example in support
                   for field in ("first", "conclusion")
                   for source in example[field]["sources"]]
        independent, available, _copied = independent_origin_support(
            sources, research_index=research_index, origin_map=origin_map)
        if not complete:
            status = "incomplete"
        elif counterexamples:
            status = "contradicted"
        elif available and len(independent) >= min_support:
            status = "uncontradicted"
        else:
            status = "insufficient-independent-sources"
        try:
            index_has_documents = (research_index is not None
                                   and research_index.document_count() > 0)
        except (AttributeError, TypeError, ValueError, OSError):
            index_has_documents = research_index is not None
        source_basis = ("independent origins"
                        if origin_map is not None or index_has_documents
                        else "source documents")
        candidates.append(RelationSchemaCandidate(
            displays.get(relation, " ".join(relation)), "symmetric",
            tuple((" ".join(name), " ".join(value))
                  for name, value in scope), support, counterexamples,
            len(group["unknown"]), status, independent, source_basis))

    candidates.sort(key=lambda candidate: (
        _key(candidate.relation), candidate.qualifiers,
        candidate.status, -len(candidate.positive_examples)))
    return RelationSchemaDiscovery(complete, tuple(candidates), expansions)

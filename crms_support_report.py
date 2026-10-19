"""Read-only provenance and dependency summaries for accepted facts.

Origins are inferred from source URLs, known corpus identifiers, or file
locations, and can be overridden with an explicit regex map. Exact-copy
deduplication requires resolvable cited text. Dependents are limited to
verified derived cases whose proof leaves provide an exact evidence link.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from crms_text import tokens as normalized_tokens


@dataclass(frozen=True)
class SupportRow:
    item_kind: str
    item_id: str
    label: str
    dependents: int | None
    source_documents: tuple[str, ...]
    origins: tuple[str, ...]
    independent_origins: int | None
    copied: bool | None
    teacher_supported: bool
    risk: str
    origin_count_available: bool = False
    support_examples: int | None = None


def _document(source: Any) -> str:
    return str(source).split("#", 1)[0].strip()


def _origin(document: str, origin_map: Mapping[str, str] | None = None) -> str:
    lowered = document.casefold()
    if lowered.startswith(("teacher:", "user-taught", "t:")):
        return "teacher"
    if origin_map:
        for pattern, origin in sorted(origin_map.items()):
            if re.search(pattern, document, flags=re.IGNORECASE):
                return str(origin)
    parsed = urlsplit(document)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        return parsed.hostname.casefold()
    if lowered.startswith("wiki:"):
        parts = document.split(":")
        if len(parts) >= 3:
            return ":".join(parts[:2]).casefold()
    if "/" in document or "\\" in document:
        path = PurePosixPath(document.replace("\\", "/"))
        parent = path.parent.as_posix()
        return parent if parent not in {"", "."} else path.name
    return document


def _origin_for_source(document: str, research_index: Any | None,
                       origin_map: Mapping[str, str] | None) -> str:
    if document.casefold().startswith(("teacher:", "user-taught", "t:")):
        return "teacher"
    if research_index is not None:
        try:
            location = str(research_index.document(document).location or "")
        except (KeyError, ValueError, OSError):
            location = ""
        if location:
            return _origin(location, origin_map)
    return _origin(document, origin_map)


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


def _proof_rule_ids(proof: Any) -> set[str]:
    found: set[str] = set()
    stack = [proof]
    while stack:
        node = stack.pop()
        if not isinstance(node, Mapping):
            continue
        rule = node.get("rule")
        if isinstance(rule, Mapping) and rule.get("rule_id"):
            found.add(str(rule["rule_id"]))
        premises = node.get("premises", ())
        if isinstance(premises, (list, tuple)):
            stack.extend(premises)
    return found


def _source_statistics(sources: Iterable[str], research_index: Any | None,
                       origin_map: Mapping[str, str] | None
                       ) -> tuple[tuple[str, ...], tuple[str, ...], int | None,
                                  bool | None, bool, bool]:
    source_values = tuple(sorted(set(str(source) for source in sources
                                     if str(source).strip())))
    documents = tuple(sorted({_document(source) for source in source_values}))
    origins = tuple(sorted({_origin_for_source(document, research_index, origin_map)
                            for document in documents}))
    teacher = "teacher" in origins
    external_origins = {origin for origin in origins if origin != "teacher"}
    support_hashes: list[tuple[str, str]] = []
    unresolved_external = False
    for source in source_values:
        document = _document(source)
        origin = _origin_for_source(document, research_index, origin_map)
        if origin == "teacher":
            continue
        if research_index is None or "#sha256=" not in source:
            unresolved_external = True
            continue
        try:
            cited_text = research_index.resolve_citation(source)
        except (KeyError, ValueError, OSError):
            unresolved_external = True
            continue
        digest = hashlib.sha256(
            " ".join(_tokens(cited_text)).encode("utf-8")).hexdigest()
        support_hashes.append((origin, digest))
    copied: bool | None
    independent_origins: int | None
    if not source_values:
        copied, independent_origins, available = None, None, False
    elif not unresolved_external:
        owners: dict[str, set[str]] = {}
        for origin, digest in support_hashes:
            owners.setdefault(digest, set()).add(origin)
        copied = any(len(supporting_origins) > 1
                     for supporting_origins in owners.values())
        independent_origins = len({min(supporting_origins)
                                    for supporting_origins in owners.values()})
        available = True
    elif len(external_origins) <= 1:
        independent_origins = len(external_origins)
        copied = False
        available = True
    else:
        copied, independent_origins, available = None, None, False
    return (documents, origins, independent_origins, copied, teacher, available)


def _stable_id(fact: Mapping[str, Any], polarity: bool) -> str:
    payload = json.dumps(
        _fact_key(fact, polarity), sort_keys=True, ensure_ascii=False,
        separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def support_report(knowledge_base: Any, *, min_dependents: int = 3,
                   min_origins: int = 2,
                   research_index: Any | None = None,
                   origin_map: Mapping[str, str] | None = None
                   ) -> list[SupportRow]:
    """List fact support and verified derived-case dependencies without mutation.

    Independent-origin counts require resolvable citation text when multiple
    origins are present, because exact copies count once. Teacher support is
    shown separately and never contributes to external independence.
    """
    if type(min_dependents) is not int or min_dependents < 0:
        raise ValueError("min_dependents must be a non-negative integer")
    if type(min_origins) is not int or min_origins < 1:
        raise ValueError("min_origins must be a positive integer")

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
            (documents, origins, independent_origins, copied, teacher,
             origin_count_available) = _source_statistics(
                fact.sources, research_index, origin_map)
            dependent_cases = dependencies.get(key, set())
            risk = ("thin" if len(dependent_cases) >= min_dependents
                    and origin_count_available
                    and independent_origins < min_origins else "unassessed")
            polarity_label = "" if polarity else "not "
            qualifiers = (f" {dict(fact.qualifiers)}" if fact.qualifiers else "")
            label = (f"{fact.subject} — {polarity_label}{fact.relation} → "
                     f"{fact.object}{qualifiers}")
            rows.append(SupportRow(
                "fact", _stable_id(fact_map, polarity), label,
                len(dependent_cases), documents, origins, independent_origins,
                copied, teacher, risk, origin_count_available))

    rule_dependents: dict[str, set[str]] = {}
    for case in verified_cases:
        case_id = json.dumps(case.get("conclusion", {}), sort_keys=True,
                             ensure_ascii=False)
        for proof in case.get("proofs", ()):
            for rule_id in _proof_rule_ids(proof):
                rule_dependents.setdefault(rule_id, set()).add(case_id)
    for rule in getattr(knowledge_base, "_inference_rules", {}).values():
        validation = getattr(knowledge_base, "_inference_rule_validation", {}).get(
            _tokens(rule.rule_id), {})
        sources = set()
        for field in ("training_positive_examples", "positive_examples"):
            for example in validation.get(field, ()):
                if not isinstance(example, Mapping):
                    continue
                for fact in example.values():
                    if isinstance(fact, Mapping):
                        sources.update(str(source) for source in fact.get("sources", ()))
        (documents, origins, independent_origins, copied, teacher,
         origin_count_available) = _source_statistics(
            sources, research_index, origin_map)
        dependents = rule_dependents.get(rule.rule_id, set())
        risk = ("thin" if len(dependents) >= min_dependents
                and origin_count_available
                and independent_origins < min_origins else "unassessed")
        label = (f"Rule {rule.rule_id}: {rule.first_relation} then "
                 f"{rule.second_relation} ⇒ {rule.conclusion_relation}")
        if rule.third_relation:
            label = (f"Rule {rule.rule_id}: {rule.first_relation} then "
                     f"{rule.second_relation} then {rule.third_relation} ⇒ "
                     f"{rule.conclusion_relation}")
        rows.append(SupportRow(
            "rule", hashlib.sha256(rule.rule_id.encode("utf-8")).hexdigest()[:20],
            label, len(dependents), documents, origins, independent_origins,
            copied, teacher, risk, origin_count_available))
    for (template, relation), examples in getattr(
            knowledge_base, "_fact_pattern_examples", {}).items():
        sources = {source for pair_sources in examples.values()
                   for source in pair_sources}
        (documents, origins, independent_origins, copied, teacher,
         origin_count_available) = _source_statistics(
            sources, research_index, origin_map)
        polarity = getattr(knowledge_base, "_fact_pattern_polarities", {}).get(
            (template, relation), True)
        surface = " ".join(template).replace("<subject>", "{subject}")
        surface = surface.replace("<object>", "{object}")
        polarity_label = "positive" if polarity else "negative"
        label = (f"Frame {surface} ⇒ {' '.join(relation)} "
                 f"({polarity_label})")
        frame_key = json.dumps(
            [template, relation, polarity], ensure_ascii=False,
            separators=(",", ":"))
        item_id = hashlib.sha256(frame_key.encode("utf-8")).hexdigest()[:20]
        rows.append(SupportRow(
            "frame", item_id, label, None, documents, origins,
            independent_origins, copied, teacher, "unassessed",
            origin_count_available, len(examples)))
    return sorted(rows, key=lambda row: (
        -(row.dependents or 0), row.label.casefold(), row.item_id))

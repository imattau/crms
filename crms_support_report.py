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
    dependents: int
    source_documents: tuple[str, ...]
    origins: tuple[str, ...]
    independent_origins: int | None
    copied: bool | None
    teacher_supported: bool
    risk: str
    origin_count_available: bool = False


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
            documents = tuple(sorted({_document(source) for source in fact.sources
                                      if _document(source)}))
            origins = tuple(sorted({_origin_for_source(source, research_index, origin_map)
                                    for source in documents}))
            teacher = "teacher" in origins
            external_origins = {origin for origin in origins
                                if origin != "teacher"}
            support_hashes: list[tuple[str, str]] = []
            unresolved_external = False
            for source in fact.sources:
                document = _document(source)
                origin = _origin_for_source(document, research_index, origin_map)
                if origin == "teacher":
                    continue
                if research_index is None or "#sha256=" not in str(source):
                    unresolved_external = True
                    continue
                try:
                    cited_text = research_index.resolve_citation(str(source))
                except (KeyError, ValueError, OSError):
                    unresolved_external = True
                    continue
                digest = hashlib.sha256(
                    " ".join(_tokens(cited_text)).encode("utf-8")).hexdigest()
                support_hashes.append((origin, digest))
            copied = None
            if not unresolved_external:
                hashes_by_origin: dict[str, set[str]] = {}
                for origin, digest in support_hashes:
                    hashes_by_origin.setdefault(origin, set()).add(digest)
                hashes_by_origin = {origin: hashes for origin, hashes in
                                    hashes_by_origin.items() if origin != "teacher"}
                owners: dict[str, set[str]] = {}
                for origin, hashes in hashes_by_origin.items():
                    for digest in hashes:
                        owners.setdefault(digest, set()).add(origin)
                copied = any(len(owners_for_hash) > 1
                             for owners_for_hash in owners.values())
                # A verbatim statement copied across origins contributes once.
                independent_origin_set = {
                    min(owners_for_hash)
                    for owners_for_hash in owners.values()
                }
                independent_origins = len(independent_origin_set)
                origin_count_available = True
            elif len(external_origins) <= 1:
                # Copies cannot raise a count of one known external origin.
                independent_origins = len(external_origins)
                origin_count_available = True
                copied = False
            else:
                independent_origins = None
                origin_count_available = False
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
    return sorted(rows, key=lambda row: (
        -row.dependents, row.label.casefold(), row.item_id))

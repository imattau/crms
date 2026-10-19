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


def _proof_sources(proof: Any) -> set[str]:
    found: set[str] = set()
    stack = [proof]
    while stack:
        node = stack.pop()
        if not isinstance(node, Mapping):
            continue
        for field in ("fact", "middle_kind_fact", "relation_type_fact"):
            fact = node.get(field)
            if isinstance(fact, Mapping):
                found.update(str(source) for source in fact.get("sources", ()))
        for fact in node.get("middle_kind_facts", ()):
            if isinstance(fact, Mapping):
                found.update(str(source) for source in fact.get("sources", ()))
        premises = node.get("premises", ())
        if isinstance(premises, (list, tuple)):
            stack.extend(premises)
    return found


def _lineage_sources(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in {"sources", "expected_sources", "actual_sources"}:
                if isinstance(item, (list, tuple, set)):
                    found.update(str(source) for source in item if str(source))
            else:
                found.update(_lineage_sources(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_lineage_sources(item))
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


def independent_origin_support(
        sources: Iterable[str], *, research_index: Any | None = None,
        origin_map: Mapping[str, str] | None = None
        ) -> tuple[tuple[str, ...], bool, bool | None]:
    """Return independent support origins, availability, and copy status.

    When citations resolve, exact copied statements across origins count once.
    If several origins are present but citation text cannot be resolved, the
    count is unavailable instead of treating document IDs as independent
    evidence. Teacher-only evidence is available but contributes no external
    origins.
    """
    documents, origins, count, copied, _teacher, available = _source_statistics(
        sources, research_index, origin_map)
    if count is None or not available:
        return (), False, copied
    # The report's count intentionally excludes teachers and duplicate copies.
    # Keep a stable, human-readable origin list where possible; if exact-copy
    # deduplication makes the count smaller than the nominal origin set, expose
    # only the count to callers rather than pretending to know which publisher
    # uniquely owns each distinct statement.
    external = tuple(origin for origin in origins if origin != "teacher")
    if len(external) != count:
        external = tuple(f"independent-origin-{i + 1}" for i in range(count))
    return external, True, copied


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
    question_frame_fact_dependencies: dict[tuple[Any, ...], set[str]] = {}
    question_frame_rule_dependencies: dict[str, set[str]] = {}
    verified_cases = [case for case in knowledge_base.derived_cases()
                      if case.get("status") == "verified"]
    for case in verified_cases:
        case_id = json.dumps(case.get("conclusion", {}), sort_keys=True,
                             ensure_ascii=False)
        for proof in case.get("proofs", ()):
            for key in _proof_fact_keys(proof):
                dependencies.setdefault(key, set()).add(case_id)
    for frame_key, by_entity in getattr(
            knowledge_base, "_question_example_evidence", {}).items():
        frame_id = hashlib.sha256(json.dumps(
            [frame_key[0], frame_key[1], frame_key[2], frame_key[3]],
            ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        for records in by_entity.values():
            for record in records:
                for fact in record.get("direct_facts", ()):
                    if isinstance(fact, Mapping):
                        question_frame_fact_dependencies.setdefault(
                            _fact_key(fact), set()).add(frame_id)
                for proof in record.get("proofs", ()):
                    for fact_key in _proof_fact_keys(proof):
                        question_frame_fact_dependencies.setdefault(
                            fact_key, set()).add(frame_id)
                    for rule_id in _proof_rule_ids(proof):
                        question_frame_rule_dependencies.setdefault(
                            rule_id, set()).add(frame_id)

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
            dependents = (dependencies.get(key, set())
                          | question_frame_fact_dependencies.get(key, set()))
            risk = ("thin" if len(dependents) >= min_dependents
                    and origin_count_available
                    and independent_origins < min_origins else "unassessed")
            polarity_label = "" if polarity else "not "
            qualifiers = (f" {dict(fact.qualifiers)}" if fact.qualifiers else "")
            label = (f"{fact.subject} — {polarity_label}{fact.relation} → "
                     f"{fact.object}{qualifiers}")
            rows.append(SupportRow(
                "fact", _stable_id(fact_map, polarity), label,
                len(dependents), documents, origins, independent_origins,
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
        dependents = (rule_dependents.get(rule.rule_id, set())
                      | question_frame_rule_dependencies.get(rule.rule_id, set()))
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
    for key, by_entity in getattr(
            knowledge_base, "_question_example_evidence", {}).items():
        relation = tuple(json.loads(key[0]))
        answer_field = key[1]
        bound_field = "object" if answer_field == "subject" else "subject"
        template = " ".join((*key[2], "{" + bound_field + "}", *key[3]))
        sources = set()
        supported_examples = 0
        for records in by_entity.values():
            example_has_support = False
            for record in records:
                for fact in record.get("direct_facts", ()):
                    if isinstance(fact, Mapping):
                        sources.update(str(source)
                                       for source in fact.get("sources", ()))
                        example_has_support = True
                for proof in record.get("proofs", ()):
                    sources.update(_proof_sources(proof))
                    example_has_support = True
            supported_examples += int(example_has_support)
        (documents, origins, independent_origins, copied, teacher,
         origin_count_available) = _source_statistics(
            sources, research_index, origin_map)
        label = (f"Question frame {template} ⇒ {' '.join(relation)} "
                 f"(answers {answer_field})")
        frame_key = json.dumps([key[0], answer_field, key[2], key[3]],
                               ensure_ascii=False, separators=(",", ":"))
        item_id = hashlib.sha256(frame_key.encode("utf-8")).hexdigest()[:20]
        rows.append(SupportRow(
            "frame", item_id, label, None, documents, origins,
            independent_origins, copied, teacher, "unassessed",
            origin_count_available, supported_examples))
    induced_proposals = []
    for attribute in ("_induced_question_frames",
                      "_induced_qualified_question_frames",
                      "_induced_multi_qualified_question_frames"):
        induced_proposals.extend(getattr(knowledge_base, attribute, {}).values())
    if induced_proposals:
        from crms_question_induction import question_frame_proposal_sources_current
        for proposal in induced_proposals:
            if not question_frame_proposal_sources_current(knowledge_base, proposal):
                continue
            lineage = proposal.get("lineage", {})
            sources = _lineage_sources(lineage)
            (documents, origins, independent_origins, copied, teacher,
             origin_count_available) = _source_statistics(
                sources, research_index, origin_map)
            kind = str(proposal.get("kind", "induced_question_frame"))
            relation = str(proposal.get("target_relation", "unknown relation"))
            answer_field = str(proposal.get("answer_field", "unknown"))
            prefix = proposal.get("prefix")
            suffix = proposal.get("suffix")
            if isinstance(prefix, (list, tuple)) and isinstance(suffix, (list, tuple)):
                bound_field = "object" if answer_field == "subject" else "subject"
                template = " ".join((*map(str, prefix),
                                      "{" + bound_field + "}",
                                      *map(str, suffix)))
                label = f"Induced question frame {template} ⇒ {relation}"
            else:
                label = (f"Induced question frame for {relation} "
                         f"(answers {answer_field}; {kind})")
            artifact_id = str(proposal.get("artifact_id", ""))
            item_id = artifact_id or hashlib.sha256(
                json.dumps(proposal, sort_keys=True, ensure_ascii=False,
                           default=str).encode("utf-8")).hexdigest()[:20]
            training_examples = lineage.get("training_examples", ())
            support_examples = (len(training_examples)
                                if isinstance(training_examples, (list, tuple))
                                else int(proposal.get("training_entities", 0)))
            rows.append(SupportRow(
                "frame", item_id, label, None, documents, origins,
                independent_origins, copied, teacher, "unassessed",
                origin_count_available, support_examples))
    return sorted(rows, key=lambda row: (
        -(row.dependents or 0), row.label.casefold(), row.item_id))

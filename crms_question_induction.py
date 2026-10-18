"""Report-only analogy proposals for fact-backed natural-language frames."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from crms_knowledge import CRMSKnowledgeBase, _tokens


def _replace_once(words: tuple[str, ...], old: tuple[str, ...],
                  new: tuple[str, ...]) -> tuple[tuple[str, ...], int] | None:
    locations = [index for index in range(len(words) - len(old) + 1)
                 if words[index:index + len(old)] == old]
    if len(locations) != 1:
        return None
    index = locations[0]
    return words[:index] + new + words[index + len(old):], index


def _target_predicates(kb: CRMSKnowledgeBase
                       ) -> dict[tuple[str, ...], list[dict[str, object]]]:
    """Collect exact canonical predicate forms from licensed source frames."""
    result: dict[tuple[str, ...], list[dict[str, object]]] = {}
    for key, examples in kb._fact_pattern_examples.items():
        if not kb._fact_pattern_is_licensed(key, examples):
            continue
        relation = key[1]
        if tuple(key[0]) != ("<subject>", "<predicate>", "<object>"):
            continue
        forms = kb._fact_pattern_predicates.get(key, set())
        for phrase in forms:
            if phrase != relation:
                continue
            rows = kb._fact_pattern_predicate_sources.get(key, {}).get(phrase, {})
            support = [{"subject": list(subject), "object": list(obj),
                        "sources": sorted(sources)}
                       for (subject, obj), sources in sorted(rows.items())]
            if support:
                result.setdefault(relation, []).append({
                    "relation": list(relation),
                    "predicate_phrase": list(phrase),
                    "support": support,
                })
    return result


def _bound(fact: Any, answer_field: str) -> str:
    return fact.object if answer_field == "subject" else fact.subject


def _answer(fact: Any, answer_field: str) -> str:
    return fact.subject if answer_field == "subject" else fact.object


def _source_key(fact: Any) -> str:
    source = sorted(fact.sources)[0] if fact.sources else ""
    return source.split("#", 1)[0]


def _source_documents(fact: Any) -> set[str]:
    return {source.split("#", 1)[0] for source in fact.sources
            if isinstance(source, str) and source}


def _qualifier_value(fact: Any, name: tuple[str, ...]) -> str:
    return next((str(value) for key, value in fact.qualifiers
                 if tuple(str(key).casefold().split()) == name), "")


def _select_split(facts: list[Any], answer_field: str, *,
                  train_count: int, holdout_count: int
                  ) -> tuple[list[tuple[Any, set[str]]],
                             list[tuple[Any, set[str]]]] | None:
    by_entity: dict[tuple[str, ...], list[Any]] = {}
    for fact in sorted(facts, key=lambda item: (
            _bound(item, answer_field).casefold(), _source_key(item))):
        entity = tuple(_bound(fact, answer_field).casefold().split())
        if entity and _source_documents(fact):
            by_entity.setdefault(entity, []).append(fact)
    ordered = sorted(by_entity)
    train: list[tuple[Any, set[str]]] = []
    train_entities: set[tuple[str, ...]] = set()
    train_sources: set[str] = set()
    for entity in ordered:
        entity_facts = by_entity[entity]
        answers = {_answer(fact, answer_field).casefold() for fact in entity_facts}
        sources = {source for fact in entity_facts
                   for source in _source_documents(fact)}
        if (len(answers) == 1 and sources
                and not sources.intersection(train_sources)):
            train.append((entity_facts[0], sources))
            train_entities.add(entity)
            train_sources.update(sources)
        if len(train) == train_count:
            break
    if len(train) != train_count:
        return None
    holdout: list[tuple[Any, set[str]]] = []
    holdout_sources: set[str] = set()
    for entity in ordered:
        if entity in train_entities:
            continue
        entity_facts = by_entity[entity]
        sources = {source for fact in entity_facts
                   for source in _source_documents(fact)}
        if not sources.intersection(train_sources | holdout_sources):
            holdout.append((entity_facts[0], sources))
            holdout_sources.update(sources)
        if len(holdout) == holdout_count:
            break
    if len(holdout) == holdout_count:
        return train, holdout
    return None


def propose_analogical_question_frames(
        kb: CRMSKnowledgeBase, *, minimum_training_entities: int = 2,
        minimum_holdout_entities: int = 2,
        maximum_proposals: int = 100) -> list[dict[str, object]]:
    """Find source-backed relation substitutions and validate them on a clone.

    A proposal copies one licensed question frame's structure, replacing its
    canonical relation phrase only when that exact phrase occurs once. The new
    relation must have a licensed source-backed predicate frame. Training and
    holdout facts must use disjoint source documents and distinct bound entities.
    Proposals are returned as report-only artifacts; ``kb`` is never mutated.
    """
    if (type(minimum_training_entities) is not int
            or not 2 <= minimum_training_entities <= 20
            or type(minimum_holdout_entities) is not int
            or not 1 <= minimum_holdout_entities <= 20
            or type(maximum_proposals) is not int
            or not 1 <= maximum_proposals <= 1000):
        raise ValueError("question-frame proposal bounds are outside supported limits")
    predicates = _target_predicates(kb)
    facts = [fact for fact in kb.facts() if not fact.qualifiers]
    proposals: list[dict[str, object]] = []
    for (base_relation_json, answer_field, prefix, suffix), base_examples in sorted(
            kb._question_examples.items()):
        if not kb._question_frame_is_licensed(
                (base_relation_json, answer_field, prefix, suffix), base_examples):
            continue
        base_relation = tuple(json.loads(base_relation_json))
        frame_words = prefix + ("<bound_entity>",) + suffix
        if _replace_once(frame_words, base_relation, ("<relation>",)) is None:
            continue
        base_support = []
        for entity, _example_values in sorted(base_examples.items()):
            supporting_facts = [fact for fact in facts
                                if tuple(fact.relation.casefold().split()) == base_relation
                                and tuple(_bound(fact, answer_field).casefold().split()) == entity]
            source_values = sorted({source for fact in supporting_facts
                                    for source in fact.sources})
            if not source_values:
                base_support = []
                break
            base_support.append({"bound_entity": list(entity),
                                 "sources": source_values})
        if not base_support:
            continue
        for target_relation, predicate_rows in sorted(predicates.items()):
            if target_relation == base_relation:
                continue
            target_replacement = _replace_once(
                frame_words, base_relation, target_relation)
            if target_replacement is None:
                continue
            candidate_words, _ = target_replacement
            candidate_prefix, candidate_suffix = [], []
            marker_seen = False
            for token in candidate_words:
                if token == "<bound_entity>":
                    marker_seen = True
                    continue
                (candidate_suffix if marker_seen else candidate_prefix).append(token)
            target_facts = [fact for fact in facts
                            if tuple(fact.relation.casefold().split()) == target_relation]
            split = _select_split(
                target_facts, answer_field,
                train_count=minimum_training_entities,
                holdout_count=minimum_holdout_entities)
            if split is None:
                continue
            training, holdout = split
            training_sources = {source for _fact, sources in training
                                for source in sources}
            training_pairs = {(tuple(fact.subject.casefold().split()),
                               tuple(fact.object.casefold().split()))
                              for fact, _sources in training}
            training_predicates = []
            for predicate_row in predicate_rows:
                support = []
                for row in predicate_row["support"]:
                    if (tuple(row["subject"]), tuple(row["object"])) not in training_pairs:
                        continue
                    row_sources = [source for source in row["sources"]
                                   if source.split("#", 1)[0] in training_sources]
                    if row_sources:
                        support.append({**row, "sources": row_sources})
                subjects = {tuple(row["subject"]) for row in support}
                objects = {tuple(row["object"]) for row in support}
                source_documents = {source.split("#", 1)[0]
                                    for row in support
                                    for source in row["sources"]}
                if (len(support) >= minimum_training_entities
                        and len(subjects) >= minimum_training_entities
                        and len(objects) >= minimum_training_entities
                        and len(source_documents) >= minimum_training_entities):
                    training_predicates.append({
                        **predicate_row, "support": support})
            if not training_predicates:
                continue
            candidate_kb = deepcopy(kb)
            training_examples = []
            try:
                for fact, entity_sources in training:
                    question = " ".join(candidate_prefix +
                                        list(_bound(fact, answer_field).casefold().split()) +
                                        candidate_suffix)
                    candidate_kb.teach_question(
                        question, relation=" ".join(target_relation),
                        answer_field=answer_field,
                        bound_entity=_bound(fact, answer_field),
                        answer=_answer(fact, answer_field))
                    training_examples.append({
                        "question": question,
                        "bound_entity": _bound(fact, answer_field),
                        "answer": _answer(fact, answer_field),
                        "source": _source_key(fact),
                        "sources": sorted(entity_sources),
                    })
            except ValueError:
                continue

            validation = []
            valid = True
            for fact, _entity_sources in holdout:
                question = " ".join(candidate_prefix +
                                    list(_bound(fact, answer_field).casefold().split()) +
                                    candidate_suffix)
                actual = candidate_kb.ask(question)
                expected_answers = sorted({
                    _answer(other, answer_field) for other in target_facts
                    if _bound(other, answer_field).casefold()
                    == _bound(fact, answer_field).casefold()}, key=str.casefold)
                expected_status = "answered" if len(expected_answers) == 1 else "ambiguous"
                actual_answers = ([actual.answer] if actual.status == "answered" else
                                  sorted(actual.candidates or [], key=str.casefold)
                                  if actual.status == "ambiguous" else [])
                expected_sources = sorted({
                    source for other in target_facts
                    if _bound(other, answer_field).casefold()
                    == _bound(fact, answer_field).casefold()
                    for source in other.sources})
                actual_sources = sorted({
                    source for item in actual.evidence
                    for source in item.get("sources", [])})
                passed = (actual.status == expected_status
                          and actual_answers == expected_answers
                          and actual_sources == expected_sources
                          and bool(actual.matched_templates))
                validation.append({
                    "question": question,
                    "bound_entity": _bound(fact, answer_field),
                    "expected_status": expected_status,
                    "expected_answers": expected_answers,
                    "actual_status": actual.status,
                    "actual_answers": actual_answers,
                    "expected_sources": expected_sources,
                    "actual_sources": actual_sources,
                    "passed": passed,
                })
                valid = valid and passed
            if not valid:
                continue
            train_documents = {source.split("#", 1)[0]
                              for row in training_examples
                              for source in row["sources"]}
            heldout_documents = {source.split("#", 1)[0]
                                 for row in validation
                                 for source in row["expected_sources"]}
            source_separated = not train_documents.intersection(heldout_documents)
            if not source_separated:
                continue
            lineage = {
                "base_relation": " ".join(base_relation),
                "base_frame": list(frame_words),
                "base_frame_examples": base_support,
                "target_predicate_evidence": training_predicates,
                "training_examples": training_examples,
                "holdout_results": validation,
                "training_source_documents": sorted(train_documents),
                "holdout_source_documents": sorted(heldout_documents),
                "source_separation": source_separated,
            }
            artifact_id = "question-frame-proposal-v1-" + hashlib.sha256(
                json.dumps(lineage, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode()).hexdigest()[:24]
            proposals.append({
                "kind": "analogical_question_frame",
                "artifact_id": artifact_id,
                "base_relation": " ".join(base_relation),
                "target_relation": " ".join(target_relation),
                "answer_field": answer_field,
                "prefix": candidate_prefix,
                "suffix": candidate_suffix,
                "training_entities": len(training),
                "heldout_entities": len(holdout),
                "validation_passed": True,
                "lineage": lineage,
                "report_only": True,
            })
            if len(proposals) >= maximum_proposals:
                return proposals
    return proposals


def _qualified_split(facts: list[Any], answer_field: str,
                    qualifier_name: tuple[str, ...], *, train_count: int,
                    holdout_count: int
                    ) -> tuple[list[tuple[Any, set[str]]],
                               list[tuple[Any, set[str]]]] | None:
    """Choose source-separated examples with distinct entities and values."""
    grouped: dict[tuple[tuple[str, ...], tuple[str, ...]], list[Any]] = {}
    for fact in facts:
        qualifiers = {tuple(str(name).casefold().split()): str(value)
                      for name, value in fact.qualifiers}
        if len(qualifiers) != 1 or qualifier_name not in qualifiers:
            continue
        entity = tuple(_bound(fact, answer_field).casefold().split())
        value = tuple(qualifiers[qualifier_name].casefold().split())
        if entity and value and _source_documents(fact):
            grouped.setdefault((entity, value), []).append(fact)

    def choose(candidates: list[tuple[tuple[str, ...], tuple[str, ...]]],
               count: int, used_entities: set[tuple[str, ...]],
               used_values: set[tuple[str, ...]], used_sources: set[str]
               ) -> list[tuple[Any, set[str]]] | None:
        selected = []
        for entity, value in candidates:
            if entity in used_entities or value in used_values:
                continue
            rows = grouped[(entity, value)]
            answers = {_answer(fact, answer_field).casefold() for fact in rows}
            if len(answers) != 1:
                continue
            sources = {source for fact in rows
                       for source in _source_documents(fact)}
            if not sources or sources.intersection(used_sources):
                continue
            selected.append((rows[0], sources))
            used_entities.add(entity)
            used_values.add(value)
            used_sources.update(sources)
            if len(selected) == count:
                return selected
        return None

    ordered = sorted(grouped)
    train = choose(ordered, train_count, set(), set(), set())
    if train is None:
        return None
    train_entities = {_tokens(_bound(fact, answer_field)) for fact, _ in train}
    train_values = {_tokens(_qualifier_value(fact, qualifier_name))
                    for fact, _ in train}
    train_sources = {source for _, sources in train for source in sources}
    holdout = choose(ordered, holdout_count, train_entities, train_values,
                     set(train_sources))
    if holdout is None:
        return None
    return train, holdout


def propose_analogical_qualified_question_frames(
        kb: CRMSKnowledgeBase, *, minimum_training_examples: int = 2,
        minimum_holdout_examples: int = 2,
        maximum_proposals: int = 100) -> list[dict[str, object]]:
    """Propose relation substitutions for licensed one-qualifier frames.

    Training and held-out examples require distinct bound entities and
    qualifier values, with no source document shared across the split. Every
    target example is a direct qualified fact; inferred targets are not
    synthesized by this proposer.
    """
    if (type(minimum_training_examples) is not int
            or not 2 <= minimum_training_examples <= 20
            or type(minimum_holdout_examples) is not int
            or not 1 <= minimum_holdout_examples <= 20
            or type(maximum_proposals) is not int
            or not 1 <= maximum_proposals <= 1000):
        raise ValueError("qualified question-frame proposal bounds are outside limits")
    predicates = _target_predicates(kb)
    facts = list(kb.facts())
    proposals: list[dict[str, object]] = []

    for (base_relation, answer_field, qualifier_name, entity_first,
         prefix, middle, suffix), base_examples in sorted(
            kb._qualified_question_examples.items()):
        if (len(base_examples) < 2
                or len({entity for entity, _value in base_examples}) < 2
                or len({value for _entity, value in base_examples}) < 2):
            continue
        base_words = (prefix + (("<bound_entity>",) + middle
                                + ("<qualifier_value>",) if entity_first else
                                ("<qualifier_value>",) + middle
                                + ("<bound_entity>",)) + suffix)
        if _replace_once(base_words, base_relation, ("<relation>",)) is None:
            continue

        base_support = []
        for (entity, value), answers in sorted(base_examples.items()):
            matching = [fact for fact in facts
                        if tuple(fact.relation.casefold().split()) == base_relation
                        and _tokens(_bound(fact, answer_field)) == entity
                        and _tokens(_qualifier_value(fact, qualifier_name)) == value
                        and {item.casefold() for item in answers}
                            .intersection({_answer(fact, answer_field).casefold()})]
            sources = sorted({source for fact in matching for source in fact.sources})
            if not sources:
                base_support = []
                break
            base_support.append({"bound_entity": list(entity),
                                 "qualifier_value": list(value),
                                 "sources": sources})
        if not base_support:
            continue

        for target_relation, predicate_rows in sorted(predicates.items()):
            if target_relation == base_relation:
                continue
            replacement = _replace_once(base_words, base_relation, target_relation)
            if replacement is None:
                continue
            words, _index = replacement
            try:
                entity_index = words.index("<bound_entity>")
                value_index = words.index("<qualifier_value>")
            except ValueError:
                continue
            if entity_index < value_index:
                candidate_entity_first = True
                candidate_prefix = list(words[:entity_index])
                candidate_middle = list(words[entity_index + 1:value_index])
                candidate_suffix = list(words[value_index + 1:])
            else:
                candidate_entity_first = False
                candidate_prefix = list(words[:value_index])
                candidate_middle = list(words[value_index + 1:entity_index])
                candidate_suffix = list(words[entity_index + 1:])
            target_facts = [fact for fact in facts
                            if tuple(fact.relation.casefold().split()) == target_relation
                            and len(fact.qualifiers) == 1
                            and tuple(fact.qualifiers[0][0].casefold().split())
                                == qualifier_name]
            split = _qualified_split(
                target_facts, answer_field, qualifier_name,
                train_count=minimum_training_examples,
                holdout_count=minimum_holdout_examples)
            if split is None:
                continue
            training, holdout = split
            training_sources = {source for _fact, sources in training
                                for source in sources}
            training_pairs = {(tuple(fact.subject.casefold().split()),
                               tuple(fact.object.casefold().split()))
                              for fact, _sources in training}
            training_predicates = []
            for predicate_row in predicate_rows:
                support = []
                for row in predicate_row["support"]:
                    if (tuple(row["subject"]), tuple(row["object"])) not in training_pairs:
                        continue
                    row_sources = [source for source in row["sources"]
                                   if source.split("#", 1)[0] in training_sources]
                    if row_sources:
                        support.append({**row, "sources": row_sources})
                documents = {source.split("#", 1)[0]
                             for row in support for source in row["sources"]}
                subjects = {tuple(row["subject"]) for row in support}
                objects = {tuple(row["object"]) for row in support}
                if (len(support) >= minimum_training_examples
                        and len(subjects) >= minimum_training_examples
                        and len(objects) >= minimum_training_examples
                        and len(documents) >= minimum_training_examples):
                    training_predicates.append({**predicate_row, "support": support})
            if not training_predicates:
                continue

            candidate_kb = deepcopy(kb)
            training_examples = []
            try:
                for fact, sources in training:
                    entity = _bound(fact, answer_field)
                    qualifier_value = _qualifier_value(fact, qualifier_name)
                    entity_tokens = list(_tokens(entity))
                    value_tokens = list(_tokens(qualifier_value))
                    question_tokens = (
                        candidate_prefix + entity_tokens + candidate_middle
                        + value_tokens + candidate_suffix
                        if candidate_entity_first else
                        candidate_prefix + value_tokens + candidate_middle
                        + entity_tokens + candidate_suffix)
                    question = " ".join(question_tokens)
                    candidate_kb.teach_qualified_question(
                        question, relation=" ".join(target_relation),
                        answer_field=answer_field, bound_entity=entity,
                        answer=_answer(fact, answer_field),
                        qualifier={" ".join(qualifier_name): qualifier_value})
                    training_examples.append({
                        "question": question,
                        "bound_entity": entity,
                        "qualifier_value": qualifier_value,
                        "answer": _answer(fact, answer_field),
                        "sources": sorted(sources),
                    })
            except ValueError:
                continue

            validation = []
            valid = True
            for fact, _sources in holdout:
                entity = _bound(fact, answer_field)
                qualifier_value = _qualifier_value(fact, qualifier_name)
                entity_tokens = list(_tokens(entity))
                value_tokens = list(_tokens(qualifier_value))
                question_tokens = (
                    candidate_prefix + entity_tokens + candidate_middle
                    + value_tokens + candidate_suffix
                    if candidate_entity_first else
                    candidate_prefix + value_tokens + candidate_middle
                    + entity_tokens + candidate_suffix)
                question = " ".join(question_tokens)
                actual = candidate_kb.ask(question)
                matches = [other for other in target_facts
                           if _tokens(_bound(other, answer_field)) == _tokens(entity)
                           and _tokens(_qualifier_value(other, qualifier_name))
                               == _tokens(qualifier_value)]
                expected_answers = sorted({_answer(other, answer_field)
                                           for other in matches}, key=str.casefold)
                expected_status = "answered" if len(expected_answers) == 1 else "ambiguous"
                actual_answers = ([actual.answer] if actual.status == "answered" else
                                  sorted(actual.candidates or [], key=str.casefold)
                                  if actual.status == "ambiguous" else [])
                expected_sources = sorted({source for other in matches
                                           for source in other.sources})
                actual_sources = sorted({source for item in actual.evidence
                                         for source in item.get("sources", [])})
                passed = (actual.status == expected_status
                          and actual_answers == expected_answers
                          and actual_sources == expected_sources
                          and bool(actual.matched_templates))
                validation.append({
                    "question": question,
                    "bound_entity": entity,
                    "qualifier_value": qualifier_value,
                    "expected_status": expected_status,
                    "expected_answers": expected_answers,
                    "actual_status": actual.status,
                    "actual_answers": actual_answers,
                    "expected_sources": expected_sources,
                    "actual_sources": actual_sources,
                    "passed": passed,
                })
                valid = valid and passed
            if not valid:
                continue

            train_documents = {source.split("#", 1)[0]
                               for row in training_examples for source in row["sources"]}
            holdout_documents = {source.split("#", 1)[0]
                                 for row in validation for source in row["expected_sources"]}
            if train_documents.intersection(holdout_documents):
                continue
            lineage = {
                "base_relation": " ".join(base_relation),
                "base_frame": list(base_words),
                "base_frame_examples": base_support,
                "qualifier_name": " ".join(qualifier_name),
                "entity_first": entity_first,
                "target_predicate_evidence": training_predicates,
                "training_examples": training_examples,
                "holdout_results": validation,
                "training_source_documents": sorted(train_documents),
                "holdout_source_documents": sorted(holdout_documents),
                "source_separation": True,
            }
            artifact_id = "qualified-question-frame-proposal-v1-" + hashlib.sha256(
                json.dumps(lineage, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode()).hexdigest()[:24]
            proposals.append({
                "kind": "analogical_qualified_question_frame",
                "artifact_id": artifact_id,
                "base_relation": " ".join(base_relation),
                "target_relation": " ".join(target_relation),
                "answer_field": answer_field,
                "qualifier_name": " ".join(qualifier_name),
                "entity_first": candidate_entity_first,
                "prefix": candidate_prefix,
                "middle": candidate_middle,
                "suffix": candidate_suffix,
                "training_entities": len(training),
                "heldout_entities": len(holdout),
                "validation_passed": True,
                "lineage": lineage,
                "report_only": True,
            })
            if len(proposals) >= maximum_proposals:
                return proposals
    return proposals


def _multi_qualified_split(
        facts: list[Any], answer_field: str,
        qualifier_names: tuple[tuple[str, ...], ...], *,
        train_count: int, holdout_count: int
        ) -> tuple[list[tuple[Any, set[str]]],
                   list[tuple[Any, set[str]]]] | None:
    grouped: dict[tuple[tuple[str, ...], tuple[tuple[str, ...], ...]], list[Any]] = {}
    expected_names = set(qualifier_names)
    for fact in facts:
        values = {tuple(str(name).casefold().split()): str(value)
                  for name, value in fact.qualifiers}
        if set(values) != expected_names:
            continue
        entity = _tokens(_bound(fact, answer_field))
        value_key = tuple(_tokens(values[name]) for name in qualifier_names)
        if entity and all(value_key) and _source_documents(fact):
            grouped.setdefault((entity, value_key), []).append(fact)

    def choose(candidates: list[tuple[tuple[str, ...],
                                      tuple[tuple[str, ...], ...]]],
               count: int, used_entities: set[tuple[str, ...]],
               used_values: list[set[tuple[str, ...]]],
               used_sources: set[str]) -> list[tuple[Any, set[str]]] | None:
        selected = []
        for entity, values in candidates:
            if entity in used_entities or any(
                    values[index] in used_values[index]
                    for index in range(len(values))):
                continue
            rows = grouped[(entity, values)]
            if len({_answer(fact, answer_field).casefold()
                    for fact in rows}) != 1:
                continue
            sources = {source for fact in rows
                       for source in _source_documents(fact)}
            if not sources or sources.intersection(used_sources):
                continue
            selected.append((rows[0], sources))
            used_entities.add(entity)
            for index, value in enumerate(values):
                used_values[index].add(value)
            used_sources.update(sources)
            if len(selected) == count:
                return selected
        return None

    ordered = sorted(grouped)
    train_values = [set() for _ in qualifier_names]
    train = choose(ordered, train_count, set(), train_values, set())
    if train is None:
        return None
    train_entities = {_tokens(_bound(fact, answer_field)) for fact, _ in train}
    for fact, _ in train:
        values = {tuple(str(name).casefold().split()): str(value)
                  for name, value in fact.qualifiers}
        for index, name in enumerate(qualifier_names):
            train_values[index].add(_tokens(values[name]))
    sources = {source for _, row_sources in train for source in row_sources}
    holdout = choose(ordered, holdout_count, train_entities, train_values, sources)
    return None if holdout is None else (train, holdout)


def _realize_multi_question(pattern: tuple[str, ...], entity: str,
                            qualifier_values: tuple[str, ...]) -> str:
    output = []
    for token in pattern:
        if token == "\x00entity":
            output.extend(_tokens(entity))
        elif token.startswith("\x00q"):
            output.extend(_tokens(qualifier_values[int(token[2:])]))
        else:
            output.append(token)
    return " ".join(output)


def propose_analogical_multi_qualified_question_frames(
        kb: CRMSKnowledgeBase, *, minimum_training_examples: int = 2,
        minimum_holdout_examples: int = 2,
        maximum_proposals: int = 100) -> list[dict[str, object]]:
    """Propose relation substitutions for licensed multi-qualifier frames."""
    if (type(minimum_training_examples) is not int
            or not 2 <= minimum_training_examples <= 20
            or type(minimum_holdout_examples) is not int
            or not 1 <= minimum_holdout_examples <= 20
            or type(maximum_proposals) is not int
            or not 1 <= maximum_proposals <= 1000):
        raise ValueError("multi-qualified proposal bounds are outside limits")
    predicates = _target_predicates(kb)
    facts = list(kb.facts())
    proposals = []
    for (base_relation, answer_field, qualifier_names, pattern), base_examples in sorted(
            kb._multi_qualified_question_examples.items()):
        if (len(qualifier_names) < 2 or len(base_examples) < 2
                or len({entity for entity, _values in base_examples}) < 2
                or any(len({values[index] for _entity, values in base_examples}) < 2
                       for index in range(len(qualifier_names)))):
            continue
        if _replace_once(pattern, base_relation, ("<relation>",)) is None:
            continue

        base_support = []
        for (entity, values), answers in sorted(base_examples.items()):
            matches = [fact for fact in facts
                       if tuple(fact.relation.casefold().split()) == base_relation
                       and _tokens(_bound(fact, answer_field)) == entity
                       and tuple(_tokens(_qualifier_value(fact, name))
                                 for name in qualifier_names) == values
                       and _answer(fact, answer_field).casefold()
                           in {answer.casefold() for answer in answers}]
            sources = sorted({source for fact in matches for source in fact.sources})
            if not sources:
                base_support = []
                break
            base_support.append({"bound_entity": list(entity),
                                 "qualifier_values": [list(value) for value in values],
                                 "sources": sources})
        if not base_support:
            continue

        for target_relation, predicate_rows in sorted(predicates.items()):
            if target_relation == base_relation:
                continue
            replaced = _replace_once(pattern, base_relation, target_relation)
            if replaced is None:
                continue
            candidate_pattern, _ = replaced
            target_facts = [fact for fact in facts
                            if tuple(fact.relation.casefold().split()) == target_relation]
            split = _multi_qualified_split(
                target_facts, answer_field, qualifier_names,
                train_count=minimum_training_examples,
                holdout_count=minimum_holdout_examples)
            if split is None:
                continue
            training, holdout = split
            training_sources = {source for _fact, sources in training
                                for source in sources}
            training_pairs = {(tuple(fact.subject.casefold().split()),
                               tuple(fact.object.casefold().split()))
                              for fact, _sources in training}
            training_predicates = []
            for predicate_row in predicate_rows:
                support = []
                for row in predicate_row["support"]:
                    if (tuple(row["subject"]), tuple(row["object"])) not in training_pairs:
                        continue
                    source_rows = [source for source in row["sources"]
                                   if source.split("#", 1)[0] in training_sources]
                    if source_rows:
                        support.append({**row, "sources": source_rows})
                subjects = {tuple(row["subject"]) for row in support}
                objects = {tuple(row["object"]) for row in support}
                documents = {source.split("#", 1)[0]
                             for row in support for source in row["sources"]}
                if (len(support) >= minimum_training_examples
                        and len(subjects) >= minimum_training_examples
                        and len(objects) >= minimum_training_examples
                        and len(documents) >= minimum_training_examples):
                    training_predicates.append({**predicate_row, "support": support})
            if not training_predicates:
                continue

            candidate_kb = deepcopy(kb)
            training_examples = []
            try:
                for fact, sources in training:
                    values_by_name = {
                        tuple(str(name).casefold().split()): str(value)
                        for name, value in fact.qualifiers}
                    values = tuple(values_by_name[name] for name in qualifier_names)
                    question = _realize_multi_question(
                        candidate_pattern, _bound(fact, answer_field), values)
                    candidate_kb.teach_qualified_question(
                        question, relation=" ".join(target_relation),
                        answer_field=answer_field,
                        bound_entity=_bound(fact, answer_field),
                        answer=_answer(fact, answer_field),
                        qualifier={" ".join(name): value
                                   for name, value in zip(qualifier_names, values)})
                    training_examples.append({
                        "question": question,
                        "bound_entity": _bound(fact, answer_field),
                        "qualifier_values": list(values),
                        "answer": _answer(fact, answer_field),
                        "sources": sorted(sources),
                    })
            except ValueError:
                continue

            validation = []
            valid = True
            for fact, _sources in holdout:
                values_by_name = {tuple(str(name).casefold().split()): str(value)
                                  for name, value in fact.qualifiers}
                values = tuple(values_by_name[name] for name in qualifier_names)
                entity = _bound(fact, answer_field)
                question = _realize_multi_question(candidate_pattern, entity, values)
                actual = candidate_kb.ask(question)
                matches = [other for other in target_facts
                           if _tokens(_bound(other, answer_field)) == _tokens(entity)
                           and tuple(_tokens(_qualifier_value(other, name))
                                     for name in qualifier_names)
                               == tuple(_tokens(value) for value in values)]
                expected_answers = sorted({_answer(other, answer_field)
                                           for other in matches}, key=str.casefold)
                expected_status = "answered" if len(expected_answers) == 1 else "ambiguous"
                actual_answers = ([actual.answer] if actual.status == "answered" else
                                  sorted(actual.candidates or [], key=str.casefold)
                                  if actual.status == "ambiguous" else [])
                expected_sources = sorted({source for other in matches
                                           for source in other.sources})
                actual_sources = sorted({source for item in actual.evidence
                                         for source in item.get("sources", [])})
                passed = (actual.status == expected_status
                          and actual_answers == expected_answers
                          and actual_sources == expected_sources
                          and bool(actual.matched_templates))
                validation.append({
                    "question": question,
                    "bound_entity": entity,
                    "qualifier_values": list(values),
                    "expected_status": expected_status,
                    "expected_answers": expected_answers,
                    "actual_status": actual.status,
                    "actual_answers": actual_answers,
                    "expected_sources": expected_sources,
                    "actual_sources": actual_sources,
                    "passed": passed,
                })
                valid = valid and passed
            if not valid:
                continue
            training_documents = {source.split("#", 1)[0]
                                  for row in training_examples for source in row["sources"]}
            holdout_documents = {source.split("#", 1)[0]
                                for row in validation for source in row["expected_sources"]}
            if training_documents.intersection(holdout_documents):
                continue
            lineage = {
                "base_relation": " ".join(base_relation),
                "base_frame": list(pattern),
                "base_frame_examples": base_support,
                "qualifier_names": [" ".join(name) for name in qualifier_names],
                "target_predicate_evidence": training_predicates,
                "training_examples": training_examples,
                "holdout_results": validation,
                "training_source_documents": sorted(training_documents),
                "holdout_source_documents": sorted(holdout_documents),
                "source_separation": True,
            }
            artifact_id = "multi-question-frame-proposal-v1-" + hashlib.sha256(
                json.dumps(lineage, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode()).hexdigest()[:24]
            proposals.append({
                "kind": "analogical_multi_qualified_question_frame",
                "artifact_id": artifact_id,
                "base_relation": " ".join(base_relation),
                "target_relation": " ".join(target_relation),
                "answer_field": answer_field,
                "qualifier_names": [" ".join(name) for name in qualifier_names],
                "pattern": list(candidate_pattern),
                "training_entities": len(training),
                "heldout_entities": len(holdout),
                "validation_passed": True,
                "lineage": lineage,
                "report_only": True,
            })
            if len(proposals) >= maximum_proposals:
                return proposals
    return proposals


def question_frame_proposal_sources_current(
        kb: CRMSKnowledgeBase, proposal: dict[str, object]) -> bool:
    """Check that every fact and predicate citation behind a proposal remains.

    This is the inexpensive runtime validity check. The proposal's full held-out
    evaluation is recomputed when it is accepted; after acceptance, any removal
    of a cited base, target, predicate, training, or holdout source disables the
    frame until a fresh proposal passes again.
    """
    try:
        if proposal.get("kind") == "active_question_role_alternation":
            from crms_question_role_induction import (
                role_alternation_proposal_sources_current)
            return role_alternation_proposal_sources_current(kb, proposal)
        if proposal.get("kind") == "analogical_multi_qualified_question_frame":
            return multi_qualified_question_frame_proposal_sources_current(kb, proposal)
        if proposal.get("kind") == "analogical_qualified_question_frame":
            return qualified_question_frame_proposal_sources_current(kb, proposal)
        if (proposal.get("kind") != "analogical_question_frame"
                or proposal.get("validation_passed") is not True
                or proposal.get("report_only") is not True):
            return False
        lineage = proposal["lineage"]
        base_relation = tuple(str(proposal["base_relation"]).split())
        target_relation = tuple(str(proposal["target_relation"]).split())
        answer_field = str(proposal["answer_field"])
        facts = list(kb._facts.values())

        base_frame = tuple(lineage["base_frame"])
        marker_index = base_frame.index("<bound_entity>")
        base_key = (json.dumps(list(base_relation), ensure_ascii=False),
                    answer_field, base_frame[:marker_index],
                    base_frame[marker_index + 1:])
        base_examples = kb._question_examples.get(base_key)
        if (base_examples is None or not kb._question_frame_is_licensed(
                base_key, base_examples)):
            return False
        if set(base_examples) != {tuple(row["bound_entity"])
                                  for row in lineage["base_frame_examples"]}:
            return False

        def related(bound: str, relation: tuple[str, ...], answer: str | None = None
                    ) -> list[Any]:
            result = []
            for fact in facts:
                if tuple(fact.relation.casefold().split()) != relation:
                    continue
                if _bound(fact, answer_field).casefold() != bound.casefold():
                    continue
                if answer is not None and _answer(fact, answer_field).casefold() != answer.casefold():
                    continue
                result.append(fact)
            return result

        for row in lineage["base_frame_examples"]:
            entity = " ".join(row["bound_entity"])
            sources = set(row["sources"])
            current_sources = {source for fact in related(entity, base_relation)
                               for source in fact.sources}
            if not sources or sources != current_sources:
                return False

        for predicate in lineage["target_predicate_evidence"]:
            relation = tuple(predicate["relation"])
            phrase = tuple(predicate["predicate_phrase"])
            found: dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]] = {}
            for key, forms in kb._fact_pattern_predicate_sources.items():
                if key[1] == relation and tuple(key[0]) == (
                        "<subject>", "<predicate>", "<object>"):
                    found.update(forms.get(phrase, {}))
            for support in predicate["support"]:
                pair = (tuple(support["subject"]), tuple(support["object"]))
                if not set(support["sources"]).issubset(found.get(pair, set())):
                    return False

        for row in lineage["training_examples"]:
            current_sources = {source for fact in related(
                row["bound_entity"], target_relation, row["answer"])
                for source in fact.sources}
            if set(row["sources"]) != current_sources:
                return False

        for row in lineage["holdout_results"]:
            bound = row["bound_entity"]
            matching = related(bound, target_relation)
            answers = sorted({_answer(fact, answer_field) for fact in matching},
                             key=str.casefold)
            sources = sorted({source for fact in matching for source in fact.sources})
            if (answers != row["expected_answers"]
                    or sources != row["expected_sources"]):
                return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def qualified_question_frame_proposal_sources_current(
        kb: CRMSKnowledgeBase, proposal: dict[str, object]) -> bool:
    """Recheck exact source lineage for a one-qualifier frame proposal."""
    try:
        if (proposal.get("kind") != "analogical_qualified_question_frame"
                or proposal.get("validation_passed") is not True
                or proposal.get("report_only") is not True):
            return False
        lineage = proposal["lineage"]
        base_relation = tuple(str(proposal["base_relation"]).split())
        target_relation = tuple(str(proposal["target_relation"]).split())
        answer_field = str(proposal["answer_field"])
        qualifier_name = tuple(str(proposal["qualifier_name"]).split())
        base_words = tuple(lineage["base_frame"])
        entity_index = base_words.index("<bound_entity>")
        value_index = base_words.index("<qualifier_value>")
        base_entity_first = entity_index < value_index
        if base_entity_first:
            base_prefix = base_words[:entity_index]
            base_middle = base_words[entity_index + 1:value_index]
            base_suffix = base_words[value_index + 1:]
        else:
            base_prefix = base_words[:value_index]
            base_middle = base_words[value_index + 1:entity_index]
            base_suffix = base_words[entity_index + 1:]
        base_key = (base_relation, answer_field, qualifier_name,
                    base_entity_first, base_prefix, base_middle, base_suffix)
        base_examples = kb._qualified_question_examples.get(base_key)
        if base_examples is None:
            return False
        expected_pairs = {(tuple(row["bound_entity"]),
                           tuple(row["qualifier_value"]))
                          for row in lineage["base_frame_examples"]}
        if set(base_examples) != expected_pairs:
            return False

        facts = list(kb._facts.values())

        def matching(relation: tuple[str, ...], bound: str,
                     qualifier_value: str,
                     answer: str | None = None) -> list[Any]:
            result = []
            for fact in facts:
                if tuple(fact.relation.casefold().split()) != relation:
                    continue
                qualifiers = {tuple(str(name).casefold().split()): str(value)
                              for name, value in fact.qualifiers}
                if (len(qualifiers) != 1
                        or qualifier_name not in qualifiers
                        or " ".join(_tokens(qualifiers[qualifier_name]))
                            != " ".join(_tokens(qualifier_value))
                        or _bound(fact, answer_field).casefold() != bound.casefold()
                        or (answer is not None and
                            _answer(fact, answer_field).casefold()
                                != answer.casefold())):
                    continue
                result.append(fact)
            return result

        for row in lineage["base_frame_examples"]:
            entity = " ".join(row["bound_entity"])
            value = " ".join(row["qualifier_value"])
            sources = {source for fact in matching(base_relation, entity, value)
                       for source in fact.sources}
            if not sources or sources != set(row["sources"]):
                return False

        for predicate in lineage["target_predicate_evidence"]:
            relation = tuple(predicate["relation"])
            phrase = tuple(predicate["predicate_phrase"])
            found: dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]] = {}
            for key, forms in kb._fact_pattern_predicate_sources.items():
                if key[1] == relation and tuple(key[0]) == (
                        "<subject>", "<predicate>", "<object>"):
                    found.update(forms.get(phrase, {}))
            for support in predicate["support"]:
                pair = (tuple(support["subject"]), tuple(support["object"]))
                if not set(support["sources"]).issubset(found.get(pair, set())):
                    return False

        for row in lineage["training_examples"]:
            sources = {source for fact in matching(
                target_relation, row["bound_entity"], row["qualifier_value"],
                row["answer"]) for source in fact.sources}
            if sources != set(row["sources"]):
                return False
        for row in lineage["holdout_results"]:
            facts_for_scope = matching(target_relation, row["bound_entity"],
                                       row["qualifier_value"])
            answers = sorted({_answer(fact, answer_field)
                              for fact in facts_for_scope}, key=str.casefold)
            sources = sorted({source for fact in facts_for_scope
                              for source in fact.sources})
            if (answers != row["expected_answers"]
                    or sources != row["expected_sources"]):
                return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def multi_qualified_question_frame_proposal_sources_current(
        kb: CRMSKnowledgeBase, proposal: dict[str, object]) -> bool:
    """Recheck all direct fact and predicate lineage for a multi-context frame."""
    try:
        if (proposal.get("kind") != "analogical_multi_qualified_question_frame"
                or proposal.get("validation_passed") is not True
                or proposal.get("report_only") is not True):
            return False
        lineage = proposal["lineage"]
        base_relation = tuple(str(proposal["base_relation"]).split())
        target_relation = tuple(str(proposal["target_relation"]).split())
        answer_field = str(proposal["answer_field"])
        qualifier_names = tuple(tuple(str(name).split())
                                for name in proposal["qualifier_names"])
        base_pattern = tuple(lineage["base_frame"])
        base_key = (base_relation, answer_field, qualifier_names, base_pattern)
        base_examples = kb._multi_qualified_question_examples.get(base_key)
        if base_examples is None:
            return False
        expected_pairs = {
            (tuple(row["bound_entity"]),
             tuple(tuple(value) for value in row["qualifier_values"]))
            for row in lineage["base_frame_examples"]}
        if set(base_examples) != expected_pairs:
            return False
        facts = list(kb._facts.values())

        def matching(relation: tuple[str, ...], bound: str,
                     values: list[str] | tuple[str, ...],
                     answer: str | None = None) -> list[Any]:
            result = []
            for fact in facts:
                if tuple(fact.relation.casefold().split()) != relation:
                    continue
                value_map = {tuple(str(name).casefold().split()): str(value)
                             for name, value in fact.qualifiers}
                if (set(value_map) != set(qualifier_names)
                        or _tokens(_bound(fact, answer_field)) != _tokens(bound)
                        or tuple(_tokens(value_map[name]) for name in qualifier_names)
                            != tuple(_tokens(value) for value in values)
                        or (answer is not None and
                            _answer(fact, answer_field).casefold() != answer.casefold())):
                    continue
                result.append(fact)
            return result

        for row in lineage["base_frame_examples"]:
            sources = {source for fact in matching(
                base_relation, " ".join(row["bound_entity"]),
                [" ".join(value) for value in row["qualifier_values"]])
                for source in fact.sources}
            if not sources or sources != set(row["sources"]):
                return False
        for predicate in lineage["target_predicate_evidence"]:
            relation = tuple(predicate["relation"])
            phrase = tuple(predicate["predicate_phrase"])
            found: dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]] = {}
            for key, forms in kb._fact_pattern_predicate_sources.items():
                if key[1] == relation and tuple(key[0]) == (
                        "<subject>", "<predicate>", "<object>"):
                    found.update(forms.get(phrase, {}))
            for support in predicate["support"]:
                pair = (tuple(support["subject"]), tuple(support["object"]))
                if not set(support["sources"]).issubset(found.get(pair, set())):
                    return False
        for row in lineage["training_examples"]:
            sources = {source for fact in matching(
                target_relation, row["bound_entity"],
                row["qualifier_values"], row["answer"])
                for source in fact.sources}
            if sources != set(row["sources"]):
                return False
        for row in lineage["holdout_results"]:
            scoped = matching(target_relation, row["bound_entity"],
                              row["qualifier_values"])
            answers = sorted({_answer(fact, answer_field) for fact in scoped},
                             key=str.casefold)
            sources = sorted({source for fact in scoped for source in fact.sources})
            if answers != row["expected_answers"] or sources != row["expected_sources"]:
                return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False

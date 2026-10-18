"""Induce and validate a narrow active-voice question alternation.

The learner looks for source-backed frame pairs of the form
``Who PAST OBJECT?`` / ``What did SUBJECT BASE?``. It requires two paired
relations to learn the ``BASE + ed -> PAST`` spelling rule, a third paired
relation as held-out validation, and a source-separated target relation with
only its subject-answer frame taught. Proposals do not mutate the knowledge
base or activate the generated frame until an exact proposal is accepted.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from itertools import combinations
import json
from typing import Any

from crms_knowledge import CRMSKnowledgeBase


def _relation_key(relation: tuple[str, ...]) -> str:
    return json.dumps(list(relation), ensure_ascii=False)


def _fact_record(fact: Any) -> dict[str, Any]:
    return {
        "subject": fact.subject, "relation": fact.relation,
        "object": fact.object, "qualifiers": [list(pair)
                                                  for pair in fact.qualifiers],
        "sources": list(fact.sources),
    }


def _frame_rows(relation_facts: list[Any], relation: tuple[str, ...],
                answer_field: str,
                examples: dict[tuple[str, ...], Any]
                ) -> list[dict[str, Any]]:
    """Return source support for each distinct bound entity in a frame."""
    rows = []
    for bound in sorted(examples):
        matching = [fact for fact in relation_facts
                    if tuple(fact.relation.casefold().split()) == relation
                    and not fact.qualifiers
                    and ((fact.object if answer_field == "subject"
                          else fact.subject).casefold()
                         == " ".join(bound).casefold())]
        sources = sorted({source for fact in matching for source in fact.sources})
        if not sources:
            return []
        rows.append({"bound_entity": list(bound), "sources": sources,
                     "facts": [_fact_record(fact) for fact in matching]})
    return rows


def _licensed_role_frames(kb: CRMSKnowledgeBase,
                          facts_by_relation: dict[tuple[str, ...], list[Any]]
                          ) -> tuple[dict[tuple[str, ...], dict[str, Any]],
                                     dict[tuple[str, ...], dict[str, Any]]]:
    """Index the exact simple active-voice subject/object frame shapes."""
    subject_frames: dict[tuple[str, ...], dict[str, Any]] = {}
    object_frames: dict[tuple[str, ...], dict[str, Any]] = {}
    for key, examples in kb._question_examples.items():
        relation = tuple(json.loads(key[0]))
        answer_field, prefix, suffix = key[1], tuple(key[2]), tuple(key[3])
        if len(relation) != 1 or not kb._question_frame_is_licensed(key, examples):
            continue
        if (answer_field == "subject" and prefix == ("who",) + relation
                and not suffix):
            rows = _frame_rows(facts_by_relation.get(relation, []), relation,
                               answer_field, examples)
            if len(rows) >= 2:
                subject_frames[relation] = {
                    "key": key, "examples": examples, "rows": rows,
                    "prefix": list(prefix), "suffix": list(suffix),
                }
        elif (answer_field == "object" and prefix == ("what", "did")
              and len(suffix) == 1 and relation == (suffix[0] + "ed",)):
            rows = _frame_rows(facts_by_relation.get(relation, []), relation,
                               answer_field, examples)
            if len(rows) >= 2:
                object_frames[relation] = {
                    "key": key, "examples": examples, "rows": rows,
                    "prefix": list(prefix), "suffix": list(suffix),
                    "base": suffix[0],
                }
    return subject_frames, object_frames


def _relation_sources(relation_facts: list[Any],
                      relation: tuple[str, ...]) -> list[str]:
    return sorted({source for fact in relation_facts
                   if tuple(fact.relation.casefold().split()) == relation
                   and not fact.qualifiers
                   for source in fact.sources})


def role_alternation_proposal_sources_current(
        kb: CRMSKnowledgeBase, proposal: dict[str, Any]) -> bool:
    """Cheaply recheck a retained alternation's cited rows and frame gates."""
    try:
        if (proposal.get("kind") != "active_question_role_alternation"
                or proposal.get("validation_passed") is not True
                or proposal.get("report_only") is not True):
            return False
        lineage = proposal["lineage"]

        def fact_is_current(record: dict[str, Any]) -> bool:
            qualifiers = tuple((str(name), str(value))
                               for name, value in record.get("qualifiers", []))
            key = kb._fact_key(record["subject"], record["relation"],
                               record["object"], qualifiers)
            current = kb._facts.get(key)
            return (current is not None
                    and set(record["sources"]).issubset(current.sources))

        def frame_is_current(relation: str, answer_field: str,
                             prefix: list[str], suffix: list[str],
                             rows: list[dict[str, Any]]) -> bool:
            key = (_relation_key(tuple(relation.split())), answer_field,
                   tuple(prefix), tuple(suffix))
            examples = kb._question_examples.get(key)
            if examples is None or not kb._question_frame_is_licensed(key, examples):
                return False
            if set(examples) != {tuple(row["bound_entity"]) for row in rows}:
                return False
            for row in rows:
                if (not row.get("facts")
                        or not all(fact_is_current(item) for item in row["facts"])):
                    return False
                current_sources = {source for item in row["facts"]
                                   for source in item["sources"]}
                if not set(row["sources"]).issubset(current_sources):
                    return False
            return True

        training_documents: set[str] = set()
        for row in lineage["training_relations"]:
            relation = tuple(str(row["relation"]).split())
            base = str(row["base"])
            if relation != (base + "ed",):
                return False
            if not frame_is_current(
                    " ".join(relation), "subject", ["who", *relation], [],
                    row["subject_frame_examples"]):
                return False
            if not frame_is_current(
                    " ".join(relation), "object", ["what", "did"], [base],
                    row["object_frame_examples"]):
                return False
            training_documents.update(source.split("#", 1)[0]
                                      for source in row["sources"])

        heldout = lineage["heldout_relation"]
        heldout_relation = tuple(str(heldout["relation"]).split())
        heldout_base = str(heldout["base"])
        if (heldout_relation != (heldout_base + "ed",)
                or not frame_is_current(
                    " ".join(heldout_relation), "subject",
                    ["who", *heldout_relation], [],
                    heldout["subject_frame_examples"])
                or not frame_is_current(
                    " ".join(heldout_relation), "object", ["what", "did"],
                    [heldout_base], heldout["object_frame_examples"])):
            return False
        heldout_documents = {source.split("#", 1)[0]
                             for source in heldout["sources"]}

        target_relation = str(proposal["target_relation"])
        target_tokens = tuple(target_relation.split())
        if (len(target_tokens) != 1 or not target_tokens[0].endswith("ed")
                or target_tokens[0][:-2] != proposal["suffix"][0]):
            return False
        if not frame_is_current(
                target_relation, "subject", ["who", *target_tokens], [],
                lineage["target_subject_frame_examples"]):
            return False
        target_object_key = (_relation_key(target_tokens), "object",
                             tuple(proposal["prefix"]),
                             tuple(proposal["suffix"]))
        if target_object_key in kb._question_examples:
            return False
        target_documents = set()
        for record in lineage["target_relation_facts"]:
            if not fact_is_current(record):
                return False
            target_documents.update(source.split("#", 1)[0]
                                    for source in record["sources"])
        for row in lineage["target_examples"]:
            if not fact_is_current(row["fact"]):
                return False
            if not set(row["sources"]).issubset(row["fact"]["sources"]):
                return False
        if (sorted(training_documents) != lineage["training_source_documents"]
                or sorted(heldout_documents) != lineage["holdout_source_documents"]
                or sorted(target_documents) != lineage["target_source_documents"]
                or training_documents.intersection(heldout_documents)
                or training_documents.intersection(target_documents)
                or heldout_documents.intersection(target_documents)):
            return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def propose_active_role_alternation_frames(
        kb: CRMSKnowledgeBase, *, minimum_training_relations: int = 2,
        maximum_proposals: int = 100) -> list[dict[str, Any]]:
    """Propose the object-answer frame from paired, source-backed examples.

    This first grammar proposal is deliberately narrow: it recognizes only
    one-token regular past relations ending in ``ed`` and the exact English
    active-voice question pair ``Who PAST object?`` / ``What did subject BASE?``.
    Two relations train the spelling rule, one independent relation holds it
    out, and a fourth relation supplies a subject-answer frame with no object
    counterpart. Target examples are checked on a temporary KB copy.
    """
    if (type(minimum_training_relations) is not int
            or not 2 <= minimum_training_relations <= 10
            or type(maximum_proposals) is not int
            or not 1 <= maximum_proposals <= 1000):
        raise ValueError("role-alternation proposal bounds are outside supported limits")

    facts_by_relation: dict[tuple[str, ...], list[Any]] = {}
    for fact in kb.facts():
        facts_by_relation.setdefault(
            tuple(fact.relation.casefold().split()), []).append(fact)
    subject_frames, object_frames = _licensed_role_frames(kb, facts_by_relation)
    paired = []
    for relation, subject_frame in sorted(subject_frames.items()):
        object_frame = object_frames.get(relation)
        if object_frame is None:
            continue
        base = object_frame["base"]
        if relation != (base + "ed",):
            continue
        sources = _relation_sources(facts_by_relation.get(relation, []), relation)
        if not sources:
            continue
        paired.append({
            "relation": list(relation), "base": base,
            "subject_frame": subject_frame,
            "object_frame": object_frame,
            "sources": sources,
            "source_documents": sorted({source.split("#", 1)[0]
                                         for source in sources}),
        })
    if len(paired) < minimum_training_relations + 1:
        return []

    proposals = []
    for target_relation, target_frame in sorted(subject_frames.items()):
        if target_relation in object_frames or len(target_relation) != 1:
            continue
        past = target_relation[0]
        if not past.endswith("ed") or len(past) <= 2:
            continue
        base = past[:-2]
        target_facts = [fact for fact in facts_by_relation.get(target_relation, [])
                        if not fact.qualifiers]
        target_sources = _relation_sources(target_facts, target_relation)
        target_documents = {source.split("#", 1)[0]
                            for source in target_sources}
        if not target_documents:
            continue

        training_selected = None
        holdout_selected = None
        for training_indices in combinations(
                range(len(paired)), minimum_training_relations):
            training = [paired[index] for index in training_indices]
            if any(item["relation"] == list(target_relation)
                   for item in training):
                continue
            if any(item["base"] + "ed" != " ".join(item["relation"])
                   for item in training):
                continue
            training_documents = {source for item in training
                                  for source in item["source_documents"]}
            if training_documents.intersection(target_documents):
                continue
            for holdout in paired:
                if holdout in training or holdout["relation"] == list(target_relation):
                    continue
                holdout_documents = set(holdout["source_documents"])
                if (holdout["base"] + "ed" != " ".join(holdout["relation"])
                        or training_documents.intersection(holdout_documents)
                        or target_documents.intersection(holdout_documents)):
                    continue
                training_selected = training
                holdout_selected = holdout
                break
            if holdout_selected is not None:
                break
        if training_selected is None or holdout_selected is None:
            continue

        facts_by_subject: dict[str, list[Any]] = {}
        for fact in target_facts:
            facts_by_subject.setdefault(fact.subject, []).append(fact)
        target_rows = []
        valid_target = True
        for subject, facts in sorted(facts_by_subject.items()):
            objects = {fact.object for fact in facts}
            if len(objects) != 1:
                valid_target = False
                break
            sources = sorted({source for fact in facts for source in fact.sources})
            if not sources:
                valid_target = False
                break
            obj = next(iter(objects))
            question = f"What did {subject} {base}?"
            target_rows.append({
                "question": question, "bound_entity": subject,
                "answer": obj, "sources": sources,
                "fact": _fact_record(facts[0]),
            })
        if not valid_target or len(target_rows) < 2:
            continue

        # The exact generated frame is exercised on a copy. This checks answer
        # completeness and citation attribution without modifying the live KB.
        candidate_kb = deepcopy(kb)
        candidate_kb._induced_question_frames.clear()
        frame_examples = []
        try:
            for row in target_rows:
                candidate_kb.teach_question(
                    row["question"], relation=" ".join(target_relation),
                    answer_field="object", bound_entity=row["bound_entity"],
                    answer=row["answer"])
                frame_examples.append(row)
        except ValueError:
            continue
        validation = []
        valid = True
        for row in target_rows:
            actual = candidate_kb.ask(row["question"])
            actual_sources = sorted({source for item in actual.evidence
                                     for source in item.get("sources", [])})
            expected_sources = row["sources"]
            passed = (actual.status == "answered"
                      and actual.answer == row["answer"]
                      and actual_sources == expected_sources
                      and bool(actual.matched_templates))
            validation.append({
                "question": row["question"],
                "expected_answer": row["answer"],
                "actual_status": actual.status,
                "actual_answer": actual.answer,
                "expected_sources": expected_sources,
                "actual_sources": actual_sources,
                "passed": passed,
            })
            valid = valid and passed
        if not valid:
            continue

        training_documents = sorted({source for item in training_selected
                                     for source in item["source_documents"]})
        holdout_documents = sorted(holdout_selected["source_documents"])
        all_documents = (training_documents + holdout_documents
                         + sorted(target_documents))
        source_separation = len(all_documents) == len(set(all_documents))
        if not source_separation:
            continue
        training_rows = [{
            "relation": " ".join(item["relation"]), "base": item["base"],
            "subject_frame_examples": item["subject_frame"]["rows"],
            "object_frame_examples": item["object_frame"]["rows"],
            "sources": item["sources"],
        } for item in training_selected]
        holdout_row = {
            "relation": " ".join(holdout_selected["relation"]),
            "base": holdout_selected["base"],
            "subject_frame_examples": holdout_selected["subject_frame"]["rows"],
            "object_frame_examples": holdout_selected["object_frame"]["rows"],
            "sources": holdout_selected["sources"],
        }
        lineage = {
            "training_relations": training_rows,
            "heldout_relation": holdout_row,
            "target_subject_frame_examples": target_frame["rows"],
            "target_relation_facts": [
                _fact_record(fact) for fact in target_facts],
            "target_examples": frame_examples,
            "training_examples": frame_examples,
            "target_validation": validation,
            "training_source_documents": training_documents,
            "holdout_source_documents": holdout_documents,
            "target_source_documents": sorted(target_documents),
            "source_separation": source_separation,
        }
        artifact_id = "question-role-alternation-v1-" + hashlib.sha256(
            json.dumps(lineage, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode()).hexdigest()[:24]
        proposals.append({
            "kind": "active_question_role_alternation",
            "artifact_id": artifact_id,
            "base_relation": "who <past-verb> object → what did subject <base-verb>",
            "target_relation": " ".join(target_relation),
            "answer_field": "object",
            "prefix": ["what", "did"], "suffix": [base],
            "training_relations": len(training_selected),
            "heldout_relations": 1,
            "target_entities": len(target_rows),
            "training_entities": len(target_rows),
            "heldout_entities": 1,
            "validation_passed": True,
            "lineage": lineage,
            "report_only": True,
        })
        if len(proposals) >= maximum_proposals:
            break
    return proposals

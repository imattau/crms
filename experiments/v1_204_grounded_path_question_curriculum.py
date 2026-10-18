"""Generate path questions from learned frames and independently join facts.

This read-only diagnostic checks path-frame execution against a small
independent relational join. Generated questions are never taught or stored.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def fact_paths(facts: list[object], start: str,
               relations: tuple[tuple[str, ...], ...]) -> list[tuple[object, ...]]:
    """Enumerate exact forward paths without calling the CRMS path API."""
    paths: list[tuple[object, ...]] = []

    def extend(entity: str, depth: int, path: tuple[object, ...]) -> None:
        if depth == len(relations):
            paths.append(path)
            return
        for fact in facts:
            if (fact.subject.casefold() == entity.casefold()
                    and tuple(fact.relation.casefold().split()) == relations[depth]
                    and not fact.qualifiers):
                extend(fact.object, depth + 1, path + (fact,))

    extend(start, 0, ())
    return paths


def main() -> None:
    kb = CRMSKnowledgeBase()
    rows = [
        ("Ada", "born in", "London", "birth-ada"),
        ("London", "located in", "United Kingdom", "geo-london"),
        ("Albert", "born in", "Ulm", "birth-albert"),
        ("Ulm", "located in", "Germany", "geo-ulm"),
        ("Alan", "born in", "London", "birth-alan"),
        ("Casey", "born in", "Springfield", "birth-casey"),
        ("Springfield", "located in", "Illinois", "geo-springfield-il"),
        ("Springfield", "located in", "Missouri", "geo-springfield-mo"),
        ("Zoe", "studied", "Logic", "study-zoe"),
    ]
    for subject, relation, obj, source in rows:
        kb.add_fact(subject, relation, obj, source)

    relation_path = ("born in", "located in")
    examples = [
        ("Which country is Ada born in?", "Ada", "United Kingdom"),
        ("Which country is Albert born in?", "Albert", "Germany"),
    ]
    for question, entity, answer in examples:
        kb.teach_path_question(question, relations=relation_path,
                               bound_entity=entity, answer=answer)

    if len(kb._path_question_examples) != 1:
        raise SystemExit("expected one learned path-question frame")
    (path, prefix, suffix), entities = next(iter(kb._path_question_examples.items()))
    key = (path, prefix, suffix)
    if not kb._path_question_frame_is_licensed(key, entities):
        raise SystemExit("two distinct grounded entities did not license frame")

    before_facts = [(fact.subject, fact.relation, fact.object, fact.sources,
                     fact.qualifiers) for fact in kb.facts()]
    before_frames = {frame: set(values)
                     for frame, values in kb._path_question_examples.items()}
    facts = list(kb.facts())
    starts = sorted({fact.subject for fact in facts
                     if tuple(fact.relation.casefold().split()) == path[0]},
                    key=str.casefold)
    checked = 0
    for start in starts:
        paths = fact_paths(facts, start, path)
        expected_answers = sorted({candidate[-1].object for candidate in paths},
                                  key=str.casefold)
        question = " ".join(prefix + tuple(start.casefold().split()) + suffix)
        result = kb.ask(question)
        if not expected_answers:
            if result.status != "unknown":
                raise SystemExit(f"path with no join should be unknown: {question}: {result}")
            continue
        expected_status = "answered" if len(expected_answers) == 1 else "ambiguous"
        actual_answers = ([result.answer] if result.status == "answered" else
                          sorted(result.candidates or [], key=str.casefold))
        if result.status != expected_status or actual_answers != expected_answers:
            raise SystemExit(f"path join mismatch for {question!r}: expected "
                             f"{expected_status} {expected_answers}, got {result}")

        expected_signatures = {
            tuple((fact.subject.casefold(), fact.relation.casefold(),
                   fact.object.casefold()) for fact in proof)
            for proof in paths
        }
        actual_signatures = {
            tuple((step["subject"].casefold(), step["relation"].casefold(),
                   step["object"].casefold()) for step in proof)
            for proof in (result.proofs or [])
        }
        if actual_signatures != expected_signatures:
            raise SystemExit(f"path proof mismatch for {question!r}: "
                             f"{actual_signatures} != {expected_signatures}")
        expected_sources = {source for proof in paths for fact in proof
                            for source in fact.sources}
        actual_sources = {source for proof in (result.proofs or [])
                          for step in proof for source in step.get("sources", [])}
        if actual_sources != expected_sources:
            raise SystemExit(f"path source mismatch for {question!r}: "
                             f"{actual_sources} != {expected_sources}")
        checked += 1

    unknown = kb.ask("Which country is Zoe born in?")
    if unknown.status != "unknown" or not unknown.matched_templates:
        raise SystemExit(f"learned frame failed to abstain on missing path: {unknown}")
    after_facts = [(fact.subject, fact.relation, fact.object, fact.sources,
                    fact.qualifiers) for fact in kb.facts()]
    after_frames = {frame: set(values)
                    for frame, values in kb._path_question_examples.items()}
    if after_facts != before_facts or after_frames != before_frames:
        raise SystemExit("generated path questions mutated facts or learned frames")

    print(f"grounded path question curriculum: {checked} path-bearing entities; PASS")
    print("independent joins, answer sets, proof chains, provenance, ambiguity, "
          "abstention, and read-only generation: PASS")


if __name__ == "__main__":
    main()

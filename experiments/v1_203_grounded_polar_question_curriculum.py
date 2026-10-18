"""Audit learned yes/no frames using mechanically labeled fact-store cases.

Generated questions are evaluated read-only. Missing evidence remains unknown;
the diagnostic never treats an absent proposition as a negative label.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def instantiate(template: tuple[str, ...], subject: str, obj: str) -> str:
    words: list[str] = []
    for token in template:
        if token == "<subject>":
            words.extend(subject.casefold().split())
        elif token == "<object>":
            words.extend(obj.casefold().split())
        else:
            words.append(token)
    return " ".join(words)


def main() -> None:
    kb = CRMSKnowledgeBase()
    cases = [
        ("Ada", "designed", "Engine", True, "src-a"),
        ("Bea", "designed", "Compiler", True, "src-b"),
        ("Cal", "designed", "Device", False, "src-c"),
        ("Dee", "designed", "Machine", False, "src-d"),
    ]
    questions = [
        "Did Ada design Engine?", "Did Bea design Compiler?",
        "Did Cal design Device?", "Did Dee design Machine?",
    ]
    for (subject, relation, obj, positive, source), question in zip(cases, questions):
        if positive:
            kb.add_fact(subject, relation, obj, source)
        else:
            kb.add_negative_fact(subject, relation, obj, source)
        kb.teach_polar_question(question, subject=subject, relation=relation,
                                obj=obj, answer=positive)

    if len(kb._polar_question_examples) != 1:
        raise SystemExit("expected one learned polar frame")
    (template, relation), examples = next(iter(kb._polar_question_examples.items()))
    key = (template, relation)
    if not kb._polar_frame_is_licensed(key, examples):
        raise SystemExit("varied grounded examples failed to license the frame")

    before = ([(f.subject, f.relation, f.object, f.sources) for f in kb.facts()],
              [(f.subject, f.relation, f.object, f.sources)
               for f in kb.negative_facts()],
              {frame: dict(rows) for frame, rows in kb._polar_question_examples.items()})
    evaluated = 0
    for subject, relation_name, obj, expected, source in cases:
        question = instantiate(template, subject, obj)
        result = kb.ask(question)
        if result.status != "answered" or result.truth is not expected:
            raise SystemExit(f"polar curriculum mismatch for {question!r}: {result}")
        evidence_sources = {name for item in (result.evidence or [])
                            for name in item.get("sources", [])}
        if source not in evidence_sources:
            raise SystemExit(f"missing source attribution for {question!r}: {result}")
        evaluated += 1

    # Unknown and conflict controls are instantiated from the learned frame,
    # but are not added to its labels.
    unknown_question = instantiate(template, "Eli", "Gadget")
    unknown = kb.ask(unknown_question)
    if unknown.status != "unknown":
        raise SystemExit(f"open-world unknown became a truth label: {unknown}")

    kb.add_fact("Cal", "designed", "Device", "src-conflict")
    conflict_question = instantiate(template, "Cal", "Device")
    conflict = kb.ask(conflict_question)
    if conflict.status != "ambiguous":
        raise SystemExit(f"contradictory evidence was not surfaced: {conflict}")
    conflict_sources = {
        name for item in (conflict.evidence or [])
        for name in (*item.get("sources", ()),
                     *item.get("contradictory_sources", ()))
    }
    if not {"src-c", "src-conflict"}.issubset(conflict_sources):
        raise SystemExit(f"conflict omitted one source: {conflict}")

    after = ([(f.subject, f.relation, f.object, f.sources) for f in kb.facts()],
             [(f.subject, f.relation, f.object, f.sources)
              for f in kb.negative_facts()],
             {frame: dict(rows) for frame, rows in kb._polar_question_examples.items()})
    # The one deliberate conflict fact is the only expected state change.
    expected_facts = before[0] + [("Cal", "designed", "Device", ("src-conflict",))]
    if after != (expected_facts, before[1], before[2]):
        raise SystemExit("curriculum evaluation changed facts or learned frames")

    print(f"grounded polar question curriculum: {evaluated} labeled cases; PASS")
    print("positive/negative evidence, citations, unknown, conflict, read-only labels: PASS")


if __name__ == "__main__":
    main()

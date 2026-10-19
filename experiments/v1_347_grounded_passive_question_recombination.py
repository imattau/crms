"""Derive passive who-questions from licensed active question frames.

A pair of source-backed active-frame examples licenses only the mechanical
voice alternation for the same regular -ed predicate. The held-out answer must
still come from its own fact; role swaps, new predicates, and under-supported
frames abstain.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def add_examples(kb: CRMSKnowledgeBase, relation: str, verb: str,
                 prefix: str) -> list[tuple[str, str, str]]:
    examples = [
        ("Ada Venn", f"{prefix} One", f"{relation}:train:one"),
        ("Nia Sol", f"{prefix} Two", f"{relation}:train:two"),
        ("Mira Sen", f"{prefix} Three", f"{relation}:heldout"),
    ]
    for subject, obj, source in examples:
        kb.add_fact(subject, relation, obj, source)
    for subject, obj, _source in examples[:2]:
        kb.teach_question(
            f"Who {verb} {obj}?", relation=relation,
            answer_field="subject", bound_entity=obj, answer=subject)
    return examples


def main() -> None:
    kb = CRMSKnowledgeBase()
    relations = [
        ("created", "created", "Engine"),
        ("designed", "designed", "Compiler"),
    ]
    for relation, verb, entity_prefix in relations:
        examples = add_examples(kb, relation, verb, entity_prefix)
        subject, obj, heldout_source = examples[-1]
        active = kb.ask(f"Who {verb} {obj}?")
        require(active.status == "answered" and active.answer == subject,
                f"active frame stopped answering for {relation}: {active}")
        passive_questions = (f"{obj} was {verb} by whom?",
                             f"Who was {obj} {verb} by?")
        for passive_question in passive_questions:
            passive = kb.ask(passive_question)
            transform = next((item for item in passive.language_evidence or []
                              if item.get("kind")
                              == "active_to_passive_subject_question_frame"), None)
            require(passive.status == "answered" and passive.answer == subject,
                    f"passive question did not recombine for {relation}: {passive}")
            require(any(heldout_source in fact.get("sources", ())
                        for fact in passive.evidence or ()),
                    f"passive answer lost held-out fact evidence: {passive}")
            require(transform is not None and transform["predicate"] == verb
                    and all(heldout_source not in row["sources"]
                            for row in transform["supporting_examples"]),
                    f"passive transformation trace was missing or leaked held-out data: {passive}")
        require(kb.ask(f"{obj} {verb} by whom?").status != "answered",
                f"passive transform accepted a missing auxiliary for {relation}")
        require(kb.ask(f"{obj} was crafted by whom?").status != "answered",
                f"passive transform guessed a predicate for {relation}")
        require(kb.ask(f"{subject} was {verb} by whom?").status != "answered",
                f"passive transform swapped agent and patient for {relation}")

    # One example cannot establish a reusable question frame.
    one = CRMSKnowledgeBase()
    one.add_fact("Ada Venn", "created", "Engine One", "one:source")
    one.add_fact("Mira Sen", "created", "Engine Three", "one:heldout")
    one.teach_question("Who created Engine One?", relation="created",
                       answer_field="subject", bound_entity="Engine One",
                       answer="Ada Venn")
    require(one.ask("Engine Three was created by whom?").status != "answered",
            "one active-frame example licensed passive generalization")

    # Explicit negative evidence retains its normal conflict semantics.
    conflict = CRMSKnowledgeBase()
    examples = add_examples(conflict, "created", "created", "Device")
    subject, obj, _source = examples[-1]
    conflict.add_negative_fact(subject, "created", obj, "review:negative")
    for wording in (f"Who created {obj}?", f"{obj} was created by whom?",
                    f"Who was {obj} created by?"):
        result = conflict.ask(wording)
        require(result.status == "ambiguous"
                and {row.get("polarity") for row in result.evidence or []}
                >= {"positive", "negative"},
                f"{wording} overrode or hid explicit negative evidence: {result}")

    with tempfile.TemporaryDirectory(prefix="crms-passive-question-") as folder:
        for suffix in (".json", ".sqlite"):
            path = Path(folder) / f"knowledge{suffix}"
            kb.save(path)
            restored = CRMSKnowledgeBase.load(path)
            for question in ("Engine Three was created by whom?",
                             "Who was Engine Three created by?"):
                result = restored.ask(question)
                require(result.status == "answered" and result.answer == "Mira Sen"
                        and any(item.get("kind")
                                == "active_to_passive_subject_question_frame"
                                for item in result.language_evidence or []),
                        f"voice recombination was lost after {suffix} save/load")
            restored.close()

            conflict_path = Path(folder) / f"conflict{suffix}"
            conflict.save(conflict_path)
            restored_conflict = CRMSKnowledgeBase.load(conflict_path)
            conflict_result = restored_conflict.ask(
                "Device Three was created by whom?")
            require(conflict_result.status == "ambiguous"
                    and any(row.get("polarity") == "negative"
                            for row in conflict_result.evidence or []),
                    f"negative conflict was lost after {suffix} save/load")
            restored_conflict.close()

    print("grounded active/passive question recombination: PASS")
    print("regular -ed predicates: created, designed; both passive question orders; "
          "held-out fact cited; "
          "training lineage retained")
    print("one-example, missing-auxiliary, unsupported-predicate, role-swap, "
          "explicit-negative, JSON, and SQLite controls: PASS")


if __name__ == "__main__":
    main()

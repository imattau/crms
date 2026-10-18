"""Ensure ambiguous answers prevent unsafe pronoun binding selection."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    kb = CRMSKnowledgeBase()
    facts = (
        ("Maker", "built", "Engine", "source:build-engine"),
        ("Foundry", "built", "Gearbox", "source:build-gearbox"),
        ("Engine", "designed", "Product A", "source:engine-a"),
        ("Engine", "designed", "Product B", "source:engine-b"),
        ("Maker", "designed", "Product C", "source:maker-c"),
    )
    for subject, relation, obj, source in facts:
        kb.add_fact(subject, relation, obj, source)
    for question, relation, answer_field, entity, answer in (
            ("Who built Engine?", "built", "subject", "Engine", "Maker"),
            ("Who built Gearbox?", "built", "subject", "Gearbox", "Foundry"),
            ("What did Engine design?", "designed", "object", "Engine", "Product A"),
            ("What did Maker design?", "designed", "object", "Maker", "Product C")):
        kb.teach_question(question, relation=relation,
                          answer_field=answer_field, bound_entity=entity,
                          answer=answer)

    dialogue = CRMSDialogue(kb)
    initial = dialogue.turn("Who built Engine?")
    if initial.status != "answered" or initial.response is None:
        raise SystemExit(f"failed to establish referent context: {initial}")
    followup = dialogue.turn("What did it design?")
    if (followup.status == "answered"
            or "multiple bindings" not in followup.text
            or followup.resolved_question != "What did it design?"):
        raise SystemExit(f"ambiguous antecedent was silently selected: {followup}")

    print("ambiguous pronoun-binding diagnostic: PASS")
    print("ambiguous and single-answer referents trigger clarification: PASS")


if __name__ == "__main__":
    main()

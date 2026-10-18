"""Check multi-turn follow-ups across learned entity plural forms."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    kb = CRMSKnowledgeBase()
    for subject, entity, source in (
            ("Ada", "Engine", "facts:engine"),
            ("Bea", "Compiler", "facts:compiler"),
            ("Sage", "Sculpture", "facts:sculpture")):
        kb.add_fact(subject, "designed", entity, source)
        kb.teach_question(f"Who designed {entity}?", relation="designed",
                          answer_field="subject", bound_entity=entity,
                          answer=subject)
    kb.teach_entity_alias("Engines", "Engine", source="engine-plural#1")
    kb.teach_entity_alias("Compilers", "Compiler", source="compiler-plural#1")

    dialogue = CRMSDialogue(kb)
    first = dialogue.turn("Who designed Sculptures?")
    if first.status != "answered" or first.response.answer != "Sage":
        raise SystemExit(f"plural question did not establish dialogue state: {first}")
    if dialogue.object_entity != "Sculpture":
        raise SystemExit("dialogue retained the surface plural instead of canonical entity")

    second = dialogue.turn("What about Compilers?")
    if second.status != "answered" or second.response.answer != "Bea":
        raise SystemExit(f"follow-up did not replace a generated plural mention: {second}")
    if dialogue.object_entity != "Compiler":
        raise SystemExit("follow-up did not update the canonical object referent")

    third = dialogue.turn("And Sculptures?")
    if third.status != "answered" or third.response.answer != "Sage":
        raise SystemExit(f"follow-up failed to restore the induced plural form: {third}")
    if not any(item.get("kind") == "induced_entity_plural"
               for item in third.response.language_evidence or []):
        raise SystemExit("dialogue follow-up omitted induced plural evidence")

    correction = dialogue.turn("Actually, I meant Compilers.")
    if (correction.status != "answered" or correction.response.answer != "Bea"
            or "Compilers" not in correction.resolved_question
            or not any(item.get("kind") == "entity_alias"
                       for item in correction.response.language_evidence or [])):
        raise SystemExit("entity correction did not preserve the learned alias form")

    corrected = dialogue._canonical_entity("Sculptures")
    if corrected != "Sculpture":
        raise SystemExit("entity correction lookup did not resolve the learned plural")

    print("dialogue plural follow-up diagnostic: PASS")
    print("multi-turn surface replacement, canonical referent tracking, evidence retention, correction lookup: PASS")


if __name__ == "__main__":
    main()

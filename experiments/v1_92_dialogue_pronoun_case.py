"""Check subject/object pronoun resolution against grounded dialogue roles.

Run from the project root with:
    python3 experiments/v1_92_dialogue_pronoun_case.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    kb = CRMSKnowledgeBase()
    for subject, obj in (("Lab", "the Researchers"),
                         ("Institute", "the Scientists")):
        kb.add_fact(subject, "employs", obj, f"source:employ:{subject}")
        kb.teach_question(f"Who employs {obj}?", relation="employs",
                          answer_field="subject", bound_entity=obj,
                          answer=subject)
    for subject, obj in (("the Researchers", "the Project"),
                         ("the Scientists", "the Archive")):
        kb.add_fact(subject, "manage", obj, f"source:manage:{subject}")
        kb.teach_question(f"What do {subject} manage?", relation="manage",
                          answer_field="object", bound_entity=subject,
                          answer=obj)

    dialogue = CRMSDialogue(kb)
    first = dialogue.turn("Who employs the Researchers?")
    object_followup = dialogue.turn("Who employs them?")
    if (first.response is None or first.response.answer != "Lab"
            or object_followup.response is None
            or object_followup.response.answer != "Lab"):
        raise SystemExit(f"object-case pronoun did not resolve object role: {object_followup}")
    cross_role_followup = dialogue.turn("What do they manage?")
    if (cross_role_followup.response is None
            or cross_role_followup.response.answer != "the Project"):
        raise SystemExit(
            f"pronoun antecedent was restricted to its prior fact role: {cross_role_followup}")

    subject_first = dialogue.turn("What do the Scientists manage?")
    subject_followup = dialogue.turn("What do they manage?")
    if (subject_first.response is None
            or subject_first.response.answer != "the Archive"
            or subject_followup.response is None
            or subject_followup.response.answer != "the Archive"):
        raise SystemExit(f"subject-case pronoun did not resolve subject role: {subject_followup}")

    print("dialogue pronoun case diagnostic: PASS")
    print("evidence-resolved subject/object antecedents, including role changes: PASS")


if __name__ == "__main__":
    main()

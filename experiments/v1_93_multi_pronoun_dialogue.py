"""Check bounded evidence-based resolution of multiple pronouns.

Run from the project root with:
    python3 experiments/v1_93_multi_pronoun_dialogue.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def build_knowledge() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    facts = [("Ada", "designed", "the Engine"),
             ("Grace", "designed", "the Compiler")]
    for subject, relation, obj in facts:
        kb.add_fact(subject, relation, obj, f"source:{subject}:{obj}")
    for subject, obj in (("Ada", "the Engine"), ("Grace", "the Compiler")):
        kb.teach_question(f"Who designed {obj}?", relation="designed",
                          answer_field="subject", bound_entity=obj,
                          answer=subject)
        kb.teach_polar_question(
            f"Did {subject} design {obj}?", subject=subject,
            relation="designed", obj=obj, answer=True)
    return kb


def main() -> None:
    dialogue = CRMSDialogue(build_knowledge())
    first = dialogue.turn("Who designed the Engine?")
    followup = dialogue.turn("Did she design it?")
    if (first.response is None or first.response.answer != "Ada"
            or followup.status != "answered" or followup.response is None
            or followup.response.truth is not True
            or followup.resolved_question != "Did Ada design the Engine?"):
        raise SystemExit(f"two-pronoun grounded follow-up failed: {followup}")

    ambiguous_kb = build_knowledge()
    ambiguous = CRMSDialogue(ambiguous_kb)
    if ambiguous.turn("Who designed the Engine?").status != "answered":
        raise SystemExit("could not establish pronoun context for ambiguity control")
    for subject, obj in (("Ada", "Ada"), ("the Engine", "Ada"),
                         ("the Engine", "the Engine")):
        ambiguous_kb.add_fact(subject, "designed", obj,
                              f"source:cross:{subject}:{obj}")
    result = ambiguous.turn("Did she design it?")
    if (result.status != "unknown"
            or "multiple bindings" not in result.text):
        raise SystemExit(f"multiple supported bindings were guessed: {result}")
    too_many = ambiguous.turn("Did she design it because they said her name to them?")
    if (too_many.status != "unknown"
            or "too many pronoun bindings" not in too_many.text):
        raise SystemExit("pronoun search exceeded its explicit binding bound")

    print("multi-pronoun dialogue diagnostic: PASS")
    print("unique binding, multiple-binding clarification, four-pronoun bound: PASS")


if __name__ == "__main__":
    main()

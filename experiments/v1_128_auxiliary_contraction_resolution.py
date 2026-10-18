"""Resolve common auxiliary contractions from exact grounded evidence.

Run from the project root with:
    python3 experiments/v1_128_auxiliary_contraction_resolution.py
"""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue, DialogueTurn
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex

PROJECT = Path(__file__).resolve().parents[1]


def research_resolution(question: str, reading: str) -> DialogueTurn:
    index = CRMSResearchIndex()
    index.add_document("source", "Grounded note", reading, "note.txt")
    return CRMSDialogue(CRMSKnowledgeBase()).turn(
        question, research_index=index)


def main() -> None:
    # Negative auxiliary contractions must reach the same explicit-polarity
    # QA path as their expanded forms, and missing evidence must stay unknown.
    kb = CRMSKnowledgeBase()
    polar_examples = [("Ada", "Engine"), ("Grace", "Compiler")]
    for subject, obj in polar_examples:
        kb.add_negative_fact(subject, "designed", obj,
                             "negative:" + subject)
    for index, (subject, obj) in enumerate(polar_examples):
        licensed = kb.teach_polar_question(
            f"Was not the {obj} designed by {subject}?",
            subject=subject, relation="designed", obj=obj, answer=False)
        if licensed != (index == 1):
            raise SystemExit("negative polar frame licensed at the wrong threshold")
    dialogue = CRMSDialogue(kb)
    negative_answer = dialogue.turn(
        "Wasn't the Engine designed by Ada?")
    if (negative_answer.status != "answered"
            or negative_answer.resolved_question
            != "Was not the Engine designed by Ada?"
            or negative_answer.response is None
            or negative_answer.response.truth is not False):
        raise SystemExit(f"contracted negative QA failed: {negative_answer}")
    unknown_polar = dialogue.turn("Wasn't the Engine designed by Grace?")
    if (unknown_polar.status != "unknown"
            or unknown_polar.response is None
            or unknown_polar.response.truth is not None):
        raise SystemExit(f"missing evidence was treated as negative: {unknown_polar}")

    cases = [
        ("Who'll design the Engine?", "Who will design the Engine?"),
        ("They've designed the Engine?", "They have designed the Engine?"),
        ("They're designing the Engine?", "They are designing the Engine?"),
        ("I'm designing the Engine?", "I am designing the Engine?"),
        ("Where'd Ada design the Engine?", "Where did Ada design the Engine?"),
        ("The Engine isn't ready.", "The Engine is not ready."),
        ("The Engine can't move.", "The Engine cannot move."),
        ("They ain't ready.", "They are not ready."),
    ]
    for question, expected in cases:
        result = research_resolution(question, expected)
        if (result.status not in {"sources_found", "needs_review"}
                or result.resolved_question != expected
                or not result.research
                or not result.research.passages):
            raise SystemExit(f"grounded contraction reading failed: {result}")

    # The contracted form is ambiguous. When two readings both match supplied
    # sources, the dialogue must ask for clarification instead of choosing.
    index = CRMSResearchIndex()
    index.add_document("did", "Did note",
                       "Where did Ada design the Engine?", "did.txt")
    index.add_document("would", "Would note",
                       "Where would Ada design the Engine?", "would.txt")
    ambiguous = CRMSDialogue(CRMSKnowledgeBase()).turn(
        "Where'd Ada design the Engine?", research_index=index)
    if (ambiguous.status != "unknown"
            or "multiple readings" not in ambiguous.text
            or ambiguous.resolved_question != "Where'd Ada design the Engine?"):
        raise SystemExit(f"ambiguous contraction did not abstain: {ambiguous}")

    negative_ambiguity = CRMSResearchIndex()
    negative_ambiguity.add_document("are", "Are note", "They are not ready.",
                                    "are.txt")
    negative_ambiguity.add_document("is", "Is note", "They is not ready.",
                                    "is.txt")
    ambiguous_negative = CRMSDialogue(CRMSKnowledgeBase()).turn(
        "They ain't ready.", research_index=negative_ambiguity)
    if (ambiguous_negative.status != "unknown"
            or "multiple readings" not in ambiguous_negative.text
            or ambiguous_negative.resolved_question != "They ain't ready."):
        raise SystemExit(
            f"ambiguous negative contraction did not abstain: {ambiguous_negative}")

    # Named-person possessives are outside the contraction grammar.
    possessive = CRMSDialogue(CRMSKnowledgeBase()).turn(
        "Who designed Ada's Engine?")
    if possessive.resolved_question != "Who designed Ada's Engine?":
        raise SystemExit("proper-name possessive was rewritten")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        dialogue_path = root / "dialogue.json"
        rules_path = root / "rules.json"
        session_path = root / "rule-session.json"
        CRMSKnowledgeBase().save(knowledge_path)
        cli_index = CRMSResearchIndex()
        cli_index.add_document("negative-note", "Engine note",
                               "The Engine is not ready.", "engine.txt")
        cli_index.save(index_path)
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(dialogue_path), "--rules", str(rules_path),
             "--rule-session", str(session_path)],
            input="The Engine isn't ready.\n/quit\n", text=True,
            capture_output=True, check=True, timeout=20)
        if ("The Engine is not ready." not in process.stdout
                or "Source: Engine note" not in process.stdout):
            raise SystemExit(f"terminal contraction research failed:\n{process.stdout}")

    print("auxiliary contraction resolution diagnostic: PASS")
    print("auxiliary and negative contraction grounding, ambiguity abstention, possessive guard, CLI: PASS")


if __name__ == "__main__":
    main()

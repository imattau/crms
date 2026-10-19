"""Bare acknowledgements must respect an open answer-choice context."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def make_ambiguous_knowledge() -> CRMSKnowledgeBase:
    knowledge = CRMSKnowledgeBase()
    knowledge.add_fact("Ada Lovelace", "designed", "the Analytical Engine", "a")
    knowledge.add_fact("Ada Lovelace", "designed", "the Difference Engine", "b")
    knowledge.teach_question(
        "What did Ada Lovelace design?", relation="designed",
        answer_field="object", bound_entity="Ada Lovelace",
        answer="the Analytical Engine")
    knowledge.teach_question(
        "What did Ada Lovelace design?", relation="designed",
        answer_field="object", bound_entity="Ada Lovelace",
        answer="the Difference Engine")
    return knowledge


def main() -> None:
    knowledge = make_ambiguous_knowledge()
    dialogue = CRMSDialogue(knowledge)
    initial = dialogue.turn("What did Ada Lovelace design?")
    require(initial.status == "ambiguous" and dialogue.pending_result is not None,
            f"test setup did not create a pending choice: {initial}")

    confirmation = respond(dialogue, "yes")
    require(confirmation.status == "ambiguous"
            and dialogue.pending_result is not None
            and "does not identify" in confirmation.text,
            "bare yes consumed a pending clarification")
    polite_confirmation = respond(dialogue, "Yes, please.")
    require(polite_confirmation.status == "ambiguous"
            and dialogue.pending_result is not None,
            "polite confirmation consumed a pending clarification")
    acknowledgement = respond(dialogue, "Okay")
    require(acknowledgement.status == "ambiguous"
            and dialogue.pending_result is not None
            and "does not identify" in acknowledgement.text,
            "generic acknowledgement bypassed an open clarification")
    selection = respond(dialogue, "Yeah, the second option please.")
    require(selection.status == "answered"
            and selection.response is not None
            and selection.response.answer == "the Difference Engine"
            and dialogue.pending_result is None,
            f"contextual ordinal selection failed after yes: {selection}")

    unanchored = respond(CRMSDialogue(knowledge), "Nope.")
    require(unanchored.status == "clarify"
            and "don't have an open yes/no question" in unanchored.text,
            f"bare no entered ordinary retrieval without context: {unanchored}")

    with tempfile.TemporaryDirectory(prefix="crms-contextual-intent-") as folder:
        root = Path(folder)
        knowledge.save(root / "knowledge.json")
        CRMSResearchIndex().save(root / "index.json")
        command = [
            sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(root / "index.json"),
            "--rules", str(root / "rules.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        completed = subprocess.run(
            command,
            input="What did Ada Lovelace design?\nokay\nsecond option please\nGoodbye\n",
            text=True, capture_output=True, check=True, timeout=30)
        require("does not identify one of the supported answers" in completed.stdout,
                f"terminal did not explain the unresolved yes: {completed.stdout}")
        require("the Difference Engine" in completed.stdout
                and "CRMS state saved. Goodbye." in completed.stdout,
                f"terminal did not keep and resolve the pending choice: {completed.stdout}")

    print("yes/no with an open choice preserves clarification state: PASS")
    print("ordinal selection after acknowledgement resolves the original candidates: PASS")
    print("unanchored yes/no asks for context instead of querying the corpus: PASS")
    print("terminal interaction retains context across the clarification sequence: PASS")


if __name__ == "__main__":
    main()

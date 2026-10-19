"""An answer to CRMS's follow-up question advances that dialogue task."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    knowledge = CRMSKnowledgeBase()
    knowledge.add_fact("Ada Lovelace", "wrote", "the first algorithm", "source-a")
    dialogue = CRMSDialogue(knowledge)

    prompt = respond(dialogue, "Tell me more.")
    require(prompt.status == "clarify"
            and "Which entity with accepted facts" in prompt.text
            and dialogue.pending_dialogue_slot == "elaboration_topic",
            "unanchored elaboration did not open a typed topic slot")

    hypothesis = classify_user_intent(dialogue, "Ada Lovelace")
    require(hypothesis is not None
            and hypothesis.dialogue_act == "answer-clarification"
            and hypothesis.task_intent == "continue-current-task"
            and hypothesis.decision == "selected"
            and hypothesis.selected_value == "Ada Lovelace"
            and "open_question:elaboration_topic" in hypothesis.context_predicates,
            "topic answer was not interpreted using the open dialogue context")

    with tempfile.TemporaryDirectory(prefix="crms-elaboration-slot-") as folder:
        state_path = Path(folder) / "dialogue.json"
        dialogue.save(str(state_path))
        restored = CRMSDialogue.load(knowledge, str(state_path))
        require(restored.pending_dialogue_slot == "elaboration_topic",
                "the open topic slot did not survive a session restart")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["pending_dialogue_slot"] = "accept-anything"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        try:
            CRMSDialogue.load(knowledge, str(state_path))
        except ValueError:
            pass
        else:
            raise SystemExit("an unknown persisted dialogue slot was trusted")

        root = Path(folder)
        knowledge.save(root / "knowledge.json")
        CRMSResearchIndex().save(root / "index.json")
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(root / "index.json"),
            "--rules", str(root / "rules.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        chat = subprocess.run(
            command, input="Tell me more.\nAda Lovelace\nGoodbye\n",
            text=True, capture_output=True, check=True, timeout=30)
        require("Which entity with accepted facts" in chat.stdout
                and "What I have accepted about Ada Lovelace" in chat.stdout
                and "Ada Lovelace — wrote → the first algorithm" in chat.stdout,
                f"interactive chat missed the contextual follow-up: {chat.stdout}")

    answer = respond(restored, "Ada Lovelace")
    require(answer.status == "elaborated"
            and "Ada Lovelace — wrote → the first algorithm" in answer.text
            and restored.pending_dialogue_slot is None
            and answer.intent_hypothesis is not None
            and answer.intent_hypothesis.selected_value == "Ada Lovelace",
            "the topic slot did not route to the accepted-fact overview")

    unmatched_dialogue = CRMSDialogue(knowledge)
    respond(unmatched_dialogue, "Tell me more.")
    unmatched = respond(unmatched_dialogue, "Python")
    require(unmatched.status == "clarify"
            and "couldn't match" in unmatched.text
            and unmatched_dialogue.pending_dialogue_slot is None,
            "an unknown topic was treated as an answer or left the slot stuck")

    cancelled_dialogue = CRMSDialogue(knowledge)
    respond(cancelled_dialogue, "Tell me more.")
    cancelled = respond(cancelled_dialogue, "Never mind")
    require(cancelled.status == "social"
            and cancelled_dialogue.pending_dialogue_slot is None
            and cancelled.intent_hypothesis is not None
            and cancelled.intent_hypothesis.matched_frame
            == "cancel-open-elaboration-question",
            "the user could not explicitly cancel an open topic question")

    new_question_dialogue = CRMSDialogue(knowledge)
    respond(new_question_dialogue, "Tell me more.")
    new_question = respond(new_question_dialogue,
                           "Who wrote the first algorithm?")
    require(new_question.status == "answered"
            and new_question_dialogue.pending_dialogue_slot is None,
            "a new content question was swallowed by the open topic slot")

    print("topic answers use the open contextual intent: PASS")
    print("typed dialogue slot survives restart and rejects unknown values: PASS")
    print("terminal exchange answers the assistant's follow-up: PASS")
    print("accepted-entity topic answer produces a cited overview: PASS")
    print("unknown topics and explicit cancellation clear the slot: PASS")
    print("a new content question supersedes the pending topic slot: PASS")


if __name__ == "__main__":
    main()

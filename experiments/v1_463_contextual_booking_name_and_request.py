"""Check that booking requests and reservation-name answers use context."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue, infer_open_question_slot
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    booking = classify_user_intent(
        CRMSDialogue(CRMSKnowledgeBase()),
        "Book a reservation with the second one?",
    )
    require(booking is not None
            and booking.dialogue_act == "request-action"
            and booking.task_intent == "make-reservation"
            and booking.goal_intent == "make-reservation",
            f"booking imperative fell through to a generic task: {booking}")

    prompt = "What name should I put the reservation under?"
    slot = infer_open_question_slot(prompt, "detail")
    require(slot == "reservation_name",
            f"reservation-name prompt did not produce a typed slot: {slot}")

    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    dialogue.active_task_intent = "make-reservation"
    dialogue.open_dialogue_question = {
        "prompt": prompt,
        "answer_kind": "detail",
        "expected_slot": slot,
    }
    with tempfile.TemporaryDirectory(prefix="crms-reservation-name-slot-") as folder:
        state_path = Path(folder) / "dialogue.json"
        dialogue.save(str(state_path))
        dialogue = CRMSDialogue.load(CRMSKnowledgeBase(), str(state_path))
        require(dialogue.open_dialogue_question is not None
                and dialogue.open_dialogue_question["expected_slot"] == slot,
                "reservation-name slot did not survive dialogue persistence")
    name_answer = respond(dialogue, "Put it under Frank.")
    require(name_answer is not None
            and name_answer.status == "social"
            and "treat that as your reply" in name_answer.text.casefold()
            and name_answer.intent_hypothesis is not None
            and name_answer.intent_hypothesis.matched_frame
                == "answer-to-open-dialogue-question"
            and name_answer.intent_hypothesis.dialogue_act == "answer-clarification"
            and name_answer.intent_hypothesis.task_intent == "make-reservation",
            f"contextual name answer was treated as a new imperative: {name_answer}")

    unrelated_dialogue = CRMSDialogue(CRMSKnowledgeBase())
    unrelated_dialogue.open_dialogue_question = {
        "prompt": prompt,
        "answer_kind": "detail",
        "expected_slot": slot,
    }
    unrelated = classify_user_intent(unrelated_dialogue, "Tell me a joke.")
    require(unrelated is not None
            and unrelated.matched_frame == "direct-imperative-request"
            and unrelated.dialogue_act == "request-action",
            f"unrelated imperative was swallowed by the open name slot: {unrelated}")

    print("booking imperative is routed to make-reservation: PASS")
    print("reservation name is an explicit contextual slot: PASS")
    print("reservation-name slot survives save/reload: PASS")
    print("name-slot response is interpreted in context: PASS")
    print("unrelated imperative still interrupts the open slot: PASS")


if __name__ == "__main__":
    main()

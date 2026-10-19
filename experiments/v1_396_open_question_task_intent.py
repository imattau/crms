"""Resolve task intent for short answers using the open prompt and task state."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def classify(prompt: str, slot: str, active_task: str | None,
             answer: str = "Two people."):
    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    dialogue.active_task_intent = active_task
    dialogue.open_dialogue_question = {
        "prompt": prompt, "answer_kind": "detail", "expected_slot": slot,
    }
    return classify_user_intent(dialogue, answer)


def main() -> None:
    search = classify("How many people should I search for?", "party_size",
                      "seek-information")
    require(search is not None and search.decision == "selected"
            and search.dialogue_act == "answer-clarification"
            and search.task_intent == "provide-constraint",
            f"search detail inherited the broad task intent: {search}")

    reservation_from_prompt = classify(
        "When would you like to make your reservation for?", "date_time",
        "seek-information", "Tonight at 5 pm.")
    require(reservation_from_prompt is not None
            and reservation_from_prompt.task_intent == "make-reservation",
            f"explicit reservation prompt did not set task phase: {reservation_from_prompt}")

    reservation_from_state = classify(
        "How many people should I plan for?", "party_size", "make-reservation")
    require(reservation_from_state is not None
            and reservation_from_state.task_intent == "make-reservation",
            f"reservation state did not persist through detail answer: {reservation_from_state}")

    change_from_prompt = classify(
        "What time would you like to change your reservation to?", "date_time",
        "seek-information", "8 pm.")
    require(change_from_prompt is not None
            and change_from_prompt.task_intent == "change-reservation",
            f"explicit change prompt did not set task phase: {change_from_prompt}")

    untyped = classify("Which detail should I use?", "detail", None,
                       "A useful detail.")
    require(untyped is not None
            and untyped.task_intent == "continue-current-task",
            f"unspecified task context was over-interpreted: {untyped}")

    print("search detail resolves as a constraint: PASS")
    print("reservation task resolves from active state or explicit prompt: PASS")
    print("change-reservation task resolves from explicit prompt: PASS")
    print("missing task evidence retains the conservative continuation label: PASS")


if __name__ == "__main__":
    main()

"""Resolve task intent for short answers using the open prompt and task state."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue, infer_open_question_slot
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def classify(prompt: str, slot: str, active_task: str | None,
             answer: str = "Two people.", *, answer_kind: str = "detail"):
    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    dialogue.active_task_intent = active_task
    dialogue.open_dialogue_question = {
        "prompt": prompt, "answer_kind": answer_kind, "expected_slot": slot,
    }
    return classify_user_intent(dialogue, answer)


def main() -> None:
    search = classify("How many people should I search for?", "party_size",
                      "seek-information")
    require(search is not None and search.decision == "selected"
            and search.dialogue_act == "provide-information"
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

    confirmation = classify("And you said for two people?", "confirmation",
                            "make-reservation", "Yes.", answer_kind="yes-no")
    require(confirmation is not None and confirmation.dialogue_act == "confirm"
            and confirmation.task_intent == "make-reservation",
            f"confirmation was collapsed into a generic clarification: {confirmation}")
    rejection = classify("Are you sure?", "confirmation", "continue-current-task",
                         "No.", answer_kind="yes-no")
    require(rejection is not None and rejection.dialogue_act == "reject",
            f"negative confirmation was not represented as rejection: {rejection}")
    require(infer_open_question_slot("Is that restaurant good?", "yes-no")
            == "yes_no",
            "ordinary yes/no question was misclassified as a confirmation")
    ordinary_yes = classify("Is that restaurant good?", "yes_no",
                            "seek-information", "Yes.", answer_kind="yes-no")
    require(ordinary_yes is not None
            and ordinary_yes.dialogue_act == "answer-clarification",
            f"ordinary yes/no response was routed as a confirmation: {ordinary_yes}")

    live = CRMSDialogue(CRMSKnowledgeBase())
    live.open_dialogue_question = {
        "prompt": "Are you sure?", "answer_kind": "yes-no",
        "expected_slot": "confirmation",
    }
    respond(live, "Yes")
    require(live.last_intent_hypothesis is not None
            and live.last_intent_hypothesis.dialogue_act == "confirm"
            and live.open_dialogue_question is None,
            "confirming an open yes/no question did not close its discourse state")

    live.open_dialogue_question = {
        "prompt": "Is that right?", "answer_kind": "yes-no",
        "expected_slot": "confirmation",
    }
    respond(live, "No")
    require(live.last_intent_hypothesis is not None
            and live.last_intent_hypothesis.dialogue_act == "reject"
            and live.open_dialogue_question is not None
            and live.open_dialogue_question["prompt"]
            == "Okay. What should I correct?",
            "rejecting a confirmation did not ask for correction details")

    print("search detail resolves as a constraint: PASS")
    print("reservation task resolves from active state or explicit prompt: PASS")
    print("change-reservation task resolves from explicit prompt: PASS")
    print("missing task evidence retains the conservative continuation label: PASS")
    print("explicit yes/no confirmation and rejection use distinct acts: PASS")
    print("confirmation rejection opens a correction-detail question: PASS")


if __name__ == "__main__":
    main()

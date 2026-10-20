"""Type composite assistant prompts as choices or confirmations."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, is_open_yes_no_prompt
from crms_dialogue import CRMSDialogue, infer_open_question_slot
from crms_knowledge import CRMSKnowledgeBase


PROMPTS = (
    (
        "Ok, the total will be $23.89. Can I continue with the purchase?",
        "confirmation",
    ),
    (
        "Amc Empire 25 has a showing at 4:15pm. One ticket will be $10. "
        "Did you want me to book it now?",
        "confirmation",
    ),
    (
        "I found another 9:35pm showing. Would you like to try that one or "
        "should I look for another showtime?",
        "choice",
    ),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    for prompt, expected_slot in PROMPTS:
        require(is_open_yes_no_prompt(prompt),
                f"composite yes/no prompt was not detected: {prompt!r}")
        slot = infer_open_question_slot(prompt, "yes-no")
        require(slot == expected_slot,
                f"prompt type was {slot!r}, expected {expected_slot!r}: {prompt!r}")

    require(not is_open_yes_no_prompt("Which would you prefer?"),
            "an open choice question was collapsed into a yes/no prompt")
    require(infer_open_question_slot("Which would you prefer?", "detail")
            == "choice", "an explicit choice question lost its choice slot")
    require(not is_open_yes_no_prompt("What time would you like?"),
            "a wh-question was classified as a yes/no prompt")

    confirmation = CRMSDialogue(CRMSKnowledgeBase())
    confirmation.active_task_intent = "other-task"
    prompt, _ = PROMPTS[0]
    confirmation.open_dialogue_question = {
        "prompt": prompt,
        "answer_kind": "yes-no",
        "expected_slot": "confirmation",
    }
    accepted = classify_user_intent(confirmation, "Yes, please.")
    require(accepted is not None
            and accepted.dialogue_act == "confirm"
            and accepted.task_intent == "resolve-ambiguity"
            and accepted.goal_intent == "other-task"
            and accepted.decision == "selected",
            f"purchase confirmation was not recognized: {accepted!r}")

    choice = CRMSDialogue(CRMSKnowledgeBase())
    prompt, _ = PROMPTS[2]
    choice.open_dialogue_question = {
        "prompt": prompt,
        "answer_kind": "yes-no",
        "expected_slot": "choice",
    }
    selected = classify_user_intent(choice, "Yes, please.")
    require(selected is not None
            and selected.dialogue_act == "answer-clarification"
            and selected.task_intent == "resolve-ambiguity"
            and selected.decision == "selected",
            f"choice answer lost its open-choice context: {selected!r}")

    print("composite confirmation prompts classified and typed: 2/2")
    print("composite option prompt retained choice state: 1/1")
    print("wh-question and choice negatives preserved: 2/2")
    print("yes-to-confirmation and yes-to-choice remain distinct: PASS")


if __name__ == "__main__":
    main()

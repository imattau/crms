"""Cover explicit positive acknowledgement forms without changing task state."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    for phrase in ("That sounds nice.", "That sounds good.",
                   "That'll be good.", "It seems perfect.",
                   "Okay, great.", "Okay, I got it."):
        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        dialogue.active_task_intent = "make-reservation"
        hypothesis = classify_user_intent(dialogue, phrase)
        require(hypothesis is not None
                and hypothesis.dialogue_act == "acknowledgement"
                and hypothesis.task_intent == "continue-current-task"
                and hypothesis.decision == "selected",
                f"positive response was not recognized as an acknowledgement: {phrase!r} -> {hypothesis}")

    live = CRMSDialogue(CRMSKnowledgeBase())
    live.active_task_intent = "make-reservation"
    turn = respond(live, "That'll be good.")
    require(turn.intent_hypothesis is not None
            and turn.intent_hypothesis.dialogue_act == "acknowledgement"
            and live.active_task_intent == "make-reservation",
            "acknowledgement did not preserve the active task in the chat route")

    require(classify_user_intent(CRMSDialogue(CRMSKnowledgeBase()),
                                 "What sounds nice?") is not None,
            "a content question was swallowed by the acknowledgement frame")
    print("positive assessment phrases route as acknowledgements: PASS")
    print("acknowledgements preserve an active reservation task: PASS")
    print("question wording is not swallowed by the phrase frame: PASS")


if __name__ == "__main__":
    main()

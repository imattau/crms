"""Prevent auxiliary-led questions from matching imperative task rules."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


QUESTIONS = (
    "Do they have booth seating?",
    "Does the restaurant have outdoor seating?",
    "Did the museum open in 1964?",
    "Have they confirmed the reservation?",
    "Can the library host a workshop?",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    for question in QUESTIONS:
        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        hypothesis = classify_user_intent(dialogue, question)
        require(hypothesis is not None
                and hypothesis.dialogue_act == "question"
                and hypothesis.task_intent == "seek-information",
                f"auxiliary-led question misclassified: {question!r}: "
                f"{hypothesis!r}")
        turn = respond(dialogue, question)
        require(turn.intent_hypothesis is not None
                and turn.intent_hypothesis.dialogue_act == "question"
                and turn.intent_hypothesis.task_intent == "seek-information",
                f"chat runtime lost the question intent: {question!r}: {turn!r}")

    # The guard is specific to questions and leaves an actual imperative on
    # the request path.
    imperative = classify_user_intent(
        CRMSDialogue(CRMSKnowledgeBase()), "Do find some booth seating options.")
    require(imperative is not None
            and imperative.dialogue_act == "request-action"
            and imperative.matched_frame == "direct-imperative-request",
            f"imperative request no longer uses its request rule: {imperative!r}")

    continuation_dialogue = CRMSDialogue(CRMSKnowledgeBase())
    continuation_dialogue.last_entity = "Ada Lovelace"
    continuation = classify_user_intent(continuation_dialogue, "Tell me more.")
    require(continuation is not None
            and continuation.dialogue_act == "continuation-request"
            and continuation.task_intent == "continue-current-task"
            and "current_topic_available" in continuation.context_predicates,
            f"topic continuation was treated as a new task: {continuation!r}")

    print(f"auxiliary-led yes/no questions classified as questions: "
          f"{len(QUESTIONS)}/{len(QUESTIONS)}")
    print("actual imperative remains a task request: PASS")
    print("continuation request stays bound to the current topic: PASS")


if __name__ == "__main__":
    main()

"""A rejection followed by an explicit request starts a new task."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    dialogue.open_dialogue_question = {
        "prompt": ("I could select another showtime or cancel the order. "
                   "Which would you prefer?"),
        "answer_kind": "detail",
        "expected_slot": "choice",
    }

    mixed = classify_user_intent(
        dialogue, "No. Just get three tickets for the next showing.")
    require(mixed is not None
            and mixed.dialogue_act == "request-action"
            and mixed.task_intent == "other-task"
            and mixed.decision == "selected"
            and mixed.matched_frame == "negative-with-direct-imperative",
            f"rejection plus request was absorbed as a choice answer: {mixed!r}")

    bare = classify_user_intent(dialogue, "No.")
    require(bare is not None and bare.decision == "ambiguous"
            and bare.dialogue_act == "answer-clarification",
            f"bare rejection escaped the open choice: {bare!r}")

    detail = classify_user_intent(
        dialogue, "No, I would prefer the other showing.")
    require(detail is not None and detail.dialogue_act == "answer-clarification"
            and detail.task_intent == "resolve-ambiguity",
            f"negative preference detail stopped answering the open choice: "
            f"{detail!r}")

    routed = CRMSDialogue(CRMSKnowledgeBase())
    routed.open_dialogue_question = dict(dialogue.open_dialogue_question)
    full_turn = respond(
        routed, "No. Just get three tickets for the next showing.")
    require(full_turn.intent_hypothesis is not None
            and full_turn.intent_hypothesis.dialogue_act == "request-action"
            and full_turn.intent_hypothesis.task_intent == "other-task"
            and routed.history[-1]["act"] == "request-action",
            f"ordinary chat did not carry the new-request interpretation: "
            f"{full_turn!r}")

    print("negative prefix with direct request starts a new task: PASS")
    print("bare no remains ambiguous against an open choice: PASS")
    print("negative preference detail remains an answer: PASS")
    print("ordinary chat records the new request act: PASS")


if __name__ == "__main__":
    main()

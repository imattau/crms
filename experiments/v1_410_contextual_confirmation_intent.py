"""Confirmation intent frames receive the actual open-question context."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent
from crms_dialogue import CRMSDialogue
from crms_dialogue_intent import (CRMSDialogueIntentModel,
                                  empty_dialogue_intent_memory)
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def make_model() -> CRMSDialogueIntentModel:
    memory = empty_dialogue_intent_memory()
    memory["learned_frames"] = [{
        "frame_id": "confirm-yes-on-confirmation",
        "dialogue_act": "confirm",
        "task_intent": "continue-current-task",
        "surface_patterns": ["Yes"],
        "context_predicates": ["awaiting_confirmation"],
        "predecessor_act": "confirmation-request",
        "source_citations": ["dialogue-a#yes", "dialogue-b#yes"],
        "status": "heldout-validated",
        "validation": {
            "status": "heldout-validated",
            "train_conversation_ids": ["dialogue-a", "dialogue-c"],
            "holdout_conversation_ids": ["dialogue-b"],
            "reviewer_count": 2,
            "metrics": {"agreement": 1.0},
        },
        "runtime_route": None,
    }]
    return CRMSDialogueIntentModel(memory)


def main() -> None:
    model = make_model()
    confirmation = CRMSDialogue(CRMSKnowledgeBase(), intent_model=model)
    confirmation.open_dialogue_question = {
        "prompt": "To confirm, is that 6:30 tonight?",
        "answer_kind": "yes-no", "expected_slot": "confirmation",
    }
    context, predecessor = confirmation.intent_context()
    require("awaiting_confirmation" in context
            and "awaiting_yes_no_answer" in context
            and predecessor == "confirmation-request",
            f"confirmation prompt context was lost: {context}, {predecessor}")
    selected = classify_user_intent(confirmation, "Yes")
    require(selected is not None and selected.decision == "selected"
            and selected.dialogue_act == "confirm"
            and selected.matched_frame == "confirm-yes-on-confirmation",
            f"confirmation-specific intent frame did not match: {selected}")

    ordinary = CRMSDialogue(CRMSKnowledgeBase(), intent_model=model)
    ordinary.open_dialogue_question = {
        "prompt": "Do you want to book a table?",
        "answer_kind": "yes-no", "expected_slot": "yes_no",
    }
    ordinary_context, ordinary_predecessor = ordinary.intent_context()
    require("awaiting_yes_no_answer" in ordinary_context
            and "awaiting_confirmation" not in ordinary_context
            and ordinary_predecessor == "clarification-request",
            "ordinary yes/no question was collapsed into a confirmation")
    ordinary_answer = classify_user_intent(ordinary, "Yes")
    require(ordinary_answer is not None
            and ordinary_answer.matched_frame == "answer-to-open-dialogue-question"
            and ordinary_answer.matched_frame != "confirm-yes-on-confirmation",
            "generic yes/no response was misread by a confirmation-only frame")

    detail = CRMSDialogue(CRMSKnowledgeBase(), intent_model=model)
    detail.open_dialogue_question = {
        "prompt": "What time should I use?",
        "answer_kind": "detail", "expected_slot": "date_time",
    }
    detail_context, detail_predecessor = detail.intent_context()
    require("awaiting_confirmation" not in detail_context
            and detail_predecessor == "clarification-request",
            "detail clarification received confirmation context")

    print("confirmation prompts expose contextual confirmation state: PASS")
    print("portable frames can condition on the preceding confirmation request: PASS")
    print("ordinary yes/no and detail prompts remain distinct: PASS")


if __name__ == "__main__":
    main()

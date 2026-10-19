"""Use the active task to disambiguate identical detail answers."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue
from crms_dialogue_intent import (CRMSDialogueIntentModel,
                                  empty_dialogue_intent_memory)
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def frame(frame_id: str, task: str, active_task: str,
          citation: str) -> dict:
    return {
        "frame_id": frame_id,
        "dialogue_act": "answer-clarification",
        "task_intent": task,
        "surface_patterns": ["two people"],
        "context_predicates": [
            "pending_assistant_question", "awaiting_user_detail",
            "awaiting_slot_party_size", f"active_task_{active_task}",
        ],
        "predecessor_act": "clarification-request",
        "source_citations": [citation, citation + "-independent"],
        "status": "heldout-validated",
        "validation": {
            "status": "heldout-validated",
            "train_conversation_ids": [frame_id + "-train"],
            "holdout_conversation_ids": [frame_id + "-holdout"],
            "reviewer_count": 2,
            "metrics": {"joint_intent_agreement": 1.0},
        },
        "runtime_route": None,
    }


def main() -> None:
    payload = empty_dialogue_intent_memory()
    payload["learned_frames"] = [
        frame("party-size-search", "provide-constraint", "seek_information",
              "search-corpus:conversation-1#turn=5"),
        frame("party-size-reservation", "make-reservation", "make_reservation",
              "reservation-corpus:conversation-2#turn=8"),
    ]
    model = CRMSDialogueIntentModel(payload)
    kb = CRMSKnowledgeBase()

    booking = CRMSDialogue(kb, intent_model=model)
    booking.active_task_intent = "make-reservation"
    booking.open_dialogue_question = {
        "prompt": "How many people should I book for?",
        "answer_kind": "detail", "expected_slot": "party_size",
    }
    booking.history.append({"act": "question", "utterance": "How many people?",
                            "status": "clarify"})
    booking_context, _ = booking.intent_context()
    require("active_task_make_reservation" in booking_context,
            "reservation task identity was not exposed as typed context")
    booking_hypothesis = classify_user_intent(booking, "Two people.")
    require(booking_hypothesis is not None
            and booking_hypothesis.decision == "selected"
            and booking_hypothesis.task_intent == "make-reservation"
            and booking_hypothesis.matched_frame == "party-size-reservation",
            f"party-size answer ignored the active reservation: {booking_hypothesis}")

    search = CRMSDialogue(kb, intent_model=model)
    search.active_task_intent = "seek-information"
    search.open_dialogue_question = {
        "prompt": "How many people should I search for?",
        "answer_kind": "detail", "expected_slot": "party_size",
    }
    search.history.append({"act": "question", "utterance": "How many people?",
                           "status": "clarify"})
    search_hypothesis = classify_user_intent(search, "Two people.")
    require(search_hypothesis is not None
            and search_hypothesis.decision == "selected"
            and search_hypothesis.task_intent == "provide-constraint"
            and search_hypothesis.matched_frame == "party-size-search",
            f"party-size answer ignored the active search: {search_hypothesis}")

    start = empty_dialogue_intent_memory()
    start["builtin_policy"].append({
        "policy_id": "start-reservation",
        "dialogue_act": "request-action",
        "task_intent": "make-reservation",
        "surface_patterns": ["I want to book a table"],
        "context_predicates": [], "predecessor_act": None,
        "runtime_route": None,
    })
    live = CRMSDialogue(kb, intent_model=CRMSDialogueIntentModel(start))
    start_turn = respond(live, "I want to book a table")
    require(start_turn.intent_hypothesis is not None
            and start_turn.intent_hypothesis.task_intent == "make-reservation"
            and live.active_task_intent == "make-reservation"
            and "active_task_make_reservation" in live.intent_context()[0],
            "a selected task intent did not become contextual session state")
    with tempfile.TemporaryDirectory(prefix="crms-task-intent-state-") as folder:
        state_path = Path(folder) / "dialogue.json"
        live.save(str(state_path))
        restored = CRMSDialogue.load(
            kb, str(state_path), intent_model=CRMSDialogueIntentModel(start))
        require(restored.active_task_intent == "make-reservation"
                and "active_task_make_reservation" in restored.intent_context()[0],
                "task-specific context did not survive dialogue-state reload")

    print("active task distinguishes search constraints from reservation details: PASS")
    print("selected task intent becomes explicit session context: PASS")
    print("task-specific context survives state reload: PASS")


if __name__ == "__main__":
    main()

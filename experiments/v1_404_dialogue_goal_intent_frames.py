"""Exercise broad-goal fields in portable contextual dialogue frames."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue
from crms_dialogue_intent import (CRMSDialogueIntentModel,
                                  empty_dialogue_intent_memory,
                                  validate_dialogue_intent_memory)
from crms_knowledge import CRMSKnowledgeBase


PHRASE = "Could you give me the restaurant address?"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def frame(frame_id: str, *, status: str, goal: str | None,
          task: str = "seek-information") -> dict:
    return {
        "frame_id": frame_id,
        "dialogue_act": "question",
        "task_intent": task,
        "goal_intent": goal,
        "surface_patterns": [PHRASE],
        "context_predicates": ["active_task_make_reservation"],
        "predecessor_act": None,
        "source_citations": [f"dialogue-a#{frame_id}", f"dialogue-b#{frame_id}"],
        "status": status,
        "validation": ({
            "status": "heldout-validated",
            "train_conversation_ids": ["dialogue-a", "dialogue-c"],
            "holdout_conversation_ids": ["dialogue-b"],
            "reviewer_count": 2,
            "metrics": {"agreement": 1.0},
        } if status == "heldout-validated" else None),
        "runtime_route": None,
    }


def dialogue_with(model: CRMSDialogueIntentModel) -> CRMSDialogue:
    dialogue = CRMSDialogue(CRMSKnowledgeBase(), intent_model=model)
    dialogue.active_task_intent = "make-reservation"
    return dialogue


def main() -> None:
    payload = empty_dialogue_intent_memory()
    payload["learned_frames"] = [frame(
        "reservation-address", status="heldout-validated",
        goal="make-reservation")]
    model = CRMSDialogueIntentModel(payload)
    dialogue = dialogue_with(model)
    hypothesis = classify_user_intent(dialogue, PHRASE)
    require(hypothesis is not None
            and hypothesis.task_intent == "seek-information"
            and hypothesis.goal_intent == "make-reservation",
            "portable frame did not return immediate intent and broad goal")
    turn = respond(dialogue, PHRASE)
    require(turn.intent_hypothesis is not None
            and turn.intent_hypothesis.goal_intent == "make-reservation"
            and dialogue.active_task_intent == "make-reservation"
            and dialogue.active_task_subgoal == "seek-information",
            "runtime did not preserve broad goal while recording subgoal")

    conflicting = empty_dialogue_intent_memory()
    conflicting["learned_frames"] = [
        frame("reservation-reading", status="heldout-validated",
              goal="make-reservation"),
        frame("availability-reading", status="heldout-validated",
              goal="check-availability"),
    ]
    conflict_model = CRMSDialogueIntentModel(conflicting)
    conflict_dialogue = dialogue_with(conflict_model)
    ambiguous = classify_user_intent(conflict_dialogue, PHRASE)
    require(ambiguous is not None and ambiguous.decision == "ambiguous"
            and ambiguous.goal_intent is None,
            "conflicting broad-goal frames silently selected one reading")
    respond(conflict_dialogue, PHRASE)
    require(conflict_dialogue.active_task_intent == "make-reservation",
            "ambiguous goal frame changed active dialogue goal")

    candidate = empty_dialogue_intent_memory()
    candidate["learned_frames"] = [frame(
        "unlicensed-reservation", status="candidate", goal="make-reservation")]
    candidate_model = CRMSDialogueIntentModel(candidate)
    require(candidate_model.resolve(
        PHRASE, context={"active_task_make_reservation"},
        predecessor_act=None) is None,
        "candidate goal frame affected runtime resolution")

    legacy = empty_dialogue_intent_memory()
    old_frame = frame("legacy-frame", status="candidate", goal=None)
    old_frame.pop("goal_intent")
    legacy["learned_frames"] = [old_frame]
    validated_legacy = validate_dialogue_intent_memory(legacy)
    require(validated_legacy["learned_frames"][0].get("goal_intent") is None,
            "legacy frame without goal failed validation")

    invalid = empty_dialogue_intent_memory()
    invalid["learned_frames"] = [frame(
        "bad-goal", status="candidate", goal="unlicensed-goal")]
    try:
        validate_dialogue_intent_memory(invalid)
    except ValueError as error:
        require("unknown goal intent" in str(error),
                f"invalid goal failed for the wrong reason: {error}")
    else:
        raise SystemExit("invalid broad goal was accepted")

    print("validated dialogue frames preserve a broad goal and immediate subgoal: PASS")
    print("conflicting broad-goal readings remain ambiguous and inert: PASS")
    print("candidate frames stay inert; legacy frames remain compatible: PASS")
    print("unsupported goal labels are rejected: PASS")


if __name__ == "__main__":
    main()

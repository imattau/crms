"""Keep a broad dialogue goal while recording its current subgoal."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    dialogue.active_task_intent = "make-reservation"
    dialogue.open_dialogue_question = {
        "prompt": "What type of food do you like?",
        "answer_kind": "detail", "expected_slot": "cuisine",
    }

    turn = respond(dialogue, "French food.")
    require(turn.intent_hypothesis is not None
            and turn.intent_hypothesis.task_intent == "provide-constraint",
            f"restaurant search detail was not typed as a constraint: {turn}")
    require(dialogue.active_task_intent == "make-reservation"
            and dialogue.active_task_subgoal == "provide-constraint",
            "constraint replaced the broader reservation goal")
    context, _ = dialogue.intent_context()
    require("active_task_make_reservation" in context
            and "active_subgoal_provide_constraint" in context,
            f"goal and subgoal were not both exposed: {context}")

    followup = CRMSDialogue(CRMSKnowledgeBase())
    followup.active_task_intent = "make-reservation"
    # Taskmaster-1 dev, conversation dlg-048c8c7c-f409-4c6b-9737-09582bb04c31,
    # user turn 16; the turn was labeled seek-information during a reservation.
    question = respond(followup, "Could you just give me the phone number?")
    require(question.intent_hypothesis is not None
            and question.intent_hypothesis.task_intent == "seek-information"
            and followup.active_task_intent == "make-reservation"
            and followup.active_task_subgoal == "seek-information",
            "a venue information question replaced the reservation goal")
    followup_context, _ = followup.intent_context()
    require("active_task_make_reservation" in followup_context
            and "active_subgoal_seek_information" in followup_context,
            f"information subgoal was not made observable: {followup_context}")

    standalone = CRMSDialogue(CRMSKnowledgeBase())
    respond(standalone, "Could you just give me the phone number?")
    require(standalone.active_task_intent == "seek-information"
            and standalone.active_task_subgoal is None,
            "information seeking without a parent task was misclassified as a subgoal")

    with tempfile.TemporaryDirectory(prefix="crms-goal-subgoal-") as folder:
        state_path = Path(folder) / "dialogue.json"
        dialogue.save(str(state_path))
        state = json.loads(state_path.read_text(encoding="utf-8"))
        require(state["format_version"] == 18
                and state["active_task_intent"] == "make-reservation"
                and state["active_task_subgoal"] == "provide-constraint",
                "saved dialogue omitted the hierarchical task state")
        restored = CRMSDialogue.load(CRMSKnowledgeBase(), str(state_path))
        require(restored.active_task_intent == "make-reservation"
                and restored.active_task_subgoal == "provide-constraint",
                "goal/subgoal state did not survive reload")

        state["active_task_subgoal"] = "unlicensed-action"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        try:
            CRMSDialogue.load(CRMSKnowledgeBase(), str(state_path))
        except ValueError:
            pass
        else:
            raise AssertionError("unknown task subgoal was accepted")

    dialogue.reset_history()
    require(dialogue.active_task_intent is None
            and dialogue.active_task_subgoal is None,
            "full dialogue reset left goal/subgoal state behind")
    print("reservation goal survives search and information subgoals: PASS")
    print("goal and subgoal context persist and validate: PASS")
    print("explicit reset clears both levels: PASS")


if __name__ == "__main__":
    main()

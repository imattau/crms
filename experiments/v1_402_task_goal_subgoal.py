"""Keep a broad dialogue goal while recording its current subgoal."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    for request in (
            "I need to make a reservation for an Italian restaurant in San Francisco.",
            "I'd like to book a table for tonight.",
            "Could we please set up a reservation?",
            "Let's reserve a table.",
            "Hi, I need to make a dinner reservation in San Francisco.",
            "Okay. I'd like to go to the Little Sheep. I'd like to make a reservation.",
            "Okay. Just make a reservation for that first one.",
            "I'm trying to make a reservation at a restaurant in San Francisco.",
            "I'd like you to book a restaurant for me.",
            "I would like you to book a restaurant for dinner.",
            "Let's do a reservation at Scoma's for tonight, party of two.",
            "I will go with the first location. Could we set up a reservation "
            "for later tonight for my party of four?"):
        hypothesis = classify_user_intent(CRMSDialogue(CRMSKnowledgeBase()), request)
        require(hypothesis is not None
                and hypothesis.task_intent == "make-reservation"
                and hypothesis.dialogue_act == "request-action",
                f"explicit reservation request was not recognized: {request!r}: {hypothesis}")
    for how_to_text in (
            "How do I make a reservation?",
            "How do I book a restaurant?",
            "Could you please tell me how to make a reservation?",
            "Could you tell me how to book a restaurant?"):
        how_to = classify_user_intent(
            CRMSDialogue(CRMSKnowledgeBase()), how_to_text)
        require(how_to is not None and how_to.task_intent == "seek-information",
                f"a how-to question was mistaken for booking: {how_to_text!r}: {how_to}")

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
    start = respond(
        followup,
        "I need to make a reservation for an Italian restaurant in San Francisco.")
    require(start.intent_hypothesis is not None
            and start.intent_hypothesis.task_intent == "make-reservation"
            and followup.active_task_intent == "make-reservation",
            "ordinary reservation wording did not establish the broad task goal")
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

    mixed = CRMSDialogue(CRMSKnowledgeBase())
    mixed_turn = respond(
        mixed,
        "Okay. So, I'll make a reservation at that restaurant. "
        "Could you please tell me the address so I can write it down?")
    require(mixed_turn.intent_hypothesis is not None
            and mixed_turn.intent_hypothesis.task_intent == "seek-information"
            and mixed_turn.intent_hypothesis.goal_intent == "make-reservation"
            and mixed.active_task_intent == "make-reservation"
            and mixed.active_task_subgoal == "seek-information",
            "a mixed booking goal and information request was collapsed to one intent")

    with tempfile.TemporaryDirectory(prefix="crms-goal-subgoal-") as folder:
        state_path = Path(folder) / "dialogue.json"
        mixed_state_path = Path(folder) / "mixed-dialogue.json"
        mixed.save(str(mixed_state_path))
        restored_mixed = CRMSDialogue.load(
            CRMSKnowledgeBase(), str(mixed_state_path))
        require(restored_mixed.last_intent_hypothesis is not None
                and restored_mixed.last_intent_hypothesis.goal_intent
                == "make-reservation"
                and restored_mixed.active_task_intent == "make-reservation"
                and restored_mixed.active_task_subgoal == "seek-information",
                "mixed intent goal did not survive state persistence")

        dialogue.save(str(state_path))
        state = json.loads(state_path.read_text(encoding="utf-8"))
        valid_state = json.loads(json.dumps(state))
        require(state["format_version"] == 21
                and state["active_task_intent"] == "make-reservation"
                and state["active_task_subgoal"] == "provide-constraint",
                "saved dialogue omitted the hierarchical task state")
        restored = CRMSDialogue.load(CRMSKnowledgeBase(), str(state_path))
        require(restored.active_task_intent == "make-reservation"
                and restored.active_task_subgoal == "provide-constraint",
                "goal/subgoal state did not survive reload")

        legacy_goal_state = json.loads(json.dumps(valid_state))
        legacy_goal_state["format_version"] = 18
        legacy_goal_state.pop("active_task_subgoal", None)
        if legacy_goal_state.get("last_intent_hypothesis"):
            legacy_goal_state["last_intent_hypothesis"].pop("goal_intent", None)
        for entry in legacy_goal_state.get("intent_trace", []):
            entry.pop("goal_intent", None)
        state_path.write_text(json.dumps(legacy_goal_state), encoding="utf-8")
        legacy_restored = CRMSDialogue.load(CRMSKnowledgeBase(), str(state_path))
        require(legacy_restored.active_task_intent == "make-reservation"
                and legacy_restored.active_task_subgoal is None,
                "format 18 dialogue state did not migrate without goal/subgoal metadata")

        invalid_subgoal = json.loads(json.dumps(valid_state))
        invalid_subgoal["active_task_subgoal"] = "unlicensed-action"
        state_path.write_text(json.dumps(invalid_subgoal), encoding="utf-8")
        try:
            CRMSDialogue.load(CRMSKnowledgeBase(), str(state_path))
        except ValueError:
            pass
        else:
            raise AssertionError("unknown task subgoal was accepted")

        invalid_goal = json.loads(json.dumps(valid_state))
        invalid_goal["last_intent_hypothesis"]["goal_intent"] = "unlicensed-goal"
        state_path.write_text(json.dumps(invalid_goal), encoding="utf-8")
        try:
            CRMSDialogue.load(CRMSKnowledgeBase(), str(state_path))
        except ValueError:
            pass
        else:
            raise AssertionError("unknown goal intent was accepted from saved state")

    dialogue.reset_history()
    require(dialogue.active_task_intent is None
            and dialogue.active_task_subgoal is None,
            "full dialogue reset left goal/subgoal state behind")

    with tempfile.TemporaryDirectory(prefix="crms-goal-subgoal-cli-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        CRMSKnowledgeBase().save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(knowledge_path),
            "--index", str(index_path),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        completed = subprocess.run(
            command,
            input=("I need to make a reservation for an Italian restaurant in "
                   "San Francisco.\nOkay. So, I'll make a reservation at that "
                   "restaurant. Could you please tell me the address so I can "
                   "write it down?\n/intent\nCould you just give me the phone "
                   "number?\n/intent\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        require("Active goal: make-reservation" in completed.stdout
                and "Current subgoal: seek-information" in completed.stdout
                and '"goal_intent": "make-reservation"' in completed.stdout
                and '"matched_frame": "reservation-goal-with-information-request"'
                in completed.stdout,
                "interactive chat did not expose the retained goal/subgoal")

        direct_request_command = list(command)
        dialogue_arg = direct_request_command.index("--dialogue-state") + 1
        direct_request_command[dialogue_arg] = str(root / "direct-request.json")
        direct_request = subprocess.run(
            direct_request_command,
            input=("I'd like you to book a restaurant for me.\n"
                   "/intent\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        require("Active goal: make-reservation" in direct_request.stdout
                and '"matched_frame": "explicit-reservation-request"'
                    in direct_request.stdout,
                "natural-language booking request did not set the reservation goal")

    print("reservation goal survives search and information subgoals: PASS")
    print("goal and subgoal context persist and validate: PASS")
    print("explicit reset clears both levels: PASS")
    print("interactive chat displays contextual goal and subgoal: PASS")
    print("natural-language 'book a restaurant' wording sets reservation goal: PASS")


if __name__ == "__main__":
    main()

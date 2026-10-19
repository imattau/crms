"""Preserve an assistant clarification as contextual state for the next turn."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue, infer_open_question_slot
from crms_dialogue_intent import (CRMSDialogueIntentModel,
                                  empty_dialogue_intent_memory)
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    for prompt, answer_kind, expected in (
            ("Where would you like to find a restaurant?", "detail", "location"),
            ("How many people are in your party?", "detail", "party_size"),
            ("What time should I use?", "detail", "date_time"),
            ("Do you want to book a table?", "yes-no", "yes_no"),
            ("To confirm, is that 6:30 tonight?", "yes-no", "confirmation"),
            ("Which topic should I expand on?", "detail", "topic")):
        require(infer_open_question_slot(prompt, answer_kind) == expected,
                f"expected slot was not inferred for {prompt!r}")

    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada Lovelace", "wrote", "the first algorithm", "source.txt")
    dialogue = CRMSDialogue(kb)

    clarification = respond(dialogue, "Tell me more")
    require(clarification.status == "clarify"
            and dialogue.open_dialogue_question is not None
            and dialogue.open_dialogue_question["answer_kind"] == "detail"
            and dialogue.open_dialogue_question["expected_slot"] in {
                "topic", "entity", "detail"}
            and "pending_assistant_question" in dialogue.intent_context()[0]
            and "awaiting_user_detail" in dialogue.intent_context()[0]
            and "awaiting_yes_no_answer" not in dialogue.intent_context()[0],
            "assistant clarification did not create inspectable QUD state")
    original_prompt = dialogue.open_dialogue_question["prompt"]

    with tempfile.TemporaryDirectory(prefix="crms-open-qud-") as folder:
        state_path = Path(folder) / "dialogue.json"
        dialogue.save(str(state_path))
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        require(saved["format_version"] == 16
                and saved["open_dialogue_question"]["prompt"] == original_prompt,
                "typed open question was not persisted in state format 16")
        restored = CRMSDialogue.load(kb, str(state_path))
        require(restored.open_dialogue_question == dialogue.open_dialogue_question,
                "open question did not survive state reload")

        result = respond(restored, "Ada Lovelace")
        require(result.status == "elaborated"
                and result.intent_hypothesis is not None
                and result.intent_hypothesis.matched_frame == "elaboration-topic-slot"
                and result.intent_hypothesis.selected_value == "Ada Lovelace"
                and restored.open_dialogue_question is None,
                f"the reply was not interpreted against the open question: {result}")
        require(len(kb._facts) == 1,
                "a user-provided clarification was incorrectly stored as a fact")

    detail = CRMSDialogue(kb)
    detail.open_dialogue_question = {
        "prompt": "What time should I use?", "answer_kind": "detail",
        "expected_slot": "date_time"}
    require("awaiting_slot_date_time" in detail.intent_context()[0],
            "expected date/time slot was not exposed as contextual intent")
    detail_answer = respond(detail, "7 pm")
    require(detail_answer.intent_hypothesis is not None
            and detail_answer.intent_hypothesis.matched_frame
            == "answer-to-open-dialogue-question"
            and detail_answer.intent_hypothesis.selected_value == "7 pm"
            and detail.history[-1]["act"] == "answer-clarification"
            and detail.session_slots["date_time"]["value"] == "7 pm"
            and detail.session_slots["date_time"]["question"] == "What time should I use?"
            and "has_session_slot_date_time" in detail.intent_context()[0]
            and detail.open_dialogue_question is None,
            "a short detail was not retained as session-only task context")
    require(len(kb._facts) == 1,
            "a session task parameter was incorrectly stored as a fact")
    slot_context_memory = empty_dialogue_intent_memory()
    slot_context_memory["builtin_policy"].append({
        "policy_id": "continue-with-known-time",
        "dialogue_act": "continuation-request",
        "task_intent": "continue-current-task",
        "surface_patterns": ["Continue with that time"],
        "context_predicates": ["has_session_slot_date_time"],
        "predecessor_act": None,
        "runtime_route": None,
    })
    slot_context_dialogue = CRMSDialogue(
        kb, intent_model=CRMSDialogueIntentModel(slot_context_memory))
    slot_context_dialogue.session_slots = dict(detail.session_slots)
    slot_context_intent = classify_user_intent(
        slot_context_dialogue, "Continue with that time")
    require(slot_context_intent is not None
            and slot_context_intent.basis == "portable_dialogue_model"
            and slot_context_intent.matched_frame == "continue-with-known-time",
            "a saved user task value did not license a contextual intent frame")
    with tempfile.TemporaryDirectory(prefix="crms-session-task-slots-") as folder:
        slot_state = Path(folder) / "dialogue.json"
        detail.save(str(slot_state))
        payload = json.loads(slot_state.read_text(encoding="utf-8"))
        require(payload["session_slots"]["date_time"] == {
                    "value": "7 pm", "question": "What time should I use?"},
                "session task-slot value or prompt was not persisted")
        restored_slots = CRMSDialogue.load(kb, str(slot_state))
        require(restored_slots.session_slots == detail.session_slots
                and "has_session_slot_date_time"
                in restored_slots.intent_context()[0],
                "session task slot did not survive reload as contextual intent")
        restored_slots.clear()
        require(restored_slots.session_slots == detail.session_slots,
                "clearing entity focus erased the active task parameter")
        restored_slots.reset_history()
        require(not restored_slots.session_slots,
                "full dialogue reset left session task parameters behind")
    farewell = CRMSDialogue(kb)
    farewell.session_slots = dict(detail.session_slots)
    respond(farewell, "Goodbye")
    require(not farewell.session_slots,
            "ending the interaction left task parameters active")

    wrong_kind = CRMSDialogue(kb)
    wrong_kind.open_dialogue_question = {
        "prompt": "Which detail should I use?", "answer_kind": "detail",
        "expected_slot": "detail"}
    respond(wrong_kind, "yes")
    require(wrong_kind.last_intent_hypothesis is None
            or wrong_kind.last_intent_hypothesis.matched_frame
            != "answer-to-open-dialogue-question",
            "bare yes was accepted for a detail question")
    require(not wrong_kind.session_slots,
            "a rejected clarification answer was stored as a task parameter")

    # A generic yes/no prompt accepts a bare yes and records the exact value.
    yes_no = CRMSDialogue(kb)
    yes_no.open_dialogue_question = {
        "prompt": "Would 7 pm work for you?", "answer_kind": "yes-no",
        "expected_slot": "yes_no"}
    yes_no_context = yes_no.intent_context()[0]
    require("awaiting_yes_no_answer" in yes_no_context
            and "awaiting_confirmation" not in yes_no_context,
            "a yes/no question was conflated with an action confirmation")
    before = len(kb._facts)
    answer = respond(yes_no, "Yes")
    require(answer.intent_hypothesis is not None
            and answer.intent_hypothesis.matched_frame
            == "answer-to-open-dialogue-question"
            and answer.intent_hypothesis.selected_value == "Yes"
            and "awaiting_yes_no_answer" in
            answer.intent_hypothesis.context_predicates
            and yes_no.open_dialogue_question is None
            and not yes_no.session_slots
            and yes_no.intent_trace[-1]["selected_value"] == "Yes"
            and len(kb._facts) == before,
            "bare yes was not treated as a contextual task response")

    # A validated contextual frame can select an intent without routing an
    # action; the hand-checked QUD fallback must not shadow the model.
    memory = empty_dialogue_intent_memory()
    memory["learned_frames"].append({
        "frame_id": "yes-as-open-answer",
        "dialogue_act": "answer-clarification",
        "task_intent": "continue-current-task",
        "surface_patterns": ["yes"],
        "context_predicates": ["pending_assistant_question",
                               "awaiting_yes_no_answer"],
        "predecessor_act": None,
        "source_citations": ["taskmaster.txt#sha256=label-example"],
        "status": "heldout-validated",
        "validation": {
            "status": "heldout-validated",
            "train_conversation_ids": ["conversation-train"],
            "holdout_conversation_ids": ["conversation-holdout"],
            "reviewer_count": 2,
            "metrics": {"label_agreement": 1.0},
        },
        "runtime_route": None,
    })
    modeled = CRMSDialogue(
        kb, intent_model=CRMSDialogueIntentModel(memory))
    modeled.open_dialogue_question = {
        "prompt": "Would 7 pm work for you?", "answer_kind": "yes-no",
        "expected_slot": "yes_no"}
    modeled_answer = respond(modeled, "yes")
    require(modeled_answer.intent_hypothesis is not None
            and modeled_answer.intent_hypothesis.basis == "portable_dialogue_model"
            and modeled_answer.intent_hypothesis.matched_frame == "yes-as-open-answer"
            and modeled_answer.intent_hypothesis.evidence_refs
            and modeled.open_dialogue_question is None,
            "a validated context frame did not select the QUD intent")

    # A reusable frame can distinguish the answer slot using the new session
    # context predicate, while an otherwise identical frame cannot match a
    # different expected slot.
    slot_memory = empty_dialogue_intent_memory()
    slot_memory["learned_frames"].append({
        "frame_id": "location-answer-slot",
        "dialogue_act": "answer-clarification",
        "task_intent": "provide-information",
        "surface_patterns": ["San Francisco"],
        "context_predicates": ["pending_assistant_question",
                               "awaiting_slot_location"],
        "predecessor_act": None,
        "source_citations": ["taskmaster.txt#sha256=location-label"],
        "status": "heldout-validated",
        "validation": {
            "status": "heldout-validated",
            "train_conversation_ids": ["location-train"],
            "holdout_conversation_ids": ["location-holdout"],
            "reviewer_count": 2,
            "metrics": {"label_agreement": 1.0},
        },
        "runtime_route": None,
    })
    slot_dialogue = CRMSDialogue(
        kb, intent_model=CRMSDialogueIntentModel(slot_memory))
    slot_dialogue.open_dialogue_question = {
        "prompt": "Where would you like to find a restaurant?",
        "answer_kind": "detail", "expected_slot": "location"}
    slot_intent = classify_user_intent(slot_dialogue, "San Francisco")
    require(slot_intent is not None
            and slot_intent.basis == "portable_dialogue_model"
            and slot_intent.matched_frame == "location-answer-slot"
            and "awaiting_slot_location" in slot_intent.context_predicates,
            "intent model did not use the typed expected-slot context")
    slot_dialogue.open_dialogue_question["expected_slot"] = "date_time"
    wrong_slot_intent = classify_user_intent(slot_dialogue, "San Francisco")
    require(wrong_slot_intent is None
            or wrong_slot_intent.basis != "portable_dialogue_model",
            "a location frame matched an unrelated date/time clarification")
    invalid_memory = empty_dialogue_intent_memory()
    invalid_frame = dict(memory["learned_frames"][0])
    invalid_frame["frame_id"] = "answer-without-question"
    invalid_frame["context_predicates"] = []
    invalid_memory["learned_frames"].append(invalid_frame)
    try:
        CRMSDialogueIntentModel(invalid_memory)
    except ValueError:
        pass
    else:
        raise SystemExit("answer-clarification frame without open-question context was accepted")

    # A new wh-question replaces a stale clarification instead of being consumed.
    replacement = CRMSDialogue(CRMSKnowledgeBase())
    replacement.open_dialogue_question = {
        "prompt": "Which detail should I use?", "answer_kind": "detail",
        "expected_slot": "detail"}
    respond(replacement, "Who created Python?")
    require(replacement.open_dialogue_question is None,
            "a fresh question did not supersede the prior QUD")

    # Older dialogue state remains readable without inventing an open question.
    old = CRMSDialogue(kb)
    with tempfile.TemporaryDirectory(prefix="crms-open-qud-legacy-") as folder:
        state_path = Path(folder) / "dialogue.json"
        old.save(str(state_path))
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload["format_version"] = 14
        payload.pop("open_dialogue_question")
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        restored = CRMSDialogue.load(kb, str(state_path))
        require(restored.open_dialogue_question is None,
                "legacy state did not default to no open question")
        payload["format_version"] = 14
        payload["open_dialogue_question"] = {
            "prompt": "Which detail?", "answer_kind": []}
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            CRMSDialogue.load(kb, str(state_path))
        except ValueError:
            pass
        else:
            raise SystemExit("malformed open-question state was accepted")

        payload["format_version"] = 14
        payload["open_dialogue_question"] = {
            "prompt": "What time should I use?", "answer_kind": "detail"}
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        migrated = CRMSDialogue.load(kb, str(state_path))
        require(migrated.open_dialogue_question["expected_slot"] == "date_time",
                "format 14 open question did not migrate its expected slot")

        payload["format_version"] = 15
        payload["open_dialogue_question"] = {
            "prompt": "What time should I use?", "answer_kind": "detail",
            "expected_slot": "date_time"}
        payload.pop("session_slots", None)
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        migrated_slots = CRMSDialogue.load(kb, str(state_path))
        require(migrated_slots.session_slots == {},
                "format 15 state did not migrate without session slot values")

        payload["format_version"] = 16
        payload["open_dialogue_question"] = {
            "prompt": "What time?", "answer_kind": "detail",
            "expected_slot": "not-a-slot"}
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            CRMSDialogue.load(kb, str(state_path))
        except ValueError:
            pass
        else:
            raise SystemExit("unknown expected slot was accepted")

        payload["format_version"] = 16
        payload["open_dialogue_question"] = {
            "prompt": "Where?", "answer_kind": "detail",
            "expected_slot": "location"}
        payload["session_slots"] = {
            "location": {"value": "Paris", "question": "Where?", "extra": True}}
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            CRMSDialogue.load(kb, str(state_path))
        except ValueError:
            pass
        else:
            raise SystemExit("malformed session task slot was accepted")

    print("open assistant-question context, persistence, supersession, and fact isolation: PASS")


if __name__ == "__main__":
    main()

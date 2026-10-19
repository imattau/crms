"""Keep a bounded, inspectable active user task in session dialogue state."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue
from crms_dialogue_intent import (CRMSDialogueIntentModel,
                                  empty_dialogue_intent_memory)
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def knowledge() -> CRMSKnowledgeBase:
    result = CRMSKnowledgeBase()
    result.add_fact("Ada Lovelace", "wrote", "the first algorithm", "a.txt")
    result.teach_question(
        "Who wrote the first algorithm?", relation="wrote",
        answer_field="subject", bound_entity="the first algorithm",
        answer="Ada Lovelace")
    return result


def main() -> None:
    kb = knowledge()
    dialogue = CRMSDialogue(kb)
    answer = respond(dialogue, "Who wrote the first algorithm?")
    require(answer.status == "answered"
            and answer.intent_hypothesis is not None
            and answer.intent_hypothesis.task_intent == "seek-information"
            and dialogue.active_task_intent == "seek-information",
            f"selected information goal was not retained: {answer}")
    require("task_in_progress" in dialogue.intent_context()[0]
            and dialogue.intent_trace[-1]["basis"]
            == answer.intent_hypothesis.basis,
            "active task context or its decision provenance was not exposed")

    memory = empty_dialogue_intent_memory()
    memory["builtin_policy"].append({
        "policy_id": "task-continuation-context-v1",
        "dialogue_act": "continuation-request",
        "task_intent": "continue-current-task",
        "surface_patterns": ["Continue this thread please"],
        "context_predicates": ["task_in_progress"],
        "predecessor_act": None,
        "runtime_route": "elaboration",
    })
    contextual = CRMSDialogue(
        kb, intent_model=CRMSDialogueIntentModel(memory))
    no_context_hypothesis = classify_user_intent(
        contextual, "Continue this thread please")
    require(no_context_hypothesis is None,
            "context-only policy matched without an active task")
    contextual.active_task_intent = "seek-information"
    task_hypothesis = classify_user_intent(
        contextual, "Continue this thread please")
    require(task_hypothesis is not None
            and task_hypothesis.basis == "portable_dialogue_model"
            and task_hypothesis.matched_frame == "task-continuation-context-v1"
            and task_hypothesis.runtime_route == "elaboration",
            "active task context did not license its contextual dialogue frame")

    # Social turns do not erase the current task; an explicit end does.
    respond(dialogue, "Thanks")
    require(dialogue.active_task_intent == "seek-information"
            and dialogue.intent_trace[-1]["task_intent"] == "social-contact",
            "a social turn erased the active task or was absent from the trace")
    dialogue.clear()
    require(dialogue.active_task_intent == "seek-information",
            "clear() erased session task context that reset_history owns")
    respond(dialogue, "Goodbye")
    require(dialogue.active_task_intent is None,
            "an explicit end-interaction intent left the task active")

    # Bounded trace and explicit full reset.
    for _ in range(18):
        respond(dialogue, "Who wrote the first algorithm?")
    require(len(dialogue.intent_trace) == 12,
            f"intent trace exceeded its bound: {len(dialogue.intent_trace)}")
    dialogue.reset_history()
    require(not dialogue.intent_trace and dialogue.active_task_intent is None
            and dialogue.last_intent_hypothesis is None,
            "reset_history left user-intent state behind")

    # Persistence, v12 migration, and malformed-state rejection.
    live = CRMSDialogue(kb)
    respond(live, "Who wrote the first algorithm?")
    with tempfile.TemporaryDirectory(prefix="crms-intent-context-") as folder:
        state = Path(folder) / "dialogue.json"
        live.save(str(state))
        payload = json.loads(state.read_text(encoding="utf-8"))
        require(payload["format_version"] == 14
                and payload["active_task_intent"] == "seek-information"
                and len(payload["intent_trace"]) == 1,
                "saved state omitted active task or intent trace")
        restored = CRMSDialogue.load(kb, str(state))
        require(restored.active_task_intent == live.active_task_intent
                and restored.intent_trace == live.intent_trace
                and "task_in_progress" in restored.intent_context()[0],
                "intent context did not survive save and reload")

        old = dict(payload)
        old["format_version"] = 12
        old.pop("intent_trace")
        old.pop("active_task_intent")
        state.write_text(json.dumps(old), encoding="utf-8")
        legacy = CRMSDialogue.load(kb, str(state))
        require(legacy.active_task_intent is None and not legacy.intent_trace,
                "version-12 dialogue state did not load with empty intent context")

        payload["active_task_intent"] = "unlicensed-side-effect"
        state.write_text(json.dumps(payload), encoding="utf-8")
        try:
            CRMSDialogue.load(kb, str(state))
        except ValueError:
            pass
        else:
            raise AssertionError("unknown active intent was accepted from saved state")

    print("selected intent updates bounded active-task context: PASS")
    print("active task context licenses matching portable dialogue frame: PASS")
    print("social turns retain it; explicit close and reset clear it: PASS")
    print("versioned persistence, v12 migration, and tamper rejection: PASS")


if __name__ == "__main__":
    main()

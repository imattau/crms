"""Use only licensed portable dialogue frames whose context predicates match."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue
from crms_dialogue_intent import (CRMSDialogueIntentModel,
                                  empty_dialogue_intent_memory)
from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_package import export_model_database


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def memory() -> dict:
    payload = empty_dialogue_intent_memory()
    payload["builtin_policy"].append({
        "policy_id": "extended-greeting-v1",
        "dialogue_act": "greeting",
        "task_intent": "social-contact",
        "surface_patterns": ["Greetings and salutations"],
        "context_predicates": ["conversation_opening"],
        "predecessor_act": None,
        "runtime_route": "greeting",
    })
    payload["learned_frames"].append({
        "frame_id": "contextual-elaboration-v1",
        "dialogue_act": "continuation-request",
        "task_intent": "continue-current-task",
        "surface_patterns": ["Would you expand a little more please"],
        "context_predicates": ["current_topic_available"],
        "predecessor_act": "answer",
        "source_citations": ["dialogue-source-a#turn=4",
                             "dialogue-source-b#turn=9"],
        "status": "heldout-validated",
        "validation": {
            "status": "heldout-validated",
            "train_conversation_ids": ["dialogue-a", "dialogue-c"],
            "holdout_conversation_ids": ["dialogue-b"],
            "reviewer_count": 2,
            "metrics": {"intent_accuracy": 1.0},
        },
        "runtime_route": "elaboration",
    })
    payload["learned_frames"].append({
        "frame_id": "unvalidated-elaboration-v1",
        "dialogue_act": "continuation-request",
        "task_intent": "continue-current-task",
        "surface_patterns": ["please continue now"],
        "context_predicates": [],
        "predecessor_act": None,
        "source_citations": ["dialogue-source-c#turn=2"],
        "status": "train-only",
        "validation": None,
        "runtime_route": "elaboration",
    })
    return payload


def main() -> None:
    model = CRMSDialogueIntentModel(memory())
    knowledge = CRMSKnowledgeBase()
    knowledge.add_fact("Ada Lovelace", "wrote", "the first algorithm", "source-a")

    no_context = CRMSDialogue(knowledge, intent_model=model)
    phrase = "Would you expand a little more please"
    no_context_hypothesis = classify_user_intent(no_context, phrase)
    require(no_context_hypothesis is None
            or no_context_hypothesis.basis != "portable_dialogue_model",
            "context-dependent frame selected without a current topic")
    require(model.resolve("please continue now", context=set(),
                          predecessor_act=None) is None,
            "train-only frame affected runtime routing")
    no_topic_turn = respond(no_context, phrase)
    require(no_topic_turn.intent_hypothesis is None
            and no_topic_turn.status != "elaborated",
            "unlicensed contextual frame changed the no-context route")

    contextual = CRMSDialogue(knowledge, intent_model=model)
    contextual.last_entity = "Ada Lovelace"
    contextual.history.append({"act": "question", "utterance": "Who wrote it?",
                               "status": "answered"})
    turn = respond(contextual, phrase.upper() + "!")
    hypothesis = turn.intent_hypothesis
    require(turn.status == "elaborated"
            and "Ada Lovelace — wrote → the first algorithm" in turn.text
            and hypothesis is not None
            and hypothesis.decision == "selected"
            and hypothesis.matched_frame == "contextual-elaboration-v1"
            and hypothesis.basis == "portable_dialogue_model"
            and hypothesis.evidence_refs == (
                "dialogue-source-a#turn=4", "dialogue-source-b#turn=9")
            and hypothesis.runtime_route == "elaboration",
            f"validated contextual frame did not route or cite its basis: {turn}")

    wrong_predecessor = CRMSDialogue(knowledge, intent_model=model)
    wrong_predecessor.last_entity = "Ada Lovelace"
    wrong_predecessor.history.append({
        "act": "question", "utterance": "Did I ask for something else?",
        "status": "ambiguous"})
    wrong_predecessor_intent = classify_user_intent(wrong_predecessor, phrase)
    require(wrong_predecessor_intent is None
            or wrong_predecessor_intent.basis != "portable_dialogue_model",
            "context frame ignored its predecessor condition")

    # Conflicting licensed readings for the same wording and context must be
    # surfaced as ambiguity, never silently discarded or routed by tie-break.
    conflicting_memory = empty_dialogue_intent_memory()
    conflicting_memory["builtin_policy"].extend((
        {
            "policy_id": "continue-reading-a",
            "dialogue_act": "social",
            "task_intent": "social-contact",
            "surface_patterns": ["Keep this thread moving"],
            "context_predicates": [],
            "predecessor_act": None,
            "runtime_route": "reaction",
        },
        {
            "policy_id": "continue-reading-b",
            "dialogue_act": "continuation-request",
            "task_intent": "continue-current-task",
            "surface_patterns": ["Keep this thread moving"],
            "context_predicates": [],
            "predecessor_act": None,
            "runtime_route": "elaboration",
        },
    ))
    conflicting = CRMSDialogue(
        knowledge, intent_model=CRMSDialogueIntentModel(conflicting_memory))
    ambiguous = classify_user_intent(conflicting, "Keep this thread moving")
    require(ambiguous is not None
            and ambiguous.decision == "ambiguous"
            and ambiguous.dialogue_act == "uncertain"
            and ambiguous.basis == "portable_dialogue_model"
            and ambiguous.runtime_route is None
            and len(ambiguous.alternatives) == 2,
            f"conflicting licensed readings were not preserved safely: {ambiguous}")
    route_options = tuple(
        item.rsplit("route ", 1)[1].rstrip(")")
        for item in ambiguous.alternatives)
    prompt_dialogue = CRMSDialogue(
        knowledge, intent_model=CRMSDialogueIntentModel(conflicting_memory))
    prompt = respond(prompt_dialogue, "Keep this thread moving")
    require(prompt.status == "clarify"
            and "Say yes" in prompt.text and "or no" in prompt.text
            and len(prompt_dialogue.offers) == 1
            and prompt_dialogue.offers[0]["kind"] == "intent_choice",
            f"ambiguous routes did not ask a bounded clarification: {prompt}")
    yes_dialogue = CRMSDialogue(
        knowledge, intent_model=CRMSDialogueIntentModel(conflicting_memory))
    respond(yes_dialogue, "Keep this thread moving")
    yes_route = respond(yes_dialogue, "yes")
    require(yes_route.intent_hypothesis is not None
            and yes_route.intent_hypothesis.runtime_route == route_options[0]
            and yes_route.intent_hypothesis.decision == "selected",
            f"yes did not select the first licensed route: {yes_route}")
    no_dialogue = CRMSDialogue(
        knowledge, intent_model=CRMSDialogueIntentModel(conflicting_memory))
    respond(no_dialogue, "Keep this thread moving")
    no_route = respond(no_dialogue, "no")
    require(no_route.intent_hypothesis is not None
            and no_route.intent_hypothesis.runtime_route == route_options[1]
            and no_route.intent_hypothesis.decision == "selected",
            f"no did not select the alternate licensed route: {no_route}")

    with tempfile.TemporaryDirectory(prefix="crms-intent-resolution-") as temporary:
        root = Path(temporary)
        knowledge.save(root / "knowledge.json")
        (root / "dialogue-intent.json").write_text(
            json.dumps(memory(), ensure_ascii=False), encoding="utf-8")
        CRMSModel().save(root / "rules.json")
        portable_model = export_model_database(
            root / "model.sqlite", knowledge=root / "knowledge.json",
            rules=root / "rules.json", dialogue=root / "dialogue-intent.json")
        state_path = root / "dialogue-state.json"
        contextual.save(str(state_path))
        restored = CRMSDialogue.load(
            knowledge, str(state_path), intent_model=model)
        require(restored.last_intent_hypothesis is not None
                and restored.last_intent_hypothesis.evidence_refs
                == hypothesis.evidence_refs
                and restored.last_intent_hypothesis.runtime_route == "elaboration",
                "portable intent evidence did not survive dialogue-state reload")

        state = json.loads(state_path.read_text(encoding="utf-8"))
        old_intent = state["last_intent_hypothesis"]
        old_intent.pop("evidence_refs")
        old_intent.pop("runtime_route")
        state_path.write_text(json.dumps(state), encoding="utf-8")
        legacy_state = CRMSDialogue.load(
            knowledge, str(state_path), intent_model=model)
        require(legacy_state.last_intent_hypothesis is not None
                and legacy_state.last_intent_hypothesis.evidence_refs == ()
                and legacy_state.last_intent_hypothesis.runtime_route is None,
                "pre-model intent hypotheses no longer load as legacy state")

        command = [sys.executable, str(PROJECT / "crms_chat.py"),
                   "--model-db", str(portable_model),
                   "--dialogue-state", str(root / "chat-state.json"),
                   "--feedback-db", str(root / "feedback.sqlite3")]
        chat = subprocess.run(
            command, input="Greetings and salutations\n/intent\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=30)
        require(chat.returncode == 0
                and "Hello. CRMS has" in chat.stdout
                and '"basis": "portable_dialogue_model"' in chat.stdout
                and '"matched_frame": "extended-greeting-v1"' in chat.stdout,
                f"interactive chat did not use its dialogue model: "
                f"{chat.stdout}\n{chat.stderr}")

        conflict_model_path = root / "conflicting-dialogue-intent.json"
        conflict_model_path.write_text(
            json.dumps(conflicting_memory), encoding="utf-8")
        conflict_chat = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--dialogue-model", str(conflict_model_path),
             "--knowledge", str(root / "knowledge.json"),
             "--rules", str(root / "conflict-rules.json"),
             "--dialogue-state", str(root / "conflict-state.json"),
             "--feedback-db", str(root / "conflict-feedback.sqlite3")],
            input="Keep this thread moving\nyes\n/intent\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=30)
        require(conflict_chat.returncode == 0
                and "Say yes for" in conflict_chat.stdout
                and "Which entity with accepted facts" in conflict_chat.stdout
                and '"matched_frame": "ambiguous-portable-frames"'
                in conflict_chat.stdout
                and '"runtime_route": "elaboration"' in conflict_chat.stdout,
                f"interactive chat did not clarify and route the selected intent: "
                f"{conflict_chat.stdout}\n{conflict_chat.stderr}")

    print("same elaboration wording abstains without its required context: PASS")
    print("validated frame requires context/predecessor and normalizes case: PASS")
    print("candidate/train-only frame has no runtime effect: PASS")
    print("conflicting frames ask for clarification; yes/no selects only licensed routes: PASS")
    print("chat routes the selected frame; model basis and legacy state load: PASS")


if __name__ == "__main__":
    main()

"""Bare acknowledgements must respect an open answer-choice context."""

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


def make_ambiguous_knowledge() -> CRMSKnowledgeBase:
    knowledge = CRMSKnowledgeBase()
    knowledge.add_fact("Ada Lovelace", "designed", "the Analytical Engine", "a")
    knowledge.add_fact("Ada Lovelace", "designed", "the Difference Engine", "b")
    knowledge.teach_question(
        "What did Ada Lovelace design?", relation="designed",
        answer_field="object", bound_entity="Ada Lovelace",
        answer="the Analytical Engine")
    knowledge.teach_question(
        "What did Ada Lovelace design?", relation="designed",
        answer_field="object", bound_entity="Ada Lovelace",
        answer="the Difference Engine")
    return knowledge


def main() -> None:
    knowledge = make_ambiguous_knowledge()
    dialogue = CRMSDialogue(knowledge)
    initial = dialogue.turn("What did Ada Lovelace design?")
    require(initial.status == "ambiguous" and dialogue.pending_result is not None,
            f"test setup did not create a pending choice: {initial}")

    confirmation = respond(dialogue, "yes")
    require(confirmation.status == "ambiguous"
            and dialogue.pending_result is not None
            and "does not identify" in confirmation.text,
            "bare yes consumed a pending clarification")
    require(confirmation.intent_hypothesis is not None
            and confirmation.intent_hypothesis.dialogue_act == "answer-clarification"
            and confirmation.intent_hypothesis.task_intent == "resolve-ambiguity"
            and confirmation.intent_hypothesis.decision == "ambiguous"
            and "pending_candidate_choice" in
            confirmation.intent_hypothesis.context_predicates,
            "pending yes did not expose its contextual intent hypothesis")
    polite_confirmation = respond(dialogue, "Yes, please.")
    require(polite_confirmation.status == "ambiguous"
            and dialogue.pending_result is not None,
            "polite confirmation consumed a pending clarification")
    acknowledgement = respond(dialogue, "Okay")
    require(acknowledgement.status == "ambiguous"
            and dialogue.pending_result is not None
            and "does not identify" in acknowledgement.text,
            "generic acknowledgement bypassed an open clarification")
    require(acknowledgement.intent_hypothesis is not None
            and acknowledgement.intent_hypothesis.dialogue_act
            == "acknowledgement"
            and acknowledgement.intent_hypothesis.task_intent
            == "resolve-ambiguity"
            and acknowledgement.intent_hypothesis.decision == "ambiguous",
            "receipt during a choice was not distinguished from confirmation")
    pending_why = respond(dialogue, "Why?")
    require(pending_why.status == "ambiguous"
            and pending_why.intent_hypothesis is not None
            and pending_why.intent_hypothesis.task_intent == "seek-information"
            and pending_why.intent_hypothesis.decision == "ambiguous"
            and "pending_candidate_choice" in
            pending_why.intent_hypothesis.context_predicates,
            "why-follow-up ignored the unresolved candidate context")
    selection = respond(dialogue, "Yeah, the second option please.")
    require(selection.status == "answered"
            and selection.response is not None
            and selection.response.answer == "the Difference Engine"
            and dialogue.pending_result is None,
            f"contextual ordinal selection failed after yes: {selection}")

    corrected_choice_dialogue = CRMSDialogue(knowledge)
    corrected_choice_dialogue.turn("What did Ada Lovelace design?")
    corrected_choice = respond(
        corrected_choice_dialogue, "No, I meant the Difference Engine.")
    require(corrected_choice.status == "answered"
            and corrected_choice.response is not None
            and corrected_choice.response.answer == "the Difference Engine"
            and corrected_choice_dialogue.pending_result is None,
            "explicit correction did not resolve the open candidate choice")
    require(corrected_choice.intent_hypothesis is not None
            and corrected_choice.intent_hypothesis.decision == "selected"
            and corrected_choice.intent_hypothesis.selected_value
            == "the Difference Engine"
            and corrected_choice.intent_hypothesis.basis
            == "hand_checked_runtime_rule",
            "candidate selection did not expose its inspectable intent decision")
    explanation = respond(corrected_choice_dialogue, "How do you know that?")
    require(explanation.intent_hypothesis is not None
            and explanation.intent_hypothesis.task_intent == "seek-information"
            and explanation.intent_hypothesis.decision == "selected"
            and "previous_grounded_question" in
            explanation.intent_hypothesis.context_predicates,
            "explanation follow-up did not use the grounded answer context")
    elaboration = respond(corrected_choice_dialogue, "Tell me more.")
    require(elaboration.intent_hypothesis is not None
            and elaboration.intent_hypothesis.task_intent
            == "continue-current-task"
            and "current_topic_available" in
            elaboration.intent_hypothesis.context_predicates,
            "continuation request did not use the current topic")

    unanchored = respond(CRMSDialogue(knowledge), "Nope.")
    require(unanchored.status == "clarify"
            and "don't have an open yes/no question" in unanchored.text,
            f"bare no entered ordinary retrieval without context: {unanchored}")
    require(unanchored.intent_hypothesis is not None
            and unanchored.intent_hypothesis.decision == "ambiguous"
            and unanchored.intent_hypothesis.dialogue_act == "uncertain"
            and unanchored.intent_hypothesis.task_intent is None
            and "no_open_yes_no_question" in
            unanchored.intent_hypothesis.context_predicates,
            "unanchored yes/no did not report the missing context")

    mixed = respond(CRMSDialogue(knowledge),
                    "Hello, what did Ada Lovelace design?")
    require(mixed.intent_hypothesis is not None
            and mixed.intent_hypothesis.dialogue_act == "question"
            and mixed.intent_hypothesis.task_intent == "seek-information"
            and mixed.intent_hypothesis.matched_frame
            == "greeting-plus-content-question",
            "mixed greeting/question did not select the task intent")
    for question, frame in (
            ("Who designed the Analytical Engine?", "wh-question"),
            ("Did Ada Lovelace design the Analytical Engine?",
             "yes-no-question")):
        hypothesis = classify_user_intent(CRMSDialogue(knowledge), question)
        require(hypothesis is not None
                and hypothesis.dialogue_act == "question"
                and hypothesis.task_intent == "seek-information"
                and hypothesis.decision == "selected"
                and hypothesis.matched_frame == frame,
                f"content question did not receive a bounded intent: {question}")
    greeting_question = classify_user_intent(CRMSDialogue(knowledge),
                                              "How are you?")
    require(greeting_question is not None
            and greeting_question.dialogue_act == "greeting"
            and greeting_question.task_intent == "social-contact",
            "social greeting was misclassified as a content question")
    information_request = classify_user_intent(
        CRMSDialogue(knowledge), "Can you tell me which engine Ada designed?")
    require(information_request is not None
            and information_request.dialogue_act == "request-action"
            and information_request.task_intent == "seek-information"
            and information_request.matched_frame == "modal-request",
            "information request was collapsed into a generic yes/no question")
    action_request = classify_user_intent(
        CRMSDialogue(knowledge), "Could you reserve a table for two?")
    require(action_request is not None
            and action_request.dialogue_act == "request-action"
            and action_request.task_intent == "make-reservation",
            "reservation action request did not receive its specific task intent")
    bare_yes = classify_user_intent(CRMSDialogue(knowledge), "Yes")
    require(bare_yes is not None and bare_yes.decision == "ambiguous"
            and bare_yes.task_intent is None,
            "bare yes was misclassified as a content question")
    content_question = respond(CRMSDialogue(knowledge),
                               "What did Ada Lovelace design?")
    require(content_question.status == "ambiguous"
            and content_question.intent_hypothesis is not None
            and content_question.intent_hypothesis.dialogue_act == "question"
            and content_question.intent_hypothesis.task_intent
            == "seek-information"
            and content_question.intent_hypothesis.matched_frame == "wh-question",
            "runtime content question did not carry its intent hypothesis")
    unanchored_explanation = respond(CRMSDialogue(knowledge), "Why?")
    require(unanchored_explanation.intent_hypothesis is not None
            and unanchored_explanation.intent_hypothesis.dialogue_act == "uncertain"
            and unanchored_explanation.intent_hypothesis.task_intent is None
            and "no_previous_grounded_answer" in
            unanchored_explanation.intent_hypothesis.context_predicates,
            "unanchored why-follow-up invented a task context")

    with tempfile.TemporaryDirectory(prefix="crms-contextual-intent-") as folder:
        root = Path(folder)
        knowledge.save(root / "knowledge.json")
        CRMSResearchIndex().save(root / "index.json")
        command = [
            sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(root / "index.json"),
            "--rules", str(root / "rules.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        completed = subprocess.run(
            command,
            input=("What did Ada Lovelace design?\nokay\nsecond option please\n"
                   "/intent\nGoodbye\n"),
            text=True, capture_output=True, check=True, timeout=30)
        require("does not identify one of the supported answers" in completed.stdout,
                f"terminal did not explain the unresolved yes: {completed.stdout}")
        require("the Difference Engine" in completed.stdout
                and "CRMS state saved. Goodbye." in completed.stdout,
                f"terminal did not keep and resolve the pending choice: {completed.stdout}")
        require("Last turn's intent hypothesis" in completed.stdout
                and '"task_intent": "resolve-ambiguity"' in completed.stdout
                and '"selected_value": "the Difference Engine"' in completed.stdout
                and "Active goal: seek-information" in completed.stdout
                and "Current subgoal: resolve-ambiguity" in completed.stdout
                and "Recent intent trace:" in completed.stdout
                and "hand-checked runtime rules; not learned" in completed.stdout,
                f"/intent did not expose the selected contextual intent: {completed.stdout}")
        restarted = subprocess.run(
            command, input="/intent\nGoodbye\n", text=True,
            capture_output=True, check=True, timeout=30)
        require("Last turn's intent hypothesis" in restarted.stdout
                and '"selected_value": "the Difference Engine"' in restarted.stdout,
                f"saved intent hypothesis was lost on restart: {restarted.stdout}")
        state_path = root / "dialogue.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        legacy_state = {key: value for key, value in state.items()
                        if key not in {"last_intent_hypothesis", "intent_trace",
                                       "active_task_intent"}}
        legacy_state["format_version"] = 8
        state_path.write_text(json.dumps(legacy_state), encoding="utf-8")
        legacy_dialogue = CRMSDialogue.load(knowledge, str(state_path))
        require(legacy_dialogue.last_intent_hypothesis is None,
                "legacy dialogue state did not load without an intent hypothesis")
        state_path.write_text(json.dumps(state), encoding="utf-8")
        state["last_intent_hypothesis"]["basis"] = "unverified"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        try:
            CRMSDialogue.load(knowledge, str(state_path))
        except ValueError:
            pass
        else:
            raise SystemExit("tampered intent-state basis was trusted")

    print("yes/no with an open choice preserves clarification state: PASS")
    print("ordinal selection after acknowledgement resolves the original candidates: PASS")
    print("explicit 'I meant' correction resolves the open candidate choice: PASS")
    print("unanchored yes/no asks for context instead of querying the corpus: PASS")
    print("terminal interaction retains context across the clarification sequence: PASS")
    print("/intent exposes the last hypothesis and active task context: PASS")
    print("saved intent hypothesis survives a chat restart: PASS")
    print("legacy dialogue state loads without intent metadata: PASS")
    print("tampered saved intent hypothesis is rejected: PASS")


if __name__ == "__main__":
    main()

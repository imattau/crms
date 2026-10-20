"""Check generic task-goal and contextual slot classification.

These are deterministic runtime checks for the narrow failure found in the
Taskmaster movie-ticket dialogue pilot. They do not measure general intent
accuracy or license the rules on their own.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent
from crms_dialogue import CRMSDialogue, DialogueTurn, infer_open_question_slot
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def classify(text: str, dialogue: CRMSDialogue | None = None):
    return classify_user_intent(dialogue or CRMSDialogue(CRMSKnowledgeBase()), text)


def main() -> None:
    action_requests = (
        "I want movie tickets.",
        "I need to get tickets.",
        "I'd like to get movie tickets.",
        "I would like to see a movie.",
        "I wanted to see a movie with my friend.",
        "I'm looking to book some movie tickets.",
        "Could you help me with getting movie tickets?",
        "Can I get a movie ticket?",
    )
    for text in action_requests:
        hypothesis = classify(text)
        require(hypothesis is not None
                and hypothesis.dialogue_act == "request-action"
                and hypothesis.task_intent == "other-task"
                and hypothesis.goal_intent == "other-task",
                f"explicit task request did not establish a broad task goal: {text!r}: {hypothesis}")

    information_requests = (
        "I want to know how long the movie is.",
        "I need to know what time it starts.",
    )
    for text in information_requests:
        hypothesis = classify(text)
        require(hypothesis is not None
                and hypothesis.task_intent == "seek-information"
                and hypothesis.goal_intent == "seek-information",
                f"information-seeking wording was mistaken for task execution: {text!r}: {hypothesis}")

    availability = classify(
        "Looking to see if Cold Pursuit is playing anywhere near Vail, Colorado.")
    require(availability is not None
            and availability.dialogue_act == "request-action"
            and availability.task_intent == "check-availability"
            and availability.goal_intent == "check-availability",
            f"explicit availability request was not distinguished: {availability}")

    availability_state = CRMSDialogue(CRMSKnowledgeBase())
    availability_state.active_task_intent = "check-availability"
    availability_question = classify(
        "What showtimes do they have available tomorrow?", availability_state)
    require(availability_question is not None
            and availability_question.task_intent == "check-availability",
            "showtime question did not become an availability subgoal")

    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    request = classify("I need movie tickets.", dialogue)
    require(request is not None and request.goal_intent == "other-task",
            "initial request did not establish a task goal")
    dialogue.record_turn("I need movie tickets.", request.dialogue_act,
                         DialogueTurn("intent-hypothesis", "", ""), request)
    require(dialogue.active_task_intent == "other-task",
            "broad task goal was not retained in dialogue state")

    question_cases = (
        ("What movie would you like to see?", "detail", "The LEGO Movie 2."),
        ("How many tickets do you need?", "quantity", "Two, please."),
        ("At what time would you like to go?", "date_time", "As soon as possible."),
        ("Which one would you prefer?", "choice", "The first one."),
    )
    for prompt, expected_slot, answer in question_cases:
        answer_kind = "yes-no" if prompt.strip().endswith("?") and prompt.lower().startswith(("is ", "are ", "do ", "does ", "would ", "will ", "can ")) else "detail"
        slot = infer_open_question_slot(prompt, answer_kind)
        if expected_slot == "detail":
            require(slot == "detail", f"unexpected slot for {prompt!r}: {slot}")
        else:
            require(slot == expected_slot,
                    f"expected {expected_slot} for {prompt!r}, got {slot}")
        dialogue.open_dialogue_question = {
            "prompt": prompt, "answer_kind": answer_kind,
            "expected_slot": slot,
        }
        hypothesis = classify(answer, dialogue)
        expected_task = ("resolve-ambiguity" if expected_slot == "choice"
                         else "provide-constraint")
        expected_act = ("answer-clarification" if expected_slot == "choice"
                        else "provide-information")
        require(hypothesis is not None
                and hypothesis.dialogue_act == expected_act
                and hypothesis.task_intent == expected_task,
                f"answer to task slot was mistyped: {answer!r}: {hypothesis}")
        require(dialogue.active_task_intent == "other-task",
                "task-slot response replaced the broad task goal")
        dialogue.record_turn(answer, hypothesis.dialogue_act,
                             DialogueTurn("intent-hypothesis", "", ""),
                             hypothesis)
        require(dialogue.active_task_intent == "other-task"
                and dialogue.active_task_subgoal == (
                    "provide-constraint" if expected_slot != "choice"
                    else "resolve-ambiguity"),
                "task subgoal was not preserved under the broad goal")

    for prompt in ("Will that work for you?", "Would you like to purchase?"):
        require(infer_open_question_slot(prompt, "yes-no") == "confirmation",
                f"proposal question was not typed as confirmation: {prompt!r}")
        dialogue.open_dialogue_question = {
            "prompt": prompt, "answer_kind": "yes-no",
            "expected_slot": "confirmation",
        }
        hypothesis = classify("Yes, please.", dialogue)
        require(hypothesis is not None
                and hypothesis.dialogue_act == "confirm"
                and hypothesis.task_intent == "resolve-ambiguity"
                and hypothesis.goal_intent == "other-task",
                f"bare acceptance did not resolve the proposal: {prompt!r}: {hypothesis}")

    no_context = classify("Two, please.", CRMSDialogue(CRMSKnowledgeBase()))
    require(no_context is None,
            "a slot value without a pending question was given an invented task context")

    long_reply = CRMSDialogue(CRMSKnowledgeBase())
    long_reply.active_task_intent = "other-task"
    long_reply.open_dialogue_question = {
        "prompt": "How many tickets did you need?",
        "answer_kind": "detail", "expected_slot": "quantity",
    }
    bundled = classify(
        "Just one for myself, looking for anything in the afternoon and in "
        "New York City area. Whatever you can find closest to city center.",
        long_reply)
    require(bundled is not None
            and bundled.dialogue_act == "provide-information"
            and bundled.task_intent == "provide-constraint",
            f"long multi-slot answer was dropped: {bundled}")

    task_change = CRMSDialogue(CRMSKnowledgeBase())
    task_change.active_task_intent = "other-task"
    task_change.open_dialogue_question = {
        "prompt": "What movie would you like to see?",
        "answer_kind": "detail", "expected_slot": "detail",
    }
    changed_goal = classify(
        "I'd like to make a dinner reservation.", task_change)
    require(changed_goal is not None
            and changed_goal.task_intent == "make-reservation",
            "explicit new task was swallowed as an answer to the open slot")
    print("PASS: explicit task goals, information requests, contextual constraints, and proposal confirmations")


if __name__ == "__main__":
    main()

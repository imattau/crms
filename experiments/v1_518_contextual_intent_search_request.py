"""Keep information-seeking goals distinct from action requests in context."""

from __future__ import annotations

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_user_intent
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase, QuestionResult


PROJECT = Path(__file__).resolve().parents[1]
REPORT = PROJECT / "experiments" / "reports" / "v1_518_contextual_intent_search_request.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def new_dialogue() -> CRMSDialogue:
    return CRMSDialogue(CRMSKnowledgeBase())


def snapshot(hypothesis):
    if hypothesis is None:
        return None
    return {
        "dialogue_act": hypothesis.dialogue_act,
        "task_intent": hypothesis.task_intent,
        "goal_intent": hypothesis.goal_intent,
        "decision": hypothesis.decision,
        "matched_frame": hypothesis.matched_frame,
        "selected_value": hypothesis.selected_value,
    }


def main() -> None:
    cases = []
    search_request = (
        "I need to find a Chinese restaurant. I'm in San Francisco, California.")
    search = classify_user_intent(new_dialogue(), search_request)
    cases.append({"case": "search goal", "utterance": search_request,
                  "context": "no active task",
                  "expected": {"dialogue_act": "request-action",
                               "task_intent": "seek-information",
                               "goal_intent": "seek-information"},
                  "actual": snapshot(search)})
    require(search is not None
            and search.dialogue_act == "request-action"
            and search.task_intent == "seek-information"
            and search.goal_intent == "seek-information",
            f"restaurant search was not recognized as information seeking: {search}")

    action_request = "I need to build a restaurant reservation system."
    action = classify_user_intent(new_dialogue(), action_request)
    cases.append({"case": "action goal contrast", "utterance": action_request,
                  "context": "no active task",
                  "expected": {"dialogue_act": "request-action",
                               "task_intent": "other-task",
                               "goal_intent": "other-task"},
                  "actual": snapshot(action)})
    require(action is not None
            and action.dialogue_act == "request-action"
            and action.task_intent == "other-task"
            and action.goal_intent == "other-task",
            f"an explicit build task was mislabeled as information seeking: {action}")

    preference_context = new_dialogue()
    preference_context.active_task_intent = "seek-information"
    preference_context.open_dialogue_question = {
        "prompt": "What kind of restaurant would you like?",
        "answer_kind": "detail",
        "expected_slot": "cuisine",
    }
    preference = classify_user_intent(
        preference_context,
        "I would like one with a high rating. I would also like one that is "
        "portable. And I also like one that has take out.")
    cases.append({"case": "open preference slot",
                  "utterance": "I would like one with a high rating. I would also like one that is portable. And I also like one that has take out.",
                  "context": "active seek-information; awaiting cuisine/restaurant preference",
                  "expected": {"dialogue_act": "provide-information",
                               "task_intent": "provide-constraint"},
                  "actual": snapshot(preference)})
    require(preference is not None
            and preference.dialogue_act == "provide-information"
            and preference.task_intent == "provide-constraint",
            f"contextual preference answer was not treated as a constraint: {preference}")

    reservation_context = new_dialogue()
    reservation_context.active_task_intent = "seek-information"
    reservation_context.pending_result = QuestionResult(
        "ambiguous", candidates=["Cafe Birch", "Bistro Alder"])
    reservation = classify_user_intent(
        reservation_context, "Book a reservation with the second one?")
    cases.append({"case": "reservation with ordinal choice",
                  "utterance": "Book a reservation with the second one?",
                  "context": "active seek-information; two source candidates pending",
                  "expected": {"task_intent": "make-reservation",
                               "goal_intent": "make-reservation"},
                  "actual": snapshot(reservation)})
    require(reservation is not None
            and reservation.task_intent == "make-reservation"
            and reservation.goal_intent == "make-reservation",
            f"explicit reservation request was absorbed as source selection: {reservation}")

    report = {
        "experiment": "v1_518_contextual_intent_search_request",
        "source_report": "v1_462_taskmaster_fresh_dialogue_intent_holdout.json",
        "source_report_revision": "70abcd8989e94064a47bd80d4aa1d66982b1a9b6",
        "label_provenance": "Codex-authored development labels from listed Taskmaster disagreement plus contrastive controls",
        "independent_validation": False,
        "result": "4/4 targeted intent controls passed",
        "cases": cases,
        "limitations": [
            "The source Taskmaster replay was not rerun because its raw transcript input is not present in this checkout.",
            "The four controls do not estimate intent accuracy, coverage, or task completion.",
            "Taskmaster labels are not independent gold; this is a development regression only.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")

    print("PASS: 'I need to find …' is an information-seeking task")
    print("PASS: 'I need to build …' remains an action task")
    print("PASS: preferences inherit intent from the open contextual slot")
    print("PASS: a reservation request with an ordinal is not mistaken for selection")
    print("LIMIT: four Codex-labeled utterance controls; not an intent-accuracy estimate")
    print(f"REPORT: {REPORT}")


if __name__ == "__main__":
    main()

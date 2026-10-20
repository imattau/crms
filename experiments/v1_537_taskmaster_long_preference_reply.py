"""Keep a long preference answer inside the active dialogue context.

The example is a held-out Taskmaster-1 restaurant-search turn. The test checks
CRMS's live dialogue response path and guards against treating the supplied
preferences as either a new task or factual knowledge.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_conversation import classify_user_intent, respond
from crms_dialogue import CRMSDialogue, DialogueTurn
from crms_knowledge import CRMSKnowledgeBase


PROMPT = (
    "sure, let me help with that. what preferences do you have in mind "
    "for the chinese restaurants i look up?")
PREFERENCE_REPLY = (
    "I would like one with a high rating. I would also like one that is "
    "portable. And I also like one that has take out.")
NEW_TASK = (
    "I would like to write a short funny poem about dinner, with a surprising "
    "ending and a playful rhythm, rather than continue the restaurant search.")
BOOKING_REQUEST = "I would like to make a reservation at San Tung."
REPORT = PROJECT / "experiments" / "reports" / \
    "v1_537_taskmaster_long_preference_reply.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def open_preference_dialogue(*, active_task: str = "seek-information") -> CRMSDialogue:
    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    dialogue.active_task_intent = active_task
    dialogue.open_dialogue_question = {
        "prompt": PROMPT,
        "answer_kind": "detail",
        "expected_slot": "detail",
    }
    return dialogue


def main() -> None:
    dialogue = open_preference_dialogue()
    hypothesis = classify_user_intent(dialogue, PREFERENCE_REPLY)
    require(hypothesis is not None
            and hypothesis.dialogue_act == "provide-information"
            and hypothesis.task_intent == "provide-constraint"
            and hypothesis.matched_frame == "answer-to-open-dialogue-question",
            f"long preference list escaped its open prompt: {hypothesis}")

    live_dialogue = open_preference_dialogue()
    turn = respond(live_dialogue, PREFERENCE_REPLY)
    require(turn.status == "social"
            and turn.text == "Got it. I’ve noted those restaurant preferences."
            and turn.intent_hypothesis is not None
            and turn.intent_hypothesis.task_intent == "provide-constraint"
            and live_dialogue.open_dialogue_question is None
            and not live_dialogue.knowledge.facts()
            and not live_dialogue.knowledge.negative_facts(),
            f"live dialogue did not accept the preference answer safely: {turn}")

    standalone = classify_user_intent(CRMSDialogue(CRMSKnowledgeBase()),
                                      PREFERENCE_REPLY)
    require(standalone is not None and standalone.task_intent == "other-task",
            f"without the preference prompt, intent was silently reinterpreted: {standalone}")

    creative = classify_user_intent(open_preference_dialogue(), NEW_TASK)
    require(creative is not None and creative.task_intent == "other-task"
            and creative.matched_frame == "explicit-generic-task-request",
            f"an unrelated long request was absorbed as a constraint: {creative}")

    booking = classify_user_intent(open_preference_dialogue(), BOOKING_REQUEST)
    require(booking is not None and booking.task_intent == "make-reservation"
            and booking.matched_frame == "explicit-reservation-request",
            f"an explicit booking request was swallowed by preference context: {booking}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "experiment": "v1_537_taskmaster_long_preference_reply",
        "date": "2026-10-20",
        "source": {
            "dataset": "Taskmaster-1, restaurant-table test split",
            "conversation_id": "dlg-e41052fb-f4a4-4975-a198-3f668bd3f69e",
            "user_turn_index": 3,
            "source_sha256": "cd3bc4e968487315d412c044d30af2bf0a4b33c3ef8b74c589f1e1fa832bf72f",
            "label_provenance": "single Codex primary label; not independent gold",
        },
        "task": {
            "assistant_prompt": PROMPT,
            "user_reply": PREFERENCE_REPLY,
            "word_count": len(PREFERENCE_REPLY.split()),
            "expected": {"dialogue_act": "provide-information",
                         "task_intent": "provide-constraint"},
            "actual": {"dialogue_act": hypothesis.dialogue_act,
                       "task_intent": hypothesis.task_intent,
                       "frame": hypothesis.matched_frame},
        },
        "controls": {
            "same_reply_without_context": standalone.task_intent,
            "unrelated_long_creative_request": creative.task_intent,
            "explicit_booking_request": booking.task_intent,
            "preference_saved_as_fact": False,
        },
        "limitations": [
            "This repairs one long preference response in one Taskmaster conversation.",
            "The label is single-annotator and not an independent accuracy measure.",
            "It does not establish general dialogue transfer or task completion quality.",
        ],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("long preference reply uses active prompt context in live dialogue: PASS")
    print("same wording is not treated as a constraint without that context: PASS")
    print("new creative request and explicit booking request remain distinct: PASS")
    print("user preference remains dialogue context, not accepted fact: PASS")
    print("scope: one contextual intent regression from a held-out transcript")
    print("report:", REPORT)


if __name__ == "__main__":
    main()

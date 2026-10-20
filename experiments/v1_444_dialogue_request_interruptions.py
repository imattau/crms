"""Explicit new requests must interrupt, not fill, an open dialogue slot."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    for request in ("Tell me a joke", "Write a poem", "Translate hello into French"):
        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        clarification = respond(dialogue, "When was it completed?")
        require(clarification.status == "unknown"
                and dialogue.open_dialogue_question is not None
                and dialogue.open_dialogue_question["expected_slot"] == "entity",
                "pronoun question did not create an open entity slot")

        reply = respond(dialogue, request)
        require("treat that as your reply" not in reply.text.casefold()
                and reply.intent_hypothesis is not None
                and reply.intent_hypothesis.dialogue_act == "request-action",
                f"new request was consumed as a clarification answer: {reply!r}")
        require(dialogue.open_dialogue_question is None,
                "interrupted entity clarification remained active")

    # A short entity answer still fills the slot rather than being mistaken
    # for a new action request.
    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    respond(dialogue, "When was it completed?")
    answer = respond(dialogue, "Eiffel Tower")
    require(answer.intent_hypothesis is not None
            and answer.intent_hypothesis.matched_frame
                == "answer-to-open-dialogue-question"
            and answer.intent_hypothesis.selected_value == "Eiffel Tower"
            and dialogue.open_dialogue_question is None,
            f"valid entity clarification stopped working: {answer!r}")

    # A WH request embedded in a polite imperative should still reach the
    # existing fact-answer path, with the actual utterance retained in history.
    kb = CRMSKnowledgeBase()
    kb.add_fact("Guido van Rossum", "created", "Python", "fixture:python")
    for request in ("Tell me who created Python",
                    "Could you tell me who created Python?"):
        dialogue = CRMSDialogue(kb)
        reply = respond(dialogue, request)
        require(reply.status == "answered" and reply.response is not None
                and reply.response.answer == "Guido van Rossum"
                and reply.question == request
                and reply.resolved_question == "Who created Python?"
                and dialogue.history[-1]["utterance"] == request,
                f"embedded WH request missed the normal fact path: {reply!r}")

    print("three direct requests interrupt open entity clarification: PASS")
    print("valid short entity reply still fills the open slot: PASS")
    print("direct and modal embedded WH requests answer and retain original wording: PASS")


if __name__ == "__main__":
    main()

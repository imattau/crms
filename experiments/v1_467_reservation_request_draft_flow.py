"""Complete a bounded reservation-request draft through ordinary chat turns."""
from __future__ import annotations

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
    knowledge = CRMSKnowledgeBase()
    dialogue = CRMSDialogue(knowledge)

    start = respond(dialogue, "I want to make a dinner reservation.")
    require(start.status == "clarify"
            and "can't check availability or submit" in start.text
            and dialogue.active_task_intent == "make-reservation"
            and dialogue.open_dialogue_question is not None
            and dialogue.open_dialogue_question["expected_slot"]
                == "restaurant_choice",
            f"reservation request did not enter an honest draft flow: {start!r}")

    restaurant = respond(dialogue, "Nopa")
    require(restaurant.status == "clarify"
            and dialogue.session_slots["restaurant_choice"]["value"] == "Nopa"
            and dialogue.open_dialogue_question is not None
            and dialogue.open_dialogue_question["expected_slot"] == "date_time",
            f"restaurant detail was not collected or next slot was not asked: "
            f"{restaurant!r}")

    when = respond(dialogue, "Friday at 7 pm")
    require(when.status == "clarify"
            and dialogue.session_slots["date_time"]["value"] == "Friday at 7 pm"
            and dialogue.open_dialogue_question is not None
            and dialogue.open_dialogue_question["expected_slot"] == "party_size",
            f"date/time was not collected or party size was not requested: "
            f"{when!r}")

    draft = respond(dialogue, "4")
    require(draft.status == "prepared"
            and "Restaurant: Nopa" in draft.text
            and "Date/time: Friday at 7 pm" in draft.text
            and "Party size: 4" in draft.text
            and "not submitted" in draft.text
            and "No reservation has been made." in draft.text
            and draft.action is None,
            f"final draft was incomplete or implied submission: {draft!r}")
    require(not knowledge._facts,
            "user-provided booking details were inserted into factual memory")

    corrected = respond(dialogue, "Actually, change the time to Saturday at 8:30 pm.")
    require(corrected.status == "prepared"
            and "Date/time: Saturday at 8:30 pm" in corrected.text
            and "Friday at 7 pm" not in corrected.text
            and dialogue.session_slots["date_time"]["updated_by"]
                == "Actually, change the time to Saturday at 8:30 pm.",
            f"correction did not regenerate the draft from current session values: "
            f"{corrected!r}")

    with tempfile.TemporaryDirectory(prefix="crms-reservation-draft-") as folder:
        state = Path(folder) / "dialogue.json"
        dialogue.save(str(state))
        restored = CRMSDialogue.load(knowledge, str(state))
        recalled = respond(restored, "What time did I give you?")
        require("Saturday at 8:30 pm" in recalled.text
                and restored.session_slots["date_time"]["value"]
                    == "Saturday at 8:30 pm",
                f"corrected draft value did not survive save/reload: {recalled!r}")

    print("reservation request collects typed session-only details: PASS")
    print("draft remains explicit that no booking was submitted: PASS")
    print("correction regenerates the draft and survives reload: PASS")


if __name__ == "__main__":
    main()

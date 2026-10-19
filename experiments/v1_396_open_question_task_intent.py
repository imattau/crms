"""Resolve task intent for short answers using the open prompt and task state."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import (
    classify_user_intent, is_open_yes_no_prompt, respond)
from crms_dialogue import CRMSDialogue, DialogueTurn, infer_open_question_slot
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def classify(prompt: str, slot: str, active_task: str | None,
             answer: str = "Two people.", *, answer_kind: str = "detail"):
    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    dialogue.active_task_intent = active_task
    dialogue.open_dialogue_question = {
        "prompt": prompt, "answer_kind": answer_kind, "expected_slot": slot,
    }
    return classify_user_intent(dialogue, answer)


def main() -> None:
    search = classify("How many people should I search for?", "party_size",
                      "seek-information")
    require(search is not None and search.decision == "selected"
            and search.dialogue_act == "provide-information"
            and search.task_intent == "provide-constraint",
            f"search detail inherited the broad task intent: {search}")

    reservation_from_prompt = classify(
        "When would you like to make your reservation for?", "date_time",
        "seek-information", "Tonight at 5 pm.")
    require(reservation_from_prompt is not None
            and reservation_from_prompt.task_intent == "make-reservation",
            f"explicit reservation prompt did not set task phase: {reservation_from_prompt}")

    reservation_from_state = classify(
        "How many people should I plan for?", "party_size", "make-reservation")
    require(reservation_from_state is not None
            and reservation_from_state.task_intent == "make-reservation",
            f"reservation state did not persist through detail answer: {reservation_from_state}")

    restaurant_search_during_booking = classify(
        "What type of food do you like?", "cuisine", "make-reservation",
        "French food.")
    require(restaurant_search_during_booking is not None
            and restaurant_search_during_booking.dialogue_act == "provide-information"
            and restaurant_search_during_booking.task_intent == "provide-constraint",
            "restaurant-search criteria inherited the later reservation task")

    preference_detail = classify(
        "Did you have any dining requirements?", "detail", "make-reservation",
        "Outdoor seating.")
    require(preference_detail is not None
            and preference_detail.dialogue_act == "provide-information"
            and preference_detail.task_intent == "provide-constraint",
            "an open-ended restaurant preference question was left untyped")

    preference_confirmation = classify(
        "Are there any other restaurant characteristics you would like?",
        "yes_no", "seek-information",
        "Yes, I would like one that has booth, affordable dining and a waiting staff.",
        answer_kind="yes-no")
    require(preference_confirmation is not None
            and preference_confirmation.decision == "selected"
            and preference_confirmation.dialogue_act == "provide-information"
            and preference_confirmation.task_intent == "provide-constraint",
            "an affirmative preference answer with details was not kept as a constraint")

    live_preferences = CRMSDialogue(CRMSKnowledgeBase())
    live_preferences.active_task_intent = "seek-information"
    live_preferences.open_dialogue_question = {
        "prompt": "Are there any other restaurant characteristics you would like?",
        "answer_kind": "yes-no", "expected_slot": "yes_no",
    }
    preference_turn = respond(
        live_preferences,
        "Yes, I would like one that has booth, affordable dining and a waiting staff.")
    require(preference_turn.status == "social"
            and preference_turn.text
            == "Got it. I’ve noted those restaurant preferences."
            and preference_turn.intent_hypothesis is not None
            and preference_turn.intent_hypothesis.dialogue_act == "provide-information"
            and live_preferences.open_dialogue_question is None
            and live_preferences.active_task_intent == "seek-information",
            "live dialogue failed to accept preference details as a search constraint")

    search_preference = classify(
        "It would help my search if I knew your preferences.", "detail",
        "make-reservation", "Fast.")
    require(search_preference is not None
            and search_preference.dialogue_act == "provide-information"
            and search_preference.task_intent == "provide-constraint",
            "an explicit search-preference prompt inherited the booking task")

    category_prompt = "What type of restaurant are you looking for?"
    require(infer_open_question_slot(category_prompt, "detail") == "restaurant_type",
            "restaurant-category question did not receive its own typed slot")
    category_state = CRMSDialogue(CRMSKnowledgeBase())
    category_state.open_dialogue_question = {
        "prompt": category_prompt, "answer_kind": "detail",
        "expected_slot": infer_open_question_slot(category_prompt, "detail"),
    }
    require("awaiting_slot_restaurant_type" in category_state.intent_context()[0],
            "restaurant-type slot did not reach the contextual intent model")

    change_from_prompt = classify(
        "What time would you like to change your reservation to?", "date_time",
        "seek-information", "8 pm.")
    require(change_from_prompt is not None
            and change_from_prompt.task_intent == "change-reservation",
            f"explicit change prompt did not set task phase: {change_from_prompt}")

    untyped = classify("Which detail should I use?", "detail", None,
                       "A useful detail.")
    require(untyped is not None
            and untyped.task_intent == "continue-current-task",
            f"unspecified task context was over-interpreted: {untyped}")

    confirmation = classify("And you said for two people?", "confirmation",
                            "make-reservation", "Yes.", answer_kind="yes-no")
    require(confirmation is not None and confirmation.dialogue_act == "confirm"
            and confirmation.task_intent == "make-reservation",
            f"confirmation was collapsed into a generic clarification: {confirmation}")
    live_booking_confirmation = CRMSDialogue(CRMSKnowledgeBase())
    live_booking_confirmation.active_task_intent = "make-reservation"
    live_booking_confirmation.open_dialogue_question = {
        "prompt": "Should I book this now?", "answer_kind": "yes-no",
        "expected_slot": infer_open_question_slot("Should I book this now?", "yes-no"),
    }
    booking_turn = respond(live_booking_confirmation, "Yes, please.")
    require(booking_turn.intent_hypothesis is not None
            and booking_turn.intent_hypothesis.dialogue_act == "confirm"
            and booking_turn.intent_hypothesis.task_intent == "make-reservation"
            and live_booking_confirmation.open_dialogue_question is None,
            "live booking confirmation was not typed as a confirmation")
    live_summary_prompt = CRMSDialogue(CRMSKnowledgeBase())
    live_summary_prompt.turn = lambda text, **_kwargs: DialogueTurn(
        "clarify", text, text,
        text="So I have a reservation for 5 people at 8pm tonight.")
    respond(live_summary_prompt, "Can you help me with this booking?")
    require(live_summary_prompt.open_dialogue_question is not None
            and live_summary_prompt.open_dialogue_question["answer_kind"] == "yes-no"
            and live_summary_prompt.open_dialogue_question["expected_slot"]
            == "confirmation",
            "a declarative booking summary was not saved as a confirmation prompt")
    require(is_open_yes_no_prompt("And you said for two people?")
            and is_open_yes_no_prompt("Sure, did you need a reservation?")
            and is_open_yes_no_prompt("Great that's tonight?")
            and is_open_yes_no_prompt(
                "Did you have any restaurant preferences? For example, "
                "outdoor seating, full bar, etc.")
            and is_open_yes_no_prompt(
                "So I have a reservation for 5 people at 8pm tonight.")
            and infer_open_question_slot("Should I book this now?", "yes-no")
            == "confirmation",
            "contextual yes/no and booking-confirmation prompts were not typed")

    reservation_need = classify(
        "Sure, did you need a reservation?", "yes_no", "seek-information",
        "Yes.", answer_kind="yes-no")
    require(reservation_need is not None
            and reservation_need.dialogue_act == "answer-clarification"
            and reservation_need.task_intent == "make-reservation",
            f"affirmative reservation need did not enter the booking task: {reservation_need}")
    live_reservation_need = CRMSDialogue(CRMSKnowledgeBase())
    live_reservation_need.active_task_intent = "seek-information"
    live_reservation_need.open_dialogue_question = {
        "prompt": "Sure, did you need a reservation?",
        "answer_kind": "yes-no", "expected_slot": "yes_no",
    }
    reservation_turn = respond(live_reservation_need, "Yes.")
    require(reservation_turn.intent_hypothesis is not None
            and reservation_turn.intent_hypothesis.task_intent == "make-reservation"
            and live_reservation_need.active_task_intent == "make-reservation"
            and live_reservation_need.open_dialogue_question is None,
            "live affirmative reservation answer did not change the active task")
    reservation_declined = classify(
        "Sure, did you need a reservation?", "yes_no", "seek-information",
        "No, not a reservation.", answer_kind="yes-no")
    require(reservation_declined is not None
            and reservation_declined.task_intent == "continue-current-task",
            f"declining a reservation incorrectly started booking: {reservation_declined}")

    bare_preference_yes = classify(
        "Did you have any restaurant preferences?", "yes_no", "seek-information",
        "Yes.", answer_kind="yes-no")
    require(bare_preference_yes is not None
            and bare_preference_yes.decision == "ambiguous"
            and bare_preference_yes.matched_frame == "yes-without-preference-details",
            "a bare yes to a preference question was accepted without preference values")
    live_preference_yes = CRMSDialogue(CRMSKnowledgeBase())
    live_preference_yes.active_task_intent = "seek-information"
    live_preference_yes.open_dialogue_question = {
        "prompt": "Did you have any restaurant preferences?",
        "answer_kind": "yes-no", "expected_slot": "yes_no",
    }
    preference_clarification = respond(live_preference_yes, "Yes.")
    require(preference_clarification.status == "clarify"
            and preference_clarification.text
            == "What restaurant preferences should I use?"
            and live_preference_yes.open_dialogue_question is not None
            and live_preference_yes.open_dialogue_question["prompt"]
            == "What restaurant preferences should I use?",
            "live dialogue did not ask for the values behind a bare preference yes")
    bare_preference_no = classify(
        "Did you have any restaurant preferences?", "yes_no", "seek-information",
        "No.", answer_kind="yes-no")
    require(bare_preference_no is not None
            and bare_preference_no.task_intent == "continue-current-task",
            "a bare no to a preference question did not preserve the current task")
    rejection = classify("Are you sure?", "confirmation", "continue-current-task",
                         "No.", answer_kind="yes-no")
    require(rejection is not None and rejection.dialogue_act == "reject",
            f"negative confirmation was not represented as rejection: {rejection}")
    require(infer_open_question_slot("Is that restaurant good?", "yes-no")
            == "yes_no",
            "ordinary yes/no question was misclassified as a confirmation")
    ordinary_yes = classify("Is that restaurant good?", "yes_no",
                            "seek-information", "Yes.", answer_kind="yes-no")
    require(ordinary_yes is not None
            and ordinary_yes.dialogue_act == "answer-clarification",
            f"ordinary yes/no response was routed as a confirmation: {ordinary_yes}")

    live = CRMSDialogue(CRMSKnowledgeBase())
    live.open_dialogue_question = {
        "prompt": "Are you sure?", "answer_kind": "yes-no",
        "expected_slot": "confirmation",
    }
    respond(live, "Yes")
    require(live.last_intent_hypothesis is not None
            and live.last_intent_hypothesis.dialogue_act == "confirm"
            and live.open_dialogue_question is None,
            "confirming an open yes/no question did not close its discourse state")

    live.open_dialogue_question = {
        "prompt": "Is that right?", "answer_kind": "yes-no",
        "expected_slot": "confirmation",
    }
    respond(live, "No")
    require(live.last_intent_hypothesis is not None
            and live.last_intent_hypothesis.dialogue_act == "reject"
            and live.open_dialogue_question is not None
            and live.open_dialogue_question["prompt"]
            == "Okay. What should I correct?",
            "rejecting a confirmation did not ask for correction details")

    print("search detail resolves as a constraint: PASS")
    print("reservation task resolves from active state or explicit prompt: PASS")
    print("restaurant filters remain constraints during reservation flows: PASS")
    print("affirmative preference answers preserve added constraints: PASS")
    print("live preference answer acknowledges the constraint and clears the open question: PASS")
    print("restaurant type is exposed as a typed open-question slot: PASS")
    print("change-reservation task resolves from explicit prompt: PASS")
    print("missing task evidence retains the conservative continuation label: PASS")
    print("explicit yes/no confirmation and rejection use distinct acts: PASS")
    print("confirmation rejection opens a correction-detail question: PASS")
    print("transcript question typing distinguishes booking offers and confirmations: PASS")
    print("reservation yes/no answers update task intent according to polarity: PASS")
    print("bare preference answers request details or continue without inventing values: PASS")


if __name__ == "__main__":
    main()

"""Deterministic conversation acts that stay separate from evidence retrieval."""

from __future__ import annotations

import re
from typing import Any

from crms_dialogue import CRMSDialogue, DialogueTurn, UserIntentHypothesis


_ACTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("greeting", re.compile(
        r"^(?:hi(?:\s+there)?|hello(?:\s+there)?|hey(?:\s+there)?|"
        r"good\s+(?:morning|afternoon|evening)|how\s+are\s+you)[?.! ]*$",
        re.IGNORECASE)),
    ("farewell", re.compile(
        r"^(?:goodbye|bye|see\s+you|take\s+care)[?.! ]*$", re.IGNORECASE)),
    ("thanks", re.compile(r"^(?:thanks|thank\s+you|thx)[.! ]*$", re.IGNORECASE)),
    ("acknowledgement", re.compile(
        r"^(?:ok|okay|got\s+it|understood)[.! ]*$", re.IGNORECASE)),
    ("elaboration", re.compile(
        r"^(?:tell\s+me\s+more|go\s+on|anything\s+else)[?.! ]*$",
        re.IGNORECASE)),
    ("help", re.compile(
        r"^(?:help|what\s+can\s+you\s+do|how\s+do\s+i\s+use\s+this)"
        r"[?!. ]*$", re.IGNORECASE)),
    ("reaction", re.compile(
        r"^(?:lol|lmao|rofl|(?:ha){2,}h?|(?:he){2,}h?|wow|whoa|oops|ugh|"
        r"huh|yay|meh|cool|nice|great|awesome)[.!? ]*$", re.IGNORECASE)),
    ("unclassified", re.compile(
        r"^(?:h+m+|u+h+|u+m+|e+r+m+|\.\.\.|\?+)[.!? ]*$",
        re.IGNORECASE)),
    # Emoji or punctuation with no letters, digits or arithmetic operators.
    # Digits and operators are excluded so a bare calculation still reaches
    # the exact-math route.
    ("unclassified", re.compile(r"^[^\w+\-*/=^%()<>\[\]{}$#@&|~]+$")),
)
_MIXED_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey)(?:\s+there)?[,]\s*(?P<question>\S.+)$",
    re.IGNORECASE)
_BARE_YES_NO_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|certainly|absolutely|no|nope|nah|not really)"
    r"(?:[, ]+(?:please|thanks|thank you))?[.!? ]*$",
    re.IGNORECASE)
_OVERVIEW_RE = re.compile(
    r"^(?:what\s+do\s+you\s+know\s+about|what\s+can\s+you\s+tell\s+me\s+about|"
    r"tell\s+me\s+what\s+you\s+know\s+about|what\s+is\s+known\s+about)\s+"
    r"(?P<entity>\S.*?)[?!. ]*$", re.IGNORECASE)
_EXPLANATION_FOLLOWUP_RE = re.compile(
    r"^(?:why(?: is that)?|how do you know(?: that)?|what supports that)"
    r"[?!. ]*$", re.IGNORECASE)
_WH_QUESTION_RE = re.compile(
    r"^(?:who|whom|whose|what|which|when|where|why|how)\b", re.IGNORECASE)
_YES_NO_QUESTION_RE = re.compile(
    r"^(?:am|is|are|was|were|do|does|did|has|have|had|can|could|will|would|"
    r"shall|should|may|might)\b.+\?\s*$", re.IGNORECASE)
_MODAL_REQUEST_RE = re.compile(
    r"^(?:can|could|would|will)\s+(?:you|i|we)\s+"
    r"(?P<verb>[a-z]+)\b(?:\s+.+)?[?.! ]*$", re.IGNORECASE)
_INFORMATION_REQUEST_VERBS = {
    "check", "confirm", "describe", "explain", "find", "give", "hear",
    "list", "read", "repeat", "say", "search", "see", "show", "tell",
    "view",
}
_ACTION_REQUEST_VERBS = {
    "add", "book", "bring", "calculate", "cancel", "change", "create",
    "do", "get", "go", "help", "include", "make", "mind", "order",
    "put", "remind", "reserve", "seat", "send", "set", "take", "translate",
    "try", "write",
}


def _count(value: int, noun: str) -> str:
    return f"{value:,} {noun}{'' if value == 1 else 's'}"


def classify_act(text: str) -> str | None:
    """Classify only anchored, content-free seed acts; mixed turns pass through."""
    normalized = text.strip()
    for act, pattern in _ACTS:
        if pattern.fullmatch(normalized):
            return act
    return None


def is_farewell(text: str) -> bool:
    return classify_act(text) == "farewell"


def classify_user_intent(
        dialogue: CRMSDialogue, text: str) -> UserIntentHypothesis | None:
    """Return only the contextual intent decisions licensed by current rules.

    This is an inspectable runtime baseline, not a learned intent model. A
    missing result means the current rules do not classify this turn.
    """
    if _EXPLANATION_FOLLOWUP_RE.fullmatch(text.strip()):
        if dialogue.pending_result is not None:
            return UserIntentHypothesis(
                dialogue_act="question",
                task_intent="seek-information",
                decision="ambiguous",
                matched_frame="explanation-follow-up",
                context_predicates=("pending_candidate_choice",),
                alternatives=tuple(dialogue.pending_result.candidates or ()),
            )
        if dialogue.last_question is not None:
            return UserIntentHypothesis(
                dialogue_act="question",
                task_intent="seek-information",
                decision="selected",
                matched_frame="explanation-follow-up",
                context_predicates=("previous_grounded_question",),
                selected_value=dialogue.last_selected_answer,
            )
        if dialogue.last_answered is not None:
            return UserIntentHypothesis(
                dialogue_act="question",
                task_intent="seek-information",
                decision="selected",
                matched_frame="explanation-follow-up",
                context_predicates=("earlier_grounded_answer",),
                selected_value=dialogue.last_answered.get("answer") or None,
            )
        return UserIntentHypothesis(
            dialogue_act="uncertain",
            task_intent=None,
            decision="ambiguous",
            matched_frame="unanchored-explanation-follow-up",
            context_predicates=("no_previous_grounded_answer",),
            alternatives=("request-explanation", "ask-new-question"),
        )

    if dialogue.pending_result is not None:
        selected, is_selection = dialogue._select_candidate(text)
        if is_selection:
            candidates = dialogue.pending_result.candidates or []
            return UserIntentHypothesis(
                dialogue_act="answer-clarification",
                task_intent="resolve-ambiguity",
                decision="selected" if selected is not None else "ambiguous",
                matched_frame="candidate-selection",
                context_predicates=("pending_candidate_choice",),
                alternatives=tuple(value for value in candidates
                                   if value != selected),
                selected_value=selected,
            )
        if classify_act(text) in {"acknowledgement", "reaction"}:
            return UserIntentHypothesis(
                dialogue_act="acknowledgement",
                task_intent="resolve-ambiguity",
                decision="ambiguous",
                matched_frame="receipt-during-pending-choice",
                context_predicates=("pending_candidate_choice",),
                alternatives=tuple(dialogue.pending_result.candidates or ()),
            )
        if _BARE_YES_NO_RE.fullmatch(text.strip()):
            return UserIntentHypothesis(
                dialogue_act="answer-clarification",
                task_intent="resolve-ambiguity",
                decision="ambiguous",
                matched_frame="bare-yes-no-or-acknowledgement",
                context_predicates=("pending_candidate_choice",),
                alternatives=tuple(dialogue.pending_result.candidates or ()),
            )

    act = classify_act(text)
    mappings = {
        "greeting": ("greeting", "social-contact"),
        "farewell": ("farewell", "end-interaction"),
        "thanks": ("thanks", "social-contact"),
        "acknowledgement": ("acknowledgement", "continue-current-task"),
        "reaction": ("reaction", "social-contact"),
        "elaboration": ("continuation-request", "continue-current-task"),
        "help": ("question", "seek-information"),
    }
    if act in mappings:
        dialogue_act, task_intent = mappings[act]
        if act == "elaboration":
            if dialogue.last_entity or dialogue.source_mentions:
                return UserIntentHypothesis(
                    dialogue_act=dialogue_act,
                    task_intent=task_intent,
                    decision="selected",
                    matched_frame=act,
                    context_predicates=("current_topic_available",),
                )
            return UserIntentHypothesis(
                dialogue_act=dialogue_act,
                task_intent=None,
                decision="ambiguous",
                matched_frame=act,
                context_predicates=("no_current_topic",),
                alternatives=("continue-current-task", "introduce-topic"),
            )
        return UserIntentHypothesis(
            dialogue_act=dialogue_act,
            task_intent=task_intent,
            decision="selected",
            matched_frame=act,
        )

    # Content questions and modal requests need an intent hypothesis too. Keep
    # this lexical baseline narrow and explicit: it classifies the immediate
    # speech act without asserting a factual premise or changing the answer path.
    stripped = text.strip()
    modal_request = _MODAL_REQUEST_RE.fullmatch(stripped)
    if modal_request is not None:
        verb = modal_request.group("verb").casefold()
        if verb in _INFORMATION_REQUEST_VERBS | _ACTION_REQUEST_VERBS:
            return UserIntentHypothesis(
                dialogue_act="request-action",
                task_intent=("seek-information"
                             if verb in _INFORMATION_REQUEST_VERBS
                             else "other-task"),
                decision="selected",
                matched_frame="modal-request",
                context_predicates=("direct-user-request",),
            )
    if (_WH_QUESTION_RE.match(stripped)
            or _YES_NO_QUESTION_RE.fullmatch(stripped)):
        return UserIntentHypothesis(
            dialogue_act="question",
            task_intent="seek-information",
            decision="selected",
            matched_frame=("wh-question" if _WH_QUESTION_RE.match(stripped)
                           else "yes-no-question"),
            context_predicates=("content-question",),
        )

    if _BARE_YES_NO_RE.fullmatch(text.strip()):
        return UserIntentHypothesis(
            dialogue_act="uncertain",
            task_intent=None,
            decision="ambiguous",
            matched_frame="bare-yes-no-without-open-question",
            context_predicates=("no_open_yes_no_question",),
            alternatives=("answer-clarification", "acknowledgement"),
        )
    return None


def _explain_earlier_answer(
        dialogue: CRMSDialogue, text: str,
        research_index: Any | None) -> DialogueTurn | None:
    """Explain the last grounded answer after turns that left no live context.

    The explanation recomputes the answer from current evidence, exactly as it
    does for an immediate follow-up, and says which question it is explaining.
    """
    if (dialogue.last_question is not None or dialogue.last_answered is None
            or dialogue.pending_result is not None
            or dialogue.last_writing_subject is not None
            or dialogue.last_timeline_subject is not None):
        return None
    earlier = dialogue.last_answered["question"]
    dialogue.last_question = earlier
    turn = dialogue.turn(text, research_index=research_index)
    if turn.response is not None and turn.response.status == "answered":
        turn.text = f"Explaining my earlier answer to ‘{earlier}’.\n{turn.text}"
    return turn


def respond(dialogue: CRMSDialogue, text: str, *,
            research_index: Any | None = None,
            pending_claims: int = 0) -> DialogueTurn:
    """Handle simple dialogue acts, delegating every content turn unchanged."""
    intent = classify_user_intent(dialogue, text)
    act = classify_act(text)

    def with_intent(turn: DialogueTurn) -> DialogueTurn:
        turn.intent_hypothesis = intent
        dialogue.last_intent_hypothesis = intent
        dialogue.record_turn(text, act or "question", turn)
        return turn

    mixed_greeting = _MIXED_GREETING_RE.fullmatch(text.strip())
    if mixed_greeting is not None:
        content = mixed_greeting.group("question").strip()
        intent = UserIntentHypothesis(
            dialogue_act="question",
            task_intent="seek-information",
            decision="selected",
            matched_frame="greeting-plus-content-question",
        )
        turn = dialogue.turn(content, research_index=research_index)
        if turn.text:
            turn.text = "Hello. " + turn.text
        return with_intent(turn)
    binding = dialogue.pending_binding
    if binding is not None:
        names = tuple(option["entity"] for option in binding["options"])
        chosen = dialogue.select_binding(text)
        if chosen is not None:
            intent = UserIntentHypothesis(
                dialogue_act="answer-clarification",
                task_intent="resolve-ambiguity",
                decision="selected",
                matched_frame="pronoun-binding-selection",
                context_predicates=("pending_pronoun_binding",),
                alternatives=tuple(name for name in names
                                   if name != chosen["entity"]),
                selected_value=chosen["entity"],
            )
            dialogue.pending_binding = None
            return with_intent(dialogue.turn(
                chosen["resolved"], research_index=research_index))
        if act in {"acknowledgement", "reaction"} or _BARE_YES_NO_RE.fullmatch(
                text.strip()):
            intent = UserIntentHypothesis(
                dialogue_act="answer-clarification",
                task_intent="resolve-ambiguity",
                decision="ambiguous",
                matched_frame="receipt-during-pending-binding",
                context_predicates=("pending_pronoun_binding",),
                alternatives=names,
            )
            numbered = "; ".join(f"{number}. {name}"
                                 for number, name in enumerate(names, 1))
            return with_intent(DialogueTurn(
                "ambiguous", text, binding["question"],
                text=("That does not say which one. Please choose: "
                      f"{numbered}.")))
        dialogue.pending_binding = None
    if act is None:
        overview = _OVERVIEW_RE.fullmatch(text.strip())
        if overview is not None:
            subject, conflict = dialogue.knowledge.resolve_about_request(text)
            card = (None if conflict or subject is not None else
                    dialogue.overview(overview.group("entity")))
            if card is not None:
                intent = UserIntentHypothesis(
                    dialogue_act="question",
                    task_intent="seek-information",
                    decision="selected",
                    matched_frame="entity-overview",
                    context_predicates=("accepted_facts_available",),
                    selected_value=dialogue.subject_entity,
                )
                return with_intent(card)
    if act is None and _EXPLANATION_FOLLOWUP_RE.fullmatch(text.strip()):
        explained = _explain_earlier_answer(dialogue, text, research_index)
        if explained is not None:
            return with_intent(explained)
    if act is None:
        turn = dialogue.turn(text, research_index=research_index)
        if dialogue.pending_binding is not None:
            intent = UserIntentHypothesis(
                dialogue_act="question",
                task_intent="seek-information",
                decision="ambiguous",
                matched_frame="pronoun-binding-request",
                context_predicates=("ambiguous_pronoun_referent",),
                alternatives=tuple(option["entity"] for option
                                   in dialogue.pending_binding["options"]),
            )
        return with_intent(turn)
    if act == "acknowledgement" and dialogue.pending_result is not None:
        # A receipt such as "okay" acknowledges the request to choose, but it
        # does not itself select or close the open answer clarification.
        return with_intent(dialogue.turn(text, research_index=research_index))
    if act == "reaction" and dialogue.pending_result is not None:
        # An exclamation is neither a choice nor a new topic: repeat the open
        # choice without retrieval and without discarding it.
        candidates = dialogue.pending_result.candidates or []
        choices = "; ".join(f"{i}. {value}"
                            for i, value in enumerate(candidates, 1))
        return with_intent(DialogueTurn(
            "ambiguous", text, dialogue.pending_question or text,
            response=dialogue.pending_result,
            text=("That does not identify one of the supported answers. "
                  f"Please choose: {choices}.")))

    if act == "greeting":
        fact_count = len(dialogue.knowledge._facts)
        source_count = (research_index.document_count()
                        if research_index is not None else 0)
        reply = ("Hello. CRMS has "
                 f"{_count(fact_count, 'accepted fact')} and "
                 f"{_count(source_count, 'source document')} loaded")
        if pending_claims:
            reply += f", with {_count(pending_claims, 'claim')} awaiting review"
        reply += (". Ask about an entity or source; ask ‘why?’ to see the "
                  "supporting evidence.")
        return with_intent(DialogueTurn("social", text, text, text=reply))
    if act == "farewell":
        return with_intent(DialogueTurn("farewell", text, text, text="Goodbye."))
    if act == "thanks":
        return with_intent(DialogueTurn("social", text, text, text="You're welcome."))
    if act in {"acknowledgement", "reaction"}:
        return with_intent(DialogueTurn(
            "social", text, text,
            text="Okay. What would you like to ask or do next?"))
    if act == "elaboration":
        elaborated = dialogue.elaborate()
        if elaborated is not None:
            return with_intent(elaborated)
        reply = "Which entity or source should I look at in more detail?"
        return with_intent(DialogueTurn("clarify", text, text, text=reply))
    if act == "help":
        return with_intent(DialogueTurn(
            "help", text, text,
            text=("Ask about indexed sources or accepted facts. Add sources with "
                  "/source or /source-dir; ask ‘why?’ for evidence. You can also "
                  "teach cited facts and ask CRMS to write a short fictional story.")))
    return with_intent(DialogueTurn(
        "unclassified", text, text,
        text=("I didn't recognize a question or action. Ask about a source or fact, "
              "request a short fictional story, or type /help.")))

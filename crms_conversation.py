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
    ("unclassified", re.compile(
        r"^(?:h+m+|u+h+|u+m+|e+r+m+|\.\.\.|\?+)[.!? ]*$",
        re.IGNORECASE)),
)
_MIXED_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey)(?:\s+there)?[,]\s*(?P<question>\S.+)$",
    re.IGNORECASE)
_BARE_YES_NO_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|certainly|absolutely|no|nope|nah|not really)"
    r"(?:[, ]+(?:please|thanks|thank you))?[.!? ]*$",
    re.IGNORECASE)
_EXPLANATION_FOLLOWUP_RE = re.compile(
    r"^(?:why(?: is that)?|how do you know(?: that)?|what supports that)"
    r"[?!. ]*$", re.IGNORECASE)


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
        if classify_act(text) == "acknowledgement":
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


def respond(dialogue: CRMSDialogue, text: str, *,
            research_index: Any | None = None,
            pending_claims: int = 0) -> DialogueTurn:
    """Handle simple dialogue acts, delegating every content turn unchanged."""
    intent = classify_user_intent(dialogue, text)

    def with_intent(turn: DialogueTurn) -> DialogueTurn:
        turn.intent_hypothesis = intent
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
    act = classify_act(text)
    if act is None:
        return with_intent(dialogue.turn(text, research_index=research_index))
    if act == "acknowledgement" and dialogue.pending_result is not None:
        # A receipt such as "okay" acknowledges the request to choose, but it
        # does not itself select or close the open answer clarification.
        return with_intent(dialogue.turn(text, research_index=research_index))

    if act == "greeting":
        fact_count = len(dialogue.knowledge._facts)
        source_count = (research_index.document_count()
                        if research_index is not None else 0)
        counts = f"{fact_count:,} accepted facts and {source_count:,} source documents"
        if pending_claims:
            counts += f"; {pending_claims:,} claims awaiting review"
        reply = (f"Hello. CRMS has {counts} loaded. Ask about an entity or source; "
                 "ask ‘why?’ to see the supporting evidence.")
        return with_intent(DialogueTurn("social", text, text, text=reply))
    if act == "farewell":
        return with_intent(DialogueTurn("farewell", text, text, text="Goodbye."))
    if act == "thanks":
        return with_intent(DialogueTurn("social", text, text, text="You're welcome."))
    if act == "acknowledgement":
        return with_intent(DialogueTurn(
            "social", text, text,
            text="Okay. What would you like to ask or do next?"))
    if act == "elaboration":
        focus = dialogue.last_entity
        if focus:
            reply = (f"I can look for more grounded information about {focus}. "
                     "Ask a specific question about it or name another topic.")
        else:
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

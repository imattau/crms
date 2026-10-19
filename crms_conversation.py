"""Deterministic conversation acts that stay separate from evidence retrieval."""

from __future__ import annotations

import hashlib
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
        r"^(?:(?:(?:can|could|would|will)\s+you\s+)?"
        r"(?:please\s+)?(?:tell\s+me\s+more|say\s+more|go\s+on|"
        r"go\s+into\s+more\s+detail|elaborate|expand)|anything\s+else)"
        r"(?:[, ]+please)?[?.! ]*$",
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
_CORRECTION_RE = re.compile(
    r"^(?:(?:no|nope|sorry)[,.!]?\s+)?(?:i\s+meant|i\s+mean)\s+"
    r"(?P<entity>\S.*?)[?!. ]*$", re.IGNORECASE)
_VERDICT_RE = re.compile(
    r"^(?:that|it)(?:\s+is|['’]s)\s+(?P<verdict>"
    r"(?:not\s+(?:right|correct|true)|wrong|incorrect|false|"
    r"right|correct|true))[.! ]*$", re.IGNORECASE)
_NEGATIVE_VERDICTS = {"wrong", "incorrect", "false", "not right",
                      "not correct", "not true"}
_REVIEW_HINT = "use /pending-candidates to inspect"
_OFFER_LIFETIME = 2
_OVERVIEW_RE = re.compile(
    r"^(?:what\s+do\s+you\s+know\s+about|what\s+can\s+you\s+tell\s+me\s+about|"
    r"tell\s+me\s+what\s+you\s+know\s+about|what\s+is\s+known\s+about)\s+"
    r"(?P<entity>\S.*?)[?!. ]*$", re.IGNORECASE)
_EXPLANATION_FOLLOWUP_RE = re.compile(
    r"^(?:why(?: is that)?|how do you know(?: that)?|what supports that)"
    r"[?!. ]*$", re.IGNORECASE)
_ELABORATION_TOPIC_REPLY_RE = re.compile(
    r"^(?:about\s+)?(?P<topic>[\w][\w '&’.-]{0,118})[.! ]*$",
    re.IGNORECASE)
_CANCEL_FOLLOWUP_RE = re.compile(
    r"^(?:never mind|forget it|cancel that|cancel)[.! ]*$", re.IGNORECASE)
_WH_QUESTION_RE = re.compile(
    r"^(?:who|whom|whose|what|which|when|where|why|how)\b", re.IGNORECASE)
_YES_NO_QUESTION_RE = re.compile(
    r"^(?:am|is|are|was|were|do|does|did|has|have|had|can|could|will|would|"
    r"shall|should|may|might)\b.+\?\s*$", re.IGNORECASE)


def _elaboration_topic_reply(text: str) -> re.Match[str] | None:
    """Match a short entity-like answer, never a newly asked question."""
    stripped = text.strip()
    if (_WH_QUESTION_RE.match(stripped)
            or _YES_NO_QUESTION_RE.fullmatch(stripped)):
        return None
    return _ELABORATION_TOPIC_REPLY_RE.fullmatch(stripped)
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


def natural_feedback_verdict(text: str) -> str | None:
    """Map an explicit verdict about the last answer to ``right`` or ``wrong``.

    Only "that's / it is" plus a verdict word counts. A bare "correct" or
    "right" is left alone because other prompts use those words as replies.
    """
    match = _VERDICT_RE.fullmatch(text.strip())
    if match is None:
        return None
    verdict = " ".join(match.group("verdict").casefold().split())
    return "wrong" if verdict in _NEGATIVE_VERDICTS else "right"


_STATEMENT_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*|\d+")
_DETERMINERS = {"the", "a", "an", "this", "that", "these", "those", "his", "her",
                "their", "its", "our", "my", "your", "some", "many", "one", "each",
                "every", "no", "all", "any"}
_NAME_CONNECTORS = {"of", "van", "von", "de", "da", "del", "la", "le", "bin", "ibn"}
_STATEMENT_BLOCKED_FIRST_WORDS = {
    "what", "who", "whom", "whose", "which", "when", "where", "why", "how",
    "is", "are", "was", "were", "do", "does", "did", "can", "could", "will",
    "would", "should", "please", "teach", "tell", "show", "write", "compose",
    "translate", "explain", "calculate", "solve", "find", "list", "give",
    "hello", "hi", "hey", "thanks", "thank", "yes", "no", "ok", "okay", "i",
    "my", "we", "you", "it", "he", "she", "they", "there", "here", "if", "so",
    "but", "and", "or", "because", "let", "make", "add", "remember", "forget",
}
_STATEMENT_BLOCKED_WORDS = {
    "and", "or", "but", "because", "although", "which", "that", "who", "whom",
    "if", "when", "while", "not", "never", "i", "you", "we", "me", "us",
}
_STATEMENT_LIMIT = 24


def parse_statement(text: str) -> tuple[str, str, str] | None:
    """Split a plain sentence into (subject, relation, object), or return None.

    A deliberately narrow proposal, not a parser: a leading named entity, a
    short run of lowercase predicate words, and the rest as the object. It
    only ever proposes; the user confirms before anything is stored.
    """
    stripped = text.strip()
    if (not stripped or stripped.endswith("?") or stripped.startswith("/")
            or any(mark in stripped for mark in ",;:()\"“”")):
        return None
    stripped = stripped.rstrip(".! ")
    if re.fullmatch(r"[A-Za-z0-9'’ -]+", stripped) is None:
        return None
    words = _STATEMENT_WORD_RE.findall(stripped)
    if len(words) < 3 or len(words) > _STATEMENT_LIMIT:
        return None
    if words[0].casefold() in _STATEMENT_BLOCKED_FIRST_WORDS:
        return None
    if any(word.casefold() in _STATEMENT_BLOCKED_WORDS for word in words):
        return None
    index = 0
    if words[0].casefold() in {"the", "a", "an"}:
        index = 1
    if index >= len(words) or not words[index][:1].isupper():
        return None
    end = index
    while end < len(words):
        word = words[end]
        if word[:1].isupper() or word.isdigit():
            end += 1
        elif (word.casefold() in _NAME_CONNECTORS and end + 1 < len(words)
              and words[end + 1][:1].isupper()):
            end += 1
        else:
            break
    subject = " ".join(words[:end])
    predicate_end = end
    while (predicate_end < len(words) and predicate_end - end < 3
           and words[predicate_end][:1].islower()
           and words[predicate_end].casefold() not in _DETERMINERS):
        predicate_end += 1
    if predicate_end == end or predicate_end >= len(words):
        return None
    relation = " ".join(words[end:predicate_end]).casefold()
    obj = " ".join(words[predicate_end:])
    if len(obj.split()) > 8:
        return None
    return subject, relation, obj


def _has_fact(knowledge: Any, subject: str, relation: str, obj: str) -> bool:
    key = knowledge._fact_key(knowledge._canonicalize_entity(subject), relation,
                              knowledge._canonicalize_entity(obj))
    return knowledge._facts.get(key) is not None


def _statement_source(sentence: str) -> str:
    """One shared origin for everything a user tells CRMS, one fragment per statement."""
    digest = hashlib.sha256(sentence.strip().encode("utf-8")).hexdigest()[:10]
    return f"told by user#{digest}"


def _propose_statement(dialogue: CRMSDialogue, text: str) -> DialogueTurn | None:
    parsed = parse_statement(text)
    if parsed is None:
        return None
    subject, relation, obj = parsed
    knowledge = dialogue.knowledge
    if _has_fact(knowledge, subject, relation, obj):
        return DialogueTurn(
            "social", text, text,
            text=f"I already have that: {subject} — {relation} → {obj}.")
    dialogue.offers = [{
        "kind": "confirm_statement", "turns_left": _OFFER_LIFETIME,
        "sentence": text.strip(), "subject": subject, "relation": relation,
        "object": obj}]
    return DialogueTurn(
        "social", text, text,
        text=(f"I understood: {subject} — {relation} → {obj}. Shall I remember "
              "that as something you told me? Say ‘yes’ or ‘no’."))


def _learn_statement(dialogue: CRMSDialogue, offer: dict[str, Any],
                     text: str) -> DialogueTurn:
    knowledge = dialogue.knowledge
    subject, relation, obj = offer["subject"], offer["relation"], offer["object"]
    sentence = offer["sentence"]
    source = _statement_source(sentence)
    try:
        knowledge.add_fact(subject, relation, obj, source)
    except ValueError as error:
        return DialogueTurn("social", text, text,
                            text=f"I could not store that: {error}")
    lines = [f"Remembered: {subject} — {relation} → {obj} [told by user]."]
    try:
        learned_pattern = knowledge.teach_fact_pattern(
            sentence, subject=subject, relation=relation, obj=obj, source=source)
    except ValueError:
        learned_pattern = None
    if learned_pattern:
        lines.append("I can now recognise sentences worded like that one.")
    else:
        lines.append("I need one more example with different names before I "
                     "recognise this wording on my own.")
    lines.append(f"Forget it with: /retract-fact POS|{subject}|{relation}|"
                 f"{obj}|{source}")
    return DialogueTurn("learned", text, text, text="\n".join(lines),
                        learned=True)


def offer_pending_review(dialogue: CRMSDialogue) -> str | None:
    """Open an offer to review pending claims and return the line that states it.

    Call it only where a reply has just told the user that claims are waiting.
    Returns ``None`` when the same offer is already open.
    """
    if any(item["kind"] == "review_pending" for item in dialogue.offers):
        return None
    dialogue.offers.append({"kind": "review_pending",
                            "action": "/pending-candidates",
                            "turns_left": _OFFER_LIFETIME})
    return "Say ‘yes’ to review them now."


def _offer(dialogue: CRMSDialogue, turn: DialogueTurn) -> None:
    """Offer a review where this reply itself says claims are waiting."""
    if _REVIEW_HINT in (turn.text or "").casefold():
        line = offer_pending_review(dialogue)
        if line:
            turn.text = f"{turn.text}\n{line}"


def _count(value: int, noun: str) -> str:
    return f"{value:,} {noun}{'' if value == 1 else 's'}"


_RUNTIME_ROUTE_WORDING = {
    "greeting": ("a greeting", "greet you"),
    "farewell": ("a goodbye", "say goodbye"),
    "thanks": ("thanks", "thank you"),
    "acknowledgement": ("an acknowledgement", "acknowledge it"),
    "reaction": ("a social reaction", "treat it as a reaction"),
    "elaboration": ("a request to continue the current topic",
                    "continue the current topic"),
}


def _ambiguous_runtime_routes(
        intent: UserIntentHypothesis) -> tuple[str, ...]:
    """Extract only the validated routes encoded in ambiguous frame readings."""
    if (intent.basis != "portable_dialogue_model"
            or intent.decision != "ambiguous"
            or intent.matched_frame != "ambiguous-portable-frames"):
        return ()
    routes = []
    for alternative in intent.alternatives:
        match = re.search(r"; route ([a-z-]+)\)$", alternative)
        if match is None or match.group(1) not in _RUNTIME_ROUTE_WORDING:
            return ()
        routes.append(match.group(1))
    if len(routes) != 2 or routes[0] == routes[1]:
        return ()
    return tuple(routes)


def _runtime_route_reply(dialogue: CRMSDialogue, route: str, text: str, *,
                         research_index: Any | None,
                         pending_claims: int) -> DialogueTurn:
    """Run a previously licensed route after the user resolves ambiguity."""
    if route == "greeting":
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
        if pending_claims:
            reply += " Use /pending-candidates to inspect them."
        return DialogueTurn("social", text, text, text=reply)
    if route == "farewell":
        return DialogueTurn("farewell", text, text, text="Goodbye.")
    if route == "thanks":
        return DialogueTurn("social", text, text, text="You're welcome.")
    if route in {"acknowledgement", "reaction"}:
        return DialogueTurn(
            "social", text, text,
            text="Okay. What would you like to ask or do next?")
    if route == "elaboration":
        elaborated = dialogue.elaborate()
        if elaborated is not None:
            return elaborated
        dialogue.pending_dialogue_slot = "elaboration_topic"
        return DialogueTurn(
            "clarify", text, text,
            text="Which entity with accepted facts should I look at in more detail?")
    return DialogueTurn("unclassified", text, text,
                        text="I could not use that intent route.")


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
    """Return only contextual intent decisions licensed by runtime evidence.

    Hand-checked rules handle the existing dialogue routes; the optional
    portable model can extend exact surface forms when its context conditions
    pass. A missing result means neither mechanism licenses an intent.
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

    if dialogue.pending_dialogue_slot == "elaboration_topic":
        if _CANCEL_FOLLOWUP_RE.fullmatch(text.strip()):
            return UserIntentHypothesis(
                dialogue_act="cancel-follow-up",
                task_intent="continue-current-task",
                decision="selected",
                matched_frame="cancel-open-elaboration-question",
                context_predicates=("open_question:elaboration_topic",),
            )
        topic_reply = _elaboration_topic_reply(text)
        if topic_reply and classify_act(text) is None:
            topic = topic_reply.group("topic").strip()
            canonical = dialogue._canonical_entity(topic)
            if canonical:
                return UserIntentHypothesis(
                    dialogue_act="answer-clarification",
                    task_intent="continue-current-task",
                    decision="selected",
                    matched_frame="elaboration-topic-slot",
                    context_predicates=("open_question:elaboration_topic",
                                        "accepted_entity_match"),
                    selected_value=canonical,
                )
            return UserIntentHypothesis(
                dialogue_act="answer-clarification",
                task_intent="continue-current-task",
                decision="ambiguous",
                matched_frame="elaboration-topic-slot",
                context_predicates=("open_question:elaboration_topic",
                                    "no_accepted_entity_match"),
                alternatives=("name an entity with accepted facts",
                             "ask a specific question about the source"),
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

    # Portable dialogue frames are additive: built-in content-free and
    # contextual clarification rules above take precedence. Only explicitly
    # built-in or held-out-validated frames can select a route.
    intent_model = getattr(dialogue, "intent_model", None)
    context_provider = getattr(dialogue, "intent_context", None)
    portable = None
    if intent_model is not None and callable(context_provider):
        context, predecessor = context_provider()
        portable = intent_model.resolve(
            text, context=context, predecessor_act=predecessor)
    if portable is not None:
        return UserIntentHypothesis(
            dialogue_act=portable["dialogue_act"],
            task_intent=portable["task_intent"],
            decision=portable["decision"],
            matched_frame=portable["matched_frame"],
            context_predicates=portable["context_predicates"],
            alternatives=portable["alternatives"],
            selected_value=portable["selected_value"],
            basis=portable["basis"],
            evidence_refs=portable["evidence_refs"],
            runtime_route=portable["runtime_route"],
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
    if (act is None and intent is not None and intent.decision == "selected"
            and intent.basis == "portable_dialogue_model"):
        act = intent.runtime_route

    def with_intent(turn: DialogueTurn) -> DialogueTurn:
        turn.intent_hypothesis = intent
        dialogue.last_intent_hypothesis = intent
        dialogue.record_turn(text, act or "question", turn, intent)
        _offer(dialogue, turn)
        return turn

    offers = dialogue.offers
    answers_offer = bool(
        offers and dialogue.pending_result is None
        and dialogue.pending_binding is None
        and _BARE_YES_NO_RE.fullmatch(text.strip()))
    if offers and not answers_offer:
        # Any other turn uses up one of the offer's remaining turns.
        dialogue.offers = [dict(item, turns_left=item["turns_left"] - 1)
                           for item in offers if item["turns_left"] > 1]
    if answers_offer:
        accepted = _BARE_YES_NO_RE.fullmatch(text.strip()).group(0).casefold()
        said_yes = accepted.split()[0].strip(",.!?") in {
            "yes", "yeah", "yep", "yup", "sure", "certainly", "absolutely"}
        offer = dialogue.offers[-1]
        dialogue.offers = []
        if offer.get("kind") == "intent_choice":
            routes = offer.get("routes", ())
            selected_route = routes[0] if said_yes else routes[1]
            intent = UserIntentHypothesis(
                dialogue_act="answer-clarification",
                task_intent="resolve-ambiguity",
                decision="selected",
                matched_frame=offer["matched_frame"],
                context_predicates=("pending_intent_choice",),
                alternatives=(offer["alternatives"][1 if said_yes else 0],),
                selected_value=selected_route,
                basis="portable_dialogue_model",
                evidence_refs=tuple(offer["evidence_refs"]),
                runtime_route=selected_route,
            )
            act = "answer-clarification"
            return with_intent(_runtime_route_reply(
                dialogue, selected_route, text,
                research_index=research_index,
                pending_claims=pending_claims))
        intent = UserIntentHypothesis(
            dialogue_act="accept-offer" if said_yes else "decline-offer",
            task_intent="continue-current-task",
            decision="selected",
            matched_frame="offer-" + ("accept" if said_yes else "decline"),
            context_predicates=("open_offer",),
            selected_value=offer["kind"],
        )
        if offer["kind"] == "confirm_statement":
            reply = (_learn_statement(dialogue, offer, text) if said_yes else
                     DialogueTurn("social", text, text,
                                  text="Okay, I won't remember that."))
        elif said_yes:
            reply = DialogueTurn("social", text, text,
                                 text="Okay, here they are.",
                                 action=offer["action"])
        else:
            reply = DialogueTurn("social", text, text,
                                 text="Okay, I will leave them for now.")
        return with_intent(reply)

    intent_routes = _ambiguous_runtime_routes(intent) if intent is not None else ()
    if (intent_routes and not dialogue.offers
            and dialogue.pending_result is None
            and dialogue.pending_binding is None):
        first_label, first_action = _RUNTIME_ROUTE_WORDING[intent_routes[0]]
        second_label, _second_action = _RUNTIME_ROUTE_WORDING[intent_routes[1]]
        dialogue.offers.append({
            "kind": "intent_choice",
            "routes": intent_routes,
            "turns_left": _OFFER_LIFETIME,
            "matched_frame": intent.matched_frame,
            "alternatives": intent.alternatives,
            "evidence_refs": intent.evidence_refs,
        })
        return with_intent(DialogueTurn(
            "clarify", text, text,
            text=(f"I can read that as {first_label} or {second_label}. "
                  f"Should I {first_action}? Say yes for {first_label} or "
                  f"no for {second_label}.")))

    if dialogue.pending_dialogue_slot == "elaboration_topic":
        if _CANCEL_FOLLOWUP_RE.fullmatch(text.strip()):
            dialogue.pending_dialogue_slot = None
            return with_intent(DialogueTurn(
                "social", text, text,
                text="Okay, I cancelled that follow-up."))
        topic_reply = _elaboration_topic_reply(text)
        if topic_reply and act is None:
            dialogue.pending_dialogue_slot = None
            topic = topic_reply.group("topic").strip()
            card = dialogue.overview(topic)
            if card is not None:
                return with_intent(card)
            return with_intent(DialogueTurn(
                "clarify", text, text,
                text=(f"I couldn't match ‘{topic}’ to an entity with accepted "
                      "facts. Ask a specific question about it, or name an "
                      "entity I have accepted facts about.")))
        # A new question or conversational act supersedes the open slot.
        dialogue.pending_dialogue_slot = None

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
    correction = (_CORRECTION_RE.fullmatch(text.strip())
                  if act is None and dialogue.pending_result is None else None)
    if correction is not None and dialogue.last_question is not None:
        entity = correction.group("entity").strip()
        turn = dialogue.turn(f"What about {entity}?",
                             research_index=research_index)
        answered = turn.response is not None and turn.response.status == "answered"
        intent = UserIntentHypothesis(
            dialogue_act="correction",
            task_intent="correct-result",
            decision="selected" if answered else "ambiguous",
            matched_frame="correction-rebind-entity",
            context_predicates=("previous_grounded_question",),
            selected_value=entity,
        )
        if answered:
            turn.text = (f"Understood. Asking again as ‘{turn.resolved_question}’.\n"
                         f"{turn.text}")
        return with_intent(turn)
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
    if act is None and dialogue.pending_result is None:
        proposal = _propose_statement(dialogue, text)
        if proposal is not None:
            proposed = bool(dialogue.offers)
            intent = UserIntentHypothesis(
                dialogue_act="inform",
                task_intent="provide-information",
                decision="ambiguous" if proposed else "selected",
                matched_frame="user-statement",
                context_predicates=("plain-statement",),
                alternatives=("remember", "ignore") if proposed else (),
            )
            return with_intent(proposal)
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
        if pending_claims:
            reply += " Use /pending-candidates to inspect them."
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
        reply = "Which entity with accepted facts should I look at in more detail?"
        dialogue.pending_dialogue_slot = "elaboration_topic"
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

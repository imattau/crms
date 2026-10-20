"""Deterministic conversation acts that stay separate from evidence retrieval."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from crms_dialogue import (CRMSDialogue, DialogueTurn, UserIntentHypothesis,
                           infer_open_question_slot)


_ACTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("greeting", re.compile(
        r"^(?:hi(?:\s+there)?|hello(?:\s+there)?|hey(?:\s+there)?|"
        r"good\s+(?:morning|afternoon|evening)|how\s+are\s+you)[?.! ]*$",
        re.IGNORECASE)),
    ("farewell", re.compile(
        r"^(?:goodbye|bye|see\s+you|take\s+care)[?.! ]*$", re.IGNORECASE)),
    ("thanks", re.compile(r"^(?:thanks|thank\s+you|thx)[.! ]*$", re.IGNORECASE)),
    ("acknowledgement", re.compile(
        r"^(?:ok|okay|got\s+it|understood|"
        r"ok(?:ay)?[, ]+(?:great|nice|perfect|i\s+got\s+it))[.! ]*$",
        re.IGNORECASE)),
    ("acknowledgement", re.compile(
        r"^(?:(?:that|it)\s+(?:sounds|looks|seems)\s+"
        r"(?:good|nice|great|fine|perfect|lovely|wonderful)|"
        r"that(?:'ll| will)\s+be\s+(?:good|fine|great|perfect))"
        r"[.! ]*$", re.IGNORECASE)),
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
_AFFIRMATIVE_DETAIL_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|sure)[, ]+(?:i(?:'d| would| want| prefer| need)\b|"
    r"we(?:'d| would| want| prefer| need)\b|one\s+that\b|something\s+that\b|"
    r"with\b|and\b)", re.IGNORECASE)
_NEGATIVE_DETAIL_RE = re.compile(
    r"^(?:no|nope|nah|not really)\b(?:[, ]+(?P<detail>.+))?[.!? ]*$",
    re.IGNORECASE)
_NEGATIVE_REQUEST_PREFIX_RE = re.compile(
    r"^(?:no|nope|nah)[,.!]\s+(?:just\s+)?(?P<request>.+)$",
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
_SESSION_SLOT_RECALL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("date_time", re.compile(
        r"^(?:what|which)\s+(?:time|date|day)\s+(?:did i|have i)\s+"
        r"(?:give(?: you)?|say(?: to you)?|tell you|ask for|choose|select)$|"
        r"^when\s+(?:did i|have i)\s+(?:say|tell you|choose|select)$",
        re.IGNORECASE)),
    ("location", re.compile(
        r"^(?:what|which)\s+(?:city|location|area)\s+(?:did i|have i)\s+"
        r"(?:give(?: you)?|say(?: to you)?|tell you|choose|ask for)$|"
        r"^where\s+(?:did i|have i)\s+(?:say|tell you|choose|select)$",
        re.IGNORECASE)),
    ("party_size", re.compile(
        r"^(?:how many people|what party size|what number of people)\s+"
        r"(?:did i|have i)\s+(?:say|give(?: you)?|tell you|ask for)$",
        re.IGNORECASE)),
    ("seating", re.compile(
        r"^(?:what|which)\s+seating(?: preference)?\s+(?:did i|have i)\s+"
        r"(?:say|give|tell you|request|ask for|choose)$",
        re.IGNORECASE)),
    ("cuisine", re.compile(
        r"^(?:what|which)\s+(?:cuisine|food)\s+(?:did i|have i)\s+"
        r"(?:say|give|tell you|request|ask for|choose)$",
        re.IGNORECASE)),
    ("restaurant_choice", re.compile(
        r"^(?:what|which)\s+restaurant\s+(?:did i|have i)\s+"
        r"(?:say|give|tell you|choose|select|pick)$",
        re.IGNORECASE)),
)
_SESSION_SLOT_CORRECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("date_time", re.compile(
        r"^(?:actually[, ]+)?(?:change|set|update|correct)\s+(?:the\s+)?"
        r"(?:date|time|day|date and time)\s+(?:to|as)\s+(?P<value>.+)$",
        re.IGNORECASE)),
    ("location", re.compile(
        r"^(?:actually[, ]+)?(?:change|set|update|correct)\s+(?:the\s+)?"
        r"(?:location|city|area)\s+(?:to|as)\s+(?P<value>.+)$",
        re.IGNORECASE)),
    ("party_size", re.compile(
        r"^(?:actually[, ]+)?(?:change|set|update|correct)\s+(?:the\s+)?"
        r"(?:party size|number of people)\s+(?:to|as)\s+(?P<value>.+)$",
        re.IGNORECASE)),
    ("seating", re.compile(
        r"^(?:actually[, ]+)?(?:change|set|update|correct)\s+(?:the\s+)?"
        r"(?:seating|seating preference)\s+(?:to|as)\s+(?P<value>.+)$",
        re.IGNORECASE)),
    ("cuisine", re.compile(
        r"^(?:actually[, ]+)?(?:change|set|update|correct)\s+(?:the\s+)?"
        r"(?:cuisine|food preference)\s+(?:to|as)\s+(?P<value>.+)$",
        re.IGNORECASE)),
    ("restaurant_choice", re.compile(
        r"^(?:actually[, ]+)?(?:change|set|update|correct)\s+(?:the\s+)?"
        r"(?:restaurant|restaurant choice)\s+(?:to|as)\s+(?P<value>.+)$",
        re.IGNORECASE)),
)
_SESSION_SLOT_LABELS = {
    "date_time": "date or time", "location": "location",
    "party_size": "party size", "seating": "seating preference",
    "cuisine": "cuisine", "restaurant_choice": "restaurant choice",
}
_SESSION_SLOT_QUESTIONS = {
    "date_time": "What date or time should I use?",
    "location": "What location should I use?",
    "party_size": "How many people should I plan for?",
    "seating": "What seating preference should I use?",
    "cuisine": "What cuisine should I use?",
    "restaurant_choice": "Which restaurant should I use?",
}
_RESERVATION_DRAFT_SLOT_ORDER = (
    "restaurant_choice", "date_time", "party_size")
_WEEKDAY_WORD = r"(?:mon|tues|wednes|thurs|fri|satur|sun)day"
_RESERVATION_DATE_TIME_RE = re.compile(
    r"\b(?P<when>(?:(?:(?:next|this)\s+)?" + _WEEKDAY_WORD
    + r"|today|tomorrow|tonight|this\s+(?:morning|afternoon|evening))"
    r"(?:\s+at\s+(?:\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?"
    r"|noon|midnight))?)\b", re.IGNORECASE)
_RESERVATION_TIME_ONLY_RE = re.compile(
    r"\bat\s+(?P<time>\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?"
    r"|noon|midnight)\b", re.IGNORECASE)
_RESERVATION_PARTY_SIZE_RE = re.compile(
    r"\b(?:party\s+of|table\s+for|for)\s+"
    r"(?P<count>\d{1,2}|one|two|three|four|five|six|seven|eight|nine|"
    r"ten|eleven|twelve)(?=\s*(?:people|persons|guests|of\s+us)?\b)",
    re.IGNORECASE)
_RESERVATION_NAME_STOP = (
    r"for|on|at|today|tomorrow|tonight|this\s+(?:morning|afternoon|evening)|"
    + _WEEKDAY_WORD)
_RESERVATION_NAME_RE = re.compile(
    r"\bat\s+(?P<name>[\w][\w&'’.-]*(?:\s+[\w][\w&'’.-]*){0,4}?)"
    r"(?=\s+(?:" + _RESERVATION_NAME_STOP + r")\b|[,;.!?]|$)",
    re.IGNORECASE)
_NON_RESTAURANT_NAMES = {
    "a restaurant", "the restaurant", "a table", "the table",
    "a place", "somewhere", "home",
}


def _extract_reservation_request_details(text: str) -> dict[str, str]:
    """Extract only explicit, bounded values from a reservation request.

    These are user-provided session details, never facts. Unrecognized or
    ambiguous wording remains unfilled and is requested conversationally.
    """
    details: dict[str, str] = {}
    party = _RESERVATION_PARTY_SIZE_RE.search(text)
    if party is not None:
        details["party_size"] = party.group("count").strip()

    when = _RESERVATION_DATE_TIME_RE.search(text)
    if when is not None:
        details["date_time"] = " ".join(when.group("when").split())
        time_match = re.search(
            r"\s+at\s+(?:\d{1,2}(?::\d{2})?\s*"
            r"(?:a\.?m\.?|p\.?m\.?)?|noon|midnight)$",
            when.group("when"), flags=re.IGNORECASE)
        if time_match is None:
            time = _RESERVATION_TIME_ONLY_RE.search(text)
            if time is not None:
                details["date_time"] += " " + time.group("time").strip()
    else:
        time = _RESERVATION_TIME_ONLY_RE.search(text)
        if time is not None:
            details["date_time"] = time.group("time").strip()

    for name in _RESERVATION_NAME_RE.finditer(text):
        candidate = " ".join(name.group("name").split()).strip(" ,")
        if (candidate.casefold() not in _NON_RESTAURANT_NAMES
                and not re.search(r"\d", candidate)):
            details["restaurant_choice"] = candidate
            break
    return details


_ELABORATION_TOPIC_REPLY_RE = re.compile(
    r"^(?:about\s+)?(?P<topic>[\w][\w '&’.-]{0,118})[.! ]*$",
    re.IGNORECASE)
_CANCEL_FOLLOWUP_RE = re.compile(
    r"^(?:never mind|forget it|cancel that|cancel)[.! ]*$", re.IGNORECASE)
_WH_QUESTION_RE = re.compile(
    r"^(?:who|whom|whose|what|which|when|where|why|how)\b", re.IGNORECASE)
_YES_NO_QUESTION_RE = re.compile(
    r"^(?:(?:okay|ok|sure|great|and|so|well)[, ]+)*(?:(?:am|is|are|was|were|"
    r"do|does|did|has|have|had|can|could|will|would|shall|should|may|might)"
    r"\b.+|you said\b.+|(?:so\s+)?i have\b.+|that(?:['’]s| is)\b.+)"
    r"\?(?:\s+(?:for example|for instance|e\.g\.).*)?\s*$",
    re.IGNORECASE)
_CONFIRMATION_STATEMENT_RE = re.compile(
    r"^(?:(?:okay|ok|sure|great|and|so)[, ]+)*so i have\b.+$",
    re.IGNORECASE)


def is_open_yes_no_prompt(text: str) -> bool:
    """Recognize yes/no questions and reservation summaries awaiting approval."""
    stripped = text.strip()
    if (_YES_NO_QUESTION_RE.fullmatch(stripped)
            or _CONFIRMATION_STATEMENT_RE.fullmatch(stripped)):
        return True
    if not stripped.endswith("?"):
        return False

    # Assistant turns can give context before asking for a yes/no decision:
    # "The total is $23.89. Can I continue with the purchase?" The whole
    # message is not itself an auxiliary-led question, so inspect the final
    # sentence and, when needed, its final comma-delimited question clause.
    final_sentence = re.split(r"(?<=[.!?])\s+", stripped)[-1].strip()
    candidates = [final_sentence]
    candidates.extend(part.strip() for part in
                      re.split(r"[,;]\s*", final_sentence)[1:])
    for candidate in candidates:
        candidate = re.sub(r"^(?:and|so)\s+", "", candidate,
                           flags=re.IGNORECASE)
        if (candidate.endswith("?")
                and _YES_NO_QUESTION_RE.fullmatch(candidate)):
            return True
    return False


def _elaboration_topic_reply(text: str) -> re.Match[str] | None:
    """Match a short entity-like answer, never a newly asked question."""
    stripped = text.strip()
    if (_WH_QUESTION_RE.match(stripped)
            or _YES_NO_QUESTION_RE.fullmatch(stripped)):
        return None
    return _ELABORATION_TOPIC_REPLY_RE.fullmatch(stripped)


def _session_slot_recall(text: str) -> str | None:
    """Recognize a direct question about one bounded session task value."""
    normalized = " ".join(text.strip().rstrip("?.! ").split())
    for slot, pattern in _SESSION_SLOT_RECALL_PATTERNS:
        if pattern.fullmatch(normalized):
            return slot
    return None


def _session_slot_correction(text: str) -> tuple[str, str] | None:
    """Parse a correction only when it names a supported session-slot type."""
    normalized = " ".join(text.strip().split())
    if "?" in normalized or "\n" in normalized:
        return None
    for slot, pattern in _SESSION_SLOT_CORRECTION_PATTERNS:
        match = pattern.fullmatch(normalized.rstrip(".! "))
        if match is None:
            continue
        value = " ".join(match.group("value").strip().rstrip(".! ").split())
        if value.casefold().endswith(" instead"):
            value = value[:-len(" instead")].rstrip()
        if value and len(value) <= 256:
            return slot, value
    return None
_MODAL_REQUEST_RE = re.compile(
    r"^(?:can|could|would|will)\s+(?:you|i|we)\s+"
    r"(?:please\s+)?(?P<verb>[a-z]+)\b(?:\s+.+)?[?.! ]*$", re.IGNORECASE)
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
_DIRECT_REQUEST_VERBS = _INFORMATION_REQUEST_VERBS | _ACTION_REQUEST_VERBS
_DIRECT_IMPERATIVE_REQUEST_RE = re.compile(
    r"^(?:please\s+)?(?P<verb>"
    + "|".join(sorted(_DIRECT_REQUEST_VERBS, key=len, reverse=True))
    + r")\b\s+\S.+$", re.IGNORECASE)
_RESERVATION_NAME_SLOT_RESPONSE_RE = re.compile(
    r"^(?:please\s+)?(?:put\s+(?:it|this|the reservation)\s+under|"
    r"use\s+the\s+name)\s+(?P<name>[\w][\w’' .-]{0,79})[.! ]*$",
    re.IGNORECASE)
_EMBEDDED_WH_REQUEST_RE = re.compile(
    r"^(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+)?"
    r"(?:tell|show|explain|describe)\s+me\s+"
    r"(?P<question>(?:who|whom|whose|what|which|when|where|why|how)"
    r"\b.+?)[?.! ]*$", re.IGNORECASE)
_INDIRECT_PRONOUN_AUX_RE = re.compile(
    r"^(?P<wh>when|where|what|which|why|how)\s+"
    r"(?P<subject>it|they|he|she|this|that)\s+"
    r"(?P<aux>is|are|was|were|does|do|did|has|have|had|"
    r"can|could|will|would|should|might|must)\s+"
    r"(?P<rest>.+)$", re.IGNORECASE)
_EXPLICIT_RESERVATION_REQUEST_RE = re.compile(
    r"^(?:(?:i|we)\s+(?:(?:need|want)\s+(?:to\s+)?|"
    r"(?:would|could)\s+like\s+to\s+)"
    r"(?:make|place|book|reserve|set\s+up)\s+(?:(?:a|the)\s+)?"
    r"(?:(?:dinner|lunch)\s+)?(?:reservation|booking|table)\b|"
    r"(?:i|we)['’]d\s+like\s+to\s+(?:make|place|book|reserve|set\s+up)\s+"
    r"(?:(?:a|the)\s+)?(?:(?:dinner|lunch)\s+)?"
    r"(?:reservation|booking|table)\b|"
    r"(?:i|we)(?:['’]d|\s+(?:would|could))\s+like\s+"
    r"(?:you\s+to\s+)?(?:make|place|book|reserve|set\s+up)\s+"
    r"(?:(?:a|the)\s+)?(?:(?:dinner|lunch)\s+)?restaurant\b|"
    r"(?:i|we)\s+(?:need|want)\s+(?:(?:a|the)\s+)?"
    r"(?:(?:dinner|lunch)\s+)?reservation\b|"
    r"(?:i|we)\s+(?:am|was)\s+(?:trying|looking|hoping)\s+to\s+"
    r"(?:make|place|book|reserve|set\s+up)\s+(?:(?:a|the)\s+)?"
    r"(?:(?:dinner|lunch)\s+)?(?:reservation|booking|table)\b|"
    r"(?:can|could|would)\s+we\s+(?:please\s+)?"
    r"(?:make|place|book|reserve|set\s+up)\s+(?:(?:a|the)\s+)?"
    r"(?:(?:dinner|lunch)\s+)?(?:reservation|booking|table)\b|"
    r"(?:let['’]s|please)\s+(?:make|place|book|reserve|set\s+up)\s+"
    r"(?:(?:a|the)\s+)?(?:(?:dinner|lunch)\s+)?"
    r"(?:reservation|booking|table)\b|"
    r"(?:please\s+)?(?:book|reserve)\s+(?:(?:a|the)\s+)?"
    r"(?:(?:dinner|lunch)\s+)?(?:reservation|booking|table)\b)"
    r".*[.!? ]*$", re.IGNORECASE)
_RESERVATION_COMMITMENT_RE = re.compile(
    r"\b(?:i|we)(?:['’]d|\s+(?:would|could))\s+"
    r"(?:like|love|want)\s+to\s+(?:make|place|book|reserve|set\s+up|do)\s+"
    r"(?:(?:a|the)\s+)?(?:(?:dinner|lunch)\s+)?"
    r"(?:reservation|booking|table)\b|"
    r"\b(?:i|we)(?:['’]d|\s+(?:would|could))\s+like\s+"
    r"(?:you\s+to\s+)?(?:make|place|book|reserve|set\s+up)\s+"
    r"(?:(?:a|the)\s+)?(?:(?:dinner|lunch)\s+)?restaurant\b|"
    r"\b(?:i|we)\s+(?:need|want)\s+(?:to\s+)?"
    r"(?:make|place|book|reserve|set\s+up|do)\s+"
    r"(?:(?:a|the)\s+)?(?:(?:dinner|lunch)\s+)?"
    r"(?:reservation|booking|table)\b|"
    r"\b(?:i|we)(?:['’]ll|\s+will)\s+(?:make|place|book|reserve|set\s+up)\s+"
    r"(?:(?:a|the)\s+)?(?:(?:dinner|lunch)\s+)?"
    r"(?:reservation|booking|table)\b|"
    r"\b(?:i|we)(?:['’]m|\s+am|\s+was)\s+"
    r"(?:trying|looking|hoping)\s+to\s+(?:make|place|book|reserve|set\s+up)\s+"
    r"(?:(?:a|the)\s+)?(?:(?:dinner|lunch)\s+)?"
    r"(?:reservation|booking|table)\b|"
    r"\b(?:let['’]s)\s+(?:do|make|place|book|reserve|set\s+up)\s+"
    r"(?:(?:a|the)\s+)?(?:(?:dinner|lunch)\s+)?"
    r"(?:reservation|booking|table)\b|"
    r"(?:^|[.!?]\s+)(?:(?:okay|ok)[, ]+)?(?:just\s+)?"
    r"(?:make|place|book|reserve|set\s+up)\s+(?:(?:a|the)\s+)?"
    r"(?:(?:dinner|lunch)\s+)?(?:reservation|booking|table)\b|"
    r"\b(?:can|could|would)\s+(?:we|you|i)\s+(?:please\s+)?"
    r"(?:make|place|book|reserve|set\s+up)\s+(?:(?:a|the)\s+)?"
    r"(?:(?:dinner|lunch)\s+)?(?:reservation|booking|table)\b",
    re.IGNORECASE)
_RESERVATION_REQUEST_QUESTION_RE = re.compile(
    r"(?:^|[.!?]\s+)(?:can|could|would)\s+(?:we|you|i)\s+"
    r"(?:please\s+)?(?:make|place|book|reserve|set\s+up)\s+"
    r"(?:(?:a|the)\s+)?(?:(?:dinner|lunch)\s+)?"
    r"(?:reservation|booking|table)\b",
    re.IGNORECASE)
_DIRECT_SEARCH_REQUEST_RE = re.compile(
    r"(?:^|[.!?,;]\s*)"
    r"(?:(?:hi|hello|hey)(?:\s+there)?[, ]+)?"
    r"(?:(?:i|we)(?:['’]m|\s+am|\s+was)\s+looking\s+for|"
    r"looking\s+for|"
    r"(?:i|we)\s+(?:need|want)\s+to\s+"
    r"(?:find|look\s+for|search\s+for|locate)|"
    r"(?:i|we)\s+(?:need|want)\s+(?:a|the)\s+"
    r"(?:place|restaurant|recommendation|option)\b)\s+\S",
    re.IGNORECASE)
_EXPLICIT_GENERIC_TASK_REQUEST_RE = re.compile(
    r"^(?:(?:good\s+(?:morning|afternoon|evening)|hey|hi|hello)[,!. ]+)?"
    r"(?:(?:i|we)(?:['’]d|\s+(?:would|could))\s+like\s+|"
    r"(?:i|we)\s+(?:want|need|wanted|needed)\s+|"
    r"(?:i|we)(?:['’]m|\s+(?:am|was|were))\s+"
    r"(?:hoping|trying|looking)\s+to\s+)"
    r"(?:to\s+)?(?P<request>.+?)[.! ]*$",
    re.IGNORECASE)
_INFORMATION_COMPLEMENT_RE = re.compile(
    r"^(?:know\b|learn\b|find\s+out\b|see\s+if\b|check\s+if\b|"
    r"ask\b|understand\b|be\s+told\b)", re.IGNORECASE)
_AVAILABILITY_SEARCH_RE = re.compile(
    r"\b(?:looking|trying|hoping|want)\s+to\s+see\s+if\b.+\b"
    r"(?:playing|showing|available)\b|"
    r"\b(?:looking|trying|hoping)\s+to\s+find\s+showtimes?\b",
    re.IGNORECASE)


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


def _open_question_task_intent(dialogue: CRMSDialogue,
                               open_question: dict[str, str]) -> str:
    """Resolve a short answer's task from the open prompt and active goal.

    The active task is session context; an explicit task named in the current
    assistant prompt can start a more specific phase before the user's answer
    supplies it. Search-constraint slots under an information-seeking task are
    reported as constraints rather than inheriting the broad task label.
    """
    prompt = " ".join(open_question.get("prompt", "").casefold().split())
    active_task = dialogue.active_task_intent
    search_prompt_cues = (
        "what type of restaurant", "which type of restaurant",
        "what kind of restaurant", "which kind of restaurant",
        "what type of food", "what kind of food", "what style of food",
        "what cuisine", "which cuisine", "restaurant preference",
        "restaurant preferences", "dining preference", "dining preferences",
        "your preferences", "preferences", "characteristic",
        "dining requirement", "dining need", "it would help my search",
        "additional characteristic", "restaurant to have",
        "dietary restriction", "what area", "which area", "where are you",
        "where in ",
    )
    if any(cue in prompt for cue in search_prompt_cues):
        return "provide-constraint"
    if open_question.get("expected_slot") == "confirmation":
        return "resolve-ambiguity"
    if open_question.get("expected_slot") == "reservation_name":
        return "make-reservation"
    if open_question.get("expected_slot") == "choice":
        return "resolve-ambiguity"
    if (re.search(r"\b(?:cancel|cancell?ing)\b", prompt)
            and re.search(r"\breserv(?:e|ation|ations)\b", prompt)):
        return "cancel-reservation"
    if (re.search(r"\b(?:change|modify|update)\b", prompt)
            and re.search(r"\breserv(?:e|ation|ations)\b", prompt)):
        return "change-reservation"
    if (re.search(r"\b(?:book|booking)\b", prompt)
            and re.search(r"\b(?:reservation|restaurant|table)\b", prompt)
            or (re.search(r"\bmake\b", prompt)
                and re.search(r"\breserv(?:ation|ations)\b", prompt))
            or (re.search(r"\b(?:need|want)\b", prompt)
                and re.search(r"\breserv(?:ation|ations)\b", prompt))):
        return "make-reservation"

    slot = open_question.get("expected_slot", "unknown")
    task_parameter_slots = {
        "location", "party_size", "quantity", "date_time", "seating",
        "cuisine", "restaurant_choice", "detail", "entity",
    }
    if (active_task == "other-task" and slot in task_parameter_slots):
        return "provide-constraint"
    if (active_task == "check-availability"
            and slot in {"location", "party_size", "quantity", "date_time",
                         "detail", "entity"}):
        return "provide-constraint"
    if (active_task == "seek-information"
            and slot in {"location", "party_size", "date_time", "seating",
                         "cuisine", "detail"}):
        return "provide-constraint"
    return active_task or "continue-current-task"


def _open_question_dialogue_act(text: str, open_question: dict[str, str],
                                task_intent: str) -> str:
    """Name the conversational move for a response to a typed open question."""
    if (open_question.get("answer_kind") == "yes-no"
            and open_question.get("expected_slot") == "confirmation"):
        normalized = text.strip().casefold()
        if normalized.startswith(("no", "nope", "nah", "not really")):
            return "reject"
        return "confirm"
    if task_intent == "provide-constraint":
        return "provide-information"
    return "answer-clarification"


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

    open_question = dialogue.open_dialogue_question

    # A rejection followed by a recognizable request is still a new request,
    # not merely an answer to the assistant's open choice. Keep bare "No" and
    # non-imperative negative details in the open-question path below.
    request_text = text.strip()
    negative_request = _NEGATIVE_REQUEST_PREFIX_RE.fullmatch(request_text)
    if negative_request is not None:
        proposed_request = negative_request.group("request").strip()
        is_new_request = bool(
            _DIRECT_IMPERATIVE_REQUEST_RE.fullmatch(proposed_request)
            or _EXPLICIT_RESERVATION_REQUEST_RE.fullmatch(proposed_request)
            or _RESERVATION_COMMITMENT_RE.search(proposed_request))
        if is_new_request:
            request_text = proposed_request

    # A clear new imperative is a new task, even while the assistant is
    # waiting for a short clarification value. Do not absorb requests such as
    # “Tell me a joke” as the entity or detail requested by the prior turn.
    direct_imperative = _DIRECT_IMPERATIVE_REQUEST_RE.fullmatch(request_text)
    reservation_request_text = request_text
    reservation_commitment = bool(_RESERVATION_COMMITMENT_RE.search(
        reservation_request_text))
    trailing_clause = re.split(
        r"(?<=[.!?])\s+", reservation_request_text)[-1].strip()
    trailing_request = _MODAL_REQUEST_RE.fullmatch(trailing_clause)
    if (reservation_commitment and trailing_request is not None
            and trailing_request.group("verb").casefold()
            in _INFORMATION_REQUEST_VERBS):
        return UserIntentHypothesis(
            dialogue_act="request-action",
            task_intent="seek-information",
            goal_intent="make-reservation",
            decision="selected",
            matched_frame="reservation-goal-with-information-request",
            context_predicates=("direct-user-request",),
        )
    is_explicit_reservation_request = bool(
        _EXPLICIT_RESERVATION_REQUEST_RE.fullmatch(reservation_request_text)
        or reservation_commitment)
    if is_explicit_reservation_request:
        return UserIntentHypothesis(
            dialogue_act="request-action",
            task_intent="make-reservation",
            goal_intent="make-reservation",
            decision="selected",
            matched_frame=("negative-with-explicit-reservation-request"
                           if request_text != text.strip()
                           else "explicit-reservation-request"),
            context_predicates=("direct-user-request",),
        )
    name_slot_reply = bool(
        open_question is not None
        and open_question.get("expected_slot") == "reservation_name"
        and _RESERVATION_NAME_SLOT_RESPONSE_RE.fullmatch(text.strip()))
    if (direct_imperative is not None
            and _YES_NO_QUESTION_RE.fullmatch(text.strip()) is None
            and classify_act(text) is None
            and _session_slot_correction(text) is None
            and not name_slot_reply):
        verb = direct_imperative.group("verb").casefold()
        task_intent = ("seek-information" if verb in _INFORMATION_REQUEST_VERBS
                       else "other-task")
        return UserIntentHypothesis(
            dialogue_act="request-action",
            task_intent=task_intent,
            goal_intent=task_intent,
            decision="selected",
            matched_frame=("negative-with-direct-imperative"
                           if request_text != text.strip()
                           else "direct-imperative-request"),
            context_predicates=("direct-user-request",),
        )

    if open_question is not None:
        intent_model = getattr(dialogue, "intent_model", None)
        context_provider = getattr(dialogue, "intent_context", None)
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

    if open_question is not None and len(text) <= 512:
        is_yes_no = _BARE_YES_NO_RE.fullmatch(text.strip()) is not None
        is_fresh_question = (_WH_QUESTION_RE.match(text.strip()) is not None
                             or _YES_NO_QUESTION_RE.fullmatch(text.strip())
                             is not None)
        social_act = classify_act(text)
        expected_yes_no = open_question["answer_kind"] == "yes-no"
        is_negative_answer = _NEGATIVE_DETAIL_RE.fullmatch(text.strip()) is not None
        if (expected_yes_no
                and _AFFIRMATIVE_DETAIL_RE.match(text.strip())
                and not is_fresh_question):
            task_intent = _open_question_task_intent(dialogue, open_question)
            if task_intent == "provide-constraint":
                return UserIntentHypothesis(
                    dialogue_act="provide-information",
                    task_intent=task_intent,
                    decision="selected",
                    matched_frame="affirmative-with-preference-details",
                    context_predicates=("pending_assistant_question",
                                        "awaiting_yes_no_answer",
                                        "restaurant_preference_prompt"),
                    selected_value=text.strip(),
                )
        if (expected_yes_no
                and open_question.get("expected_slot") != "confirmation"
                and is_negative_answer):
            prompt_task = _open_question_task_intent(dialogue, open_question)
            if prompt_task in {"make-reservation", "provide-constraint"}:
                return UserIntentHypothesis(
                    dialogue_act="answer-clarification",
                    task_intent="continue-current-task",
                    decision="selected",
                    matched_frame="negative-answer-to-task-question",
                    context_predicates=("pending_assistant_question",
                                        "awaiting_yes_no_answer"),
                    selected_value=text.strip(),
                )
        if (expected_yes_no and is_yes_no
                and open_question.get("expected_slot") != "confirmation"):
            prompt_task = _open_question_task_intent(dialogue, open_question)
            if prompt_task == "provide-constraint":
                if text.strip().casefold().startswith("no"):
                    return UserIntentHypothesis(
                        dialogue_act="answer-clarification",
                        task_intent="continue-current-task",
                        decision="selected",
                        matched_frame="no-additional-preferences",
                        context_predicates=("pending_assistant_question",
                                            "restaurant_preference_prompt"),
                        selected_value=text.strip(),
                    )
                return UserIntentHypothesis(
                    dialogue_act="answer-clarification",
                    task_intent=None,
                    decision="ambiguous",
                    matched_frame="yes-without-preference-details",
                    context_predicates=("pending_assistant_question",
                                        "restaurant_preference_prompt"),
                    alternatives=("provide the restaurant preferences",
                                  "continue without additional preferences"),
                )
        if is_yes_no and not expected_yes_no:
            slot = open_question.get("expected_slot", "detail")
            label = _SESSION_SLOT_LABELS.get(slot, "requested detail")
            return UserIntentHypothesis(
                dialogue_act="answer-clarification",
                task_intent="resolve-ambiguity",
                decision="ambiguous",
                matched_frame="yes-no-response-to-detail-question",
                context_predicates=("pending_assistant_question",
                                    "awaiting_user_detail",
                                    f"awaiting_slot_{slot}"),
                alternatives=(f"provide the requested {label}",
                             "ask a yes/no question"),
            )
        is_typed_parameter_reply = (
            not expected_yes_no and not is_yes_no and not is_fresh_question
            and "?" not in text
            and social_act is None
            and _EXPLICIT_RESERVATION_REQUEST_RE.fullmatch(text) is None
            and (len(re.findall(r"[\w’'-]+", text)) <= 24
                 or (open_question.get("expected_slot") in {
                     "location", "party_size", "quantity", "date_time",
                     "seating", "cuisine", "restaurant_type"}
                     ))
        )
        if ((is_yes_no and expected_yes_no and not is_fresh_question)
                or is_typed_parameter_reply):
            task_intent = _open_question_task_intent(dialogue, open_question)
            return UserIntentHypothesis(
                dialogue_act=_open_question_dialogue_act(
                    text, open_question, task_intent),
                task_intent=task_intent,
                goal_intent=(dialogue.active_task_intent
                             if task_intent == "resolve-ambiguity" else None),
                decision="selected",
                matched_frame="answer-to-open-dialogue-question",
                context_predicates=("pending_assistant_question",
                                    "awaiting_yes_no_answer" if expected_yes_no
                                    else "awaiting_user_detail"),
                selected_value=text.strip(),
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

    reservation_request = text.strip()
    if _AVAILABILITY_SEARCH_RE.search(reservation_request):
        return UserIntentHypothesis(
            dialogue_act="request-action",
            task_intent="check-availability",
            goal_intent="check-availability",
            decision="selected",
            matched_frame="explicit-availability-search",
            context_predicates=("direct-user-request",))

    # Treat explicit first-person wants/needs for an action or service as a
    # broad task goal. Information-seeking complements are left to the search
    # and question routes below; the rule does not infer a task from a bare
    # topic mention.
    generic_request = _EXPLICIT_GENERIC_TASK_REQUEST_RE.fullmatch(
        reservation_request)
    if generic_request is not None:
        complement = (generic_request.group("request")
                      or generic_request.group("looking") or "").strip()
        if _INFORMATION_COMPLEMENT_RE.match(complement):
            return UserIntentHypothesis(
                dialogue_act="request-action",
                task_intent="seek-information",
                goal_intent="seek-information",
                decision="selected",
                matched_frame="explicit-information-request",
                context_predicates=("direct-user-request",
                                    "information-seeking-complement"))
        else:
            return UserIntentHypothesis(
                dialogue_act="request-action",
                task_intent="other-task",
                goal_intent="other-task",
                decision="selected",
                matched_frame="explicit-generic-task-request",
                context_predicates=("direct-user-request",
                                    "explicit-action-complement"))

    # A direct search statement establishes an information-seeking goal.
    # This runs after open-question handling and explicit booking detection so
    # a cuisine/slot answer or reservation commitment keeps its active intent.
    if _DIRECT_SEARCH_REQUEST_RE.search(reservation_request):
        return UserIntentHypothesis(
            dialogue_act="request-action",
            task_intent="seek-information",
            goal_intent="seek-information",
            decision="selected",
            matched_frame="explicit-search-request",
            context_predicates=("direct-user-request",),
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
            goal_intent=portable.get("goal_intent"),
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
                goal_intent=("seek-information"
                             if verb in _INFORMATION_REQUEST_VERBS
                             else "other-task"),
                decision="selected",
                matched_frame="modal-request",
                context_predicates=("direct-user-request",),
            )
    if (_WH_QUESTION_RE.match(stripped)
            or _YES_NO_QUESTION_RE.fullmatch(stripped)):
        availability_followup = bool(
            dialogue.active_task_intent is not None
            and re.search(r"\b(?:showtimes?|screenings?|playing|available)\b",
                          stripped, re.IGNORECASE))
        return UserIntentHypothesis(
            dialogue_act="question",
            task_intent=("check-availability" if availability_followup
                         else "seek-information"),
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


def _present_direct_search_matches(
        dialogue: CRMSDialogue, turn: DialogueTurn,
        research_index: Any | None) -> DialogueTurn:
    """Show exact retrieved excerpts for a direct, open-ended search request.

    Search hits are source matches, not accepted facts or verified
    recommendations. Only citations actually shown become selectable
    conversation context.
    """
    research = turn.research
    if research_index is None or research is None:
        return turn
    if research.status != "sources_found":
        if research.status == "unknown":
            turn.text = ("I couldn't find a matching source for what you're "
                         "looking for, so I can't recommend an option from "
                         "the indexed material.")
        return turn
    request = turn.question.casefold()
    target_match = re.search(
        r"(?:looking for|need to find|want to find|search for|"
        r"need|want)\s+(?P<target>.+?)(?:[.!?]|$)", request)
    target_terms: set[str] = set()
    location_terms: set[str] = set()
    if target_match is not None:
        target_parts = re.split(
            r"\b(?:in|near|around|at|within)\b",
            target_match.group("target"), maxsplit=1)
        target_text = target_parts[0]
        target_terms = set(re.findall(r"[a-z0-9]+", target_text)) - {
            "i", "we", "am", "are", "was", "were", "a", "an", "the",
            "to", "for", "me", "us", "some", "any", "please", "just",
            "looking", "need", "want", "find", "search", "place", "option",
        }
        if len(target_parts) == 2:
            location_terms = set(re.findall(r"[a-z0-9]+", target_parts[1])) - {
                "i", "we", "a", "an", "the", "please", "just",
            }
    passages = research.passages or []
    visible: list[dict[str, str]] = []
    for passage in passages:
        if not isinstance(passage, dict):
            continue
        matched_terms = {str(term).casefold() for term in
                         passage.get("matched_question_terms", [])}
        if target_terms and not target_terms.intersection(matched_terms):
            continue
        if location_terms and not location_terms.intersection(matched_terms):
            continue
        citation = passage.get("citation")
        if not isinstance(citation, str) or not citation:
            continue
        try:
            excerpt = research_index.resolve_citation(citation)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if not excerpt.strip():
            continue
        visible.append({
            "text": excerpt,
            "document_id": citation.partition("#sha256=")[0],
            "title": str(passage.get("title") or "source"),
            "location": str(passage.get("location") or ""),
            "citation": citation,
        })
        if len(visible) == 3:
            break
    if not visible:
        turn.text = ("I couldn't find a source excerpt that matched what "
                     "you're looking for, so I can't recommend an option "
                     "from the indexed material.")
        return turn

    lines = ["Matching source excerpts (quoted evidence, not verified recommendations):"]
    for number, item in enumerate(visible, 1):
        lines.append(f"{number}. {item['text']}\n   Source: {item['title']}")
    choices = ["first", "second", "third"][:len(visible)]
    lines.append("Ask about the " + ", ".join(choices)
                 + " result to select it.")
    turn.text = "\n".join(lines)
    research.source_sentences = visible
    dialogue.presented_sources = [
        {"citation": item["citation"], "title": item["title"]}
        for item in visible
    ]
    # The dialogue layer may have cleared state for a non-answer. Restore only
    # evidence the user can now see, so follow-ups cannot bind to hidden hits.
    dialogue.source_mentions = dialogue._source_entity_mentions(visible)
    dialogue.topic_entity = (dialogue.source_mentions[0]["entity"]
                             if len(dialogue.source_mentions) == 1 else None)
    dialogue.last_question = turn.resolved_question
    return turn


def respond(dialogue: CRMSDialogue, text: str, *,
            research_index: Any | None = None,
            pending_claims: int = 0) -> DialogueTurn:
    """Handle dialogue acts and route embedded WH requests to question handling."""
    original_text = text
    embedded_request = _EMBEDDED_WH_REQUEST_RE.fullmatch(text.strip())
    if embedded_request is not None:
        question = embedded_request.group("question").strip().rstrip(" .?!")
        indirect = _INDIRECT_PRONOUN_AUX_RE.fullmatch(question)
        if indirect is not None:
            question = " ".join((indirect.group("wh"),
                                 indirect.group("aux"),
                                 indirect.group("subject"),
                                 indirect.group("rest")))
        text = question
        text = text[:1].upper() + text[1:] + "?"
    intent = classify_user_intent(dialogue, text)
    act = classify_act(text)
    preserves_question = bool(
        intent is not None and (
            intent.matched_frame == "elaboration-topic-slot"
            or intent.matched_frame == "yes-no-response-to-detail-question"
            or intent.matched_frame == "yes-without-preference-details"
            or (intent.decision == "selected"
                and intent.dialogue_act in {
                    "answer-clarification", "provide-information",
                    "confirm", "reject"})))
    if dialogue._pending_entity_followup_question(
            text, research_index=research_index) is not None:
        # A named entity is a valid answer to the explicit referent
        # clarification even when the learned intent classifier calls the
        # surface a new question ("What about Eiffel Tower?").
        preserves_question = True
    if dialogue.open_dialogue_question is not None and not preserves_question:
        # A fresh question or unrelated act replaces the prior QUD.
        dialogue.open_dialogue_question = None
    if (act is None and intent is not None and intent.decision == "selected"
            and intent.basis == "portable_dialogue_model"
            and intent.matched_frame != "explicit-search-request"):
        act = intent.runtime_route

    def with_intent(turn: DialogueTurn) -> DialogueTurn:
        if (intent is not None and intent.decision == "selected"
                and intent.dialogue_act == "answer-clarification"
                and dialogue.open_dialogue_question is not None):
            dialogue.remember_session_slot(
                intent.selected_value or "", user_turn=text)
            dialogue.open_dialogue_question = None
        elif (intent is not None and intent.decision == "selected"
              and intent.dialogue_act == "provide-information"
              and dialogue.open_dialogue_question is not None):
            dialogue.open_dialogue_question = None
        elif (intent is not None and intent.decision == "selected"
              and intent.dialogue_act in {"confirm", "reject"}
              and dialogue.open_dialogue_question is not None):
            dialogue.open_dialogue_question = None
        elif (turn.status == "clarify"
              and (turn.text.rstrip().endswith("?")
                   or _CONFIRMATION_STATEMENT_RE.fullmatch(turn.text.strip()))
              and dialogue.open_dialogue_question is None
              and not dialogue.offers and dialogue.pending_result is None
              and dialogue.pending_binding is None):
            answer_kind = ("yes-no" if is_open_yes_no_prompt(turn.text)
                           else "detail")
            expected_slot = infer_open_question_slot(
                turn.text.strip(), answer_kind)
            if expected_slot in dialogue.session_slots:
                # The assistant is asking for this value again; do not expose
                # the previous answer as if it were still current.
                del dialogue.session_slots[expected_slot]
            dialogue.open_dialogue_question = {
                "prompt": turn.text.strip()[:500],
                "answer_kind": answer_kind,
                "expected_slot": expected_slot,
            }
        turn.intent_hypothesis = intent
        dialogue.last_intent_hypothesis = intent
        history_act = (act or (intent.dialogue_act if intent is not None else None)
                       or "question")
        if embedded_request is not None:
            turn.question = original_text
        dialogue.record_turn(original_text, history_act, turn, intent)
        _offer(dialogue, turn)
        return turn

    def reservation_draft_prompt(utterance: str) -> DialogueTurn:
        missing_slot = next((slot for slot in _RESERVATION_DRAFT_SLOT_ORDER
                             if slot not in dialogue.session_slots), None)
        if missing_slot is not None:
            return DialogueTurn(
                "clarify", utterance, utterance,
                text=_SESSION_SLOT_QUESTIONS[missing_slot])
        restaurant = dialogue.session_slots["restaurant_choice"]["value"]
        date_time = dialogue.session_slots["date_time"]["value"]
        party_size = dialogue.session_slots["party_size"]["value"]
        return DialogueTurn(
            "prepared", utterance, utterance,
            text=("Reservation request draft (not submitted):\n"
                  f"- Restaurant: {restaurant}\n"
                  f"- Date/time: {date_time}\n"
                  f"- Party size: {party_size}\n"
                  "No reservation has been made."))

    if (intent is not None and intent.decision == "selected"
            and intent.task_intent == "make-reservation"
            and intent.matched_frame == "explicit-reservation-request"):
        extracted = _extract_reservation_request_details(text)
        for slot, value in extracted.items():
            dialogue.session_slots[slot] = {
                "value": value,
                "question": "Initial reservation request: " + text[:400],
                "updated_by": text[:512],
            }
        progress = reservation_draft_prompt(text)
        if progress.status == "prepared":
            intro = ("I used the details stated in your request to prepare "
                     "this draft. I can't check availability or submit it.\n"
                     + progress.text)
            return with_intent(DialogueTurn(
                progress.status, text, text, text=intro))
        turn = with_intent(DialogueTurn(
            progress.status, text, text, text=progress.text))
        noted = "; ".join(
            f"{_SESSION_SLOT_LABELS[slot]}: {value}"
            for slot, value in extracted.items())
        intro = ("I can prepare a reservation request draft, but I can't "
                 "check availability or submit it.")
        if noted:
            intro += f" I noted {noted} from your request."
        turn.text = intro + "\n" + turn.text
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

    if (intent is not None and intent.decision == "selected"
            and intent.dialogue_act in {"answer-clarification",
                                        "provide-information"}
            and dialogue.open_dialogue_question is not None
            and _session_slot_correction(text) is None):
        if (dialogue.active_task_intent == "make-reservation"
                and intent.dialogue_act == "answer-clarification"
                and dialogue.open_dialogue_question.get("expected_slot")
                    in _RESERVATION_DRAFT_SLOT_ORDER):
            dialogue.remember_session_slot(
                intent.selected_value or text.strip(), user_turn=text)
            dialogue.open_dialogue_question = None
            return with_intent(reservation_draft_prompt(text))
        prompt = (dialogue.open_dialogue_question or {}).get("prompt", "")
        value = (intent.selected_value or text.strip()).rstrip(" .!?")
        if intent.dialogue_act == "provide-information":
            return with_intent(DialogueTurn(
                "social", text, text,
                text="Got it. I’ve noted those restaurant preferences."))
        return with_intent(DialogueTurn(
            "social", text, text,
            text=(f"Got it: {value}. I’ll treat that as your reply to my "
                  f"question: {prompt}")))

    if (intent is not None
            and intent.matched_frame == "yes-without-preference-details"):
        dialogue.open_dialogue_question = None
        return with_intent(DialogueTurn(
            "clarify", text, text,
            text="What restaurant preferences should I use?"))

    if (intent is not None
            and intent.matched_frame == "yes-no-response-to-detail-question"
            and dialogue.open_dialogue_question is not None):
        question = dialogue.open_dialogue_question
        slot = question.get("expected_slot", "detail")
        label = _SESSION_SLOT_LABELS.get(slot, "requested detail")
        return with_intent(DialogueTurn(
            "clarify", text, question.get("prompt", ""),
            text=(f"I was asking for the {label}. "
                  f"{question.get('prompt', 'What detail should I use?')}")))

    if (intent is not None and intent.decision == "selected"
            and intent.dialogue_act in {"confirm", "reject"}
            and dialogue.open_dialogue_question is not None):
        dialogue.open_dialogue_question = None
        if intent.dialogue_act == "confirm":
            return with_intent(DialogueTurn(
                "social", text, text, text="Got it."))
        return with_intent(DialogueTurn(
            "clarify", text, text,
            text="Okay. What should I correct?"))

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
    recalled_slot = _session_slot_recall(text)
    if recalled_slot is not None and dialogue.pending_result is None:
        saved_slot = dialogue.session_slots.get(recalled_slot)
        # Do not let explanation or correction follow-ups attach this dialogue
        # answer to an older fact answer.
        dialogue.last_answered = None
        dialogue.last_question = None
        dialogue.last_selected_answer = None
        intent = UserIntentHypothesis(
            dialogue_act="question",
            task_intent="seek-information",
            decision="selected",
            matched_frame="session-slot-recall",
            context_predicates=((f"has_session_slot_{recalled_slot}",)
                                if saved_slot else ()),
            selected_value=None,
        )
        if saved_slot:
            reply = (f'The current saved {_SESSION_SLOT_LABELS[recalled_slot]} is '
                     f'“{saved_slot["value"]}”. ')
            if saved_slot.get("updated_by"):
                reply += f'You last supplied it as: “{saved_slot["updated_by"]}”. '
            reply += (f'The original question was: “{saved_slot["question"]}”. '
                      "This is session context, not a verified fact.")
        else:
            label = _SESSION_SLOT_LABELS[recalled_slot]
            reply = (f"I haven't saved a {label} from this conversation to recall.")
        return with_intent(DialogueTurn(
            "answered", text, text, text=reply))
    slot_correction = _session_slot_correction(text)
    if slot_correction is not None and dialogue.pending_result is None:
        slot, value = slot_correction
        label = _SESSION_SLOT_LABELS[slot]
        open_question = dialogue.open_dialogue_question
        answering_open_slot = bool(
            open_question is not None
            and open_question.get("expected_slot") == slot)
        saved_slot = dialogue.session_slots.get(slot)
        if answering_open_slot:
            dialogue.remember_session_slot(value, user_turn=text)
            dialogue.open_dialogue_question = None
            reply = f"Got it. I'll use “{value}” as your session-only {label}."
            decision = "selected"
            contexts = (f"awaiting_slot_{slot}",)
        elif saved_slot is not None:
            old_value = saved_slot["value"]
            saved_slot["value"] = value
            saved_slot["updated_by"] = " ".join(text.split())[:512]
            if dialogue.open_dialogue_question is not None:
                dialogue.open_dialogue_question = None
            reply = (f"Updated your session-only {label} from “{old_value}” "
                     f"to “{value}”.")
            decision = "selected"
            contexts = (f"has_session_slot_{slot}",)
        else:
            if dialogue.open_dialogue_question is not None:
                dialogue.open_dialogue_question = None
            reply = (f"I don't have a saved {label} to change. Give me that "
                     f"detail when I ask for it. {_SESSION_SLOT_QUESTIONS[slot]}")
            decision = "ambiguous"
            contexts = ()
        dialogue.last_answered = None
        dialogue.last_question = None
        dialogue.last_selected_answer = None
        intent = UserIntentHypothesis(
            dialogue_act="correction",
            task_intent=("correct-result" if decision == "selected"
                         else "resolve-ambiguity"),
            decision=decision,
            matched_frame="session-slot-correction",
            context_predicates=contexts,
            selected_value=value if decision == "selected" else None,
        )
        act = "correction"
        if (decision == "selected"
                and dialogue.active_task_intent == "make-reservation"
                and all(required in dialogue.session_slots
                        for required in _RESERVATION_DRAFT_SLOT_ORDER)):
            return with_intent(reservation_draft_prompt(text))
        return with_intent(DialogueTurn(
            "social" if decision == "selected" else "clarify",
            text, text, text=reply))
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
        if (dialogue.presented_sources and dialogue.last_question
                and dialogue.last_intent_hypothesis is not None
                and dialogue.last_intent_hypothesis.matched_frame
                    == "explicit-search-request"):
            sources = ", ".join(
                item.get("title", "source")
                for item in dialogue.presented_sources[:3])
            return with_intent(DialogueTurn(
                "sources_found", text, dialogue.last_question,
                text=(f"I showed those excerpts because they matched terms in "
                      f"your search. Sources: {sources}. They are quoted source "
                      "matches, not verified recommendations.")))
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
        if (intent is not None
                and intent.matched_frame == "explicit-search-request"):
            turn = _present_direct_search_matches(
                dialogue, turn, research_index)
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

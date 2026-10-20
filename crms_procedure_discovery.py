"""Review-only extraction of source-attested procedure phrase candidates.

This module identifies a narrow grammatical construction, not the operation
semantics. Candidates remain inert; a reviewer must establish what the source
means and align it with independently verified examples before teaching a
procedure.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


_PREDICATE_CLAUSE = re.compile(
    r"\b(?P<subject>(?:the\s+)?(?:following\s+)?"
    r"(?:(?:items?|elements?|records?|values?)\s+in\s+(?:the\s+)?array|"
    r"function|method|program|code|returned\s+array|array|output|result|"
    r"items?|elements?|records?|values?))"
    r"\s+will\s+(?P<polarity>not\s+)?"
    r"(?P<predicate>[a-z](?:\.(?=\d)|[^.!?;()]){1,180}?)"
    r"(?=(?:,?\s+(?:but|if|unless|when|provided\s+that|assuming)\b)"
    r"|[!?;()]|(?<!\d)\.(?!\d)|$)",
    re.IGNORECASE,
)
_QUOTES = (("\"", "\""), ("'", "'"), ("“", "”"), ("‘", "’"),
           ("«", "»"), ("`", "`"))


@dataclass(frozen=True)
class ProcedurePhraseCandidate:
    """One cited phrase candidate, deliberately not an accepted rule."""

    subject: str
    predicate_phrase: str
    polarity: bool
    quoted: bool
    source_citation: str
    source_sentence: str
    scope_notes: tuple[str, ...] = ()
    assertion_status: str = "asserted"
    status: str = "needs_review"


def _is_quoted(text: str, offset: int) -> bool:
    """Check whether offset lies inside a balanced quote, ignoring apostrophes."""
    opener_to_closer = dict(_QUOTES)
    closer_to_opener = {closer: opener for opener, closer in _QUOTES}
    stack: list[str] = []
    index = 0
    while index < min(offset, len(text)):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "'" and index > 0 and index + 1 < len(text):
            if text[index - 1].isalnum() and text[index + 1].isalnum():
                index += 1
                continue
        if stack and char == stack[-1]:
            stack.pop()
        elif not stack and char in opener_to_closer:
            stack.append(opener_to_closer[char])
        elif stack and char in closer_to_opener:
            # Mismatched nested quotation: fail closed as quoted.
            return True
        index += 1
    return bool(stack)


def _scope_notes(text: str, start: int, end: int) -> tuple[str, ...]:
    """Retain adjacent conditional language without deciding its scope."""
    prefix = re.split(r"[.!?]\s+", text[:start])[-1]
    suffix = text[end:]
    notes = []
    leading = re.search(
        r"\b(if|unless|assuming|provided\s+that)\b[^,]{1,160},\s*$",
        prefix, re.IGNORECASE)
    if leading:
        notes.append("before: " + " ".join(leading.group(0).split()).rstrip(", "))
    trailing = re.match(
        r"\s*\((?P<condition>[^)]{1,160})\)", suffix)
    if trailing:
        notes.append("after: " + " ".join(trailing.group("condition").split()))
    else:
        trailing = re.match(
            r"\s*,?\s*(?P<condition>(?:if|unless|only\s+if|only\s+when|"
            r"provided\s+that|as\s+long\s+as)\b[^.!?;]{1,160})",
            suffix, re.IGNORECASE)
        if trailing:
            notes.append("after: " + " ".join(trailing.group("condition").split()))
    return tuple(notes)


def _assertion_status(text: str, subject_start: int) -> str:
    """Flag a future clause embedded under denial or uncertainty."""
    prefix = re.split(r"[.!?]\s+", text[:subject_start])[-1]
    denied = re.search(
        r"\b(?:does\s+not|doesn't|did\s+not|didn't|cannot|can't|never)\s+"
        r"(?:guarantee|claim|assert|show|indicate|establish|prove|state|"
        r"promise)\b[^.!?]{0,140}$", prefix, re.IGNORECASE)
    no_support = re.search(
        r"\b(?:there\s+is\s+no|no)\s+(?:guarantee|evidence|proof|"
        r"indication)\s+that\b[^.!?]{0,140}$", prefix, re.IGNORECASE)
    uncertain = re.search(
        r"\b(?:unclear|uncertain|unknown)\s+whether\b[^.!?]{0,140}$",
        prefix, re.IGNORECASE)
    unverified = re.search(
        r"\b(?:has|have|had)\s+not\s+(?:verified|validated|proven|"
        r"shown|established|confirmed)\s+that\b[^.!?]{0,140}$",
        prefix, re.IGNORECASE)
    if denied or no_support:
        return "denied"
    if uncertain or unverified:
        return "uncertain"
    return "asserted"


def propose_procedure_phrase_candidates(
        sentence: str, *, source_citation: str
        ) -> tuple[ProcedurePhraseCandidate, ...]:
    """Extract source-backed ``<subject> will [not] <predicate>`` candidates.

    The extractor deliberately does not map phrases to operations, resolve
    semantic equivalence, or accept quoted/negative claims. Those distinctions
    remain visible to a reviewer. ``source_citation`` must identify an exact
    hashed span so evidence cannot be detached from the extracted sentence.
    """
    if not isinstance(sentence, str) or not sentence.strip():
        return ()
    if (not isinstance(source_citation, str)
            or "#sha256=" not in source_citation
            or "&chars=" not in source_citation):
        return ()
    match = _PREDICATE_CLAUSE.search(sentence)
    if match is None:
        return ()
    prefix = sentence[:match.start("subject")]
    if re.search(
            r"\b(?:[\w-]+\s+){1,4}(?:of|in|from|for|with|to)\s+"
            r"(?:the\s+)?$", prefix, re.IGNORECASE):
        # Avoid promoting the object of a preposition to subject, as in
        # "The length of the returned array will be N". The true subject
        # precedes "of"; the array itself is not said to be N.
        return ()
    predicate = " ".join(match.group("predicate").split()).strip(
        " \t\r\n,;:'\"“”‘’«»`")
    if len(predicate.split()) < 2:
        return ()
    return (ProcedurePhraseCandidate(
        subject=" ".join(match.group("subject").split()),
        predicate_phrase=predicate,
        polarity=not bool(match.group("polarity")),
        quoted=_is_quoted(sentence, match.start("predicate")),
        source_citation=source_citation,
        source_sentence=sentence,
        scope_notes=_scope_notes(
            sentence, match.start("subject"), match.end("predicate")),
        assertion_status=_assertion_status(sentence, match.start("subject")),
    ),)

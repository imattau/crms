"""Review-only extraction of source-attested procedure phrase candidates.

This module identifies a narrow grammatical construction, not the operation
semantics. Candidates remain inert; a reviewer must establish what the source
means and align it with independently verified examples before teaching a
procedure.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


_WILL_CLAUSE = re.compile(r"\bwill\s+(?P<negative>not\s+)?", re.IGNORECASE)
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


def _scope_notes(text: str, start: int, end: int,
                 leading_context: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Retain adjacent conditions and contrasts without interpreting them."""
    prefix = re.split(r"[.!?]\s+", text[:start])[-1]
    suffix = text[end:]
    notes = ["before: " + " ".join(item.split())
             for item in leading_context]
    leading = re.search(
        r"\b(if|unless|when|whenever|where|assuming|provided\s+that)"
        r"\b[^,]{1,180},\s*$",
        prefix, re.IGNORECASE)
    if leading and not leading_context:
        notes.append("before: " + " ".join(leading.group(0).split()).rstrip(", "))
    trailing = re.match(
        r"\s*\((?P<condition>[^)]{1,160})\)", suffix)
    if trailing:
        note = " ".join(trailing.group("condition").split())
        label = ("after: " if re.match(
            r"(?:if|unless|when|only\s+if|only\s+when|provided\s+that)",
            note, re.IGNORECASE) else "after-note: ")
        notes.append(label + note)
    else:
        trailing = re.match(
            r"\s*,?\s*(?P<condition>(?:if|unless|only\s+if|only\s+when|"
            r"when|provided\s+that|as\s+long\s+as|but|otherwise|"
            r"and\s+will(?:\s+not)?)"
            r"\b[^.!?;]{1,180})",
            suffix, re.IGNORECASE)
        if trailing:
            notes.append("after: " + " ".join(trailing.group("condition").split()))
    return tuple(notes)


def _subject_start(text: str, will_start: int
                   ) -> tuple[int, str, tuple[str, ...]] | None:
    """Return a broad source subject, separating explicit leading context.

    Unlike the previous entity whitelist, this retains full noun phrases and
    allows parameter names, qualified values, and other technical subjects.
    It fails closed on empty or excessively long prefixes.
    """
    prefix_start = 0
    prefix = text[:will_start]
    # A source sentence may contain several list bullets. The last bullet is
    # the local clause boundary, so a neighboring bullet cannot become subject.
    bullets = list(re.finditer(r"(?:,|;)\s*(?:\*|[-•])\s*", prefix))
    if bullets:
        prefix_start = bullets[-1].end()
        prefix = text[prefix_start:will_start]

    context: list[str] = []
    # A contrastive finite clause has its own subject. Keep its antecedent as
    # scope and bind the claim only to the clause after the coordinator.
    contrasts = list(re.finditer(
        r",\s*(?P<marker>(?:and\s+)?(?:but|however|whereas|while|"
        r"similarly|likewise))\s+", prefix, re.IGNORECASE))
    if contrasts:
        contrast = contrasts[-1]
        antecedent = " ".join(prefix[:contrast.start()].split())
        marker = contrast.group("marker").casefold()
        if antecedent:
            context.append(f"contrast ({marker}): {antecedent}")
        prefix_start += contrast.end()
        prefix = text[prefix_start:will_start]

    prefix = prefix.lstrip(" \t\r\n(*•-")
    prefix_start = will_start - len(text[prefix_start:will_start].lstrip(
        " \t\r\n(*•-"))

    # Sphinx/reStructuredText API docs put a parameter declaration directly
    # before its description. Keep the named parameter as the subject instead
    # of absorbing the type/option metadata into it.
    parameter = re.match(
        r"(?P<name>[A-Za-z_][\w]*)\s*:\s*(?P<type>[^,]{1,50}),\s*"
        r"optional\s+(?P<description>.+)$", prefix, re.IGNORECASE)
    if parameter:
        name_start = prefix_start + parameter.start("name")
        return (name_start, f"the {parameter.group('name')} parameter",
                (f"parameter type/option: {parameter.group('type').strip()}, optional",))

    leading = re.match(
        r"(?P<context>(?:note\s+that\s+)?(?:if|unless|when|whenever|assuming|provided\s+that|"
        r"at\s+(?:the\s+)?locations?\s+where|elsewhere|otherwise|"
        r"for\s+each\b)[\s\S]{0,400})"
        r"(?:,\s*(?:then\s+)?|\s+then\s+)(?P<subject>[\s\S]+?)\s*$",
        prefix, re.IGNORECASE)
    if leading:
        context.append(leading.group("context").strip().rstrip(",;:"))
        subject = leading.group("subject").strip()
        subject_start = prefix_start + leading.start("subject")
    else:
        deictic_condition = re.match(
            r"(?P<context>(?:note\s+that\s+)?(?:if|unless|when|whenever|"
            r"assuming|provided\s+that)\b[\s\S]*\s+)"
            r"(?P<subject>this|that|it|they|these|those)$",
            prefix, re.IGNORECASE)
        if deictic_condition:
            context.append(deictic_condition.group("context").strip())
            subject = deictic_condition.group("subject")
            subject_start = prefix_start + deictic_condition.start("subject")
        else:
            discourse = re.match(
                r"(?P<context>(?:currently|generally|typically|usually|"
                r"by\s+default|in\s+general|in\s+practice|for\s+example)"
                r"\b[^,]{0,100}),\s*"
                r"(?P<subject>[\s\S]+?)\s*$", prefix, re.IGNORECASE)
            if discourse:
                context.append(discourse.group("context").strip())
                subject = discourse.group("subject").strip()
                subject_start = prefix_start + discourse.start("subject")
            else:
                if re.search(r"\b(?:otherwise|else|and|but)\s*$", prefix,
                             re.IGNORECASE):
                    # An omitted subject cannot be licensed from lexical
                    # support in another sentence. Do not turn a connective
                    # into the subject.
                    return None
                subject = prefix.strip()
                subject_start = prefix_start + len(prefix) - len(prefix.lstrip())

    subject = subject.strip(" \t\r\n,;:")
    if not subject or len(subject) > 180:
        return None
    if not re.search(r"[A-Za-z\u0080-\uffff]", subject):
        return None
    return subject_start, subject, tuple(context)


def _predicate_end(text: str, start: int) -> int | None:
    """Find a predicate boundary while preserving balanced inline literals."""
    index = start
    paren_depth = 0
    while index < len(text):
        if text[index] == "`":
            run_end = index + 1
            while run_end < len(text) and text[run_end] == "`":
                run_end += 1
            marker = text[index:run_end]
            close = text.find(marker, run_end)
            if close < 0:
                return None
            index = close + len(marker)
            continue
        character = text[index]
        if character == "(":
            # Parenthetical citations, conditions, and side notes belong in
            # scope metadata rather than the main predicate. Keep ordinary
            # parenthesized values such as shapes and argument expressions.
            if re.match(
                    r"\(\s*(?:see\b|e\.g\.|i\.e\.|if\b|unless\b|"
                    r"when\b|only\s+if\b|note\b)",
                    text[index:], re.IGNORECASE):
                return index
            paren_depth += 1
            index += 1
            continue
        if character == ")" and paren_depth:
            paren_depth -= 1
            index += 1
            continue
        if paren_depth:
            index += 1
            continue
        if character in "!?;":
            return index
        if character == ".":
            previous_is_digit = index > start and text[index - 1].isdigit()
            next_is_digit = index + 1 < len(text) and text[index + 1].isdigit()
            if previous_is_digit and next_is_digit:
                index += 1
                continue
            return index
        if character == "," and re.match(r",\s*\*\s+", text[index:]):
            return index
        if character == "," and re.match(
                r",\s*(?:and\s+)?(?:but|otherwise|if|unless|when|provided\s+that|"
                r"assuming)\b", text[index:], re.IGNORECASE):
            return index
        if re.match(r"\s+(?:and|but)\s+will\b", text[index:], re.IGNORECASE):
            return index
        if re.match(
                r"\s+(?:if|unless|only\s+if|only\s+when|provided\s+that|"
                r"as\s+long\s+as)\b", text[index:], re.IGNORECASE):
            return index
        index += 1
    return len(text) if paren_depth == 0 else None


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

    This boundary pass preserves the full source subject and local scope rather
    than selecting from a fixed noun list. It does not parse operation
    semantics, align phrases, or accept candidates. ``source_citation`` must
    identify an exact hashed span so evidence cannot be detached from its
    sentence. Ambiguous structures remain review-only.
    """
    if not isinstance(sentence, str) or not sentence.strip():
        return ()
    if (not isinstance(source_citation, str)
            or "#sha256=" not in source_citation
            or "&chars=" not in source_citation):
        return ()
    matches = list(_WILL_CLAUSE.finditer(sentence))
    if not matches:
        return ()
    candidates = []
    for position, match in enumerate(matches):
        if position:
            between = sentence[matches[position - 1].end():match.start()]
            if not re.search(r",\s*\*\s+", between):
                # Keep coordinated/contrastive clauses attached as scope to
                # the first claim until their implicit subject is resolved.
                continue
        subject = _subject_start(sentence, match.start())
        if subject is None:
            continue
        subject_start, subject_phrase, leading_context = subject
        predicate_start = match.end()
        predicate_end = _predicate_end(sentence, predicate_start)
        if predicate_end is None:
            continue
        predicate = " ".join(
            sentence[predicate_start:predicate_end].split()).strip(
                " \t\r\n,;:")
        if not predicate or (predicate.casefold() == "be"):
            continue
        candidates.append(ProcedurePhraseCandidate(
            subject=" ".join(subject_phrase.split()),
            predicate_phrase=predicate,
            polarity=not bool(match.group("negative")),
            quoted=_is_quoted(sentence, predicate_start),
            source_citation=source_citation,
            source_sentence=sentence,
            scope_notes=_scope_notes(sentence, subject_start, predicate_end,
                                     leading_context),
            assertion_status=_assertion_status(sentence, match.start()),
        ))
    return tuple(candidates)

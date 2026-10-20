"""Optional dependency-parse proposal generator for source procedure claims.

The caller supplies a spaCy-compatible parser so the CRMS runtime does not
require spaCy or a language model. Results are review-only and retain the
complete source sentence citation. This prototype does not infer operation
semantics or accept claims.
"""
from __future__ import annotations

import re
from typing import Any

from crms_procedure_discovery import (
    ProcedurePhraseCandidate,
    _assertion_status,
    _is_quoted,
)


_CONDITION_WORDS = {
    "if", "unless", "when", "whenever", "provided", "assuming",
}
_LEADING_CONTEXT = re.compile(
    r"^\s*(?P<scope>(?:if|unless|when|whenever|provided\s+that)"
    r"\b[^,]{1,100}|by\s+default|generally|typically|usually|"
    r"in\s+general|in\s+practice|in\s+this\s+case|for\s+example)"
    r"\s*,?\s+",
    re.IGNORECASE)


def _source_span(source_text: str, tokens: list[Any]) -> str:
    """Return the exact source span covered by a dependency subtree."""
    if not tokens:
        return ""
    start = min(token.idx for token in tokens)
    end = max(token.idx + len(token.text) for token in tokens)
    return source_text[start:end].strip()


def _subject_roots(predicate: Any) -> tuple[list[Any], bool]:
    subjects = [child for child in predicate.children
                if child.dep_ in {"nsubj", "nsubjpass", "csubj", "csubjpass"}]
    if subjects:
        return subjects, False
    if predicate.dep_ == "conj":
        subjects = [child for child in predicate.head.children
                    if child.dep_ in {"nsubj", "nsubjpass", "csubj", "csubjpass"}]
        if subjects:
            return subjects, True
    return [], False


def _condition_roots(predicate: Any) -> list[Any]:
    conditions = []
    for child in predicate.children:
        if child.dep_ != "advcl":
            continue
        words = {token.lower_ for token in child.subtree}
        if words & _CONDITION_WORDS:
            conditions.append(child)
    return conditions


def _proposal_for_will(doc: Any, source_text: str, will_token: Any,
                       source_citation: str
                       ) -> ProcedurePhraseCandidate | None:
    predicate = will_token.head
    if predicate.pos_ not in {"VERB", "AUX"}:
        return None
    leading_context = _LEADING_CONTEXT.match(source_text)
    if (leading_context is not None
            and leading_context.end() > will_token.idx):
        leading_context = None
    subjects, inherited = _subject_roots(predicate)
    conditions = _condition_roots(predicate)
    # Parsers can attach an elliptical condition (for example, "If None") as
    # a second subject. Keep its clause as scope and retain the actual subject.
    for subject in list(subjects):
        subtree = list(subject.subtree)
        if {token.lower_ for token in subtree} & _CONDITION_WORDS:
            conditions.append(subject)
            subjects.remove(subject)
    subjects = [subject for subject in subjects
                if subject.pos_ in {"NOUN", "PROPN", "PRON", "VERB", "X"}]
    subject_tokens = [token for subject in subjects for token in subject.subtree]
    subject_phrase = _source_span(source_text, subject_tokens)
    if leading_context is not None:
        # The explicit source prefix is a safer boundary than a parser subtree
        # when it attaches an elliptical condition to the grammatical subject.
        subject_phrase = source_text[leading_context.end():will_token.idx].strip(
            " \t\r\n,;:")
        scope_kind = ("condition" if leading_context.group("scope").casefold().startswith(
            ("if", "unless", "when", "whenever", "provided")) else "context")
        scope_note = (scope_kind + ": "
                      + leading_context.group("scope").strip().rstrip(","))
        if scope_kind == "condition":
            conditions.append(leading_context)
    if not subjects and leading_context is None:
        # Do not bind a source claim to a guessed entity or parameter.
        return None
    if not subject_phrase:
        return None
    predicate_end = max(token.idx + len(token.text)
                        for token in predicate.subtree)
    trailing_conditions = [root for root in conditions
                           if hasattr(root, "subtree")
                           and min(token.idx for token in root.subtree)
                           > will_token.idx]
    if trailing_conditions:
        predicate_end = min(predicate_end, min(
            min(token.idx for token in root.subtree)
            for root in trailing_conditions))
    predicate_phrase = source_text[will_token.idx:predicate_end].strip()
    if not predicate_phrase:
        return None

    notes = ["condition: " + _source_span(source_text, list(root.subtree))
             for root in conditions if hasattr(root, "subtree")]
    if leading_context is not None and scope_note not in notes:
        notes.append(scope_note)

    if inherited:
        notes.append("shared subject inherited from coordinated clause")
    return ProcedurePhraseCandidate(
        subject=" ".join(subject_phrase.split()),
        predicate_phrase=" ".join(predicate_phrase.split()),
        polarity=not any(token.dep_ == "neg"
                         for token in predicate.children),
        quoted=_is_quoted(source_text, will_token.idx),
        source_citation=source_citation,
        source_sentence=source_text,
        scope_notes=tuple(notes),
        assertion_status=_assertion_status(source_text, will_token.idx),
        status="needs_review",
    )


def propose_dependency_procedure_phrase_candidates(
        parser: Any, sentence: str, *, source_citation: str
        ) -> tuple[ProcedurePhraseCandidate, ...]:
    """Extract claims with an injected dependency parser, never auto-promote.

    The parser must expose spaCy-style tokens (``text``, ``text_with_ws``,
    ``idx``, ``pos_``, ``dep_``, ``head``, ``children``, and ``subtree``).
    Passing an invalid citation or malformed input returns no candidates.
    """
    if (not isinstance(sentence, str) or not sentence.strip()
            or not isinstance(source_citation, str)
            or "#sha256=" not in source_citation
            or "&chars=" not in source_citation):
        return ()
    try:
        # Strip Markdown backticks only for parsing. Replacing them with spaces
        # preserves offsets so extracted spans still point into exact source.
        parser_text = re.sub(r"`", " ", sentence)
        doc = parser(parser_text)
    except Exception:
        return ()
    candidates = []
    for token in doc:
        if token.lower_ != "will" or token.pos_ != "AUX":
            continue
        candidate = _proposal_for_will(doc, sentence, token, source_citation)
        if candidate is not None:
            candidates.append(candidate)
    # Preserve repeated clauses only when their structured claims differ.
    unique = {}
    for candidate in candidates:
        key = (candidate.subject, candidate.predicate_phrase,
               candidate.polarity, candidate.scope_notes)
        unique.setdefault(key, candidate)
    return tuple(unique.values())

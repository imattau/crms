"""Pattern-based faithfulness checks for composed text (Phase 11).

Three deterministic checks over the final text and the request's facts:
numbers (every number was stated by a fact), polarity (negation is neither
dropped nor invented), and names (capitalised names inside a sentence come from
the facts). They complement the span-level evidence check; they do not replace it.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from crms_patterns import PatternLanguage, sentence_spans as _sentence_spans, tokenize

_NEGATIONS = frozenset({"not", "no", "never", "cannot", "without", "neither", "nor"})
_ALLOWED_NAMES = frozenset({"i"})


def _is_negation(word: str) -> bool:
    return word in _NEGATIONS or word.endswith("n't") or word.endswith("n’t")


def _fact_text(fact) -> str:
    return " ".join(part for part in (fact.subject, fact.verb, fact.object,
                                      fact.complement, fact.source_text) if part)


def _numbers(text: str, language: PatternLanguage) -> set[str]:
    return {t.text.replace(",", "") for t in tokenize(text, language) if t.kind == "NUM"}


def check_generated(text: str, facts: Sequence, language: PatternLanguage,
                    extra_sources: Iterable[str] = ()) -> list[str]:
    issues: list[str] = []
    if not text.strip():
        return issues
    support = " ".join([_fact_text(f) for f in facts] + list(extra_sources))
    support_tokens = tokenize(support, language)
    allowed_numbers = {t.text.replace(",", "") for t in support_tokens if t.kind == "NUM"}
    allowed_names = {t.low for t in support_tokens if t.kind == "CAP"}

    tokens = tokenize(text, language)
    invented = sorted({t.text.replace(",", "") for t in tokens if t.kind == "NUM"} - allowed_numbers)
    if invented:
        issues.append("number not stated by any fact: " + ", ".join(invented))

    fact_negated = any(_is_negation(t.low) for t in support_tokens)
    text_negated = any(_is_negation(t.low) for t in tokens)
    if fact_negated and not text_negated:
        issues.append("polarity: a negated statement was written without negation")
    if text_negated and not fact_negated:
        issues.append("polarity: negation appears but no fact is negated")

    sentence_starts = {0}
    for a, _b in _sentence_spans(text):
        for i, token in enumerate(tokens):
            if token.start >= a:
                sentence_starts.add(i)
                break
    unsupported = []
    for i, token in enumerate(tokens):
        if token.kind != "CAP" or i in sentence_starts or token.low in _ALLOWED_NAMES:
            continue
        if token.low not in allowed_names and token.low not in {t.low for t in support_tokens}:
            unsupported.append(token.text)
    if unsupported:
        issues.append("name not found in any fact: " + ", ".join(sorted(set(unsupported))))
    return issues


def check_role_order(text: str, facts: Sequence, language: PatternLanguage) -> list[str]:
    """For an active fact (subject, verb, object) a sentence naming both must put
    the subject first, unless it is passive ("by")."""
    issues: list[str] = []
    for fact in facts:
        if not (fact.subject.strip() and fact.object.strip() and fact.verb.strip()):
            continue
        subject = [t.low for t in tokenize(fact.subject, language)]
        obj = [t.low for t in tokenize(fact.object, language)]
        for a, b in _sentence_spans(text):
            tokens = tokenize(text[a:b], language)
            words = [t.low for t in tokens]
            si = _find(words, subject)
            oi = _find(words, obj)
            if si is None or oi is None or si < oi:
                continue
            if "by" in words[oi:si]:
                continue    # passive: "Y was written by X"
            issues.append(f"role order: {fact.object!r} comes before {fact.subject!r}")
            break
    return issues


def _find(words: Sequence[str], needle: Sequence[str]) -> int | None:
    n = len(needle)
    for i in range(len(words) - n + 1):
        if list(words[i:i + n]) == list(needle):
            return i
    return None

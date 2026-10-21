"""Pattern-based faithfulness checks for composed text (Phase 11).

Three deterministic checks over the final text and the request's facts:
numbers (every number was stated by a fact), polarity (negation is neither
dropped nor invented), and names (capitalised names inside a sentence come from
the facts). They complement the span-level evidence check; they do not replace it.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

from crms_patterns import PatternLanguage, tokenize

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
    for i, token in enumerate(tokens):
        if token.text in (".", "!", "?") or (i and tokens[i - 1].text in (".", "!", "?")):
            sentence_starts.add(i + 1)
    # sentence boundaries by terminal punctuation in the original text
    for m in re.finditer(r"[.!?]\s+", text):
        for i, token in enumerate(tokens):
            if token.start >= m.end():
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

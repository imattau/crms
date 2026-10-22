"""Corpus-driven verb induction for the pattern language (Phase 12 coverage program).

The pattern layer binds a question's verb to a sentence only for verbs it knows
(the seed lists 43). A regular verb is added when the corpus itself shows its
paradigm: the base form, a third-person form and a past form all occur, and the
past form is used as a passive participle (after a copula and before "by") often
enough that it cannot be a bare noun or adjective. Irregular verbs need the
paradigm table and are not guessed. Candidates are proposals: the caller measures
them against the control bank before keeping them (`grow` returns them ranked).
"""
from __future__ import annotations

import collections
from typing import Iterable, Mapping, Sequence

from crms_intent_rules import words

_COPULAS = frozenset({"is", "are", "was", "were", "been", "be", "being"})
_STOP = frozenset({"the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "with",
                   "by", "from", "as", "that", "this", "it", "he", "she", "they", "his", "her"})


def count_forms(texts: Iterable[str]) -> tuple[collections.Counter, collections.Counter]:
    """(word frequencies, passive-participle frequencies: copula + word + 'by')."""
    freq: collections.Counter = collections.Counter()
    passive: collections.Counter = collections.Counter()
    for text in texts:
        tokens = words(text)
        freq.update(tokens)
        for a, b, c in zip(tokens, tokens[1:], tokens[2:]):
            if a in _COPULAS and c == "by":
                passive[b] += 1
    return freq, passive


def paradigm(lemma: str) -> tuple[str, str, str, str]:
    """Regular base, third-person, past, participle spellings for a lemma."""
    if lemma.endswith("e"):
        past = lemma + "d"
        s3 = lemma + "s"
    elif lemma.endswith("y") and lemma[-2:-1] not in "aeiou":
        past = lemma[:-1] + "ied"
        s3 = lemma[:-1] + "ies"
    elif lemma.endswith(("s", "sh", "ch", "x", "z")):
        past, s3 = lemma + "ed", lemma + "es"
    else:
        past, s3 = lemma + "ed", lemma + "s"
    return lemma, s3, past, past


def candidates(freq: Mapping[str, int], passive: Mapping[str, int], known: Iterable[str], *,
               min_passive: int = 3) -> list[dict]:
    """Regular verbs whose paradigm and passive use the corpus attests."""
    known_forms = set(known)
    out = []
    for word, count in passive.items():
        if count < min_passive or word in _STOP or not word.endswith(("ed", "ied")):
            continue
        stems = {word[:-2], word[:-1], word[:-3] + "y" if word.endswith("ied") else word[:-2]}
        best = None
        for lemma in sorted(stems):
            if len(lemma) < 3 or lemma in known_forms or lemma in _STOP:
                continue
            forms = paradigm(lemma)
            if forms[2] != word:
                continue
            support = freq.get(forms[0], 0) + freq.get(forms[1], 0)
            if freq.get(forms[0], 0) >= 2 and freq.get(forms[1], 0) >= 1 and (best is None or support > best[0]):
                best = (support, lemma, forms)      # the spelling the corpus actually uses
        if best:
            _support, lemma, forms = best
            out.append({"lemma": lemma, "forms": list(forms), "passive": count,
                        "base_freq": freq.get(forms[0], 0), "s3_freq": freq.get(forms[1], 0)})
    out.sort(key=lambda c: (-c["passive"], c["lemma"]))
    return out


def grow(texts: Iterable[str], known_verbs: Mapping[str, Sequence[str]], *, limit: int = 60,
         min_passive: int = 3) -> list[dict]:
    freq, passive = count_forms(texts)
    known = {form for forms in known_verbs.values() for form in forms}
    return candidates(freq, passive, known, min_passive=min_passive)[:limit]

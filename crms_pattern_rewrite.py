"""Pattern-based text rewriting and phrase detection (Phase 11, generation layer).

Replaces regex whole-word substitution in the clarity pass. Matching runs over
tokens, so "prior to" never matches inside another word, a verb rule covers
every inflection (utilize, utilizes, utilized, utilizing -> use, uses, used,
using), and the capital letter of a replaced word is kept.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from crms_patterns import PatternLanguage, Token, tokenize


@dataclass(frozen=True)
class Rewrite:
    kind: str       # "phrase" or "verb"
    source: str
    target: str


def _kind_of(language: PatternLanguage, lemma: str, token: Token) -> str | None:
    forms = language.forms(lemma)
    low = token.low
    for kind in ("part", "past", "s3", "base"):
        if low == forms[kind]:
            return kind
    if low in forms["ing"]:
        return "ing"
    return None


def _inflect(language: PatternLanguage, lemma: str, kind: str) -> str:
    forms = language.forms(lemma)
    if kind != "ing":
        return forms[kind]
    base = forms["base"]
    candidates = sorted(forms["ing"])
    # prefer the regular spelling: drop a final e, otherwise append "ing"
    regular = (base[:-1] if base.endswith("e") else base) + "ing"
    return regular if regular in candidates else candidates[0]


def _match_phrase(tokens: Sequence[Token], words: Sequence[str], start: int) -> int:
    end = start + len(words)
    if end > len(tokens):
        return 0
    return len(words) if all(tokens[start + i].low == words[i] for i in range(len(words))) else 0


class PatternRewriter:
    def __init__(self, language: PatternLanguage, rules: Sequence[Rewrite]) -> None:
        self.language = language
        self.phrases = [(tuple(tokenize(r.source, language)), r) for r in rules if r.kind == "phrase"]
        self.phrases = [([t.low for t in toks], r) for toks, r in self.phrases]
        self.phrases.sort(key=lambda item: -len(item[0]))
        self.verbs = {r.source: r.target for r in rules if r.kind == "verb"}

    def _matches(self, text: str) -> list[tuple[int, int, str]]:
        tokens = tokenize(text, self.language)
        found: list[tuple[int, int, str]] = []
        taken = [False] * len(tokens)
        for words, rule in self.phrases:
            for i in range(len(tokens)):
                if taken[i] or not _match_phrase(tokens, words, i):
                    continue
                if any(taken[i:i + len(words)]):
                    continue
                for k in range(i, i + len(words)):
                    taken[k] = True
                found.append((tokens[i].start, tokens[i + len(words) - 1].end, rule.target))
        for i, token in enumerate(tokens):
            if taken[i]:
                continue
            for lemma in self.language.lemmas(token):
                target = self.verbs.get(lemma)
                if target is None or target not in self.language.verbs:
                    continue
                kind = _kind_of(self.language, lemma, token)
                if kind is None:
                    continue
                found.append((token.start, token.end, _inflect(self.language, target, kind)))
                taken[i] = True
                break
        return sorted(found)

    def rewrite(self, text: str) -> str:
        out = text
        for start, end, replacement in reversed(self._matches(text)):
            if text[start:start + 1].isupper():
                replacement = replacement[:1].upper() + replacement[1:]
            out = out[:start] + replacement + out[end:]
        return out

    def contains(self, text: str, term: str) -> bool:
        """True when a phrase occurs as whole tokens, or an inflection of a verb term."""
        tokens = tokenize(text, self.language)
        words = [t.low for t in tokenize(term, self.language)]
        if not words:
            return False
        for i in range(len(tokens)):
            if _match_phrase(tokens, words, i):
                return True
        if len(words) == 1:
            for lemma in self.language.verbs:
                if words[0] in self.language.forms(lemma)["any"]:
                    if any(lemma in self.language.lemmas(t) for t in tokens):
                        return True
        return False
